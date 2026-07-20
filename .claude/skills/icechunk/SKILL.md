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

**Tag deletion is permanent and logical, not physical**: deleting a tag
writes a `.deleted` marker next to it — the tag name can **never be
reused**, even after deletion (design doc `006-tag-delete.md`). Plan tag
names accordingly (e.g. don't expect to re-create `v1.0` later with
different contents).

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
    compression=CompressionConfig(algorithm="zstd", level=3),
    caching=CachingConfig(
        num_snapshot_nodes=500_000,        # LRU cache for snapshot nodes (default)
        num_chunk_refs=15_000_000,         # LRU cache for chunk references (default)
        num_transaction_changes=0,
        num_bytes_attributes=0,
        num_bytes_chunks=0,
    ),
    manifest=ManifestConfig(
        preload=ManifestPreloadConfig(...),
        splitting=ManifestSplittingConfig(...),
    ),
    storage=StorageSettings(
        concurrency=StorageConcurrencySettings(
            max_concurrent_requests_for_object=10,  # per-object parallelism
            ideal_concurrent_request_size=8_388_608, # 8 MiB per request part
        ),
    ),
)
repo = icechunk.Repository.create(storage, config=config)
```

Note: `unsafe_overwrite_refs` (present in Icechunk 1.x) was **removed** from
`RepositoryConfig` in 2.x — don't reference it.

### Compression

Icechunk uses internal compression (separate from Zarr codec compression) for
manifests, attributes, and transaction logs:

| Setting | Default | Description |
|---|---|---|
| `algorithm` | `zstd` | `zstd`, `lz4`, or `gzip` |
| `level` | `3` | 1=fast, 22=max (for zstd) |

### Caching

`CachingConfig` fields are `num_snapshot_nodes`, `num_chunk_refs`,
`num_transaction_changes`, `num_bytes_attributes`, `num_bytes_chunks` — **not**
`num_manifest_nodes`/`num_transaction_changes_nodes` (don't exist). Caching is
**not** all-disabled by default — snapshot-node and chunk-ref caching are on
with large limits out of the box; only the byte-based attribute/chunk caches
default to off:

| Field | Default |
|---|---|
| `num_snapshot_nodes` | 500,000 |
| `num_chunk_refs` | 15,000,000 |
| `num_transaction_changes` | 0 |
| `num_bytes_attributes` | 0 |
| `num_bytes_chunks` | 0 |

Enable the byte-based caches for read-heavy workloads:

```python
caching=CachingConfig(
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
   requests to object storage. There is no module-level
   `icechunk.set_max_concurrent_requests()` function — set it on the config:
   ```python
   config = icechunk.RepositoryConfig(max_concurrent_requests=50)
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
3. Use `session.commit(message, rebase_with=solver, rebase_tries=N)` — automatic
   rebase-and-retry against a conflict solver, instead of a hand-rolled retry loop
4. Use optimistic concurrency with snapshot IDs

`commit()` also accepts `metadata=` (arbitrary dict attached to the snapshot,
queryable later via `ancestry()`/`lookup_snapshot()` without opening the
dataset) and `allow_empty=` (permit a commit with no changes). `readonly_session()`
additionally accepts `as_of=datetime` — resolve a branch to the latest snapshot
at or before a given time, without knowing its snapshot ID.

## Maintenance: Expiration & Garbage Collection

Icechunk keeps **every** snapshot ever written, forever, by default — nothing
is deleted automatically. For any repo under sustained daily/hourly writes
(exactly canvodpy's shape), snapshot/manifest count grows unbounded unless
maintenance is run deliberately. This is a two-stage, explicitly separate
process — don't conflate them:

### Stage 1: Expiration (metadata-only, reversible in effect until GC)

```python
expired_ids = repo.expire_snapshots(
    older_than=datetime(2026, 1, 1, tzinfo=timezone.utc),
    delete_expired_branches=False,   # keep branches whose tip is now expired
    delete_expired_tags=False,       # keep tags whose tip is now expired
)
```

- Operates **only on `written_at`** (write-time) — there is no notion of "the
  data's own date." If you need retention keyed to the data's own time range
  rather than when it was committed, you must select snapshots yourself (e.g.
  via `commit(metadata={...})` written at write time, read back through
  `ancestry()`) and expire/tag around that — Icechunk doesn't do it natively.
- **No objects are deleted at this stage** — `expire_snapshots` rewrites the
  ancestry chain (an existing snapshot's `parent_id` is edited in place to
  skip the expired run, git-squash-style) so expired snapshots become
  unreachable from any surviving branch/tag. Manifests, chunks, and snapshot
  files on disk/object-store are untouched until GC actually runs.
- The **root snapshot and each branch's tip are never expired**. A tag or
  branch whose tip snapshot would otherwise be expired stays reachable
  (protecting it) unless `delete_expired_*=True`, in which case that tag/
  branch itself gets deleted (not the snapshot — deleting the ref just makes
  the snapshot unreachable so GC *can* collect it).
- **Only one expiration or GC operation should run at a time** — concurrent
  history-rewrite operations have undefined behavior (not just "risky", the
  design doc says undefined). IC2 does have self-protection against races
  with *new* commits arriving during the operation (see below), but not
  against two expire/GC runs overlapping each other.
- Treat this as an **administrative operation run when the repo isn't
  actively being written to** — not something to trigger casually mid-
  pipeline-run. Use a generous `older_than` margin (weeks to months, not
  hours) so it can never touch anything from an in-flight write session.

### Stage 2: Garbage collection (physically deletes)

```python
summary = repo.garbage_collect(
    delete_object_older_than=datetime(2026, 1, 1, tzinfo=timezone.utc),
    dry_run=True,   # report what WOULD be deleted, delete nothing — run this first
)
```

- Deletes any manifest/chunk/snapshot object no longer reachable from any
  branch or tag — i.e. only what Stage 1 already made unreachable.
- **Self-protecting against concurrent writes** (IC2 design): GC first
  collects its deletable-object list, then does a conditional update. If a
  new branch/tag/snapshot appears pointing at an about-to-be-deleted object
  during that window, GC **restarts** (bounded retries) instead of deleting
  something a concurrent writer needs. This is real protection, not just
  operator discipline — but the generous-margin practice above is still the
  right default; don't rely on the retry mechanism as your only safety net.
- Always run `dry_run=True` first on a repo you haven't GC'd before,
  especially one with a large accumulated backlog — there's no documented
  cost model for GC time/memory at scale (tens of thousands of manifests),
  so a first-ever run's duration is unknown until measured.
- **Recommended cadence** (operational guidance, not in the reference docs):
  expire every 1-2 months, GC every 15-30 days — running more frequently
  yields marginal storage savings for real operational risk. Not something
  to run every pipeline batch or every day.

### Scheduling maintenance in canvodpy

Everything above works, but nothing in canvodpy ever calls it automatically
— it's a human running `canvodpy store maintain <site> --execute` by hand
(and that command itself requires an interactive confirmation, so it can't
be scheduled unattended as-is). `canvodpy store maintain-due` is the
cron/systemd-timer-safe counterpart: never prompts, does nothing unless
`processing.storage.maintenance.enabled: true` in canvod-settings.yaml, no
pipeline run is currently active on the host (checked via a same-host PID
file, see `canvodpy.orchestrator.resources.PipelineRunLock`), and the
store's own ops log shows expiration/GC are actually due (per
`maintenance.expire_interval_days`/`.gc_delay_days`) — `MyIcechunkStore.
maintenance_due()` reads `ExpirationRan`/`GCRan` ops-log entries as the
source of truth rather than a separate marker file, since Icechunk writes
those atomically as part of the operation itself. `maintenance.
dry_run_until_confirmed` (default `true`) gates the very first automated
touch to report-only, matching `garbage_collect(dry_run=True)`'s own
recommended first-run practice.

Example cron entry (personal-machine deployment):
```
0 3 * * * cd /path/to/canvodpy && uv run canvodpy store maintain-due --all-sites >> ~/.canvodpy_maintenance.log 2>&1
```
Does **not** protect against a second host writing to the same store on a
network-mounted (CIFS/NFS) deployment — that case is a documented
operational constraint (keep the maintenance window and pipeline-run
windows apart by convention), not something this locking mechanism covers.

### `rewrite_manifests()` — manifest compaction without expiring anything

```python
new_snapshot = repo.rewrite_manifests(
    "compact manifests",
    branch="main",
    commit_method="new_commit",   # or "amend" (spec v2 only) to not grow history
)
```

Consolidates all of an array's fragmented manifests back to the currently
configured splitting config, in one operation — useful when a write pattern
creates many small manifests over time (e.g. one `to_icechunk()` call per
file rather than one per batch — each such call triggers its own internal
flush, which pushes touched chunks into a **new** manifest; see "Write cost
model" below). It's an ordinary commit under the hood (starts a writable
session, computes the rewrite, commits) — ordinary conflict semantics apply,
not a special unsafe operation. `commit_method="amend"` avoids adding a new
commit to history entirely (spec version 2 repos only).

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

### Write Cost Model — why many small `to_icechunk()` calls get expensive

Two distinct mechanisms, both real, at different scales:

1. **Per-flush manifest creation.** During `flush` (every `to_icechunk()`
   call, not just every `commit()`), touched chunks are streamed into a
   **new manifest**. Without manifest splitting configured, this is the
   *entire* array's manifest rewritten from scratch every time — "appending
   a small amount of data to a large array requires downloading and
   rewriting the entire manifest" (Icechunk's own performance guide). With
   splitting configured, the rewrite scope narrows to the *closure* of the
   modified arrays' manifest set — every array sharing a manifest with a
   touched array, not the whole store, but still not just the touched array
   alone if others are packed with it. **Practical implication**: one
   `to_icechunk()` call per file in a 96-file daily batch creates ~96
   manifests for that one commit; batching files into fewer, larger
   `to_icechunk()` calls (or periodic `rewrite_manifests()` compaction)
   directly reduces this.
2. **Per-commit repo-info rewrite.** IC2 keeps a single flatbuffer object at
   the repo root holding every ref (tags/branches) and every snapshot's
   metadata (~256 bytes/snapshot, including up to a 200-byte commit
   message), fetched at repo open and rewritten on every commit. This is
   **sharded**, not unbounded within one file — `RepositoryConfig.
   num_updates_per_repo_info_file` (default 1,000) caps how many updates
   live in a single repo-info file before a new one starts; lower values
   mean smaller per-write payloads but more object fetches to reconstruct
   history. `RepositoryConfig.repo_update_retries` controls retry backoff
   for repo-info update conflicts (default: 100 tries, 50ms initial
   backoff, 30s max backoff). For a store with sustained high commit
   frequency, tuning `num_updates_per_repo_info_file` down is worth
   experimenting with if commit latency (not manifest-flush latency) is the
   bottleneck — profile which one first, they have different fixes.

Mitigations for mechanism 1: batch writes into fewer `to_icechunk()` calls
per commit; tune manifest-set assignment (`ManifestSplittingConfig` rules)
so co-written variables share sets and unrelated ones don't; periodic
`rewrite_manifests()`. Mitigations for mechanism 2: `num_updates_per_repo_
info_file` tuning; periodic expiration to shrink total ancestry length
snapshots need to reconstruct from.

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
| One `to_icechunk()` call per file | Each flush creates a new manifest — N files/batch = N manifests/commit | Batch files into fewer, larger `to_icechunk()` calls; periodic `rewrite_manifests()` |
| `expire_snapshots(delete_expired_tags=True)` on a keeper-tag scheme | Deletes tags you meant to keep permanently | Default is `False` — only flip it if you've confirmed which tags are disposable |
| Running expiration/GC every batch or every day | Real but avoidable operational risk for marginal storage savings | Separate scheduled job, weeks-to-months cadence, not inside the pipeline's own write loop |
| Assuming caching is off by default | `num_snapshot_nodes`/`num_chunk_refs` default to 500k/15M (on); only byte-based caches default to 0 | Check `CachingConfig` defaults before assuming a memory budget |

## Storage Backends

| Backend | Function | Use Case |
|---|---|---|
| Local filesystem | `icechunk.local_filesystem_storage(path)` | Development, testing |
| AWS S3 | `icechunk.s3_storage(bucket, prefix)` | Production cloud |
| Google Cloud Storage | `icechunk.gcs_storage(bucket, prefix)` | Production cloud |
| Azure Blob | `icechunk.azure_storage(account=, container=, prefix=)` | Production cloud (`account` is required, keyword-only) |
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
| `repo.delete_tag(name)` | Delete tag — logical/permanent, name can never be reused |
| `repo.expire_snapshots(older_than, delete_expired_branches=False, delete_expired_tags=False)` | Soft-delete: rewrite ancestry, no objects removed yet. Write-time only |
| `repo.garbage_collect(delete_object_older_than, dry_run=False)` | Physically delete unreachable objects. Run `dry_run=True` first |
| `repo.rewrite_manifests(message, branch=, commit_method="new_commit"\|"amend")` | Consolidate fragmented manifests to current splitting config |
| `repo.save_config()` | Persist repository config to the repo itself |
| `repo.ops_log()` | Iterate the operations log (maintenance/admin op history) |
| `repo.total_chunks_storage()` | Aggregate chunk storage size |
| `repo.spec_version()` / `repo.fetch_spec_version(storage)` | Repo's on-disk format version |

### Session

| Method | Description |
|---|---|
| `session.store` | Access `zarr.Store` |
| `session.commit(message, metadata=None, rebase_with=None, rebase_tries=None, allow_empty=False)` | Commit changes, advance branch tip, return snapshot ID |
| `session.flush(message, metadata=None)` | Create anonymous snapshot without advancing branch (for checkpoints); session becomes read-only after call |
| `session.amend(message, metadata=None, allow_empty=False)` | Replace the immediately preceding snapshot with updated content. Cannot amend a repo's very first commit |
| `session.rebase(solver)` | Rebase this session's changes onto the current branch tip using a conflict solver |
| `session.has_uncommitted_changes` | Check for pending changes |
| `session.snapshot_id` | ID of the snapshot this session is based on |

### Xarray

| Function | Description |
|---|---|
| `icechunk.xarray.to_icechunk(ds, session)` | Write dataset |
| `icechunk.xarray.to_icechunk(ds, session, append_dim=)` | Append along dim |
| `xr.open_zarr(session.store, consolidated=False)` | Read dataset |
