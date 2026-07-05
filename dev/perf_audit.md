# Performance Audit — Parallelization in the canvodpy Orchestrator

Branch: `explore/performance-review` (worktree `canvodpy-perf`)
Date: 2026-07-02
Scope: `canvodpy/src/canvodpy/orchestrator/{processor.py,pipeline.py,interpolator.py}`,
`packages/canvod-store/src/canvod/store/store.py`,
`packages/canvod-utils/src/canvod/utils/config/models.py`,
readers layer oriented via the graphify knowledge graph (`graphify-out/`).

---

## 1. Current parallelism: pool types, worker counts, unit of work

### Executor backends (two, selected by config — plus two auxiliary thread pools)

| Where | Executor | Selected by |
|---|---|---|
| `RinexDataProcessor._parallel_process_rinex_dask` (processor.py:1279) | **Dask distributed** LocalCluster (process workers) | `ProcessingParams.parallelization_strategy = "dask"` (default; models.py:243) and a client exists |
| `RinexDataProcessor._parallel_process_rinex_pool` (processor.py:1409, PPE at :1448) | **`ProcessPoolExecutor`** | Fallback when no Dask client (`parallelization_strategy = "processpool"` or dask import failure, pipeline.py:160–172) |
| `PipelineOrchestrator._process_multi_day_batches` Phase 1 (pipeline.py:746–747) | **`ThreadPoolExecutor`**, `max_workers = min(len(batch), 4)` — **hardcoded** | Multi-day batches only; per-DOY prep (SP3/CLK download, aux Zarr, positions) |
| `interpolator.py:138` (clock) and `:273` (SP3 Hermite) | **`ThreadPoolExecutor()`** with **no `max_workers`** (OS default) | Always, inside aux preprocessing; one task per SV |

The dispatch point is `RinexDataProcessor._parallel_process_rinex` (processor.py:1254–1277):
Dask if `self._dask_client is not None and _HAS_DISTRIBUTED`, else `ProcessPoolExecutor`.

### `max_workers` source chain

- **Config**: `ProcessingParams` (models.py:134) — `resource_mode: "auto" | "manual"`,
  `n_max_threads: int | None` (1–100, required in manual mode, ignored in auto),
  `threads_per_worker`, `max_memory_gb`, `cpu_affinity`, `nice_priority`.
  `resolve_resources()` (models.py:298) returns `n_workers = n_max_threads` (manual)
  or `None` (auto → "let Dask/OS decide").
- **Flow**: `resources["n_workers"]` → `PipelineOrchestrator(n_max_workers=...)`
  (pipeline.py:77, 1333) → `RinexDataProcessor(n_max_workers=...)` (pipeline.py:495, 611)
  → clamped `min(n_max_workers, os.cpu_count())` (processor.py:591–592) → Dask cluster
  `n_workers` or `ProcessPoolExecutor(max_workers=...)`.
- **Hardcoded values found**:
  - `SingleReceiverProcessor(n_max_workers=12)` default (pipeline.py:1235)
  - `DistributedRinexDataProcessor(n_max_workers=12)` default (processor.py:3030) and
    its `__main__` demo `n_max_workers=12` (processor.py:3361)
  - Phase-1 prep pool `min(len(batch), 4)` (pipeline.py:746)
  - Interpolator thread pools use the executor default (no cap at all)
- **No GIL awareness anywhere**: nothing checks `sys._is_gil_enabled()`; executor choice
  is config-driven, not format- or runtime-driven.

### Unit of parallelism

**One file per task**, uniformly. Every path submits
`preprocess_with_hermite_aux(rnx_file, ...)` (module-level, processor.py:80) which does
*read → aux-Zarr slice → spherical coords* for a single file and returns
`(Path, xr.Dataset, aux_dict, sid_issues)`. In the flat-Dask multi-day path the task
list is flattened across dates *and* receivers (pipeline.py:744–830), so parallelism
spans (date × receiver × file). The readers themselves (`SbfReader.to_ds()`,
`Rnxv3Obs.to_ds()`, `GNSSDataReader.iter_epochs()`) are single-threaded per file —
confirmed via graphify (`GNSSDataReader`, `SbfReader` subgraphs; SBF is a sequential
`$@`-sync block stream, not randomly seekable without a pre-scan).

## 2. RINEX vs SBF dispatch: same pool

There is **no format-based routing**. The file format travels as a plain
`reader_name` / `reader_format` string argument into the worker
(`ReaderFactory.create(reader_name, fpath=rnx_file)`, processor.py:157). Each receiver
group is format-homogeneous (`_get_rinex_files(data_dir, reader_format)` filters per
receiver; `reader_format_lookup` at pipeline.py:809–819), but *all* receivers' tasks —
RINEX and SBF alike — go to the **same** Dask cluster or the same
`ProcessPoolExecutor`. Consequences:

- With the default (Dask/PPE, process workers) SBF *does* get true CPU parallelism
  today — at the cost of process startup per day (short-lived PPE per
  `_parallel_process_rinex_pool` call) and pickling full `xr.Dataset`s from worker back
  to driver.
- RINEX files pay the same process/pickling overhead even though they are I/O-bound
  and would be served adequately by threads.
- SBF (~10× heavier per file) and RINEX tasks share one worker budget, so a mixed
  batch lets long SBF tasks occupy workers while cheap RINEX tasks queue behind them
  (no size-aware scheduling; `dask_as_completed`/`as_completed` only).

## 3. Boundary between parallel phase and sequential write phase

Two concrete boundaries, both funneling into
`RinexDataProcessor._append_to_icechunk` (processor.py:1745) — one writable session,
one commit per (receiver, day), strictly sequential:

1. **Single-date path** (`parsed_rinex_data_gen`, processor.py:2725–2790, and the older
   `parsed_rinex_data_gen_2_receivers`, processor.py:2337–2353):
   `_parallel_process_rinex(...)` returns the **complete list** of augmented datasets
   for a receiver-day, then `_append_to_icechunk(augmented_datasets, ...)` is called.
   Boundary = the return of `_parallel_process_rinex`.
2. **Multi-day flat-Dask path** (`_process_multi_day_batches`, pipeline.py:877–1002):
   results are collected in the `dask_as_completed` loop into
   `pending_results[group_key]`; when a (date, receiver) group's expected count is
   reached, `processor._append_to_icechunk(...)` is called **inline in the collection
   loop** (pipeline.py:954). Boundary = the group-complete branch at pipeline.py:932–960.

Note on (2): the write is on the driver thread *inside* the result-collection loop, so
while a group is being written the driver drains no further futures; completed results
pile up in Dask worker memory. It is "streaming per group", not pipelined.

An experimental third path exists — `DistributedRinexDataProcessor.
_cooperative_distributed_writing` (processor.py:3042) using Icechunk session forks for
parallel writes — but it is marked "Under development. Use with caution", and its
Step 1 **parses every file twice sequentially** (once to collect epochs at
processor.py:3063–3074, again in the workers). Not production-relevant.

## 4. Backpressure: absent

- `_parallel_process_rinex_pool` / `_parallel_process_rinex_dask` accumulate **all**
  results of a receiver-day in `results: list` before returning
  (processor.py:1317/1442). A full day (96 RINEX or 95 SBF files, augmented, in memory)
  sits in driver RAM before the first byte is written.
- `_process_multi_day_batches` accumulates `pending_results` / `pending_aux`
  per group with **no size bound** (pipeline.py:840–845); with `days_per_batch > 1`
  several days × receivers can be buffered simultaneously.
- No `queue.Queue`, no semaphore, no bounded buffer anywhere between processing and
  Icechunk writes. The only memory control is Dask's per-worker `memory_limit`
  (pipeline.py:105–107) and the passive `MemoryMonitor` (logs only).
- Additional buffer: `_rinex_cache` (processor.py:2656) keeps a whole receiver-day of
  augmented datasets alive for reference-variant reuse.

## 5. sbf_obs concat bottleneck: status on this branch

The bottleneck recorded in project memory ("`processor.py:2744` does
`xr.concat(sbf_parts, dim='epoch')`") is **no longer present on this branch**. It has
been replaced:

- processor.py:2130–2157 (STEP 6 of `_append_to_icechunk`): collects
  `sbf_parts = [aux_dict["sbf_obs"] ...]` and calls
  `self.site.rinex_store.append_metadata_datasets(sbf_parts, receiver_name, "sbf_obs", branch)`.
- store.py:1080–1129 (`MyIcechunkStore.append_metadata_datasets`): first part
  `mode="w"`, subsequent parts `append_dim="epoch"`, all inside one session/commit —
  **no in-memory concat**. Read path (`read_metadata_dataset`, store.py:1131) is a lazy
  `xr.open_zarr` — concat-on-read is effectively in place.

Two residual issues remain:

1. **Ordering**: parts are gathered from dicts populated in *task-completion order*
   (`aux_datasets_by_file[fname] = aux` at processor.py:1361/1484;
   `pending_aux[group_key][fname] = aux` at pipeline.py:885). The main obs results are
   re-sorted chronologically (processor.py:1390/1513, pipeline.py:946) but the
   **sbf_obs parts are appended along `epoch` unsorted**, so the metadata group can end
   up with non-monotonic epochs.
2. **Buffering**: every file's `sbf_obs` dataset is held in driver memory from task
   completion until after the main data commit (STEP 6 runs last), i.e. the memory cost
   of the old concat is gone but the *retention* cost is not.

## 6. Other performance observations

- **Broadcast-geometry double parse** (processor.py:168–184): when
  `use_sbf_geometry=True` and a `broadcast_canopy_file` is passed, each *reference*
  file task re-reads and fully parses the matching **canopy SBF file**
  (`to_ds_and_auxiliary`) inside the worker — the heaviest possible operation,
  duplicated once per reference file, with no caching.
- **Pickling tax**: workers return fully-realized `xr.Dataset`s (obs + aux) across the
  process boundary; for SBF days this is hundreds of MB serialized twice
  (worker→driver, then driver→Icechunk).
- **Short-lived pools**: the non-Dask path creates a fresh `ProcessPoolExecutor` per
  receiver-day (processor.py:1448) — process spawn + import cost repeated per day.
- **Aux interpolation threads**: `interpolator.py` uses unbounded
  `ThreadPoolExecutor()` per variable with one task per SV; scipy/numpy release the GIL
  only partially, and this runs inside the Phase-1 prep threads too (nested pools).
- **Per-day aux Zarr rebuild**: `parsed_rinex_data_gen_2_receivers` deletes and
  rebuilds the day's aux Zarr on every run (processor.py:2264–2271).
- **Known-broken overwrite path**: `_prepare_store_for_overwrite` (`.load()` on
  Dask-backed data → `TypeError`) — pre-existing, documented in memory; interacts with
  any write-path refactor.
- **Sequential writes are correct**: Icechunk local FS cannot take concurrent commits;
  the single-session/single-commit design in `_append_to_icechunk` is the right shape
  and is treated as a hard constraint in the companion plan (`perf_plan.md`).

---

## 7. Deep-dive findings (dispatch internals, memory, 24h file problem)

Measurements below were taken on this machine (macOS arm64, Python 3.14, icechunk 2.0.1)
with `bench_dispatch` scratch scripts; all sizes computed from code-verified dtypes
(`DTYPES`, gnss_specs/metadata.py:229–239: SNR f32, Pseudorange f64, Phase f64,
Doppler f32, SSI/LLI i8).

### 7.1 What crosses the process boundary

**Sent to each worker** (tiny, <1 KB): the positional args of
`preprocess_with_hermite_aux` (processor.py:80–92) —
`(rnx_file: Path, keep_vars: list[str], aux_zarr_path: Path, receiver_position:
ECEFPosition, receiver_type: str, keep_sids, reader_format: str, use_sbf_geometry,
store_radial_distance, store_sbf_raw_observables)`. Built in
`prepare_batch_tasks` (processor.py:2376–2399), submitted at processor.py:1324–1340
(Dask) / :1449–1463 (pool) / pipeline.py:825–830 (flat multi-day). The aux Zarr is
**not** shipped — workers open it by path (processor.py:242–249). Input pickling is a
non-issue.

**Returned from each worker** (large):
`(Path, ds_augmented: xr.Dataset, aux: dict[str, xr.Dataset], sid_issues)`
(processor.py:93, 225, 330). `ds_augmented` = keep_vars-filtered obs + `theta`/`phi`
(f64, dims `(epoch, sid)`) + optional `r`/`clock`; `aux` contains the full `sbf_obs`
metadata dataset for SBF. All fully realized numpy — pickled worker→driver, held in
`pending_results`/`results` until group write.

### 7.2 Dataset size estimates — the SID-padding multiplier is the story

Both readers pad the sid dim to the **global SID universe** before returning
(`pad_to_global_sid`, called at sbf/reader.py:1205–1211 and rinex/v3_04.py:1830–1833).
Measured size of that universe with current constellation models
(`aggregate_glonass_fdma=True`): **3 658 SIDs**. (Project memory says 321 — that
figure is stale or reflects a `keep_sids`-restricted run; the discrepancy is an
**open question** worth checking against production config. `strip_fillvalue` does
NOT prune — it only removes `_FillValue` attrs, preprocessing.py.) After padding, the
worker intersects with aux SIDs (processor.py:255–272), which shrinks sid again to
the ephemeris-covered set — but the padded arrays are materialized first, inside the
reader.

Per-variable bytes = epochs × sids × dtype. With padding to 3 658:

| File | Epochs | Cells/var | Reader-level 5 obs vars (25 B/cell) | + raw obs vars (store_sbf_raw_observables, ~24 B/cell) | Returned augmented (SNR f32 + θ/φ f64 = 20 B/cell) |
|---|---|---|---|---|---|
| 15-min RINEX @ 5 s | 180 | 0.66 M | 16 MB | n/a | 13 MB |
| 15-min SBF @ 1 Hz | 900 | 3.3 M | 82 MB | +79 MB | 66 MB |
| 24 h SBF @ 1 Hz | 86 400 | 316 M | **7.9 GB** | **+7.6 GB** | **6.3 GB** |

Unpadded (observed SIDs only, ~60–90 for a real SBF file), the 24 h augmented result
is ~155 MB — the padding multiplier is **~40×**. The prompt's back-of-envelope
"86 400 × 30 × f32 ≈ 10 MB/var" is what the data *intrinsically* is; the pipeline
materializes 40–120× that. If `keep_sids` is configured (typical VOD analyses),
everything shrinks to a few MB and none of this matters — **whether production runs
with `keep_sids=None` is the single most important question this audit raises.**

Additional transient: SBF `to_ds` builds `epoch_rows`, a Python list of 4 dicts per
epoch (reader.py:1063–1097) — for 24 h, ~86 400 × 4 dicts × ~60 entries ≈ 20 M dict
entries of boxed floats (several GB of Python object overhead) held until the arrays
are filled (reader.py:1105–1119).

**Measured pickle cost** (synthetic 86 400 × 321, SNR f32 + θ/φ f64): 555 MB in
memory → 555 MB pickled, `dumps` 0.49 s, `loads` 0.37 s (~1.1 GB/s each way). Pickle
*throughput* is fine; the cost is **2–3× peak RSS** (worker copy + wire copy + driver
copy) and driver-side retention.

### 7.3 GIL-held fraction of `preprocess_with_hermite_aux`

| Stage | Code | GIL behaviour |
|---|---|---|
| Reader parse/decode | processor.py:157–163 → readers | **~100 % GIL-held.** SBF: Cython `sbf_parser` builds Python dicts for every block (block_parsers.pyx:22–78); canvod decode is per-observation Python (see 7.9). RINEX: pure-Python string slicing (`_parse_obs_fast`, v3_04.py:120–150) and Python fill loops. |
| Aux Zarr open+load | processor.py:242–249 | Partially GIL-released (zarr decompression, disk I/O). |
| SID intersection | processor.py:255–272 | GIL-held, negligible. |
| Spherical coords | processor.py:298, :333–358 | Vectorized numpy — mostly GIL-released. |

For SBF the reader dominates wall time → the task is **>90 % GIL-held**; for RINEX
~80–90 %. Corollary: the audit's earlier "RINEX is I/O-bound, threads would suffice"
framing is **wrong** — RINEX parsing is CPU-bound *Python*, so a ThreadPool would
serialize it. Process-based executors are the right choice for **both** formats
(absent free-threaded Python).

### 7.4 Measured dispatch overheads

| Metric | Value |
|---|---|
| Bare interpreter start | 0.031 s |
| `import numpy` | 0.094 s |
| `import numpy, xarray, zarr, icechunk` | 0.94 s |
| `import canvodpy.orchestrator.processor` (what a worker pays to unpickle the task fn) | **3.05 s** |
| `ProcessPoolExecutor(8)` create / trivial-task steady round-trip | 0.015 s / **0.2 ms** |
| Dask `LocalCluster(4)` create / trivial-task round-trip median (p90) | 0.75 s / **10.4 ms** (11.9 ms) |

Dask's ~10 ms/task overhead is irrelevant against seconds-per-file tasks. The real
fixed cost is the **3 s canvod-stack import per worker process** (see 7.7).

### 7.5 The 24 h file problem — confirmed, plus a memory blocker

Confirmed from code: the unit of parallelism is one whole file everywhere
(processor.py:1324–1340, :1449–1463; pipeline.py:825–830). There is **no chunking of
any file before dispatch** — no time-splitting exists in the orchestrator or either
reader. For a two-receiver site with 24 h SBF files, exactly **2 tasks exist per
day**; a pool of N > 2 workers is idle capacity, and wall time per day ≈ one full 24 h
parse (minutes, see 7.9) regardless of hardware.

Two aggravations beyond the parallelism ceiling:
1. **Memory**: per 7.2, one 24 h SBF task with padding and raw observables can
   transiently need >10 GB in a single worker; two receivers = two such workers, plus
   pickled copies on the driver. On shared machines with adaptive memory caps this is
   the more likely failure mode than slowness.
2. **Broadcast-geometry mode doubles it**: each *reference* task re-parses the whole
   canopy SBF file inside the worker (processor.py:168–184) — for 24 h files that is
   a second full 24 h parse per day, uncached.

### 7.6 SBF intra-file splitting: existing surface, gaps, cost

Existing reader surface (`SbfReader`, sbf/reader.py:761):

- `iter_epochs()` (reader.py:979–1017) **streams** (generator, one decoded epoch at a
  time) — but each call re-scans the file from byte 0, and there is **no offset or
  byte-range parameter**.
- **No** scan-only pass exposing `(block_offset, id, length, timestamp)`; **no**
  `from_bytes()` / `read_range()`. The cached "pre-scan" that exists
  (`_freq_nr_cache`, reader.py:802–822) is a *full parse* of every block (it goes
  through `sbf_parser.read`, which invokes the block parsers and builds full Python
  dicts for every MeasEpoch — nearly doubling per-file parse cost, see 7.9).
- Also per task: `file_hash` reads the whole file into memory for SHA-256
  (reader.py:829–838); `num_epochs` / `header` / `start_time` / `end_time` each
  trigger *additional* full scans if accessed (reader.py:854–931, :937–973).

Underlying library (`sbf-parser`, Cython, site-packages):

- `read(path)` (parser.pyx:42) → `load(fobj)` (parser.pyx:49–70): `fread`s 1 MB
  buffers **from the fd's current position to EOF**. A worker can therefore
  `open(); seek(chunk_start); sbf_parser.load(f)` and simply **stop consuming when
  the decoded TOW passes its chunk end** — no library change needed.
- The stream **self-synchronizes**: `_parse` scans byte-wise for `$@` and validates
  the 2-byte CRC-16 (parser.pyx:183, C impl `c_crc.c`) before accepting a block, so
  starting at an arbitrary offset is safe.
- `parse(bytes)` exists (parser.pyx:73–86) but caps input at 1 MB per call with a
  fresh internal buffer each call — not usable for chunked feeding as-is.

What intra-file splitting needs (moderate addition, est. 150–300 LOC in
canvod-readers; **zero** changes to sbf-parser):

1. A cheap index pass: walk 8-byte headers (`Sync,CRC,ID,Length`), skip payloads,
   record `(offset, TOW)` for MeasEpoch plus **running stream state** — last-seen
   `DeltaLS` (ReceiverTime) and SVID→FreqNr (ChannelStatus) at each chunk boundary.
   This can replace, not add to, the existing `_freq_nr_cache` full parse.
2. `SbfReader.iter_epochs(byte_range=..., initial_state=...)` /
   `to_ds_and_auxiliary(byte_range=...)` variants.
3. Reassembly on the driver: N chunk datasets per file, epoch-disjoint by
   construction → append in chunk order (no concat needed if streamed into the
   store, §7.10).

Stream-state is the correctness trap: a mid-file worker that misses the file-head
`ReceiverSetup`, earlier `ReceiverTime` and `ChannelStatus` blocks would default
`delta_ls=18` (reader.py:77, :1001) and lack GLONASS FreqNr entries — hence
`initial_state` from the index pass is mandatory, not optional.

### 7.7 ProcessPoolExecutor spawn overhead — corrected

The audit's framing ("95 × 15-min files = 95 spawn-import cycles") is **wrong**: the
pool is created once per `_parallel_process_rinex_pool` *call*, i.e. once per
**receiver-day** (processor.py:1448), and all ~95 files of that day share it. Cost
per fresh pool = each worker process paying interpreter start + module import when it
unpickles the task function: measured **~3.1 s** (`import
canvodpy.orchestrator.processor`, 7.4), incurred concurrently across workers → ~3–6 s
wall per pool. For a 30-day, 2-receiver backfill on the pool path that is 60 pools ≈
3–6 min of pure re-import — worth eliminating, but it does **not** explain the
"minutes for 95 SBF files" benchmark; per-file decode cost does (7.9).

A long-lived pool (created in `PipelineOrchestrator.__init__`, reused across days)
reduces this to a one-time ~3–6 s and also removes repeated `structlog`/config
re-initialization in children. Low-risk change; workers are stateless (all state
arrives via task args).

### 7.8 Reader dataset construction — no concat anywhere (requested §8)

`grep` over `canvod-readers/src`: **zero** occurrences of `xr.concat` / `pd.concat`
in reader code. All three assembly paths pre-allocate and fill in place:

- `SbfReader.to_ds()`: single scan → per-epoch dict accumulation → `np.full((n_epochs,
  n_sids))` + Python fill loops (reader.py:1105–1119). The weak point is not concat
  but the **list-of-dicts intermediate** (reader.py:1063–1097) and per-value boxing.
- `SbfReader.to_ds_and_auxiliary()`: one `parser.read()` pass for obs+metadata
  (reader.py:1651–1677) — good — but it **decodes each Type_1/Type_2 sub-block
  twice**: once via `_decode_epoch` for obs (reader.py:1705), again re-walking the
  raw dicts for metadata SID discovery (reader.py:1743–1762).
- `Rnxv3Obs`: pre-allocated `np.full` arrays (v3_04.py:1547–1553), filled from
  string-sliced values (`_parse_obs_fast`, v3_04.py:120); `to_ds` (v3_04.py:1777)
  only drops/pads/validates.
- `DatasetBuilder.build()`: pre-allocates and fills (builder.py:195–199); its
  `_values: dict[(epoch_idx, sid) → float]` (builder.py:84, :117–120) is per-value
  dict churn, but it is only used by stub/secondary readers.

Conclusion: repeated-`xr.concat` is **not** a problem in this codebase (the one
historical concat, sbf_obs, was already removed — §5). The reader cost is per-value
Python object churn, quantified next.

### 7.9 SBF reader: performance & correctness review (requested §9)

**Performance mechanics**

| Question | Answer |
|---|---|
| Byte reading | Buffered: Cython `fread` in 1 MB chunks (parser.pyx:62–66). Not seek-per-block. |
| Payload parsing | No `struct.unpack` at all — Cython struct-pointer casts. But every block is converted to **nested Python dicts/lists** (MeasEpoch_toDict, block_parsers.pyx:22–78): a 12-key dict per Type1 + 9-key dict per Type2. |
| MeasEpoch sub-block loop | Nested Python loops twice: once in Cython dict-building, again in `_decode_epoch` (reader.py:2286–2299). ~0 unpack calls, but ~12–21 Python objects created per signal *at parser level alone*. |
| C/N0 scaling | Per-value, in Python, with a **pint Quantity allocated per observation** (`cn0_dbhz`, _scaling.py:83–115), immediately unwrapped again via `.to(UREG.dBHz).magnitude` (reader.py:1725). Not vectorized. |

The dominant cost per signal-observation: Cython dict → `decode_signal_num` →
`decode_svid` (linear scan of 13 ranges, _registry.py:107–110) → 2–4 pint Quantities
(_scaling.py) → **one Pydantic `SbfSignalObs` instantiation with validation**
(models.py:84, `BaseModel`) → pint `.to()` conversions back to float. Order 10–30 µs
each. A 24 h file at 1 Hz with ~60–100 signals/epoch ≈ 5–9 M observations →
**minutes of pure Python decode**, plus the `_freq_nr_cache` pass which re-parses
every MeasEpoch payload it doesn't need (reader.py:814–822), plus `file_hash`'s full
104 MB read (reader.py:837). ≥2 full parses + 1 full read per task — consistent with
the observed "95 × 15-min SBF files take minutes". **This, not dispatch, is the SBF
bottleneck.** A vectorized decode (accumulate raw integer columns per epoch, apply
scaling with numpy once, skip pint/Pydantic in the hot loop) is a 10–50× lever that
compounds with any parallelism change.

**Correctness vs RefGuide (v4.14.0, bundled PDF; citations are in-code)**

| Item | Spec | Code | Verdict |
|---|---|---|---|
| CRC | CRC-16 over ID..body must validate | Validated in C before any block is accepted (parser.pyx:183, c_crc.c); failures become "BadSBF" and are silently ignored by the reader (match falls through, reader.py:1004–1017) | **Agrees.** Gap: corrupt blocks are dropped with *no counter/warning* — silent data loss on damaged files. |
| SVID mapping | Table 4.1.9: GPS 1–37; GLONASS 38–61 (slot+37), 62 unknown, 63–68 (R25–R30); Galileo 71–106; SBAS 120–140 & 198–215; BeiDou 141–180 & 223–245; QZSS 181–187; IRNSS 191–197, 216–222 | `_SVID_RANGES` (_registry.py:67–82) reproduces exactly this, incl. the two GLONASS sub-ranges and split BeiDou/SBAS ranges | **Agrees.** (The simpler "GLONASS 38–68 = slot+37" formulation is itself not what the spec says.) |
| Signal table 4.1.10 | 39 signal numbers | 33 defined (_registry.py:227–279); omitted: 16, 18, 31, 35–37 — all Reserved (31 is the extended-signal escape, handled in `decode_signal_num`, _scaling.py:60–66) | **Agrees / complete for non-reserved.** Unknown numbers → observation dropped at debug level (reader.py:2371–2373) — should be a counted warning. |
| Type2 delta reconstruction | PR₂ = PR₁ + (MSB·65536+LSB)·1e-3; D₂ = D₁·f₂/f₁ + (MSB·65536+LSB)·1e-4; L₂ from PR₂/λ₂ | pr2_m (_scaling.py:283–311), doppler2_hz (:324–359), phase via pr2 (reader.py:2455–2463); DNU sentinels (−4/0, −16/0, −128/0) handled | **Agrees.** |
| GLONASS FDMA | f = 1602 + slot·9/16 MHz (G1), 1246 + slot·7/16 (G2); slot = FreqNr − 8 from ChannelStatus | glonass_freq_hz (_scaling.py:373–417); FreqNr cache pre-scanned over the whole file so *early* epochs are correct too (reader.py:802–822) | **Agrees.** |
| Timestamp | TOW ms + WNc (WNc is continuous/rollover-free in SBF); UTC = GPS − DeltaLS | `_tow_wn_to_utc` (reader.py:80–104); DeltaLS tracked from ReceiverTime (reader.py:1005–1006, 1679–1680), default 18 (:77) | **Agrees**, two caveats: (a) epochs before the first ReceiverTime use the hardcoded 18; (b) ReceiverTime `DeltaLS` DNU (−128) is **not checked** — an unsynchronized receiver would shift all timestamps by ~2 min. Low likelihood, cheap guard. |
| C/N0 fill value | u1, 0.25 dB-Hz/LSB, **DNU = 255**; +10 dB offset except signals 1/2 (P-codes) | raw==255 → None → NaN (_scaling.py:109–110); +10 except sig 1/2 (:111–114, table flags at _registry.py:231–232) | **Agrees with spec.** The claim that "C/N0 = 0 means not-measured" is **not supported** by RefGuide-4.14.0 (DNU is 255; raw 0 decodes to 10.0 dB-Hz / 0 dB-Hz for P-codes). No masking of raw-0 needed. |

Net: the SBF reader is **scientifically careful and spec-faithful; it is slow by
construction, not incorrect**. The two real (minor) correctness gaps: silent BadSBF
drops, and unvalidated DeltaLS.

### 7.10 Streaming writes to Icechunk (requested §10)

Current shape of `_append_to_icechunk` (processor.py:1745):

- **One session for the whole receiver-day**: `writable_session(branch)` opened at
  processor.py:1836 (thin wrapper, store.py:276–281), per-file loop at :1873, each
  file written with `to_icechunk(ds, session, group=..., append_dim="epoch")`
  (:1929/:1941/:1952/:1963), metadata table via `append_metadata_bulk(...,
  session=session)` (:1999), **single `session.commit`** at :2011.
- So the store API already supports exactly what streaming needs: incremental
  appends inside one session, commit once. **No Icechunk-level change required.**
- `append_to_group` (store.py:1288) is *not* the right primitive for streaming: it
  opens its **own** session and commits per call (store.py:1336–1350) → one commit
  per file, plus its internal guardrail re-reads metadata per call.
- `append_metadata_datasets` (sbf_obs, store.py:1080–1129) opens a *second* session
  and commit (called after the data commit, processor.py:2130–2157) — data and
  sbf_obs are currently **not atomic** anyway; streaming can keep or fix that by
  passing the main session in.

**Minimum interface change**: make `_append_to_icechunk` accept
`Iterable[tuple[Path, xr.Dataset, dict[str, xr.Dataset] | None]]` (a generator fed
by `as_completed`) instead of `list`. Inside the existing session context: consume →
dedup-check per item (see 7.11) → `to_icechunk` append → drop the reference →
accumulate only the small `metadata_records` dicts → commit at generator exhaustion.
The per-file loop body needs almost no change; what must be decomposed is the
up-front batch dedup call at :1790 and the up-front sorts
(processor.py:1390/:1513, pipeline.py:946). Driver memory then holds ~1 dataset at a
time instead of a full receiver-day.

Ordering caveat: streamed appends land in **completion order**, so the store's epoch
axis becomes non-monotonic. Options: (a) bounded reorder buffer keyed by filename
(files are named by start time — a min-heap releasing the next-expected file bounds
memory to the out-of-orderness window); (b) accept non-monotonic epochs and sort on
read. (a) is preferred: downstream `.sel(epoch=slice(...))` assumes monotonicity.

### 7.11 Safeguard correctness under streaming input (requested §11)

Layer-by-layer (`_check_existing_with_temporal_overlap`, processor.py:1662–1743):

- **Layer 1** hash-vs-store (`batch_check_existing`, :1680) — pure per-item lookup;
  streams fine.
- **Layer 2** temporal-vs-store (`check_temporal_overlaps`, :1699) — per-item; streams
  fine, **provided** each already-written streamed file becomes visible to the check
  for *subsequent* items (within one uncommitted session the store metadata table
  won't reflect them — the check must also consult an in-session "written intervals"
  set).
- **Layer 3** intra-batch containment (:1704–1741) — **breaks under streaming.** It
  needs the complete batch: it flags the *container* (daily concat file) when its
  interval contains sub-files' intervals (:1727–1730, "prefer keeping the smaller
  sub-files"). With completion-order arrival, if the daily file completes first it is
  written immediately; the later 15-min files then hit Layer 2 (overlap vs
  now-written store data) and get dropped — the **opposite** file survives, silently.
  Redesign: run containment at **discovery time**, before dispatch — the file list is
  fully known up front and the naming convention encodes start time + period
  (`{...}_{PERIOD}_...`), so intervals are computable without parsing. This also
  stops wasted parsing of files that will be skipped.
- The historical `idx == 0` initial-write guard is gone; group creation now keys on
  `receiver_name not in groups` (:1927–1930) — order-independent, streaming-safe.
- `_check_store_vars_consistency` (:1841–1844) — fine if run on the first arriving
  item.
- `_prepare_store_for_overwrite` (:1847–1854) assumes the full batch's epoch ranges
  before any write; under streaming it must take its ranges from the *planned* file
  list (naming convention) — note this path is already broken (Dask `.load()`
  TypeError, §6) and will need rework regardless.
- **sbf_obs order**: parts already append in completion order (dict insertion,
  processor.py:1361/:1484, pipeline.py:885 → store.py:1118–1124). Zarr/Icechunk have
  **no ordering constraint** — appends are just region writes after a resize — so the
  write itself is fine; the damage is at *read* time (`read_metadata_dataset`,
  store.py:1131, returns a non-monotonic epoch axis; any `.sel(slice)` on it
  misbehaves). Same fix as §7.10: ordered release or sort-on-read. Streaming makes
  this pre-existing issue apply to the *main* obs axis too, which is why the reorder
  buffer is not optional.

### 7.12 Future-proofing for object storage: fork/merge behind a WriteStrategy (requested §12)

API surface today: icechunk 2.0.1 is installed; `Session.fork` and `Session.merge`
exist (verified by import). The codebase already imports `ForkSession`
(processor.py:30) and exercises `session.fork()` in the experimental
`_cooperative_distributed_writing` (processor.py:3097) with picklable-fork worker
helpers (processor.py:394–538) — the ingredients exist but only in the
"use with caution" path.

Sketch that serves both worlds:

```python
class WriteStrategy(Protocol):
    def begin(self, group: str, branch: str) -> None: ...
    def write(self, item: PreprocessResult) -> WriteOutcome: ...   # verdict + write
    def finalize(self, message: str) -> str: ...                    # → snapshot_id

class SequentialSessionStrategy:   # today: local FS
    # begin: repo.writable_session(branch)  (store.py:276)
    # write: dedup layers 1–2 per item → to_icechunk(append_dim="epoch")
    # finalize: append_metadata_bulk + session.commit  (processor.py:1999, 2011)

class ForkMergeStrategy:           # later: S3/GCS
    # begin: writable_session + allocate epoch regions from the pre-scan/plan
    # write: driver-side no-op — workers received a fork() and wrote their region
    # finalize: session.merge(*returned_forks) → single commit
```

The streaming refactor of §7.10 should be expressed as
`for item in results: strategy.write(item)` so the fork/merge swap is localized.
Two structural implications to flag now, so the sequential design doesn't paint us in:

1. **`append_dim="epoch"` is incompatible with fork/merge.** Concurrent appends
   resize the same array — conflicting metadata. Fork/merge requires *pre-sized*
   arrays + disjoint region writes, which means total epoch counts must be known
   before dispatch (RINEX: derivable from naming convention + sampling; SBF: needs
   the §7.6 index pass — another reason to build it). One-file-per-worker maps
   cleanly to one-region-per-worker since files are epoch-disjoint after dedup.
2. **Dedup must move ahead of dispatch.** A forked worker cannot be "skipped" after
   it has written; layers 1–3 must all be resolved on the driver from the planned
   file list + store metadata before forks are handed out. §7.11's discovery-time
   Layer 3 is therefore a prerequisite for fork/merge, not just a streaming fix.

### 7.13 Recommendation

**Two streams + pre-scan** (option 3), staged — but with the decode fix first:

1. **Fix the SBF hot loop before adding machinery** (7.9): vectorize scaling, drop
   pint/Pydantic from the per-observation path, make `file_hash` stream in chunks,
   and fold `_freq_nr_cache` into the single main pass (or the index pass). Expected
   ≥10× on SBF single-file latency; benefits every dispatch design and shrinks the
   24 h problem to where splitting may be optional.
2. **Stop padding to 3 658 SIDs inside workers** (7.2): return observed SIDs, pad at
   the write/read boundary (or resolve whether `keep_sids` is always set in
   production). This is the pickling/memory fix — cheaper and larger than shared
   memory or temp-Zarr spill, neither of which is warranted once payloads are tens of
   MB. Revisit temp-Zarr spill only if 24 h-unsplit + padded datasets must survive.
3. **Format-based streams, both ProcessPool** (7.3 kills the RINEX-ThreadPool idea):
   one long-lived pool (7.7), format-aware sizing — SBF workers = physical cores,
   RINEX can share; keep Dask as the multi-day backend (its 10 ms overhead is
   immaterial, 7.4).
4. **Pre-scan + split large SBF files** (7.6) behind a size threshold
   (`sbf_split_threshold_mb`, ~10 MB default is reasonable: 15-min files ≈ 1.1 MB
   pass whole, 24 h ≈ 104 MB split into N time-equal byte ranges). The index pass is
   cheap, doubles as the fork/merge epoch plan (7.12), and restores intra-day
   parallelism for the 2-tasks-per-day site. A distinct third "SBF-large" *stream* is
   unnecessary — splitting changes the task list, not the pool.
5. **Streaming single-writer behind `WriteStrategy`** (7.10–7.12), with
   discovery-time Layer-3 dedup and a filename-ordered release buffer.

Open questions surfaced (not guessed at): (a) is `keep_sids` set in production
configs, i.e. does the 3 658-SID padding actually bite? (b) what fraction of the
"minutes" benchmark is the `_freq_nr_cache` second parse vs the main decode —
worth one profiling run before step 1 is scoped; (c) does any downstream consumer
rely on store epoch monotonicity today (grep suggests `.sel(slice)` users do);
(d) the stale "321 global SIDs" memory entry vs measured 3 658.
