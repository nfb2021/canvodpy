# Dask & Resource Management

## What is Dask

[Dask](https://www.dask.org/) is a Python library for parallel computing. It
distributes work across multiple CPU cores automatically, so that processing
many GNSS files happens simultaneously instead of one at a time.

canVODpy uses Dask's **Distributed** scheduler, which creates a local cluster
of worker processes on your machine. Each worker handles one GNSS file at a time,
and the scheduler coordinates the work.

---

## Why canVODpy uses Dask

GNSS-Transmissometry processing involves reading hundreds or thousands of
observation files per site. On shared machines (university servers, HPC nodes),
it's important to:

- **Use available cores** without manually tuning parallelism
- **Respect memory limits** so other users aren't affected
- **Handle failures gracefully** -- if a worker runs out of memory, Dask restarts
  it and retries the task
- **Monitor progress** through a web dashboard

Dask provides all of this out of the box.

---

## How it works in canVODpy

When you run the processing pipeline, canVODpy creates a `DaskClusterManager`
that starts a `LocalCluster`:

```
LocalCluster
  Worker 0  ──  1 process, 1 core
  Worker 1  ──  1 process, 1 core
  Worker 2  ──  1 process, 1 core
  ...
```

Each worker process reads and preprocesses one GNSS file at a time. The
scheduler distributes files across workers and collects results.

### Resource modes

| Mode | Use case | Behaviour |
|------|----------|-----------|
| `auto` | Local machine, single user | Dask detects available cores and memory automatically |
| `manual` | Shared server, HPC node | You set explicit limits on workers, memory, and CPU cores |

Configure the mode in `canvod.yaml` under `processing.params:`:

```yaml
processing:
  resource_mode: auto
```

For shared machines:

```yaml
processing:
  resource_mode: manual
  n_max_threads: 4          # use 4 worker processes
  max_memory_gb: 16         # soft RAM limit across all workers
  threads_per_worker: 1     # threads per worker (1 is usually best)
  cpu_affinity: [0, 1, 2, 3]  # pin to specific CPU cores (Linux only)
  nice_priority: 10         # lower process priority (0=normal, 19=lowest)
```

---

## Cluster lifecycle

`DaskClusterManager` owns the full lifetime of the local Dask cluster. It starts
the cluster when the pipeline begins and shuts it down when the pipeline ends,
regardless of whether the run completes normally, raises an exception, or is
interrupted by the user.

Shutdown happens automatically through two complementary mechanisms. When the
manager is used as a context manager — which is how the pipeline always runs it
— the cluster is stopped in `__exit__` as soon as the `with` block exits.
Additionally, a handler is registered with Python's `atexit` module at creation
time, so the cluster is also stopped if the Python process exits without
executing the `with` block's cleanup (for example, if `sys.exit()` is called
from a Dask worker or a signal handler). Both paths call the same `close()`
method, which is guarded against double execution: if `close()` is called a
second time — for instance, because atexit fires after `__exit__` has already
run — it returns immediately without attempting to stop an already-stopped
cluster.

You never call `close()` directly. The manager is designed to be used
exclusively as a context manager, and the pipeline infrastructure handles
startup and teardown transparently.

```python
# The pipeline does this internally — you do not call these methods yourself
with DaskClusterManager(config) as manager:
    client = manager.client
    # ... work happens here ...
# cluster is stopped here, or by atexit if the process exits first
```

---

## Worker plugins

### ResourceInitPlugin

When `cpu_affinity` or `nice_priority` is set, canVODpy registers a Dask
`WorkerPlugin` that configures each worker process at startup:

- **CPU affinity** (Linux only): pins the worker to specific CPU cores using
  `os.sched_setaffinity`, preventing it from migrating across all cores
- **Nice priority**: lowers the process priority using `os.setpriority`, so
  interactive users on the same machine get CPU time first

If a worker is restarted (e.g., after an out-of-memory kill), the plugin
re-applies these settings automatically.

### MemoryMonitor

The `MemoryMonitor` logs system memory usage at key points during processing.
It does **not** enforce limits -- Dask's built-in nanny process handles actual
memory enforcement by killing and restarting workers that exceed their allocation.

---

## Dask arrays in Icechunk stores

canVODpy stores processed GNSS data in Icechunk/Zarr stores using chunked arrays.
When you read data back from a store, Dask can load these chunks lazily -- only
the chunks you actually access are read into memory.

This means the same Dask cluster that processes RINEX files can also read from
the store without loading the entire dataset:

```python
import xarray as xr

# Opens lazily -- no data loaded yet
ds = xr.open_zarr(store, group="rosalia/reference_01")

# Only loads the chunks needed for this slice
snr_day1 = ds.SNR.sel(epoch="2025-01-01")
```

---

## Dashboard

When a Dask cluster is running, a monitoring dashboard is available at:

```
http://localhost:8787
```

The dashboard shows:

- Active tasks and worker utilisation
- Memory usage per worker
- Task stream (timeline of completed work)
- Progress bars for running computations

---

## Configuration reference

| Field | Default | Description |
|-------|---------|-------------|
| `resource_mode` | `auto` | `auto` or `manual` |
| `n_max_threads` | -- | Number of worker processes (required in manual mode) |
| `max_memory_gb` | -- | Soft RAM limit in GB (manual mode) |
| `threads_per_worker` | `1` | Threads per worker process |
| `cpu_affinity` | -- | List of CPU core IDs to pin workers to (Linux only) |
| `nice_priority` | `0` | Process priority: 0 = normal, 19 = lowest |

!!! tip "Fallback"

    If Dask is not installed, canVODpy falls back to `ProcessPoolExecutor` from
    the Python standard library. All resource management features require Dask.
