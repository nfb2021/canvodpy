# Storage Strategies

## Overview

`canvod-store` supports three storage strategies for handling existing data:

1. **Skip** - Skip writing if data exists
2. **Overwrite** - Replace existing data
3. **Append** - Add to existing data

## Strategy Details

### Skip Strategy

```python
store = MyIcechunkStore(store_path, strategy="skip")
store.write(dataset)  # Skips if data exists
```

**Use cases:**
- Initial data ingestion
- Avoid accidental overwrites
- Fast pipeline restarts

**Behavior:**
- Checks if data exists for given time range
- If exists: skips write, returns immediately
- If not exists: writes data normally

### Overwrite Strategy

```python
store = MyIcechunkStore(store_path, strategy="overwrite")
store.write(dataset)  # Replaces existing data
```

**Use cases:**
- Reprocessing with updated algorithms
- Fixing corrupted data
- Complete dataset replacement

**Behavior:**
- Deletes existing data for time range
- Writes new data
- Creates new version snapshot

### Append Strategy

```python
store = MyIcechunkStore(store_path, strategy="append")
store.write(dataset)  # Adds to existing data
```

**Use cases:**
- Continuous data ingestion
- Extending time series
- Adding new signals

**Behavior:**
- Merges new data with existing
- Handles overlapping time ranges
- Maintains data consistency

## Configuration

Configure strategy via:

**1. Constructor parameter:**
```python
store = MyIcechunkStore(store_path, strategy="append")
```

**2. Configuration file:**
```yaml
# config/processing.yaml
storage:
  rinex_store_strategy: skip
  vod_store_strategy: overwrite
```

**3. Environment variable:**
```bash
export CANVOD_STORE_STRATEGY=append
```

## Best Practices

### For RINEX Data (Raw Observations)
```python
# Use skip strategy - raw data shouldn't change
rinex_store = MyIcechunkStore(
    rinex_path,
    strategy="skip"
)
```

### For VOD Data (Processed Results)
```python
# Use overwrite - recompute as algorithms improve
vod_store = MyIcechunkStore(
    vod_path,
    strategy="overwrite"
)
```

### For Continuous Monitoring
```python
# Use append - add new observations daily
monitor_store = MyIcechunkStore(
    monitor_path,
    strategy="append"
)
```

## Time Range Handling

All strategies respect time ranges:

```python
# Only affects data in specified range
store.write(
    dataset,
    time_range=("2024-01-01", "2024-01-31")
)
```

## Conflict Resolution

### Overlapping Time Ranges (Append Mode)
- **Last write wins** - Newer data overwrites older
- **Signal-level merging** - Different signals preserved
- **Metadata preserved** - Original metadata maintained

### Version Control
Each write creates a new version:
```python
# Access specific version
store.read(version="v1.2.3")

# List versions
versions = store.list_versions()
```

## Performance Considerations

| Strategy | Write Speed | Storage Use | Safety |
|----------|------------|-------------|--------|
| Skip | Fast ⚡ | Efficient | High ✅ |
| Overwrite | Medium | Moderate | Medium ⚠️ |
| Append | Slow | High | Low ⚠️ |

**Recommendations:**
- Use **skip** for production pipelines
- Use **overwrite** for development/testing
- Use **append** for live monitoring only
