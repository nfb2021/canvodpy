# Performance Plan — Two-Stream Parallelization for canvodpy

Branch: `explore/performance-review` · Date: 2026-07-02 · Status: **PLAN ONLY — nothing implemented**

Companion audit: [`perf_audit.md`](perf_audit.md). All function/line references below
come from that audit.

Goal: replace the single format-blind pool with **two format-aware streams**
(RINEX → threads, SBF → processes when the GIL is on), add **backpressure** between the
parallel read/process stage and the sequential Icechunk write stage, and make worker
counts a first-class, mode-aware config. The sequential write phase and the
one-file-per-worker unit of parallelism are explicitly preserved.

---

## A. `ParallelismConfig` Pydantic model

**Location**: new file `packages/canvod-utils/src/canvod/utils/config/parallelism.py`,
re-exported from `canvod.utils.config.models` and embedded in `ProcessingConfig`
alongside the existing `ProcessingParams`. A separate file keeps the ~900-line
`models.py` from growing and lets the model own its runtime-detection helpers.

```python
from typing import Literal
import os
import sys

from pydantic import BaseModel, Field, model_validator


class ParallelismConfig(BaseModel):
    """Two-stream parallelization settings (backlog vs daily ingestion)."""

    mode: Literal["backlog", "daily"] = Field(
        "daily",
        description=(
            "'backlog': bulk historical processing, use up to cpu_count//2 workers. "
            "'daily': conservative ingestion on shared/pay-per-use machines, 1-2 workers."
        ),
    )
    max_workers: int | Literal["auto"] = Field(
        "auto",
        description=(
            "Total worker budget across both streams. 'auto' derives from mode: "
            "backlog -> max(1, os.cpu_count() // 2); daily -> 2."
        ),
    )
    memory_fraction: float = Field(
        0.5, gt=0.0, le=1.0,
        description="Fraction of system RAM the pipeline may use (bounds queue depth "
                    "and Dask/PPE memory limits).",
    )

    # ---- resolution helpers (no I/O, safe to call anywhere) ----

    @staticmethod
    def gil_enabled() -> bool:
        """True on standard CPython builds; False on free-threaded 3.13t/3.14t."""
        fn = getattr(sys, "_is_gil_enabled", None)
        return True if fn is None else fn()

    def resolved_max_workers(self) -> int:
        if self.max_workers != "auto":
            return min(self.max_workers, os.cpu_count() or self.max_workers)
        if self.mode == "backlog":
            return max(1, (os.cpu_count() or 2) // 2)
        return 2  # daily

    def executor_kind_for(self, reader_format: str) -> Literal["thread", "process"]:
        """RINEX -> threads always. SBF -> processes iff the GIL is on."""
        if not self.gil_enabled():
            return "thread"          # 3.14t: threads give true parallelism for all
        if reader_format == "sbf":
            return "process"         # CPU-bound binary parsing, GIL on
        return "thread"              # rinex2/rinex3/nmea: I/O-bound text parsing
```

**Auto-detection logic** (as mandated):

1. `sys._is_gil_enabled()` — guarded with `getattr` so pre-3.13 interpreters (no such
   attribute) are treated as GIL-on.
2. GIL **off** → `ThreadPoolExecutor` for everything (see §E).
3. GIL **on** → `ThreadPoolExecutor` for RINEX, `ProcessPoolExecutor` for SBF.
4. Worker defaults: backlog `cpu_count // 2` (never monopolize a shared node); daily
   `2` (fits "1–2 workers" and covers canopy+reference pairs).
5. `memory_fraction` (default 0.5) is used to (a) size the bounded queue payload cap,
   (b) derive Dask `memory_limit`/PPE soft limits via the existing `MemoryMonitor`
   (pipeline.py:96).

**Open questions to resolve before implementation** (do not guess):

- **Q1 — overlap with `ProcessingParams`**: `resource_mode` / `n_max_threads` /
  `threads_per_worker` / `parallelization_strategy` (models.py:142–260) already cover
  part of this space. Proposal: `ParallelismConfig` becomes the single source of truth;
  `resolve_resources()` delegates to it and the old fields are deprecated with
  warnings. Needs a decision from the maintainer — sites.yaml files in the field
  already set `resource_mode`/`n_max_threads`.
- **Q2 — Dask's role**: the current default backend is a Dask LocalCluster (process
  workers), which *already* gives SBF true CPU parallelism. Does the two-stream design
  (i) replace Dask as the default, (ii) apply only to the `"processpool"` strategy and
  the daily mode, or (iii) coexist (Dask for backlog on big machines, two-stream pools
  otherwise)? This plan assumes (iii): two-stream pools become the default executor
  layer and `parallelization_strategy="dask"` remains an opt-in for cluster
  deployments. Confirm before wiring.

## B. Two-stream pool design

### Streams

- **Stream 1 (RINEX / text formats)** — one long-lived `ThreadPoolExecutor`.
  Rationale: file reading dominates; threads avoid process spawn and the
  `xr.Dataset` pickling tax entirely (results stay in-process). *Caveat to verify
  (Q3)*: `Rnxv3Obs` parsing is pure-Python text processing, and the existing
  `threads_per_worker` docstring (models.py:227–232) itself notes threads do "not
  [help] pure-Python RINEX text parsing". The 30 s / 96-file benchmark was measured
  with process workers. Before committing to threads-for-RINEX under a GIL-on build,
  run a one-day A/B (threads vs processes, 4 workers). If threads regress badly,
  Stream 1 falls back to sharing Stream 2's process pool — the config API above
  already permits this via `executor_kind_for()`.
- **Stream 2 (SBF)** — one long-lived `ProcessPoolExecutor` when the GIL is on
  (binary block parsing is Python-CPU-bound; SBF is not seekable so the unit stays one
  whole file per worker). When the GIL is off, Stream 2 is the same thread pool as
  Stream 1.

Both pools are created **once** per `PipelineOrchestrator` lifetime (not per
receiver-day as `_parallel_process_rinex_pool` does today, processor.py:1448) and
share the single `resolved_max_workers()` budget. Suggested split for a mixed site:
SBF stream gets `max(1, budget - 1)` processes and RINEX stream `min(budget, 2)`
threads — threads are cheap and I/O-bound, so slight oversubscription of the budget by
the thread stream is acceptable; the hard CPU cap is carried by the process stream.

### Wiring points (from the audit)

1. **`RinexDataProcessor._parallel_process_rinex`** (processor.py:1254) — the existing
   dispatch seam. Change: instead of choosing *Dask vs PPE*, choose the stream via
   `parallelism.executor_kind_for(effective_reader)` and submit to the corresponding
   long-lived pool (injected by the orchestrator, e.g. a small `ExecutorPair` object
   passed into `RinexDataProcessor.__init__` next to `dask_client`). The worker
   function stays `preprocess_with_hermite_aux` unchanged — it is already module-level
   and picklable for the process stream, and equally callable from threads.
2. **`PipelineOrchestrator.__init__` / `cluster_manager`** (pipeline.py:74–172) — owns
   the `ExecutorPair` lifecycle (create lazily like the Dask cluster, close in
   `close()`), replacing the per-day short-lived PPE.
3. **`PipelineOrchestrator._process_multi_day_batches`** (pipeline.py:826–830) — the
   flat task list already carries the reader format per task
   (`reader_format_lookup`, pipeline.py:809–819). Route each task to the matching
   stream at submit time instead of `dask_client.submit(...)` for all.
4. **`SingleReceiverProcessor`** (pipeline.py:1228) — drop the hardcoded
   `n_max_workers=12`; take a `ParallelismConfig` (or resolved `ExecutorPair`).

### Mixed batches: yes, route by format

A mixed batch (e.g. SBF canopy receiver + RINEX reference receiver on the same day)
**should** split across the two pools: receiver groups are format-homogeneous already,
so routing is per receiver group (single-date path) or per task (flat multi-day path)
with zero data-model changes. Benefit beyond GIL correctness: cheap RINEX files no
longer queue behind 10×-heavier SBF files, and both streams drain into the same
bounded write queue (§C) so write ordering/dedup is unaffected.

## C. Bounded queue / backpressure

**Mechanism**: `queue.Queue(maxsize=2 * max_workers)` between the read/process stage
and the sequential Icechunk write stage. Producers are the two streams' completion
handlers; the consumer is a single writer (the driver thread), preserving the hard
"one sequential writer" constraint.

**Insertion points** (referencing audited functions):

1. **Single-date path** — restructure the pair
   `_parallel_process_rinex` → `_append_to_icechunk` (processor.py:1254 / 1745), which
   today materializes the whole receiver-day before writing:
   - A collector thread runs the current `as_completed` /
     `dask_as_completed` loop bodies (processor.py:1480–1509) and `put()`s each
     `(fname, ds_augmented, aux, sids)` tuple into the queue; workers therefore
     **block on `put()`** once `2 × max_workers` results are pending — that is the
     backpressure.
   - `_append_to_icechunk` gains a streaming inner loop: open the writable session
     first (as it already does at processor.py:1836), then `get()` items until the
     sentinel, running the existing per-file logic (hash check, cleanse,
     `to_icechunk`, metadata record collection, processor.py:1873–1944) per item, and
     commit once at the end. Single session, single commit — unchanged semantics.
   - **Guardrail constraint (Q4)**: the three-layer dedup currently pre-computes
     `existing_hashes` from the *full* batch
     (`_check_existing_with_temporal_overlap`, processor.py:1790). Streaming items
     arrive out of chronological order, so (a) the hash/overlap check against store
     metadata must be evaluable per item (it is — it reads the metadata table, not the
     batch), and (b) the *intra-batch* overlap layer must accumulate seen time ranges
     as items are consumed rather than sorting the full batch up front. This needs a
     careful touch — the `idx == 0` initial-write bug class from 2026-03 lives here.
     Flag for review against `test_store_guardrails.py`.
2. **Multi-day flat-Dask path** — `_process_multi_day_batches`
   (pipeline.py:877–1002): move the group-complete write block (pipeline.py:936–1002)
   out of the collection loop into a **writer thread** consuming
   `queue.Queue(maxsize=2 * max_workers)` of group payloads
   `(group_key, augmented, rinex_files, group_aux, group_fmt)`. The collection loop
   becomes a pure producer (it already pops `pending_results`/`pending_aux` at
   group-completion, freeing memory), and the driver keeps draining futures while a
   group is being written — fixing the "writes stall collection" issue from the audit.
   Queue bound here is effectively per-group (a group ≈ one receiver-day), so
   `maxsize` should also be validated against `memory_fraction × total RAM /
   estimated group size`; whichever is smaller wins.

Ordering note: items are written in completion order, not filename order. Data
correctness does not depend on write order (epochs are coordinates; dedup is
hash+interval based), but if chronological commits are desired for the metadata table,
the writer can maintain a small reorder buffer — decide during implementation (part of
Q4).

## D. sbf_obs concat fix

Status from the audit: the `xr.concat(sbf_parts, dim="epoch")` bottleneck recorded in
project memory is **already replaced on this branch** by
`MyIcechunkStore.append_metadata_datasets(parts, group, "sbf_obs", branch)`
(store.py:1080–1129; call site processor.py:2130–2157) — incremental writes
(first `mode="w"`, then `append_dim="epoch"`), one session/commit, lazy
`read_metadata_dataset` on the read side (concat-on-read done). Remaining work:

1. **Stream instead of retain**: `sbf_obs` parts are still buffered in driver memory
   from task completion until STEP 6 of `_append_to_icechunk`. With the §C queue in
   place, feed each part into the same writer as it is consumed. Change
   `append_metadata_datasets` to accept an iterator and, optionally, an existing
   session so it can participate in the streaming write:

   ```python
   def append_metadata_datasets(
       self,
       parts: Iterable[xr.Dataset],          # was: list[xr.Dataset]
       group_name: str,
       name: str,
       branch: str = "main",
       *,
       session: Session | None = None,        # reuse the caller's session if given
   ) -> str | None:                           # None when written into a caller session
   ```

   (Keeping list-compatibility is free since `list` is `Iterable`; the empty-check at
   store.py:1109 becomes a first-item peek.)
2. **Fix part ordering**: parts currently arrive in task-completion order
   (processor.py:1361/1484, pipeline.py:885) and are appended along `epoch` unsorted →
   potentially non-monotonic epoch axis in `{group}/metadata/sbf_obs`. Sort parts by
   their first epoch before appending (cheap: one scalar per part), or document that
   readers must `.sortby("epoch")`. Prefer sorting at write time.
3. No change to the read path: `read_metadata_dataset` / `read_sbf_metadata`
   (store.py:1131/1225) already return a lazy dataset.

## E. Python 3.14t opt-in

Users who install the free-threaded build (`uv python install 3.14t` and pin the
project venv to it) get a CPython where `sys._is_gil_enabled()` returns `False`. In
that case `ParallelismConfig.executor_kind_for()` returns `"thread"` for every format,
so both streams collapse into a single `ThreadPoolExecutor`: SBF binary parsing runs
with true CPU parallelism on threads, no `ProcessPoolExecutor` is created, and the
pickling/spawn overhead disappears entirely. No user-facing configuration changes —
the same `mode`/`max_workers` settings apply; only the executor kind flips. Worth one
sentence in the docs plus a CI job on 3.14t once dependencies (numpy/xarray/icechunk
wheels) declare free-threaded support (Q5: verify wheel availability before
recommending it as the default).

## F. What NOT to change

- **Individual readers stay single-threaded per file**: `SbfReader.to_ds()` /
  `to_ds_and_auxiliary()`, `Rnxv3Obs.to_ds()`, `GNSSDataReader.iter_epochs()` are
  untouched. The unit of parallelism remains **one file per worker**. In particular,
  no intra-file SBF splitting: the block stream is not randomly seekable and would
  require a `$@`-sync pre-scan for no expected win at 24 h-file granularity.
- **The sequential write phase stays sequential**: local-FS Icechunk cannot take
  concurrent commits. `_append_to_icechunk`'s single-session/single-commit design is
  preserved; §C only changes *when* items reach it, not *how many writers* exist. The
  experimental `DistributedRinexDataProcessor` fork-based cooperative writing is out
  of scope.
- **Store guardrails** (three-layer dedup), **VOD formula**, **coordinate
  transforms**, **ephemeris interpolation math** — untouched; any write-path
  restructuring must pass `packages/canvod-audit/tests/` and
  `test_store_guardrails.py` before merge.

## Open questions (consolidated)

| # | Question | Blocking |
|---|---|---|
| Q1 | How does `ParallelismConfig` reconcile with `ProcessingParams.resource_mode` / `n_max_threads` / `threads_per_worker` / `parallelization_strategy`? Deprecate or wrap? | A |
| Q2 | Does two-stream replace Dask as default, or apply to the non-Dask path only? (Plan assumes coexistence, two-stream default.) | B |
| Q3 | Is RINEX parsing thread-scalable under GIL-on? Existing config docs suggest not; benchmark threads vs processes on one day before finalizing Stream 1. | B |
| Q4 | Streaming writes vs batch-computed intra-batch dedup: exact restructuring of `_check_existing_with_temporal_overlap` and whether chronological write order must be preserved for the metadata table. | C |
| Q5 | 3.14t wheel availability for numpy/xarray/zarr/icechunk before promoting the free-threaded path. | E |
| Q6 | Separate fix (not part of this plan, found in audit): the broadcast-geometry path re-parses the canopy SBF file inside every reference-file worker (processor.py:168–184) — cache it per day? Large SBF-mode win independent of pooling. | — |
