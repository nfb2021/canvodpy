# Deferred Work — canvodpy Performance & Refactoring

**Date:** 2026-07-02. Sourced from Fable Phase 0 (`ragged_sid_feasibility.md`) and
Phase 1 (`perf_plan_phase1.md`) investigations. All file:line references verified
against the `explore/performance-review` worktree. Implementation deferred — plan only.

---

## 1. ~~SID universe: make `mode: all` authoritative~~ — RESOLVED (Task A)

**Resolution (2026-07-04):** Three modes kept: `all` (no filtering), `preset` (named
YAML file), `custom` (explicit list). Implemented `_get_preset_sids()` loading from
`presets/` via `Path(__file__).parent`. Bundled `presets/default.yaml` — 277-SID
curated multi-GNSS list (GPS + Galileo + BeiDou MEO + GLONASS; no GEO, no IGSO, no
augmentation, no GPS L2W). Package default flipped from `mode: all` (3658 SIDs) to
`mode: preset, preset: default`. Release maintenance process documented in
`docs/guides/configuration.md`. No cross-package import needed.

**Commits:** `ac5283e8` (implementation), `98a890c1` (docs)

---

## 2. ~~Ragged-in-pipeline: move padding to write boundary~~ — RESOLVED (Task B)

**Resolution (2026-07-04):** Memory win achieved via Task A (277-SID preset default:
273 MB vs 1662 MB baseline). Lazy padding (pad to ~100 observed SIDs at write boundary)
benchmarked at 9% *slower* on macOS (Run 3) — the reindex in the driver accumulates
faster than the sequential Icechunk write can drain. Linux fork/COW would make the math
different, but that's not actionable here and the main win is already captured.
Benchmark wiring committed (`b3dad777`). Production flip deferred — not worth the
complexity without a measured Linux benefit.

**Commit:** `b3dad777` (benchmark implementation)

---

## 3. ~~`canvod-virtualiconvname` — needs drastic redesign (Task C)~~ — MOOT, package deleted (confirmed 2026-07-14)

**Confirmed 2026-07-14:** the package no longer exists anywhere in the repo
(`find . -iname "*virtualiconvname*"` returns nothing) — removed in commit
`0b2e7027` ("remove canvod-virtualiconvname, port tests to canvod-preflight"),
2026-07-09. Everything below is now historical context for how that
descoping decision was reached, not an open redesign task.

**Status (2026-07-08) — scope changed, not just superseded:** the decision was not
to redesign the mapping mechanism, but to **not need one** for the default path.
canvodpy now prescribes a single canonical filename convention and `canvod-preflight`
enforces it as a hard, mandatory gate before ingestion; users with non-conforming
receiver output rename files on disk (`gfzrnx`, one-time per site). The **only**
remaining escape hatch for people who can't or won't rename is the optional
`canvod-filemap` package — deliberately kept as an admitted hack, not a polished
feature. Consequence: this section's original redesign goals ("one mechanism, not
three", wizard-in-10-minutes) are **descoped for `canvod-filemap`** — it doesn't need
to be intuitive, that's the whole reason it's optional and quarantined outside the
main monorepo. They still matter for the *canonical-name path*, but that path is
already simple (prescribe + enforce), so there's little left to redesign there either.

**What's still legitimately open** is `canvod-preflight` polish (the mandatory path,
where quality does matter): §12 Phase 1 item 4 (plain-language
`_format_validation_error()`) and Phase 3 items 11-13 (RINEX header peek, gap
detection, full CLI report). §12 Phase 2 (hardening `canvod-filemap` itself: items
6, 8, 9, 10) is now **de-prioritized** per this scope decision, not forgotten — it's
acceptable for the optional hack to stay rough.

**User note (original, 2026-07-02):** The current mapping is way too complicated and not intuitive for humans. This needs to change drastically.

**What it is:** filename-convention layer that maps arbitrary receiver filenames to the
canonical `{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}`
name. ~1,765 LOC, 9 test modules.

### Problems identified

**Too many overlapping mechanisms — not intuitive:**
- Three distinct ways to define a mapping: builtin `SourcePattern` regexes, `NamingRecipe`
  (width-based YAML field extraction, 367 LOC), and per-receiver naming config defaults.
  Two extension points for the same problem. Users face a non-obvious choice with no
  clear guidance on which to use.
- `NamingRecipe` (used in exactly one place: `tasks.py:355-365`) duplicates what a
  custom `SourcePattern` could express — redundant abstraction, adds cognitive load.
- The interaction between patterns, recipes, and naming config defaults is not documented
  in a way a new user can reason about without reading source.

**Dead code pulling in a dependency:**
- `FilenameCatalog` (DuckDB-backed cache, `catalog.py:79-301`) has **zero consumers**
  outside its own tests. Pulls in the `duckdb` dep. Duplicates the store metadata
  table's `canonical_name`/`physical_path` fields. Remove or quarantine explicitly.

**Silent data loss:**
- `discover_all`/`discover_for_date` swallow `ValueError/KeyError` per file with `continue`
  and **no logging** (`mapping.py:145, 178`). The L2 fluent path uses `FilenameMapper`
  directly (bypassing the validator) and can silently omit data files. Unacceptable.

**Correctness edge cases:**
- Cross-midnight overlaps missed: `detect_overlaps` groups by `(year, doy)` — a 23:45
  15M file vs the next day's 01D file cannot be flagged (`mapping.py:308-333`).
- Period inference heuristics: `hour_letter == "0"` → `period = "01D"` (`mapping.py:257`)
  can silently mis-tag hourly files named with `0`.
- `NamingRecipe.matches` requires exact filename length (`recipe.py:331-339`); has no
  compression-extension handling (`.gz`). `_detect_file_type` in mapping handles it;
  recipe doesn't. Inconsistent.

**Coupling:**
- Naming config stored as opaque dicts in canvod-utils — validation only surfaces at
  pipeline runtime, not at `just config-validate`. Errors are late and hard to diagnose.
- `canvod-readers` depends on the package only for the deprecated
  `DataDirMatcher`/`PairDataDirMatcher` path — once removed, that dependency edge drops.

**Direction for redesign:**
- One mechanism, not three. Single, well-documented pattern definition format that
  covers both the "I have a regex" and "I have fixed-width fields" cases.
- Discovery must produce a report (like the validator) — never silently drop files.
- Config validation at load time, not at first use.
- Remove `FilenameCatalog` and its `duckdb` dependency.
- Naming should be approachable: a new user should be able to add a custom receiver
  naming pattern in under 10 minutes without reading source code.

---

## 4. ~~CLI and configuration — package-standalone usage and human ergonomics (Task D)~~ — RESOLVED (2026-07-14)

**User notes:**
1. Using individual `canvod-*` packages standalone currently errors about config not
   being set up. Packages must be usable without a full `canvodpy` config stack.
2. The config itself needs to be more human-friendly.

### Problems identified

**Packages are not standalone:**
- `load_config()` (`canvod-utils/config/loader.py:233`) walks up to a `.git` directory
  to find the monorepo root. In a pip-installed package (`import canvod.store`), there is
  no `.git` → config load fails immediately. `CANVOD_CONFIG_DIR` is the only escape and
  is not documented in any package README.
- Library code calls `load_config()` mid-computation (e.g. `manager.py:calculate_vod`)
  instead of receiving config as a parameter. Any call to these methods outside a full
  canvodpy install stack fails.
- `load_config()` calls `sys.exit(1)` on validation error (`loader.py:116-118`) — kills
  the interpreter in programmatic (L2/L4/standalone) use. Should raise instead.
- **Goal:** each `canvod-*` package should import and operate with zero config setup.
  Config is an orchestrator-layer concern; individual packages should accept their
  required settings as constructor/method arguments and have sensible library defaults.

**Config is not human-friendly:**
- 24 model classes in one 990-line `models.py` — hard to navigate, hard to understand
  what belongs where.
- `ProcessingParams` mixes reproducibility-relevant science settings (`file_pairing`,
  `store_radial_distance`) with machine-local resource knobs (`n_max_threads`,
  `parallelization_strategy`, `threads_per_worker`). A config file should be portable
  between machines without carrying worker counts.
- Two CLIs both named `canvodpy`: the installed `canvodpy` script is the config tool;
  the pipeline runner (`canvodpy/src/canvodpy/cli/run.py`) is not registered → `canvodpy --site X`
  fails for every new user. Confusing at first launch.
- Override precedence is ad hoc: `--workers` ~~/ `--batch-hours`~~ bypass the config model ~~(`--batch-hours` removed, 96e58c73)~~; no general CLI > env > user-yaml > defaults story; no `--set key=value` passthrough for other fields.
- Config errors from naming sections (C10) only surface at pipeline start — too late.

**Directions:**
- ~~Make `canvod-*` packages usable without a config file.~~ **RESOLVED (c7bcad13):** `GnssResearchSite.calculate_vod()` accepts `processing_params=None`; `extra="forbid"` on all 24 models catches bad YAML at load time; `ConfigValidationError` replaces `sys.exit`.
- ~~`sys.exit` → raise throughout `loader.py`.~~ **RESOLVED (c7bcad13)**
- ~~Split `models.py` into focused files~~ **RESOLVED (2026-07-12):** converted
  `models.py` (1244 lines, 24 model classes) into a `models/` subpackage —
  `base.py`, `metadata.py`, `aux_data.py`, `processing_params.py`,
  `compression.py`, `storage.py`, `logging.py`, `preprocessing.py`,
  `references.py`, `processing.py`, `sites.py`, `sids.py`, `root.py`
  (`CanvodConfig`), with `__init__.py` re-exporting everything so `from
  canvod.config.models import X` is 100% unaffected — verified against all
  10 known repo-wide consumers. Two relative-path gotchas fixed in the move:
  `LoggingConfig.get_log_dir()`'s `from .loader import ...` → `from
  ..loader import ...` (now one level deeper), and
  `SidsConfig._get_preset_sids()`'s `Path(__file__).parent / "presets"` →
  `.parent.parent / "presets"` (presets/ is a sibling of `models.py`, not of
  the new `models/` dir) — both verified working (277-SID preset loads,
  log dir resolves). Full regression: 1445 passed / 85 failed / 49 errors,
  identical to the pre-split baseline.
- ~~Separate science config from machine config / Introduce `ParallelismConfig`.~~ **RESOLVED differently (366c7eab + 4f855dde):** Dask gone, loky Wave A/B in place; credentials moved to `.env` (4f855dde); `days_per_batch` replaces `batch_hours`; `aggregate_glonass_fdma` dead wire removed; `scs_from → paired_canopies`; `ProcessingConfig.processing → .params`.
- ~~**Merge the two CLIs**~~ **RESOLVED (2026-07-08).** `find_monorepo_root()` was
  deduplicated in c7bcad13, but the user-facing entry point wasn't unified until
  now. Two steps: first registered `run.py`'s `main()` as a `canvodpy run`
  subcommand via a lazy import in `canvod-utils`' `cli.py` (avoided a circular
  dependency, since `canvodpy` depends on `canvod-utils`, not the reverse); then,
  on review, moved the *entire* CLI — `config`, `stats`, `run` — into
  `canvodpy/src/canvodpy/cli/` (`config.py`, `stats.py`, `app.py`), since
  `canvodpy` is already the one package that hosts every other user-facing
  surface (`Site`, `Pipeline`, functional API). `canvod-utils` is a pure config/
  utility library again — no CLI code, no `typer`/`rich` deps. Installed console
  script: `canvodpy/pyproject.toml` → `canvodpy.cli.app:main`. Full rationale in
  `dev/cli_home_and_flags_plan.md`.
- ~~Validate naming-section config at `SitesConfig` load time~~ **PARTIALLY
  RESOLVED (2026-07-12):** deep structural validation of the `naming:` dict
  still correctly stays out of `canvod-config` — that package has zero
  inter-package dependencies by design (see the models.py-split entry above),
  and `canvod-preflight` (which owns `SiteNamingConfig`/`ReceiverNamingConfig`)
  doesn't depend on `canvod-config`, so importing preflight's models here
  would create a fresh circular-dependency risk, the same class of problem
  already flagged in §22. What canvod-config *can* validate without a new
  dependency, added now: a `ReceiverConfig` cross-field check rejecting
  `recipe` and `naming` both being set — `recipe`'s own description already
  said it "replaces the naming block for file discovery," but nothing
  enforced that, so both could be set with no indication of which one
  actually took effect. Deep structural validation of `naming`'s contents
  itself is still deferred to `canvod-preflight`/`canvod-filemap`, by design.
- ~~Surface `CANVOD_CONFIG_DIR` in `--help` and all package READMEs.~~ **RESOLVED (96e58c73 + prior):** `CANVOD_CONFIG_FILE` + `CANVOD_CONFIG_DIR` both handled in `load_config()`; `@lru_cache(maxsize=8)`, `logger.warning()` (no print()), `ConfigValidationError` (no sys.exit) all in place.
  ~~**Still open:** mention both env vars in each `canvod-*` package README.~~
  **RESOLVED (2026-07-12):** added a "Configuration (optional)" section to
  the 6 package READMEs that actually call `load_config()`/`find_monorepo_root()`
  (verified by grep, not guessed) — `canvod-config` itself, `canvod-readers`,
  `canvod-auxiliary`, `canvod-ops`, `canvod-store`, `canvod-store-metadata`.
  The other 6 packages (`canvod-audit`, `canvod-grids`, `canvod-preflight`,
  `canvod-utils`, `canvod-viz`, `canvod-vod`) don't touch config at all, so
  left untouched. Side finding: `canvod-config/README.md` itself was quite
  stale beyond this (documented the old 3-file `processing.yaml`/
  `sites.yaml`/`sids.yaml` format and pre-unified-config `just config-edit
  processing` commands). **RESOLVED (2026-07-14):** rewritten against the
  actual unified `canvod-settings.yaml` + `canvodpy config
  init/edit/show/validate` CLI, verified against `Justfile`,
  `cli/config.py`, and the real template
  (`packages/canvod-config/src/canvod/config/templates/canvod-settings.yaml.example`).
- ~~`defaults/sites.yaml` never read by `_load_sites()`.~~ **RESOLVED (moot):** With the unified `canvod-settings.yaml`, sites are always user-defined — `defaults/sites.yaml` contains `sites: {}` and there is nothing to merge. Dead file; delete or leave as a stub.

**Open questions:**
- ~~Primary operational interface: L3 `Site` API with `run.py` as sugar, or runner as
  first-class interface for n8n/Airflow?~~ **RESOLVED (2026-07-08):** CLI (wrapping
  `Site.pipeline()`) is the primary interface for running the pipeline. Airflow/n8n
  keep calling `canvodpy.functional` (stateless) directly — unchanged. Going forward
  there are two supported Python surfaces: `Site.pipeline()` (configured pipeline
  runs — what the CLI wraps) and `canvodpy.functional` (component-level
  scripting/analysis). Deprecated with `DeprecationWarning` (via a shared
  `canvodpy._deprecation.deprecated` decorator): `FluentWorkflow`, the flat
  `process_date()` / `calculate_vod()` / `preview_processing()` convenience
  functions, and `VODWorkflow` — the latter found to have a **broken augmentation
  step** (`workflow.py::_augment_data` is a no-op TODO stub; VOD computed through it
  never gets ephemeris-augmented angles). None of these are removed, just no longer
  taught. ~~**Still open:** update `CLAUDE.md`/docs API-levels tables, scrub demos,
  strengthen the breadcrumb trail/skill toward CLI-first guidance, and add CLI flags
  for ephemeris-source/VOD-calculator choice (currently `Pipeline` hardcodes
  `TauOmegaZerothOrder` and only reads ephemeris source from YAML, not as a
  parameter — the CLI inherits this limit since it calls `Site.pipeline()`).~~
  **Ephemeris/VOD-calculator flags DONE (2026-07-08)** — `canvodpy run
  --ephemeris-source {final,broadcast}` and `--vod-calculator` added; see
  `dev/cli_home_and_flags_plan.md` Parts B/C. Docs/demo scrubbing still open
  (tracked separately in §17, the `canvodpy-demo` submodule work).
  ~~**Docs API-levels/CLAUDE.md tables specifically:** still stale as of
  2026-07-08~~ **RESOLVED (2026-07-12, `d99405da`):** fixed the stale
  `uv run python -m canvodpy.cli.run ...` invocation (6 files) and
  `docs/guides/api-levels.md`'s false claims that `run` "isn't registered
  yet" and that `--ephemeris-source`/`--vod-calculator` "aren't CLI flags" —
  both were true when written, both wrong by the time this was checked.
  `CLAUDE.md`'s own package/API-levels tables had the same staleness, fixed
  in the same pass.
- ~~Should `CanvodConfig` snapshots be persisted into store metadata per run
  (the store-metadata package already has a `config` section) for drift
  auditability? — still open, unanswered.~~ **RESOLVED (2026-07-12) —
  user decision: yes, implement it.** Turned out the schema/collector
  (`ConfigSnapshot`, `collect_config_snapshot()`) already existed and was
  already wired into `collect_metadata()` — the actual gap was that
  `processor.py`'s STEP 5b only wrote the snapshot **once**, on first
  ingest; every subsequent ingest only bumped `temporal.updated`, so the
  stored config silently froze at whatever was true on day one, forever.
  Fixed: the STEP 5b "else" branch (existing-metadata case) now re-runs
  `collect_config_snapshot()` every ingest, compares its `config_hash`
  against the stored one, and if different, updates the `config` section
  and appends a `"Config changed (<old> -> <new>)"` history entry.
  Found and fixed two adjacent bugs while wiring this in: (1)
  `collect_config_snapshot()` collected the compression section under key
  `"netcdf_compression"` but read it back as `sections.get("compression")`
  — always `None`, silently; (2) `update_metadata()`'s dotted-key updates
  **replace** list fields wholesale rather than appending, so every repeat
  ingest was already quietly wiping `summaries.history` down to one entry
  — fixed at the call site (read-merge-write in `processor.py`) rather than
  changing `update_metadata()`'s generic semantics, since other callers may
  rely on replace-not-append. `collect_config_snapshot` and `read_metadata`
  now both exported from `canvod.store_metadata`'s top level. Tests:
  `test_config_drift.py` (3, mirrors the exact processor.py logic since a
  full orchestrator-level test would need a real pipeline run).

**Action:** effectively DONE (confirmed 2026-07-14) — every sub-item above is
resolved; the only remaining loose end (`canvod-config/README.md` staleness)
was fixed in the same pass. No open code/doc work left under Task D.

---

## 5. ~~Pipeline parallelism (Phase 2+, lower priority)~~ — RESOLVED

**RESOLVED (366c7eab):** Dask removed. Wave A/B parallel receiver processing via `ThreadPoolExecutor × ProcessPoolExecutor` (loky backend). 1.7× speedup confirmed (847s → 501s, 28 days). `_process_sub_day_batches` deleted (4f855dde). `batch_hours` → `days_per_batch` (4f855dde). `resource_mode` / `n_max_threads` / `auto_uncapped` / `nice` remain as the resource knobs (simpler than a full `ParallelismConfig` model — no need to introduce one).

---

## 6. ~~Streaming write path~~ — CLOSED

**Why closed:** The Layer 3 dedup inversion concern (daily + sub-daily mix) does not
apply — users always provide 24h files, so mixed-granularity batches never occur.
Streaming `as_completed()` instead of list-accumulation would be a micro-latency win
on local FS only; not worth the complexity.

**Note for object storage:** If the store moves to S3/GCS/Azure, Icechunk v2 OCC makes
concurrent writes viable. The right shape then is a `WriteStrategy` Protocol:

- `SequentialSessionStrategy` — local FS, one session, sequential commits (current)
- `ConcurrentSessionStrategy` — object storage, one session per worker, concurrent
  chunk puts, OCC rebase on commit conflict

No implementation needed until object storage is a confirmed target.

---

## 7. Quick wins — can ride any PR

- ~~**Silent discovery skips** (`mapping.py:145, 178`)~~ **DONE:** `logger.warning("Could not map %s — skipping", path.name)` at lines 149 and 183.
- ~~**`sys.exit` in `loader.py:116-118`**~~ **DONE (c7bcad13):** raises `ConfigValidationError`.
- ~~**`FilenameCatalog`** (`catalog.py:79-301`): delete. Zero consumers, pulls in `duckdb`.~~
  **DONE (2026-07-08)** in the in-monorepo package, **but regressed**: when the
  package moved to the separate `canvodpy-extensions` repo (§12), the deletion did
  not carry over — `catalog.py`, `tests/test_catalog.py`, and the `duckdb>=1.0`
  dependency are all still present in
  `canvodpy-extensions/packages/canvod-filemap` (verified 2026-07-08).
  ~~**Still open:** re-apply the deletion in the extensions repo.~~
  **RESOLVED (2026-07-12, `canvodpy-extensions@49c0627`, branch
  `chore/remove-dead-filecatalog`, not yet merged/pushed):** deleted
  `catalog.py` + `tests/test_catalog.py`, removed `FilenameCatalog` from
  `__init__.py`'s exports, removed `duckdb>=1.0` from `pyproject.toml`, and
  fixed the 4 docs that documented it (`CLAUDE.md`, `README.md`,
  `docs/packages/filemap/overview.md`, `docs/api/canvod-filemap.md` — the
  last one had a dangling mkdocstrings `::: canvod.filemap.catalog` block
  that would have failed the docs build once the module was gone). 140
  tests pass, `zensical build` clean.
- ~~**`canvod-filemap` hard dependency**: made it a required `canvodpy` dependency
  while installing it for testing, then reverted per user direction — it must stay
  optional so regular installs have zero footprint.~~ **DONE (2026-07-08):**
  `canvod-filemap` is now `[project.optional-dependencies] filemap = [...]` in
  `canvodpy/pyproject.toml`. Fixed two hard top-level/unguarded imports that
  would crash a regular install without the extension: `orchestrator/pipeline.py`
  (`_detect_reader_format`, `_get_rinex_files`) and `workflows/tasks.py`
  (`_get_gnss_globs`, used by the Airflow `check_rinex`/`check_sbf` tasks) — both
  now lazily import with a canonical-name fallback (`*.rnx`/`*.sbf`), matching the
  pattern already used in `orchestrator/processor.py`. **Follow-up bug caught
  2026-07-08 on the remote processing machine:** `[tool.uv.sources]` initially
  pointed `canvod-filemap` at a local sibling path (`../canvodpy-extensions/...`),
  which broke `uv run` entirely on any machine without that sibling repo cloned —
  `uv` resolves optional-group sources even when the extra isn't requested. Fixed
  by switching the source to `{ git =
  "https://github.com/nfb2021/canvodpy-extensions.git", subdirectory =
  "packages/canvod-filemap" }` in the root `pyproject.toml`; the local-path form
  is now documented in `docs/guides/extensions.md` as an uncommitted local
  override only, for contributors iterating on both repos side by side. New docs
  page `docs/guides/extensions.md` covers install (`uv add "canvod-filemap @
  git+...#subdirectory=..."` or the sibling-path form) and is linked from
  `docs/index.md` and `docs/guides/configuration.md`.
- ~~**Silent recipe-without-filemap failure** (found 2026-07-08, real production run
  on the remote processing machine). A site's receivers were configured with
  `recipe: rosalia_canopy` / `recipe: rosalia_reference` in `canvod-settings.yaml`
  — i.e. non-canonical filenames requiring `canvod-filemap` to match them — but
  `canvod-filemap` wasn't installed (plain `uv sync`, no `--extra filemap`). The
  ImportError fallback in `pipeline.py`/`tasks.py` (see bullet above) silently
  degraded to canonical-only globs (`*.rnx`/`*.RNX`), which don't match this
  site's real files. Symptom was a confusing `no_rinex_files_found` warning per
  receiver-day with no indication of the actual cause, discovered only through
  manual diagnosis (checking `config.sites.*.receivers.*.recipe` against whether
  `canvod.filemap` importable). Needed: a clear, fail-fast, actionable error
  instead of a silent degrade whenever a receiver has `recipe:` configured but
  `canvod-filemap` isn't importable.~~ **RESOLVED (2026-07-12):** added at both
  suggested gates. `canvodpy config validate` (`cli/config.py`) checks every
  receiver up front and exits 1 listing every offending `site/receiver` plus
  `Install with: uv sync --extra filemap` before checking directories at all.
  `PipelineOrchestrator.__init__` (`orchestrator/pipeline.py`,
  `_check_recipe_receivers_have_filemap`) raises the same actionable
  `ImportError` at construction — covers every invocation path (`canvodpy run`,
  `Site.pipeline()`) since both go through this one constructor, not just the
  CLI validate subcommand. Tests: `test_pipeline_filemap_guard.py` (3),
  `test_cli_config.py::TestValidateRecipeWithoutFilemap` (2).

- ~~**Dueling Rich `Live` displays cause flashing/reprinting progress bars** (found
  2026-07-08, live production run on the remote processing machine). Two
  separate `Live` regions were active at once during a real pipeline run:
  `RichReporter.__enter__` (`canvodpy/src/canvodpy/cli/dashboard.py:190-199`)
  creates its own `Live` for the "Overall" bar + header panel; independently,
  `_processing_progress()` (`canvodpy/src/canvodpy/orchestrator/pipeline.py:626`)
  created a separate `Progress` for the per-receiver bars
  (`canopy_01`/`reference_01_canopy_01`/etc.), which spins up its own
  independent internal `Live`. Two concurrent `Live` instances fight over
  cursor control on the same terminal, producing exactly the observed symptom.~~
  **DONE (2026-07-08):** rather than merging the two displays into one shared
  `Live`/`Group` (bigger refactor), threaded a `show_progress: bool = True` flag
  through `Site.pipeline()` → `Pipeline.__init__` → `PipelineOrchestrator.__init__`
  (`api.py`, `orchestrator/pipeline.py`), used at the `_processing_progress()`
  call site as `disable=not self._show_progress`. `cli/run.py`'s real-run
  `site.pipeline(...)` call now passes `show_progress=False`, since
  `RichReporter` already owns the one `Live` that should exist and already
  reports per-day/per-dataset progress via its own callbacks
  (`on_day_start`/`on_datasets`/`on_timing`) — the per-receiver bars were
  redundant with that, not additive. Default stays `True` for programmatic/
  notebook use of `Site(...).pipeline()` without a competing `Live`.
  **Superseded (2026-07-08):** the `show_progress: bool` flag from this fix was
  itself replaced by an `on_group_written: Callable[[str], None] | None`
  callback as part of the multi-site + per-(site,receiver) progress redesign —
  see `dev/multi_site_progress_plan.md`. The per-receiver bars weren't
  actually redundant after all: they were the only mechanism giving real-time
  feedback *during* a `days_per_batch`-sized batch (the aggregate bar can only
  advance once a whole batch yields). Disabling them traded that away; the
  redesign restores it properly instead of re-enabling the old dueling-`Live`
  version.

- ~~**Commit metadata annotation**: add `rinex_hash`, `canonical_name`, `start`, `end` to
  `session.commit(metadata={...})` — self-describing Icechunk history, zero logic change.~~
  **DONE (2026-07-08):** `processor.py:2010–2024` — builds `_commit_meta` dict with
  `receiver`, `date`, `files`, `start`, `end`, `rinex_hashes`, `canonical_names` from
  `metadata_records` and passes it to `session.commit(commit_msg, metadata=_commit_meta)`.
  icechunk v2 `Session.commit()` signature: `(message, metadata: dict[str, Any] | None)`.

- ~~**`canvod-grids==0.2.3` `create_hemigrid()` broken for every grid type — wrong
  logger import**~~ **DONE (2026-07-08)** (found in the external `mp2grids` repo
  integrating `canvod-grids` as a standalone dependency, not via the full monorepo).
  `packages/canvod-grids/src/canvod/grids/core/grid_builder.py:12-16`:
  ```python
  def _get_logger():
      """Lazy import to avoid circular dependency."""
      from canvodpy.logging import get_logger
      return get_logger(__name__)
  ```
  `BaseGridBuilder.__init__` calls this unconditionally, so it fires on
  construction of every builder (`EqualAreaBuilder`, `EqualAngleBuilder`,
  `EquirectangularBuilder`, `HTMBuilder`, `GeodesicBuilder`, `HEALPixBuilder`,
  `FibonacciBuilder`). But `canvodpy` (the orchestrator) is not a distributed
  dependency of `canvod-grids` — only the `canvod` namespace subpackages are —
  so any standalone install raises `ModuleNotFoundError: No module named
  'canvodpy'` on the very first `create_hemigrid(...)` call. Confirmed
  2026-07-08: this is the **only** `from canvodpy` reference anywhere in
  `canvod-grids`' source tree; every other call site in the same package
  already uses the correct local logger (e.g. `operations.py:27` → `from
  canvod.grids._internal import get_logger`). **Fix:** swap the import in
  `grid_builder.py` to `from canvod.grids._internal import get_logger` —
  `_internal/logger.py`'s `get_logger(name: str | None = None)` signature
  matched exactly. Fixed in `grid_builder.py`; verified with
  `create_hemigrid('equal_area', angular_resolution=5.0)` and
  `uv run ty check` — both clean.

- ~~**`DeltaLS` DNU guard** in `_tow_wn_to_utc` (`reader.py:1276`): guard `delta_ls == -128`
  to prevent ~2-min timestamp shift on unsynchronised receivers.~~
  **DONE (2026-07-08):** Fixed at all three `ReceiverTime` match arms (lines ~1276, ~1589,
  ~2128). Pattern: `_dls = int(data["DeltaLS"]); if _dls != -128: delta_ls = _dls`.
  -128 is the SBF DNU sentinel (0xFF signed); keeping the previous/default value prevents
  a ~2-minute UTC timestamp jump when the receiver hasn't yet synchronised to GPS time.

---

---

## 8. ~~VOD hemisphere visualization — integration plan~~ SUPERSEDED (2026-07-13)

**Superseded, not executed as written.** The plan below (§8.1–§8.5) proposed
promoting the prototype by splitting it across the monorepo: `mesh.py` into
`canvod-grids`, `vodgrid.py` into `canvod-store`, rollup math into a new
`canvod-streamstats`, and a new `canvod-serve` package for the FastAPI/xpublish
layer. That's not what happened. Real work since June instead consolidated
everything into one standalone package, **`canvod-streamviz`**
(`/Users/work/Developer/GNSS/canvod-streamviz/`, private repo, not in this
monorepo or in `canvodpy-extensions` — confirmed with the user 2026-07-13 it
stays standalone for now) — `mesh.py`, `rollup.py`, `ingest.py`, `catalog.py`,
`pipeline.py`, `serve/{app,router,cache,zarr_plugin}.py`. Its `serve/`
subpackage fills the role §8.2 wanted a new `canvod-serve` package for — no
separate package needed. `canvod-streamstats` also already exists as its own
mature standalone repo (full accumulator library, ops layer, near-complete
test coverage) — nothing to build there either, just an editable dependency.

**Phase 1 of `canvod-streamviz`'s own `TODO.md` is now done (2026-07-13):**
bumped it to Python 3.14 (canvod-grids/store/vod all require >=3.14, its venv
was 3.13.2), installed canvod-grids/store/vod/streamstats editable, fixed 3
pre-existing test bugs (missing `mode="r"` on a raw `zarr.open_group` call,
`mesh_endpoint`'s ETag headers being dropped because it returned a fresh
`Response` instead of reusing the injected one, a `ThreadPoolExecutor.map`
arg-count bug in a test), and verified end-to-end (not just by reading code)
that `ingest.py`'s `TauOmegaZerothOrder` usage and `catalog.py`'s Icechunk v2
API usage both still match current canvod-vod/canvod-store — no drift found.
Also found the zarr HTTP v3 plugin (`serve/zarr_plugin.py`), which its own
TODO.md called "a skeleton" returning 404s, was in fact already a complete,
working implementation — added 6 tests proving it (root/group/array
`zarr.json`, chunk bytes, 404 cases) since it had zero test coverage before.
41 → 47 tests, all passing. Remaining `canvod-streamviz` work (hour-level
rollup wiring for Phase 4, Phase 2/3 object storage + portal work) tracked in
that repo's own `TODO.md`, not here.

**`prototypes/vod_serving/` in this repo (canvodpy-perf) is now a stale
duplicate** — the original June prototype bundle (committed via `8f334938`),
superseded by `canvod-streamviz`. Not deleted yet; a decision to remove it
is still open.

<details>
<summary>Original plan (2026-07-04), kept for history — not executed as written</summary>

**Status (2026-07-04):** Prototype validated end-to-end (204M obs, selftest + golden scan pass) but lives entirely in an untracked scratch directory outside the repo. Zero provenance. Promote before it rots. Fable architecture review commissioned and plan compiled below.

**Source files (currently untracked, outer scratch repo):**
- `grid_storage/_common.py`, `build_native_full.py`, `build_rollup.py`, `serve_hemisphere.py`, `view_vod_cube.py`, `build_icechunk_cube.py` (contains `build_mesh`)
- `precompute_vod_summary.py` (outer repo root) — has hard dep on untracked side script

### 8.1 Soundness review

**Sound, keep as-is:**
- S² Cartesian unit vectors for mesh nodes — KDTree in R³ is correct; no pole/seam. Standard uxarray/UGRID approach.
- Gridded-in-space, native-in-time — preserves full fidelity; rollup provides O(1) aggregation without baking time bins at build time.
- Prefix-sum rollup for O(1) windowing — sound in principle, with known edge cases below.
- Serve from rollup groups, not raw obs — O(cells) per request regardless of window length. Correct at scale.
- Serve-from-source (rollup groups inside obs store) — single commit = atomicity; no two-store sync. Verify `scan_stores`/viewer tolerate non-(epoch,sid) groups.
- Additive moments (sum/sumsq/count) — correct. **Float64 required** (float32 loses precision at 10⁸ cumulative sum).

**Must fix during promotion (all already flagged in `REVIEW_AND_PROVENANCE.md`):**

1. **No θ cutoff / rejection radius on KDTree.** Obs at/beyond horizon snap to rim cells → horizon inflation + biased VOD. Fix: drop `theta > theta_max` before assignment; reject KDTree matches beyond `1.5 × cell_radius` (return `cell_id = -1`). Add `theta_max_deg` and `rejection_factor` to `RollupConfig`.
2. **`cons` param unvalidated** → `KeyError` → HTTP 500. Fix: `Literal["G","E","C","R","all"]` on the FastAPI query param → automatic 422.
3. **Population vs sample std — decide and document.** Use `ddof=0`, record in group attrs `"std_ddof": 0` and in JSON response. Mask cells where `count < min_count` (config, default 2).
4. **Cumulative dtype.** `cum_sum`/`cum_sumsq` must be float64; counts int64. Float32 cumulative over 2×10⁸ obs loses precision. Assert dtype in `RollupWriter`.
5. **NaN poisoning.** A single NaN VOD corrupts all subsequent cumulative edges. Drop NaNs before accumulation; assert `isfinite` on each appended slice.
6. **Out-of-order ingest / backfill.** If a day older than `edge_time[-1]` is ingested, appending is invalid. Detect and fall back to `build_from_scratch()` (see §8.3).
7. **Window semantics — define once.** `[a, b] = cum[i_b] - cum[i_a]` covers obs in `(edge_a, edge_b]`. Document in group attrs; test for off-by-one.
8. **`sid_code` registry must be append-only** and committed atomically with the obs that use it. Make it a method on the store class, not a dict in a script.

**Note on streamstats wiring:** `canvod-streamstats` does **not** exist as a package in this repo (verified 2026-07-08 — not in `packages/`). `StatisticsConfig` is defined in `models.py:592` but is not wired into the orchestrator. The rollup hook below is the first real instance of the post-commit-step pattern; design it so `StatisticsConfig` can later reuse the same hook point.

### 8.2 Package placement

| Component | Destination | Reasoning |
|---|---|---|
| `build_mesh()` (equal-area → UGRID, Cartesian nodes) | `canvod-grids`, new `packages/canvod-grids/src/canvod/grids/mesh.py` | Pure grid geometry; sits beside `grid_to_dataset`/`store_grid`. Build only from existing `GridData` to enforce no-re-tessellation. |
| `open_session`/`day_bounds`/`vod_for_day` (VOD source iterator) | Folded into `VodComputer.iter_days(pair)` in `canvodpy/src/canvodpy/vod_computer.py` | Duplicate VOD-from-store path; `VodComputer.compute_bulk()` already does this. Reuse internals and `TauOmegaZerothOrder` (never reimplemented). |
| Native obs store schema + writer | `canvod-store`, new `packages/canvod-store/src/canvod/store/vodgrid.py` (`VodGridStore`: `write_grid_mesh()`, `append_day_obs()`, sid-code registry) | Store schema + icechunk R/W = canvod-store's job. KDTree cell assignment (with θ fix) lives in canvod-grids; called from here. |
| Rollup math (additive moments) | `canvod-streamstats`, `canvod/streamstats/accumulators/moments.py` | Math is streaming statistics; testable without a store. |
| Rollup writer/orchestration | `canvod-store`, `vodgrid.py` (`RollupWriter.append_slice()`, `build_from_scratch()`) | Store I/O belongs in canvod-store. |
| `serve_hemisphere.py` | **New package `canvod-serve`** (`packages/canvod-serve/`, deps: xpublish, fastapi, uvicorn) | Not viz (no rendering) and not ops. xpublish/fastapi/uvicorn are heavy deps that must not leak into canvod-viz (imported in notebooks). A dedicated package matches the monorepo's small-package pattern. |
| `view_vod_cube.py` (marimo viewer) | Repo notebooks directory (verify path via `just notebooks` recipe) | Thin HTTP client + Plotly, not library code. |
| `RollupConfig` (Pydantic model) | `canvod-utils`, `models.py` next to `StatisticsConfig` (line 592), referenced from `ProcessingConfig` | Config models are centralized here by convention. |

### 8.3 Pipeline integration design

**Open question (must resolve first):** The rollup consumes VOD per pair. `_append_to_icechunk()` writes raw observables — not VOD. The hook belongs to the **VOD persistence stage**, not the ingest commit. Determine whether per-day VOD is already persisted (check `site.process()` / workflows), or if `VodGridStage` is the first VOD persistence stage. This determines the hook point.

**`RollupConfig` fields:**
```python
class RollupConfig(BaseModel):
    enabled: bool = False
    pairs: list[str] | Literal["auto"] = "auto"  # auto = derive from vod_analyses keys
    freq: str = "1D"
    theta_max_deg: float = 90.0            # KDTree assignment cutoff
    rejection_factor: float = 1.5          # × cell radius for rejection
    min_count: int = 2                     # serving-side mask threshold
    constellations: list[str] = ["G", "E", "C", "R"]
    # dtype: float64/int64 enforced in RollupWriter, not configurable
```

**Hook placement:** inside `VodGridStage`, after `append_day_obs()`, **before** `session.commit()` — same commit. Atomicity of obs+rollup is the whole point.

**Append-one-slice mechanics:**
1. Read last cumulative edge: `{cum_count[-1], cum_sum[-1], cum_sumsq[-1], cum_count_{G,E,C,R}[-1]}` — shape `(cell,)`.
2. Drop NaNs; assert `isfinite`.
3. Guard: `day_end > edge_time[-1]` else `raise RollupOrderError` → caller runs `build_from_scratch()`.
4. Compute delta via `np.bincount(cell_id, ...)` (vectorized `sid_code→letter` via `meta/`).
5. Append `last + delta` + new `edge_time`.

**Idempotency:** per-edge `built_from_commit` array (same `edge` dim) + group attr `schema_version: 2`. Before appending for day D with commit X: if D exists with same X → skip (no-op); if D exists with different X → full rebuild.

**Backfill:** `RollupWriter.build_from_scratch(pair, freq)` — the promoted `build_rollup.py` becomes exactly this. Expose as `just rollup-rebuild <store> <pair>`. Auto-trigger when rollup group missing, invariant fails, or `RollupOrderError`.

### 8.4 Numbered implementation plan

1. **Promote prototype (provenance first).** Move per §8.2: `_common.py` → split to `canvod/grids/mesh.py` + `canvod/streamstats/accumulators/moments.py`; `precompute_vod_summary.py` → `VodComputer.iter_days()`; builders → `canvod/store/vodgrid.py`; `serve_hemisphere.py` → `packages/canvod-serve/`; `view_vod_cube.py` → notebooks. Apply fixes #1–#5 (θ cutoff, cons validation, ddof decision, float64, NaN drop) *during* the move — do not port broken behavior. Port selftest as integration test.

2. **Phase 1 — rollup schema v2 + golden tests.** Changes from prototype: per-constellation `cum_sum_{G,E,C,R}` / `cum_sumsq_{G,E,C,R}` (not just counts); `built_from_commit` per-edge array; group attrs `schema_version=2`, `std_ddof=0`, window semantics string. Golden tests (pytest): (a) prefix-window diff vs brute-force recompute, all window positions; (b) `(a, b]` inclusivity; (c) NaN rejection; (d) float64 dtype assertion; (e) real-day fixture round-trip; (f) `cum_count[-1].sum() == len(obs)` invariant.

3. **Pipeline integration.** `RollupConfig` in canvod-utils, `VodGridStage` in canvodpy orchestrator (resolve open question first), idempotent `append_slice` with `built_from_commit` skip, `build_from_scratch` backfill + `just rollup-rebuild`. This establishes the post-processing hook that `StatisticsConfig`/streamstats wiring can later reuse.

4. **Deferred work (Phases 2–6 from `MATURATION.md`).** Phase 2 (catalog, per-site layout, object storage): premature, no second site in production. Phase 3 (multi-tenant serving, LRU, multi-resolution): single-site serving works; LRU matters at >~3 sites × 3 pairs × 90 MB. Phase 4 (24h self-updating job): nearly free after Phase 3 — wire into automation backend chosen by n8n/canvod-automate decision. Phases 5–6 (frontends, productionization): blocked on Phase 3. Float64 sumsq cancellation mitigation (block re-anchoring): adequate at current 10⁸ obs scale; revisit only on test failure.

### 8.5 Open questions

- Does the pipeline already persist per-day VOD to a store? (Determines hook point — §8.3 prerequisite.)
- Same icechunk repo as RINEX store, or separate per-site repo? Recommend **separate** (RINEX dedup guardrails assume (epoch, sid) dims, incompatible with (edge, cell) rollup groups).
- Notebooks directory exact path — verify via `just notebooks` recipe.
- Should `canvod-serve` selftest run in CI (needs fixture store) or as a manual `just` target?

</details>

---

---

## 9. ~~Production pipeline config — revisit before next run~~ — PARTIALLY RESOLVED

**Context (2026-07-04):** First production config written for rosalia/January 2025 RINEX run. Two fields added that need review:

- ~~**`batch_hours: 24`**~~ — **RESOLVED (96e58c73):** `batch_hours` removed entirely from `ProcessingParams`; pipeline handles file granularity via `FilenameMapper`, not a time-based batch window.
- ~~**`resource_mode: auto`**~~ — **RESOLVED (96e58c73):** `auto` now caps at `cpu_count − 2` workers and applies `nice=3`. Add `auto_uncapped: true` only on a dedicated machine. Shared server no longer needs manual intervention by default.
- ~~**`preprocessing.grid_assignment`** — still open: 2° equal-area grid assignment is currently baked into preprocessing. Confirm this is the intended behavior (vs. doing grid assignment only at VOD time) and that it doesn't conflict with the rollup-native store's own `cell_id` assignment.~~
  **RESOLVED, non-issue (confirmed 2026-07-14):** it isn't actually baked into
  preprocessing today. `config/canvod-settings.yaml`'s own 2026-07-10 note
  says `grid_assignment`/`temporal_aggregation` only feed `canvod-ops`'s
  standalone `build_default_pipeline()`, which nothing in the live
  orchestrator (`processor.py`, `workflows/tasks.py`) or the CLI calls yet —
  the config value is currently dormant. Real ingested data gets grid-cell
  assignment ad hoc downstream instead (canvod-streamviz's own KDTree-based
  ingest step). No conflict exists because the orchestrator-side path isn't
  wired in at all; revisit if/when it is.

---

## Combined implementation order (when ready)

```
§2 scaffold  (store reindex helper + tests — inert, safe to ship first)
  → §1       (SidsConfig + universe builder)
  → §2 flip  (pad_global_sid=False in orchestrator + region path)
  → audit + Tier-2 regression
§5 + §6     (parallelism + streaming) — after §1/§2
§3 / §12    (virtualiconvname — larger, §12 has the detailed plan)
§4 / §10–11 (config: standalone warnings fix first, then UX modernization)
Quick wins  — ride alongside any of the above
```

---

## 10. Standalone sub-package install — config warnings leak (Fable review, 2026-07-05) — TIER 1 RESOLVED

**Problem:** Installing only `canvod-readers` or `canvod-grids` (without the full canvodpy pipeline) produces 4–6 lines of `⚠️ Warning` noise on stdout per `.to_ds()` call, each telling the user to run `just config-init` — a command that doesn't exist in their environment.

### Current behaviour (Fable-verified file:line)

- `loader.py:133–134` — `_load_processing()`: bare `print()` to stdout when `processing.yaml` absent
- `loader.py:146–147` — `_load_sites()`: bare `print()` to stdout when `sites.yaml` absent
- `loader.py:116–118` — `sys.exit(1)` on `ValidationError` — a library function killing the interpreter
- `loader.py:20–55` — `find_monorepo_root()` walks up from cwd looking for `.git`; in a scientist's own repo the warning names a directory in _their_ project
- No caching: `load_config()` (loader.py:233–262) re-reads YAML every call; warnings print every single time

**Trigger chain for `canvod-readers` standalone user:**

1. `readers/base.py:421` — `_build_attrs()` → `get_global_attrs()` → `metadata.py:254` → `load_config()` (fires on every `.to_ds()`)
2. `rinex/v3_04.py:1816` — `keep_data_vars is None` → `load_config().processing.keep_rnx_vars`
3. `rinex/v3_04.py:1847` — if `outname` given → `load_config().processing.compression`
4. `v2_11.py:1392` — `_create_basic_attrs()` → `get_global_attrs()` again

Net: 2–3 `load_config()` calls, 4–6 warning lines, every `.to_ds()`.

**Secondary failure mode:** `canvod-store/reader.py:161` and `manager.py:884` — `next(iter(config.sites.sites))` crashes with bare `StopIteration` when sites is empty (no config). Completely cryptic for a user who just wants to open a store.

**Oddity:** `canvod-utils/config/defaults/sites.yaml` exists but `_load_sites()` never reads it (unlike the other two loaders). Dead file or missing merge.

### Root cause

`load_config()` conflates two audiences: (a) the orchestrator's "you must configure your pipeline" gate and (b) a silent defaults provider for library internals (attrs, compression, keep-vars). The warning text assumes audience (a); the callers in canvod-readers are audience (b).

Good pattern already in-tree to copy: `canvod-store/store.py:139–149` and `canvod-ops/registry.py:29–33` both wrap `load_config()` in `try/except` and fall back to Pydantic model defaults.

### Fix strategy (~55–70 lines, 5–6 files)

**~~Tier 1 — fix the loader (canvod-utils, eliminates 90% of noise):~~ DONE**
1. ~~Replace the four `print()` lines~~ — **DONE:** `logger.warning()` throughout.
2. ~~Add `strict` semantics~~ — **DONE:** defaults silently when config absent; `ConfigValidationError` raised on bad YAML.
3. ~~Add `@lru_cache`~~ — **DONE:** `@functools.lru_cache(maxsize=8)` on `load_config()`.
4. ~~Replace `sys.exit(1)` with `raise ConfigValidationError`~~ — **DONE.**
5. ~~Either use `defaults/sites.yaml` in `_load_sites()` or delete it.~~ **RESOLVED (moot):** unified config makes this irrelevant — see §4.

**Tier 2 — decouple readers from config (canvod-readers):**
6. ~~`metadata.py:254`: wrap in `try/except Exception: meta = MetadataConfig()`. ~6 lines.~~
   **DONE (2026-07-08):** `get_global_attrs()` now wraps `load_config()` in `try/except
   Exception` and returns `{"Software": "canVODpy"}` on failure. Note: `MetadataConfig()`
   cannot be instantiated without required fields (`author`, `email`, `institution` use
   `Field(...)`), so the fallback is a minimal attrs dict rather than a default model.

**Tier 3 — fix cryptic crashes (canvod-store):**
7. ~~`reader.py:161` and `manager.py:884`: replace bare `next(iter(...))` with a clear `ValueError("No sites configured. Create config/sites.yaml or pass site_name explicitly.")`. ~8 lines.~~
   **DONE (2026-07-08):** Both sites guard `if not _sites: raise ValueError(...)` before
   calling `next(iter(...))`. Message: "No sites configured — create canvod-settings.yaml
   or pass site_name explicitly."

### Packages affected

| Package | Change | Required? |
|---|---|---|
| **canvod-utils** | loader.py: logging, strict mode, lru_cache, no sys.exit | Yes — root fix |
| **canvod-readers** | metadata.py:254 fallback to `MetadataConfig()` | Recommended |
| **canvod-store** | reader.py:161, manager.py:884 clear error | Recommended |
| **canvodpy** | switch entry points to `load_config(strict=True)` | Yes if strict mode added |
| canvod-grids, canvod-vod, canvod-viz, canvod-virtualiconvname, canvod-store-metadata | no changes — no `load_config()` usage | — |

---

## 11. Config UX overhaul + TUI redesign — unified implementation plan

> **§11 and §13 are merged here.** The config wizard IS the TUI entry point. §13 below is a cross-reference stub.
>
> **Design principle:** scientists do not write config files. The wizard scans their data directory, infers structure, shows a confirmation table, then asks the 5 non-discoverable facts. The YAML file is the wizard's output artifact, not a prerequisite. Everything else — Icechunk layout, Dask scheduler, chunk sizes — uses opinionated defaults never visible to scientists.

### The 5 non-discoverable facts

Everything else is auto-detected (file naming, temporal extent, SID universe) or set by opinionated defaults scientists never need to touch. The wizard asks only:

1. Which receiver is under the canopy (pairing)
2. Output path for Icechunk stores
3. Author name + email (FAIR/DataCite metadata)
4. VOD model to use (default: `tau_omega_zeroth_order`)
5. (Optional) site lat/lon, altitude — fillable later

### Phase 0 — Silent trap fixes (~1 day) — PREREQUISITE

~~Files: `packages/canvod-utils/src/canvod/utils/config/loader.py`, `models.py`.~~

1. ~~`loader.py:118` — replace `sys.exit(1)` with `raise ConfigValidationError`~~ **RESOLVED (c7bcad13)**
2. ~~Replace all `print()` warnings in `loader.py` with `logging.getLogger("canvod.config")`~~ **RESOLVED (c7bcad13)**
3. ~~`@lru_cache(maxsize=4)` on `load_config` keyed on resolved `config_dir`.~~ **RESOLVED (e8275bc6):** `@functools.lru_cache(maxsize=8)`
4. ~~`model_config = {"extra": "forbid"}` on **every** nested model~~ **RESOLVED (c7bcad13):** `_StrictModel` base class, all 24 config classes inherit it.
5. ~~Path-existence `@field_validator` on `stores_root_dir`, `gnss_site_data_root` — reject sentinel values (`/path/to/stores`, `Unknown`, `user@example.com`) at load time.~~ **DONE (2026-07-08):**
   - `MetadataConfig`: `_reject_sentinel_author` rejects `"Unknown"`, `"Your Name"`, `"Your Name Here"`
   - `MetadataConfig`: `_reject_sentinel_email` rejects `"user@example.com"`, `"your@email.com"`, `"your.email@example.com"`
   - `StorageConfig.validate_stores_dir`: extended to reject `"/path/to/stores"`, `"/path/to/your/stores"` before expanding `~`
   - All raise `ValueError` with a plain-language message pointing to `canvod-settings.yaml`

### Phase 1 — Config simplification (~3 days)

Files: `models.py`, `defaults/` templates, `canvodpy/src/canvodpy/cli/config.py`, `docs/guides/configuration.md`.

1. ~~Collapse `processing.yaml` + `sids.yaml` into `sites.yaml` optional sections.~~ **RESOLVED (c7bcad13 + 4f855dde):** unified `canvod-settings.yaml` loader implemented; legacy 3-file path kept with `DeprecationWarning`. Dask scheduler addr removed. Template still needs trimming (infrastructure fields not yet moved to `defaults/advanced.yaml`).
2. ~~Rename `ReceiverConfig.scs_from` (models.py:698) → `pairs_with_canopy`~~ **RESOLVED (4f855dde):** renamed to `paired_canopies` with deprecated `scs_from` alias; `resolve_scs_from → resolve_paired_canopies` kept as alias.
3. ~~Implement `SidsConfig._get_preset_sids()` (models.py:967 TODO stub returning `[]`) from packaged `presets/` dir, or remove `preset` from the `Literal` entirely and fix `sids.yaml.example:31–36`.~~ **RESOLVED (ac5283e8):** implemented with bundled `presets/default.yaml`.
4. ~~Docstring the 5 non-discoverable facts on `SiteConfig` / `ReceiverConfig` / `MetadataConfig` — these become the wizard's question prompts verbatim.~~ **DONE (2026-07-08):**
   - `MetadataConfig.author`, `.email`, `.institution`: wizard-prompt-quality `description=` strings with example values and "Wizard prompt:" labels
   - `StorageConfig.stores_root_dir`: "Where should processed results be stored?"
   - `ReceiverConfig.type`: "Is this receiver under the canopy or in the open sky?"
   **Auto-derive vod_analyses also DONE:** Added `_auto_derive_vod_analyses` `@model_validator(mode="after")` on `SiteConfig` — when `vod_analyses` is omitted, expands `paired_canopies` via `get_reference_canopy_pairs()` into `{canopy}_vs_{ref}: VodAnalysisConfig(...)` entries. Users no longer need to declare pairings twice.
5. ~~Fix documentation drift: `configuration.md:91` `base_dir` → `gnss_site_data_root`; `configuration.md:145` `custom:` → `custom_sids`; correct `scs_from` receiver example (L103–107).~~ **ALREADY RESOLVED** (verified 2026-07-08: all three drifts absent from current file — `base_dir` gone from L91 area, L145 shows `paired_canopies: all`, L289 names field correctly with deprecated alias note).

**Risk:** field rename ripples into `canvodpy/src/canvodpy/orchestrator/pipeline.py` and `workflows/tasks.py` — grep `scs_from` across the workspace before merging. Depends on Phase 0 item 4.

### Phase 2 — Discovery wizard: `canvodpy init` — CANCELLED (2026-07-14)

**User direction (2026-07-14):** we don't need config/recipe inference — the
user controls what goes in. This kills the whole data-directory-scanning +
recipe-inference premise below, not just the recipe-inference stretch goal.
The already-existing `canvodpy config init --interactive` (fixed 8 questions,
no directory scanning, no recipe inference — see Phase 3's "DONE, partially"
note above) is now the **final** state here, not a partial step toward this
Phase 2. Nothing further planned.

<details>
<summary>Original plan (2026-07-05), kept for history — not being built</summary>

Files: `canvodpy/src/canvodpy/cli/config.py` (upgrade `init` command), new `wizard.py` alongside it. New dep: `questionary` (MIT, actively maintained, prompt_toolkit 3.x).

1. `canvodpy init` flow:
   - `questionary.path` → data directory
   - Scan with `canvod.virtualiconvname.patterns.BUILTIN_PATTERNS`
   - Align a sample filename against `CanVODFilename` (canvod-virtualiconvname/convention.py:109) → emit `config/recipes/<name>.yaml`
   - Build Rich confirmation table: inferred receivers, temporal extent, format — **show before asking**, never silently commit
   - Ask the 5 non-discoverable facts
   - Write `sites.yaml` (Phase 1's single-file format, ~25 lines)
   - Re-run `load_config(strict=True)` immediately; render `ConfigValidationError` as plain English (map Pydantic `loc` tuples to YAML paths)
2. Non-TTY guard: `if not sys.stdin.isatty(): print instructions; sys.exit(2)` — never hang on prompts in cron/CI.
3. `canvodpy run` after `init` needs no further config — just `--site <name> --start --end`.

**Risk:** heterogeneous data dirs (daily + sub-daily files) confuse inference → reuse `FilenameMapper` dedup logic already in the codebase. Hard-depends on Phase 0 (strict load) and Phase 1 (small template = small wizard output).

</details>

### Phase 3 — TUI dashboard + `canvodpy vod` subcommand (~3–5 days)

#### Dashboard — DONE (2026-07-08)

**What was built:** Pure Rich (not Textual) `Reporter` abstraction in
`canvodpy/src/canvodpy/cli/dashboard.py`.  `run.py` updated to use it.

**How it works:**
- TTY auto-detected via `sys.stdout.isatty()` — no flag needed.
- **Non-TTY** (`PlainReporter`): identical output to before, plain `print()`.
- **TTY** (`RichReporter`): `Live(Group(Panel, Progress))` pinned at the bottom;
  per-day lines scroll above via `live.console.print()`.

**Invoke:**
```bash
# TTY → Rich Live display
uv run python -m canvodpy.cli.run --site Rosalia --start 2025001 --end 2025007

# Force plain output (e.g. when piping)
uv run python -m canvodpy.cli.run --site Rosalia 2>&1 | tee run.log
```

**What you see in TTY mode:**
```
  ephemeris=final  resource_mode=auto  strategy=skip
  VOD analyses: ['canopy_01_vs_reference_01']

─── 2025001
  canopy_01: 17280×277  reference_01_canopy_01: 17120×277
  VOD canopy_01_vs_reference_01: 1204k/1204k valid (98%)  1.2s
  pipeline=42.3s  vod=1.2s  vod_store=0.3s

╭─────────────────────────────────────────────────────╮
│  ─[◉]─  canvod · ROSA · 2025001–2025007 · day 3    │
╰─────────────────────────────────────────────────────╯
  Overall  ━━━━░░░░░░░░  3/7 days  0:02:06  eta 1:55:14
```

**What's deferred (Phase 3b):**
- Per-receiver progress bars (◉/◎ step labels from §14) — require orchestrator
  event hooks (asyncio.Queue into processor.py) not yet wired.
- Decision against Textual: pure Rich `Live` covers the need without the heavy
  dep; Textual adds value only if we need interactive widgets (keyboard nav,
  mouse, collapsible sections). Revisit if those become a requirement.

#### Still open in Phase 3

**Correction (2026-07-14):** items 2/3 below are stale — verified directly
against current code. `VodComputer.__init__(calculator: str = "tau_omega")`
already resolves through `VODFactory` for both `compute_day()` and
`compute_bulk()` — it is **not** hardcoded to `TauOmegaZerothOrder` anymore.
`canvodpy run --vod-calculator <name>` already exists too, dynamically
populated from `VODFactory.list_available()`
(`cli/run.py:_build_vod_calculator_choice`). What's actually still missing —
the standalone `canvodpy vod` CLI subcommand itself, plus the bigger
VOD-store organizational/metadata design this surfaced — is now specified in
full in **§29**, not here.

~~2. `canvodpy vod` subcommand: `--site`, `--analysis`, `--start`, `--end`, `--calculator`. Thread `calculator_cls` through `VodComputer.compute_bulk()` (vod_computer.py:127) — currently hardcoded `TauOmegaZerothOrder` at L236.~~
~~3. Calculator registry in `VODFactory` (factories.py:362): resolve `importlib.metadata.entry_points(group="canvodpy.calculators")` first; if `":"` in the name, import dotted path (`mylab.module:MyClass`). Register `tau_omega_zeroth_order` (`canvod-vod/.../calculator.py:148`) in `pyproject.toml` `[project.entry-points."canvodpy.calculators"]`.~~

**Constraint:** no `xr.concat()` anywhere in `compute_bulk` changes.

**Total effort: ~11–14 days.** Phase 0 is the prerequisite; Phases 1–2 deliver the biggest scientist-visible wins and can ship before Phase 3.

---

**Minimum a scientist must write:** ~13 YAML keys / 2 files at absolute minimum; ~35 keys / 4–5 files in practice (vendor filenames → recipes; provenance metadata; NASA credentials).

### Pain points (Fable-verified, with file:line)

1. **Conceptual split is developer logic, not scientist logic.** "Where my data lives" (`gnss_site_data_root`, sites.yaml) vs. "where results go" (`storage.stores_root_dir`, processing.yaml) — in different files. A scientist thinks per-site.
2. **Silent placeholder failure.** `defaults/processing.yaml:57` ships `stores_root_dir: /path/to/stores  # MUST be set by user!`. Pydantic accepts it; `config validate` passes; pipeline fails at runtime. Same for `author: Unknown` / `email: user@example.com` which end up in FAIR/DataCite metadata.
3. **Typos silently ignored in every nested section.** `model_config = {"extra": "forbid"}` exists only on top-level `CanvodConfig` (models.py:990). All nested models (`ProcessingParams`, `StorageConfig`, `SiteConfig`, …) use Pydantic's default `extra="ignore"` — `bach_hours: 6` or `angular_resoluton: 1.0` gets no error, just the default value.
4. **`scs_from` is cryptic and asymmetric.** Required for reference receivers, forbidden for canopy (models.py:737–746). No scientist knows what "SCS" means. The docs (`docs/guides/configuration.md:103–107`) show `scs_from` on canopy receivers — copying that fails validation with a confusing error.
5. **Documentation drift → guaranteed first-run failures.** `configuration.md:91` uses `base_dir`; model requires `gnss_site_data_root` (models.py:760). `configuration.md:145` uses `custom:`; model field is `custom_sids` (models.py:912). Two validation errors on first try following the official guide.
6. **Redundant declaration.** `vod_analyses` (models.py:769) restates the pairing already encoded in `scs_from`. Users say "canopy_01 pairs with reference_01" twice, in two syntaxes.
7. ~~**`sids: mode: preset` documented but not implemented.** `SidsConfig._get_preset_sids()` is a TODO returning `[]` (models.py:959–969); `config/sids.yaml.example:31–36` advertises three presets. User selecting `preset: gps_galileo` silently filters to nothing.~~ **RESOLVED (ac5283e8)**
8. **Overwhelming template.** `config/processing.yaml.example` is 217 lines exposing Icechunk `inline_threshold`, chunk strategies, Dask scheduler addresses — pure infrastructure jargon for an ecologist whose only real decisions are "where is my data, where do results go."
9. **`sys.exit(1)` in a library.** `loader.py:118` kills a Jupyter/marimo kernel session on validation error instead of raising.
10. **Git-checkout coupling.** `find_monorepo_root()` requires a `.git` directory (loader.py:20–55); a scientist who `pip install`s canvodpy without cloning lands in a poorly documented `cwd/config` fallback.

### Minimum viable config (current)

```yaml
# config/processing.yaml (everything else from packaged defaults)
metadata:
  author: Jane Forester
  email: jane@boku.ac.at
  institution: BOKU
storage:
  stores_root_dir: /data/stores   # required in practice; default is a fake path
```

```yaml
# config/sites.yaml (no defaults; entirely user-written)
sites:
  mysite:
    gnss_site_data_root: /data/mysite
    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        scs_from: all
      canopy_01:
        type: canopy
        directory: 02_canopy
    vod_analyses:
      canopy_vs_reference:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

`config/sids.yaml` can be omitted. That is 13 keys / 2 files at absolute minimum.

### Alternative approaches

**Option A — `canvod init` interactive wizard** (upgrade the existing template-copier in `cli.py:90–198`):
Replace template copy with typer/rich Q&A: site name → data root → scan subdirs → detect format → ask "which receiver is under the canopy?" → author/email → stores dir. Recipe inference as a stretch goal.
- Pros: zero YAML knowledge at bootstrap; live path/data validation during setup; builds on existing CLI
- Cons: helps only at first run; recipe inference is genuinely hard; wizard needs maintenance alongside models
- Effort: 3–4 days wizard, +3–4 days recipe inference. Fit for scientists: excellent day one, neutral afterwards.

**Option B — single consolidated `canvod-settings.yaml`, site-centric** (recommended structural fix):
One file; site is the top-level concept; `processing`/`sids`/`storage` become optional override sections. Loader already deep-merges (loader.py:181–211) — mostly re-plumb `_load_*` to read one file, keep 3-file path as deprecated fallback. Pair with convention-over-configuration: derive `vod_analyses` from `scs_from`; rename `scs_from` to something human; default `directory` to receiver name.
- Pros: one file = one mental model; minimal config shrinks to ~10 lines; matches Snakemake/nf-core convention scientists already know; fixes the "which file does this go in?" question permanently
- Cons: migration shim needed; doesn't fix recipes by itself; docs rewrite
- Effort: 2–3 days loader + models, 1 day docs. Fit for scientists: high — this is the structural fix.

**Option C — hardening + honesty pass** (no structural change; prerequisite for A and B):
`extra="forbid"` on all nested models; sentinel detection for placeholder paths/author; raise instead of `sys.exit`; implement or remove SID presets; fix 3 documentation drifts; auto-derive `vod_analyses`.
- Pros: cheapest, immediately reduces silent-failure incidents
- Cons: scientists still face 3+N files and a 217-line template
- Effort: 1–1.5 days. Necessary but not sufficient.

**Field consensus** (Snakemake, Dask, nf-core): one user-facing file, everything defaulted, interactive wizard for bootstrap.

### Recommendation: C → B → A

Do C first (fixes silent traps that would poison any new UX), then B (structural fix that matches how scientists think; makes wizard output trivially small), then A wizard (with B in place, wizard asks ~6 questions and writes a ~12-line file; recipe inference ships as a follow-up).

### Implementation plan

**Phase 1 — hardening (1–1.5 days):**
- `models.py`: add `model_config = ConfigDict(extra="forbid")` to all nested models (shared base class); add `@model_validator` on `StorageConfig`/`MetadataConfig` rejecting sentinel values (`/path/to/stores`, `Unknown`, `user@example.com`) with plain-language messages; auto-derive `vod_analyses` in `SiteConfig` when omitted (from `get_reference_canopy_pairs()`, models.py:845).
- `loader.py:110–119`: raise `ConfigError` instead of `sys.exit(1)`; keep pretty-printing in CLI layer only.
- ~~`models.py:959–969`: implement `_get_preset_sids()` from packaged `presets/` dir~~ **RESOLVED (ac5283e8)**
- `docs/guides/configuration.md`: fix `base_dir`→`gnss_site_data_root` (L91), `custom`→`custom_sids` (L145), correct `scs_from` semantics (L103–120).

**Phase 2 — single `canvod-settings.yaml` (3–4 days):**
- `loader.py`: new resolution order — `$CANVOD_CONFIG` → `./canvod-settings.yaml` → `config/canvod-settings.yaml` → legacy 3-file mode (deprecation notice). Sections: `site:`/`sites:`, optional `processing:`, `storage:`, `sids:`, `metadata:`. **Mechanism: use `pydantic-settings` `BaseSettings` to implement env-var override layer — see §16 for details.**
- `models.py`: rename `scs_from` with Pydantic `AliasChoices` so old files keep working.
- New `config/canvod-settings.yaml.example` (~25 lines); demote 217-line `processing.yaml.example` to `docs/reference/config-full.md`.
- Update `justfile` targets `config-validate`/`config-init` (justfile:104–116).

**Phase 3 — wizard (3–4 days; +3–4 later for recipe inference):**
- ~~`cli.py`: `canvod config init --interactive` ... Writes minimal
  `canvod-settings.yaml`, runs validation immediately.~~ **DONE, partially
  (2026-07-12, `5296bcb5`):** `canvodpy config init --interactive` exists —
  asks 8 fixed questions (author, email, institution, stores_root_dir,
  site_name, data_root, canopy/reference dir names), patches answers into
  the raw template text (preserving all comments — no YAML parse/re-dump),
  then runs `load_config()` immediately and reports validity via
  `format_validation_error()`. **Not done:** it's opt-in (`--force`-guarded,
  doesn't touch an existing file), not the default; no directory/format
  auto-detection reused from `validate` — the wizard asks fixed questions
  rather than scanning the data directory first.
- ~~Follow-up: recipe inference — user pastes one filename, wizard aligns it against `CanVODFilename` fields and emits `config/recipes/<name>.yaml`.
  **Still open** — not attempted.~~
  **MOOT (2026-07-14):** contradicted Phase 2's own cancellation note above
  ("we don't need config/recipe inference — the user controls what goes
  in") — this line was a stale leftover from before that decision, not a
  real open item.

**Tests/docs (1–2 days):** extend `packages/canvod-utils/tests/test_config_models.py`; rewrite `docs/guides/configuration.md` around the single file; add "5-minute setup" to `docs/guides/getting-started.md`.

**Total: ~8–11 days.** Phase 1+2 (~5 days) deliver the biggest scientist-visible wins.

---

## 12. ~~canvod-virtualiconvname split → `canvod-preflight` + optional virtual renaming~~ RESOLVED 2026-07-06

**Architecture decision (2026-07-05):** the package is split into two. The virtual renaming engine stays in `canvod-virtualiconvname` as an optional standalone package — not auto-used by the pipeline, manually slotted in by users who need it (e.g. Septentrio SBF / RINEX v2 with non-standard names). The validation and convention logic moves to a new mandatory package: **`canvod-preflight`**.

**Why the virtual renaming can't be the default:** there is no reliable "standard" GNSS filename convention across manufacturers (Trimble, Leica, NovAtel, u-blox, Javad all differ), receiver firmware versions, and lab naming practices. The 5 BUILTIN_PATTERNS cover Septentrio output and the IGS RINEX v3 long-name convention — a subset of real-world deployments. The `NamingRecipe` character-offset escape hatch is too complex for scientists and fails silently. Making virtual renaming optional and explicit is more honest than pretending it covers everything.

**Pipeline default (Strategy A):** canvodpy requires RINEX v3 long-name files (`SITE00CTY_R_YYYYDDDHHMM_PER_SAMP_CONTENT.rnx`). `canvod-preflight validate` checks that the data directory contains files in this format before ingestion. `gfzrnx` (already installed) converts any RINEX format to long-name convention as a one-time per-site step.

**`canvod-virtualiconvname` (optional, standalone, no pipeline dependency):**
- Keeps: `FilenameMapper`, `VirtualFile`, `NamingRecipe`, `BUILTIN_PATTERNS`, `mapping.py`, `recipe.py`, `config_models.py`
- Use: user installs separately, manually wraps the pipeline's file discovery step when their data uses non-standard names
- Integration: TBD — open question is what hook point in `canvodpy` allows a custom file mapper to be injected (e.g. `site.pipeline(file_mapper=...)` or a pre-processing step that produces a staging dir with canonical names)
- The package name stays as-is; it accurately describes what it does for users who need it

**`canvod-preflight` (new, mandatory in canon repo):**

Extracts from current `canvod-virtualiconvname`:
- `convention.py` → `canvod.preflight.convention` (`CanVODFilename`, `FileType`, `ReceiverType`)
- `validator.py` → `canvod.preflight.validator` (`DataDirectoryValidator`, `ValidationReport`, `detect_overlaps`)
- `catalog.py` → `canvod.preflight.catalog` (`FilenameCatalog`)

New additions (from §12 pain-point analysis below):
- Plain-language error messages (replace canonical-name exposure in validator.py:135–159)
- `ValidationReport.is_valid` hard-fails on zero matched files (currently returns True — worst bug)
- Overlap detection in recipe path (tasks.py:402–407 — currently missing)
- Log every skipped file at WARNING (mapping.py:145–146 silent drops)
- RINEX header peek: sampling rate in header vs filename
- Gap detection: missing days in date range
- Standalone CLI: `canvod-preflight validate <data-dir>` producing the plain-language report shown below

**Open question:** what other a priori checks belong here over time? File size sanity (24h at 5s → expected N epochs), receiver firmware metadata from RINEX header, coordinate consistency across days?

**Supersedes §3** (implementation ticket stub, which remains). The pain-point analysis below is the Fable-verified input to `canvod-preflight` design.

### Pain points (P1–P6, Fable-verified)

**P1 — Two parallel config systems exposed to users.** `validate_data_dirs()` (tasks.py:436–577) supports "Recipe mode" (`recipe:` key → `NamingRecipe`) and "Legacy mode" (`naming:` dict). The docstring explains both. A scientist has no basis for choosing. Vocabulary is inconsistent between them (`directory_layout` vs `layout`, `source_pattern` vs `glob` + `fields`).

**P2 — The recipe asks scientists to hand-write a parser.** `NamingRecipe.fields` (recipe.py:135–137) requires a character-position spec (`skip: 4`, `doy: 3`, `hour_letter: 1`…). This requires knowing what a glob is, what DOY is, what a RINEX "hour letter" is, and counting character offsets. This is regex-by-another-name. A forester cannot produce this.

**P3 — Documented escape hatches don't exist.**
- tasks.py:344: `Create it with: just naming-init {recipe_name}` — **no such recipe in the justfile**.
- `config/sites.yaml.example:9`: "See config/recipes/ for examples" — **`config/recipes/` does not exist**.
A new user following the official breadcrumbs hits two dead ends before their first run.

**P4 — All config fields are software-internal, not scientist-facing.** `ReceiverNamingConfig` (config_models.py:35–54): `source_pattern` (name of an internal regex), `directory_layout` (enum of glob strategies), `agency` (3-char code only used to build the canonical filename), `sampling`/`period`/`content` (duration codes like `05S`, `01D`, `AA`). None describe the scientist's reality.

**P5 — Silent data loss; "valid" with zero files.**
- `FilenameMapper.discover_all/discover_for_date` (mapping.py:145–146, 178–179): swallows `ValueError`/`KeyError` with bare `continue` — unmappable files vanish silently.
- `ValidationReport.is_valid` (validator.py:37–40) returns `True` when `matched` is **empty**. Wrong `directory_layout` → finds nothing → reports "0 files, all valid". The scientist's worst failure (misconfiguration) is reported as success.
- Recipe mode: `_validate_receiver_with_recipe` ignores its `reader_format` parameter (tasks.py:353); checks only duplicate canonical names (tasks.py:402–407), not temporal overlaps — weaker guardrails than legacy mode.

**P6 — Errors speak canonical-name, users speak filenames.** `_format_validation_error()` (validator.py:135–159) says "3 file(s) could not be mapped to canonical names" and shows overlaps as `ROSA01TUW_R_20250010000_01D_05S_AA.rnx overlaps …` — strings the user never created and cannot decode.

### User journey (where confusion occurs)

1. Copy `config/sites.yaml.example` — fine until `recipe:` line. Referenced examples dir doesn't exist. ❌
2. Create a recipe — must hand-author `fields:` char-offsets and a glob. Most users stall or copy-paste a wrong one. ❌
3. Run pre-flight (`just config-check-data`) — missing recipe suggests a nonexistent command. Wrong layout → 0 files → "all valid". ❌❌
4. Fix filename mismatches — error lists canonical names and counts, not causes or fixes. ❌
5. Run pipeline — `discover_*` silently drops unmapped files; partial data with no warning. ❌

### Auto-detection opportunities

| Field | Auto-detectable? | How | Effort |
|---|---|---|---|
| `directory_layout` | **Yes, trivially** | Probe subdirs: `\d{5}` → YYDDD_SUBDIRS; `\d{7}` → YYYYDDD_SUBDIRS; data files at top → FLAT. Warn on ambiguity. Reuse existing regexes at mapping.py:350–352. | ~0.5 day |
| `source_pattern` | **Yes — already is** | Default is `"auto"` (config_models.py:45). No user case requires overriding it. Deprecate the field; keep as hidden expert override. | ~0 (deprecate) |
| `receiver_number` | **Yes** | Derive from trailing digits of the receiver key (`reference_01` → 1). | Trivial |
| `agency`, `site_id` | **Yes** | Only used to build the canonical filename internally. Derive `site_id` from the site key (first 3 chars, uppercased); `agency` from one global institution setting. | Trivial |
| `recipe fields:` | **Mostly** | Sample N filenames → try `BUILTIN_PATTERNS`. On miss: interactive wizard that highlights filename segments and asks which part is the day/year/hour. | 2–3 days |
| `source_station` | **Semi** | Auto-learn dominant 4-char code per directory; only require explicit value when two codes coexist. | 0.5 day |

**Confirmed from previous session:** working minimal config requires only `receiver_number` + `type` + `directory` — nothing else is load-bearing. The remaining `ReceiverNamingConfig` fields should all become auto-detected or optional expert overrides.

### Canonical name exposure

The canonical name (`CanVODFilename`, convention.py:109) is a database key. Users never type one and never need to read one. It must be **fully hidden at every user boundary**: errors should say "data from receiver canopy_01 covering 1 Jan 2025, 00:15–00:30", never `ROSA01TUW_R_20250010015_15M_05S_AA.rnx`. Only current exposures: `sample_canonical_names` in validation output (tasks.py:432, 540–542) and error messages — both fixable presentation layers.

### Proposed scientist-facing config

```yaml
sites:
  rosalia:
    data_folder: /data/gnss/rosalia
    latitude: 47.7
    longitude: 16.3

    receivers:
      reference_01:
        role: above canopy          # was: type: reference
        folder: 01_reference        # subfolder with this receiver's files
        # canvodpy figures out file format, folder structure, and naming automatically

      canopy_01:
        role: below canopy          # was: type: canopy
        folder: 02_canopy
        station_code: ract          # ONLY if two receivers share one folder

    compare:
      - below: canopy_01
        above: reference_01
```

Plus one pre-run command: `canvod check rosalia` that prints in plain language:
```
rosalia / canopy_01 (/data/gnss/rosalia/02_canopy)
  Found 412 data files — Septentrio RINEX (15-min files, 5-sec sampling)
  Folder structure: day folders like 25001/ (year 2025, day 001)
  Coverage: 1 Jan 2025 – 14 Mar 2025, no gaps, no double-counted periods
  Ignored 3 non-data files: notes.txt, receiver_log.old, .DS_Store
```

### Error message redesign

**Unmatched files** (validator.py:137–147):
> Current: `3 file(s) could not be mapped to canonical names`
> Proposed: `I don't recognise 3 files as GNSS data: session_notes.txt (not a GNSS file), ract001a15.25o.bak (looks like a backup — move it out). If they ARE data files, run "canvod identify /data/…" and I'll walk you through describing the filenames.`

**Temporal overlap** (validator.py:150–157):
> Current: `ROSA01TUW_R_20250010000_01D_05S_AA.rnx overlaps ROSA01TUW_R_20250010015_15M_05S_AA.rnx`
> Proposed: `Two files cover the same time: rosl0010.25o (all of 1 Jan 2025) and ract001a15.25o (1 Jan 2025, 00:15–00:30). Keep EITHER the daily file OR the 15-minute files for that day — not both.`

**Zero files found** (must become a hard failure, not "valid"):
> Proposed: `No data files found in /data/rosalia/02_canopy. Check that 'folder: 02_canopy' points at the folder containing your receiver files.`

**Missing recipe** (tasks.py:341–346, currently points to nonexistent command):
> Proposed: `canvodpy hasn't learned the filename style for receiver "reference_01" yet. Run: canvod identify rosalia reference_01 — this looks at your files and sets everything up automatically.`

### Implementation plan (revised — reflects split decision above)

**~~Phase 1 — create `canvod-preflight` package (~2 days):~~ DONE (2026-07-08)**
1. ~~New workspace package `packages/canvod-preflight/`.~~ **DONE** — exists with `convention.py`, `validator.py`, `mapping.py`, `config_models.py`, `patterns.py`, `cli.py`.
2. ~~Move `convention.py`, `validator.py`, `catalog.py` out of `canvod-virtualiconvname`.~~ **DONE** (note: `catalog.py` was NOT moved — still in virtualiconvname only).
3. ~~Fix `ValidationReport.is_valid` (validator.py:37–40): fail hard on zero matched files.~~ **DONE** — zero-match guard at `canvod-preflight/validator.py:52`.
4. Rewrite `_format_validation_error()` using plain-language templates. ← **still open**
5. ~~Standalone CLI entry point.~~ **DONE** — `canvod-preflight validate` via typer in `cli.py`.

**Phase 2 — harden remaining `canvod-virtualiconvname`/`canvod-filemap` (~1 day)
— DE-PRIORITIZED (2026-07-08):** scope decision in §3 — `canvod-filemap` is an
admitted escape hatch for non-conforming filenames, not a feature to polish. Items
below stay open but are no longer worth pulling forward; fine to leave rough.
6. Remove the moved files from virtualiconvname; add `canvod-preflight` as an explicit dependency. ← **still open** (convention.py/validator.py still duplicated in both packages)
7. ~~Log every file skipped by `discover_all/discover_for_date` (mapping.py:145–146, 178–179).~~ **DONE** — `logger.warning()` at lines 149 and 183.
8. Port `detect_overlaps()` into recipe validation path (tasks.py:402–407) — equal guardrails on both paths. ← **still open**
9. ~~Remove phantom `just naming-init` reference (tasks.py:344); add `config/recipes/` with 2 commented examples.~~
   **DONE (2026-07-09):** found in practice on a real deployment — `config validate`
   pointed a user at `just naming-init rosalia_reference`, which didn't exist,
   exactly as flagged here. Implemented for real: `just naming-init <name>`
   scaffolds `config/recipes/<name>.yaml` from `config/recipes/_template.yaml.example`
   (substitutes `name:` and infers `receiver_type` from `canopy` appearing in the
   recipe name), refuses to clobber an existing recipe, and prints next steps.
   The template embeds two worked examples as comments (RINEX short-name
   hour-letter style, and an arbitrary `STATION_YYYY_DDD_HH_MM` style) rather
   than shipping as two separate files — verified end-to-end: a filled-in
   copy of the template validates against `NamingRecipe` and correctly parses
   a real filename.
10. Document the manual integration hook in the package README. ← **still open**

**Phase 3 — `canvod-preflight` new checks (~2 days):**
11. RINEX header peek: open first few KB, parse `SYS / # / OBS TYPES` and `INTERVAL`, compare against filename-declared sampling and period.
12. Gap detection: given a date range, report missing days in plain language.
13. Expand CLI to produce the full plain-language report shown in "Proposed scientist-facing config" section above.

**Files touched:** new `packages/canvod-preflight/`, updated `packages/canvod-virtualiconvname/` (remove moved files, add dep), `canvodpy/src/canvodpy/workflows/tasks.py` (import updates), root `pyproject.toml` (new workspace member).

---

## 14. Visual design language — Rich/Textual aesthetic spec

**Context (2026-07-05):** Agreed design direction: clean, modern, instrument-like.
No emoji (render inconsistently, look cheap). All marks are plain Unicode or ASCII.
Nordic Green palette from `docs/assets/canvod-nordic.css` carried into the terminal.

**Correction (2026-07-14):** verified directly against `cli/dashboard.py` — the
live multi-row per-(site, receiver) progress display this section's "Target
progress layout" describes **already exists and is live**
(`RichReporter._task_ids: dict[(site, group), TaskID]`, one `Progress` task
per receiver, advanced via the `on_group_written` callback wired in
`cli/run.py`, all rendered together in one shared `Live(Group(...))` region).
The header mark (`─[◉]─`) and `green3`/`dim green` palette are also already
implemented, not just documented. What's genuinely still open is narrower
than this section implies: just the per-row glyph styling (◉ active / ◎
waiting / ● done, `▸ stage` labels) — cosmetic, not structural. Deprioritized
per 2026-07-14 discussion: revisit only if the current dashboard proves
insufficient in practice, not worth building preemptively.

### Symbol system

| Context | Symbol | Meaning |
|---|---|---|
| Header / brand mark | `─[◉]─` | Satellite with solar panels — appears once in run header only |
| Active task | `◉` | Receiver currently computing |
| Waiting / queued | `◎` | Receiver waiting to start |
| Complete | `●` | Finished — row goes dim immediately after |
| Step arrow | `▸` | Prefixes current stage label (`▸ Augmenting ephemeris`) |
| Inline divider | `─` | Separators in single-line contexts |

Progress bars use Rich's `━` (thick fill) character — not the default `█` — for a
lighter weight that matches the symbol set.

### ASCII art header (startup banner, shown once per run)

Placeholder until the full logo is designed (see §15):

```
  ─[◉]─  canvod  v0.x.x
   |||   GNSS-T Vegetation Pipeline
```

Rendered as `Panel(..., box=ROUNDED, border_style="dim green")`.
Two lines, no more. Suppressed in `--no-progress` / non-TTY mode.

### Colour palette (Rich style names — no other colours)

| Role | Rich style | Use |
|---|---|---|
| Progress fill (active) | `green3` | Bar fill while running |
| Progress fill (done) | `dim green` | Bar fill after completion |
| Completed row text | `dim` | Entire row dims on finish |
| Header / panel border | `dim green` | Panel border |
| Stage label | `bold` | Current stage name |
| Warning | `yellow` | Non-fatal (e.g. overwrite strategy warn) |
| Error header | `bold red` | ValidationError table header only |

Background stays terminal-default. No forced dark/light mode.

### Target progress layout (§11 Phase 3)

```
╭──────────────────────────────────────────────────────╮
│  ─[◉]─  canvod · ROSA · 2025-003 · day 3 of 28      │
╰──────────────────────────────────────────────────────╯

  ◉ canopy_01     ▸ Augmenting ephemeris  ━━━━━━━━━░░  80%  0:12
  ◎ reference_01  ▸ Augmenting ephemeris  ━━━━━━━━━━━  done
  · vod_01        ▸ Computing VOD         ━━━━━━░░░░░  55%  0:06

  Overall  ━━━━━━━━░░░░░░░░░░░  3/28 days  elapsed 0:54
```

`Live(Group(header_panel, receiver_progress, overall_progress))`.
`SpinnerColumn(spinner_name="dots")` on active rows; removed on completion.

### Rich column config (reference for implementation in `cli/dashboard.py`)

```python
from rich.progress import (
    BarColumn, MofNCompleteColumn, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn,
    TimeRemainingColumn,
)

receiver_columns = [
    TextColumn("{task.fields[symbol]} {task.fields[name]:<16}"),
    TextColumn("▸ {task.fields[stage]:<28}"),
    BarColumn(bar_width=None, complete_style="green3",
              finished_style="dim green"),
    TaskProgressColumn(),
    TimeRemainingColumn(),
]

overall_columns = [
    TextColumn("  Overall"),
    BarColumn(bar_width=None, complete_style="green3",
              finished_style="dim green"),
    MofNCompleteColumn(),
    TextColumn("days  elapsed"),
    TimeElapsedColumn(),
]
```

### ValidationError renderer layout (§11 Phase 0 / §10 item 4)

```
╭─ Config error — config/sites.yaml ──────────────────╮
│  Field                          Problem       Got    │
│  sites.rosalia.receivers                            │
│  .canopy_01.scs_from            not allowed  canopy  │
│  storage.stores_root_dir        must be set  (none)  │
╰──────────────────────────────────────────────────────╯
```

`Panel` with `border_style="bold red"`, body plain white.
One table row per Pydantic `ValidationError.errors()` entry.
No raw Python tracebacks surfaced to the user.

---

## 15. ASCII logo (deferred design task)

Design a proper multi-line ASCII art logo to replace the `─[◉]─` placeholder
header. This is a creative task — do it once the CLI is stable so the logo
doesn't predate the UX it decorates.

**Requirements:**
- 4–6 lines tall, ~40 chars wide — fits an 80-col terminal cleanly
- Works in monochrome (no colour dependency)
- Domain legible without labels: satellite + signal or vegetation theme
- The inline `─[◉]─` mark remains in progress rows; this logo is startup-only

**Candidates to explore:**

```
  ═[◉]═         /\  ─[◉]─      ─[◉]─
    |           /  \   |          |
   /|\           ||  ─ · ─      ~/ \~
    |            |              ~ · ~
  option A   option B        option C
 (satellite)  (sat+tree)    (sat+signal)
```

**Process:** sketch candidates in `dev/ux/logo-candidates.txt`, render each
inside a Rich `Panel` at real terminal width (80 and 120 cols), pick the one
that holds up at both widths. Then commit as a constant in a new
`canvod.utils.branding` module so every CLI entry point imports the same mark.

---

## 16. ~~pydantic-settings: 12-factor config resolution~~ — DONE (2026-07-08)

**Context:** §11 identifies "no general CLI > env > user-yaml > defaults story"
as a pain point and proposes Option B (single `canvod-settings.yaml`). `pydantic-settings`
is the concrete mechanism that implements Option B's resolution order with
minimal code.

**What it adds over bare Pydantic:**
- `ProcessingConfig(BaseSettings)` instead of `BaseModel` — env vars override
  YAML automatically with zero custom parsing.
- Resolution order (standard 12-factor):
  `env vars → .env file → canvod-settings.yaml → defaults/canvod-settings.yaml`
- Nested override via double-underscore separator:
  `CANVOD__STORAGE__STORES_ROOT_DIR=/nfs/stores canvodpy run --site rosalia`
- `.env` file support: scientists keep a per-machine `.env` (gitignored) for
  paths and credentials; the committed `canvod-settings.yaml` stays portable.
- HPC/cloud/n8n deployment: pipeline step sets env vars, no config file needed
  on the compute node — directly enables the n8n/Airflow integration track (§4).

**DONE (verified 2026-07-08):** `CanvodConfig(BaseSettings)` with `settings_customise_sources()` at `models.py:1087`. `pydantic_settings` imported at `models.py:25`.

~~**Migration:** `BaseModel` → `BaseSettings` on `ProcessingConfig` and the new
unified `CanvodConfig`. Add `settings_customise_sources()` to insert two YAML
sources (defaults then user file) below env vars. `pydantic-settings` ships
with pydantic v2 — no new dependency in practice.~~

**Effort:** ~1 day (base class swap + source registration + env var tests).
Sequence after §11 Phase 2 (single `canvod-settings.yaml` must exist before env var
overrides of it make sense).

**Files:** `packages/canvod-utils/src/canvod/utils/config/models.py` (base
class swap); `packages/canvod-utils/src/canvod/utils/config/loader.py`
(source registration); `packages/canvod-utils/pyproject.toml` (add
`pydantic-settings` dep if not already pulled in by pydantic v2 extras).

---

## 17. `canvodpy-demo` submodule — update for API-level deprecation + CLI-first — DONE (2026-07-08)

**Context (2026-07-08):** follows this session's API-level cleanup (§4 open
questions). `FluentWorkflow`, the flat `process_date()`/`calculate_vod()`/
`preview_processing()` convenience functions, and `VODWorkflow` are now deprecated
with `DeprecationWarning`. CLI (wrapping `Site.pipeline()`) is the recommended way
to run the pipeline; `canvodpy.functional` is the recommended Python surface for
component-level scripting/analysis. The demo submodule (`demo/` in this repo,
`github.com/nfb2021/canvodpy-demo`, checked out locally at
`/Users/work/Developer/GNSS/canvodpy-demo`) predates this decision and needs to
catch up.

**Current demo files (marimo notebooks, numbered):**
`01_naming_convention.py` … `11_configuration.py`, `12_api_overview.py`,
`13_api_level1_convenience.py`, `14_api_level2_fluent.py`,
`15_api_level3_site_pipeline.py`, `16_api_level4_functional.py`,
`17_workflow_single_day.py` … `20_grid_exploration.py`.

**Also found (2026-07-08):** `docs/notebooks/index.md` references a
`00_convenience_speedrun.py` notebook that does **not exist** in the current
`canvodpy-demo` checkout (`/Users/work/Developer/GNSS/canvodpy-demo`, `main`
branch) — a pre-existing docs/repo drift, unrelated to this session's changes.
Resolve during this task: either the notebook was deleted and the docs table
needs to drop the row, or it needs to be recreated. `docs/notebooks/index.md`
has been updated in the meantime to mark rows 13/14 as deprecated without
renumbering, since the underlying files still exist under their current names.

**Tasks:**
1. **Remove** demos for deprecated surfaces: `13_api_level1_convenience.py`,
   `14_api_level2_fluent.py`. Check whether `VODWorkflow` is demonstrated inside
   `12_api_overview.py` or elsewhere (no dedicated numbered file found) and remove
   that too.
2. **Rename/renumber** remaining demos to close the gap left by the removals, and
   update `12_api_overview.py` to describe only the two supported surfaces (CLI +
   `Site.pipeline()` for running, `canvodpy.functional` for scripting/analysis) —
   don't just delete two files and leave a numbering hole.
3. **Verify all demos still run** end-to-end (marimo notebooks) — some may already
   be stale; this is also an opportunity to catch drift before adding new content.
4. **Add a new CLI demo** — there is currently no demo showcasing `canvodpy run`
   (or whatever the CLI entry point resolves to) from the shell. Should cover a
   basic run and, once available, the resume-from-interruption behavior (see
   §4's CLI flag/ephemeris-choice follow-up work, still in progress).

**Depends on:** finishing the docs/CLAUDE.md API-levels table updates and the CLI
ephemeris/calculator flag work (§4 follow-ups) first, so the demo doesn't document
a CLI surface that's still mid-change.

**Resolution (2026-07-08):** all four tasks done in the local `canvodpy-demo`
checkout, commit `6f5ba32` on `main` — **not yet pushed to `origin/main`**
(explicit user decision, pending thumbnail regeneration).
1. Removed `13_api_level1_convenience.py`, `14_api_level2_fluent.py` (pure
   documentation notebooks, no live code — confirmed no `VODWorkflow` demo
   existed anywhere either).
2. Renumbered: `15_api_level3_site_pipeline.py` → `14_site_pipeline.py` (content
   reframed to lead with `Site.pipeline().process_range()`, not just
   `VodComputer`), `16_api_level4_functional.py` → `15_functional_api.py`,
   `17`–`20` (workflow/grid) shift down to `16`–`19`. `12_api_overview.py`
   rewritten for the 3-surface model (CLI, `Site.pipeline()`, functional).
   All footer/cross-reference links fixed repo-wide (verified via grep, zero
   dangling references).
3. All touched notebooks verified via `ast.parse` (syntax) and `uv run
   <file>.py` (each notebook's own PEP 723 header pins deps — all exited 0,
   no exceptions).
4. New `13_cli_pipeline.py`: basic usage, auto-resume, multi-site, the
   `--ephemeris-source`/`--vod-calculator` flags, resource flags, config
   overlay.

`README.md`/`PUBLISHING.md` notebook tables updated in the demo repo;
`docs/notebooks/index.md` in this repo updated to match (zensical build
clean). **Two follow-ups before/at push time:** (a) push `6f5ba32` to
`origin/main`, (b) regenerate molab thumbnails for the renamed/new notebooks
per `PUBLISHING.md` Step 4 (`uv run marimo export thumbnail ./`) — old
thumbnails are keyed by the old filename stems and won't exist for
`13_cli_pipeline.py` or match the renamed files.

---

## 18. ~~Multi-process logging race~~ — FIXED 2026-07-08

**Fix:** option 3 from the candidates below — per-process log filenames.
`_process_log_suffix()` in `logging_config.py` returns `""` for the main
process (unchanged filenames, fully backwards compatible) and `.{pid}` for
any other process. Every handler's filename (`full{suffix}.json`,
`main{suffix}.log`, `errors{suffix}.log`, `performance{suffix}.json`,
`{component}{suffix}.log`) now includes it, so concurrent loky workers never
share a physical path — the `os.rename()` race in `doRollover()` is
structurally impossible, not just less likely. No log content is dropped or
silenced (rejected option 1/4); no new dependency (rejected option 2).
Trade-off accepted: `machine/full.json` is now fragmented per worker PID
during a run with active parallelism — a `full*.json` glob is needed for
full-run analysis instead of a single file (matches what the log-analysis
work in this same session already did for rotated `.1`–`.10` files).

**Also removed** the `HANDLER 9: Legacy compatibility` file handler (writing
to the raw `logfile` path, i.e. `canvodpy.log`) — it duplicated
`machine/full.json`'s content with no remaining consumer and was already
tagged `# Remove this after migration`; no reason to also suffix a dead
handler.

Verified with a real `ProcessPoolExecutor` run: main process wrote
unsuffixed files, each of 2 workers wrote its own `*.{pid}.*` set, zero
collisions.

**Found 2026-07-08**, live production run on the remote processing machine, under
`days_per_batch=14`. Non-fatal (Python's `logging` module catches handler `emit()`
failures and prints `--- Logging error ---` rather than propagating — confirmed the
pipeline kept running, "Overall" bar continued advancing), but noisy and a latent
data-integrity risk.

**Symptom:**
```
FileNotFoundError: [Errno 2] No such file or directory:
  '.../.logs/machine/full.json' -> '.../.logs/machine/full.json.1'
```
raised from `logging/handlers.py:doRollover() -> rotate() -> os.rename()`, inside a
loky worker process (call stack: `loky/process_executor.py:_process_worker` →
`processor.py:290 log.debug("computing_spherical_coordinates")` → structlog →
stdlib logging → `RotatingFileHandler.emit()`).

**Root cause:** `canvodpy/src/canvodpy/logging/logging_config.py:420` —
`LOGGER = configure_logging()` runs at **module import time**, at global scope.
Every loky worker process re-imports this module when it spawns and independently
re-runs `configure_logging()`, which creates 9 file handlers
(`RotatingFileHandler`/`TimedRotatingFileHandler`) all pointing at the *same*
physical paths under `.logs/` (`machine/full.json`, `human/main.log`,
`human/errors.log`, `machine/performance.json`, 3× `component/*.log`, legacy
`canvodpy.log`). `RotatingFileHandler` is only safe within a single process (its
lock is a `threading.RLock`, not cross-process) — when the shared file crosses its
size threshold, multiple worker processes can decide to rotate simultaneously and
race on `os.rename()`. Whichever loses finds the source already renamed away by the
winner. This isn't limited to the one handler that happened to fire in the observed
traceback — all 9 registered handlers share the same exposure whenever multiple
processes are alive and the threshold is crossed mid-run.

**Candidate fixes (tradeoffs, no single obviously-right answer — needs a decision,
not a unilateral pick):**
1. **Skip file-handler setup in worker processes.** Guard `configure_logging()`
   (or its call site) to detect a non-main process (e.g.
   `multiprocessing.current_process().name != "MainProcess"`, or check for the
   loky/ProcessPoolExecutor worker context) and have workers log to stderr/null
   only, or forward records to the main process via `logging.handlers.QueueHandler`
   + `QueueListener` (stdlib, no new dependency, but requires plumbing a
   multiprocessing-safe queue through to every worker).
2. **Process-safe rotating handler.** Swap `RotatingFileHandler`/
   `TimedRotatingFileHandler` for a library that uses file locking across processes
   (e.g. `concurrent-log-handler`'s `ConcurrentRotatingFileHandler`) — new
   dependency, but a drop-in replacement with minimal code change.
3. **Per-process log files.** Include PID (or loky worker ID) in each handler's
   filename, eliminating the shared-path race entirely — but fragments
   `machine/full.json` (meant to be "complete JSON logs for analysis" in one place)
   across many files, needing a separate aggregation/merge step to read "the full
   log" as originally intended.
4. **Reduce worker-process verbosity.** Cheap mitigation, not a real fix: workers
   currently log at DEBUG (`log.debug("computing_spherical_coordinates")` etc.) —
   dropping worker-process handlers to WARNING would reduce volume and therefore
   how often the 100MB threshold gets crossed mid-run, lowering race likelihood
   without eliminating the underlying multi-process-unsafe pattern.

**Needed:** a decision on which fix (or combination) to pursue before implementing —
flagging here rather than picking one, since #1 and #2 have real cost (dependency or
plumbing) and #3/#4 are partial mitigations, not fixes.

---

## 19. ~~Chunk-size misalignment on the Rosalia store~~ — root cause + fix documented (2026-07-13)

**Found 2026-07-08**, analyzing performance logs from the remote processing
machine's live backfill run (`dev/*.md` log analysis, not a code investigation).
The Icechunk write step (`_append_to_icechunk` → `session.commit()`) was taking
17-19s per receiver-group-day — by far the dominant cost in the run (~63% of
total wall-clock across the sampled batches).

**Root cause:** `epoch` chunk size defaults to `34560`
(`packages/canvod-utils/src/canvod/utils/config/models.py:419,459-460,486,490`;
`packages/canvod-store/src/canvod/store/store.py:626,1237`), which the
docstring explicitly says is tuned for **2.5s sampling** (86400s/day ÷ 2.5s =
34560). Rosalia samples at **5s**, so one real day = 17280 epochs — exactly
half the configured chunk size. Every daily write lands mid-chunk, forcing a
read-modify-write of the whole 2-day chunk instead of a clean append — this
matches icechunk's own documented "chunk-unaligned writes" limitation
(confirmed via web search against icechunk's FAQ). General principle: chunk
size (append dim) should equal the write granularity — for this pipeline,
that's always one calendar day, since `append_to_group()` commits once per
receiver-group per day regardless of `days_per_batch`. Formula:
`epoch_chunk_size = 86400 / site_sampling_interval_seconds`. Not a universal
constant — every site should be set to match its own sampling rate.

**Config-only fix does NOT work retroactively.** Confirmed by reading
`write_initial_group()`/`append_to_group()`: chunk shape is set once, at a
group's first-ever write (`write_initial_group`, `to_icechunk(..., mode="w")`,
no explicit `chunks=` — inherited from whatever the incoming dataset was
already rechunked to via `self.chunk_strategy` at store-construction time).
Every subsequent `append_to_group()` call passes no `chunks=` at all — it just
extends the array using whatever grid was established on the first write.
Changing the config and restarting the pipeline has **zero effect** on
already-existing groups; it only applies to brand-new groups/stores. The
existing 4 Rosalia groups (`canopy_01`, `canopy_02`, `reference_01_canopy_01`,
`reference_01_canopy_02`) need an actual migration.

**`rechunk_group()` (`packages/canvod-store/src/canvod/store/store.py`) was
broken for its stated purpose** — found via new test coverage
(`packages/canvod-store/tests/test_rechunk.py`, zero prior tests existed).
Original implementation used `mode="r+"` to preserve the group's nested
`metadata/` subtree (file registry table, `sbf_obs`), but `mode="r+"` writes
into the array's *existing* chunk grid — verified empirically that it cannot
actually change chunk boundaries (Zarr arrays have immutable chunk shape once
created). The previous author's exact tradeoff (`r+` to avoid losing
metadata) is confirmed real: `mode="w"` does wipe the nested `metadata/`
subtree, reproduced directly in a debug script.

**Fixed** by combining the destructive-but-correct path (`mode="w"`, which
actually changes chunk shape) with a recursive raw-Zarr copy of the wiped
subtree, restored on the same temp branch before promotion — generalizing a
fix already applied once before in `gnssvodpy`
(`gnssvodpy/src/gnssvodpy/icechunk_manager/store.py:1457`,
`rechunk_group_verbose`, found via `/Users/work/rechunk.py`), which only
copied one level of subgroup depth; canvod-store's layout nests
`metadata/{table,sbf_obs}` two levels deep, so the fix here
(`_copy_zarr_subtree`) is properly recursive. Also pins the whole operation to
the exact snapshot captured at the start (`repo.readonly_session(snapshot_id=
current_snapshot)`, not `branch=source_branch`), so it stays safe even if
`source_branch` advances concurrently — anything committed after the rechunk
started is simply not part of the migration, not silently discarded. Verified
by `packages/canvod-store/tests/test_rechunk.py` (6 tests: metadata table
survives, root attrs survive, data values byte-identical, chunk size actually
changes, sibling groups untouched, `promote_to_main=False` correctly leaves
`main` alone) — all passing, including against a real column-order/flaky
false-failure in the metadata comparison that got caught and fixed along the
way (sort by unique `rinex_hash` key, not all columns).

**Decision (2026-07-08): no periodic rechunking.** Considered "day-aligned
during ingestion, periodically consolidate to something bigger for reads"
(mirrors gnssvodpy's `rechunk.py`, which ran rechunks periodically) — rejected
because the actual read pattern here is single-day/single-week windows, which
day-aligned chunks already serve well; consolidating to bigger chunks would
only help genuine bulk/seasonal reads (not the case here) while reintroducing
the exact write-side merge cost being fixed, since write granularity stays
per-day regardless of chunk size chosen. Fix the chunk size once, correctly;
`rechunk_group()` is a one-time migration tool, not a recurring maintenance
job. Also worth remembering if this ever changes: `rechunk_group()` isn't
currently safe to run concurrently with active ingestion into the same group
(pinned-snapshot + branch-reset would silently discard anything committed
during the rechunk window) — fine for a one-time migration with the pipeline
stopped first, but would need a "detect branch moved, abort" guard before ever
becoming a recurring/automated job.

**Rechunk NOT needed before one-off analysis reads (2026-07-09).** The
misalignment above is a write-amplification problem (daily appends forcing
read-modify-write of a straddling chunk) — it does not force a rechunk
before a bulk read-and-aggregate pass like a VOD timeseries plot. Reading
the whole store once touches every chunk regardless of how they're cut;
an oversized-but-uniform epoch chunk just means slightly more data pulled
per fetch, not a correctness or major performance problem. The one thing
that *would* matter for reads: if the RMW churn during backfill left the
store with many small, irregular chunks (fragmented) rather than a uniform
oversized grid — that's a genuinely different failure mode from "just
bigger than a day" and worth a quick check first. `dev/plot_galileo_vod_timeseries.py`
includes a chunk-layout diagnostic cell for exactly this (reports actual
on-disk epoch chunk sizes/counts before running the full aggregation).

**RESOLVED (2026-07-13) — repurposed per user direction: turned into
permanent documentation instead of a one-off remote-migration checklist**
(the actual remote-store migration on Rosalia is outside this repo's
tracking — not verifiable from here either way). Added two things a
future site setup needs to know, so this doesn't have to be rediscovered
per-site:
1. `docs/packages/store/icechunk.md`'s "Chunk Strategy" section now has a
   warning box with the general formula (`epoch_chunk_size = 86400 s/day ÷
   sampling_interval_seconds`, equivalently `× logging_rate_hz`), the
   write-amplification consequence of getting it wrong, and the
   fixed-at-first-write / needs-`rechunk_group()`-to-change caveat.
2. `docs/guides/parallel-processing.md`'s loky section now has a note that
   the first minute or two of a run can look idle — one-time per-worker
   setup (dependency imports, database/index creation) happens once per
   worker lifetime, not per file/day, and isn't a hang.

The 4-step remote-migration checklist (stop pipeline, set `epoch=17280`,
`rechunk_group()`, verify, resume) is still the right recipe *if and when*
that specific migration needs doing — just no longer tracked here as a
pending action, since whether it happened lives on the remote machine, not
in this repo.

## 20. ~~Pre-existing test failures (18)~~ — RESOLVED 2026-07-13

**Found** while verifying `canvod-virtualiconvname` removal, 2026-07-09.
**Resolved** 2026-07-13 — re-verified all 18 still reproduced exactly as
catalogued (moved locations aside: `test_config_loader.py` now lives in
`canvod-config`, per the split), then root-caused all three clusters. Two
were genuine bugs, not just stale tests:

1. **`canvod-config/tests/test_config_loader.py`** (4 failures) — pure test
   staleness, no code bug. Tests still wrote the old 3-file config format
   (`processing.yaml`/`sites.yaml`/`sids.yaml`) and mocked a `_load_sids`
   method that no longer exists — `ConfigLoader` was correctly redesigned
   around the unified `canvod-settings.yaml`, tests just never got updated.
   **Fixed**: rewrote all 4 to use the unified file; split
   `test_missing_user_config_uses_defaults` into two accurate tests since
   the old single-test premise ("missing files silently default") is now
   two different real behaviors — `test_missing_settings_file_raises_file_not_found`
   (the file itself must exist, by design) and
   `test_omitted_sections_use_package_defaults` (individual *sections*
   within an existing file still default correctly, but `metadata` must
   always be supplied — the package defaults for author/email are
   themselves rejected sentinel placeholders, by design).

2. **`canvod-readers/tests/test_builder.py`** (13 failures) — **real bug**.
   `REQUIRED_ATTRS` (`base.py`) requires `"Institution"`, but
   `get_global_attrs()`'s fallback when `load_config()` fails was just
   `{"Software": "canVODpy"}` — missing `Institution`, so dataset
   construction always failed validation in any environment without a
   working config (standalone installs — the exact scenario the earlier
   §10 fix was supposed to enable — and, it turns out, this test suite too,
   since `ConfigLoader` now requires `canvod-settings.yaml` to exist).
   **Fixed**: fallback now includes `"Institution": "Unknown"` — a
   recognizable placeholder, not a value that could be mistaken for real
   FAIR/DataCite metadata downstream.

3. **`canvod-store/tests/test_store_crud.py::test_create_rinex_store`**
   (1 failure) — **real bug**, bigger than the test. `create_rinex_store()`
   hardcoded `store_type="gnss_store"`, but the actual production code
   (`processor.py`, `store_metadata/collectors.py`, `viewer.py`, `store.py`'s
   own write-strategy check) all use `"rinex_store"`. Tracing the actual
   impact: `chunk_strategies` config (see §19) was keyed `"gnss_store"` in
   both the Pydantic default and every YAML template, so it silently never
   resolved for `"rinex_store"`-typed stores — `self.chunk_strategy` was
   always `{}`. This had already caused one real production incident:
   `canvod-store/tests/test_rechunk.py`'s docstring documents a 2026-07-08
   finding of exactly this misalignment on the Rosalia store, mitigated
   with `rechunk_group()` at the time but never fixed at the root.
   **Fixed**: renamed to `"rinex_store"` everywhere (the class docstring,
   `__init__` default, `create_rinex_store()`, `canvodpy/cli/store.py`'s
   local var, and the `chunk_strategies` config key in both
   `compression.py`'s `default_factory` and all 3 YAML templates).

   **While fixing this, found and fixed a second, unrelated bug in the same
   area**: the default `epoch` chunk size was `34560`, justified by two
   *contradicting* comments (my own §19 doc claimed "24h at 2.5s cadence";
   the YAML template claimed "2 days of 5s data" — both explain the same
   number, but assume different sampling rates and day-counts). Given
   `append_to_group()` commits once per day, chunks must equal exactly one
   day's epochs — the "2 days" framing was simply wrong. Rosalia (the
   reference site this default is tuned around) samples at 5s, so the
   correct 1-day value is `86400 ÷ 5 = 17280`, not `34560`. **Fixed
   everywhere**: `ChunkStrategy`'s own field default, the `chunk_strategies`
   `default_factory`, `manifest_splitting_epoch_range`'s default +
   description, all 3 YAML templates + this repo's local
   `canvod-settings.yaml`, `VodComputer`'s `_rechunk` default, `cli/run.py`'s
   hardcoded VOD rechunk, `store.py`'s 2 read-path fallback literals, and
   6 docs files (`icechunk.md`, `configuration.md`,
   `packages/config/overview.md`, `packages/store/overview.md`) plus their
   corresponding tests. Existing stores created with the old `34560` default
   are unaffected (chunk shape is fixed at first write) — only new stores
   pick up the corrected value.

Full regression: `pytest -m "not integration"` — no new failures beyond a
pre-existing, unrelated local issue (this repo's own `config/canvod-settings.yaml`
has placeholder `author: Your Name` / `email: your.email@example.com`,
confirmed via `git stash` to predate all of today's changes — not something
to fix here, it's local dev-environment config, not shipped code).

## 21. ~~`canvod-utils/diagnostics/` is a dead chain, superseded by OpenTelemetry~~ — DELETED 2026-07-14

**Found 2026-07-09**, while scoping the `canvod-config` extraction (checking
what else lives in `canvod-utils` besides `config/`).

`canvod-utils/diagnostics/` (1187 lines: `timing.py`, `memory.py`,
`dataset.py`, `airflow.py`, `retry.py`, `_store.py` — a homegrown
timing/memory/dataset-quality/Airflow-metrics toolkit with an optional
SQLite-backed metrics store) has exactly **one** consumer anywhere in the
repo: `canvodpy/utils/perf.py`, which is a pure re-export shim (`"""Re-exports
from canvod.utils.diagnostics ... the canonical implementation lives in
canvod-utils so all workspace packages can use it."""`). That shim is in turn
only re-exported again by `canvodpy/utils/__init__.py`. **Nothing imports
either re-export layer** — confirmed via repo-wide grep for
`canvodpy.utils.perf`/`canvodpy.utils.<symbol>`. Three layers deep, zero real
callers.

The actual, live telemetry system is a completely separate one:
`canvodpy/utils/telemetry.py` (OpenTelemetry-based traces/metrics), actively
imported by `canvod-store/store.py` (`trace_icechunk_write`) and
`canvodpy/orchestrator/processor.py` (`trace_rinex_processing`). So there are
two parallel diagnostics systems — one dead, one live — same shape as the
`canvod-virtualiconvname`/`canvod-preflight`/`canvod-filemap` situation
resolved above (see §12 history).

**Airflow-specific angle, checked per explicit request:** `diagnostics/airflow.py`
(`TaskMetrics`/`task_metrics`, designed to push to Airflow XCom + StatsD) has
zero consumers — confirmed the two real DAGs in this repo
(`dags/gnss_daily_processing.py`, `dags/gnss_backfill.py`) don't import it
either, so it's disconnected even from the one place it's explicitly designed
for. This matters for the Airflow outsourcing — **done as of 2026-07-10,
`54db8617`:** the DAGs moved to `canvodpy-extensions/packages/canvod-airflow`
(confirmed `canvod-airflow` is the actual name, not `canvod-pipeline-orchestration`);
`dags/gnss_daily_processing.py`/`dags/gnss_backfill.py` and this repo's own
`docs/guides/airflow.md` were deleted here, see `docs/guides/extensions.md` for
the install path. `diagnostics/airflow.py` stayed behind in `canvod-utils`, so
the exact risk flagged below is now live, not hypothetical — if
`canvod-airflow` ever wants `TaskMetrics`, it needs a narrow dependency back
into the main monorepo, the same cross-repo split problem already hit once
with naming-convention code. Since it has zero consumers today, this is the
cheap moment to decide, before it accretes real callers: either move
`airflow.py` to live with `canvod-airflow`, or delete it outright and rebuild
simple Airflow instrumentation directly in that package if/when actually
needed (OpenTelemetry's `telemetry.py` may already cover the real need —
worth checking before rebuilding anything).

**Cross-referenced 2026-07-09** into `dev/airflow_extraction_plan.md` (§0.1 and
O8): confirmed `diagnostics/airflow.py` is not imported by either DAG file
being migrated in that plan, so `diagnostics/` stays in `canvod-utils` for
that extraction — resolving the open question there without blocking on this
cleanup.

**Resolved 2026-07-14:** chose (a) — deleted the whole dead chain rather than
filing a GitHub issue first (user opted to skip that formality since it was
fully confirmed dead). Removed `canvod-utils/diagnostics/` (all 7 files +
`grafana_dashboard.json`), `canvodpy/utils/perf.py`, and both re-export
layers (`canvodpy/utils/__init__.py`, `canvod-utils/__init__.py`). Also found
and removed two now-orphaned dependencies in `canvod-utils/pyproject.toml`
that existed only to support the deleted `retry.py`/logging in the dead
modules: `tenacity` and `structlog` (neither had any remaining import in the
package — verified via grep before removing, not assumed). `structlog`
remains correctly declared as its own independent dependency in the 6 other
packages that actually use it (`canvodpy`, `canvod-grids`, `canvod-readers`,
`canvod-ops`, `canvod-auxiliary`, `canvod-vod`) — this workspace has no
transitive dependency inheritance between packages, so removing it from
`canvod-utils` specifically has zero effect on them. Updated
`canvod-utils/README.md` and `CLAUDE.md` to match. `diagnostics/airflow.py`'s
fate (the one item genuinely tied to the Airflow extraction) is moot now —
it's gone along with everything else; if `canvod-airflow` ever wants
task-metric instrumentation, it starts from scratch there, not from this
dead code.

## 22. `canvod-readers` standalone install: stale-warning report resolved, real missing-deps + circular-dep bug found, 2026-07-09

**Context:** user reproduced a real standalone-install pain point — `uv init` +
`uv add canvod-readers` in a fresh directory, then `SbfReader(...).to_ds()`.

**Part 1 — the double config warning, resolved as a non-issue on current HEAD.**
Live repro printed:
```
⚠️  Warning: .../config/processing.yaml not found, using defaults
   Run: just config-init
⚠️  Warning: .../config/sites.yaml not found, no sites configured
   Run: just config-init
.../pydantic/main.py:263: UserWarning: No research sites defined in sites.yaml. Run: just config-init
```
Traced the exact literal text — it does **not** exist anywhere in this branch's
`canvod-config`/`canvod-utils` source (grepped `models.py`/`loader.py`, no
match). The Dataset attrs in the user's repro show `Software: canVODpy,
Version: 0.2.3` — PyPI is serving the **old, pre-`canvod-settings.yaml`-unification**
release (before §16 "pydantic-settings: 12-factor config resolution", DONE
2026-07-08). Verified directly: called `canvod.config.load_config()` from an
empty cwd using this branch's current code — raises a clean `FileNotFoundError`,
**zero warnings printed** (`warnings.catch_warnings(record=True)` recorded 0).
The `SitesConfig.validate_at_least_one_site` `UserWarning` (`models.py:1074`,
"No research sites defined...") still exists in current code, but the new
unified loader raises `FileNotFoundError` before ever constructing an empty
`SitesConfig`, so it doesn't fire in the "nothing configured at all" case
anymore. **Conclusion: already fixed on this branch, just not released to
PyPI yet.** Re-verify once a new version publishes — if the warning still
appears in a real `uv add canvod-readers` after that release, this needs a
second look.

**Re-confirmed live, 2026-07-14 (canvodpy-extensions repo):** ran
`from canvod.store import MyIcechunkStore` in canvodpy-extensions' own dev
env (`canvod-adapters[store]` pulls in `canvod-store>=0.2.3` from PyPI) —
same exact warning text fired again. Traced it: the installed PyPI package
has **no `canvod.config` module at all** (`ModuleNotFoundError` on direct
import), confirming it predates the config unification entirely. More
precisely than "not released yet": `uv pip show canvod-store` reports
`Version: 0.2.3`, and the **local monorepo's `canvod-store/pyproject.toml`
is also still at `0.2.3`** — the fix landed in source but the version was
never bumped, so there's nothing new to even publish yet. Needs an actual
`cz bump` + PyPI release of canvod-store (and canvod-config itself, which
doesn't exist on PyPI at all) before this stops surfacing for real installs.

**Part 2 — a real, separate bug: missing dependencies + a genuine circular
dependency.** After installing `pymap3d` and `canvod-auxiliary` manually to
get past two `ModuleNotFoundError`s, the read succeeded. Confirmed in source:
`packages/canvod-readers/src/canvod/readers/sbf/reader.py` does deferred
(inside-method, not top-level) hard imports —
`import pymap3d as pm` (lines 1471, 2417) and
`from canvod.auxiliary.preprocessing import pad_to_global_sid` (lines 1517,
2038, 2457) — reachable from ordinary `to_ds()` usage on SBF files, but
neither `pymap3d` nor `canvod-auxiliary` is declared in
`packages/canvod-readers/pyproject.toml`'s `dependencies`. **Worse than a
missing-dependency bug:** `canvod-auxiliary/pyproject.toml` itself declares
`canvod-readers` as a dependency (confirmed) and imports it in 5 files. So
`canvod-readers` cannot simply add `canvod-auxiliary` as a hard dependency —
that would create a real cycle (`canvod-readers → canvod-auxiliary →
canvod-readers`), not just an awkward one. This is the same shape of problem
as the `canvod-config`-in-`canvodpy` question resolved earlier this session,
one layer down the dependency graph.

**Not fixed yet — needs a real design decision, not a quick patch:**
1. ~~`pymap3d` — straightforward, just add it to `canvod-readers`'s
   `dependencies` (it has no reverse dependency on `canvod-readers`).~~
   **RESOLVED 2026-07-14:** added `pymap3d>=3.0.0` to
   `canvod-readers/pyproject.toml` (matching the existing pin in
   `canvod-auxiliary`). **But this was a symptom, not the real fix** — per
   user direction 2026-07-14, replacing this narrow item with a proper
   methodology instead of chasing individual missing-dependency reports one
   at a time:

   **New: genuinely verify standalone installs for every package in a real
   sandboxed environment.** This bug was only found because a user manually
   reproduced it (`uv init` + `uv add canvod-readers` in a fresh directory) —
   nobody had actually tried a clean standalone install of any package
   before that. Grepping `pyproject.toml` dependency lists (what caught this
   specific case) only catches declared-vs-imported mismatches; it doesn't
   catch things that only surface at runtime (lazy/deferred imports inside
   function bodies, like the `pymap3d`/`canvod-auxiliary` imports here were
   — both hidden inside `sbf/reader.py` methods, not at module top level, so
   even reading the file's top imports wouldn't have caught them).
   **Needs an actual sandboxed test, not just static analysis:** for each of
   the 12 `canvod-*` packages, in a genuinely isolated environment (fresh
   `uv init` + `uv add <package>` from PyPI or a local path, no access to the
   monorepo's own `.venv`/lockfile), run a small set of real smoke commands
   that exercise the package's main documented entry points (per its own
   README "Quick Start" section) and see what actually happens — not just
   `import canvod.X` succeeding, but calling the functions a real standalone
   user would call. Catalogue every `ModuleNotFoundError`/warning/crash
   found, the same way this one was found, rather than assuming the
   dependency lists are correct because they look complete on paper.
2. `pad_to_global_sid` — the actual cycle. Options: (a) move
   `pad_to_global_sid` (or whatever `sbf/reader.py` specifically needs from
   it) down into `canvod-readers` or a lower-level shared package that both
   can depend on without a cycle; (b) make the SBF-auxiliary-augmentation
   path in `sbf/reader.py` a true optional/lazy feature with a clear
   `ImportError` message telling the user to `uv add canvod-auxiliary`
   themselves (matches today's *de facto* behavior, just needs a friendlier
   error instead of a raw `ModuleNotFoundError`); (c) restructure so
   `sbf/reader.py`'s augmentation step lives in `canvod-auxiliary` instead
   (which already legitimately depends on `canvod-readers`), not in
   `canvod-readers` reaching upward into `canvod-auxiliary`.
3. Translate into a GitHub issue alongside §21 — same "found while doing
   something else, needs its own decision" bucket.

## 23. ~~Revisit logging + a simplified performance tracker~~ — RESOLVED (2026-07-14)

**Flagged 2026-07-12**, implemented 2026-07-14. Reframed mid-design by the
owner: this isn't just a performance-analysis convenience — canvodpy runs
unattended on remote machines, so the logs written during a run are the
*only* forensic evidence that will ever exist. That drove the final design
past what was originally scoped.

**Shipped:**
- **Two-track logging.** `machine/full.json` renamed to `machine/agent.json`
  — always-on DEBUG, deliberately never gated behind a flag (can't
  retroactively enable debug logging after a remote failure). A `run_id`
  (`{site}-{YYYYMMDD-HHMMSS}`, one per site per CLI invocation) is now
  auto-injected into every log record via a structlog processor
  (`logging/run_context.py` + `_add_run_id` in `logging_config.py`), and
  propagated into `ProcessPoolExecutor`/loky worker processes via
  `_worker_init_with_run_id` (contextvars don't cross process boundaries).
  Also appended to Icechunk commit messages (`store.py`'s new
  `_with_run_id()` helper) so a run correlates across logs *and* the data
  it wrote.
- **Crash handling (the actual gap this closed).** Found there was
  previously **no crash handler at all** — an uncaught exception in
  `cli/run.py` just propagated to Python's default traceback, silently lost
  on an unattended run if stderr wasn't redirected. Fixed with two layers:
  a process-wide `sys.excepthook` (idempotent — installing it more than
  once, e.g. in tests, no longer grows a chain that re-logs the same
  exception per wrap) logging `uncaught_exception` with full traceback +
  run_id; and a top-level try/except around each site's processing loop in
  `cli/run.py` logging `run_crashed` with last-good-date/stage before
  re-raising. Worker-process failures (`ProcessPoolExecutor`) now log
  `worker_task_failed`/`worker_pool_broken` (the latter for
  `BrokenProcessPool` — OOM/segfault, a distinct failure class) instead of
  propagating silently.
- **Performance tracker: `stage_timer()`** (`logging/stage_timer.py`) —
  deliberately not full telemetry (no spans/collectors/exporters). One
  canonical `stage_timing` event replaces the OpenTelemetry-based
  `canvodpy/utils/telemetry.py` (deleted — confirmed `opentelemetry` was
  never actually installed anywhere in the repo, so every span was a
  silent no-op; only 2 of 6 tracer functions had real callers, one of which
  — `store.py`'s `trace_icechunk_write` — was itself an upward
  canvod-store→canvodpy layering violation, now fixed as a side effect).
  `emit_run_summary()` rolls up accumulated stage timings into one
  `run_summary` event, called both on success and from the crash path (so a
  partial summary exists even for a run that later died). The per-file
  RINEX pipeline additionally emits `reading`/`validating`/`augmenting`/
  `writing` sub-stage timings tagged with `receiver`/`date_key`, purpose-built
  for the dashboard below.
  - **Correction made mid-implementation:** initially over-tightened
    `PerformanceFilter` to match only the new `stage_timing` event name,
    which would have silently dropped ~15 pre-existing, deliberately
    detailed, well-named timing events already using the correct
    `duration_seconds` field (e.g. `ephemeris_interpolation_complete` in
    `processor.py`) — those were never actually "ragged", just not using
    the new event name. Fixed by broadening the filter to match either
    shape. Two truly ragged fields (`processing_time_min`,
    `hampel_processing_time_s` in `canvod-grids`) turned out on inspection
    to be **dataset attrs, not log fields at all** — false positives from
    an earlier naive text grep; left untouched.
- **Live performance dashboard**: `canvodpy dashboard` (`--edit`/`--logs-dir`)
  launches a marimo notebook (`cli/dashboards/performance.py`) reading
  `machine/performance*.json` directly (no new data format) — a per-stage
  breakdown for the most recent iteration, and elapsed time per receiver ×
  day, with a manual refresh button. Works during a live run or after.
- **New test suite**: `canvodpy/tests/test_logging.py` (16 tests, all
  passing) covering run_id injection, the excepthook safety net (including
  the idempotency fix), `PerformanceFilter` matching both event shapes, and
  `stage_timer`/`emit_run_summary`/`reset_run_stats`. Full regression:
  1601 passed, 0 failed (`uv run pytest -m "not integration"`).
- **Docs**: `docs/guides/diagnostics.md` fully rewritten (was describing the
  deleted `canvod.utils.diagnostics` module from §21); new "Logging — add it
  generously" section in `docs/guides/DEVELOPMENT.md` teaching the
  `canvodpy.logging.get_logger` vs. bare `structlog.get_logger` distinction
  and when to reach for `stage_timer()`.

**Explicitly out of scope, not solved**: shipping/collecting logs off the
remote machine (no S3 sync, no systemd journal forwarding) — no such
tooling exists anywhere in this monorepo; flagged as a known follow-up.

---

## 24. ~~Adapter to feed canvodpy data back into gnssvod (Humphrey et al.)~~ — RESOLVED (2026-07-14)

**Flagged 2026-07-13** — not investigated yet, just capturing the intent.

`canvod-audit` already has one side of this bridge: Tier 3
(`audit_vs_gnssvod` in `canvod.audit.runners`) compares canvodpy's VOD output
*against* gnssvod as ground truth, using `RinexTrimmer` to feed both tools the
same trimmed RINEX file (one code per band, to avoid SID vs PRN ambiguity —
canvodpy uses SID like `G01|L1|C`, gnssvod uses PRN like `G01`). See the
`canvod-audit Package` memory entry for the full comparison pipeline and the
fillna-merge-order finding (`gnssvod_merge_codes()`).

**Built (2026-07-14):** new `canvod-adapters` package in
`canvodpy-extensions` (`canvod.adapters.gnssvod`), extracting
`GnssvodAdapter`/`detect_band_map`/`BAND_MAP`/`gnssvod_merge_codes`/
`gnssvod_df_to_xarray` out of `vs_gnssvod.py` (re-exported from their new
location for backward compatibility — no test-file changes needed) plus two
new multi-band functions:
- `to_gnssvod_dataset(vod_ds)` — converts an already-computed canvodpy VOD
  Icechunk-store dataset (`VOD`/`delta_snr`/`phi`/`theta`, one code per
  band) into one gnssvod-shaped dataset with all bands as sibling columns
  (`S1C`... not emitted for `delta_snr` — kept as `dSNRn` since it's a
  canopy-minus-reference difference, not real per-receiver SNR), directly
  consumable by gnssvod's own `Hemi.add_CellID()`/plotting/hemispheric
  stats.
- `from_gnssvod_dataset(gnssvod_ds)` — the reverse. Lossy for per-code
  identity (gnssvod fillna-merges codes before ever exporting), flagged via
  `attrs["vod_reconstructed_code_ambiguous"] = True`.
- `provenance.py`: every conversion gets
  `conversion_source`/`_url`/`_version`, `conversion_tool`
  (`"canvod-adapters.gnssvod"`), `conversion_direction`, `conversion_timestamp`,
  `analysis_name` in the output's global attrs.
- `io.py` (optional `store` extra): `vod_store_to_gnssvod_nc()` /
  `gnssvod_nc_to_vod_store()` — read/write an Icechunk VOD store directly
  (accepts a `MyIcechunkStore`, a site/manager object via `.vod_store`, or
  a path).
- `canvod-audit` now depends on `canvod-adapters` instead of vendoring its
  own copy — 60 audit tests still pass unchanged.
- **Not done yet:** `canvod-adapters` needs to actually be committed/pushed
  to the `canvodpy-extensions` GitHub repo before
  `canvod-audit`'s new git-subdirectory dependency resolves anywhere but a
  local sibling-checkout override — `uv sync` in this repo will fail on
  that dependency until then.

---

## 25. Prepare the first real (non-alpha/beta) canvodpy release

**Flagged 2026-07-13** (added from a side-response with no tool access — user
asked for this to be captured for the main session, not investigated yet).

Treat this as a deliberate "first stable" milestone, not another incremental
version bump. Needs:

- **Version scheme decision**: jump to `1.0.0`, or keep incrementing `0.x`?
  No decision made yet.
- **PyPI publishing checklist**: confirm requirements are actually met before
  publishing. Directly ties into the already-known gap that PyPI's published
  `canvodpy==0.3.0` predates the `[project.scripts]` CLI entry point (root
  cause: `a88fc381` matches the PyPI upload date; `ea82a886`, dated later,
  added the entry point) — a straight republish of the current `0.3.0` isn't
  enough, this needs a real version bump.
- **FAIR compliance loose ends**: the deferred PyPI-registry badge and
  OpenSSF Best Practices registration from the FAIR compliance work (see
  `memory/fair_compliance.md`) — both blocked on/relevant to an actual
  release existing.

**Action:** no decision made yet on version scheme or exact release
checklist — revisit as a deliberate milestone, not folded into the ongoing
incremental work.

---

## 26. `canvod-streamviz` / `canvod-streamstats` — GitHub infrastructure + repo setup (2026-07-13)

**Done.** Both are standalone private repos (not in canvodpy-extensions or
this monorepo — confirmed to stay that way, see §8's resolution). Brought
their GitHub-facing infrastructure in line with canvodpy, minus CI workflows
(not requested).

**`canvod-streamviz`** (`git@github.com:nfb2021/canvod-streamviz.git`):
- Had no git repo at all — initialized, remote added, `main` branch.
- `.gitignore`: replaced with canvodpy's full version.
- `.pre-commit-config.yaml`: same hooks as canvodpy (local uv-managed ruff,
  `uv-lock`, `pre-commit-hooks` trio, commitizen commit-msg), minus `ty-check`
  and `update-submodules` (neither applies here). Hooks installed.
- `pyproject.toml`'s `[tool.commitizen]`: added `tag_format`, changelog
  settings, `annotated_tag`, and a `customize.scopes` list derived from its
  own modules (mesh/rollup/ingest/catalog/pipeline/serve/ci/docs/deps).
- `.github/CODEOWNERS`, `.github/dependabot.yml` (pip + pre-commit
  ecosystems only, no `github-actions` ecosystem since no workflows exist).
- Added `LICENSE` (Apache-2.0, copied from canvodpy) and `README.md`
  (description, install incl. editable sibling installs for
  canvod-grids/store/vod/streamstats, a verified usage example, testing,
  license) — neither existed before.
- Two commits: `45a7bc5` (LICENSE + README), and an earlier initial commit
  with everything else plus Phase 1 fixes (see §8's resolution note).
- Also bumped to Python 3.14 (matches canvod-grids/store/vod's `>=3.14`) —
  covered under §8, not repeated here.

**`canvod-streamstats`** (`git@github.com:nfb2021/canvod-streamstats.git`):
- Already had a git repo + GitHub remote + a LICENSE, but the LICENSE still
  had the **unfilled Apache-2.0 template placeholder**
  (`Copyright [yyyy] [name of copyright owner]`) — fixed to a real copyright
  line.
- `.gitignore`, `.pre-commit-config.yaml`: brought in line with canvodpy's,
  **except** kept the pre-existing `check-added-large-files: --maxkb=2000`
  override (now commented) since `docs/streaming-statistics.pdf` is ~1MB,
  over canvodpy's 500KB default.
- `.github/CODEOWNERS`, `.github/dependabot.yml`: same as streamviz.
- Added `README.md` (was missing entirely) — module table, install (incl.
  `canvod-ops` note), usage, testing, license.
- Committed as `ffe0bb2`, **scoped via `git commit -- <pathspec>`** rather
  than a plain `git commit` — this repo had substantial pre-existing
  uncommitted WIP (a reorg moving files from
  `integration/canvod-ops-statistics/`+`integration/canvod-ops-tests/` into
  `src/canvod/streamstats/ops/`+`tests/` directly, with `pyproject.toml`
  already modified as part of it) already staged. A plain `git commit -m`
  would have swept that WIP into the same commit — caught this because
  pre-commit's ruff-check hook linted a WIP file and failed on an unrelated
  unused-variable error. Pathspec-scoped commit fixed it cleanly.

**Resolved 2026-07-13:** the WIP (moving `integration/canvod-ops-statistics/` +
`integration/canvod-ops-tests/` into `src/canvod/streamstats/ops/` + `tests/`
directly, plus dag wiring updates and a new `welford_states.py` vectorized
per-state accumulator module) was committed whole, together with the
`[tool.commitizen]` additions, as `0b47f5d` on `canvod-streamstats` main.
Pre-commit's ruff hook caught 3 real `F841` findings in the newly-added
files, fixed before committing: a dead `sumsq` bincount in
`welford_states.batch_states` (superseded by the deviations-from-mean `M2`
pass), a dead `m` in `test_states_to_moments_skewness`, and a missing
assertion in `test_batch_matches_sequential` (docstring claimed to check
sequential-vs-batch GK-sketch quantile agreement but never actually asserted
it — now does). Separately noted, not fixed: `tests/conftest.py`'s new ops
fixtures import `pandas`/`xarray`, neither of which is a declared dependency
anywhere in `pyproject.toml` — blocks running the test suite in a fresh env;
out of scope for this commit, left as a follow-up.

---

## 27. Airflow DAGs forked — `canvod-streamstats` vs. `canvod-airflow`, needs a decision (2026-07-13)

**Flagged 2026-07-13** — found while checking on canvod-streamstats, not
investigated further, no decision made.

There isn't duplication to clean up here — there's a genuine fork with two
different DAG designs for the same jobs:

- **`canvod-airflow`** (`canvodpy-extensions`, committed `b66aae2` on branch
  `chore/remove-dead-filecatalog`, **not yet merged to main**) — the
  "official" extraction destination per the earlier migration plan
  (`airflow_extraction_plan.md`). Simpler 2-DAG design (`daily_processing`,
  `backfill`): `validate_dirs → check_sbf/process_rinex → validate_ingest →
  calculate_vod → cleanup`. Uses `structlog`. No streaming-statistics
  integration.
- **`canvod-streamstats/dags/`** (committed in that repo's own single
  "initial import" commit) — a **more elaborate 3-DAG design** covering the
  same two DAGs plus a third (SBF+agency hybrid), each extended with
  `run_preprocessing_pipeline → update_statistics → update_climatology →
  detect_anomalies/detect_changepoints → snapshot_statistics` steps.
  Explicitly requires `canvod-streamstats` installed on the Airflow worker
  per its own docstring. Uses stdlib `logging`.
- **`canvodpy-perf/dags/`** (the presumed original source both were derived
  from) — **no longer exists in this repo.** The extraction plan explicitly
  said not to delete it until `canvod-airflow` had a tagged release (Phase D
  was supposed to be last, gated on Phase C) — worth checking whether that
  release already happened, or whether this deletion happened out of order.

**Open questions, none decided:**
1. Should `canvod-airflow` absorb the statistics-pipeline steps from
   `canvod-streamstats`'s version, making it the one canonical DAG design?
2. Should `canvod-streamstats` depend on `canvod-airflow` and contribute
   just the statistics-pipeline task functions to be composed there, rather
   than vendoring its own full DAG copies?
3. Is the simpler `canvod-airflow` 2-DAG version an intentional first cut
   (ship the core pipeline, add stats integration later), or was it
   extracted from a stale/pre-stats-integration snapshot of the original
   `canvodpy-perf/dags/`?
4. Why/when did `canvodpy-perf/dags/` get deleted, and was that consistent
   with the extraction plan's Phase D gating?

**Action:** no decision made yet — revisit when ready to consolidate on one
canonical DAG design.

---

## 28. ~~Deactivate CLK (clock correction) file usage — not deleted, just turned off~~ — RESOLVED (2026-07-14)

**User note:** we do not need CLK files. Deactivate their use, don't delete
the code.

**Confirmed via code trace, not yet implemented:**
- `canvod-auxiliary`'s `AgencyEphemerisProvider` downloads CLK files
  alongside SP3 orbit files (`ephemeris/provider.py`), parses them
  (`clock/parser.py`, `clock/reader.py`, `clock/validator.py`), interpolates
  them (`ClockInterpolationStrategy`, piecewise linear), and merges the
  result into the augmented dataset as a `clock` variable
  (`augmentation.py:281-289`, `provider.py:205-212,288-290`).
- **`canvod-vod` never references `clock` at all** — grepped the whole
  package, zero hits. Matches the documented VOD formula
  (`VOD = -ln(T) · cos(θ)`, CLAUDE.md) — only needs transmittance (from SNR)
  and polar angle (from ephemeris/position), no clock correction. The `clock`
  variable is pure overhead today: extra downloads, extra parsing, extra
  dataset size, zero downstream consumer.

**Implemented (2026-07-14):**
1. New `AuxDataConfig.fetch_clock: bool = True` (`canvod-config`,
   `models/aux_data.py`) — the single source of truth for the toggle.
2. `AuxDataPipeline.create_standard()` (`pipeline.py`) now only registers
   `"clock"` when `fetch_clock` is true (explicit kwarg overrides the config
   default). Ephemerides registration is unaffected.
3. `AgencyEphemerisProvider` (`ephemeris/provider.py`) gained a `fetch_clock`
   constructor param threaded into `create_standard()`; `preprocess_day()`
   now checks `pipeline.is_loaded("clock")` before interpolating/merging it
   — falls back to ephemerides-only when disabled.
4. The **real production hot path**, `processor.py`'s
   `_preprocess_aux_data_with_hermite()` (not `AgencyEphemerisProvider` —
   that's only used by the L4/deprecated-fluent paths), got the same
   guard: `clock_ds` is `None` when clock wasn't registered, skipping
   interpolation/merge entirely and using `ephem_interp` alone.
5. `ClockCorrectionAugmentation.get_required_aux_files()` (`augmentation.py`,
   used by the separate `AuxDataAugmenter` L4 path) changed from
   `["clock"]` to `[]` — it already handled clock's absence gracefully in
   its body; the old required-file declaration would have hard-failed
   `AuxDataAugmenter.augment_dataset()` whenever clock fetching is disabled.
6. Nothing deleted, per the "don't delete" instruction — `ClkFile`,
   `ClockInterpolationStrategy`, `clock/parser.py` etc. are all untouched
   and still exercised when `fetch_clock=True` (the default).
7. Tests added: `AuxDataConfig` defaults/override
   (`canvod-config/tests/test_config_models.py`), `create_standard()`
   clock-gating incl. explicit-kwarg-overrides-config
   (`canvod-auxiliary/tests/test_pipeline_unit.py`), updated the now-stale
   `ClockCorrectionAugmentation` required-files assertion
   (`test_augmentation.py`). Full `canvod-auxiliary`/`canvod-config` suites
   (331 tests) and the `canvod-audit` suite (60 tests) pass.
8. Config templates (`config/canvod-settings.yaml.example`,
   `canvod-config/templates/canvod-settings.yaml.example`) document the new
   field as a commented-out opt-in line, matching the `ftp_timeout_s` pattern.
9. Docs + Mermaid diagrams updated to note CLK is optional (not removed —
   it's still real, still-running code, on by default): `architecture.md`,
   `packages/auxiliary/overview.md`, `api/canvod-auxiliary.md`,
   `guides/configuration.md`, `guides/api-levels.md`,
   `packages/readers/overview.md`, `packages/readers/ephemeris-sources.md`,
   `guides/quickstart.md`, `guides/getting-started.md`, `index.md`, and 4
   `docs/diagrams/*.mmd` sources (`02-processing-pipeline`,
   `05-gnss-t-methodology`, `06-ephemeris-sources`,
   `10-complete-logical-flow` — clock nodes/edges now dashed + labelled
   "optional"/"if fetch_clock"). **Not done:** the matching pre-rendered
   `.html` exports for those 4 diagrams are now stale — the
   `beautiful-mermaid` CLI wasn't available in this environment to
   regenerate them with the correct house style; `.mmd` sources (the
   tracked source of truth) are correct and validated to parse cleanly via
   `mmdc`. Re-render those 4 `.html` files next time `beautiful-mermaid` is
   available.

**Action:** done. Only remaining loose end is the stale `.html` diagram
exports noted above.

---

## 29. Standalone `canvodpy vod` + multi-model VOD store hierarchy + metadata (2026-07-14)

**Debated and designed 2026-07-14** — full spec below, not implemented yet.
Started from "we need a `canvodpy vod` subcommand," grew into a real VOD
store redesign once we dug into what already exists vs. what's missing.

### What's already built (verified against current code, not assumed)

- `canvodpy run --vod-calculator <name>` already exists, dynamically
  populated from `VODFactory.list_available()`
  (`cli/run.py:_build_vod_calculator_choice`) — registering a new calculator
  automatically makes it selectable here. No work needed.
- `VodComputer.__init__(calculator: str = "tau_omega")` already resolves via
  the same `VODFactory` for both `compute_day()` (inline, pipeline path) and
  `compute_bulk()` (standalone, from an existing store). The old §11/§13
  claim that `compute_bulk()` hardcodes `TauOmegaZerothOrder` is stale —
  already fixed.
- The storage layer already supports branches end-to-end:
  `append_to_group(branch: str = "main")` / `write_or_append_group(branch:
  str = "main")` both take a `branch` param. (Decided below: branches are
  the *wrong* tool for model-differentiation anyway — see hierarchy
  decision.)
- `RichReporter` already has live per-(site, receiver) progress bars (see
  §14's correction) — not related to this section, noted here only because
  it came up in the same discussion and was wrongly claimed missing earlier.

### What's actually missing

**1. The `canvodpy vod` CLI subcommand itself.** Thin wrapper around
`Site(site).vod.compute_bulk(analysis_name, calculator=..., start=..., end=...)`,
reusing the same dynamic `VodCalculatorChoice` enum pattern `run.py` already
built. `--site`, `--analysis`, `--start`, `--end`, `--calculator`. This part
really is just wiring — the calculator-selection logic underneath already
works.

**2. VOD store group hierarchy: add a `model` layer, drop `site` from it.**
Decided: `{model}/{analysis_name}` as the group path (e.g.
`tau_omega_zeroth_order/canopy_01_vs_reference_01`), not the originally
proposed `branch/model/site/receiver`:
- **Branch stays orthogonal, not used for model-differentiation** — the
  original idea of one Icechunk branch per model was rejected: branches are
  git-like (meant for a small number of temporary parallel histories), not a
  permanent categorical axis; using them for models would make "give me all
  VOD across all models for site X" awkward and doesn't scale to many
  models. Branch keeps its normal meaning (defaults to `main`, versioning
  only).
- **`site` is redundant as an in-store level** — verified `get_vod_store_path(site_name)`
  already returns a path like `{stores_root_dir}/{site_name}/vod`: one
  physical Icechunk store *per site*, always. A single VOD store instance
  can never contain more than one site's data, so nesting "site" inside it
  would repeat the same path segment on every group — pure ceremony.
- **"receiver" → "analysis"** — VOD is inherently computed over a pair
  (canopy + reference), matching the existing `analysis_name`
  (`vod_analyses` config, `store_vod_analysis(analysis_name=...)`), not a
  single receiver.
- `viewer.py` already branches on `store_type == "vod_store"` at a few call
  sites (`_get_display_type` and others) — there's an existing seam to add
  "group the tree by model first" rendering without a bigger refactor.

**3. Wire up the VOD dedup/overwrite gap — a real prerequisite, found while
designing this, not just a metadata nice-to-have.** `store_vod_analysis()`
calls `write_or_append_group(...)` **without** `dedup=True` (its default is
`False`). That method's own docstring says: *"suitable for VOD stores...
where rinex-style dedup does not apply."* Net effect today: reprocessing the
same VOD analysis for the same date range doesn't skip or overwrite — it
just blindly appends via `to_icechunk(..., append_dim="epoch")`,
**duplicating those epochs**. This needs fixing before the new metadata
table's `action` field (below) can mean anything. The hash-match part of
`should_skip_file` doesn't map cleanly to VOD (no single "File Hash" for a
computation over two receivers' data) — needs its own temporal-overlap-style
check, analogous to but not identical to the RINEX guardrail.

**4. Rich store-level metadata for VOD stores.** Traced why `show.py` prints
"No metadata found" for VOD stores: `collect_metadata()`/`write_metadata()`
(the DataCite/ACDD/STAC provenance writer) is only ever called from
`processor.py`'s RINEX ingest path (STEP 5b) — `vod_computer.py`'s
`store_vod_analysis()` never calls it. Fix: wire the *existing*
`collect_metadata()`/`write_metadata()` into `VodComputer._write_to_store()`,
same pattern as processor.py. Gets config-drift detection (built earlier
2026-07-13) for free on VOD stores too.

**5. New per-computation VOD metadata ledger table** —
`{model}/{analysis_name}/metadata/table`, modeled directly on the GNSS
store's `{group}/metadata/table` at the same level of completeness (commit
tracking via `snapshot_id`, `action`, `write_strategy`, not just a couple of
fields):

| Field | Notes |
|---|---|
| `index` | same as GNSS table |
| `source_file_hashes` | JSON `{receiver_name: [hashes]}` — was going to be a flat `rinex_hash` like the GNSS table, but VOD reads from *two* receivers so it needs to be per-receiver |
| `source_gnss_stores` | **added per user direction** — JSON `{receiver_name: store_path}`; provenance needs to trace back to *which* GNSS store, not just which file hashes |
| `start`, `end` | same |
| `snapshot_id` | same — meaningless until item 3 (dedup/overwrite) is wired |
| `action` | same (`write`/`append`/`overwrite`) — see item 3 |
| `commit_msg`, `written_at`, `write_strategy`, `attrs` | same as GNSS table (`write_strategy` reads `vod_store_strategy` instead of `gnss_store_strategy`) |
| `calculator_name` | new, e.g. `"tau_omega_zeroth_order"` |
| ~~`canonical_name`, `physical_path`~~ | dropped as separate fields — folded into `source_gnss_stores` above instead |
| ~~`ephemeris_source`~~, ~~`config_hash`~~ | considered, then **deferred** — see item 6 |

**6. Deferred — open a GitHub issue (not implemented now):** add
`ephemeris_source`, `ephemeris_file_name`, and the applied interpolation
strategy to **both** metadata tables — the GNSS store's existing one (a
genuine current gap there too, not just for VOD: the GNSS store's own
ingested data is already ephemeris-augmented and *also* doesn't record which
ephemeris source/file/interpolation strategy produced those angles) and the
new VOD table above. Same deferred treatment for `config_hash` on both
tables. All four fields are real reproducibility gaps, just scoped out of
this pass — track as a single GitHub issue covering both tables together
when picked up.

### Implementation order (when ready)

1. Wire dedup/overwrite logic for VOD writes (item 3) — real prerequisite,
   do first.
2. Group hierarchy change: `{model}/{analysis_name}` (item 2) — touches
   `store_vod_analysis()`, `read_vod_analysis()`, and any other caller of the
   current flat `analysis_name` group path (grep before merging).
3. Wire `collect_metadata()`/`write_metadata()` into the VOD write path
   (item 4).
4. New VOD metadata ledger table + writer, modeled on `_append_metadata_row`
   (item 5).
5. `viewer.py` model-aware tree rendering for `store_type == "vod_store"`.
6. `canvodpy vod` CLI subcommand (item 1) — comes last since it's the
   thinnest layer, depends on nothing above being done first, but ships the
   whole thing together.
7. File the deferred GitHub issue for item 6 (ephemeris_source/file/
   interpolation strategy + config_hash on both tables) — separate from this
   implementation, no code change needed to file it.

**Action:** DONE (2026-07-14) — items 1-5 implemented: `write_or_append_vod_group()`
dedup guardrail, `{calculator}/{analysis_name}` group hierarchy, rich
DataCite/ACDD/STAC metadata wired via `ensure_vod_store_metadata()`, new
per-write VOD metadata ledger table, `viewer.py` model-aware rendering, and
the `canvodpy vod` CLI subcommand. Item 7 filed as
[nfb2021/canvodpy#120](https://github.com/nfb2021/canvodpy/issues/120).

---

## 30. New `canvod-audit` tier enabled by `canvod-adapters` (deferred, 2026-07-14)

**Flagged 2026-07-14** — not investigated, no decision made, explicitly
deferred by the owner ("lets solve that later, add a todo item").

Since §24 built `canvod-adapters` (bidirectional gnssvod ↔ canvodpy
conversion: `to_gnssvod_dataset()` / `from_gnssvod_dataset()`), the owner
raised whether this opens up a new verification tier in `canvod-audit`
beyond the existing Tier 3 (`audit_vs_gnssvod`, which already compares
canvodpy's VOD output against gnssvod as ground truth via `RinexTrimmer`).
Two framings were floated when this came up, neither chosen yet:

1. **Round-trip fidelity tier** — test `canvod-adapters`' conversion itself,
   not canvodpy's science: `to_gnssvod_dataset()` then
   `from_gnssvod_dataset()` back, compare to the original canvodpy VOD
   dataset. `from_gnssvod_dataset()` is already flagged lossy for per-code
   identity (`attrs["vod_reconstructed_code_ambiguous"] = True`, gnssvod
   fillna-merges codes before export) — this tier would quantify exactly
   what's lost and confirm it's *only* that, nothing else drifting.
2. **Refactor Tier 3 to route through `canvod-adapters`** — `vs_gnssvod.py`
   has its own ad hoc conversion logic predating the adapter package; now
   that `to_gnssvod_dataset()` is the canonical single source of truth
   (canvod-audit already depends on canvod-adapters per §24), Tier 3 could
   call it directly instead of maintaining a parallel implementation that
   could silently drift from the adapter's behavior.

Also relevant context surfaced while looking into this: the owner ran audit
against the latest PyPI release recently and it was clean — no known
regression motivating this, purely an opportunistic "now that the bridge
exists, should we use it more" question.

**Action:** not decided, not investigated. Revisit alongside or after the
§(pending) canvod-audit → canvodpy-extensions migration, since both touch
the same file (`vs_gnssvod.py`) and it's wasteful to refactor it twice.

---

## 31. Zenodo push for canvodpy-extensions' first release (2026-07-14)

**Flagged 2026-07-14** — not started, just capturing the intent so it isn't
forgotten once a release actually happens.

canvodpy-extensions has now settled on staying **GitHub-only, no PyPI**
(§ decided 2026-07-14 — `publish_pypi.yml`/`publish_testpypi.yml` deleted,
all install docs point at git-subdirectory sources). That decision is
independent of archival/citability: canvodpy itself already does a Zenodo
deposit per release (`CITATION.cff`'s `doi: 10.5281/zenodo.18496233`,
same pattern used for `canvodpy-test-data`) purely for a citable DOI and
long-term archival — nothing to do with package distribution. The owner
wants the same treatment for canvodpy-extensions once its first real
release (`v*.*.*` tag via `just release`) happens.

**Not fixed yet — nothing to build until a release exists:**
1. Set up a Zenodo GitHub integration (or manual deposit) for
   `nfb2021/canvodpy-extensions`, mirroring however canvodpy's own Zenodo
   connection was configured.
2. Add the resulting concept DOI to `CITATION.cff`'s `doi` field (file
   already exists as of PR #4 — `docs/add-citation-cff` — just missing a
   DOI since nothing's been archived yet).
3. Consider whether the Zenodo badge should also go in `README.md`
   (canvodpy has one) once a DOI exists.

**Action:** DONE (2026-07-14) — `v0.1.0` released, Zenodo DOI
`10.5281/zenodo.21359005` obtained and set in `CITATION.cff`, and the DOI
badge added to `canvodpy-extensions/README.md` (same pattern as canvodpy's
own `10.5281/zenodo.18496233`). All three sub-items closed.

---

## 32. canvodpy's own README needs a pass (2026-07-14)

**Flagged 2026-07-14** — not started, just capturing scope while it's fresh
from working on canvodpy-extensions' README/CI/release cleanup.

Three things, found by grepping the root `README.md`:

1. **Remove/reframe the Airflow mentions.** canvodpy itself no longer ships
   or depends on Airflow — DAG definitions live entirely in
   `canvod-airflow` over in `canvodpy-extensions`, which is (per §26-31 work)
   a deliberately separate, optional, GitHub-only, unreleased-to-PyPI
   package. The core README still carries: an "Apache Airflow" badge in the
   tooling table (line ~32), an `Airflow["🌀 canvod-airflow<br/>Airflow
   DAGs"]` node in the architecture mermaid diagram + a
   `Canvodpy -.optional.-> Airflow` edge (lines ~78-96), the phrase
   "Airflow-ready stateless functions" describing the L4 API (line ~204),
   and a line noting `canvod-airflow` "are published separately" (line
   ~347, itself now stale — nothing is "published" anywhere, extensions
   are GitHub-only). All of this should either go or be reframed as "this
   is what the *optional* canvod-airflow extension provides", not
   presented as if it's part of canvodpy's own surface.
2. **General update pass.** Given how much has changed this session alone
   (canvod-config split, canvod-preflight rename, L1/L2 API deprecation,
   the logging/stage_timer redesign, the CLI becoming the recommended
   entry point over `Site.pipeline()`), the README is likely stale in
   more places than just the Airflow bits — worth a full re-read against
   current `CLAUDE.md`/`docs/architecture.md`, not just a targeted fix.
3. **Add a plain "Related repositories" section.** Right now the only
   related-repo signal is a passing mermaid subgraph label and a
   `git clone --recurse-submodules` comment — there's no single place that
   plainly lists and links `canvodpy-extensions`, `canvodpy-demo`, and
   `canvodpy-test-data` with a one-line description of what each is and
   why it's separate. Should mirror the clarity canvodpy-extensions' own
   README now has for its three packages.

**Action:** PARTIALLY DONE (2026-07-14) — items 1 and 3 fixed: removed the
Apache Airflow badge and the `Airflow` mermaid node/edge, reframed the L4
description and the "published separately" package-layout note to
correctly describe `canvod-airflow` as a GitHub-only optional extension
(nothing has actually been published anywhere), and added a "Related
repositories" section listing `canvodpy-extensions`,
`canvodpy-demo`, and `canvodpy-test-data` with their relationship to this
repo. Item 2 (full re-read against current `CLAUDE.md`/architecture — the
L1/L2 quickstart examples still show the now-deprecated `process_date()`/
`calculate_vod()`/`FluentWorkflow` surface as if current) not started —
deliberately out of scope for a quick pass, needs its own read-through.

---

## 33. `canvodpy run` needs a visible "warming up" note before per-day progress (2026-07-14)

**Reported live** during a remote-machine test run: after invoking
`canvodpy run --site ... --start ...`, there is a real, silent delay before
the first per-day progress line appears — looks hung, not "not processing
right away" as the owner put it.

**Plausible causes found while spot-checking** (not fully root-caused, just
enough to make the note useful):
- `orchestrator/pipeline.py` uses `loky.get_reusable_executor()` (line ~796)
  for its persistent worker pool — the *first* call pays full worker-process
  startup cost (each worker re-imports xarray/dask/icechunk/etc.), which can
  be several seconds to tens of seconds depending on disk/import speed, with
  zero progress output during that window today.
- `SatelliteCatalog.fetch()` (`canvod-readers/.../satellite_catalog.py`) can
  fall through to downloading `igs_satellite_metadata.snx` from
  `files.igs.org` on a cold cache (`~/.cache/canvod/`) — on a remote machine
  with slow/restricted outbound network, this could stall silently for a
  while before falling back to the bundled snapshot.
- Store opening (`GnssResearchSite.__init__` → `create_rinex_store`/
  `create_vod_store`) and initial config/site resolution also happen before
  `reporter.set_current_site(...)` prints anything.

**Fix, when picked up:** add a one-line startup message (e.g. via the
`reporter`/`log` before the main site loop in `_main_impl`) explaining that
canvodpy is initializing (worker pool, satellite catalog, store opening) —
doesn't need to pinpoint which one is slow, just needs to exist so a
first-time or remote run doesn't look hung. Optionally instrument each of
the three candidates with its own `stage_timing` event (see
`canvodpy.logging.stage_timer`, already used elsewhere) so a future run can
show *which* warm-up step actually took the time instead of guessing.

**Action:** DONE (2026-07-14) — added the one-line startup message via
`reporter.log(...)` right after `print_header` in `cli/run.py`'s per-site
loop (before worker-pool/satellite-catalog/store-opening happens). Root
cause still not profiled/confirmed — the optional `stage_timing`
instrumentation for each of the three candidates (to show *which* one is
slow) remains unimplemented; revisit if the warm-up is reported as
consistently long rather than a one-off.
