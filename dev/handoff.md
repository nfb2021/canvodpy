# Handoff — canvodpy-extensions bootstrap, canvod-airflow extraction, CLI/distribution work

Written 2026-07-12 for a fresh agent picking this up. Two repos involved:
- `/Users/work/Developer/GNSS/canvodpy-perf` — the core canvodpy monorepo
- `/Users/work/Developer/GNSS/canvodpy-extensions` — optional extension
  packages for canvodpy (independently versioned/released, `uv add <pkg>`)

## Why this all started

canvodpy is maturing from "monorepo you clone and `uv run` inside" into a
terminal-first program people install and invoke like any other CLI
(`gfzrnx`, `git`, etc.) from anywhere on their machine, not just from within
the repo. That reframing drove three threads of work below.

## 1. Done: canvodpy-extensions repo hygiene bootstrap

The extensions repo existed with only `canvod-filemap` and no governance
files. Added (all committed, pushed):
- `LICENSE`/`LICENSES/Apache-2.0.txt`/`NOTICE`/`REUSE.toml` (Apache-2.0, same
  attribution as canvodpy-perf)
- `README.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, `SECURITY.md`,
  `.github/CODEOWNERS`
- PyPI release automation: root `Justfile` (`bump`/`release`/`build-all`/
  `publish-pypi`/`publish-testpypi`), `.git-changelog.toml`, `CHANGELOG.md`,
  and three GitHub Actions workflows (`publish_pypi.yml`,
  `publish_testpypi.yml`, `release.yml`) — all discover packages dynamically
  under `packages/*/`, no hardcoded package lists, so new packages need zero
  workflow edits
- Full Zensical documentation site mirroring canvodpy-perf's setup
  (`zensical.toml`, `docs/`, `deploy_docs.yml`, shared CSS/JS/theme assets)
- `canvodpy-extensions.code-workspace` (VS Code multi-root workspace, same
  shape as canvodpy-perf's)
- Root `CLAUDE.md` with the same "breadcrumb trail" documentation-navigation
  section canvodpy-perf uses
- `.gitignore` replaced with canvodpy-perf's version (trimmed to drop
  perf-specific dead entries); untracked `.DS_Store` files removed from git
- Branch protection applied to `main` on GitHub (PR required, 0 mandatory
  approvals — matches canvodpy-perf's solo-maintainer setup; no required
  status checks yet since there's no lint/test CI here)
- `.pre-commit-config.yaml` + fixed `Justfile` `hooks`/`sync` recipes to
  actually install all three hook stages (pre-commit, commit-msg, pre-push) —
  previously only `pre-commit` was being installed
- Fixed two pre-existing `ty` type errors in `canvod-filemap` that the new
  pre-push hook surfaced (optional `polars` import needed a `# ty:
  ignore[unresolved-import]`; several tests passed raw strings where
  `ReceiverType`/`FileType`/`DirectoryLayout` enum members were expected)

**Reference example used throughout:** `github.com/npikall/homebrew-tap` (a
real, working Homebrew tap, likely a TU Wien colleague's) — see distribution
doc below for what was learned from it.

## 2. Done: `canvod-airflow` package extracted to canvodpy-extensions

Full plan in `dev/airflow_extraction_plan.md` (this repo) — **already
executed**, not just planned:
- canvodpy-extensions: commit `b66aae2 feat(airflow): add canvod-airflow
  package with daily + backfill DAGs` — package now lives at
  `packages/canvod-airflow/`, status flipped to "Available" everywhere
  (README, CLAUDE.md, docs nav, commitizen `version_files`, pytest/coverage
  paths)
- canvodpy-perf: `dags/` directory no longer exists (confirmed) — moved out
  cleanly
- n8n: confirmed nothing existed to migrate (only aspirational mentions in
  `dev/todo_later.md` etc.) — no action needed, not a gap
- Open items noted in that doc but not yet resolved: whether
  `apache-airflow` should be a hard dependency or optional extra on
  `canvod-airflow` (leaned toward extra), whether canvodpy-extensions
  packages get actually published to PyPI or stay git-subdirectory-install
  only (currently the latter — `canvod-filemap` returns 404 on PyPI despite
  the OIDC publish workflows existing)

## 3. Open / actively being worked: distribution & packaging strategy

Full history and findings in `dev/distribution_packaging_plan.md` (this
repo) — this doc evolved a lot over the conversation, read it in full rather
than trusting a summary; highlights:

- Explored, in order, then mostly moved past: curl-pipe install script →
  Homebrew tap (confirmed via reading Homebrew's actual source that
  `icechunk`/`duckdb` would force a from-source Rust/C++ compile via the
  standard `virtualenv_install_with_resources` + `brew
  update-python-resources` pattern — verified, not hypothesized) → pipx/
  conda-forge (rejected by the user: "no conda, no pip ideally, this is from
  the last decade") → **pivoted to standalone-binary distribution**
  (PyInstaller/Nuitka for a real compiled-feeling artifact)
- **For Linux specifically**, `python-appimage` (verified real/maintained via
  `gh api` against `niess/python-appimage`) looks like the easiest win — it
  does a plain `pip install` of wheels into a relocatable manylinux Python
  runtime rather than freezing/import-analysis, so it sidesteps both the
  Homebrew sdist problem and PyInstaller's hidden-import fragility. Confirmed
  a real example recipe (`applications/scipy`) already bundles a heavy
  compiled-extension scientific stack successfully.
- Full installation-procedure writeup for "assume the AppImage exists" is in
  the doc (Tier 0 plain curl+chmod, Tier 1 `am`/`appman -e user/repo`, Tier 2
  getting listed in AM's curated catalog) — **none of this has been built
  yet**, still just researched/planned.
- **Not yet done, still needed if this direction is pursued:** the actual
  feasibility spike (build one PyInstaller/Nuitka bundle locally, confirm the
  full scientific stack — xarray/dask/zarr/icechunk/duckdb/pyarrow/altair/
  matplotlib — imports and runs, measure size/startup time) has NOT been run
  yet. This is the next concrete step if picking this thread back up.

### Separately, resolved short-term (already works, documented, not yet coded)

The AppImage/Homebrew thread above is about giving canvodpy a real
distribution channel later. Independent of that, "how do I invoke canvodpy
from anywhere, right now, with what's on PyPI today" is answered in the same
doc's "Resolved (short-term)" section:
- `uv tool install canvodpy` + `uv tool update-shell` for the published
  version (persistent, survives reboots — verified this isn't session-scoped)
- For local dev-checkout-with-live-edits: `uv sync` at the monorepo root, then
  `ln -s .../canvodpy-perf/.venv/bin/canvodpy ~/.local/bin/canvodpy` (the
  shim's shebang has an absolute path baked in, so it works from any CWD)
- `canvodpy run --site ... --start ... --end ...` etc. is real, pre-existing
  CLI syntax — verified directly in `canvodpy/src/canvodpy/cli/app.py` and
  `cli/run.py`, not improvised

## 4. Confirmed but NOT yet fixed: canvodpy can't fully run outside a git checkout

Found while answering the "invoke from anywhere" question, written up in
`dev/distribution_packaging_plan.md`'s "Prerequisite" section near the top.
Concrete, code-confirmed (not speculative):

- `canvodpy config init` (`canvodpy/src/canvodpy/cli/config.py`) reads its
  YAML templates (`canvod-settings.yaml.example`, `recipes/*.yaml`) from
  `monorepo_root / "config"` — **these templates are not bundled as package
  data in the wheel**, so this command fails outright ("Make sure you're
  running from the repository root") when canvodpy is installed standalone
  (`uv tool install`/pip) with no monorepo checkout present anywhere.
- Default config *directory* discovery (`find_monorepo_root()` in
  `canvod-utils/src/canvod/utils/config/loader.py`, plus an independently
  duplicated copy of the same logic in `cli/config.py`) walks up from
  `Path.cwd()` looking for `.git`, falling back to `cwd()/config` — never an
  XDG user-level location like `~/.config/canvodpy`. The override mechanism
  already works fine (`--config-dir`/`-c` flag, `CANVOD_CONFIG_FILE` env var —
  user confirmed passing an arbitrary config file already works), it's just
  the *default* that assumes a checkout.
- **Not implemented yet.** What's needed, in priority order (full detail in
  the doc): (1) bundle config templates as real package data in the wheel —
  this is the actual blocker; (2) default config dir to XDG, not
  monorepo/CWD; (3) consolidate the three duplicated "find monorepo root, else
  cwd" implementations into one shared helper.

## 5. Minor: reader API usage gotcha (not written to a doc, worth knowing)

`SbfReader`/`Rnxv3Obs` (and presumably all `GNSSDataReader` subclasses) are
Pydantic `BaseModel`s — constructor takes `fpath=` as a **keyword-only**
argument (positional `SbfReader('/path')` raises `TypeError`), and getting the
actual `xr.Dataset` requires calling `.to_ds()` — printing the reader object
itself just shows its repr, not the data. Confirmed in
`packages/canvod-readers/src/canvod/readers/base.py` (base class docstring
literally shows the `reader.to_ds()` pattern) and in both `sbf/reader.py` and
`rinex/v3_04.py`.

## Uncommitted / unrelated state currently in canvodpy-perf's working tree

Not part of this conversation's work — flagging so the next agent doesn't
confuse it with the above: `canvodpy/pyproject.toml` (added a `marimo`
dependency), `docs/guides/DEVELOPMENT.md` /
`docs/guides/architecture-design.md` / `docs/packages/utils/overview.md`
(fixing stale `canvod config ...` → `canvodpy config ...` command-name
references), `uv.lock`, plus untracked `dev/data_discovery_stats.py`,
`dev/nc_explorer.py`, `graphify-out/`, `packages/canvod-readers/graphify-out/`.
Appears to be separate/parallel work — verify with the user before touching.

## Suggested next steps, in rough priority order

1. Decide whether to actually fix the config-discovery/package-data issue
   (§4) — this is the one confirmed bug blocking real standalone usability,
   independent of whatever distribution channel gets chosen.
2. If pursuing the standalone-binary pivot (§3): run the PyInstaller/Nuitka
   feasibility spike that hasn't happened yet.
3. Otherwise/in parallel: `uv tool install canvodpy` already works today for
   anyone who just wants it invocable from anywhere — this needs no further
   engineering, just needs to become the documented recommendation if desired.
