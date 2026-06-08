# Icechunk Storage

Icechunk is a cloud-native transactional storage format for multidimensional arrays — Git-like versioning meets Zarr v3.

<div class="grid cards" markdown>

-   :fontawesome-solid-code-branch: &nbsp; **Versioned Writes**

    ---

    Every `commit()` produces an immutable snapshot with a hash-addressable ID.
    Roll back to any prior state with a single line.

-   :fontawesome-solid-bolt: &nbsp; **ACID Transactions**

    ---

    Multiple writes are atomic — either all succeed or none are persisted.
    No partial writes, no corrupt chunks, no reader/writer races.

-   :fontawesome-solid-cloud: &nbsp; **Cloud-Native**

    ---

    Local filesystem for development; S3, MinIO, or Cloudflare R2 for
    production. Zero code change to switch backends.

-   :fontawesome-solid-gauge-high: &nbsp; **Zarr v3 Chunks**

    ---

    Zstd-compressed chunks, O(1) epoch-range reads, compatible with
    `xarray.open_zarr()` out of the box.

</div>

---

## Why Icechunk over plain Zarr?

| Feature | Icechunk | Zarr v3 | NetCDF4 | HDF5 |
|---------|:--------:|:-------:|:-------:|:----:|
| Version control | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |
| Cloud-native | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |
| Atomic transactions | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |
| Chunked arrays | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } |
| Deduplication | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |

---

## Storage Structure

=== "Spec v2 (icechunk ≥ 2.0)"

    ```
    stores/
      rosalia/
        rinex/
          repo            # Unified repository info (branches, tags, config)
          snapshots/      # Immutable snapshot files
          chunks/         # SHA-256 addressed chunk data
        vod/
          repo
          snapshots/
          chunks/
    ```

=== "Spec v1 (icechunk 1.x)"

    ```
    stores/
      rosalia/
        rinex/
          .icechunk/      # Repository metadata + snapshots
          data/           # SHA-256 addressed chunk files
          refs/           # Branch heads
        vod/
          .icechunk/
          data/
          refs/
    ```

!!! info "Format compatibility"
    Icechunk 2.x reads and writes both v1 and v2 repositories — no migration required.
    Run `icechunk.upgrade_icechunk_repository(repo)` to opt in to the v2 format
    for a given store. `scan_stores()` detects both layouts automatically.

---

## Chunk Strategy

=== "Default"

    The default chunk shape is tuned for daily GNSS time series:

    ```python
    chunk_strategy = {"epoch": 34560, "sid": -1}
    ```

    | Dimension | Value | Rationale |
    |-----------|-------|-----------|
    | `epoch` | 34560 | ≈ 24 h at 2.5 s cadence — aligned to daily processing granularity |
    | `sid` | −1 (unlimited) | All signal IDs in one chunk — VOD computes across all signals simultaneously |

=== "Memory Estimate"

    For a typical 72-SID dataset at 1 Hz:

    ```python
    # float32, 24 h × 72 SIDs
    bytes_per_chunk = 86400 * 72 * 4   # ≈ 24 MB uncompressed
    # Zstd level 5 typically achieves 4–8× for GNSS float data
    bytes_compressed ≈ 3–6 MB per chunk
    ```

=== "Custom Chunks"

    Override per read call — does not affect on-disk layout:

    ```python
    ds = reader.read(
        time_range=("2024-01-01", "2024-01-31"),
        chunks={"epoch": 3600, "sid": -1},  # 1-hour lazy chunks in memory
    )
    ```

---

## Configuration

```yaml
# config/processing.yaml
icechunk:
  compression_algorithm: zstd
  compression_level: 5
  inline_threshold: 512
  get_concurrency: 1

  # Manifest preloading — loads coordinate manifests into memory at session open.
  # Worth enabling once stores grow beyond a few hundred commits.
  # manifest_preload_enabled: false
  # manifest_preload_max_refs: 100000000
  # manifest_preload_pattern: "epoch|sid"
```

| Key | Default | Description |
|-----|---------|-------------|
| `compression_algorithm` | `zstd` | Icechunk internal compression — `zstd`, `lz4`, or `gzip` |
| `compression_level` | `5` | Compressor level (1 = fast, 22 = max for zstd) |
| `inline_threshold` | `512` | Bytes below which chunks are stored inline in the manifest |
| `get_concurrency` | `1` | Concurrent partial-value reads (increase for S3/GCS) |
| `manifest_preload_enabled` | `false` | Pre-load coordinate manifests into memory at session open |
| `manifest_preload_max_refs` | `100000000` | Cap on chunk refs preloaded |
| `manifest_preload_pattern` | `"epoch\|sid"` | Regex for arrays to preload |

---

## Usage

=== "Initialize / Open"

    ```python
    from canvod.store import MyIcechunkStore

    # Open or create (filesystem)
    store = MyIcechunkStore("/data/stores/rosalia/rinex")

    # Open existing (read-only)
    store = MyIcechunkStore("/data/stores/rosalia/rinex", read_only=True)
    ```

=== "Write with Versioning"

    ```python
    from canvod.site import Site

    site = Site("Rosalia")

    # Append one day of observations → creates snapshot
    snapshot_id = site.rinex_store.append_dataset(
        ds,
        receiver_name="canopy_01",
    )
    print(f"Snapshot: {snapshot_id[:8]}")
    ```

=== "Version History"

    ```python
    # List all commits on main branch
    history = site.rinex_store.get_history()
    for entry in history:
        print(entry["snapshot_id"][:8], entry["written_at"], entry["commit_msg"])

    # Pretty-print — same output, one liner
    site.rinex_store.print_history(limit=20)

    # Open a specific historical snapshot
    ds_old = site.rinex_store.read(
        receiver_name="canopy_01",
        time_range=("2024-01-01", "2024-01-31"),
        snapshot=history[-1]["snapshot_id"],
    )

    # Visualise the commit graph (SVG in notebooks, coloured text in terminal)
    site.rinex_store.plot_commit_graph()

    # Repo-wide operations audit trail (commits, branch ops, GC, …)
    site.rinex_store.print_ops_log(limit=30)
    ```

=== "Query Time Range"

    ```python
    ds = site.rinex_store.read(
        receiver_name="canopy_01",
        time_range=("2024-01-01", "2024-06-30"),
    )

    # Lazily loaded — only reads chunks covering the range
    print(ds.epoch.values[[0, -1]])
    ```

---

## Cloud Deployment

=== "AWS S3"

    ```python
    # No code change — set the store path to an S3 URI
    store = MyIcechunkStore("s3://my-bucket/rosalia/rinex")
    ```

    Configure credentials via environment variables or instance roles:

    ```bash
    export AWS_DEFAULT_REGION=eu-central-1
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    ```

=== "MinIO / S3-Compatible"

    ```python
    import os
    os.environ["AWS_ENDPOINT_URL"] = "https://minio.example.com"
    os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"

    store = MyIcechunkStore("s3://canvod-data/rosalia/rinex")
    ```

=== "Cloudflare R2"

    ```python
    os.environ["AWS_ENDPOINT_URL"] = "https://<account_id>.r2.cloudflarestorage.com"
    os.environ["AWS_ACCESS_KEY_ID"] = "<r2_access_key>"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "<r2_secret_key>"

    store = MyIcechunkStore("s3://canvod-data/rosalia/rinex")
    ```

!!! tip "Local → Cloud"
    Switch from filesystem to S3 by changing the `store_path` string —
    no other code changes required.

---

## Deduplication

canvod-store uses SHA-256 file hashes to skip re-ingesting the same file:

```python
# In MyIcechunkStore.append_dataset()
if self._file_already_ingested(ds.attrs["File Hash"]):
    log.info("file_skipped", hash=ds.attrs["File Hash"][:8])
    return None

# Otherwise write + record hash
snapshot = self._write_and_commit(ds, ...)
self._record_ingested_hash(ds.attrs["File Hash"])
return snapshot
```

!!! info "Hash source"
    The `"File Hash"` attribute is set by the reader (`SbfReader.file_hash` /
    `Rnxv3Obs.file_hash`) — a 16-character SHA-256 prefix of the raw file.
    Duplicate ingestion is impossible even if the same file is submitted twice.
