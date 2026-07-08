# Config Template Bugs

Found during "new user" stress test of `just config-init` + `just config-validate`.
The generated `config/canvod-settings.yaml` fails Pydantic validation immediately — a new user
hits a wall before editing anything.

---

## CLEANUP — Legacy config files never removed

The pydantic-settings refactor unified the three-file system into `canvod-settings.yaml`, but the
old files were never deleted. `config/` currently contains both:

```
config/
  canvod-settings.yaml           ← new unified file (active)
  canvod-settings.yaml.example
  processing.yaml       ← legacy, should be removed
  processing.yaml.example
  sites.yaml            ← legacy, should be removed
  sites.yaml.example    ← legacy, should be removed
  sids.yaml             ← legacy, should be removed
  sids.yaml.example     ← legacy, should be removed
```

A new user seeing all these files has no idea which one the loader uses.
`canvod config migrate` was written for this but was never run on `config/`.

**Fix:** Delete the legacy files and their `.example` counterparts once confirmed
that nothing still reads them directly. Keep `canvod-settings.yaml.example` as the single template.

---

## BUG — `scs_from` in template (should be `paired_canopies`)

The template ships the deprecated field name `scs_from` under each reference receiver:

```yaml
receivers:
  reference_01:
    scs_from: all        # ← deprecated
```

Correct name (models.py:777):
```yaml
receivers:
  reference_01:
    paired_canopies: all  # ← current
```

**Why it doesn't fail validation:** `ReceiverConfig` has a `model_validator` at
models.py:818 (`_migrate_scs_from`) that silently renames `scs_from` → `paired_canopies`
at parse time and emits a `DeprecationWarning`. So the bug is invisible — no error, just
a warning that no one sees on first run.

**Fix:** Replace `scs_from` with `paired_canopies` in `canvod-settings.yaml.example`
(and the generated `canvod-settings.yaml`). Also update docs wherever `scs_from` appears.

---

## CRITICAL — Template fails validation on first run (3 Pydantic errors)

```
❌ Validation failed:
icechunk.inline_threshold      → Extra inputs are not permitted
icechunk.get_concurrency       → Extra inputs are not permitted
compression                    → Extra inputs are not permitted
```

### Fix 1: `inline_threshold` → `inline_chunk_threshold_bytes`

Template says:
```yaml
icechunk:
  inline_threshold: 512
```
Correct field (models.py:392):
```yaml
icechunk:
  inline_chunk_threshold_bytes: 512
```

### Fix 2: `get_concurrency` → `get_partial_values_concurrency`

Template says:
```yaml
icechunk:
  get_concurrency: 1
```
Correct field (models.py:393):
```yaml
icechunk:
  get_partial_values_concurrency: 1
```

### Fix 3: `compression:` → `netcdf_compression:`

Template says:
```yaml
compression:
  zlib: true
  complevel: 5
```
Correct field (models.py:724):
```yaml
netcdf_compression:
  zlib: true
  complevel: 5
```
Note: `ProcessingConfig.compression` exists as a deprecated alias that emits a warning
(models.py:752–761) but is not accepted by the strict model — rename the template key.

---

## MEDIUM — `.env` myth propagated in two places

### Fix 4: CLI output from `canvod config init`

Step 2 of the CLI output tells the user:
```
For NASA CDDIS access, add to config/.env (gitignored):
    CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=you@example.com
```
`.env` is NOT loaded automatically — code explicitly says "dotenv/secrets not used".
Fix: change to "set the environment variable in your shell or HPC job script".

### Fix 5: Template header comment

```yaml
# Environment variable overrides (via .env or shell):
```
Remove "(via .env or shell)" → just "Environment variable overrides:".

### Fix 6: Credentials comment in template

```yaml
# Preferred: set via CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL
#            in config/.env (gitignored) rather than here.
```
Remove `config/.env` reference. Replace with:
```yaml
# Preferred: set via environment variable rather than storing here:
#   export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=you@example.com
```

---

## LOW — Dask reference in template comment

### Fix 7: `resource_mode` comment

```yaml
# 'auto'   — Dask/OS auto-detects workers and memory (personal machines)
```
Remove "Dask/". Correct:
```yaml
# 'auto'   — auto-detects available cores and memory (personal machines)
```

---

## LOW — Precision/latency claim in template comment

### Fix 8: `ephemeris_source` comment

```yaml
# 'final'     — satellite coords from SP3/CLK agency products (~3 cm, 12-18 day latency)
# 'broadcast' — broadcast ephemerides from SBF SatVisibility (SBF only, faster but ~1-2 m)
```
Same rule as docs: no precision/latency claims without citation.
Remove the `(~3 cm, 12-18 day latency)` and `(~1-2 m)` parentheticals.

---

---

## UX — `config validate` does not show resolved credential from env var

During stress test on the other machine, `⊘ NASA CDDIS disabled (ESA only)` was shown
even after setting the env var. Root cause: bare `VAR=value` in the shell does NOT export
to subprocesses — `just` spawns a subprocess and never sees it.

Fix for users:
```bash
export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=you@example.com
just config-validate
# or inline: CANVOD__PROCESSING__... just config-validate
```

To verify pydantic-settings resolved the value: `just config-show | grep -A3 credentials`

**Doc fix:** `getting-started.md` should show `export` explicitly, not just the variable assignment.

---

## BUG — Duplicate `vod_analyses:` key silently drops first analysis

YAML does not support duplicate keys — the second `vod_analyses:` block silently overwrites
the first. In the stress-test config:

```yaml
vod_analyses:
  canopy_01_vs_reference_01: ...   # ← SILENTLY DROPPED

vod_analyses:
  canopy_02_vs_reference_01: ...   # ← only this one survives
```

Fix: merge all analyses under a single `vod_analyses:` key:

```yaml
vod_analyses:
  canopy_01_vs_reference_01:
    canopy_receiver: canopy_01
    reference_receiver: reference_01
  canopy_02_vs_reference_01:
    canopy_receiver: canopy_02
    reference_receiver: reference_01
```

Pydantic won't catch this — it's a YAML parser behaviour. Consider adding a validator
that checks all declared canopy receivers appear in at least one `vod_analyses` entry.

---

## BUG — `custom_sids:` at wrong indentation level

In the stress-test config, `custom_sids:` appears at the top level of the file instead
of nested under `sids:`:

```yaml
sids:
  mode: custom
  preset: default   # ← also wrong: preset is irrelevant when mode: custom

custom_sids:        # ← top-level, will be ignored or error
  - 'G01|L1|C'
  ...
```

Correct:
```yaml
sids:
  mode: custom
  custom_sids:
    - 'G01|L1|C'
    ...
```

The `preset: default` line when `mode: custom` is also dead config — worth removing to
avoid confusion.

---

---

## BUG — Template comment "written to processed files / store attributes" is misleading

The `processing.metadata` block has this comment at the top:

```yaml
  # Metadata  (written to processed files / store attributes)
```

This is inaccurate in two ways.

**What actually happens** (processor.py:2053-2107, STEP 5b of `_append_to_icechunk()`):

1. `canvod-store-metadata` is imported inside a `try/except Exception` block.
2. If import succeeds and the store has no metadata yet: `collect_metadata()` + `write_metadata()` are called.
3. On subsequent ingests: `update_metadata()` updates timestamps only.
4. **If anything fails, it is silently swallowed** — only logged at `DEBUG` level. Users never see a failure.

**Specifically wrong about the comment:**
- "processed files" — metadata is NOT written to individual RINEX/observation files as xarray attrs. It is written as Zarr root-level attributes (`canvod_metadata`) on the **GNSS store** (rinex_store) only.
- "store attributes" — only the GNSS store gets it. The **VOD store does not receive any rich metadata** — STEP 5b is inside `_append_to_icechunk()` which only references `self.site.rinex_store`.

**Fix the template comment** to accurately say:

```yaml
  # Metadata  (written as Zarr root attrs on the GNSS store via canvod-store-metadata;
  #            VOD store metadata not yet implemented; failures are silent)
```

Or just document it honestly: these fields feed `canvod-store-metadata` which stamps the
GNSS Icechunk store with DataCite/ACDD/STAC provenance on first ingest. Run
`just metadata-show <gnss_store_path>` to verify the write succeeded.

---

## Files to fix

| File | Issues |
|---|---|
| Template source (find with `grep -r "config-init\|config init" packages/canvodpy`) | Fixes 1–8 |
| `docs/guides/configuration.md` | Verify these field names are now correct after template fix |

---

## ARCHITECTURE DECISION — Sever `canvod-virtualiconvname` from monorepo

**Decision:** `canvod-virtualiconvname` is to be removed from the public monorepo and
maintained as a **standalone private-then-public package**. It will not ship as part of
the canvodpy workspace.

**Rationale:**
- The public monorepo requires users to adhere to the canVOD file naming convention
  directly. No mapping layer is provided by default.
- `canvod-virtualiconvname` is a power-user tool for sites with legacy or non-canonical
  filenames (RINEX v2 short names, custom directory layouts, etc.). It stays with the
  author privately and will eventually be released as a standalone public package.
- Bundling it in the monorepo implies it is required — it is not.

**Integration model (optional slot-in):**
- The pipeline checks whether `canvod-virtualiconvname` is importable at runtime.
- If present: `FilenameMapper` + recipe files handle physical→canonical name mapping
  transparently (as demonstrated: RINEX v2 short names `ract087p45.25o` worked out of
  the box via `rosalia_reference.yaml` / `rosalia_canopy.yaml`).
- If absent: pipeline expects files to already follow the canVOD naming convention
  (`{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}`).
- Recipes (`config/recipes/*.yaml`) are the extension point — they live in the user's
  config dir, not in the package, so no monorepo changes are needed to add site-specific
  mappings.

**What needs to change in the codebase:**
1. Make the import of `canvod.virtualiconvname` optional everywhere in the orchestrator
   (guard with `try/except ImportError` or `importlib.util.find_spec`).
2. Remove `canvod-virtualiconvname` from workspace `members` in root `pyproject.toml`.
3. Remove it from `uv.lock` and any `[project.dependencies]` that reference it.
4. Update docs: mention it as an optional extension, not a built-in package.
5. `canvod-preflight` (which also wraps convention logic) may need the same treatment
   or should be made to work without `canvod-virtualiconvname` as a hard dep.

**Status:** not yet started — decision recorded 2026-07-07.
