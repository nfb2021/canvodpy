# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->
## v0.3.0 (2026-04-30)

### Feat

- **readers**: Implementation of stripped RINEX 3.05 reader
- **readers**: Implementation of NMEA reader
- **readers**: Register NMEA reader in ReaderFactory
- **reader**: add NMEA standard document (large file, 1MB, ignoring hooks)
- **readers**: Implementation for NMEA v4.* incl. test, and format reference file
- **readers**: Add tests for rinex 2.11 and a data standard description
- Implementing reader for RINEX 2.11
- Implementing reader for RINEX 2.11, add test_data

### Fix

- **ci**: remove taiki-e/install-action to fix BASH_FUNC_ injection false positive
- **store**: bump canvod-store to 0.2.3 — add missing canvod-utils/vod/auxiliary/readers deps                                  \canvod.utils is imported eagerly at module load time but was absent from the 0.2.2 PyPI release dependencies. Files: packages/canvod-store/pyproject.toml
- **grids**: bump canvod-grids to 0.2.3 — add missing structlog dep
- **readers**: move keep_data_vars filter after store_raw_observables in to_ds_and_auxiliary
- **speedrun**: decode_timedelta=False on zarr open; subpkg header >=0.2.3; fix SP3/CLK paths
- **demo**: verify 00_convenience_speedrun — bump readers/auxiliary/vod to 0.2.3
- **orchestrator**: add consolidated=False + datetime64 epoch fix in VodComputer
- **quality**: resolve CodeQL error-severity code scanning alerts
- **utils**: replace tomli with built-in tomllib
- **ci**: regenerate uv.lock for Dependabot PRs before uv sync --locked
- **ci**: make Dependabot PRs work without lockfile race condition
- **ci**: re-run failed checks after uv.lock update to resolve race condition
- **ci**: pass GITHUB_TOKEN to howfairis to avoid rate limit 403
- **ci**: remove stale just installer from lock_file job
- **types**: resolve all ty diagnostics and enforce type checking
- **deps**: declare remaining missing inter-package dependencies
- **deps**: declare missing inter-package dependencies
- **deps**: add missing structlog dependency to 5 packages
- **readers**: use importlib.metadata for version lookup in get_version_from_pyproject()
- **readers**: remove unnecessary files
- **readers**: delete useless file
- **readers**: remove unnecessary config files
- **readers**: rename rinex2-files
- **readers**: find rinex2 files
- **docs**: use VODnet badge with embedded logo in docs/index.md

## v0.2.2 (2026-04-07)

## v0.2.1 (2026-04-07)

### Fix

- restore fair-software badge to 5/5 green (PyPI registry check now passes)
- **ci**: add PyPI badge to README and update fair-software badge to 4/5

## [0.2.0](https://github.com/nfb2021/canvodpy/releases/tag/v0.2.0) - 2026-04-06

<small>[Compare with 0.1.0](https://github.com/nfb2021/canvodpy/compare/0.1.0...v0.2.0)</small>

### Features

- First public release — removes pre-release access restriction.
- Add `canvod-store-metadata`, `canvod-virtualiconvname`, `canvod-ops`, `canvod-audit` to PyPI publish workflows (previously unpublished packages).
- Enrich Zenodo and CITATION.cff metadata: aligned titles/dates, added `related_identifiers` for `canvodpy-test-data` and `canvodpy-demo` sub-repos, extended keyword list.

### Bug Fixes

- Fix PyPI publish workflow: `uv build` in sub-directories was writing wheels to per-package `dist/` instead of the root `dist/` consumed by `gh-action-pypi-publish`.
- Add missing Dependabot labels (`dependencies`, `ci`, `python`) to repository.

### Chores

- Bump all package versions `0.1.0` → `0.2.0`.
- Remove confidential pre-release CAUTION banner from README.

## [0.1.0](https://github.com/nfb2021/canvodpy/releases/tag/0.1.0) - 2026-02-04

<small>[Compare with first commit](https://github.com/nfb2021/canvodpy/compare/96138d31f317198083a65199572cd23366b8b9b3...0.1.0)</small>

### Features

- Re-enable code_quality.yml workflow with Phase 1 rules ([d60a953](https://github.com/nfb2021/canvodpy/commit/d60a95343b90a985701cf4f8db36bcc697269485) by Nicolas Bader).

### Bug Fixes

- Update deprecated ruff config in package pyproject.toml files ([1c757a6](https://github.com/nfb2021/canvodpy/commit/1c757a690328fefb6477b181d0ca7c111c1179d6) by Nicolas Bader).
- Convert test_config_from_anywhere to proper pytest test ([db47b8a](https://github.com/nfb2021/canvodpy/commit/db47b8ae15624a365dcc1267d6b4c3707178a5c3) by Nicolas Bader). Result: Test collection works in CI, tests skip properly
- Measure coverage for all packages, not just umbrella ([b0046f4](https://github.com/nfb2021/canvodpy/commit/b0046f4ac18ad97136c1843baa00fe6ce76f7af8) by Nicolas Bader). Expected coverage: ~63% overall, - High: canvod-store (70%), canvod-grids (75%), - Medium: canvod-vod (75%), canvod-auxiliary (60%), - Lower: canvod-viz (36%), canvod-utils (79%)
- Remove obsolete test_configuration.py from workflow ([f5c1727](https://github.com/nfb2021/canvodpy/commit/f5c1727ce94717cfe4308a3ff1bac785a574d74e) by Nicolas Bader).
- Fix CI failures - pint ApplicationRegistry and sys.exit ([3120d30](https://github.com/nfb2021/canvodpy/commit/3120d30390e7cec9426576fcd3809b98751a7cc0) by Nicolas Bader).
