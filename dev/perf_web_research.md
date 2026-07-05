# Performance Research: Parallelization Strategies for Scientific Data Pipelines

*Research date: 2026-07-02 | Scope: web search synthesis, no local code examined*

---

## 1. ProcessPoolExecutor vs Dask LocalCluster for Local Single-Machine CPU-Bound Batch Processing

### Overhead per task

Dask's task scheduling overhead varies significantly by scheduler variant:

- **Dask threaded / synchronous scheduler (local):** ~50–90 microseconds per task. This is comparable to
  `concurrent.futures` raw dispatch.
- **Dask distributed (LocalCluster):** ~1 millisecond per task, because even on a single machine the
  distributed scheduler uses a TCP round-trip between the scheduler process and each worker process for
  each completed task ([Dask distributed efficiency docs](https://distributed.dask.org/en/stable/efficiency.html)).
- **`concurrent.futures.ProcessPoolExecutor`:** dispatch latency is similar to Dask threaded but without
  the scheduler overhead layer. Task results are returned via OS pipes/pickled IPC.

The practical implication: for tasks that run in seconds (e.g. parsing a 10 MB RINEX file), either
framework's per-task overhead is negligible. For many sub-100 ms tasks, `ProcessPoolExecutor` or Dask's
`multiprocessing` scheduler (which itself wraps `ProcessPoolExecutor`) will outperform `LocalCluster`
([Dask scheduling docs](https://docs.dask.org/en/stable/scheduling.html)).

### Scheduler added value for local workloads

Dask's `LocalCluster` (`dask.distributed`) adds a persistent scheduler process and worker processes that
can cache intermediates in memory across tasks, enable work-stealing, and emit rich diagnostics. For a
linear pipeline (read → process → write), this added machinery provides little benefit over raw
`ProcessPoolExecutor`. Dask's own docs recommend its multiprocessing scheduler (not distributed) for
"relatively linear workflows" with "small inputs/outputs like filenames and counts"
([Dask scheduling](https://docs.dask.org/en/stable/scheduling.html)).

### Independent benchmarks

A March 2025 benchmark found `multiprocessing.Pool` and `ProcessPoolExecutor` clearly underperform
relative to MPIRE and Ray when tasks involve **large data objects** passed across process boundaries,
because serialization cost dominates. Dask beats standard multiprocessing due to state management, but
MPIRE and Ray outperform Dask for single-machine workloads
([MPIRE benchmark on Towards Data Science](https://towardsdatascience.com/mpire-for-python-multiprocessing-is-really-easy-d2ae7999a3e9/),
[MPIRE GitHub](https://github.com/sybrenjansen/mpire)).

MPIRE's primary advantage over `ProcessPoolExecutor`: it uses **copy-on-write shared objects** when
`fork` is available (macOS/Linux), which avoids re-serializing large shared state (e.g., a lookup table)
for every task.

### Summary verdict

| Scenario | Recommendation |
|---|---|
| Linear read→process→write, tasks >1 s, small outputs | `ProcessPoolExecutor` (low overhead, simple) |
| Tasks share large read-only state (e.g., ephemeris tables) | MPIRE (fork + copy-on-write avoids copies) |
| Complex DAG with intermediates, monitoring needed | Dask LocalCluster |
| Sub-100 ms many small tasks | Dask threaded scheduler or `ThreadPoolExecutor` |

---

## 2. Long-Lived vs Short-Lived ProcessPoolExecutor

### Process spawn cost for heavy scientific stacks

Creating a `ProcessPoolExecutor` spawns `n_workers` fresh Python interpreters. On macOS/Linux with
`spawn` start method (macOS default since Python 3.8), each worker imports the entire Python environment
from scratch:

- **Rule of thumb:** if your task takes 50 ms but spawning takes 200 ms, `ProcessPoolExecutor` makes
  your code ~5× slower than serial execution ([SuperFastPython](https://superfastpython.com/processpoolexecutor-in-python/)).
- For stacks including numpy + xarray + zarr + icechunk, interpreter startup is typically **0.5–2 s
  per worker** (import of compiled extensions dominates). No precise published benchmark was found for
  this exact stack, but the 0.5–2 s range is consistent with documented behaviour for similar scipy
  stacks.
- Memory: each spawned worker adds ~20 MB of resident memory baseline; with numpy/xarray loaded this
  rises to 80–200 MB per worker depending on what is imported
  ([Medium: fork vs spawn](https://medium.com/@Nexumo_/python-multiprocessing-revisited-fork-vs-spawn-5b9216fd5710)).

### Recommendation: long-lived pools

Create **one** `ProcessPoolExecutor` at program startup and reuse it across all batches:

- Amortizes spawn cost over the lifetime of the program.
- Use the `initializer=` argument to preload heavy imports (numpy, xarray, zarr) once per worker at pool
  creation time rather than per task.
- A generator of futures (lazy `executor.submit`) avoids accumulating all futures in memory
  simultaneously ([SuperFastPython ProcessPoolExecutor guide](https://superfastpython.com/processpoolexecutor-in-python/)).
- Tinybird engineering documented killing and recreating `ProcessPoolExecutor` per batch as a source of
  significant latency regression; the fix was pool reuse
  ([Tinybird blog](https://www.tinybird.co/blog/killing-the-processpoolexecutor)).

### Known pitfall: future accumulation memory leak

Every `executor.submit()` call creates a `Future` object that holds a reference to the result until
collected. If hundreds of futures are submitted without collecting results, memory grows unboundedly.
Fix: bound in-flight submissions by draining futures in batches (e.g., sliding window of N futures)
([CPython issue #85754](https://github.com/python/cpython/issues/85754)).

---

## 3. Strategies for Parallelizing Large Binary Files with a Pre-Scan Step

### The core challenge

Variable-length block streams (like SBF) cannot be byte-offset-partitioned without first knowing where
records begin. This is a well-known problem in parallel text and binary parsing literature.

### Documented strategy: two-pass (pre-scan then parallel parse)

The pattern is described in patent literature and bioinformatics tooling:

1. **Pre-scan pass (single thread/process):** Read sequentially, collect byte offsets of record
   boundaries. This produces a list `[(start_offset, end_offset), ...]`.
2. **Parallel parse:** Submit each `(start, end)` region as an independent task. Workers `seek()` to
   `start`, read `end - start` bytes, parse in isolation.

This pattern is explicitly described in parallel markup parsing literature
([USPTO patent 10387563](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10387563)) and
in high-performance bioinformatics formats like BINSEQ
([BINSEQ preprint](https://www.biorxiv.org/content/10.1101/2025.04.08.647863.full.pdf)).

**Applicability to SBF:** SBF has a fixed sync byte + block header pattern. A single-threaded pre-scan
that identifies all block headers is feasible (linear in file size, I/O-bound). The resulting offset
table can then feed a `ProcessPoolExecutor` for parallel block decoding.

### Alternative: streaming producer with parallel workers

Instead of pre-scanning, a single producer thread reads blocks sequentially and pushes them into a
bounded `queue.Queue`. Worker processes (or threads) pull blocks and parse them. This avoids the
two-pass cost but serializes the I/O:

- Pro: works for files arriving as streams (no pre-scan required).
- Con: producer is a throughput bottleneck if I/O is fast relative to parsing.
- For SBF at 1 Hz with many signal types, parsing is likely the bottleneck, not I/O — making the
  parallel-parse-after-prescan approach more attractive.

No widely-cited Python reference implementation for this exact pattern was found; the approach is
project-specific but well-grounded in parallel parsing literature.

---

## 4. Producer-Consumer Patterns with Bounded Queues for Python Data Pipelines

### Standard pattern

```
N producer threads/processes  →  bounded queue.Queue(maxsize=M)  →  1 consumer thread
```

- `queue.Queue(maxsize=M)` provides built-in backpressure: `put()` blocks when the queue is full,
  so producers naturally throttle to the consumer's throughput
  ([Python multiprocessing docs](https://docs.python.org/3/library/multiprocessing.html)).
- M should be sized so the queue holds roughly 2–4× the consumer's batch size (enough to keep the
  consumer busy without accumulating unbounded memory).

### ProcessPoolExecutor futures feeding a queue

This is a common but subtly dangerous pattern. Key pitfalls:

1. **Future accumulation:** Calling `executor.submit()` in a tight loop without collecting results
   stores all `Future` objects (and their result payloads) in the driver process heap. For large
   xarray datasets returned per task, this causes rapid OOM. Fix: use a sliding-window approach —
   maintain at most `N` in-flight futures at a time ([CPython bug tracker](https://bugs.python.org/issue41588)).

2. **BrokenProcessPool:** Worker crashes (OOM, segfault in a C extension) silently kill the pool.
   The next `future.result()` raises `BrokenProcessPool`. This is especially relevant for large
   binary files where a single malformed block can crash a worker process
   ([DeepSource debugging heisenbugs](https://deepsource.com/blog/debugging-heisenbugs)).

3. **Cross-process queue limitations:** `multiprocessing.Queue` (vs `queue.Queue`) can be used to
   communicate between processes directly, but involves pickle overhead for every item. For large
   datasets this is prohibitive (see Section 5).

### Threading model recommendation

For a read-heavy pipeline with a sequential write bottleneck:

- Use `ThreadPoolExecutor` for I/O-bound reads (RINEX files) — no pickle overhead, shared memory.
- Use `ProcessPoolExecutor` for CPU-bound parsing (SBF binary decoding).
- Use a single writer thread/process that drains results serially.
- Connect them with `queue.Queue(maxsize=N)` in the driver process to implement backpressure.

See: [SuperFastPython thread producer-consumer](https://superfastpython.com/thread-producer-consumer-pattern-in-python/),
[SuperFastPython threadpool producer-consumer](https://superfastpython.com/threadpool-producer-consumer/).

---

## 5. Returning Large numpy/xarray Results Across Process Boundaries

### Pickle overhead: the dominant cost for large datasets

When a `ProcessPoolExecutor` worker returns an `xr.Dataset`, the result is pickled in the worker,
sent over an OS pipe, and unpickled in the driver. For a 100 MB dataset:

- Pickle serialization + IPC copy costs are proportional to dataset size.
- A 10 MB numpy array already shows significant overhead; 100–500 MB datasets make this the
  dominant cost ([DEV Community IPC post](https://dev.to/imsushant12/inter-process-communication-in-python-multiprocessing-with-examples-5ai2)).
- xarray's pickle support exists but is documented as version-sensitive and fragile for
  `open_mfdataset`-backed datasets ([xarray GitHub issue #7109](https://github.com/pydata/xarray/issues/7109)).

### Alternatives

**A. Write to temp Zarr in worker, return path (recommended for large outputs)**

Each worker writes its result to a temporary Zarr store (e.g., `zarr.open(tempfile, mode='w')`)
and returns only the file path to the driver. The driver (or consumer thread) opens the Zarr store
for the sequential write step. This eliminates all IPC data transfer for the large payload.
- Pro: zero cross-process data movement for the array data; robust to large datasets.
- Con: requires disk I/O in the worker; temp files must be cleaned up.
- The xarray/Zarr integration supports this naturally ([xarray Zarr docs](https://docs.xarray.dev/en/stable/user-guide/io.html)).

**B. `multiprocessing.shared_memory` (Python 3.8+)**

The `multiprocessing.shared_memory` module allocates a named shared memory region that all
processes map into their address spaces with zero copy. A numpy array can be wrapped over shared
memory with no serialization:

```python
shm = shared_memory.SharedMemory(create=True, size=arr.nbytes)
shared_arr = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shm.buf)
```

- Pro: true zero-copy; fastest possible IPC for numpy data.
- Con: requires manual coordination (shape, dtype, size passed separately); no xarray metadata;
  manual cleanup; writer must not mutate while reader is active
  ([Python shared_memory docs](https://docs.python.org/3/library/multiprocessing.shared_memory.html),
  [Abhik Sarkar shared memory guide](https://www.abhik.ai/concepts/language-internals/shared-memory)).

**C. Memory-mapped files (`np.memmap`)**

Workers write to a temp file via `np.memmap`; driver reads back via `np.memmap`. Similar in effect
to shared memory but backed by the filesystem. Slightly slower than shared memory but more resilient
across process restarts.

### Practical recommendation for 2025 Python

| Dataset size | Recommended approach |
|---|---|
| < 50 MB | Pickle via ProcessPoolExecutor pipe (acceptable) |
| 50–500 MB | Temp Zarr store in worker → return path |
| > 500 MB or high throughput | `multiprocessing.shared_memory` + numpy view |

The temp-Zarr-path pattern is the most idiomatic for an xarray/Zarr pipeline and avoids introducing
shared memory lifecycle complexity.

---

## 6. Free-Threaded Python 3.14t for CPU-Bound Scientific Workloads

### Status as of mid-2026

Python 3.14 (released October 2025) promoted free-threaded builds from experimental to **officially
supported** via PEP 779
([Python 3.14 free-threading overview](https://www.edgarmontano.com/posts/python/python-3-14-free-threading-true-parallelism),
[devlap benchmarks](https://devlap.com/tutorials/2695/python-314-free-threading-real-benchmarks-real-breakage-real-code)).

### Real performance benchmarks

- **Single-threaded overhead:** Python 3.13t had ~40% single-thread penalty vs GIL Python. Python
  3.14t reduced this to **5–10%** by re-enabling the specialising adaptive interpreter
  ([Java Code Geeks, June 2026](https://www.javacodegeeks.com/2026/06/python-3-13s-free-threaded-mode-what-no-gil-actually-means-for-your-code.html)).
- **Multi-threaded CPU-bound:** Up to **3.5–8× speedup** on 4–8 cores for pure-Python CPU-bound
  tasks. Real benchmarks consistently show 2–4× on 4-core machines
  ([devlap real benchmarks](https://devlap.com/tutorials/2695/python-314-free-threading-real-benchmarks-real-breakage-real-code),
  [neelsomaniblog](https://www.neelsomaniblog.com/p/killing-the-gil-how-to-use-python)).
- Facebook's free-threading benchmarking project documents results across a range of workloads
  ([facebookexperimental/free-threading-benchmarking](https://github.com/facebookexperimental/free-threading-benchmarking)).

### NumPy / xarray / Zarr / Icechunk support status

| Library | Free-threaded status (mid-2026) |
|---|---|
| **NumPy** | `Py_GIL_DISABLED` declared in NumPy 2.1+ (Python 3.13t). Thread-safe for read-only access; mutable array operations are NOT protected — caller must synchronize ([NumPy thread safety docs](https://numpy.org/doc/stable/reference/thread_safety.html)) |
| **xarray** | Not explicitly declared free-threaded-safe; relies on NumPy + Dask underneath |
| **zarr-python** | Free-threaded support not officially declared as of search date; no GIL_NOT_USED marker found |
| **icechunk** | No published free-threaded status found |

**Critical caveat:** if any loaded C extension has **not** declared `Py_GIL_DISABLED`, the
free-threaded interpreter silently re-enables the GIL for the entire process. Zarr and Icechunk use
Rust extensions (via PyO3); PyO3 >= 0.23 supports GIL-free builds, but must be explicitly compiled
that way.

### ThreadPoolExecutor competitiveness on 3.14t

For CPU-bound binary parsing on 3.14t:
- If all extensions in the parse path declare GIL-free support: `ThreadPoolExecutor` becomes
  competitive with `ProcessPoolExecutor` (no IPC, no pickle, shared memory by default).
- If any extension re-enables the GIL: `ThreadPoolExecutor` degrades to serial behaviour; fall back
  to `ProcessPoolExecutor`.
- The practical test: run `sys.flags.gil` at runtime. If it returns `0`, GIL is disabled across
  all loaded extensions.

As of mid-2026, **`ProcessPoolExecutor` remains the safer choice for production** because it
guarantees parallelism regardless of extension GIL status. Free-threaded Python with
`ThreadPoolExecutor` is worth piloting for this stack but requires explicit verification of the
full extension chain.

---

## 7. Streaming Writes to Zarr / Icechunk Without In-Memory Accumulation

The core scenario: results arrive from a `ProcessPoolExecutor` in completion order (not sorted
chronologically), and must be written to an Icechunk/Zarr store inside a **single session** that
commits once at the end.

### Zarr v3 append patterns: `mode="a"` safety

Zarr's `open(..., mode="a")` opens an existing store for read/write, or creates it if absent. It is
safe to call repeatedly from the same process — it reopens the store handle; it does not reload all
prior data. Array data is written chunk-by-chunk to object storage; only the array metadata (shape,
dtype, chunk spec) is cached in the Zarr store object.

`xarray.Dataset.to_zarr()` supports two append-friendly modes
([xarray to_zarr docs](https://docs.xarray.dev/en/stable/generated/xarray.Dataset.to_zarr.html)):

- **`mode="a"`** — override existing variables including dimension coordinates; create if absent.
- **`append_dim="epoch"`** — grow an existing array along the named dimension. All other dimension
  sizes must remain unchanged.

**Critical constraint with `append_dim`:** appending must happen in a defined order because zarr
arrays grow sequentially. A zarr GitHub discussion confirms: "Appending over the time dimension has
to be done in the correct order because it is sequential and cannot be parallelized"
([zarr-python discussion #2532](https://github.com/zarr-developers/zarr-python/discussions/2532)).
For out-of-order completion from a process pool, `append_dim` is therefore unsafe without
additional sorting.

**Known bug with `append_dim` and coordinates** ([xarray issue #8427](https://github.com/pydata/xarray/issues/8427)):
coordinate data can be silently overwritten by the most recently appended dataset without checking
alignment. Verified as a live issue as of 2024–2025.

### `to_zarr(region=...)` for non-contiguous writes

`region` allows updating arbitrary slices of an existing store:

```python
ds.to_zarr(store, region={"epoch": slice(start, stop)})
```

Constraints ([xarray to_zarr docs](https://docs.xarray.dev/en/stable/generated/xarray.Dataset.to_zarr.html)):

- The store must already exist with the correct shape pre-allocated. The recommended pattern is a
  first call with `compute=False` to write metadata/coordinates only, then fill data via `region=`.
- All variables in the dataset must share at least one dimension with the region.
- Coordinate variables (e.g. `epoch`) must be written separately in a prior call — they cannot
  appear in the same `to_zarr()` call as `region=`.
- Alignment with chunk boundaries is **the caller's responsibility**. xarray makes limited checks.
  Writing partial chunks can silently corrupt data
  ([xarray issue #8323](https://github.com/pydata/xarray/issues/8323)).
- `region=` and `append_dim=` cannot be combined on the same dimension.

### Documented pattern: pre-allocate then region-fill

The only xarray-documented strategy for streaming writes without buffering:

1. **Pre-allocate:** write an empty store of the final expected shape (with `compute=False` or
   dummy arrays).
2. **Per-result region-write:** as each worker result arrives, compute its epoch slice index and
   call `to_zarr(region={"epoch": slice(i, j)})`. No buffering of other results required.

This requires knowing final array shape upfront (which may not be possible when file counts vary).
If shape is unknown, a workaround is to accumulate only the epoch-index metadata (lightweight) and
do a single sorted bulk write at the end — or use `append_dim` with a pre-sort step.

### Icechunk-specific considerations

Icechunk wraps a Zarr store with ACID transaction semantics. Within a single writable session,
multiple `region=` writes to non-overlapping chunks are safe and accumulate in the session's
changeset until `session.commit()` is called. No evidence was found that Icechunk imposes
contiguity constraints beyond those of Zarr itself.

The Icechunk `session.flush(message)` API (new in v2) can create intermediate snapshots without
advancing the branch, which could allow checkpointing long streaming write sequences without losing
progress on crash
([Icechunk v2 announcement](https://www.earthmover.io/blog/announcing-icechunk-2-better-consistency-performance-and-reliability-for-tensor-storage/)).

---

## 8. Icechunk Concurrent Writes on Object Storage — Fork/Merge Pattern

### How `Session.fork()` / `Session.merge()` works

Icechunk's distributed write model is documented in its parallel writing guide
([Icechunk parallel docs](https://icechunk.io/en/stable/understanding/parallel/)):

1. **Fork:** Call `session.fork()` to obtain a `ForkSession`. This is a picklable, sendable object
   that represents a snapshot of the session state. Forking is only valid when the session has **no
   uncommitted changes**.
2. **Distribute:** Send the `ForkSession` to worker processes (via `ProcessPoolExecutor.submit`,
   Dask, or any executor). Each worker writes to its own `ForkSession` independently.
3. **Collect:** Workers return their `ForkSession` objects to the driver.
4. **Merge:** The driver calls `session.merge(fork1, fork2, ..., forkN)` to aggregate all
   changesets. This produces a combined changeset in the parent session.
5. **Commit:** A single `session.commit()` atomically writes all changes.

The documented Python example pattern uses `region="auto"` in `xarray.to_zarr()` to infer which
array region each worker should write:

```python
fork = session.fork()
future = executor.submit(write_worker, fork, data_chunk)
fork_result = future.result()
session.merge(fork_result)
session.commit("parallel write complete")
```

([DeepWiki: Icechunk distributed examples](https://deepwiki.com/earth-mover/icechunk/7.2-distributed-examples))

### Overlapping vs non-overlapping region constraints

**Non-overlapping writes are required.** The Icechunk docs state explicitly:
"It is your responsibility to ensure that such conflicts are avoided."
`session.rebase()` can merge concurrent sessions only if they modified **different chunks** of an
array. Workers writing to overlapping Zarr chunks will produce a conflict that cannot be
automatically resolved
([Icechunk parallel docs](https://icechunk.io/en/stable/understanding/parallel/),
[GitHub discussion #802](https://github.com/earth-mover/icechunk/discussions/802)).

Icechunk uses **optimistic concurrency** on object storage: a conditional-update (compare-and-swap)
on the `RepoInfo` object detects whether a concurrent session has modified the repo between fork and
merge. If conflict is detected, a retry is needed. This is designed for infrequent conflicts, not
for contended concurrent writes to the same chunks
([Earthmover consistency blog](https://www.earthmover.io/blog/learning-about-icechunk-consistency/)).

### Production readiness as of mid-2026

- Icechunk 1.0 was released July 2025 and declared production-ready. Data written by 1.0+ will be
  readable by all future versions
  ([Icechunk 1.0 announcement](https://www.earthmover.io/blog/icechunk-1-0-production-grade-cloud-native-array-storage-is-here/)).
- Icechunk v2 was announced April 2026, adding **parallel flush** (array nodes flushed in parallel
  during commit) and **concurrent transaction log fetching** during rebase, reducing commit latency
  for large sessions
  ([Icechunk v2 announcement](https://www.earthmover.io/blog/announcing-icechunk-2-better-consistency-performance-and-reliability-for-tensor-storage/)).
- The fork/merge pattern is the documented, tested production path. No evidence of it being marked
  experimental as of mid-2026.

### Sequential vs concurrent write benchmarks on S3

No published benchmark directly comparing sequential vs concurrent Icechunk writes on S3 was found
in this search. Earthmover published S3 read scalability data (>230,000 chunk reads/s,
[Icechunk S3 scalability blog](https://www.earthmover.io/blog/exploring-icechunk-scalability/))
but no equivalent write throughput comparison. The v2 "parallel flush" improvement targets commit
latency, not per-chunk write throughput (which is bounded by S3 PUT rate limits per prefix).

### Designing a write abstraction for sequential-local vs concurrent-S3

Based on the Icechunk fork/merge API, a write abstraction that supports both paths should:

| Concern | Sequential (local) | Concurrent (S3) |
|---|---|---|
| Session lifecycle | Single session, write one at a time | Fork per worker before dispatch |
| Worker interface | Worker returns `xr.Dataset`; driver writes | Worker receives `ForkSession`, writes, returns `ForkSession` |
| Merge step | No-op | `session.merge(*fork_sessions)` in driver |
| Commit | Single `session.commit()` | Single `session.commit()` after merge |
| Conflict avoidance | N/A (serial) | Partition epoch ranges across workers before dispatch |

The abstraction boundary: workers should receive pre-partitioned epoch ranges and the Icechunk
session token (fork or direct), and the driver should orchestrate merge + commit. This keeps
workers stateless with respect to session management.

---

## 9. Synthesis: What the Literature Recommends for This Pipeline

Given the pipeline characteristics (RINEX I/O-bound + SBF CPU-bound reads; xarray Dataset outputs
50–500 MB; strictly sequential writes; 4–32 cores, 8–64 GB RAM):

### Read / parse phase

1. **RINEX files (I/O-bound, 0.5–50 MB):** Use `ThreadPoolExecutor` with `max_workers=min(32, n_cores * 4)`.
   No GIL contention for I/O; no IPC overhead; shared-memory results. For very large files (>10 MB),
   the parse is partly CPU-bound — benchmark to see if `ProcessPoolExecutor` wins.

2. **SBF files (CPU-bound, 1–200 MB, non-seekable):**
   - **Per-file parallelism:** One file per worker via `ProcessPoolExecutor`. Use a long-lived pool
     created at startup with `initializer=` to preload numpy/zarr. Avoids per-batch spawn overhead.
   - **Intra-file parallelism (large 24h files):** Pre-scan to collect block offsets, then submit
     offset ranges to the same pool. This is the only documented strategy for non-seekable
     variable-length records.

3. **Avoid returning large Datasets via pickle:** Write to a per-worker temp Zarr store; return the
   path. The sequential writer opens the temp store and appends. This eliminates the dominant IPC
   cost for large files.

### Write phase

Serialize writes explicitly — do not attempt concurrent writes to the Icechunk store. Use a bounded
`queue.Queue(maxsize=4)` to cap in-memory buffer between the parallel read/parse workers and the
single writer thread. This provides backpressure if parsing outpaces writing (likely for SBF).

### Pool lifecycle

Create **one** long-lived `ProcessPoolExecutor` at application startup. Reuse across all batches.
Collect futures in a sliding window (e.g., 2–4× `n_workers` in-flight at once) to bound memory.

### Free-threaded Python

Do not adopt 3.14t as a dependency yet for this stack. The zarr-python and icechunk extension GIL
status is unclear as of mid-2026. Revisit when icechunk's PyO3 bindings explicitly declare
GIL-free support. At that point, `ThreadPoolExecutor` on 3.14t would eliminate IPC overhead
entirely for the parse phase.

### Framework choice

`ProcessPoolExecutor` (stdlib) with manual sliding-window future management is the recommended
baseline — it has the lowest overhead for linear pipelines and no external dependencies. MPIRE is a
well-benchmarked upgrade if copy-on-write shared state (e.g., a pre-loaded ephemeris table) needs
to be shared across workers efficiently. Dask LocalCluster adds overhead that is not justified for
this linear topology.

---

## Sources

- [Dask distributed efficiency docs](https://distributed.dask.org/en/stable/efficiency.html)
- [Dask scheduling docs](https://docs.dask.org/en/stable/scheduling.html)
- [Dask fine performance metrics](https://distributed.dask.org/en/stable/fine-performance-metrics.html)
- [MPIRE for Python — Towards Data Science](https://towardsdatascience.com/mpire-for-python-multiprocessing-is-really-easy-d2ae7999a3e9/)
- [MPIRE GitHub](https://github.com/sybrenjansen/mpire)
- [SuperFastPython: ProcessPoolExecutor complete guide](https://superfastpython.com/processpoolexecutor-in-python/)
- [SuperFastPython: thread producer-consumer](https://superfastpython.com/thread-producer-consumer-pattern-in-python/)
- [SuperFastPython: threadpool producer-consumer](https://superfastpython.com/threadpool-producer-consumer/)
- [Tinybird: killing the ProcessPoolExecutor](https://www.tinybird.co/blog/killing-the-processpoolexecutor)
- [Medium: Python multiprocessing fork vs spawn](https://medium.com/@Nexumo_/python-multiprocessing-revisited-fork-vs-spawn-5b9216fd5710)
- [Python multiprocessing.shared_memory docs](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
- [Python multiprocessing docs](https://docs.python.org/3/library/multiprocessing.html)
- [DEV Community: IPC in Python multiprocessing](https://dev.to/imsushant12/inter-process-communication-in-python-multiprocessing-with-examples-5ai2)
- [Abhik Sarkar: Python shared memory](https://www.abhik.ai/concepts/language-internals/shared-memory)
- [CPython issue #85754: memory leak with ThreadPoolExecutor](https://github.com/python/cpython/issues/85754)
- [NumPy issue: BrokenProcessPool / memory leak](https://github.com/numpy/numpy/issues/12122)
- [DeepSource: debugging heisenbugs in parallel processing](https://deepsource.com/blog/debugging-heisenbugs)
- [xarray GitHub issue #7109: multiprocessing pickle](https://github.com/pydata/xarray/issues/7109)
- [xarray parallel computing with Dask](https://docs.xarray.dev/en/stable/user-guide/dask.html)
- [xarray IO docs](https://docs.xarray.dev/en/stable/user-guide/io.html)
- [NumPy thread safety docs](https://numpy.org/doc/stable/reference/thread_safety.html)
- [NumPy free-threaded tracking issue #26157](https://github.com/numpy/numpy/issues/26157)
- [Python 3.14 free-threading — edgarmontano.com](https://www.edgarmontano.com/posts/python/python-3-14-free-threading-true-parallelism)
- [Python 3.14 free-threading real benchmarks — devlap](https://devlap.com/tutorials/2695/python-314-free-threading-real-benchmarks-real-breakage-real-code)
- [Python 3.14 free-threading — danilchenko.dev](https://www.danilchenko.dev/posts/python-314-free-threading/)
- [Python 3.14 no-GIL explained — engineersmeetai substack](https://engineersmeetai.substack.com/p/python-314s-no-gil-explained-and)
- [Python 3.13 free-threaded mode — Java Code Geeks, June 2026](https://www.javacodegeeks.com/2026/06/python-3-13s-free-threaded-mode-what-no-gil-actually-means-for-your-code.html)
- [facebookexperimental/free-threading-benchmarking](https://github.com/facebookexperimental/free-threading-benchmarking)
- [Quansight: free-threaded Python rollout](https://labs.quansight.org/blog/free-threaded-python-rollout)
- [USPTO patent 10387563: parallel markup parsing](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10387563)
- [BINSEQ: high-performance binary formats (biorxiv 2025)](https://www.biorxiv.org/content/10.1101/2025.04.08.647863.full.pdf)
- [Runtime vs Scheduler: Analyzing Dask's Overheads (arxiv)](https://arxiv.org/pdf/2010.11105)
- [xarray Dataset.to_zarr docs](https://docs.xarray.dev/en/stable/generated/xarray.Dataset.to_zarr.html)
- [xarray reading and writing files (v2025)](https://docs.xarray.dev/en/v2025.01.2/user-guide/io.html)
- [xarray issue #8323: to_zarr region + consolidated metadata](https://github.com/pydata/xarray/issues/8323)
- [xarray issue #8427: ambiguous coordinates with append_dim](https://github.com/pydata/xarray/issues/8427)
- [xarray issue #6329: to_zarr append/region + _FillValue](https://github.com/pydata/xarray/issues/6329)
- [zarr-python discussion #2532: concurrent downloading and appending](https://github.com/zarr-developers/zarr-python/discussions/2532)
- [xarray issue #7702: passing coordinates in to_zarr(region=...)](https://github.com/pydata/xarray/issues/7702)
- [Icechunk parallel / distributed writing docs](https://icechunk.io/en/stable/understanding/parallel/)
- [Icechunk FAQ](https://icechunk.io/en/latest/understanding/faq/)
- [DeepWiki: Icechunk distributed examples](https://deepwiki.com/earth-mover/icechunk/7.2-distributed-examples)
- [Icechunk GitHub discussion #802: understanding parallel writes](https://github.com/earth-mover/icechunk/discussions/802)
- [Earthmover: Icechunk consistency blog](https://www.earthmover.io/blog/learning-about-icechunk-consistency/)
- [Earthmover: Icechunk 1.0 production announcement](https://www.earthmover.io/blog/icechunk-1-0-production-grade-cloud-native-array-storage-is-here/)
- [Earthmover: Icechunk v2 announcement (April 2026)](https://www.earthmover.io/blog/announcing-icechunk-2-better-consistency-performance-and-reliability-for-tensor-storage/)
- [Earthmover: Icechunk S3 scalability](https://www.earthmover.io/blog/exploring-icechunk-scalability/)
- [Icechunk Dask integration docs](https://icechunk.io/en/latest/guides/dask/)
