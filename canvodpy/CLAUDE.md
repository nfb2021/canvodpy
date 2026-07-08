# canvodpy (orchestrator)

Main application package — orchestrates the full GNSS → VOD pipeline.

## Key modules

| Module | Purpose |
|---|---|
| `orchestrator/processor.py` | `RinexDataProcessor` — main pipeline (~2800 lines) |
| `orchestrator/pipeline.py` | `PipelineOrchestrator` — coordination |
| `api.py` | `Site`, `Pipeline` (L3, active); `process_date()`/`calculate_vod()`/`preview_processing()` (L1, **deprecated**) |
| `fluent.py` | `FluentWorkflow` (L2, **deprecated** — deferred execution chain) |
| `functional.py` | L4 functional API: `read_rinex()`, `augment_with_ephemeris()`, etc. |
| `workflow.py` | `VODWorkflow` (**deprecated** — `_augment_data` is a no-op stub, never applies ephemeris augmentation) |
| `vod_computer.py` | `VodComputer` — `compute_day()` (inline) + `compute_bulk()` (from store) |
| `factories.py` | `ReaderFactory`, `GridFactory`, `VODFactory`, `AugmentationFactory` |
| `workflows/` | Task definitions, `validate_data_dirs()` pre-flight check |
| `orchestrator/resources.py` | `MemoryMonitor`, `DaskClusterManager` |

## API levels

Two supported surfaces, plus the CLI on top of one of them. The rest are
deprecated (`DeprecationWarning` on use) — kept working, no longer taught.

| Level | Style | Entry point | Use case | Status |
|---|---|---|---|---|
| CLI | Command-line | `uv run python -m canvodpy.cli.run --site ... --start ... --end ...` | Running the pipeline — recommended | Active |
| L3 | Site pipeline (OOP) | `Site(site).pipeline()` (`api.py`) | Python-native configured pipeline runs — what the CLI wraps; internally builds `PipelineOrchestrator`/`RinexDataProcessor` | Active |
| L4 | Functional | `read_rinex()`, `augment_with_ephemeris()`, etc. (`functional.py`) | Component-level scripting/analysis; also used by Airflow (stateless) | Active |
| L1 | Convenience | `process_date()`, `calculate_vod()`, `preview_processing()` (`api.py`) | Superseded by `Site(site).pipeline()` | Deprecated |
| L2 | Fluent | `FluentWorkflow(...).read().augment().grid().vod()` (`fluent.py`) | Superseded by `Site.pipeline()` / functional | Deprecated |
| — | `VODWorkflow` (`workflow.py`) | `VODWorkflow(site=...)` | Broken augmentation step (`_augment_data` is a no-op) — do not use | Deprecated |

Note: `Site("rosa").process_date(...)` does **not** exist directly on `Site` —
use `Site("rosa").pipeline().process_date(...)`.

## Processing flow

```
Files → DataDirectoryValidator → GNSSDataReader → AuxDataAugmenter → GridAssignment → VODCalculator → MyIcechunkStore
```

## Important patterns

- **The two CLIs are not actually merged** despite the todo tracker claiming this
  resolved: the installed `canvodpy` console script (`project.scripts` in
  `packages/canvod-utils/pyproject.toml`) is the **config tool only**
  (`canvod.utils.config.cli:main`, no subparsers). The pipeline runner
  (`cli/run.py`) has no registered entry point — invoke it as
  `uv run python -m canvodpy.cli.run --site ... --start ... --end ...`. Registering
  it as a `canvodpy run` subcommand is open follow-up work.
- `PipelineOrchestrator`/`RinexDataProcessor` (the CLI/`Site.pipeline()` path) discover
  files via `canvod-filemap`'s `BUILTIN_PATTERNS` when installed, falling back to
  canonical canVOD-only globs (`*.rnx`/`*.sbf`) otherwise — see §12 in `dev/todo_later.md`
- `FluentWorkflow.read()` (**deprecated**) uses `FilenameMapper` when naming config is available
- Receiver position from RINEX header via `ECEFPosition.from_ds_metadata(ds)`
- Factory API: `fpath=` (not `path=`), `.to_ds()` (not `.read()`)
- `vod_analyses` returns `dict[str, VodAnalysisConfig]` (Pydantic models, attribute access)
- `VodComputer` accessible via `site.vod`

## Store integration

`_append_to_icechunk()` in processor.py:
1. Three-layer dedup check
2. `append_to_group()` write
3. Commit
4. SBF metadata concat + write (STEP 5a)
5. Rich metadata write/update (STEP 5b)

## Testing

```bash
uv run pytest canvodpy/tests/
```
