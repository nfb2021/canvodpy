# Storage Strategies

## Overview

Three storage strategies control how existing data is handled during writes:

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| Skip | No write if data exists for the time range | Initial ingestion, pipeline restarts |
| Overwrite | Replace existing data for the time range | Reprocessing, algorithm updates |
| Append | Merge new data with existing | Continuous monitoring, extending time series |

## Skip Strategy

```python
store = MyIcechunkStore(store_path, strategy="skip")
store.write(dataset)  # No-op if data exists
```

Checks whether data exists for the given time range before writing. Suitable for raw RINEX observations, which do not change after initial ingestion.

## Overwrite Strategy

```python
store = MyIcechunkStore(store_path, strategy="overwrite")
store.write(dataset)  # Replaces existing data
```

Deletes existing data for the time range and writes new data with a new version snapshot. Suitable for processed results that may be recomputed with improved algorithms.

## Append Strategy

```python
store = MyIcechunkStore(store_path, strategy="append")
store.write(dataset)  # Merges with existing
```

Merges new data with existing data, handling overlapping time ranges. Suitable for live monitoring stations.

## Configuration

Strategy can be set via constructor, configuration file, or environment variable:

```python
store = MyIcechunkStore(store_path, strategy="append")
```

```yaml
# config/processing.yaml
storage:
  rinex_store_strategy: skip
  vod_store_strategy: overwrite
```

```bash
export CANVOD_STORE_STRATEGY=append
```

## Recommended Defaults

- **RINEX data (raw observations)**: `skip` -- raw data is immutable
- **VOD data (processed results)**: `overwrite` -- recompute as algorithms improve
- **Continuous monitoring**: `append` -- extend time series daily

## Performance Characteristics

| Strategy | Write Speed | Storage Efficiency | Data Safety |
|----------|-----------|-------------------|-------------|
| Skip | Fast | High | High |
| Overwrite | Medium | Moderate | Medium |
| Append | Slow | Lower | Lower |
