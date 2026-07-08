# Docs Audit Status

Tracking the documentation overhaul (accuracy + scientist explanations).
Rules: status-quo only, no historical content, no guessed precision claims,
plain-language explanations backed by web research with links.

Workflow per file: Opus pre-vet → Sonnet rewrite → Opus verify.

---

## Completed and verified

| File | Notes |
|---|---|
| `docs/index.md` | Dask card, grid count (7→5 hemispheric), `.augment()` example, canvod-preflight + canvod-audit cards |
| `docs/guides/parallel-processing.md` | New file — Wave A/B ThreadPoolExecutor + ProcessPoolExecutor, sequential Icechunk writes |
| `docs/guides/dask-resources.md` | Cleared to comment-only stub (nav points to parallel-processing.md) |
| `zensical.toml` | Nav entry renamed ("Parallel Processing") |
| `docs/architecture.md` | Dask removed (2 places), 12 packages, 3-layer dedup, config unified, API levels table, scientist rationale table |
| `docs/guides/getting-started.md` | `just config-init` CLI, canvod-preflight first-run, L1/L2 examples, ephemeris admonition (no precision/latency claims) |
| `docs/guides/configuration.md` | 6 wrong field names fixed, `.env` auto-load myth removed, CANVOD__ env prefix explained, pydantic-settings linked |
| `docs/guides/api-levels.md` | 10 errors fixed: fabricated L4 params, wrong ephemeris enum (broadcast tab), `RinexNavProvider` removed, `compute_bulk` signature, Dask references, IGS claims |
| `docs/principles.md` | Full structural rewrite — 6 verified design principles (epoch×sid contract, DataDirectoryValidator hard gate, Icechunk reproducibility, layered deps, self-describing filenames, 3-layer dedup) |
| `docs/tooling.md` | hatchling exception removed (all packages use uv_build), ty config corrected, pre-commit YAML fixed, real CI workflows |
| `docs/packages/readers/overview.md` | IRNSS added, `.sbf`/`.rnx` filenames fixed, Dask batch tip replaced, M1–M5 scientist explanations (SID 6D→2D framing, Zarr/Icechunk/Pangeo stack, consistent output structure, File Hash traceability, RINEX v2/v3 flavours, SBF firmware caveat) |
| `docs/packages/store/overview.md` | 14 errors fixed: fabricated API removed (`store.write()`, `IcechunkDataReader(store_path)`, `strategy=` param), Zstd level 5→3, chunk gloss corrected, `obs/` subgroup removed, S3 claim softened, 3-layer dedup expanded, Zarr/Icechunk scientist explanation, versioning API surface |

---

## Needs one more Opus verify pass

| File | Status |
|---|---|
| `docs/packages/store/overview.md` | Sonnet done (14 fixes applied); Opus verify hit rate limit before running |

---

## Not started

### Package overviews
- ~~`docs/packages/store/icechunk.md`~~ **DONE 2026-07-07** — Configuration section rewritten: 3 critical field-name bugs fixed, compression_level 5→3, lz4/gzip removed, S3 migration table added, manifest splitting/preloading/cache all documented with correct defaults
- `docs/packages/store-metadata/overview.md`
- `docs/packages/auxiliary/overview.md`
- `docs/packages/auxiliary/coordinates.md`
- `docs/packages/auxiliary/interpolation.md`
- `docs/packages/auxiliary/products.md`
- `docs/packages/vod/overview.md`
- `docs/packages/grids/overview.md`
- `docs/packages/naming/overview.md` ← rewritten as canvod-preflight doc (2026-07-07); canvod-filemap API sections removed (package is now external)
- `docs/packages/utils/overview.md`

### Readers sub-pages
- `docs/packages/readers/rinex-format.md`
- `docs/packages/readers/sbf.md`
- `docs/packages/readers/satellite-catalog.md`
- `docs/packages/readers/ephemeris-sources.md`

### Guides
- `docs/guides/architecture-design.md`
- `docs/guides/diagnostics.md`

### Scientific context (purpose #3)
- To be written together with the user — last.

---

## Nav / site structure overhaul — DONE (2026-07-07)

Implemented. Landing / Usage / Development / API Reference. Two CTAs. `quickstart.md` split from `getting-started.md` → `contributor-setup.md`. All inbound links updated.

~~The site currently mixes user-facing content into a "Development" section written
for contributors. The target layout is three audience-first sections:~~

### 1. Landing page
- Tease what's new and exciting; why scientists should use canVODpy
- Brief trust signals: FAIR-compliant, open-source, citable (Zenodo DOI), REUSE /
  OpenSSF — teaser only, link to full compliance details in Development
- Two CTAs:
  - **"Get started retrieving VOD"** → Usage section
  - **"Get started contributing to the ecosystem"** → Development section
- Development CTA must carry a note: "written for newcomers, no experience assumed"

### 2. Usage (for end users / scientists)
Everything needed to actually run the pipeline — no contributor knowledge assumed:
- Configuration guide ← **currently buried in Development; move here**
- High-level pipeline diagrams (logical flow: files → VOD)
- Core principles / data contracts (what the user-facing invariants are)
- Demos and notebooks
- API levels (L1–L4 usage patterns)
- Getting started (first VOD retrieval)

### 3. Development (for contributors — written for newcomers)
- Getting started contributing (setup, workflow, first PR)
- Monorepo architecture (packages, deps, namespace packages)
- Technical deep-dives (reader architecture, store internals, etc.)
- Contributing guide, build system, tooling
- Release mechanics (versioning, PyPI, Zenodo, OIDC) ← release is a contributor concern
- FAIR compliance details, OpenSSF Best Practices ← quality practices for contributors
- Claude Code / AI-assisted development notes

### 4. Footer / Legal
- Impressum & AI disclosure
- License

### Notes for implementation
- `docs/guides/configuration.md` → move to Usage
- `docs/principles.md` → move to Usage (rename to "Core Principles")
- `docs/guides/api-levels.md` → move to Usage
- `docs/guides/getting-started.md` → split: "first VOD" goes to Usage; "dev setup" goes to Development
- FAIR / OpenSSF pages → move to Development
- Release & Publishing section → merge into Development
- Packages reference (API docs) → keep as a standalone Reference layer outside the three sections

---

## Known issues — docs content

Issues in doc files that still need a fix pass.

| File | Issue |
|---|---|
| `docs/guides/airflow.md` | ~~`keep_rnx_vars:`~~ → `keep_gnss_observables:` **FIXED** |
| `docs/guides/airflow.md` | ~~`# SP3/CLK, ~12-18 day lag`~~ comment removed **FIXED** |
| `docs/guides/configuration.md` | ~~`scs_from` at L103–107~~ → `paired_canopies` — verified already correct |
| `docs/guides/configuration.md` | ~~`base_dir`~~ → `gnss_site_data_root` — verified already correct |
| `docs/guides/configuration.md` | ~~`custom:`~~ → `custom_sids` — verified already correct |
| `docs/guides/quickstart.md` | ~~Bare `VAR=value`~~ — `export` already used in quickstart.md (content moved from getting-started.md) |
| `canvodpy/src/canvodpy/__init__.py:132` | `.preprocess()` orphan in workflow example (code bug, not docs) — open |
| `canvodpy/src/canvodpy/workflows/fluent.py` | Orphaned `.preprocess()` step (code bug) — open |

---

## Known issues — config template / code side — RESOLVED (2026-07-07)

All template bugs verified fixed in `config/canvod-settings.yaml.example`:
- `inline_chunk_threshold_bytes` ✓, `get_partial_values_concurrency` ✓, `netcdf_compression:` ✓
- `paired_canopies:` ✓ (no `scs_from`), no `.env` references ✓, no Dask in comments ✓
- No precision/latency claims in ephemeris_source ✓, metadata scope comment correct ✓
- Stale `canvod config migrate` reference removed from both template and live config header

Live `config/canvod-settings.yaml`: `scs_from` → `paired_canopies` fixed (2 occurrences).

### Open — YAML usage bugs (validation-level guards, not template bugs)

- **Duplicate `vod_analyses:` key** — YAML parsers silently drop the first block. Consider a
  model validator that checks all declared canopy receivers appear in at least one `vod_analyses` entry.
- **`custom_sids:` at wrong indent** — must be nested under `sids:`. Verify `extra="forbid"` raises
  a clear error for this case.

---

---

## dev/ directory — pre-PR cleanup verdict (2026-07-07)

All `dev/` files can be deleted. `icechunk-config-guide.md` was consumed into
`docs/packages/store/icechunk.md`. Everything else (benchmark CSVs, perf plans,
web research notes, scripts, raw terminal output, empty files, resolved bug lists)
is ephemeral — content that matters is in the commits or in the parallel-processing guide.

`docs-audit-status.md` (this file) — keep until PR is merged, then delete.

---

## Recurring rules (apply to every file)

- No "we used to use X", "we removed Y because Z", "previously" — status quo only
- No precision/latency claims without web-research backing (e.g. IGS product timing, orbital accuracy)
- No Dask references anywhere
- Plain-language explanations encouraged — back with official docs links (xarray, Zarr, Icechunk, Pangeo, IGS, Septentrio)
- Wrong field names are bugs, not style — always verify against `models.py` before documenting config keys
