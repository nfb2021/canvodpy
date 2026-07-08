# CLI Home + Ephemeris/VOD-Calculator Flags — Plan

Written 2026-07-08. Two coupled changes: (A) relocate the `canvodpy` console-script
entry point so "the CLI" has one obvious home, (B)+(C) add the two flags tracked as
todo #6. Order matters — A first, so B/C land in the right package.

## Part A — Move the whole CLI into `canvodpy` (revised: full move, not just the entry point) — DONE (2026-07-08)

**Problem.** The installed `canvodpy` console script is registered in
`packages/canvod-utils/pyproject.toml` → `canvod.utils.config.cli:main`
(815-line file). That module owns `config`/`stats` directly, but reaches the `run`
subcommand only via a `try/except ImportError` lazy import of `canvodpy.cli.run`
(`cli.py:785-805`), because `canvod-utils` is a lower-level package and cannot
statically depend on `canvodpy` (dependency only flows `canvodpy → canvod-utils`).

**Design question raised in review:** the first draft of this plan only moved the
entry point + `run` registration into `canvodpy`, leaving `config`/`stats` *logic*
in `canvod-utils`. That still splits "the CLI" across two packages by subject
matter. Since `canvodpy` is already the one package that hosts every other
user-facing surface (`Site`, `Pipeline`, the functional API), the CLI — as another
user-facing surface — belongs there too, composing calls into library packages
(`canvod-utils`, `canvod-ops`, `canvod-readers`) rather than living inside one of
them. `canvod-utils`'s own `CLAUDE.md` already describes it as "Configuration, date
parsing, diagnostics, and shared utilities" — no CLI mentioned; hosting the console
script there was incidental, not a deliberate design.

**Verified before deciding:**
- No test anywhere references `canvod.utils.config.cli` by import path — nothing
  pinned to the current location.
- `typer`/`rich` are used **only** in `cli.py` within all of `canvod-utils` — safe
  to drop as deps once the file moves.
- `canvodpy/pyproject.toml` doesn't declare `typer`/`rich` as direct deps today even
  though `canvodpy/src/canvodpy/cli/dashboard.py` already imports `rich` — an
  existing transitive-dependency smell this move also fixes.
- Two `try/except ImportError` guards in `cli.py` exist only because `canvod-utils`
  doesn't hard-depend on `canvod-readers`/`canvod-ops`: `validate()` guards
  `from canvod.readers.gnss_specs.constants import FORMAT_GLOB_PATTERNS,
  RINEX_OBS_GLOB_PATTERNS`; `stats_show()` guards
  `from canvod.ops.statistics.store import StatisticsStore`. `canvodpy` already
  hard-depends on both packages, so both guards become dead weight once moved —
  delete them, plain top-level imports.

**Decision: full move.** `canvod-utils` goes back to being a pure library (no CLI,
no `typer`/`rich` deps, no `[project.scripts]`). All CLI code — `config`, `stats`,
`run` — lives under `canvodpy/src/canvodpy/cli/`.

1. New `canvodpy/src/canvodpy/cli/config.py` — move `config_app` and its commands
   (`init`, `validate`, `show`, `edit`, `_show_processing`, `_show_sites`,
   `_show_sids`, `CONFIG_DIR_OPTION`, `DEFAULT_CONFIG_DIR`/`MONOREPO_ROOT` setup)
   out of `cli.py` verbatim, fixing imports:
   `from .loader import find_monorepo_root` → `from canvod.utils.config.loader
   import find_monorepo_root`; `from .models import ProcessingConfig, SidsConfig,
   SitesConfig` → `from canvod.utils.config.models import ...`. Remove the
   `canvod.readers` `try/except ImportError` guard in `validate()` — plain import.
2. New `canvodpy/src/canvodpy/cli/stats.py` — move `stats_app` and its commands
   (`stats_compute`, `stats_show`, `stats_reset`) out of `cli.py`, same import-path
   fixes. Remove the `canvod.ops` `try/except ImportError` guard in `stats_show()`
   — plain import.
3. New `canvodpy/src/canvodpy/cli/app.py` — the root Typer app and entry point:
   ```python
   import typer
   from canvodpy.cli.config import config_app
   from canvodpy.cli.stats import stats_app
   from canvodpy.cli.run import main as _run_main

   main_app = typer.Typer(name="canvodpy", help="canvodpy CLI tools", no_args_is_help=True)
   main_app.add_typer(config_app, name="config")
   main_app.add_typer(stats_app, name="stats")

   @main_app.command(
       "run",
       help="Process GNSS observations into Icechunk stores and compute VOD.",
       context_settings={
           "allow_extra_args": True,
           "ignore_unknown_options": True,
           "help_option_names": [],
       },
       add_help_option=False,
   )
   def run_cmd(ctx: typer.Context) -> None:
       raise typer.Exit(code=_run_main(ctx.args))

   def main() -> None:
       main_app()

   if __name__ == "__main__":
       main()
   ```
4. Delete `packages/canvod-utils/src/canvod/utils/config/cli.py` entirely.
5. `packages/canvod-utils/pyproject.toml`: remove `[project.scripts]`; remove
   `typer>=0.9` and `rich>=13.0` from `dependencies`.
6. `canvodpy/pyproject.toml`: add `typer>=0.9`, `rich>=13.0` to `dependencies`; add
   ```toml
   [project.scripts]
   canvodpy = "canvodpy.cli.app:main"
   ```
7. `uv lock && uv sync` — re-resolves deps and re-links the console script (which
   package owns `[project.scripts]` determines what `.venv/bin/canvodpy` points at).
8. Verify: `uv run canvodpy --help` shows `config`/`stats`/`run`;
   `uv run canvodpy config validate`/`show` work unchanged;
   `uv run canvodpy stats --help` works unchanged;
   `uv run canvodpy run --help` shows the real argparse flags;
   `uv run canvodpy run --site NonexistentSiteXYZ --dry-run` still forwards args;
   `uv run pytest -m "not integration" -q --no-cov` matches baseline
   (18 failed / 1388 passed / 257 skipped / 7 deselected).
9. Docs/refs to update after the move (found via repo-wide grep for
   `canvod.utils.config.cli`): `canvodpy/CLAUDE.md` (the "two CLIs not merged" note
   in "Important patterns" — already stale from the earlier `canvodpy run` work,
   needs a full rewrite reflecting this move), `dev/todo_later.md` (lines ~157, 262,
   503, 519 reference the old `cli.py` path).

Net effect: **all** CLI code — entry point, `config`, `stats`, `run`, and future
subcommands — lives under `canvodpy/src/canvodpy/cli/`. `canvod-utils` is a pure
library again, consistent with its own docs.

## Part B — `--ephemeris-source {final,broadcast}` flag — DONE (2026-07-08)

Implemented as planned: flag added, config mutated after `load_config()`.
Bonus: the deprecated `.processing.processing.` alias access (not just the
one at `processor.py:607` scoped by this plan) turned out to appear at 11
more call sites in the same file — all fixed in one mechanical pass
(`.processing.processing.` → `.processing.params.`), removing the
`DeprecationWarning` spam entirely rather than leaving 10 of 12 dangling.
Verified: `uv run ty check`/`ruff check` clean, `uv run pytest -m "not
integration"` matches baseline, `canvodpy run --help` shows the flag,
`--ephemeris-source bogus` correctly rejected by argparse `choices=`.


**Already config-driven, not hardcoded.** `ProcessingParams.ephemeris_source:
Literal["final", "broadcast"]` already exists
(`packages/canvod-utils/src/canvod/utils/config/models.py:315`). Selection happens in
`RinexDataProcessor.__init__` (`canvodpy/src/canvodpy/orchestrator/processor.py:602-608`):
explicit `use_sbf_geometry` constructor param wins, else falls back to
`config.processing.processing.ephemeris_source == "broadcast"`.

**Two findings that shape the approach:**

- `use_sbf_geometry` is a real, working param on `RinexDataProcessor`, but **nothing
  above it forwards it** — `Site.pipeline()` (`api.py:130-196`), `Pipeline.__init__`
  (`api.py:261-273`), and `PipelineOrchestrator.__init__` (`pipeline.py:69-79`) all
  have fixed, explicit param lists with no ephemeris-related kwarg and no `**kwargs`
  passthrough. `PipelineOrchestrator` constructs `RinexDataProcessor` at two call
  sites (`pipeline.py:417-421`, `pipeline.py:529-533`), neither passing
  `use_sbf_geometry` — wiring a flag through the object chain would mean touching 3
  layers' signatures plus 2 call sites.
- **Simpler route: mutate the loaded config in place.** `load_config()`
  (`packages/canvod-utils/src/canvod/utils/config/loader.py:241`) is
  `@functools.lru_cache(maxsize=8)`. `run.py:289` calls
  `load_config(config_file=config_file)`; `RinexDataProcessor.__init__` calls the
  bare `load_config()` (`processor.py:598`). When no `--config` overlay is given
  (the common case), both calls hit the same cache key `(None, None)` and return the
  *same object* — this is already how the existing `--config`/`CANVOD_CONFIG_FILE`
  overlay mechanism works (env var set once, first `load_config()` call bakes it in,
  every later same-key call returns the cached, already-overlaid instance). Since
  `_StrictModel` is `frozen=False` project-wide, mutating a field on that shared
  cached object after load is safe and consistent with the existing overlay pattern.

**Drive-by bug found while tracing this:** `processor.py:607` reads
`config.processing.processing.ephemeris_source` — `.processing` on `ProcessingConfig`
is a **deprecated property alias** for `.params`
(`models.py:795-805`, emits `DeprecationWarning` on every access, i.e. on every
`RinexDataProcessor.__init__`). Fix in the same pass: change to
`config.processing.params.ephemeris_source`.

**Implementation in `canvodpy/src/canvodpy/cli/run.py`:**

1. `_build_parser()`: add
   ```python
   p.add_argument(
       "--ephemeris-source",
       choices=["final", "broadcast"],
       default=None,
       help="Override the configured ephemeris source (final=agency SP3/CLK, "
            "broadcast=SBF SatVisibility). Default: from canvod-settings.yaml.",
   )
   ```
2. In `main()`, right after `config = load_config(config_file=config_file)`
   (line 289): if `args.ephemeris_source is not None`, set
   `config.processing.params.ephemeris_source = args.ephemeris_source`.
3. `processor.py:607`: fix `.processing.processing.` → `.processing.params.`.

## Part C — `--vod-calculator` flag — DONE (2026-07-08)

Implemented as planned: `_compute_vod_for_day` now takes `calculator_name`,
manually re-adds the `xr.align(canopy_ds, ref_ds, join="inner")` step
`VODFactory.create()` doesn't do (unlike `TauOmegaZerothOrder.from_datasets()`,
which did it internally), then `VODFactory.create(name, canopy_ds=...,
sky_ds=...).calculate_vod()`. `--vod-calculator` choices are populated
dynamically from `VODFactory.list_available()` at parser-build time — just
`tau_omega` today, extends automatically if a second calculator is ever
registered. Verified: `uv run ty check`/`ruff check` clean, `uv run pytest`
matches baseline, `canvodpy run --help` shows `{tau_omega}` as the only
choice.


**Only one concrete calculator exists today**: `TauOmegaZerothOrder`
(`packages/canvod-vod/src/canvod/vod/calculator.py:148`), registered as `"tau_omega"`
in `VODFactory` (`canvodpy/src/canvodpy/__init__.py:303`,
`canvodpy/src/canvodpy/factories.py:362-388`). No config field for calculator choice
exists yet (unlike `ephemeris_source`).

**The real gap**: `cli/run.py`'s `_compute_vod_for_day` (~line 175-268) bypasses
`VODFactory` entirely — hardcodes `from canvod.vod.calculator import
TauOmegaZerothOrder` (line 199) and calls
`TauOmegaZerothOrder.from_datasets(canopy_ds=..., sky_ds=..., align=True)` directly
(line 232). Every other call site in the codebase (`vod_computer.py:236-242`,
`functional.py:310`, `workflow.py:319`, `fluent.py:457`) goes through
`VODFactory.create(name, canopy_ds=..., sky_ds=...)` then `.calculate_vod()`. `run.py`
is the outlier.

**Wrinkle**: `VODCalculator.from_datasets()` (`calculator.py:118-145`) does an
internal `xr.align(canopy_ds, sky_ds, join="inner")` before constructing + calling
`calculate_vod()`. `VODFactory.create()` constructs directly from raw kwargs with no
align step. Switching `_compute_vod_for_day` to the factory means re-adding that align
call manually so behavior doesn't silently change.

**Implementation:**

1. `_build_parser()`: add
   ```python
   from canvodpy.factories import VODFactory
   p.add_argument(
       "--vod-calculator",
       choices=VODFactory.list_available(),
       default="tau_omega",
       help="VOD calculator to use.",
   )
   ```
   (Safe to call `VODFactory.list_available()` at parse-build time — importing
   `canvodpy.cli.run` already runs `canvodpy/__init__.py` first, which registers
   `"tau_omega"`.)
2. Rewrite `_compute_vod_for_day` to accept a `calculator_name: str` param; replace
   the hardcoded import + `TauOmegaZerothOrder.from_datasets(...)` call with:
   ```python
   canopy_ds, ref_ds = xr.align(canopy_ds, ref_ds, join="inner")
   calculator = VODFactory.create(calculator_name, canopy_ds=canopy_ds, sky_ds=ref_ds)
   vod_ds = calculator.calculate_vod()
   ```
3. Thread `args.vod_calculator` from `main()` into the `_compute_vod_for_day(...)`
   call.

**Not doing**: adding a `vod_calculator` config-file field. With only one real choice,
a CLI-only flag (defaulting to the sole registered option) avoids inventing config
surface for a choice that doesn't exist yet. Revisit if/when a second calculator is
registered.

## Testing / verification

- `uv run canvodpy --help` / `uv run canvodpy run --help` — new flags visible, old
  ones unchanged.
- `uv run canvodpy run --site <site> --dry-run --ephemeris-source broadcast` and
  `--ephemeris-source final` — both parse and reach pipeline construction.
- `uv run canvodpy run --site <site> --dry-run --vod-calculator tau_omega` and an
  invalid choice (should reject via argparse `choices=`).
- `uv run ty check canvodpy/src/canvodpy/cli/ canvodpy/src/canvodpy/orchestrator/processor.py packages/canvod-utils/src/canvod/utils/config/cli.py` clean.
- `uv run pytest -m "not integration" -q --no-cov` — must still match baseline
  (18 failed / 1388 passed / 257 skipped / 7 deselected).
- Confirm no more `DeprecationWarning: ProcessingConfig.processing is deprecated`
  spam in logs after the processor.py fix.

## Docs to update after implementation

- `canvodpy/CLAUDE.md` — "Important patterns" bullet about the two CLIs not being
  merged (already stale after the earlier `canvodpy run` subcommand work; needs a
  further update once the entry point itself moves packages).
- `docs/guides/api-levels.md`, root `CLAUDE.md` — CLI flags table, if one exists;
  otherwise no change needed since flags are argparse `--help`-documented.
- `dev/todo_later.md` — mark #6 (in the numbered CLI/config todo list, if tracked
  there) as done, matching the pattern used for the other closed items in this file.
