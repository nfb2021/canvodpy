# Performance Web Research — Phase 2: Parallelization Frameworks

**Date:** 2026-07-02
**Branch:** explore/performance-review
**Purpose:** Research prior art and concrete recommendations for Python parallelization
of the canvodpy CPU-bound RINEX processing pipeline.

## Pipeline shape (reminder)

```
[parallel file processing — CPU-bound Python]  →  [sequential writes to versioned store]
   one file per worker, ~1-30s per file             single writer, cannot be concurrent
```

Constraints: Python 3.14, macOS + Linux, GIL ON, spawn start method, ~100MB ephemeris
table to share across workers, long-lived pool goal (eliminate 3s spawn cost per batch).

---

## Question 1: ProcessPoolExecutor vs loky vs MPIRE vs Ray

### 1a. Default start method on macOS + Python 3.14

**Concrete answer: spawn.**

macOS has used `spawn` as default since Python 3.8. Python 3.14 changed the default
on *Linux/POSIX* from `fork` to `forkserver`, but macOS remains `spawn`. Windows also
remains `spawn`. This matters for every subsequent question.

> "Python 3.14 changed the default method for multiprocessing and ProcessPoolExecutor
> from fork to forkserver on platforms other than macOS and Windows, where it was already
> spawn."
>
> Source: https://docs.python.org/3/library/multiprocessing.html

**Implication for canvodpy:** `fork` and copy-on-write approaches are unavailable on macOS.
All workers are fresh-spawned subprocesses; everything passed to them is pickled and copied.

### 1b. Can ProcessPoolExecutor pools be reused across batches?

**Concrete answer: yes, safely, without context manager.**

`submit()` and `map()` can be called multiple times on the same executor instance.
Workers (with `max_tasks_per_child=None`, the default) live as long as the pool.
The context manager pattern (`with ProcessPoolExecutor(...) as ex:`) shuts down
the pool on exit, so it is only appropriate for single-use pools.

```python
# Long-lived pattern — correct
executor = ProcessPoolExecutor(max_workers=N)
# many batches:
futures = [executor.submit(process_file, f) for f in batch]
...
# Eventually at CLI shutdown:
executor.shutdown(wait=True)
```

`max_tasks_per_child` (Python 3.11+) can be used to cap how many tasks a single
worker process handles before it is replaced. Useful to control memory growth in
very long runs, at the cost of occasional respawn.

> Source: https://superfastpython.com/processpoolexecutor-in-python/
> Source: https://docs.python.org/3/library/concurrent.futures.html

### 1c. Does loky offer anything ProcessPoolExecutor doesn't?

**Concrete answer: yes — two critical extras for a long-lived pool.**

**loky** (https://github.com/joblib/loky) is used as the default backend for joblib
and provides a `get_reusable_executor()` singleton:

```python
from loky import get_reusable_executor
executor = get_reusable_executor(
    max_workers=N,
    timeout=300,       # idle timeout before retiring workers (seconds; default=10)
    kill_workers=False # if True, forcibly kills existing workers on resize
)
```

Key advantages over stdlib `ProcessPoolExecutor`:

| Feature | ProcessPoolExecutor | loky |
|---|---|---|
| Reuse across batches | Yes (no context manager) | Yes (explicit singleton) |
| Worker idle timeout | No | Yes (configurable) |
| Pool resize without recreate | No | Yes (dynamic resize) |
| Broken pool recovery | No (BrokenProcessPool is terminal) | Yes (auto-respawn) |
| Crash traceback | Minimal | faulthandler + Python traceback |
| macOS `spawn` safe | Yes | Yes (uses fork+exec, avoids fork-without-exec) |

The loky `ReusableExecutor` is a global singleton: any call to `get_reusable_executor()`
with the same parameters returns the same pool. This exactly matches the canvodpy pattern
of one pool per CLI run, shared across many batches.

**Crash recovery detail:** When a worker process is killed by OOM or a bug, stdlib
`ProcessPoolExecutor` enters a `BrokenProcessPool` state and all subsequent submits raise.
loky automatically detects this and respawns workers, returning the executor to a healthy
state. Errors are also surfaced with meaningful Python tracebacks via faulthandler.

> Source: https://loky.readthedocs.io/en/stable/
> Source: https://loky.readthedocs.io/en/stable/API.html
> Source: https://github.com/joblib/loky

**Recommendation for canvodpy:** Use loky's `get_reusable_executor()` instead of
stdlib `ProcessPoolExecutor` for the long-lived pool. It is a drop-in API-compatible
replacement and handles the three hardest problems: idle timeout, crash recovery,
and dynamic resize between batches.

### 1d. MPIRE `shared_objects` — does copy-on-write work with spawn?

**Concrete answer: no — copy-on-write is fork-only; spawn gets one copy per worker.**

MPIRE (https://github.com/sybrenjansen/mpire) provides `shared_objects` which copies
the object once per *worker* (not once per *task*). This is better than passing it
per-task (which copies on every pickle/unpickle), but it is not zero-copy.

From the MPIRE docs:
> "For the start methods spawn and forkserver, shared objects are copied once for each
> worker, in contrast to copying it for each task which is done when using a regular
> multiprocessing.Pool."
> "MPIRE offers easy use of copy-on-write shared objects with a pool of workers, though
> copy-on-write is only available for start method fork."

**Implication:** On macOS (spawn), MPIRE's `shared_objects` for a 100MB ephemeris table
copies 100MB × N_workers at pool startup. For 8 workers this is 800MB peak. This is
a one-time cost but not zero-copy. The pattern is still useful because it avoids
re-sending 100MB with every task.

> Source: https://sybrenjansen.github.io/mpire/v2.3.0/usage/workerpool/shared_objects.html

### 1e. Ray vs ProcessPoolExecutor for this use case

**Concrete answer: ProcessPoolExecutor / loky wins on a single machine for 1-30s tasks.**

Ray adds non-trivial scheduling overhead per task (measured in milliseconds to tens of
milliseconds). For tasks under ~10ms, Ray's overhead is prohibitive. For the canvodpy
use case (1-30s file processing tasks), this overhead is tolerable but adds complexity.

From the Ray docs:
> "Every task invocation has non-trivial overhead including scheduling, inter-process
> communication, and updating the system state, and this overhead can dominate the
> actual time it takes to execute the task."
> "You will be unlikely to see speedups if your tasks take less than ten milliseconds."

From benchmarks (TaPS evaluation suite):
> "ProcessPoolExecutor performs the best on single-node setups because, unlike other
> executors, there is no scheduler."

Ray is appropriate when tasks need to span machines or when tasks need to share Ray
objects (actors, object store). For the current single-machine canvodpy pipeline,
Ray introduces unnecessary complexity.

**Verdict:** Ray is the right choice only if canvodpy moves to multi-machine distributed
processing. For now, loky / ProcessPoolExecutor is better.

> Source: https://docs.ray.io/en/latest/ray-core/tips-for-first-time.html
> Source: https://arxiv.org/pdf/2408.07236 (TaPS benchmark)
> Source: https://medium.com/analytics-vidhya/benchmarking-performances-and-scaling-of-time-series-forecast-with-multiprocessing-concurrent-68a8c552afd6

---

## Question 2: Ephemeris data sharing across workers

### The core problem

The SP3/CLK ephemeris table is ~100MB. Loading it per-task would be too slow (disk I/O
per file × N files). Loading it per-worker once at startup (via `initializer`) copies
100MB × N_workers. Sharing it zero-copy across processes is the ideal but has caveats
on macOS with spawn.

### Option A: `initializer` / `initargs` (simplest, recommended)

```python
import globals_module

def _init_worker(ephemeris_bytes):
    # Deserialize once per worker at startup, store in module global
    globals_module.EPHEMERIS = pickle.loads(ephemeris_bytes)

executor = ProcessPoolExecutor(
    max_workers=N,
    initializer=_init_worker,
    initargs=(pickle.dumps(ephemeris_table),)
)
```

Workers receive the pickled blob once at startup, deserialize it, and store it in a
module-level global. Every task in that worker reuses the global without re-copying.
Total cost: 100MB pickled once per worker at pool creation. For N=8, this is ~800MB
peak during init, then amortized across all tasks.

This is the pattern recommended by the Python docs and multiple tutorials for "large
model / large table initialization."

> Source: https://www.pythontutorials.net/blog/launch-concurrent-futures-processpoolexecutor-with-initialization/
> Source: https://docs.python.org/3/library/concurrent.futures.html

### Option B: `multiprocessing.shared_memory` (zero-copy numeric arrays)

For a numpy array (which the SP3/CLK data ultimately is), `shared_memory.SharedMemory`
allows all workers to access the same OS-level shared memory region without copying.

```python
from multiprocessing.shared_memory import SharedMemory
import numpy as np

# Main process: create and populate shared block
shm = SharedMemory(create=True, size=arr.nbytes)
shared_arr = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shm.buf)
shared_arr[:] = arr  # one copy into shared region
shm_name = shm.name  # pass this string to workers

# Worker: attach to same block
def worker_init(shm_name, shape, dtype):
    global EPHEMERIS
    shm = SharedMemory(name=shm_name)
    EPHEMERIS = np.ndarray(shape, dtype=dtype, buffer=shm.buf)
    EPHEMERIS.flags.writeable = False  # enforce read-only
```

Works with `spawn` on macOS. Workers receive the shared memory block *name* (a string),
not the data, and attach to the same OS-level region.

**macOS caveat:** A CPython issue (#117262) reports failures with shared memory of
*object arrays* across spawned processes on macOS. This does not affect plain numeric
dtype arrays (float32, float64). The SP3/CLK ephemeris represented as numpy float arrays
should work fine.

> Source: https://docs.python.org/3/library/multiprocessing.shared_memory.html
> Source: https://github.com/python/cpython/issues/117262

### Option C: joblib's automatic memmap (simplest for numpy arrays)

When using `joblib.Parallel` and arrays are larger than 1MB, joblib automatically
memory-maps them to a temp file so all workers can access without copying:

```python
from joblib import Parallel, delayed
import numpy as np

ephemeris_arr = load_ephemeris()  # numpy array
results = Parallel(n_jobs=N)(
    delayed(process_file)(f, ephemeris_arr) for f in files
)
# joblib detects >1MB array, auto-memmap to /dev/shm or JOBLIB_TEMP_FOLDER
```

This is the most transparent approach for scientific Python — no manual SharedMemory
management. However it requires using joblib's parallel interface, which may not
integrate cleanly with the existing canvodpy architecture.

> Source: https://joblib.readthedocs.io/en/stable/parallel.html

### Option D: Copy-on-write via fork (Linux only)

On Linux, the `fork` start method copies parent process memory pages lazily. If the
ephemeris is loaded in the parent before forking, workers inherit it without copying
*as long as they don't modify it*. This works in theory but Python's reference counting
(GC) writes to object headers on every read, defeating copy-on-write and causing pages
to be copied anyway.

**On macOS: not available at all.** Not recommended.

### Prior art from scientific Python

- **astropy**: Uses `memmap=True` (default) for all FITS files, allowing multiple
  processes to share file pages via OS-level mmap. Same principle as SharedMemory.
- **astropy parallel_fit_dask**: Uses Dask for parallelizing model fits across N-D data
  cubes, but defers to Dask's scheduler rather than explicit pool management.
- **scikit-learn**: Uses joblib's automatic memmap for training data passed to parallel
  cross-validation — the exact same pattern as Option C above.

> Source: https://docs.astropy.org/en/stable/modeling/parallel-fitting.html
> Source: https://scikit-learn.org/stable/computing/parallelism.html

### Recommendation for canvodpy

**Short term:** Use `initializer`/`initargs` (Option A) with loky's `get_reusable_executor()`.
The ephemeris is pickled once per worker at pool creation, stored as a module global,
and reused for all tasks. Total memory cost: 100MB × N_workers (manageable for N=4-8).
The pool lives for the CLI run, so the pickling cost is a one-time startup overhead.

**Medium term:** If profiling shows the 100MB × N_workers memory cost is significant,
switch to Option B (SharedMemory) for the numpy arrays backing the SP3 interpolation
tables. This requires more code but eliminates per-worker copies.

---

## Question 3: Producer-consumer queue patterns

### Options

**Option A: `as_completed` with bounded submission window**

The simplest approach. Submit a bounded number of futures (e.g., 2× workers), then
use `as_completed()` to iterate results. As each future completes, submit the next file.
This naturally bounds the number of in-flight tasks (backpressure).

```python
from concurrent.futures import ProcessPoolExecutor, as_completed

def run_pipeline(files, writer, max_workers=4):
    window = max_workers * 2  # max in-flight tasks
    with ProcessPoolExecutor(max_workers) as executor:
        pending = {}
        file_iter = iter(files)

        # seed the window
        for f in itertools.islice(file_iter, window):
            pending[executor.submit(process_file, f)] = f

        for fut in as_completed(pending):
            result = fut.result()
            writer.write(result)          # sequential write
            del pending[fut]
            # submit next file as slot opens
            try:
                f = next(file_iter)
                pending[executor.submit(process_file, f)] = f
            except StopIteration:
                pass
```

Pros: simple, stdlib-only, natural backpressure. Con: error from any future raises
immediately on `.result()` call — need explicit try/except per future.

**Option B: `multiprocessing.Queue` with maxsize**

Full producer-consumer separation with an explicit bounded queue.

```python
from multiprocessing import Process, Queue
import queue

def producer(file_list, q, n_workers):
    for f in file_list:
        q.put(f)  # blocks when q is full (backpressure)
    for _ in range(n_workers):
        q.put(None)  # sentinel

def worker(q_in, q_out):
    while True:
        f = q_in.get()
        if f is None:
            break
        q_out.put(process_file(f))

def consumer(q_out, n_workers):
    done = 0
    while done < n_workers:
        item = q_out.get()
        if item is None:
            done += 1
        else:
            writer.write(item)

q_in = Queue(maxsize=2 * N_WORKERS)  # bounded — creates backpressure
q_out = Queue()
```

Pros: clean separation, explicit backpressure via maxsize. Con: more complex code,
sentinel management, explicit worker spawning vs using a pool.

**Option C: asyncio + run_in_executor**

Asyncio `Queue` with `maxsize` provides backpressure. Producer is async, consumers run
CPU-bound work via `loop.run_in_executor(process_pool)`. The sequential writer is the
asyncio coroutine consuming the output queue.

```python
async def pipeline(files):
    q = asyncio.Queue(maxsize=2 * N_WORKERS)
    loop = asyncio.get_event_loop()

    async def producer():
        for f in files:
            result = await loop.run_in_executor(executor, process_file, f)
            await q.put(result)   # blocks when queue full
        await q.put(None)

    async def consumer():
        while True:
            item = await q.get()
            if item is None:
                break
            writer.write(item)   # sequential write

    await asyncio.gather(producer(), consumer())
```

Note: Python 3.13 added `asyncio.Queue.shutdown()` for clean shutdown signalling.

Pros: clean, asyncio backpressure is easy to reason about. Con: adds asyncio event loop
as a dependency; `run_in_executor` doesn't propagate context variables (use `asyncio.to_thread`
for thread pools, but ProcessPool needs `run_in_executor`).

> Source: https://www.krython.com/tutorial/python/asyncio-queues-producer-consumer
> Source: https://oneuptime.com/blog/post/2026-01-30-python-asyncio-queues/view

### Recommendation for canvodpy

**Use Option A** (`as_completed` with bounded submission window) as the first
implementation. It is the simplest and has no additional dependencies. The bounded
window (2-4× workers) acts as natural backpressure — if the writer is slow, futures
accumulate but submission halts once the window is full.

**If the pipeline becomes multi-stage** (e.g., read → augment → vod → write as
separate stages), then Option C (asyncio with per-stage queues) becomes appropriate.

---

## Question 4: Long-lived pool lifecycle

### Is it safe to keep a pool alive across many batches?

**Yes.** `ProcessPoolExecutor` (and loky's equivalent) is safe to use for arbitrarily
many `submit()` / `map()` calls without recreating it. Workers stay alive by default
(`max_tasks_per_child=None`).

The only gotcha: `with ProcessPoolExecutor() as ex:` shuts down the pool on block exit.
For a long-lived pool, construct the executor explicitly and call `shutdown()` at the end.

### How to handle worker crashes

**stdlib ProcessPoolExecutor:** A worker crash puts the pool into `BrokenProcessPool`
state. All future `.submit()` calls raise `BrokenProcessPool`. **The pool cannot recover.**
You must catch the exception, recreate the executor, and resubmit. This is boilerplate-heavy
for a long-running CLI.

**loky `get_reusable_executor()`:** Automatically detects broken state and respawns workers.
The executor returned by subsequent calls to `get_reusable_executor()` is healthy.
Additionally, `faulthandler` is enabled in all loky workers, so crash tracebacks are
much more informative.

### Context manager vs explicit shutdown

| Pattern | Use when |
|---|---|
| `with ProcessPoolExecutor() as ex:` | Single-use pool, results needed before next step |
| Explicit `executor.shutdown(wait=True)` | Long-lived pool, reused across many batches |
| `loky.get_reusable_executor(timeout=X)` | Long-lived pool with automatic crash recovery and idle timeout |

The `timeout` parameter in loky (default 10s) controls how long idle workers wait before
being retired. For a CLI that processes files in bursts with pauses between sites, set
`timeout=300` (5 minutes) to keep workers alive across batch boundaries.

### Memory management over long runs

If workers accumulate memory (e.g., from caching large intermediate objects), set
`max_tasks_per_child=100` to periodically recycle workers. Python 3.11+ added this
to `ProcessPoolExecutor`; loky has had it longer.

> Source: https://loky.readthedocs.io/en/stable/
> Source: https://docs.python.org/3/library/concurrent.futures.html
> Source: https://superfastpython.com/processpoolexecutor-in-python/

---

## Question 5: Prior art for parallel geospatial / scientific file processing pipelines

### GNSS-specific tools

**gnssrefl** (https://gnssrefl.readthedocs.io): The `rinex2snr` command gained a
`--parallel` flag limited to 10 workers. No sophisticated pool management or shared
ephemeris handling documented. Uses Python's stdlib multiprocessing. Treats each
RINEX file independently, writes per-file outputs to disk (no sequential writer pattern).

**PyRINEX** (https://github.com/geumjin99/PyRINEX): Batch processing for RINEX 2.0 and 3.0.
Uses Python string parsing. No parallel processing or pool documentation found.

**pyRTKLib** (https://github.com/alainmuls/pyRTKLib): Wraps RTKLib C library, uses
subprocess-based parallelism rather than in-process pools. C library avoids GIL.

**Conclusion:** No GNSS processing library was found that combines a long-lived
process pool, shared ephemeris data, and a sequential versioned write backend.
canvodpy is ahead of the public prior art for this specific shape.

### Climate/geophysical processing (closer analogy)

**Iris (UK Met Office)** (https://scitools-iris.readthedocs.io): Documented Dask bags
for parallel CF-NetCDF file loading with greedy parallelism. Their docs specifically
warn against the "greedy parallelism" antipattern (submitting all tasks without
backpressure) and recommend bounded queues.

**xarray + Dask**: The standard pattern for parallel climate file processing is to
construct a Dask graph over files and let Dask's scheduler parallelize reads. Writes
use Zarr's parallel chunk writing (which is safe for concurrent chunk writes to
disjoint regions). This differs from canvodpy's versioned-write constraint.

**astropy parallel model fitting**: Uses Dask (via `parallel_fit_dask`) for N-D
data fitting. Shares data via Dask's object store.

### Joblib prior art (closest to canvodpy pattern)

joblib's `Parallel` is the dominant prior art for this exact shape in scientific Python:
CPU-bound tasks in a process pool, with large shared data (sklearn training matrices,
model weights, etc.) auto-memmapped to temp files. The pattern:

```python
from joblib import Parallel, delayed, dump, load
import numpy as np

# Dump large array to disk memmap
dump(ephemeris, '/tmp/ephemeris_memmap.pkl')
memmap = load('/tmp/ephemeris_memmap.pkl', mmap_mode='r')

results = Parallel(n_jobs=N)(
    delayed(process_file)(f, memmap) for f in files
)
```

joblib will pass the memmap filename, not the data, so workers attach to the same
file pages via OS-level mmap. Works on macOS with spawn.

> Source: https://joblib.readthedocs.io/en/stable/parallel.html

---

## Synthesis: Recommended architecture for canvodpy

### Chosen pattern

```
┌─────────────────────────────────────────────────────┐
│                  CLI / site.process()               │
│                                                     │
│  loky.get_reusable_executor(                        │
│      max_workers=N,                                 │
│      timeout=300,                                   │  ← long-lived, crash-safe
│      initializer=_init_ephemeris,                   │  ← one-time 100MB copy per worker
│      initargs=(ephemeris_pickle,)                   │
│  )                                                  │
│                                                     │
│  bounded_submit_window = 2 * N                      │
│  for file in files:                                 │
│      fut = executor.submit(process_file, file)      │
│      pending.add(fut)                               │
│      if len(pending) >= bounded_submit_window:      │  ← backpressure
│          done, pending = wait(pending, FIRST_COMPLETED)
│          for f in done:                             │
│              writer.write(f.result())               │  ← sequential write
└─────────────────────────────────────────────────────┘
```

### Future path: Icechunk fork/merge for concurrent writes

When canvodpy moves to S3 object storage, Icechunk's fork/merge pattern enables
concurrent writes without the sequential writer bottleneck:

```python
# v2 API (current)
forked = session.fork()        # creates a ForkSession (picklable)
# worker writes to forked session
session.merge(forked_session)  # merge changesets
session.commit(...)            # one atomic commit
```

Each worker gets a forked session, writes its chunks independently, then the main
process merges all fork sessions before committing. This is documented in Icechunk's
parallel write docs and scales to thousands of concurrent S3 writes.

> Source: https://icechunk.io/en/v1.1.4/parallel/
> Source: https://github.com/earth-mover/icechunk/discussions/802

---

## Source index

- [Python 3.14 multiprocessing docs — start methods](https://docs.python.org/3/library/multiprocessing.html)
- [Python 3.14 concurrent.futures docs](https://docs.python.org/3/library/concurrent.futures.html)
- [loky — Reusable Process Pool Executor](https://loky.readthedocs.io/en/stable/)
- [loky API Reference](https://loky.readthedocs.io/en/stable/API.html)
- [loky GitHub (joblib)](https://github.com/joblib/loky)
- [MPIRE shared_objects documentation](https://sybrenjansen.github.io/mpire/v2.3.0/usage/workerpool/shared_objects.html)
- [multiprocessing.shared_memory — Python 3.14 docs](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
- [CPython issue #117262 — SharedMemory on macOS](https://github.com/python/cpython/issues/117262)
- [Sharing large NumPy arrays across multiprocessing — Luis Sena](https://luis-sena.medium.com/sharing-big-numpy-arrays-across-python-processes-abf0dc2a0ab2)
- [On sharing large arrays with multiprocessing — Mianzhi Wang](https://research.wmz.ninja/articles/2018/03/on-sharing-large-arrays-when-using-pythons-multiprocessing.html)
- [ProcessPoolExecutor initializer pattern](https://www.pythontutorials.net/blog/launch-concurrent-futures-processpoolexecutor-with-initialization/)
- [Ray tips for first-time users — overhead warnings](https://docs.ray.io/en/latest/ray-core/tips-for-first-time.html)
- [TaPS benchmark: ProcessPoolExecutor vs Ray vs Dask vs TaskVine](https://arxiv.org/pdf/2408.07236)
- [Benchmarking Ray vs multiprocessing vs concurrent.futures](https://medium.com/analytics-vidhya/benchmarking-performances-and-scaling-of-time-series-forecast-with-multiprocessing-concurrent-68a8c552afd6)
- [asyncio Queue producer-consumer](https://www.krython.com/tutorial/python/asyncio-queues-producer-consumer)
- [asyncio Queue patterns 2026](https://oneuptime.com/blog/post/2026-01-30-python-asyncio-queues/view)
- [joblib.Parallel docs — memmap for large arrays](https://joblib.readthedocs.io/en/stable/parallel.html)
- [scikit-learn parallelism guide](https://scikit-learn.org/stable/computing/parallelism.html)
- [astropy parallel_fit_dask](https://docs.astropy.org/en/stable/modeling/parallel-fitting.html)
- [Iris Dask bags and greedy parallelism warning](https://scitools-iris.readthedocs.io/en/v3.8.0/further_topics/dask_best_practices/dask_bags_and_greed.html)
- [gnssrefl rinex2snr parallel flag](https://gnssrefl.readthedocs.io/en/latest/api/gnssrefl.rinex2snr_cl.html)
- [Icechunk parallel writes docs](https://icechunk.io/en/v1.1.4/parallel/)
- [Icechunk GitHub discussion #802 — parallel writes](https://github.com/earth-mover/icechunk/discussions/802)
- [Python multiprocessing start methods — switching to spawn discussion](https://discuss.python.org/t/switching-default-multiprocessing-context-to-spawn-on-posix-as-well/21868)
- [SuperFastPython — ProcessPoolExecutor guide](https://superfastpython.com/processpoolexecutor-in-python/)
