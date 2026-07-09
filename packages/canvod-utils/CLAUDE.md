# canvod-utils

Date parsing, diagnostics, and shared utilities. Configuration models and
loading now live in [[canvod-config]] (`canvod.config`), not here.

## Key modules

| Module | Purpose |
|---|---|
| `tools/` | `YYYYDOY`, `YYDOY` date parsing, `file_hash()`, `isfloat`, `get_version_from_pyproject` |
| `diagnostics/` | `TaskMetrics`, `track_memory`, `track_time`, `BatchTracker`, `DatasetReport`, `retry` |

## Testing

```bash
uv run pytest packages/canvod-utils/tests/
```
