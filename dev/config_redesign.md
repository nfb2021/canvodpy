# Config System Redesign Plan

**Audience:** implementing agent (Sonnet). All paths relative to repo root
`/Users/work/Developer/GNSS/canvodpy-perf/` unless absolute.
**Scope:** `packages/canvod-utils/src/canvod/utils/config/` (models.py, loader.py, cli.py),
plus call sites in `canvodpy/src/canvodpy/` and `packages/canvod-store/`.

---

## 1. Field liveness audit (ProcessingParams)

Verified by exhaustive grep across `canvodpy/`, `packages/`, `dags/` (the orchestrator
lives at `canvodpy/src/canvodpy/`, NOT under `packages/` — earlier searches that only
covered `packages/` were wrong).

| Field | models.py | Verdict | Evidence |
|---|---|---|---|
| `batch_hours` | L203 | **OBSOLETE SEMANTICS — replace** | Still wired: `pipeline.py:619` (`days_per_batch = max(1, round(batch_hours/24))`), `pipeline.py:1136-1146` (strategy switch multi_day/sub_day), `api.py:288-289`, `cli/run.py:177,297,321`. After the flat-loky per-file parallel refactor, the only real effect is how many DOYs are pooled per loky wave; the sub-day (<24) branch is legacy. |
| `aggregate_glonass_fdma` | L163 | **DEAD WIRE — remove** | Config value is read ONLY by the CLI display (`cli.py:454`). It is NEVER passed to any reader/preprocessor. All consumers (`canvod-readers/builder.py:78`, `signals.py:49`, `bands.py:55`, `rinex/v3_04.py:774`, `v2_11.py:566`, `canvod-auxiliary/preprocessing.py`, `canvod-store/preprocessing.py`) use their own hardcoded default `True`. The config field promises control it does not have. |
| `store_radial_distance` | L167 | **LIVE — keep** | `processor.py:1355`, `processor.py:296`, `tasks.py:943,1141`, `canvod-auxiliary/ephemeris/provider.py:285`. |
| `store_delta_snr` | L171 | **LIVE — keep** | `canvod-store/manager.py:592` (inside `calculate_vod`). |
| `store_radial_diff` | L178 | **LIVE — keep** | `canvod-store/manager.py:595-607`. |
| `store_sbf_raw_observables` | L244 | **LIVE — keep** | `processor.py:1356, 3089-3112`, `tasks.py:1142`, consumed as `store_raw_observables` in `sbf/reader.py:2853`. |

### Decisions

**`batch_hours`** → replace with `days_per_batch: int = 1` (ge=1, le=30).
- The float-hours abstraction no longer matches the implementation: per-file concurrency
  replaced batch-by-hours; the only live semantics are "how many DOYs per loky pool".
- Deprecation shim: keep `batch_hours` as an optional field; if set, emit
  `DeprecationWarning` and map `days_per_batch = max(1, round(batch_hours / 24))`.
- Delete `_process_sub_day_batches` dispatch: in `pipeline.py:1143-1146`, always take
  the multi-day path (the sub-day branch at `pipeline.py:1011` becomes dead; remove it
  in the same PR or mark deprecated if the diff gets too big — removal preferred).
- Update: `pipeline.py:74,83-84,127,619,1136-1146,1283`, `api.py:132,266,288-289,320,338,351,560`,
  `cli/run.py:177,297,321`, `cli.py:458` (display), `test_config_models.py:119-123`,
  `canvod-store-metadata/tests/test_collectors.py:79,90` (snapshot fixture).

**`aggregate_glonass_fdma`** → **remove from ProcessingParams** (models.py:163-166), keep the
reader kwarg. Rationale: (a) it currently lies — changing it in YAML does nothing;
(b) flipping it on an existing store would change the SID axis and corrupt
append-compatibility, so it must NOT be a casual YAML toggle. If per-store control is
ever needed, it belongs in store-creation metadata, not runtime config. Also remove the
CLI display row at `cli.py:454` and the stale mapping comment in
`canvod-readers/gnss_specs/constants.py:10`.

---

## 2. pydantic-settings assessment → ADOPT

**Decisive fact: `pydantic-settings>=2.0` is already a declared dependency of canvod-utils
(`packages/canvod-utils/pyproject.toml:14`, locked at 2.13.1 in `uv.lock`) and is
imported NOWHERE.** Zero new dependency; we are already paying for it.
(Correction to §16 of todo_later.md: pydantic-settings is a separate PyPI package, not
part of pydantic v2 core — but irrelevant here since it's already in the lockfile.)

**Nested override syntax works.** With
`SettingsConfigDict(env_prefix="CANVOD__", env_nested_delimiter="__")`, nested plain
`BaseModel` submodels are populated from env vars — submodels do NOT need to become
`BaseSettings`. `CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR=/nfs/stores` resolves to
`config.processing.storage.stores_root_dir`. Caveat: the path mirrors the model tree, so
the ugly `processing.processing` double-nesting (see §7) leaks into env var names
(`CANVOD__PROCESSING__PROCESSING__N_MAX_THREADS`). Fix the nesting name first (item 9)
or accept the wart.

**Rejected alternative** (extend `CANVOD_CONFIG_DIR` pattern with hand-rolled per-field
env parsing in loader.py): reinvents type coercion, nested path walking, and `.env`
loading that pydantic-settings already does correctly. Not simpler after ~3 fields.

**Migration (small, ~40 lines):**
1. `models.py:962` — `class CanvodConfig(BaseSettings)` instead of `BaseModel`;
   `model_config = SettingsConfigDict(extra="forbid", env_prefix="CANVOD__",
   env_nested_delimiter="__", env_file=".env", env_file_encoding="utf-8")`.
2. Override `settings_customise_sources` classmethod to order:
   `env_settings > dotenv_settings > init_settings` (env must beat YAML; YAML arrives
   via init kwargs from ConfigLoader). Default order puts init first, so this override
   is mandatory — it is the one subtle step.
3. `loader.py` keeps doing YAML discovery + deep merge exactly as today and calls
   `CanvodConfig(**merged_dict)`. No YAML source class needed.
4. Precedence becomes: **env var > .env file > YAML > model defaults.** Document in
   `docs/guides/configuration.md`.

---

## 3. Single file vs three files → CONSOLIDATE to `canvod-settings.yaml`

Recommendation: **one `config/canvod-settings.yaml`** with top-level keys `processing:`, `sites:`,
`sids:` — an exact mirror of `CanvodConfig`, so `yaml.safe_load(file)` feeds the model
with no remapping.

Why:
- First-time scientist experience: one file to open, one file `canvod config init`
  scaffolds, one file to attach to a bug report. Three files force the user to learn the
  loader's merge rules before their first run.
- Every field has a Pydantic default, so a minimal `canvod-settings.yaml` is ~15 lines (site name,
  receivers, author email). "Partial override" was the argument for three files; defaults
  in the models already provide that.
- Env-var layer (§2) now covers deployment-specific overrides (HPC/Airflow/n8n), which
  was the other justification for file splitting.

Back-compat: `ConfigLoader` checks for `canvod-settings.yaml` first; if absent, falls back to the
legacy trio (`processing.yaml`, `sites.yaml`, `sids.yaml`) with a one-line
`DeprecationWarning` (via `warnings`, not print). Add `canvod config migrate` command to
cli.py that merges the trio and writes `canvod-settings.yaml`. Keep fallback for one minor
release. Update `*.example` files: ship a single `canvod-settings.yaml.example`.

---

## 4. Credentials → env var / `.env`, deprecate YAML field

Reality check: `nasa_earthdata_acc_mail` is an email used as CDDIS FTP identification
(`processor.py:614,664`, `tasks.py:692`, `canvod-auxiliary/pipeline.py:409`,
`core/downloader.py`, `core/base.py`) — low secrecy, but it is PII and it normalizes
putting credentials in committed YAML.

Decision: **env var via the §2 layer, with `.env` file as the scientist-friendly path.**
- Canonical: `CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL` in `.env`
  (already loaded free by pydantic-settings; `.env` is gitignored — verify and add to
  `.gitignore` if missing).
- Keep the model field (`models.py:86`) so `config.nasa_earthdata_acc_mail`
  (models.py:978) keeps working — only the *source* changes.
- If the key is found in YAML: load it but emit `DeprecationWarning`
  ("move nasa_earthdata_acc_mail to .env"). Detect in `ConfigLoader._load_processing`.
- Remove the field from `canvod-settings.yaml.example`; document the `.env` line instead.
- Update the four hardcoded error-message strings that say "set nasa_earthdata_acc_mail
  in config/processing.yaml": `core/downloader.py:100,196,272`, `core/base.py:33,235,279`,
  `cli.py:192`.
- **No keyring.** It is an email, not a password; keyring adds an OS-specific dependency
  and a concept scientists don't have. If real Earthdata tokens arrive later, revisit.

---

## 5. Rename `scs_from` → `paired_canopies`

Meaning: on a **reference** receiver, "which canopy receiver(s) this reference is paired
with (for spherical-coordinate computation and VOD)". `paired_canopies` reads naturally
in YAML and needs no GNSS jargon:

```yaml
reference_01:
  type: reference
  paired_canopies: all          # or [canopy_01, canopy_02]
```

Implementation (alias keeps old YAML working):
- `models.py:681` — rename field; add
  `validation_alias=AliasChoices("paired_canopies", "scs_from")` and
  `serialization_alias="paired_canopies"`. Emit `DeprecationWarning` in a
  `model_validator(mode="before")` on `ReceiverConfig` when raw input contains `scs_from`.
- `models.py:721-728` — `validate_scs_from` → `validate_paired_canopies` (update messages).
- `models.py:762-777` — `validate_scs_from_targets` → `validate_paired_canopies_targets`.
- `models.py:801-826` — `resolve_scs_from` → `resolve_paired_canopies`; keep a thin
  `resolve_scs_from = resolve_paired_canopies`-style deprecated wrapper (warn once) for
  one release, because external code may call it.
- `models.py:828-843` — `get_reference_canopy_pairs`: name is already clear, keep it;
  update its internals to the new method.
- Call sites: `tasks.py:851,1020`, `pipeline.py:174-215`, `processor.py:2866-2897`,
  `config/sites.yaml:14`, `config/sites.yaml.example:34,82`,
  tests `test_config_models.py:186-287,429,461,485`, `test_config_loader.py:93`,
  `canvodpy/tests/test_integration_sid_filtering.py:34`, `docs/guides/configuration.md`.

---

## 6. Additional defects found during this audit (not in the brief)

- **Hidden global config in library code**: `canvod-store/manager.py:588-590` —
  `calculate_vod()` calls `load_config()` internally to read
  `store_delta_snr`/`store_radial_diff`. A store-layer method silently depending on the
  process-global config dir breaks testability and violates the package layering
  (canvod-store should not need the full CanvodConfig). Fix: `GnssResearchSite.__init__`
  or `calculate_vod()` accepts `processing_params: ProcessingParams | None = None`;
  fall back to `load_config()` only when None (with the fallback slated for removal).
- **`config.processing.processing` double nesting** (`ProcessingConfig.processing:
  ProcessingParams`, models.py:645ff) appears at `processor.py:1355-1356,3089`,
  `tasks.py:943,1141-1142`, `manager.py:590`. Rename the attribute to `params`
  (`config.processing.params.store_radial_distance`) with a deprecated `processing`
  property alias on `ProcessingConfig`. Do this BEFORE the env-var layer ships, so env
  names are `CANVOD__PROCESSING__PARAMS__...` from day one.
- **`extra="forbid"` only on CanvodConfig** (`models.py:975`) — a typo inside
  `sites:` or `processing:` sub-dicts is silently dropped. Fix: module-wide base class
  `class _StrictModel(BaseModel): model_config = ConfigDict(extra="forbid")`; every
  config class inherits from it.

---

## 7. Prioritized implementation plan

Ordered: (a) safety/correctness → (b) user experience → (c) nice-to-have.
Each step is independently commitable; run
`uv run pytest packages/canvod-utils/ canvodpy/tests/ -m "not integration"` after each.

### Tier A — safety / correctness

1. **Remove `sys.exit(1)` from `ConfigLoader.load()`** — `loader.py:119`.
   Raise a new `ConfigValidationError(ValueError)` (defined in loader.py or a new
   `errors.py`) wrapping the pydantic `ValidationError`; move the pretty-print of
   `_show_validation_error` (loader.py:226-231) into the CLI layer (`cli.py`), which
   catches `ConfigValidationError` and calls `raise typer.Exit(1)`. Library callers and
   pytest get a normal exception. Why: `sys.exit` in a library kills Airflow workers and
   test isolation.

2. **Replace `print()` with `logging`** — `loader.py:134-135,147-148,226-231`.
   Module logger `logging.getLogger("canvod.utils.config")`; warnings become
   `logger.warning(...)`. Why: library stdout pollution corrupts piped/CLI output and
   Airflow logs.

3. **`extra="forbid"` everywhere** — models.py: add `_StrictModel` base
   (see §6) and change every `class XxxConfig(BaseModel)` (lines 29, 78, 92, 135, 310,
   342, 389, 494, 549, 557, 567, 575, 608, 638, 645, 673, 732, 740, 845, 884) to inherit
   it; drop the redundant dict at models.py:975. Why: a typo like `n_max_treads:` is
   currently silently ignored — worst possible failure mode for scientists.
   Risk: may surface latent typos in existing user YAMLs — that is the point; the error
   message from step 1 makes it actionable.

4. **Fix hidden `load_config()` in `calculate_vod`** — `canvod-store/manager.py:588-607`.
   Add `processing_params` parameter as described in §6. Why: correctness/testability;
   also unblocks using canvod-store without a config dir.

5. **Deduplicate `find_monorepo_root()`** — delete the copy at `cli.py:23`; import from
   `loader.py:21` (or move both into a new `config/_paths.py` to avoid a cli→loader
   import if circularity threatens). Why: the two copies can drift; this function decides
   where config is read from.

### Tier B — user experience

6. **`batch_hours` → `days_per_batch`** — models.py:203 + all call sites listed in §1.
   Deprecation mapping as specified. Why: config must describe what the code does.

7. **Remove `aggregate_glonass_fdma` from ProcessingParams** — models.py:163-166,
   cli.py:454, constants.py:10 comment. Why: dead wire (§1); a lying config field is
   worse than none.

8. **Rename `scs_from` → `paired_canopies`** — full list in §5, with alias +
   deprecation warning. Why: the one field every new site operator must write is
   currently opaque jargon.

9. **Rename `ProcessingConfig.processing` → `ProcessingConfig.params`** — models.py:645ff
   + call sites in §6, deprecated property alias. Why: `config.processing.processing.x`
   is disorienting and would fossilize into env-var names in step 10.

10. **Adopt pydantic-settings on CanvodConfig** — models.py:962-975 + loader.py, exactly
    as §2. Precedence env > .env > YAML > defaults. Why: HPC/Airflow/n8n deployments
    need per-environment overrides without editing YAML; dependency already present.

11. **Credentials to `.env`** — §4: deprecation warning when found in YAML, remove from
    examples, fix the 7 hardcoded "processing.yaml" message strings, verify `.env` in
    `.gitignore`. Why: stop normalizing credentials-in-repo; trivial after step 10.

### Tier C — nice-to-have

12. **Consolidate to single `canvod-settings.yaml`** — §3: loader fallback chain, `canvod config
    migrate` command in cli.py, single `canvod-settings.yaml.example`, docs update. Why: biggest
    onboarding win, but touches docs/CLI/justfile (`just config-init`,
    `config-validate`) broadly — do it last, on top of the stabilized model layer.

13. **Delete `_process_sub_day_batches`** — `pipeline.py:1011-1078` (if not already done
    in step 6) and `_validate_batch_floor` (`pipeline.py:351`) if it only served sub-day
    logic. Why: dead strategy after step 6.

14. **Docs sweep** — `docs/guides/configuration.md`, `docs/api/canvod-utils.md`,
    `config/*.example`: new field names, env-var table, `.env` instructions, single-file
    layout. Regenerate graphify (`graphify update .`).

### Explicitly out of scope
- Wiring `PreprocessingConfig` (StatisticsConfig / GridAssignment / TemporalAggregate)
  into canvod-ops — known gap from the Airflow strategy review, separate work stream.
- Keyring/secret-manager integration.
