---
name: icechunk
description: "Transactional, versioned storage engine for Zarr v3 on cloud object storage. Git-like version control for N-D arrays with ACID transactions, time travel, branching, and xarray integration."
---

# Icechunk

## Overview

Icechunk is a transactional storage engine for Zarr v3, adding Git-like version
control to multidimensional array data. It provides ACID transactions, time
travel, branching/tagging, and deduplication on cloud object storage (S3, GCS,
Azure) or local filesystems. Apply this skill when working with Icechunk repos,
sessions, stores, version control, or xarray/Zarr integration on Icechunk.

**Icechunk 2.x API** — the examples below use the current stable API.

## Quick Start

### Installation

```bash
uv add icechunk
```

Requires Zarr Python 3 (Zarr v3 spec).

### Create a Repository

```python
import icechunk

# Local filesystem
storage = icechunk.local_filesystem_storage("/path/to/repo")
repo = icechunk.Repository.create(storage)

# S3
storage = icechunk.s3_storage(bucket="my-bucket", prefix="my-prefix", from_env=True)
repo = icechunk.Repository.create(storage)

# GCS
storage = icechunk.gcs_storage(bucket="my-bucket", prefix="my-prefix", from_env=True)
repo = icechunk.Repository.create(storage)

# Open an existing repo (does not create)
repo = icechunk.Repository.open(storage)

# Open or create
repo = icechunk.Repository.open_or_create(storage)
```

### Sessions and Stores

Sessions are the gateway to reading and writing data. A session yields a
`zarr.Store` that can be used with Zarr or xarray.

```python
# Writable session (only from branch tip)
session = repo.writable_session("main")
store = session.store  # zarr.Store

# Read-only session (from branch, tag, or snapshot ID)
session = repo.readonly_session(branch="main")
session = repo.readonly_session(tag="v1.0")
session = repo.readonly_session(snapshot_id="abc123...")
store = session.store
```

**Key rule:** After `session.commit()`, the session becomes read-only. Create a
new writable session for further writes.

### Write and Commit with Zarr

```python
import zarr

session = repo.writable_session("main")
store = session.store

# Create group and array
group = zarr.group(store)
array = group.create("my_array", shape=(100,), dtype="f4", chunks=(10,))
array[:] = 42.0

# Commit creates an immutable snapshot
snapshot_id = session.commit("initial data")
```

### Transaction Context Manager

Simplifies the write-commit pattern:

```python
with repo.transaction("main", message="update values") as store:
    group = zarr.open_group(store)
    group["my_array"][:10] = 99.0
# Auto-commits on clean exit, auto-rolls-back on exception
```

## Xarray Integration

### Writing xarray Datasets

```python
import xarray as xr
from icechunk.xarray import to_icechunk

session = repo.writable_session("main")

# Write dataset — use to_icechunk (not to_zarr) for full Icechunk support
to_icechunk(ds, session)
snapshot_id = session.commit("add dataset")
```

**Why `to_icechunk` over `to_zarr`?**
- Required for distributed/parallel writes (Dask, multiprocessing)
- Ensures all remote writes are captured in the commit
- If using `to_zarr` instead, you must pass `zarr_format=3, consolidated=False`

### Appending along a dimension

```python
session = repo.writable_session("main")
to_icechunk(ds_new, session, append_dim="time")
session.commit("append new time steps")
```

### Reading xarray Datasets

```python
# From latest branch state
session = repo.readonly_session(branch="main")
ds = xr.open_zarr(session.store, consolidated=False)

# From a specific snapshot (time travel)
session = repo.readonly_session(snapshot_id=earlier_snapshot)
ds = xr.open_zarr(session.store, consolidated=False)
```

**Always pass `consolidated=False`** — Icechunk manages metadata internally
and does not use Zarr consolidated metadata.

## Version Control

### Snapshots and Ancestry

Every `commit()` creates an immutable snapshot with a unique hash ID.

```python
# Browse history
for snapshot in repo.ancestry(branch="main"):
    print(snapshot.id, snapshot.message, snapshot.written_at)
```

### Branches

```python
# List branches
repo.list_branches()  # ["main", "dev", ...]

# Create branch from current tip
tip = repo.lookup_branch("main")
repo.create_branch("dev", snapshot_id=tip)

# Write to a branch
session = repo.writable_session("dev")
# ... write data ...
session.commit("dev changes")

# Delete a branch
repo.delete_branch("dev")

# Reset branch to earlier snapshot
repo.reset_branch("main", snapshot_id=earlier_id)
```

### Tags

```python
# Create immutable tag
repo.create_tag("v1.0", snapshot_id=tip)

# Read from tag
session = repo.readonly_session(tag="v1.0")

# List and delete tags
repo.list_tags()
repo.delete_tag("v1.0")
```

### Time Travel

```python
# Go back to any snapshot
session = repo.readonly_session(snapshot_id=old_snapshot_id)
ds = xr.open_zarr(session.store, consolidated=False)

# Create branch from historical snapshot to modify old data
repo.create_branch("fix-old-data", snapshot_id=old_snapshot_id)
```

## Configuration

### Repository Config

```python
from icechunk import RepositoryConfig, CompressionConfig, CachingConfig, ManifestConfig

config = RepositoryConfig(
    inline_chunk_threshold_bytes=512,      # chunks smaller than this go in manifest
    unsafe_overwrite_refs=False,           # NEVER set True in production
    compression=CompressionConfig(algorithm="zstd", level=5),
    caching=CachingConfig(
        num_snapshot_nodes=0,              # LRU cache for snapshot nodes
        num_manifest_nodes=0,              # LRU cache for manifest nodes
        num_transaction_changes_nodes=0,
        num_bytes_attributes=0,
        num_bytes_chunks=0,
    ),
    manifest=ManifestConfig(
        preload=ManifestPreloadConfig(...),
        splitting=ManifestSplittingConfig(...),
    ),
    storage=StorageSettings(
        concurrency=StorageConcurrency(
            max_concurrent_requests_for_object=10,  # per-object parallelism
            ideal_concurrent_request_size=8_388_608, # 8 MiB per request part
        ),
    ),
)
repo = icechunk.Repository.create(storage, config=config)
```

### Compression

Icechunk uses internal compression (separate from Zarr codec compression) for
manifests, attributes, and transaction logs:

| Setting | Default | Description |
|---|---|---|
| `compression_algorithm` | `zstd` | `zstd`, `lz4`, or `gzip` |
| `compression_level` | `5` | 1=fast, 22=max (for zstd) |

### Caching

LRU caches for snapshot/manifest nodes and attribute/chunk bytes. All default to
0 (disabled). Enable for read-heavy workloads:

```python
caching=CachingConfig(
    num_snapshot_nodes=100,
    num_manifest_nodes=100,
    num_bytes_attributes=10_000_000,   # 10 MB for attrs
    num_bytes_chunks=100_000_000,      # 100 MB for chunks
)
```

### Manifest Splitting

Large manifests slow down reads/writes. Splitting breaks them by array and
optionally by dimension coordinate ranges:

```python
from icechunk import (
    ManifestConfig, ManifestSplittingConfig,
    ManifestSplitCondition, ManifestSplitDimCondition,
)

# ManifestSplittingConfig.from_dict maps:
#   condition → {dim_condition → max_chunk_refs_per_sub_manifest}
splitting = ManifestSplittingConfig.from_dict({
    # Split any array when a sub-manifest exceeds 1000 chunk refs
    ManifestSplitCondition.name_matches(".*"): {
        ManifestSplitDimCondition.Any(): 1000,
    },
    # Also split obs/snr along axis 0 (epoch) every 34560 indices
    ManifestSplitCondition.name_matches("obs|snr"): {
        ManifestSplitDimCondition.Axis(0): 34560,
    },
})

# Wrap in ManifestConfig when assigning to RepositoryConfig
config = RepositoryConfig(
    manifest=ManifestConfig(splitting=splitting),
)
```

**Conditions:**
- `ManifestSplitCondition.name_matches(regex)` — match by array name
- `ManifestSplitCondition.path_matches(regex)` — match by full array path
- Combine with `&` (AND) or `|` (OR) operators

**Dimension conditions:**
- `ManifestSplitDimCondition.Any()` — split along any dimension
- `ManifestSplitDimCondition.Axis(n)` — split along the nth axis
- `ManifestSplitDimCondition.DimensionName(name)` — split along a named dim

**When to split:** Repos with >100k chunks per array. Splitting makes commits
faster (only modified sub-manifests are rewritten) and reads faster (only
relevant sub-manifests are fetched).

### Manifest Preloading

Preload chunk manifests into memory at session open for faster first reads:

```python
from icechunk import (
    ManifestConfig, ManifestPreloadConfig, ManifestPreloadCondition,
)

preload = ManifestPreloadConfig(
    max_total_refs=100_000_000,     # safety cap on total refs loaded
    max_arrays_to_scan=1000,        # max arrays to evaluate conditions on
    preload_if=(
        # Preload arrays matching name AND with refs in [0, 50_000]
        ManifestPreloadCondition.name_matches("obs|snr|epoch")
        & ManifestPreloadCondition.num_refs(0, 50_000)
    ),
)

# Wrap in ManifestConfig when assigning to RepositoryConfig
config = RepositoryConfig(
    manifest=ManifestConfig(preload=preload),
)
```

**Conditions:**
- `ManifestPreloadCondition.name_matches(regex)` — match by array name
- `ManifestPreloadCondition.path_matches(regex)` — match by full path
- `ManifestPreloadCondition.num_refs(from, to)` — match by chunk-ref count range
- `ManifestPreloadCondition.true` / `.false` — unconditional preload / skip
- Combine with `&` (AND) or `|` (OR) operators

**When to preload:** Read-heavy workloads accessing known arrays repeatedly.
Increases memory use but eliminates per-read manifest fetches.

### Persisting Config

```python
# Save config to the repo (stored alongside data)
repo.save_config()

# Config is automatically loaded on Repository.open()
```

### Concurrency Tuning

Two independent concurrency knobs:

1. **Zarr async concurrency** — controls how many Zarr operations run in
   parallel. Set via `zarr.config`:
   ```python
   import zarr
   zarr.config.set({"async.concurrency": 20})  # default: 10
   ```

2. **Icechunk max concurrent requests** — global limit on simultaneous HTTP
   requests to object storage:
   ```python
   import icechunk
   icechunk.set_max_concurrent_requests(50)  # default: varies by platform
   ```

For cloud storage, increase both. For local filesystem, defaults are usually
fine. If you see stalled reads, Icechunk detects stalled network streams and
automatically retries.

## Concurrency and Transactions

### ACID Guarantees

- **Atomicity**: all changes in a commit succeed or none are persisted
- **Consistency**: no partial writes visible to readers
- **Isolation**: serializable isolation — readers always see committed state
- **Durability**: committed snapshots are immutable and permanent

### Parallel Writes

For distributed writes with Dask or multiprocessing, use `to_icechunk`:

```python
from icechunk.xarray import to_icechunk

# Dask-backed dataset — writes happen in parallel
to_icechunk(dask_ds, session)
session.commit("parallel write")
```

### Conflict Resolution

If two writers commit to the same branch concurrently, the second commit will
fail with a conflict error. Solutions:
1. Retry the transaction (re-read, re-apply changes, re-commit)
2. Use separate branches and merge later
3. Use optimistic concurrency with snapshot IDs

## Performance Tips

### Chunk Sizing

Choose chunks based on access patterns:

```python
# Time-series: chunk along time, keep spatial dims whole
# For GNSS data with (epoch, sid) dims:
#   epoch: 34560 (one day of 2.5s data)
#   sid: -1 (all signals together)
ds.to_zarr(store, encoding={"obs": {"chunks": (34560, -1)}})
```

### Best Practices

1. **Use `transaction` context manager** for simple write-commit patterns
2. **Never use `consolidated=True`** with Icechunk — it's unnecessary and unsupported
3. **Use `to_icechunk`** instead of `to_zarr` for distributed writes
4. **Create new sessions after commits** — committed sessions are read-only
5. **Use branches for experiments** — keep `main` stable
6. **Tag releases** — immutable references for reproducibility
7. **Scope repos to related data** — one repo per logical dataset, not one giant repo

## Common Pitfalls

| Pitfall | Problem | Solution |
|---|---|---|
| Writing after commit | `session.commit()` makes session read-only | Create new `repo.writable_session()` |
| Missing `consolidated=False` | xarray tries to read consolidated metadata | Always pass `consolidated=False` to `open_zarr` |
| Using `to_zarr` for parallel writes | Distributed writes may not be captured | Use `to_icechunk` from `icechunk.xarray` |
| Concurrent branch writes | Second commit conflicts | Retry, use separate branches, or use `transaction` |
| Large inline threshold | Too many small chunks in manifest | Keep `inline_chunk_threshold_bytes` at 512 (default) |
| Forgetting `zarr_format=3` | Zarr Python defaults may differ | Pass `zarr_format=3` when using `to_zarr` directly |

## Storage Backends

| Backend | Function | Use Case |
|---|---|---|
| Local filesystem | `icechunk.local_filesystem_storage(path)` | Development, testing |
| AWS S3 | `icechunk.s3_storage(bucket, prefix)` | Production cloud |
| Google Cloud Storage | `icechunk.gcs_storage(bucket, prefix)` | Production cloud |
| Azure Blob | `icechunk.azure_storage(container, prefix)` | Production cloud |
| In-memory | `icechunk.in_memory_storage()` | Unit tests |

## API Quick Reference

### Repository

| Method | Description |
|---|---|
| `Repository.create(storage)` | Create new repo |
| `Repository.open(storage)` | Open existing repo |
| `Repository.open_or_create(storage)` | Open or create |
| `repo.writable_session(branch)` | Get writable session |
| `repo.readonly_session(branch=, tag=, snapshot_id=)` | Get read-only session |
| `repo.transaction(branch, message=)` | Context manager for write+commit |
| `repo.ancestry(branch=)` | Iterate snapshot history |
| `repo.list_branches()` | List all branches |
| `repo.create_branch(name, snapshot_id=)` | Create branch |
| `repo.delete_branch(name)` | Delete branch |
| `repo.reset_branch(name, snapshot_id=)` | Reset branch tip |
| `repo.lookup_branch(name)` | Get branch tip snapshot ID (O(1)) |
| `repo.lookup_snapshot(snapshot_id)` | Get snapshot info object with `.id`, `.message`, `.written_at`, `.parent_id`, `.metadata` (O(1)) |
| `repo.list_tags()` | List all tags |
| `repo.create_tag(name, snapshot_id=)` | Create immutable tag |
| `repo.delete_tag(name)` | Delete tag |

### Session

| Method | Description |
|---|---|
| `session.store` | Access `zarr.Store` |
| `session.commit(message)` | Commit changes, advance branch tip, return snapshot ID |
| `session.flush(message)` | Create anonymous snapshot without advancing branch (for checkpoints); session becomes read-only after call |
| `session.amend(message)` | Replace the immediately preceding snapshot with updated content |
| `session.has_uncommitted_changes` | Check for pending changes |
| `session.snapshot_id` | ID of the snapshot this session is based on |

### Xarray

| Function | Description |
|---|---|
| `icechunk.xarray.to_icechunk(ds, session)` | Write dataset |
| `icechunk.xarray.to_icechunk(ds, session, append_dim=)` | Append along dim |
| `xr.open_zarr(session.store, consolidated=False)` | Read dataset |
