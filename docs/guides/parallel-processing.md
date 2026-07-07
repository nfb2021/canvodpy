# Parallel Processing & Resource Management

canVODpy processes many GNSS observation files per site — one per receiver per day,
sometimes split into sub-daily intervals. Running these sequentially on a single
core would be prohibitively slow for multi-year datasets. This page explains how
canVODpy distributes that work and how to configure resource limits for your machine.

---

## The parallelism model

canVODpy uses Python's standard `concurrent.futures` library — no external scheduler
required. The pipeline applies two levels of parallelism:

```
┌─────────────────────────────────────────┐
│  ThreadPoolExecutor (Wave A / Wave B)   │  ← receivers processed concurrently
│  ┌──────────────┐  ┌──────────────┐     │
│  │  Receiver A  │  │  Receiver B  │     │
│  │ ─────────── │  │ ─────────── │     │
│  │ProcessPool  │  │ProcessPool  │     │
│  │(file parse) │  │(file parse) │     │
│  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────┘
           │
           ▼  (sequential)
   Icechunk store  ←  one commit per receiver-day
```

**Wave A/B**: the outer `ThreadPoolExecutor` runs two groups of receivers
concurrently. Within each receiver, an inner `ProcessPoolExecutor` parses
individual GNSS files in parallel.

**Sequential writes**: Icechunk on a local filesystem cannot accept concurrent
commits. Every write is performed sequentially after parsing completes, with one
commit per receiver-day. This is a hard constraint of the local storage model
and ensures data integrity through Icechunk's snapshot mechanism.

!!! note "Reading from the store is always fast"
    `xarray.open_zarr()` loads only the array chunks you actually access — the
    full dataset is never read into memory at once.

---

## Configuration

Resource limits are set under `processing.params` in your `canvod-settings.yaml`:

=== "Automatic (local machine)"

    canVODpy detects available cores and memory automatically:

    ```yaml
    processing:
      params:
        resource_mode: auto
        days_per_batch: 1
    ```

=== "Manual (shared server / HPC)"

    Hard caps prevent the pipeline from monopolising shared resources:

    ```yaml
    processing:
      params:
        resource_mode: manual
        n_max_threads: 4          # number of worker processes
        max_memory_gb: 16         # soft RAM limit across all workers
        cpu_affinity: [0, 1, 2, 3]  # pin to specific CPU cores (Linux only)
        nice_priority: 10         # lower process priority (0=normal, 19=lowest)
        days_per_batch: 1         # days processed per commit
    ```

### Configuration reference

| Field | Default | Description |
|-------|---------|-------------|
| `resource_mode` | `auto` | `auto` (detect cores/memory) or `manual` (hard caps) |
| `n_max_threads` | — | Worker process count. Required when `resource_mode=manual` |
| `max_memory_gb` | — | Soft RAM limit in GB. Manual mode only |
| `days_per_batch` | `1` | Days of data per processing batch and Icechunk commit |
| `cpu_affinity` | — | CPU core IDs to pin workers to (Linux only) |
| `nice_priority` | `0` | Process priority: 0 = normal, 19 = lowest |

!!! tip "Shared servers"
    On a machine shared with colleagues, set `resource_mode: manual` with
    `n_max_threads` ≤ half the available cores and `nice_priority: 10`.
    This ensures interactive work on the same server is not disrupted.

---

## Memory monitoring

`MemoryMonitor` logs system memory usage at key points during a pipeline run.
It does not enforce limits — that is handled by the OS and the `max_memory_gb`
cap on worker processes. Logs are written to the configured logging output and
can be inspected to diagnose out-of-memory failures on constrained machines.

---

## Write granularity and data integrity

Each receiver-day produces one Icechunk commit. This maps directly to the three-layer
deduplication guard built into `canvod-store`:

1. **Hash match** — identical file content is never written twice
2. **Temporal overlap** — a new batch that overlaps existing epochs is rejected
3. **Intra-batch overlap** — duplicate epochs within a single batch are caught before writing

These checks run before every write, regardless of parallelism settings. A failed
write leaves the store unchanged — Icechunk's snapshot model means partial writes
are never committed.
