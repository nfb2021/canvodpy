# Migration Plan: `canvod-airflow` extraction from canvodpy-perf → canvodpy-extensions

Planned 2026-07-08. Mirrors the precedent set by the `canvod-filemap` extraction
(now living at `canvodpy-extensions/packages/canvod-filemap`). Not yet executed —
see Open Questions before starting.

## 0. Research findings (verified)

**Airflow integration in canvodpy-perf — confirmed inventory:**

| Artifact | Path | Fate |
|---|---|---|
| Daily DAGs (3 DAG factories/site, 424 lines) | `dags/gnss_daily_processing.py` | **Moves** |
| Backfill DAG (240 lines) | `dags/gnss_backfill.py` | **Moves** |
| Deployment notes | `dags/README.md` | **Moves** (merged into package README; content is stale — describes an old 4-task/6-hour DAG, current DAGs are `@daily` with 6–8 tasks) |
| User guide (412 lines) | `docs/guides/airflow.md` | **Moves** (adapted), replaced by pointer |
| DAG structure tests (AST-based, no Airflow needed) | `canvodpy/tests/test_dag_structure.py` | **Moves** (hardcodes `parents[2] / "dags"`, must be re-pathed) |
| Task functions (10 public fns) | `canvodpy/src/canvodpy/workflows/tasks.py` | **Stays** — plain-Python functional API, no Airflow import |
| Task tests | `canvodpy/tests/test_airflow_tasks.py`, `test_task_serialization.py`, `test_fluent_workflow.py`, `test_workflow_integration.py` | **Stay** (they test `canvodpy.workflows.tasks`, not the DAGs) |

**Exact dependency surface of the two DAG files** (all deferred into task bodies except `structlog` and `airflow.*`):
- `canvodpy.workflows.tasks`: `validate_data_dirs`, `check_sbf`, `check_rinex`, `check_sp3_availability`, `fetch_aux_data`, `process_sbf`, `process_rinex`, `validate_ingest`, `calculate_vod`, `cleanup`
- `canvod.utils.config.load_config` (parse-time, wrapped in try/except), `canvod.utils.tools.YYYYDOY`
- Top-level: `structlog`, `airflow.decorators`, `airflow.utils.trigger_rule`, `airflow.models.param`; task-level: `airflow.sensors.base.PokeReturnValue`

All canvodpy-side imports are covered by the single PyPI dependency `canvodpy` (v0.3.0 is live on PyPI, `requires-python >=3.14`; `canvod-utils` is a transitive dep). **apache-airflow 3.3.0 supports Python 3.14** (`requires_python: >=3.10,!=3.15`), so the extensions repo's py3.14-only policy is not a blocker — but see risk R1 about the `!=3.15` exclusion.

**n8n — confirmed: nothing to migrate.** Exhaustive sweep (filename search, grep across `.json/.yml/.yaml/.py/.toml`, docker-compose search) found only aspirational mentions in `dev/todo_later.md` (lines 170–171, 342, 979–980), `dev/config_redesign.md` (98, 242), `dev/perf_plan_phase1.md` (540, 577, 627), plus an unrelated zensical icon in `.venv`. Notably `todo_later.md:170` marks the interface question **RESOLVED (2026-07-08)**: CLI wrapping `Site.pipeline()` is primary; Airflow/n8n are consumers. No workflow JSON, no code. Purely aspirational — nothing to do.

**Extensions-repo precedent — confirmed with two corrections to the initial briefing:**
- Dynamic `packages/*/` discovery confirmed in `Justfile` `build-all` and both `publish_pypi.yml` / `publish_testpypi.yml` — **no CI/Justfile edits needed** for a new package.
- Correction 1: `packages/canvod-filemap/pyproject.toml` `[project.urls]` point at `github.com/nfb2021/canvodpy` (the **core** repo), *not* canvodpy-extensions. Pre-existing inconsistency; `canvod-airflow` should point at the extensions repo, and fixing filemap's URLs is a candidate drive-by.
- Correction 2 / inconsistency: `canvod-filemap` is **not on PyPI** (404) even though the extensions repo has OIDC publish workflows, and `canvodpy-perf/docs/guides/extensions.md` explicitly says "Extensions are not published to PyPI — install via git+…#subdirectory=". Install docs for `canvod-airflow` must follow the git-subdirectory pattern unless publishing is activated first.
- Commitizen: lockstep versioning, `version_files` in root `pyproject.toml` currently lists only filemap; both packages sit at **0.3.0**, so `canvod-airflow` must start at **0.3.0** (commitizen requires a single shared version).

---

## 1. Ordered migration steps

### Phase A — Create the package in canvodpy-extensions

**A1. Package skeleton** `packages/canvod-airflow/`:
```
packages/canvod-airflow/
├── pyproject.toml
├── pytest.ini              # copy filemap's verbatim
├── Justfile                # copy filemap's verbatim
├── README.md               # merged from dags/README.md + deployment sections of docs/guides/airflow.md
├── CLAUDE.md               # mirror filemap's CLAUDE.md shape (module table, gotchas, test cmd)
├── src/canvod/airflow/
│   ├── __init__.py         # docstring + version; do NOT import airflow here (keep importable w/o airflow for tooling)
│   ├── daily_processing.py # from dags/gnss_daily_processing.py, unchanged logic
│   └── backfill.py         # from dags/gnss_backfill.py, unchanged logic
└── tests/
    ├── conftest.py
    └── test_dag_structure.py  # migrated from canvodpy/tests/, DAGS_DIR → module source paths
```

**A2. `pyproject.toml`** (mirroring filemap's shape):
- `name = "canvod-airflow"`, `version = "0.3.0"`, `requires-python = ">=3.14"` (see R1 for whether to cap `<3.15`)
- `[build-system]` `uv_build`; `[tool.uv.build-backend] module-name = "canvod.airflow"`
- `[project.urls]` → `https://github.com/nfb2021/canvodpy-extensions` (not the core repo — deliberate divergence from filemap's current, wrong URLs)
- Dependencies (recommended; see Open Questions):
  - `structlog>=23.0` — hard (module-level import)
  - `canvodpy>=0.3.0` — hard (resolvable from PyPI; the deferred-import "parse-time safety" in the DAGs stays as defensive coding)
  - `apache-airflow>=3.0` — **optional extra** `[project.optional-dependencies] airflow = ["apache-airflow>=3.0"]`, matching today's "provided by the deployment environment" model and keeping the workspace `uv.lock` free of Airflow's ~100-package tree. Note: `uv lock` resolves extras, so even as an extra it enters `uv.lock` — verify resolution on py3.14 during execution (R1).

**A3. Source moves** (git-history-preserving where possible — different repos, so realistically `git mv` is unavailable; copy with a commit message citing origin SHA):
- `dags/gnss_daily_processing.py` → `src/canvod/airflow/daily_processing.py`
- `dags/gnss_backfill.py` → `src/canvod/airflow/backfill.py`
- Only required code change: none for logic. Both files already self-register DAGs (`globals()[...]` loop / `canvod_backfill()` call) — Airflow ≥2.4 DAG auto-registration handles module-level instantiation.

**A4. DAG discovery shim** — since DAGs now live in site-packages, not `dags_folder`, the README must document the standard shim pattern (replaces the old symlink instructions):
```python
# <airflow_dags_folder>/canvod_dags.py
from canvod.airflow.daily_processing import *  # noqa: F403  (airflow dag)
from canvod.airflow.backfill import *  # noqa: F403
```
(The words "airflow" and "dag" must appear in the shim for the DagBag keyword pre-filter.)

**A5. Tests**:
- Migrate `test_dag_structure.py` — AST/regex checks, no Airflow needed; re-point `DAGS_DIR` to `Path(canvod.airflow.__file__).parent` and the two new module filenames.
- Add a `pytest.importorskip("airflow")`-guarded DagBag import test (parses both modules, asserts zero import errors, asserts `canvod_backfill` exists) so it runs only when the `airflow` extra is installed.

### Phase B — Root-level canvodpy-extensions integration

All in `canvodpy-extensions/`:

1. `pyproject.toml`:
   - `[tool.commitizen] version_files` += `"packages/canvod-airflow/pyproject.toml:version"` (mandated by `CONTRIBUTING.md:158`)
   - `[tool.pytest.ini_options] testpaths` += `"packages/canvod-airflow/tests"`
   - `[tool.coverage.run] source` += `"packages/canvod-airflow/src"`
   - Header comment block: drop "(planned)" from the canvod-airflow line
2. `README.md` package table: flip to `[`canvod-airflow`](packages/canvod-airflow) | Airflow DAGs (daily SBF/RINEX/SBF-agency + backfill) for canvodpy pipelines | Available`
3. `CLAUDE.md`: project-structure table row → namespace `canvod.airflow`, Status Available; skills table row for `airflow-dag-patterns` loses "(planned)"
4. `docs/index.md`: flip the `canvod-airflow` grid card from *(planned)* to a real card linking `packages/airflow/overview.md`
5. New docs pages:
   - `docs/packages/airflow/overview.md` — adapted from perf's `docs/guides/airflow.md` (architecture, retry-driven scheduling, the three DAG variants + backfill, deployment via shim, multi-config options). Strip perf-internal file-layout references (`dags/`, `canvodpy/src/...`) and point at `canvodpy.workflows.tasks` as the upstream API.
   - `docs/api/canvod-airflow.md` — mkdocstrings page (`::: canvod.airflow`, `::: canvod.airflow.daily_processing`, `::: canvod.airflow.backfill`). **Caveat:** mkdocstrings must import the modules, and they import `airflow` at top level; `deploy_docs.yml` runs `uv sync --locked --dev`, which does *not* install extras. Either (a) add `apache-airflow` to the docs sync (`uv sync --all-extras`), or (b) skip mkdocstrings for these two modules and hand-write the API page. Decide at execution (see O2).
6. `zensical.toml` nav: under Packages add `{ "canvod-airflow" = [{ "Overview" = "packages/airflow/overview.md" }] }`; under API Reference add `{ "canvod.airflow" = "api/canvod-airflow.md" }`
7. `REUSE.toml`: no change needed — `path = "**"` aggregate annotation covers new files.
8. Justfile / `.github/workflows/*`: **no changes** (dynamic discovery verified).
9. `uv sync` regenerates `uv.lock` (this is where R1 surfaces if resolution fails).

### Phase C — Release from canvodpy-extensions

Per `CONTRIBUTING.md`: `just release 0.4.0` (tests → changelog → `cz bump` updates both packages' versions in lockstep → tag `v0.4.0`). If PyPI publishing is not activated (canvod-filemap is currently 404 on PyPI), the installable artifact remains the git URL:
`uv add "canvod-airflow @ git+https://github.com/nfb2021/canvodpy-extensions.git#subdirectory=packages/canvod-airflow"`

### Phase D — canvodpy-perf cleanup (only after C is tagged)

All in `canvodpy-perf/`:

1. Delete `dags/` (all three files).
2. Delete `canvodpy/tests/test_dag_structure.py` (migrated in A5).
3. `docs/guides/airflow.md`: replace with a short stub — "Airflow DAGs moved to canvod-airflow in canvodpy-extensions" + install snippet + link — or delete entirely and rely on `docs/guides/extensions.md`. Keeping a stub preserves inbound links; recommend stub for one release, delete later.
4. `zensical.toml` line 46: keep `{ "Airflow Integration" = "guides/airflow.md" }` if stubbed, else remove.
5. `docs/guides/extensions.md` line 19: flip `canvod-airflow` row from Planned → Available; add the git-install snippet mirroring filemap's (line 27).
6. Root `pyproject.toml`:
   - Line 7: delete the dead `exclude = ["packages/canvod-streamstats", "packages/canvod-filemap"]` entries (neither dir exists) — the requested drive-by cleanup.
   - Line 128: remove `"dags/**"` from `[tool.ty.src] exclude` (dir gone).
7. Grep-check remaining references: `docs/index.md:136` (mentions Airflow only as a consumer of the functional API — fine, stays), `README.md` Airflow badge (fine, canvodpy still ships Airflow-ready task functions), `CLAUDE.md:28-29` skills rows (fine — `canvodpy.workflows.tasks` remains Airflow-adjacent; optionally annotate they now serve the external package).
8. Keep `canvodpy/src/canvodpy/workflows/tasks.py` docs intact — sections of the old `guides/airflow.md` documenting the task functions ("Task Functions", "Calling Tasks Without Airflow") arguably belong to canvodpy, not the extension. Consider salvaging those into a perf-side `docs/guides/workflow-tasks.md` rather than losing them (O4).
9. Optional: add `airflow = ["canvod-airflow"]` to `canvodpy/pyproject.toml` `[project.optional-dependencies]` mirroring `filemap = [...]` — but this creates a benign extra→base dependency cycle (canvod-airflow depends on canvodpy) and, like the filemap extra, is unresolvable for end users until extensions are on PyPI. Recommend **not** adding it (O3).

---

## 2. Open questions / risks needing a human decision

- **R1 — `apache-airflow` py3.14/3.15 resolution.** Airflow 3.3.0 declares `>=3.10,!=3.15`. The extensions workspace declares `requires-python = ">=3.14"` (unbounded), and uv refuses to lock a dependency whose python range doesn't cover the member's full range. `canvod-airflow` (or the extra carrying apache-airflow) likely needs `requires-python = ">=3.14,<3.15"` or an environment marker. Verify with `uv lock` on day one.
- **O1 — apache-airflow: hard dep vs extra vs undeclared peer.** Recommended: extra (`canvod-airflow[airflow]`), preserving today's "Airflow env provides Airflow" model and keeping CI light. Hard dep is defensible (modules import it unconditionally) but drags ~100 packages into `uv.lock` and docs CI. Human call.
- **O2 — mkdocstrings API page needs airflow importable in docs CI** (or hand-written API page / deferred top-level imports). Tied to O1.
- **O3 — `canvodpy[airflow]` extra in perf?** Mild circularity + extensions not on PyPI → recommend no; the existing `filemap` extra has the same not-on-PyPI problem and is worth flagging as its own inconsistency.
- **O4 — Where the task-function documentation lives.** `canvodpy.workflows.tasks` stays in perf; ~40% of `guides/airflow.md` documents it. Split the doc rather than moving it wholesale.
- **O5 — PyPI publishing activation.** Extensions repo has full OIDC publish workflows, but canvod-filemap was never published and perf docs say "not published to PyPI". Decide whether the `v0.4.0` release should be the first actual PyPI publish (would simplify all install docs and unblock O3).
- **O6 — Versioning.** Lockstep forces `canvod-airflow` to be born at 0.3.0 and released as 0.4.0 alongside a filemap bump with no filemap changes. Acceptable per repo policy, but confirm.
- **O7 — Config loading at parse time.** `_get_configured_sites()` runs `load_config()` inside the Airflow scheduler's parse loop on every DagBag refresh. No change strictly required for the move, but the packaged context is a natural moment to add the `config_path` Variable/Param support the guide describes (Options 1–3 in `guides/airflow.md` are documented but only partially implemented). Recommend deferring — keep the extraction a pure move.
- **n8n — resolved:** nothing exists; nothing to migrate; no `canvod-n8n` placeholder warranted (the `todo_later.md` decision already routed automation through the CLI).

### Critical files for implementation
- `canvodpy-perf/dags/gnss_daily_processing.py`
- `canvodpy-perf/dags/gnss_backfill.py`
- `canvodpy-extensions/pyproject.toml`
- `canvodpy-extensions/packages/canvod-filemap/pyproject.toml` (template for the new package)
- `canvodpy-perf/pyproject.toml` (workspace exclude + ty exclude cleanup)
- `canvodpy-perf/docs/guides/airflow.md`
