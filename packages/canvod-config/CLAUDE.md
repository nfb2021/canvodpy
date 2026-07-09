# canvod-config

Configuration models and YAML loading for canvodpy. Foundation-layer package —
depended on directly by `canvod-readers`, `canvod-auxiliary`, `canvod-store`,
`canvod-store-metadata`, `canvod-ops`, and `canvodpy` itself. Not published to
PyPI as a standalone artifact (same as every other internal `canvod-*` package)
— it exists purely as a shared workspace dependency, not something meant to be
installed on its own.

## Key modules

| Module | Purpose |
|---|---|
| `models.py` | 40+ Pydantic models: `CanvodConfig`, `SiteConfig`, `ProcessingParams`, `StorageConfig`, `MetadataConfig`, `LoggingConfig` |
| `loader.py` | `ConfigLoader` — YAML config loading with overlay support, `find_monorepo_root()` |

## Config hierarchy

User config file (NEVER committed):
- `config/canvod-settings.yaml` — unified config: processing, sites, sids

Templates (committed): `config/canvod-settings.yaml.example`

Precedence: env var > overlay file (`--config` / `CANVOD_CONFIG_FILE`) > `canvod-settings.yaml` > package defaults.

## Pydantic conventions

- All models use `frozen=False` with `@cached_property` for lazy computation
- `ProcessingParams.file_pairing`: `"complete"` (all receivers) or `"paired"` (matched pairs)
- Config additions for metadata: `orcid`, `institution_ror`, `license`, `publisher`, etc.

## `find_monorepo_root()` gotcha

Walks up from `Path.cwd()` looking for a `.git` entry (file or directory — a
git worktree's `.git` is a file, not a directory, so both must count as a
valid root). Fixed 2026-07-09 after this broke recipe lookups when run from
inside a worktree.

## Testing

```bash
uv run pytest packages/canvod-config/tests/
```
