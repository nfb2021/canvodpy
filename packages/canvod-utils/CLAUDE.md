# canvod-utils

Date parsing and shared utilities. Configuration models and loading now
live in [[canvod-config]] (`canvod.config`), not here.

## Key modules

| Module | Purpose |
|---|---|
| `tools/` | `YYYYDOY`, `YYDOY` date parsing, `file_hash()`, `isfloat`, `get_version_from_pyproject` |

Removed 2026-07-14: the `diagnostics/` module (`TaskMetrics`, `track_memory`,
`track_time`, `BatchTracker`, `DatasetReport`, `retry`, SQLite-backed
storage) was a fully dead chain — zero real callers anywhere in the
pipeline, only re-exported through `canvodpy.utils.perf` /
`canvodpy.utils.__init__`, neither of which anything imported from either.
Superseded by the live OpenTelemetry-based tracing in
`canvodpy.utils.telemetry`.

## Testing

```bash
uv run pytest packages/canvod-utils/tests/
```
