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
| `models/` | Pydantic models, split by config section (dev/todo_later.md §4) — `__init__.py` re-exports everything, so `from canvod.config.models import X` is unaffected |
| `models/root.py` | `CanvodConfig` — top-level settings, composes `processing`/`sites`/`sids` |
| `models/processing.py` | `ProcessingConfig` — composes metadata/credentials/aux_data/params/compression/icechunk/storage/logging/preprocessing/references |
| `models/sites.py` | `SiteConfig`, `SitesConfig`, `ReceiverConfig`, `VodAnalysisConfig` |
| `models/sids.py` | `SidsConfig` — note: `_get_preset_sids()` resolves `presets/` via `Path(__file__).parent.parent`, one level up from this subpackage |
| `models/metadata.py`, `processing_params.py`, `compression.py`, `storage.py`, `logging.py`, `preprocessing.py`, `references.py`, `aux_data.py`, `base.py` | One config section each |
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
