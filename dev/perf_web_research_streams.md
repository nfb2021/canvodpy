# Web Research: Python Parallelization for Heterogeneous Workloads

**Context:** Stream architecture for canvodpy GNSS pipeline — one loky ProcessPool,
bounded submission window, sequential Icechunk writer. File classes range from 0.39 s
(15-min RINEX) to ~6 min (24 h SBF). Research validates/refines the "one physical stream
+ per-task profiles" plan.

---

## Q1 — The Straggler Problem in Python Process Pools

### Does loky / ProcessPoolExecutor do work-stealing?

**Finding:** Yes, but only in a limited sense. Loky's architecture is described in 2026
tooling docs as "FIFO-with-stealing" — it uses work-stealing inspired by Cilk for
load balancing across its managed processes. However, "work-stealing" in this context
means a worker with an empty local deque can pull tasks from another worker's deque
*before* they start executing — it does **not** mean that a slow in-flight task can be
preempted and moved. Once a task is running in a worker process it runs to completion.
There is no preemption in loky, CPython's `ProcessPoolExecutor`, or any standard Python
pool.

**Practical implication:** Loky will balance the *queue* of pending tasks across workers,
but it cannot rescue a worker already pinned on a 6-minute SBF parse. The 24 h
straggler must be broken into chunks *before* submission, not handled dynamically by the
pool.

**Sources:**
- [Loky docs — Reusable Process Pool Executor](https://loky.readthedocs.io/en/stable/)
- [GitHub: joblib/loky](https://github.com/joblib/loky)
- [Python Batch Processing with Joblib/Loky Backends Scheduling 2026](https://johal.in/python-batch-processing-with-joblib-parallel-loky-backends-scheduling-2026/)

**Relevance to canvodpy:** Confirms that intra-file splitting at task-preparation time
(the proposed "profile" approach) is the only viable path. Pool-level scheduling cannot
fix a straggler that's already running.

---

### What is the received wisdom on minimum task duration?

**Finding:** The community consensus is that tasks shorter than ~10–50 ms are poor
candidates for process pools; multiprocessing becomes beneficial when tasks take "tens or
hundreds of milliseconds of pure CPU." The main overhead is process-to-process IPC +
pickling of arguments/results. A tight CPU loop that takes 1 ms per call has been
documented to run *slower* in an 8-process pool than serially, because pickling overhead
dominates.

The pipeline's measured values:
- 15-min RINEX: 0.39 s/file — well above the threshold; pool is appropriate.
- 15-min SBF: 3.69 s/file — firmly in the good range.
- 24 h RINEX: ~25–37 s — excellent for a pool, but 1 task/receiver-day pins one worker.
- Epoch chunks from splitting a 24 h file: if split into K=8, each chunk ≈ 3–4.6 s —
  still well above the amortization floor.

**Sources:**
- [Top 5 Ways to Boost Python Multiprocessing Performance — Techbuddies Studio](https://www.techbuddies.io/2026/03/17/top-5-ways-to-boost-python-multiprocessing-performance-and-cut-ipc-overhead/)
- [Speed Up Your Python Program With Concurrency — Real Python](https://realpython.com/python-concurrency/)

**Relevance to canvodpy:** Epoch-range chunks of K=N are each 3–5 s, which is
comfortably above the amortization floor. No "chunks too small" risk at N=8. If N scales
to 32, revisit: 37 s / 32 = 1.2 s/chunk, still above the 10-ms floor but getting leaner.

---

### Does `as_completed` + bounded submission window handle stragglers naturally?

**Finding:** No — `as_completed` yields futures as they finish and is useful for
*result collection*, but it provides no feedback to the *submission* side about task
duration. The standard library's `ProcessPoolExecutor` does not implement backpressure:
calling `executor.submit()` in a tight loop will queue all tasks immediately, exhausting
memory on large task sets.

Two practical patterns exist:
1. **Semaphore-bounded submission:** A `threading.Semaphore(max_queued)` is acquired
   before each `submit()` and released in the future's `add_done_callback`. This is
   exactly the bounded-window pattern proposed in the plan. Libraries
   `bounded_pool_executor` and `futureproof` package this pattern.
2. **`futureproof`:** Wraps `concurrent.futures` with lazy task consumption, backpressure,
   and error propagation. Relevant if the pipeline ever grows to millions of tasks.

Neither approach changes *which* task is slow; they only prevent queue saturation.

**Sources:**
- [GitHub: noxdafox — bounded concurrent.futures wrapper (gist)](https://gist.github.com/noxdafox/4150eff0059ea43f6adbdd66e5d5e87e)
- [GitHub: mowshon/bounded_pool_executor](https://github.com/mowshon/bounded_pool_executor)
- [GitHub: yeraydiazdiaz/futureproof](https://github.com/yeraydiazdiaz/futureproof)
- [concurrent.futures — Python 3 docs](https://docs.python.org/3/library/concurrent.futures.html)

**Relevance to canvodpy:** The bounded-semaphore submission pattern is confirmed as the
right idiom. It does not solve the straggler — it prevents queue bloat. The straggler is
solved by pre-splitting.

---

## Q2 — File-Splitting Patterns for Large Sequential Scientific Data

### RINEX-specific: splitting epoch records

**Finding:** No published Python implementation of intra-file parallel RINEX parsing was
found. Existing tools (GeoRinex, RinexParser, PyRINEX) are all single-pass sequential
readers. However, the structural analogy to FASTA is strong:

| Property | FASTA | RINEX observation |
|---|---|---|
| Record delimiter | `>` (first char) | `>` (first char of epoch line) |
| Header | Yes (metadata lines starting with `;`) | Yes (fixed-length header block) |
| Self-synchronizing | After any `>` line | After any `>` line |
| File size | Up to tens of GB | Up to ~100 MB for 24 h @ 1 Hz |

The FASTA community has solved exactly this problem. The canonical pattern (KDnuggets,
nurdabolatov):
1. Divide file size by N workers → N byte-offset pairs.
2. Each worker seeks to its start offset, reads forward to the next `>` line boundary,
   then processes to its end offset (or next `>` boundary, whichever comes last).
3. Workers are stateless after alignment; no inter-worker communication needed.

For RINEX, the header must be parsed once and passed (pickled) to all workers, since the
epoch records reference obs types declared in the header. The header is small (<2 KB
typical), so this is negligible.

**Measured FASTA performance:** On a 2.4 GB / 400 M line file, 4 workers reduced
wall time from 785 s to 548 s (~30% improvement). The gains are sub-linear on I/O-bound
files; on a CPU-bound task like RINEX string slicing the improvement would be closer to
linear (N× for N workers, up to I/O saturation).

**Tools:** `gfzrnx` already supports `--epoch-by-epoch` output and can split RINEX
by time window, making it a viable pre-splitter if implementing a pure-Python splitter
is not worthwhile.

**Sources:**
- [Parallel Processing Large File in Python — Nurda Bolatov](https://nurdabolatov.com/parallel-processing-large-file-in-python)
- [Parallel Processing Large File in Python — KDnuggets](https://www.kdnuggets.com/2022/07/parallel-processing-large-file-python.html)
- [GFZRNX splice/split documentation](https://gnss.git-pages.gfz-potsdam.de/gfzrnx/tasks/tasks_splice/)
- [PyRINEX — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10803049/)

**Relevance to canvodpy:** RINEX epoch-range splitting is straightforward to implement:
seek to byte offset, scan forward to next `>` line, parse to end offset. Header must be
pre-parsed and passed to each worker. `gfzrnx` is already bundled and can serve as a
file-level pre-splitter for the rare 24 h RINEX case if a Python splitter is not
implemented in Phase 1.

---

### SBF binary stream: self-synchronizing splits

**Finding:** The SBF `$@` sync-marker + CRC-16 design is equivalent to what the binary
stream literature calls a "self-synchronizing stream." The standard pattern:
1. **Index scan (serial, O(n)):** Walk the stream once, recording byte offsets of all
   `$@` sync markers that pass CRC check. This produces a sorted list of valid block
   boundaries.
2. **Divide index by N:** Each worker gets a slice of the offset list
   `[start_idx : end_idx]`. Workers seek directly to their block offsets — no alignment
   scan needed.
3. **State carry-across:** SBF does carry some inter-block state (receiver clock, last-
   known navigation message), but for the pipeline's use (SNR + satellite visibility) this
   state is either self-contained per block or already handled by the existing sequential
   reader's logic. The key question is whether the per-epoch auxiliary output (PVT, DOP)
   requires accumulated state.

For HDF5/NetCDF analogies: the geophysical community commonly splits on dimension
boundaries (e.g. time-step index ranges), not byte offsets, because the format stores
an index. For binary streams without an index, the byte-offset approach above is standard.

**Sources:**
- [Binary stream splitting — multiprocessing-chunks GitHub](https://github.com/malcolmvr/multiprocess-chunks)
- [Parallel Astronomical Data Processing with Python](https://arxiv.org/pdf/1306.0573)
- [Parallel netCDF — High-Performance I/O](https://arxiv.org/pdf/cs/0306048)

**Relevance to canvodpy:** SBF splitting requires a one-time index pre-scan (already
partially present in the reader's block-boundary logic). The result is a list of
`(byte_offset, block_count)` pairs that can be distributed to workers. The 24 h SBF
case (rare, ~6 min) is the highest-priority target for this work.

---

## Q3 — Priority Queues / Size-Descending Scheduling

### Is LPT the standard recommendation?

**Finding:** Yes. The Longest Processing Time first (LPT) rule, introduced by Graham
(1969), is the canonical greedy heuristic for heterogeneous task scheduling on identical
parallel machines. It requires sorting tasks in non-ascending order of processing time
and assigning each task to the currently least-loaded machine (worker).

**Theoretical makespan bound (identical machines):**

  `makespan(LPT) ≤ (4/3 - 1/(3m)) × OPT`

where m is the number of machines. For m=8 workers this is ≤ 1.292 × OPT.

A tighter bound was proven in 2018 (Della Croce et al., arXiv:1801.05489):

  `makespan(LPT) ≤ (4/3 - 1/(3(m-1))) × OPT`   for m ≥ 3

For **heterogeneous machines** (different processor speeds), LPT variants achieve at
most `2m/(m+1)` times optimal, which approaches 2× as m grows. The Multifit algorithm
(bin-packing heuristic) achieves a worst-case bound within 1.4× optimal on uniform
processors and is empirically better than LPT on skewed distributions.

**Does Python's pool support task priorities natively?**

No. Neither `concurrent.futures.ProcessPoolExecutor` nor loky expose a priority queue
interface. Task priority must be managed externally by **submission order**: tasks
submitted first are picked up first by idle workers. Therefore:

  - Submit tasks in LPT order (largest/slowest first).
  - The pool's internal FIFO queue ensures the first tasks submitted occupy all workers
    immediately, minimizing idle time.
  - Libraries like `heapq` or `queue.PriorityQueue` can maintain a pre-submission
    ordering if tasks arrive dynamically (e.g. live filesystem events).

**Sources:**
- [LPT — Journal of Scheduling, Springer](https://link.springer.com/article/10.1007/s10951-022-00742-w)
- [LPT revisited — arXiv:1801.05489](https://arxiv.org/abs/1801.05489)
- [Grokipedia — Longest Processing Time Scheduling](https://grokipedia.com/page/longest_processing_time_first_scheduling)
- [Priority Queue Python — DigitalOcean](https://www.digitalocean.com/community/tutorials/priority-queue-python)

**Relevance to canvodpy:** Size-descending submission is theoretically grounded and
trivially implemented (sort task list by estimated file-size-class before submission).
For a heterogeneous set of 15-min + 24 h files, LPT ensures the one 24 h file starts
immediately rather than being queued behind 95 small ones. With the proposed
pre-splitting, the 24 h file becomes K chunks of known size — these K chunks should also
be submitted before the small files to fill all workers.

---

## Q4 — Profile-Based Task Shaping vs Multiple Pools

### Single pool vs multiple pools: what does the literature say?

**Finding:** The tradeoff is well-understood:

| Approach | Pros | Cons |
|---|---|---|
| **Single pool** | Simple management, full resource sharing, no idle allocation between pools | No logical isolation; one slow task type can starve another if not managed |
| **Multiple pools** | Each pool tuned to its task type; isolation for debugging; separate thread/process counts | Resource fragmentation; a pool sized for rare large tasks wastes workers on idle days |

Python's `multiprocessing.Pool` documentation explicitly notes it is "designed to
execute heterogeneous tasks, where each task submitted may be a different target
function." SuperFastPython's guidance: multiple pools are worth it when pipeline
*stages* have genuinely different parallelism characteristics (e.g. CPU-bound parse
followed by I/O-bound upload), not when task types merely have different durations.

For canvodpy, all tasks are CPU-bound Python (GIL-held >80%) feeding the same
sequential writer. There is no I/O stage that could benefit from a separate thread pool.

**Spark AQE as a lessons-learned source:**

Spark's Adaptive Query Execution handles skewed partitions at runtime by:
1. Monitoring task execution times and partition sizes mid-job.
2. Splitting oversized ("skewed") partitions into sub-partitions when they exceed
   `skewedPartitionFactor × median_size` and `skewedPartitionThresholdInBytes` (default
   256 MB).
3. Replicating the corresponding join side as needed.

The key Spark lesson: the split decision happens at the **stage boundary**, not mid-task.
Spark never interrupts a running task; it splits work for the *next* stage. This maps
exactly to the proposed plan: detect large files before submission, emit K chunk-tasks
instead of 1 file-task.

**joblib `batch_size` and its load-balancing logic:**

joblib's `batch_size="auto"` (default) adjusts batch size dynamically to keep each
dispatch round ≈ 0.5 seconds of work. Critically, joblib PR #899 added end-of-queue
balancing: when approaching the last tasks, it pre-fetches `batch_size × n_jobs` items
and rescales to `max(1, remaining // (10 × n_jobs))` to avoid "straggler batches" where
one worker holds a large batch while others finish. This is automatic load balancing at
the *batch* level, not the task level — relevant if canvodpy ever uses joblib's
`Parallel()` instead of raw `concurrent.futures`.

**Dask Bags and Prefect for per-task shaping:**

Dask's heterogeneous cluster support allows specifying `resources={"GPU": 1}` per task,
but this is for resource-type routing (GPU vs CPU workers), not duration-based shaping.
Prefect + DaskTaskRunner follows the same model. Neither framework provides native
"profile-based task transformation" (the ability to split a file into N tasks based on
a per-file profile object). This would need to be implemented in the task itself or in
a pre-processing step — exactly what the proposed profile system does.

**Sources:**
- [SuperFastPython — Multiprocessing Pool vs Process](https://superfastpython.com/multiprocessing-pool-vs-process/)
- [ThreadPoolExecutor Pipeline For Multi-Step Tasks — SuperFastPython](https://superfastpython.com/threadpoolexecutor-pipeline/)
- [Spark AQE skew mitigation — Medium](https://sachin-s1dn.medium.com/mitigating-partition-skew-with-adaptive-query-execution-aqe-7d09e9f9f0a3)
- [Spark AQE docs — Databricks](https://docs.databricks.com/aws/en/optimizations/aqe)
- [joblib Parallel — official docs](https://joblib.readthedocs.io/en/stable/parallel.html)
- [joblib PR #899 — load-balancing improvement](https://github.com/joblib/joblib/pull/899/files)
- [Dask heterogeneous workers discussion](https://github.com/dask/dask/discussions/7207)

**Relevance to canvodpy:** The single-pool + profiles architecture is the right design.
Multiple pools would fragment workers without benefit (all tasks are the same kind of
CPU work). The profile object (split vs no-split, estimated duration, submission
priority) is a design pattern not offered by existing frameworks — it needs to be
canvodpy-native.

---

## Q5 — The 1-Task/Day Utilization Ceiling and Chunk Granularity

### What chunk granularity maximizes throughput?

**Finding:** The general guidance across geophysical/scientific data communities:

- Pangeo/Dask best practices: chunks of **100 MB** for cloud I/O; for local CPU-bound
  work the target is chunks that keep each worker busy for "seconds, not milliseconds."
- rapidgzip: optimal chunk = 4–32 MiB for parallel gzip decompression (I/O-dominated).
- The general heuristic from parallel computing literature:
  **chunk duration should be at least 10–50× the dispatch overhead**, and
  **chunk count should be at least 2–4× the worker count** to absorb variance in
  per-chunk time.

For canvodpy's 24 h RINEX (37 s total, linear in epochs, N=8 workers):

| K chunks | Chunk duration | Chunk count / worker | Residual imbalance |
|---|---|---|---|
| K = N = 8 | 4.6 s | 1 | High — one slow chunk = straggler remains |
| K = 2N = 16 | 2.3 s | 2 | Better — idle worker picks up 2nd chunk |
| K = 4N = 32 | 1.2 s | 4 | Good balance, overhead starts to matter |
| K = 8N = 64 | 0.6 s | 8 | Overhead ~10% of task time — marginal |

The "2× to 4× worker count" rule (Dask guidance, also echoed in Spark's partition
sizing) suggests K=16 to K=32 for N=8. With 2.2 ms/epoch and ~40,000 epochs in a 24 h
@ 1 Hz RINEX, K=16 means ~2,500 epochs/chunk, each taking ~5.5 s — comfortably above
the amortization floor.

**Aux-data overhead per chunk:**

This is the canvodpy-specific wrinkle: each chunk must also receive ephemeris data for
its epoch range. If the ephemeris is pre-computed and serialized (via Icechunk or a
shared dict), the overhead per chunk is a dict lookup + pickling, not a full SP3
interpolation. If each chunk triggers an independent interpolation, the per-chunk cost
grows. The profile system should pre-compute ephemeris once and pass it as a shared
read-only object (a `Manager().dict()` or memory-mapped array) to avoid K×interpolation
blowup.

**For 24 h SBF (~6 min total, N=8):**

K = 2N = 16 chunks → ~22 s/chunk — well-amortized. K = 4N = 32 → ~11 s/chunk. Either
is fine. The main cost is the one-time index pre-scan for SBF block boundaries
(estimated <5 s for a 24 h file at typical SBF data rates).

**Sources:**
- [EOPF / Zarr chunking intro — Pangeo recommendations](https://eopf-toolkit.github.io/eopf-101/03_about_chunking/31_zarr_chunking_intro.html)
- [Airbyte — Parallelize Data Loading 2026](https://airbyte.com/data-engineering-resources/parallelize-data-loading-performance)
- [ESIP CCC — Cloud optimization practices](https://esipfed.github.io/cloud-computing-cluster/optimization-practices.html)
- [rapidgzip — Parallel Decompression arXiv:2308.08955](https://arxiv.org/pdf/2308.08955)
- [Parallel Astronomical Data Processing — arXiv:1306.0573](https://arxiv.org/pdf/1306.0573)

**Relevance to canvodpy:** Use K = 2N (default) with an option in `custom_profile` to
set K explicitly. Pre-compute ephemeris outside the chunk tasks and pass as a shared
read-only object. For 24 h RINEX at N=8, K=16 gives ~5 s chunks — optimal. Avoid K=N
(too coarse, one slow chunk remains a straggler).

---

## Synthesis: Do Web Findings Support the "One Physical Stream + Profiles" Plan?

### What is supported

1. **Single pool is correct.** All authoritative sources (joblib docs, SuperFastPython,
   Python docs) confirm that a single pool handling heterogeneous task durations is the
   idiomatic Python approach. Multiple pools would fragment workers without benefit when
   all tasks are the same compute archetype (CPU-bound Python parse → sequential write).

2. **LPT submission order is theoretically grounded.** Sort task list by descending
   estimated size before submission. Makespan bound: ≤ 1.29 × OPT for N=8 workers.
   Trivial to implement; should be default behavior, not optional.

3. **Bounded submission window (semaphore pattern) is confirmed practice.** The
   `futureproof` library and `bounded_pool_executor` package both implement exactly this.
   A Semaphore of size `2 × n_workers` (or configurable) is the standard idiom.

4. **Pre-submission splitting (profiles) mirrors how Spark, Hadoop, and AQE work.** None
   of these systems interrupt a running task. They all make split decisions at *task
   preparation time*, before the task enters the pool. The profile-based approach is
   architecturally equivalent to Spark's stage-boundary repartitioning.

5. **RINEX splitting is feasible** via the FASTA chunking pattern: byte-offset + forward
   scan to next `>` line. Header must be pre-parsed and passed to workers. `gfzrnx` is
   a viable alternative for pre-splitting if a Python splitter isn't implemented in
   Phase 1.

6. **SBF splitting is feasible** via an index pre-scan (`$@` + CRC check) to produce a
   block-offset list, then slice the list by K. One-time scan cost is acceptable.

### What is refined or challenged

1. **K = N is the wrong default chunk count.** The instinct to split into exactly N
   chunks (one per worker) is a classic mistake. If one chunk is 20% slower than the
   median, one worker finishes 20% late while others idle. K = 2N is the minimum safe
   default; K = 4N is better for files with non-uniform epoch density.

   **Change to plan:** Set default `K = 2 * n_workers` in profile defaults. Expose as
   `split_chunks_multiplier: int = 2` in `custom_profile`.

2. **Aux-data (ephemeris) overhead per chunk must be accounted for.** The plan is
   silent on this. If each chunk independently triggers SP3 interpolation, K=16 chunks
   means 16× the interpolation cost — which for a 24 h SP3 file could dominate. Pre-
   compute ephemeris once (producing an `xr.Dataset` of per-epoch satellite positions),
   serialize to a temp Zarr/Icechunk group or pass via a shared Manager object, and
   have each chunk worker read its slice.

   **Addition to plan:** Profile object should carry an `ephemeris_ref` (path or shared
   object handle) computed before task submission. This is a new planning item.

3. **Speculative execution is not worth adding for this pipeline.** Speculative
   execution (cloning a slow task and racing two copies) requires idempotent tasks and a
   way to cancel the loser. For Icechunk writes, the sequential writer assumption means
   tasks must complete in order. Cloning is incompatible with the current architecture.
   The pre-splitting approach is strictly superior for this use case.

4. **joblib's `batch_size="auto"` is not a substitute for explicit profiles.** joblib's
   dynamic batch sizing targets "each batch ≈ 0.5 s" — which would *merge* many 15-min
   RINEX tasks (0.39 s each) into batches of ~1. This flattens duration variance but
   introduces latency for result availability and complicates the sequential writer
   (which needs per-file granularity). If canvodpy ever switches to joblib, set
   `batch_size=1` and `pre_dispatch=2*n_jobs` to preserve per-task semantics.

5. **loky's "work-stealing" is real but limited.** It is queue-level stealing (pending
   tasks), not task preemption. This does reduce queue starvation on heterogeneous
   workloads where some tasks finish quickly and free up workers. It means that with
   K=2N chunks, the 50% of chunks not immediately assigned will be claimed by workers
   that finish their first chunk — which is the desired behavior.

### Verdict

The "one physical stream + profiles" recommendation is **well-supported** by the
literature. The two additions to the plan are:

- **K = 2N default** (not K = N) for intra-file chunk count.
- **Ephemeris pre-computation before chunk submission** to avoid K× interpolation blowup.

No finding challenges the core architecture. The main risk identified is the
ephemeris overhead per chunk, which is canvodpy-specific and not addressed by any
general-purpose framework.

---

*Research date: 2026-07-03*
