# Parallelization Strategy — canvodpy Performance Redesign

Branch: `explore/performance-review` · Date: 2026-07-02 · Status: **DRAFT — plan only**

Sources: `perf_audit.md` (Fable code audit §1–7), `perf_web_research.md` (Sonnet web research),
`icechunk_v2_metadata.md` (Sonnet Icechunk v2 research). All research complete 2026-07-02.

---

## Core constraints (non-negotiable)

1. **Sequential writes, local FS**: Icechunk on local filesystem cannot take concurrent commits.
   One writer at a time, single `session.commit()` per receiver-day.
2. **One file per worker**: unit of parallelism stays at the file level. Readers
   (`SbfReader.to_ds()`, `Rnxv3Obs.to_ds()`) are single-threaded per file and must not change.
3. **Store dedup guardrails preserved**: three-layer dedup (hash + temporal overlap + intra-batch)
   must pass `test_store_guardrails.py` after any write-path change.
4. **Future S3 path**: design the write interface so the sequential-local path and the future
   fork/merge concurrent-S3 path share the same worker API surface.

---

## Write ordering: does it matter?

**Short answer: no for correctness, no for the planned implementation either.**

### Why it does not matter at the data level

`epoch` is a coordinate dimension in the `(epoch, sid)` Dataset — not a log with implicit
position semantics. Reading back from the store with `.sortby("epoch")` produces a correctly
ordered result regardless of write order. Out-of-order writes are **not a correctness problem**.

What *is* a correctness problem: **duplicate epochs**. If the same time range is written twice,
the epoch coordinate appears twice with different data. This is what the three-layer dedup
guards against — and must continue to do so.

### Current `append_dim` usage

`append_dim="epoch"` appears in 14 places across the codebase:
- `processor.py:498, 1945, 1956, 1967` — main write path and fork worker
- `store.py:963, 1124, 1337, 1439` — `append_to_group()`, `append_metadata_datasets()`, etc.
- `store/reader.py:421, 431, 615, 630`, `manager.py:658` — VOD and other writes

`append_to_group()` (store.py:1288) opens its **own session per call** and commits inside the
method — one file = one session = one commit. This is correct for the public API but too fine-
grained for batch ingestion (should be one commit per receiver-day, not per file).

`_append_to_icechunk` in processor.py writes multiple files inside **one shared session**
using `append_dim` sequentially — this is the right granularity, but still requires ordered input.

### `region="auto"` is already implemented

`worker_task_with_region_auto` (processor.py:505) already exists:

```python
ds_clean.to_zarr(
    fork.store,
    group=receiver_name,
    mode="a",
    region="auto",   # xarray infers position from epoch coordinates
    consolidated=False,
)
return fork
```

This uses `region="auto"` inside an Icechunk `ForkSession` — xarray matches the incoming
dataset's epoch coordinates to the pre-allocated store and writes to the correct position.
Workers complete and write in **any order**. The driver merges forks and commits once.

This is the preferred path forward. `append_dim` is not necessary.

---

## Priority order (Fable recommendation — do these in sequence)

**Before any parallelism machinery, fix the two biggest levers:**

1. **Fix SBF decode hot loop** — vectorize obs scaling (numpy, not pint per-value),
   drop `SbfSignalObs` Pydantic instantiation from the hot path, fold `_freq_nr_cache`
   into the main parse pass (eliminating the second full parse), chunk `file_hash` SHA-256
   (eliminating the third full file read). Expected: ≥10× on single-file SBF latency.

2. **SID universe size** — `pad_to_global_sid` expands every dataset to 3,658 SIDs
   (all theoretically possible SV × Band × Code combinations across all constellations).
   For a 24h SBF file this creates 316M cells/var (~7.9 GB) vs ~155 MB for observed SIDs
   only — a **40× multiplier**. This padding is **intentional and necessary**: without a
   shared SID axis, datasets from different files cannot be aligned for VOD computation.
   "Pad later" is not viable — a single file cannot know the full universe.
   Three paths to reduce the cost, in order of feasibility:
   **Phase 0 (W7 + W9) answered 2026-07-02:**
   - **W7**: `keep_sids` is NOT set by default. `mode: all` ships as the default → full
     3,658 SIDs every time. `mode: preset` is a **silent no-op** (`_get_preset_sids` is a
     TODO returning `[]`). Only `mode: custom` with an explicit list actually filters.
     The 40× is real in all default deployments. L1 API doesn't plumb `keep_sids` at all.
   - **W9 verdict: GO — moderate refactor, one concentrated choke point.**
     Pipeline is far more ragged-ready than expected: VOD already uses `xr.align(join="inner")`
     (`calculator.py:141-145`), augmentation already does label-based inner join on SIDs
     (`processor.py:252-272`), zero positional `isel(sid=N)` indexing anywhere, readers
     already have `pad_global_sid=False` kwarg at every call site. **One load-bearing
     assumption**: fixed sid axis for Zarr epoch-appends. Different-size sid on append =
     hard error. Same-size-different-SIDs = **silent positional misalignment** (no error,
     wrong data). Appears in three places: SNR store, VOD store, sbf_obs appends.
   - **Key insight**: "ragged in pipeline" and "fixed axis in store" are separable.
     Move padding from reader to write boundary → workers hold ~155 MB, not ~7.9 GB.
   - **Minimum change set** (~20 lines total):
     1. `pad_global_sid=False` in orchestrator path (kwarg already exists in all readers)
     2. `ds.reindex(sid=store_axis, fill_value=np.nan)` immediately before `to_icechunk`
        in `_append_to_icechunk` and `write_or_append_group`
     3. Union-SID skeleton in existing pre-scan for the `region="auto"` path
        (`processor.py:3061-3074`)
     4. Two intersection guards on `.sel(sid=list)` in `grids/aggregation.py:82-83, 237`
   - **Quick independent win** — make `mode: all` authoritative instead of enumerating all
     theoretical combinations. Both inputs are already in the codebase:
     `SatelliteCatalog.active_prns(on_date)` (bundled SINEX file) × RINEX v3.04 spec-valid
     Band×Code per constellation (already in `SYSTEM_BANDS` / `BAND_CODES`). Cross-product
     gives ~321 SIDs derived from authoritative sources, zero user configuration, auto-updates
     as the SINEX catalog is refreshed. Drop `mode: preset` (was always a placeholder for this
     idea). Revised `SidsConfig` has two modes: `all` (SINEX×spec, ~321) and `custom`
     (explicit list for site-specific narrowing). Collapses 42× → ~3.7× with no architectural
     change to the pipeline.

**Then the pooling and write path:**

3. **Long-lived ProcessPool, both formats** (§Pool design below)
4. **Pre-scan + SBF splitting** for large files (§SBF intra-file splitting)
5. **Streaming single-writer behind `WriteStrategy`** (§Streaming write pipeline)

---

## Pool design

### Replace Dask LocalCluster with long-lived ProcessPoolExecutor

**Decision: drop Dask as the default executor.**

Rationale:
- Dask LocalCluster adds ~1 ms/task TCP round-trip overhead — negligible for tasks >1 s, but
  adds complexity and a dashboard dependency users neither need nor understand.
- Dask's scheduler value (work-stealing, DAG dependencies, diagnostics) provides no benefit
  for a linear read→process→write pipeline.
- A long-lived `ProcessPoolExecutor` is simpler, lower overhead, and sufficient.

**Long-lived pool (critical):** create ONE `ProcessPoolExecutor` at `PipelineOrchestrator`
startup. Reuse across all batches. The current implementation creates a fresh pool per
receiver-day (processor.py:1448), incurring 0.5–2 s spawn cost per worker per day for the
full scientific stack (numpy + xarray + zarr + icechunk imports). On a 96-day backlog run
with 8 workers, this is 96 × 8 × ~1 s = ~13 minutes of pure overhead.

Use `initializer=` to preload heavy imports once per worker at pool creation:
```python
def _worker_init():
    import numpy as np
    import xarray as xr
    import zarr
    # ephemeris lookup tables that are shared read-only across tasks
    # (or use MPIRE for copy-on-write sharing — see below)

pool = ProcessPoolExecutor(max_workers=n, initializer=_worker_init)
```

### Two-stream pool (GIL-aware)

| Stream | Format | Executor | Rationale |
|---|---|---|---|
| Stream 1 | RINEX / text | `ProcessPoolExecutor` | **Confirmed CPU-bound** — pure-Python string slicing; ThreadPool serializes under GIL. Processes required. |
| Stream 2 | SBF / binary | `ProcessPoolExecutor` | CPU-bound binary parsing; processes give true parallelism under GIL |
| Both | Any | `ThreadPoolExecutor` | Only if `sys._is_gil_enabled()` returns `False` (3.14t opt-in) |

Both streams share one long-lived pool. Suggested worker split for mixed sites:
- SBF stream: `max(1, budget - 1)` workers (CPU-heavy)
- RINEX stream: `min(budget, 2)` workers (I/O-lighter; slight oversubscription acceptable)

### MPIRE: an alternative worth evaluating

MPIRE (pip-installable, MIT) wraps `ProcessPoolExecutor` with **copy-on-write shared objects**
via `fork`. This is directly relevant: `preprocess_with_hermite_aux` loads SP3/CLK ephemeris
data per task. With MPIRE, the ephemeris table can be loaded once in the parent process and
shared across all workers at zero serialization cost. Benchmark against plain
`ProcessPoolExecutor` before committing.

---

## Eliminating pickle IPC cost (workers → driver)

**Problem**: workers currently return full `xr.Dataset` objects across the process boundary.
For a 24h SBF file, this is hundreds of MB pickled twice (worker → driver pipe → Icechunk).
For 15-min files (~10 MB per dataset), pickle is acceptable. For 24h files, it is not.

**Strategy: worker writes to temp Zarr, returns path**

```python
# in the worker function (preprocess_with_hermite_aux or wrapper):
import tempfile, zarr
tmp_path = Path(tempfile.mkdtemp()) / "result.zarr"
augmented_ds.to_zarr(tmp_path)
return (fname, tmp_path, aux_metadata)  # only path crosses process boundary

# in the driver (writer thread):
ds = xr.open_zarr(tmp_path)
store.region_write(ds, epoch_slice)
shutil.rmtree(tmp_path)  # cleanup
```

This eliminates all IPC data transfer for the large payload. Only the path string and
lightweight `aux_metadata` (scalars / small dicts) cross the process boundary.

**Size threshold**: keep returning `xr.Dataset` directly for small files (<50 MB in memory);
use temp-Zarr path for large files (24h SBF). `ParallelismConfig` can expose a
`large_file_threshold_mb` knob, defaulting to 50.

---

## Backpressure: bounded in-flight futures

**Problem**: submitting all futures upfront with `executor.submit()` in a tight loop causes
all results to accumulate in the driver process heap simultaneously.

**Strategy: sliding-window future management**

Maintain at most `2 × max_workers` futures in flight at once:

```python
from concurrent.futures import as_completed
from collections import deque

window = deque()
for fpath in file_list:
    if len(window) >= 2 * max_workers:
        # drain one before submitting next
        done = window.popleft()
        writer_queue.put(done.result())
    window.append(pool.submit(preprocess_with_hermite_aux, fpath, ...))

# drain remaining
for fut in window:
    writer_queue.put(fut.result())
```

This caps in-flight memory at `2 × max_workers` datasets while keeping the pool fully
saturated. The `writer_queue` is a `queue.Queue(maxsize=4)` connecting the submitter
thread to the single writer thread.

---

## Streaming write pipeline

```
file_list (sorted by size descending for scheduling)
    │
    ▼
[Submitter thread]  → sliding window (2×N futures) → ProcessPoolExecutor (N workers)
                                                              │
                                                      worker: parse → write temp Zarr → return path
                                                              │
    ┌─────────────────────────────────────────────────────────┘
    ▼
queue.Queue(maxsize=4)   ← backpressure: blocks submitter if writer is slow
    │
    ▼
[Writer thread]  → open Icechunk session (once)
                 → for each (path, epoch_slice): ds = open_zarr(path); region_write(ds)
                 → session.commit()  (once at end)
                 → cleanup temp Zarr files
```

**Session lifecycle**: one `repo.writable_session()` opened before the writer loop starts,
one `session.commit()` after all files are written. Commit granularity = one receiver-day
(unchanged from current design).

**Crash recovery**: use `session.flush(message)` (Icechunk v2) to checkpoint after every
N files without advancing the branch. If the process crashes mid-day, restart from the
last flush checkpoint rather than re-processing the entire day.

---

## 24h SBF files: intra-file parallelism

**(Pending Fable deep-dive findings — to be filled in)**

Current issue: one 24h SBF file = one task = one worker occupied for the entire day.
For a two-receiver site with 24h files, max parallelism = 2 regardless of pool size.

Candidate strategy: **pre-scan + parallel chunk workers**
1. Lightweight pre-scan pass: read block headers sequentially to build offset table
   `[(byte_start, byte_end, n_epochs), ...]` for N time-equal chunks.
2. Submit N tasks, each reading a byte range and parsing its chunk.
3. Writer receives N partial datasets and region-writes them (out-of-order fine with §above).

Decision pending: requires `SbfReader` to expose a `from_byte_range(path, start, end)` API
(does not currently exist). Fable is assessing feasibility.

---

## ParallelismConfig model

```python
class ParallelismConfig(BaseModel):
    mode: Literal["backlog", "daily"] = "daily"
    max_workers: int | Literal["auto"] = "auto"
    memory_fraction: float = Field(0.5, gt=0.0, le=1.0)
    large_file_threshold_mb: float = 50.0  # above this: worker writes temp Zarr

    @staticmethod
    def gil_enabled() -> bool:
        fn = getattr(sys, "_is_gil_enabled", None)
        return True if fn is None else fn()

    def resolved_max_workers(self) -> int:
        if self.max_workers != "auto":
            return min(self.max_workers, os.cpu_count() or self.max_workers)
        return max(1, (os.cpu_count() or 2) // 2) if self.mode == "backlog" else 2

    def executor_kind_for(self, reader_format: str) -> Literal["thread", "process"]:
        if not self.gil_enabled():
            return "thread"
        return "process"  # safe default for both formats until Q3 is benchmarked
```

**Relationship to `ProcessingParams`**: `ParallelismConfig` is the new single source of
truth. Existing `ProcessingParams` fields (`resource_mode`, `n_max_threads`,
`threads_per_worker`, `parallelization_strategy`) are bridged to `ParallelismConfig` with
`DeprecationWarning`. Existing `sites.yaml` files continue to work unchanged.

---

## What's missing to make `worker_task_with_region_auto` the default

`worker_task_with_region_auto` is prototyped but not wired as the default path. The gaps:

1. **Pre-allocation step**: before dispatching workers, the store must exist with the full
   epoch coordinate array written. Epoch count per file is obtainable cheaply:
   - RINEX: `TIME OF FIRST OBS` / `TIME OF LAST OBS` in the header + sampling rate
   - SBF: lightweight header-only pre-scan (block ID filter, collect MeasEpoch TOWs only)
   A pre-allocation pass over all file headers takes seconds and unlocks order-free writes.

2. **Fork distribution**: the driver must create a `ForkSession` per worker before dispatch
   (or one fork per file, reusing the pattern in `worker_task_append_only`). The fork is
   picklable and passed as an argument to the worker.

3. **Merge orchestration**: driver collects returned `ForkSession` objects and calls
   `session.merge(*forks)` then `session.commit()`. This is not yet wired in the main
   `_parallel_process_rinex` dispatch path.

4. **Dedup under fork/merge**: dedup (hash + temporal overlap) currently runs in the driver
   before writing. With fork/merge, each worker writes directly to its fork — dedup must
   either (a) run in the driver before dispatch (check against the store, not the batch),
   or (b) be skipped for the fork path and enforced at merge time. Option (a) is safer and
   compatible with the existing three-layer guardrails.

This work is **local-FS compatible** — Icechunk fork/merge works on the filesystem store,
not only on S3. Adopting it now means the local and S3 paths share the same worker interface.

**Decision deferred to Fable deep-dive**: Fable will confirm session lifecycle details,
fork/merge wiring points, and dedup restructuring before implementation is planned.

## WriteStrategy abstraction (forward-compat with S3 fork/merge)

```python
class WriteStrategy(Protocol):
    def open(self, repo: IcechunkRepo, branch: str) -> None: ...
    def write(self, ds: xr.Dataset, epoch_slice: slice, group: str) -> None: ...
    def commit(self, message: str) -> None: ...

class SequentialWriteStrategy:
    """Current path: local FS, one writer, region= writes."""
    ...

class ForkMergeWriteStrategy:
    """Future path: object storage, N workers each hold a ForkSession."""
    ...
```

Worker function signature (same for both strategies):
```python
def preprocess_with_hermite_aux(
    fpath: Path,
    ...,
    epoch_range: tuple[int, int] | None = None,  # pre-allocated store position
) -> tuple[Path, Path, dict]:  # (source_path, temp_zarr_path, aux_metadata)
```

For the fork/merge path: worker additionally receives a `ForkSession` token, writes directly
to it, and returns the fork. Driver merges and commits. Worker interface is identical — only
what the session token points to differs.

---

## Custom metadata table — keep it (Icechunk v2 research, 2026-07-02)

See `icechunk_v2_metadata.md` for full findings. Summary:

Icechunk v2 `repo.ancestry()` exposes `SnapshotInfo` with a free-form `metadata` dict per
commit — you can attach `rinex_hash`, `start`, `end`. But there is **no server-side filter**:
finding "has hash X been ingested?" requires iterating all commits in Python — O(n) vs the
Zarr table's O(1) Polars column filter. Temporal overlap is a domain concept Icechunk has
no abstraction for. The custom `{group}/metadata/table` stays as the authoritative source.

**Low-cost enhancement (add now):** attach file provenance to every commit:
```python
session.commit(
    f"Append {canonical_name}",
    metadata={"rinex_hash": rinex_hash, "canonical_name": canonical_name,
              "start": str(start), "end": str(end), "action": action},
)
```
Makes every Icechunk commit self-describing in `icechunk-io` tooling and Arraylake viewers
at zero cost. The table remains the dedup source of truth.

---

## Open questions

| # | Question | Status |
|---|---|---|
| W1 | Does `append_to_group()` use `append_dim`? | **Answered**: yes, and opens its own session/commit — wrong primitive for streaming. Use `_append_to_icechunk`'s shared session. |
| W2 | Epoch count per file cheaply obtainable? | **Answered**: RINEX header (`TIME OF FIRST/LAST OBS` + rate); SBF: header-walk index pass (§SBF splitting). Same pass enables fork/merge pre-allocation. |
| W3 | `region=` coordinate constraint (xarray #7702)? | Open — verify before implementing region writes. |
| W4 | SBF `from_byte_range` API cost? | **Answered**: ~150–300 LOC, zero changes to `sbf-parser`. Self-sync on `$@`+CRC from any offset. Stream state (DeltaLS, FreqNr) must come from index pass. |
| W5 | Layer 3 dedup under streaming? | **Answered**: inverts silently — must move to discovery time using filename-encoded intervals before dispatch. |
| W6 | MPIRE vs PPE for ephemeris sharing? | Open — benchmark if ephemeris reload cost becomes visible after decode hot loop is fixed. |
| W7 | Is `keep_sids` always set in production configs? | **ANSWERED**: No. Default is `mode: all` → full 3,658 SIDs. `mode: preset` is a silent no-op. 40× is real in all default deployments. |
| W8 | Does downstream code rely on monotonic epoch axis? | Open — grep `.sel(epoch=slice(...))` callers. |
| W9 | Ragged SID axis feasibility | **ANSWERED**: GO. Full audit in `ragged_sid_feasibility.md`. Min change set ~20 lines. See priority order. |
