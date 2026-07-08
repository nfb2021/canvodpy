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

## 3. `canvod-virtualiconvname` — needs drastic redesign (Task C)

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

## 4. CLI and configuration — package-standalone usage and human ergonomics (Task D)

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
- Split `models.py` into focused files — still open (deferred to §11 Phase 1).
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
- Validate naming-section config at `SitesConfig` load time — still open (§12 preflight).
- ~~Surface `CANVOD_CONFIG_DIR` in `--help` and all package READMEs.~~ **RESOLVED (96e58c73 + prior):** `CANVOD_CONFIG_FILE` + `CANVOD_CONFIG_DIR` both handled in `load_config()`; `@lru_cache(maxsize=8)`, `logger.warning()` (no print()), `ConfigValidationError` (no sys.exit) all in place. **Still open:** mention both env vars in each `canvod-*` package README.
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
- Should `CanvodConfig` snapshots be persisted into store metadata per run (the
  store-metadata package already has a `config` section) for drift auditability?
  — still open, unanswered.

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
  `canvodpy-extensions/packages/canvod-filemap` (verified 2026-07-08). **Still open:**
  re-apply the deletion in the extensions repo.
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
- **Silent recipe-without-filemap failure (found 2026-07-08, real production run
  on the remote processing machine).** A site's receivers were configured with
  `recipe: rosalia_canopy` / `recipe: rosalia_reference` in `canvod-settings.yaml`
  — i.e. non-canonical filenames requiring `canvod-filemap` to match them — but
  `canvod-filemap` wasn't installed (plain `uv sync`, no `--extra filemap`). The
  ImportError fallback in `pipeline.py`/`tasks.py` (see bullet above) silently
  degraded to canonical-only globs (`*.rnx`/`*.RNX`), which don't match this
  site's real files. Symptom was a confusing `no_rinex_files_found` warning per
  receiver-day with no indication of the actual cause, discovered only through
  manual diagnosis (checking `config.sites.*.receivers.*.recipe` against whether
  `canvod.filemap` importable). **Needed:** a clear, fail-fast, actionable error
  instead of a silent degrade whenever a receiver has `recipe:` configured but
  `canvod-filemap` isn't importable — e.g. in `canvodpy config validate`
  (`canvodpy/src/canvodpy/cli/config.py`) and/or at
  `PipelineOrchestrator`/`RinexDataProcessor` startup, something like:
  `"Receiver {name} configures recipe '{recipe}' but canvod-filemap is not
  installed. Install with: uv sync --extra filemap"`. Should fail before any
  processing starts, not surface as a per-day discovery warning deep in a run.

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

## 8. VOD hemisphere visualization — integration plan

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

---

---

## 9. ~~Production pipeline config — revisit before next run~~ — PARTIALLY RESOLVED

**Context (2026-07-04):** First production config written for rosalia/January 2025 RINEX run. Two fields added that need review:

- ~~**`batch_hours: 24`**~~ — **RESOLVED (96e58c73):** `batch_hours` removed entirely from `ProcessingParams`; pipeline handles file granularity via `FilenameMapper`, not a time-based batch window.
- ~~**`resource_mode: auto`**~~ — **RESOLVED (96e58c73):** `auto` now caps at `cpu_count − 2` workers and applies `nice=3`. Add `auto_uncapped: true` only on a dedicated machine. Shared server no longer needs manual intervention by default.
- **`preprocessing.grid_assignment`** — still open: 2° equal-area grid assignment is currently baked into preprocessing. Confirm this is the intended behavior (vs. doing grid assignment only at VOD time) and that it doesn't conflict with the rollup-native store's own `cell_id` assignment.

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

### Phase 2 — Discovery wizard: `canvodpy init` (~3–4 days)

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

2. `canvodpy vod` subcommand: `--site`, `--analysis`, `--start`, `--end`, `--calculator`. Thread `calculator_cls` through `VodComputer.compute_bulk()` (vod_computer.py:127) — currently hardcoded `TauOmegaZerothOrder` at L236.
3. Calculator registry in `VODFactory` (factories.py:362): resolve `importlib.metadata.entry_points(group="canvodpy.calculators")` first; if `":"` in the name, import dotted path (`mylab.module:MyClass`). Register `tau_omega_zeroth_order` (`canvod-vod/.../calculator.py:148`) in `pyproject.toml` `[project.entry-points."canvodpy.calculators"]`.

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
- `cli.py`: `canvod config init --interactive` (make it default; `--templates` keeps old behaviour). Reuse directory/format detection from `validate` (cli.py:246–309). Writes minimal `canvod-settings.yaml`, runs validation immediately.
- Follow-up: recipe inference — user pastes one filename, wizard aligns it against `CanVODFilename` fields and emits `config/recipes/<name>.yaml`.

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
9. Remove phantom `just naming-init` reference (tasks.py:344); add `config/recipes/` with 2 commented examples. ← **still open**
10. Document the manual integration hook in the package README. ← **still open**

**Phase 3 — `canvod-preflight` new checks (~2 days):**
11. RINEX header peek: open first few KB, parse `SYS / # / OBS TYPES` and `INTERVAL`, compare against filename-declared sampling and period.
12. Gap detection: given a date range, report missing days in plain language.
13. Expand CLI to produce the full plain-language report shown in "Proposed scientist-facing config" section above.

**Files touched:** new `packages/canvod-preflight/`, updated `packages/canvod-virtualiconvname/` (remove moved files, add dep), `canvodpy/src/canvodpy/workflows/tasks.py` (import updates), root `pyproject.toml` (new workspace member).

---

## 13. CLI: TUI + `canvodpy vod` subcommand

> **Merged into §11 (Phase 3).** All detail — Textual app design, three-pane layout, TTY detection, `canvodpy vod` subcommand, `--calculator` registry, `VodComputer.compute_bulk(calculator_cls=...)` threading — is documented in §11 Phase 3. This stub remains for section numbering.

---

## 14. Visual design language — Rich/Textual aesthetic spec

**Context (2026-07-05):** Agreed design direction: clean, modern, instrument-like.
No emoji (render inconsistently, look cheap). All marks are plain Unicode or ASCII.
Nordic Green palette from `docs/assets/canvod-nordic.css` carried into the terminal.

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

## 18. Multi-process logging race — `RotatingFileHandler` shared across loky workers

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

## 19. Chunk-size misalignment on the Rosalia store — root cause found, `rechunk_group()` fixed, migration still pending

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

**Still pending:**
1. Stop the remote pipeline.
2. Set `epoch=17280` for Rosalia in `canvod-settings.yaml`'s
   `icechunk.chunk_strategies` (both `gnss_store` and `vod_store` if VOD
   analyses are also affected — not yet checked whether VOD store has the same
   sampling-rate assumption).
3. Run `store.rechunk_group(group_name, chunks={"epoch": 17280, "sid": -1})`
   for each of the 4 groups.
4. Verify (chunk size, metadata row counts, root attrs, spot-check data
   values) before resuming the pipeline.
5. Resume ingestion — new writes should now be clean appends.
