# canvod-utils

Configuration, date parsing, diagnostics, and shared utilities.

## Key modules

| Module | Purpose |
|---|---|
| `config/` | 40+ Pydantic models: `CanvodConfig`, `SiteConfig`, `ProcessingParams`, `StorageConfig`, `MetadataConfig`, `LoggingConfig` |
| `config/loader.py` | `ConfigLoader` — YAML/JSON/TOML config loading |
| `tools/` | `YYYYDOY`, `YYDOY` date parsing, `file_hash()` |
| `diagnostics/` | `TaskMetrics`, `track_memory`, `track_time`, `BatchTracker`, `DatasetReport` |

## Config hierarchy

User config file (NEVER committed):
- `config/canvod.yaml` — unified config: processing, sites, sids

Templates (committed): `config/canvod.yaml.example`

Legacy trio (`processing.yaml` / `sites.yaml` / `sids.yaml`) still loads with a
`DeprecationWarning`. Migrate with `canvod config migrate`.

## Pydantic conventions

- All models use `frozen=False` with `@cached_property` for lazy computation
- `ProcessingParams.file_pairing`: `"complete"` (all receivers) or `"paired"` (matched pairs)
- Config additions for metadata: `orcid`, `institution_ror`, `license`, `publisher`, etc.

## Testing

```bash
uv run pytest packages/canvod-utils/tests/
```
