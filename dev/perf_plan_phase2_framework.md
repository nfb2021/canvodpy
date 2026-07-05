# Performance Plan — Phase 2: Parallelization Framework (Implementation Plan)

**Date:** 2026-07-03. Follow-up to `dev/perf_plan_phase1.md` (Tasks A/B land first),
`dev/perf_audit.md` §7, `dev/perf_strategy.md`, `dev/perf_web_research_phase2.md`
(framework research). **Planning only — no code was changed.** All file:line
references verified against the `explore/performance-review` worktree (`canvodpy-perf`)
on 2026-07-03.

> **Supersedes the 2026-07-02 draft of this file.** That draft chose stdlib
> `ProcessPoolExecutor`; the framework decision was subsequently settled by the
> dedicated web-research session (`perf_web_research_phase2.md`): **loky
> `get_reusable_executor()`**. This rewrite plans around loky. All verified
> file:line findings from the draft are retained and re-checked.

Sequencing: this phase assumes Phase 1 Task B (ragged SIDs) is merged first.
Everything here is correct without it, but the memory numbers in §3 assume
post-Task-B payloads (~155 MB worst case per 24 h SBF task, not ~7.9 GB).

---

## 1. Decision summary

**Framework: loky `get_reusable_executor()`** — drop-in for `ProcessPoolExecutor`
with the same `Future` API, but: (a) singleton semantics — any call with the same
parameters returns the same warm pool, which makes "long-lived pool" the default
behaviour instead of a lifecycle-management project; (b) automatic crash recovery —
a crashed worker respawns instead of bricking the pool (stdlib enters unrecoverable
`BrokenProcessPool`), eliminating the manual recreate-and-retry machinery the PPE
draft needed; (c) configurable idle timeout (`timeout=300` — default 10 s is too
short for the write pauses between receiver-days); (d) dynamic resize between
batches without recreation; (e) faulthandler enabled in workers, so OOM-kill and
segfault tracebacks are meaningful; (f) identical API on macOS (spawn), Linux
(forkserver in 3.14), Windows (spawn). loky uses cloudpickle for task functions —
already in the tree (`uv.lock:850`, via dask). psutil is already a transitive dep
(`uv.lock:2526`, via `distributed`) and becomes an explicit dep so loky's memory-leak
and zombie-worker detection activates. Ray (10 ms+/task, multi-node machinery) and
Dask-as-local-executor (10.4 ms/task dispatch, audit §7.4) are rejected for a
single-machine linear pipeline; MPIRE's copy-on-write requires `fork` (unsafe on
macOS, fights the 3.14 Linux forkserver default) and solves a non-problem here (§2
ephemeris correction). Local Dask `LocalCluster` is retired; the Dask code path
survives only for `scheduler_address` remote clusters pending §7 Q1.

**Scope note — SBF benefit is gated on the decoder fix (2026-07-03):** this
framework ships for **RINEX now** and applies to **SBF automatically once the
SBF decode fix lands** (stream doc §10.1: post-fix, zero SBF-specific
accommodation is needed at the scheduling level). Pre-fix, a 24 h 1 Hz SBF
file is ~30 min of GIL-held decode and multi-GB of transient worker RSS
(audit §7.5/§7.9) — a backlog of 730 such files is ~45 h at N = 8 and likely
OOMs first (stream doc §10.2). The pool treats both formats identically
(same process tasks, different duration constants); nothing in this plan is
SBF-specific, and nothing in it makes pre-fix SBF fast. Do not present
Phase 2 as an SBF speedup; the decode fix is the hard prerequisite for SBF
backlog processing.

---

## 2. Current state (Q1 — pool location and lifecycle, verified)

### 2.1 Where pools are created today

| What | Where | Lifecycle |
|---|---|---|
| `ProcessPoolExecutor` (fallback path) | `canvodpy/src/canvodpy/orchestrator/processor.py:1448` — `with ProcessPoolExecutor(max_workers=self.n_max_workers) as executor:` inside `_parallel_process_rinex_pool` (:1409) | **One fresh pool per (receiver, day)**, torn down at the end of the `with` block. ~3–6 s wall per pool (3.05 s canvod-stack import per worker, audit §7.4/§7.7). 30-day × 2-receiver backfill = 60 pools ≈ 3–6 min pure spawn overhead. |
| `ProcessPoolExecutor` (fork path) | `processor.py:3140` — second `with ProcessPoolExecutor(...)` inside `_cooperative_distributed_writing` | Per receiver-day, experimental path (see §2.3). |
| Dask `LocalCluster` + `Client` | `canvodpy/src/canvodpy/orchestrator/resources.py:152` (`DaskClusterManager`; `LocalCluster` at :227, `atexit.register(self.close)` at :237) | **Already long-lived**: lazy `cluster_manager` property on `PipelineOrchestrator` (`pipeline.py:158-172`), closed in `close()` (:174-179) / `__exit__` (:185). The loky pool must mirror exactly this shape. |
| Phase-1 prep `ThreadPoolExecutor` | `pipeline.py:746-747` — `ThreadPoolExecutor(max_workers=min(len(batch), 4))` | Per multi-day batch; I/O-bound SP3/CLK prep. **Out of scope, unchanged.** |

### 2.2 Dispatch and per-day processor creation

- Dispatch decision: `processor.py:1257` — `if self._dask_client is not None and
  _HAS_DISTRIBUTED:` → `_parallel_process_rinex_dask` (:1279), else
  `_parallel_process_rinex_pool` (:1268-1277). Dask does **not** wrap the pool path;
  they are parallel siblings submitting the same worker function.
- A **fresh `RinexDataProcessor` per date**: `pipeline.py:492-497`
  (`_process_single_date`) and `:608-613` (`_create_processor_for_date`), receiving
  the shared `dask_client` or `None`. So the Dask path already amortizes cluster
  spawn across days; the PPE path pays per receiver-day.
- `_use_processpool` selection bool: `pipeline.py:135`
  (`parallelization_strategy == "processpool"`); `PipelineOrchestrator.__init__`
  takes `parallelization_strategy: str = "dask"` at `pipeline.py:84`.
- Hardcoded worker counts: `SingleReceiverProcessor(n_max_workers=12)`
  (`pipeline.py:1235`), `DistributedRinexDataProcessor(n_max_workers=12)`
  (`processor.py:3030`).
- Submission is **unbounded**: `_parallel_process_rinex_pool` submits every file
  upfront in a dict comprehension (`processor.py:1449-1464`), then drains with
  `as_completed` (:1479). All results accumulate in the driver
  (`results.append`, :1483) until the day's write. No backpressure (audit §4).

### 2.3 Worker functions — which path is active

| Function | Location | Status |
|---|---|---|
| `preprocess_with_hermite_aux` | `processor.py:80` | **The active worker for all production paths** (pool, Dask, flat multi-day at `pipeline.py:825-830`). Pure function; all state via args; opens the per-day aux Zarr **by path** (`processor.py:242-249`). Returns `(Path, ds_augmented, aux_dict, sid_issues)`. |
| `worker_task` | `processor.py:429` | **Dead code — zero callers** (repo-wide grep). Fork-per-file + `append_dim` variant. |
| `worker_task_append_only` | `processor.py:471` | **Dead code — zero callers.** |
| `worker_task_with_region_auto` | `processor.py:505-538` | Called only from `_cooperative_distributed_writing` (:3110 Dask branch, :3143 PPE branch). Takes a picklable `ForkSession` arg, writes `region="auto"`, returns the fork. |

(Note: the task brief cited :443/:483 for the first two; verified locations are
:429/:471 — the brief's numbers were pre-branch-drift.)

`_cooperative_distributed_writing` (`processor.py:3042`) is **experimental, not
active**: its only caller is `parsed_rinex_data_gen_parallel` (:3175, call at :3307)
on `DistributedRinexDataProcessor` (:3011), which is instantiated nowhere in
`canvodpy/src` or any package (verified). It is the prototype for the future
fork/merge S3 path (§6) and must stay viable.

### 2.4 Correction to the ephemeris-sharing premise

Workers do **not** hold or reload an in-memory ephemeris table per task. SP3/CLK is
preprocessed once per day into an aux Zarr on the driver
(`_ensure_aux_data_preprocessed`, called at `processor.py:2645-2647`); each worker
opens that Zarr *by path* and loads only its file's epoch slice
(`processor.py:242-249`). Sharing already happens through the filesystem + OS page
cache. Consequence for the research findings: the `initializer`/`initargs`
ephemeris-pickle pattern ships as a **hook, not a day-one requirement** — the
initializer's day-one job is eager imports + worker politeness (§4.3). The
initargs upgrade path stays documented because loky makes it cheap later: calling
`get_reusable_executor()` with new `initargs` restarts workers once (per day), which
is exactly the granularity the per-day aux table would need. Do not wire it until
profiling shows per-task aux-open cost after the Phase-1 fixes land.

---

## 3. `ParallelismConfig` model (Q2 + Q3)

### 3.1 Q2 — `ProcessingParams` fields to deprecate

All in `packages/canvod-utils/src/canvod/utils/config/models.py`
(`ProcessingParams` starts :134):

| Field | Lines | Type / default | Controls | Fate |
|---|---|---|---|---|
| `resource_mode` | :142-148 | `Literal["auto","manual"]` = `"auto"` | auto vs hard-capped resources | **Deprecate + bridge**: `"manual"`+`n_max_threads=N` → `max_workers=N`; `"auto"` → `max_workers="auto"` |
| `n_max_threads` | :149-157 | `int \| None` = `None` | max worker processes (manual mode) | **Deprecate + bridge** → `max_workers` |
| `max_memory_gb` | :208-212 | `float \| None` = `None` | soft RAM limit | **Deprecate + bridge** → converted to the memory cap (§3.3); absolute cap wins over `memory_fraction` when both present (see §7 Q4) |
| `cpu_affinity` | :213-216 | `list[int] \| None` = `None` | pin workers to cores | **Move** to `ParallelismConfig` (same name); applied in `_worker_init` via `os.sched_setaffinity` (Linux-only, matching `resources.py:108-117`) |
| `nice_priority` | :217-222 | `int` = `0` (0-19) | worker nice value | **Move** to `ParallelismConfig`; applied in `_worker_init` via `os.setpriority` (matching `resources.py:124-135`) |
| `threads_per_worker` | :223-233 | `int \| None` = `None` | Dask-only threads per worker | **Deprecate**: bridged to the Dask-remote path only; warned-and-ignored under loky |
| `parallelization_strategy` | :243-251 | `Literal["dask","processpool"]` = `"dask"` | executor selection | **Deprecate + bridge**: `"processpool"` → `executor="process"`; `"dask"` → `executor="process"` **too** (local Dask is retired) *unless* `scheduler_address` is set → `executor="dask"` + warning |
| `scheduler_address` | :252-260 | `str \| None` = `None` | remote Dask scheduler | **Move** to `ParallelismConfig.scheduler_address` (it is a parallelism concern); old field bridged |

Related code: `validate_resource_mode` validator (:273-296) — stays as-is during the
deprecation window (its manual-without-n_max_threads error is still correct for
legacy users). `resolve_resources()` (:298-324) — becomes a deprecated thin delegate
over the synthesized `ParallelismConfig`, returning the same dict keys, with a
`DeprecationWarning`. Its consumers (all verified by grep):

- `canvodpy/src/canvodpy/api.py:305` (primary — replaced by §3.4 wiring)
- `canvodpy/src/canvodpy/orchestrator/pipeline.py:1329` (`__main__` demo)
- `canvodpy/src/canvodpy/orchestrator/processor.py:2097` (+ `:2105-2106`, store
  metadata `dask_workers`/`dask_threads_per_worker`)
- `packages/canvod-store/src/canvod/store/reader.py:165`
- `canvodpy/src/canvodpy/diagnostics/timing_diagnostics_script.py:144`

**No hard cuts.** Production `processing.yaml` files exist on shared servers using
`resource_mode: manual`. Bridge for one release, then remove.

### 3.2 Q3 — model design and location

**Location: new file `packages/canvod-utils/src/canvod/utils/config/parallelism.py`**,
re-exported from `models.py` and the config package `__init__`. Rationale:
`models.py` is a 990-line 24-class monolith (Phase-1 finding D7) — don't grow it.
The model must live in canvod-utils (not canvodpy) because it becomes a field of
`ProcessingConfig` and must load from `processing.yaml` through the existing
`ConfigLoader` deep-merge (`packages/canvod-utils/src/canvod/utils/config/loader.py:122-162`).
stdlib + pydantic only — no layering issue (contrast Phase-1 A.3).

Wiring: `ProcessingConfig` (`models.py:662-682`) gains
`parallelism: ParallelismConfig = Field(default_factory=ParallelismConfig)` next to
`processing: ProcessingParams` (:671); `defaults/processing.yaml` and
`config/processing.yaml.example` gain a commented `parallelism:` block.

```python
class ParallelismConfig(BaseModel):
    """Machine-resource parallelism settings (how), separate from science params (what)."""

    # mode = STEP EXTENT, not merely a core count (revised 2026-07-03, stream doc §9):
    #   "daily"   = single-day step: one day's task list per invocation
    #               (1-2 files/receiver; latency irrelevant — next data
    #               arrives tomorrow). Worker cap cores//2 as a CONSEQUENCE
    #               (headroom on shared machines).
    #   "backlog" = multi-day step: task descriptors for the ENTIRE requested
    #               date range prepared and flat-submitted into the one pool
    #               (no per-day batching, no file splitting). All cores as a
    #               CONSEQUENCE (dedicated machine / off-hours throughput).
    mode: Literal["backlog", "daily"] = "daily"
    max_workers: int | Literal["auto"] = "auto"
    memory_fraction: float = Field(0.5, gt=0.0, le=1.0)
    large_file_threshold_mb: float = Field(50.0, gt=0)   # consumed by Phase-3 temp-Zarr return path; inert until then
    worker_idle_timeout_s: float = Field(300.0, gt=0)    # loky `timeout=`; default 10 s is too short for write pauses
    executor: Literal["process", "dask"] = "process"     # "dask" = remote scheduler only
    scheduler_address: str | None = None
    nice_priority: int = Field(0, ge=0, le=19)
    cpu_affinity: list[int] | None = None

    @model_validator(mode="after")
    def _dask_requires_scheduler(self) -> ParallelismConfig:
        # executor="dask" without scheduler_address is the retired LocalCluster
        # path — warn and coerce to "process" for one release, then error.
        ...

    @staticmethod
    def gil_enabled() -> bool:
        fn = getattr(sys, "_is_gil_enabled", None)
        return True if fn is None else fn()

    def executor_kind_for(self, reader_format: str) -> Literal["thread", "process"]:
        # Always "process" today: both RINEX and SBF tasks are >80-90 % GIL-held
        # Python (audit §7.3). Kept as the single hook where the free-threaded
        # (3.14t) path plugs in; `reader_format` reserved for per-format policy.
        return "thread" if not self.gil_enabled() else "process"

    def resolved_max_workers(
        self,
        *,
        cpu_count: int | None = None,
        available_memory_gb: float | None = None,
        est_worker_peak_gb: float | None = None,
    ) -> int:
        cpus = cpu_count or os.cpu_count() or 2
        if self.max_workers != "auto":
            n = min(self.max_workers, cpus)
        elif self.mode == "backlog":
            n = cpus                       # throughput mode: all cores
        else:  # daily
            n = max(1, cpus // 2)          # cron/operational: leave headroom
        if available_memory_gb and est_worker_peak_gb:
            n = max(1, min(n, int(available_memory_gb * self.memory_fraction / est_worker_peak_gb)))
        return n
```

Design decisions:

- **`mode` means step extent; the worker cap is a consequence** (revised
  2026-07-03 per stream doc §9). `backlog` = multi-day step: the driver
  prepares task descriptors across the *whole* date range and flat-submits
  them into the one pool (the flat multi-day shape at pipeline.py:825-830) —
  natural parallelism across days, no per-day batching; the only remaining
  per-day serial work is the driver-side aux-Zarr build, a cheap pre-step
  per date. `daily` = single-day step: one day's 1–2 files per receiver per
  cron invocation, latency irrelevant. The `auto` worker resolution follows
  from that intent: `backlog` = all cores (dedicated machine/off-hours);
  `daily` = `max(1, cores // 2)` (headroom on shared machines). These
  replace both `resource_mode: auto` and the scattered hardcoded 12s.
  Architecturally, `daily` is the degenerate case of the backlog machinery
  (stream doc §9.5) — the default is optimized for backlog throughput, and
  daily gets that default with the politer cap; nothing else forks on
  `mode`. One backlog-specific expectation to carry into benchmarking: once
  parse is fast (RINEX now; SBF post-decode-fix), the **sequential writer is
  the backlog throughput ceiling** (~4.6 s of parse per receiver-day at
  N = 8 vs one commit per receiver-day; stream doc §9.4) — the remedy is the
  Phase-3 streaming-writer overlap, never a second writer or pool change.
- **Memory cap formula**: `available_memory * memory_fraction / per_worker_peak
  estimate`, floored at 1. The *formula* is pure and unit-testable in the model
  (fake cpu/ram injected via kwargs); the *facts* come from the orchestrator at
  pool-creation time: `psutil.virtual_memory().available` (psutil becomes explicit,
  §5 change 5) and a per-worker peak estimate. Until a measured estimate exists the
  orchestrator passes `est_worker_peak_gb=None` and the cap is inactive — do **not**
  guess a peak; post-Task-B payloads make CPU the binding constraint.
  `large_file_threshold_mb` is plumbed now, consumed by Phase 3 (worker writes temp
  Zarr and returns a path for results above it).
- **`executor_kind_for(reader_format)` stays** — always `"process"` now, five lines,
  documents why, and is the one place the free-threaded future plugs in (gated,
  §7 Q6).
- **loky mapping**: `resolved_max_workers()` → `max_workers=`,
  `worker_idle_timeout_s` → `timeout=`, `nice_priority`/`cpu_affinity` → applied
  inside `initializer`. Because `get_reusable_executor()` is a singleton keyed on
  its parameters, the config **is** the pool identity — same resolved config, same
  warm pool, across every processor and day in the run.

### 3.3 CLI `--workers` mapping

Verified flow today: `canvodpy/src/canvodpy/cli/run.py:74-77` defines `--workers`
(help text still says "Number of Dask workers"); `main()` (:285) passes
`n_workers=args.workers` at :304 (dry-run) and :328 →
`Site.pipeline(n_workers=...)` (`canvodpy/src/canvodpy/api.py:130`, forwarded :187)
→ `Pipeline.__init__` (`api.py:264`), where the explicit-`n_workers` branch
(:291-315) bypasses `resolve_resources()` entirely.

After:

```python
# Pipeline.__init__ (api.py:291-315 replaced)
pcfg = config.processing.parallelism
if n_workers is not None:                       # CLI/API override — highest precedence
    pcfg = pcfg.model_copy(update={"max_workers": n_workers})
self._orchestrator = PipelineOrchestrator(site=..., parallelism=pcfg, ...)
```

- Keep the `n_workers` kwarg on `Site.pipeline` and `Pipeline` (1:1 with
  `max_workers`); `run.py` needs only a help-text fix at :77 ("Max worker
  processes (overrides parallelism.max_workers)").
- Add an explicit `--mode {backlog,daily}` flag (default: config value) — the
  runner's two real usage patterns (backfill vs cron) become first-class. Do
  **not** infer `backlog` from `--start/--end` presence (too magic).
- `_print_header` (`run.py:168-183`) prints parallelism mode/workers instead of
  `resource_mode`.
- Precedence, documented once: **CLI flag > `Site.pipeline()` kwarg >
  `processing.yaml` `parallelism:` > model defaults** (flag and kwarg are the same
  mechanism).

### 3.4 Legacy bridge mechanism

A `model_validator(mode="after")` on `ProcessingConfig` (not `ProcessingParams`):
when any legacy field was user-set **and** no `parallelism:` section was provided,
synthesize `self.parallelism` from the legacy values per the table in §3.1 and warn
once, naming the replacement. If both are set, `parallelism:` wins and the validator
warns that legacy fields are ignored. Old `processing.yaml` files keep working
unchanged for one release.

---

## 4. Pool placement (Q4)

### 4.1 Verified: receivers are processed strictly sequentially today

`parsed_rinex_data_gen` (`processor.py:2558`) loops over receiver configs
(:2657 ff.): per receiver — parse all files in parallel
(`_parallel_process_rinex`, :2725-2735) → **write** (`_append_to_icechunk`,
:2783) → yield. The pool (today: fresh per receiver-day) idles during each
receiver's write. The two-receiver variant `parsed_rinex_data_gen_2_receivers`
(:2206) follows the same per-receiver sequence.

### 4.2 Decision: **Option A — one global pool** (all receivers, formats, days)

- **Per-receiver pools buy nothing.** Receiver parallelism is a property of the
  *task list*, not the pool: canopy + reference files submitted into one N-worker
  pool interleave exactly as well as two N/2 pools, without capacity fragmentation
  when one receiver's day is smaller or absent. The flat multi-day Dask path
  already proves the shape — it submits (date × receiver × file) into one cluster
  (`pipeline.py:825-830`).
- **Against the write constraint**: end-to-end per day ≈
  `parse_all_files / N_workers + write_canopy + write_reference` (writes strictly
  serial, one Icechunk commit per receiver-day). Two pools cannot shrink the write
  term — it is serialized by the store, not by the pool. What per-receiver overlap
  *could* do (parse B while writing A) requires cross-receiver submission, which is
  a task-scheduling change on one shared pool anyway — deferred to Phase 3, where
  the streaming writer makes it fall out naturally. Verdict: per-receiver pools do
  **not** reduce end-to-end latency for a 2-receiver site; they only fragment
  capacity.
- **loky reinforces Option A**: `get_reusable_executor()` is a process-global
  singleton — two "pools" with different parameters would tear each other down on
  every alternation. One shared parameterization is the natural (and only sane)
  usage.
- Sizing for mixed SBF/RINEX sites: no reserved lanes. Submit large files first
  (`file_list.sort(key=size, reverse=True)` — one line in `prepare_batch_tasks`,
  `processor.py:2376`); a 24 h SBF file occupies one worker while RINEX flows
  through the rest — LPT handles the scheduling; the residual is memory
  co-scheduling (N largest decodes start simultaneously), guarded by the
  memory-based worker cap, not the sort (stream doc §10.3). Intra-file
  splitting is **not** on the default-stream roadmap (2026-07-03 constraint:
  every file touched exactly once; splitting is a custom-profile opt-in only,
  stream doc §5/§7). SBF throughput is gated on the decoder fix (§1 scope
  note), not on splitting.

### 4.3 Pool ownership and worker init

The pool factory is wrapped in a small module —
`canvodpy/src/canvodpy/orchestrator/executor.py`:

```python
def _worker_init(nice_priority: int = 0, cpu_affinity: list[int] | None = None,
                 ephemeris_pickle: bytes | None = None) -> None:
    import canvodpy.orchestrator.processor  # noqa: F401 — pay the 3.05 s import once, visibly
    # politeness (Linux-only; mirrors resources.py:108-135)
    ...os.sched_setaffinity / os.setpriority...
    if ephemeris_pickle is not None:        # §2.4 hook — unused day one
        _worker_globals.EPHEMERIS = pickle.loads(ephemeris_pickle)

def get_executor(cfg: ParallelismConfig, **runtime_facts) -> Executor:
    """Thin wrapper over loky.get_reusable_executor — config → kwargs mapping only."""
    return get_reusable_executor(
        max_workers=cfg.resolved_max_workers(**runtime_facts),
        timeout=cfg.worker_idle_timeout_s,
        initializer=_worker_init,
        initargs=(cfg.nice_priority, cfg.cpu_affinity),
    )
```

- **No `ExecutorManager` lifecycle class** (the PPE draft needed one; loky doesn't):
  the singleton *is* the lifecycle. `PipelineOrchestrator.close()`
  (`pipeline.py:174-179`) additionally calls
  `get_reusable_executor().shutdown(kill_workers=True)` guarded by a
  did-we-use-loky flag, for deterministic teardown in tests and `with` blocks;
  loky's own atexit handling covers hard exits.
- **Design rule: no result-typed helpers in `executor.py`** — it returns a bare
  `Executor` so the same pool serves both worker-return shapes (§6).
- `RinexDataProcessor` **borrows, never owns**: `__init__` (`processor.py:576-585`)
  gains `executor: Executor | None = None`; `_parallel_process_rinex_pool` uses
  `self._executor` when injected, else calls `get_executor(...)` itself (which,
  being a singleton, is still the shared pool — the injection exists for testability
  and for passing a mock/thread executor).
- Selection rule replacing `_use_processpool` (`pipeline.py:135`):
  `parallelism.executor == "dask"` **and** `scheduler_address` set →
  `cluster_manager` (remote connect only, `resources.py:207` branch); otherwise →
  loky. `LocalCluster` creation (`resources.py:227`) becomes unreachable from the
  orchestrator.

### 4.4 Bounded submission window (producer-consumer, decided pattern)

Replace the submit-everything dict comprehension (`processor.py:1449-1464`) with the
bounded window:

```python
window = executor._max_workers * 2          # or resolved_max_workers * 2
file_iter = iter(rinex_files)
pending: dict[Future, Path] = {}
for f in itertools.islice(file_iter, window):
    pending[executor.submit(preprocess_with_hermite_aux, f, ...)] = f
while pending:
    for fut in as_completed(list(pending)):
        f = pending.pop(fut)
        try:
            results.append(fut.result())    # Phase 2: still collect-then-write
        except (OSError, RuntimeError, ValueError) as e:
            ...existing per-file error handling (processor.py:1498-1508)...
        nxt = next(file_iter, None)
        if nxt is not None:
            pending[executor.submit(preprocess_with_hermite_aux, nxt, ...)] = nxt
```

Natural backpressure: at most `2 × max_workers` futures (and their returned
datasets) in flight. The 2N window is mode-independent and final (stream doc
§9.3): its job is bounding *driver memory*, not feeding the pool — any window
≥ N + refill-latency (~0.2 ms) keeps workers saturated, so a larger backlog
window buys zero throughput while pinning more ~155 MB results in the driver
for hours. Phrase the window (and its tests) in **tasks**, not files. **Phase-2 scope note**: results still accumulate into
`results` for the existing batch write (`_append_to_icechunk`, :2783) — the
per-result `writer.write(result)` from the research pattern is the Phase-3
streaming writer; this loop is deliberately shaped so Phase 3 only swaps
`results.append` for `write_strategy.write`. The in-flight cap is what Phase 2
delivers (driver holds ≤ window results *plus* the day's collected list — the
collected list shrinks to Phase-3's queue later).

---

## 5. Fork/merge compatibility (Q5)

**Answer: yes — the same long-lived loky pool serves both the sequential-write path
(today) and the fork/merge path (future S3), by construction.**

- **The Icechunk session/fork is a task argument, not worker state.** Verified in
  `_cooperative_distributed_writing`: the driver opens the session and creates ONE
  fork (`session.fork()`, `processor.py:3097`), the fork is pickled into every
  submitted task (:3143-3156 PPE branch), each task's copy diverges in the worker,
  mutated copies return by value, and the driver merges + commits
  (`session.merge(*remote_sessions)` :3168, `session.commit` :3170-3172).
  `worker_task_with_region_auto` (:505-538) holds nothing between calls — the fork
  arrives as an arg and leaves as the return value. A worker that runs 500
  fork-tasks over 30 days retains zero session state. Pool reuse is safe.
- **loky specifics**: `ForkSession` is picklable by design (already crosses the PPE
  boundary today); loky's cloudpickle serialization is a superset of what stdlib
  PPE already handles here. Worker idle-timeout recycling (a worker dying after
  300 s idle and respawning on demand) is invisible to the fork pattern for the
  same reason — no state lives in the worker. The respawned worker re-pays the
  3.05 s import inside `_worker_init`, off the critical path.
- **Return-shape agnosticism**: the sequential path submits
  `preprocess_with_hermite_aux` → `(Path, Dataset, aux, sids)`; the fork path
  submits `worker_task_with_region_auto` → `ForkSession`. The executor is
  return-type-agnostic; the §4.3 design rule (bare `Executor`, no result-typed
  wrappers) keeps it that way. Phase 3's `WriteStrategy` chooses which worker
  function to submit and how to finalize — it swaps paths without touching the pool.
- Transition detail: `_cooperative_distributed_writing` prefers Dask when a client
  exists (:3101). After this phase orchestrators no longer create local Dask
  clients, so its PPE branch (:3134-3165) becomes the default; inject the shared
  executor there too (change 3) so it stops creating throwaway pools.
- Known blockers of the fork path itself are **Phase-3 items, unchanged by this
  phase**: double parse in the pre-scan (:3063-3086), `append_dim` vs pre-sized
  arrays, dedup-before-dispatch (audit §7.12). Nothing here worsens them.

---

## 6. Change list

Ordered; changes 1–2 are shippable with zero behaviour change (config only),
3–4 flip the machinery, 5–7 are dependencies/docs.

```
CHANGE 1 — Add ParallelismConfig
FILE: packages/canvod-utils/src/canvod/utils/config/parallelism.py
LINES: new file (~90 lines)
WHAT: ParallelismConfig model per §3.2 (mode, max_workers, memory_fraction,
      large_file_threshold_mb, worker_idle_timeout_s, executor, scheduler_address,
      nice_priority, cpu_affinity; resolved_max_workers, executor_kind_for,
      gil_enabled, dask-requires-scheduler validator).
HOW:  New BaseModel; stdlib + pydantic imports only. Re-export from
      canvod/utils/config/__init__.py and models.py.
TESTS: new packages/canvod-utils/tests/test_parallelism_config.py —
      resolved_max_workers matrix (auto×backlog=cpus, auto×daily=cpus//2,
      explicit capped by cpu_count, memory cap active only when both
      available_memory_gb and est_worker_peak_gb given); executor_kind_for under
      monkeypatched sys._is_gil_enabled; validator coerces dask-without-scheduler
      to process with warning.

CHANGE 2 — Deprecate legacy ProcessingParams resource fields
FILE: packages/canvod-utils/src/canvod/utils/config/models.py
LINES: ProcessingParams fields :142-148 (resource_mode), :149-157 (n_max_threads),
       :208-212 (max_memory_gb), :213-216 (cpu_affinity), :217-222 (nice_priority),
       :223-233 (threads_per_worker), :243-251 (parallelization_strategy),
       :252-260 (scheduler_address); validator :273-296; resolve_resources
       :298-324; ProcessingConfig :662-682.
WHAT: Add `parallelism: ParallelismConfig` field to ProcessingConfig; bridge
      legacy fields; deprecate resolve_resources().
HOW:  Field descriptions on the 8 legacy fields gain "(deprecated — use
      parallelism.*)"; model_validator(mode="after") on ProcessingConfig
      synthesizes parallelism from legacy values when user-set and no
      parallelism: section (§3.1 table, §3.4 precedence); resolve_resources()
      becomes a delegate over the synthesized config + DeprecationWarning.
      Migrate consumers: api.py:305 (replaced by change 4), pipeline.py:1329
      (__main__ demo rewritten), processor.py:2097-2106 (store metadata fed from
      parallelism.resolved_max_workers(); canvod-store-metadata field names
      dask_workers/dask_threads_per_worker stay — renaming the ~90-field DataCite
      schema is out of scope), packages/canvod-store/src/canvod/store/reader.py:165,
      diagnostics/timing_diagnostics_script.py:144.
TESTS: packages/canvod-utils/tests/test_config_models.py:91-140
      (resource_mode/n_max_threads tests) keep passing (deprecated, not removed);
      extend with pytest.warns(DeprecationWarning) + bridge-synthesis assertions
      (manual/N → parallelism.max_workers==N; explicit parallelism: wins + warns).

CHANGE 3 — Long-lived loky pool; move creation out of per-receiver-day scope
FILE: canvodpy/src/canvodpy/orchestrator/executor.py (new, ~60 lines);
      canvodpy/src/canvodpy/orchestrator/processor.py;
      canvodpy/src/canvodpy/orchestrator/pipeline.py
LINES: pool creation today: processor.py:1448 (_parallel_process_rinex_pool) and
       :3140 (_cooperative_distributed_writing). Injection points:
       RinexDataProcessor.__init__ :576-585; dispatch :1254-1277;
       pipeline.py :135 (_use_processpool), :158-172 (cluster_manager),
       :174-179 (close), :492-497 and :608-613 (processor construction),
       :1235 + :1302-1307 (SingleReceiverProcessor), processor.py:3030
       (DistributedRinexDataProcessor hardcoded 12).
WHAT: Replace both per-day `with ProcessPoolExecutor(...)` blocks with the shared
      loky reusable executor; pool identity owned by config, teardown by
      PipelineOrchestrator.close().
HOW:  executor.py provides _worker_init (eager `import
      canvodpy.orchestrator.processor`; apply nice/affinity; optional
      ephemeris_pickle hook per §2.4) and get_executor(cfg) mapping
      ParallelismConfig → loky.get_reusable_executor(max_workers, timeout,
      initializer, initargs). RinexDataProcessor gains `executor: Executor | None
      = None`; _parallel_process_rinex_pool uses injected executor or
      get_executor(cfg) — no `with` block, no shutdown in the method. Same
      injection into _cooperative_distributed_writing (:3140 branch). Dispatch
      precedence: injected/loky executor by default; Dask only when
      parallelism.executor=="dask" and scheduler_address set (LocalCluster
      creation at resources.py:227 becomes unreachable from the orchestrator).
      pipeline.py passes executor into processors at :492-497/:608-613; drop
      hardcoded n_max_workers=12 at pipeline.py:1235 and processor.py:3030 in
      favour of resolved config. close() additionally shuts the reusable
      executor down (kill_workers=True) when it was created. BrokenProcessPool
      handling: none needed — loky respawns crashed workers; the failed task
      surfaces as TerminatedWorkerError at fut.result(), added to the per-file
      except tuple at processor.py:1498-1508 (log + count, batch continues).
TESTS: new canvodpy/tests/test_executor_lifecycle.py — same executor object across
      two RinexDataProcessor runs (identity check: the regression this phase
      exists to prevent); worker crash (task calling os._exit(1)) →
      TerminatedWorkerError on that future only, next task on the same pool
      succeeds; close() is idempotent. Integration (marked): 2-day × 1-receiver
      run asserting byte-identical store output vs the per-day-pool baseline, plus
      standing gates `uv run pytest packages/canvod-audit/tests/` and
      `uv run pytest -m "not integration"`.

CHANGE 4 — Bounded submission window in the pool path
FILE: canvodpy/src/canvodpy/orchestrator/processor.py
LINES: :1449-1464 (upfront dict-comprehension submit), drain loop :1479-1508;
       prepare/task-list at :2376 (prepare_batch_tasks).
WHAT: Cap in-flight futures at 2 × max_workers; submit large files first.
HOW:  Replace submit-all with the islice window + as_completed refill loop (§4.4),
      preserving the existing progress bar (:1478-1481) and per-file error
      handling (:1498-1508, extended with loky's TerminatedWorkerError). One-line
      size-descending sort of the file list in prepare_batch_tasks
      (processor.py:2376). Results still collected for the existing batch write —
      the per-result streaming write is Phase 3; keep the loop body shaped so
      Phase 3 swaps `results.append(...)` for `write_strategy.write(...)`.
TESTS: unit test with a fake executor asserting never more than 2×N pending
      futures for a 10×N file list and that all results arrive; existing
      processor tests unchanged (same function, same return shape).

CHANGE 5 — CLI --workers → ParallelismConfig.max_workers
FILE: canvodpy/src/canvodpy/api.py; canvodpy/src/canvodpy/cli/run.py
LINES: api.py — Site.pipeline :126-193 (n_workers kwarg :130, forward :187);
       Pipeline.__init__ :259-345 (resolve branch :291-315, orchestrator
       construction :334-336). run.py — flag :74-77, _print_header :168-183,
       main() n_workers pass-through :304 and :328.
WHAT: Route the CLI/API override through the model instead of bypassing it.
HOW:  Pipeline.__init__ replaces the :291-315 branching with
      `pcfg = config.processing.parallelism`, `model_copy(update={"max_workers":
      n_workers})` when given, and passes `parallelism=pcfg` to
      PipelineOrchestrator. Keep n_workers kwarg (maps 1:1). run.py: fix --workers
      help text ("Max worker processes (overrides parallelism.max_workers)"), add
      `--mode {backlog,daily}` (default from config) mapped via the same
      model_copy, _print_header prints parallelism mode/workers.
TESTS: canvodpy/tests/test_public_api.py:92,120,147,225 assert exact
      Pipeline→PipelineOrchestrator constructor kwargs incl. threads_per_worker —
      these WILL break; rewrite to assert the parallelism object. New parse-level
      test: main(argv=["--site","X","--workers","3","--dry-run"]) with mocked Site
      reaches ParallelismConfig.max_workers==3; `--mode backlog` reaches
      mode=="backlog".

CHANGE 6 — Dependencies: loky + explicit psutil
FILE: canvodpy/pyproject.toml
LINES: [project].dependencies list (dask entry at :38)
WHAT: Add loky (new — verified absent from uv.lock; no joblib in tree either) and
      make psutil explicit (currently transitive via distributed, uv.lock:2526).
HOW:  Add `"loky>=3.4"` and `"psutil>=5.9"` to canvodpy dependencies (the pool
      lives in canvodpy/orchestrator; no other package imports it). psutil is
      loky's opt-in enabler for memory-leak and zombie-worker detection, and the
      orchestrator uses it for available-memory facts (§3.2). `uv sync` +
      lockfile update. Keep `dask[distributed]>=2026.1.1` pending §7 Q1.
TESTS: `uv run python -c "from loky import get_reusable_executor"`; CI lockfile
      check; no test-suite impact.

CHANGE 7 — Docs nav: dask-resources.md is now wrong-named
FILE: zensical.toml (nav entry :107 — { "Dask & Resource Management" =
      "guides/dask-resources.md" }); referenced from docs/index.md:77,
      docs/guides/configuration.md:79, docs/packages/readers/overview.md:288.
WHAT: FLAG ONLY (per task instruction — do not edit the doc in this phase).
HOW:  Follow-up PR renames guides/dask-resources.md → guides/parallelism.md
      ("Parallelism & Resource Management"), rewrites content around
      ParallelismConfig/loky, updates the nav title at zensical.toml:107 and the
      three cross-references. Until then the guide describes the deprecated
      fields, which still work (change 2), so it is stale-but-not-lying.
TESTS: `uv run zensical build` link check in the follow-up.
```

Estimated size: ~150 lines new (`parallelism.py` + `executor.py`), ~200-300 lines
changed, excluding tests (~250-350).

Suggested landing order: 1 → 2 → 6 → 3 → 4 → 5 → (7 follow-up). 1+2+6 are inert;
3 is the behaviour flip; the integration gate (change 3 TESTS) runs after 4.

---

## 7. Open questions (maintainer input needed before/while Sonnet builds)

1. **Does anyone use `scheduler_address` / remote Dask?** If no: delete the Dask
   executor path in a fast-follow (drop `dask[distributed]` from
   canvodpy/pyproject.toml:38, remove `resources.py:152-289`,
   `canvodpy/tests/test_dask_lifecycle.py`, the `executor: "dask"` enum value). If
   yes: it stays as scoped here (remote connect only, `resources.py:207` branch).
2. **Delete dead/experimental code first?** `worker_task` (processor.py:429) and
   `worker_task_append_only` (:471) have zero callers — recommend deleting in this
   PR. `DistributedRinexDataProcessor` (:3011) + `parsed_rinex_data_gen_parallel`
   (:3175) are uninstantiated but are the fork/merge prototype — recommend keep,
   inject the shared executor (change 3), mark experimental in the docstring.
   `SingleReceiverProcessor` (pipeline.py:1208) has near-zero callers — port
   minimally (drop hardcoded 12) or deprecate?
3. **`mode` default = `daily`** (polite on shared machines) — confirm, and confirm
   whether the Airflow DAGs should pin `mode` per DAG (backfill DAG → `backlog`).
   Note the revised semantics (§3.2, 2026-07-03): `mode` now selects the *step
   extent* (single-day vs whole-date-range flat submission), with the worker cap
   as a consequence — a backfill DAG pinning `backlog` therefore also opts into
   multi-day flat submission, which is the intended pairing.
4. **`max_memory_gb` retirement**: `memory_fraction` (relative) replaces it
   conceptually, but shared-server operators may prefer absolute caps. Bridge maps
   the legacy absolute value into the cap for one release — keep an absolute
   `max_memory_gb` on `ParallelismConfig` permanently (absolute wins when set), or
   fraction only?
5. **loky version pin**: `>=3.4` assumed (reusable-executor API stable since 3.x);
   Sonnet should verify the latest release and whether `timeout` +
   `initializer`/`initargs` signatures match on the pinned version before wiring.
6. **Free-threaded trigger**: `executor_kind_for` flips to threads automatically
   when `gil_enabled()` is False. Gate behind an explicit opt-in
   (`allow_free_threaded: bool = False`)? Recommend yes — numpy/zarr thread-safety
   under 3.14t is unaudited for this codebase.
7. **Ephemeris initargs hook** (§2.4): agreed to ship unwired? Wiring it per-day
   means calling `get_reusable_executor` with new `initargs` daily → one worker
   restart cycle per day. Only worth it if post-Phase-1 profiling shows per-task
   aux-Zarr open/load (processor.py:242-249) as a visible cost.
8. **Interrupt semantics for multi-day batches**: with `days_per_batch > 1`
   (`_process_multi_day_batches`, pipeline.py:648), an interrupt lands between
   receiver-day commits; resume logic (`run.py:88-136`) handles the partial state
   today. Confirm no stronger transactional guarantee is expected before Phase 3
   adds `session.flush` checkpointing.
