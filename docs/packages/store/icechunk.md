# Icechunk Storage

## Overview

Icechunk is a cloud-native transactional storage format for multidimensional array data providing ACID guarantees, built-in versioning, and Zarr compatibility.

## Rationale

| Feature | Icechunk | Zarr | NetCDF4 | HDF5 |
|---------|----------|------|---------|------|
| Version control | Yes | No | No | No |
| Cloud-native | Yes | Yes | No | No |
| Transactions | Yes | No | No | No |
| Chunking | Yes | Yes | Yes | Yes |
| Compression | Yes | Yes | Yes | Yes |

## Storage Structure

```
stores/
  rosalia/
    rinex/
      .icechunk/      # Icechunk metadata
      data/           # Chunked data files
      versions/       # Version snapshots
    vod/
      .icechunk/
      data/
      versions/
```

## Chunk Strategy

Default chunking for RINEX data:

```python
{
    "epoch": 34560,  # ~24 hours at 2.5s sampling
    "sid": -1        # All signals in one chunk
}
```

Epoch chunking aligns with daily processing granularity. Keeping all signal IDs in a single chunk (-1) optimizes VOD calculations that access all signals simultaneously.

## Configuration

```yaml
# config/processing.yaml
icechunk:
  compression_algorithm: zstd
  compression_level: 5
  inline_threshold: 512
  get_concurrency: 1
```

## Usage

### Initialize Store

```python
from icechunk import IcechunkStore

store = IcechunkStore.open_or_create(
    storage="file:///path/to/store",
    read_only=False
)
```

### Write with Transaction

```python
with store.transaction() as txn:
    ds = preprocess_dataset(raw_data)
    ds.to_zarr(store, mode="a")
    txn.commit(message="Added 2024-01-15 data")
```

### Version Control

```python
versions = store.list_versions()

store_v1 = IcechunkStore.open(
    storage="file:///path/to/store",
    version=versions[0]
)
ds = xr.open_zarr(store_v1)
```

### Query Time Range

```python
ds = xr.open_zarr(store)
subset = ds.sel(epoch=slice("2024-01-01", "2024-01-31"))
```

## Cloud Deployment

### S3 Backend

```python
store = IcechunkStore.open_or_create(
    storage="s3://bucket-name/path/to/store",
    storage_config={"region": "us-east-1", "credentials": "auto"}
)
```

### Azure Backend

```python
store = IcechunkStore.open_or_create(
    storage="az://container/path/to/store",
    storage_config={"account_name": "myaccount", "account_key": "..."}
)
```
