# Optional Extensions

canvodpy ships as a lean core. Packages that only a subset of users need —
because their receivers use non-standard filenames, or because they run a
specific orchestrator — live in a separate repository so the core install
stays small and dependency-free by default:

**[github.com/nfb2021/canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions)**

canvodpy works fully without any of these. Each one is a drop-in: install
it, and canvodpy detects and uses it automatically — no code changes,
no config beyond what the package itself asks for.

## Available extensions

| Package | Purpose | Status |
|---|---|---|
| `canvod-filemap` | Recipe-based filename mapping for non-canonical GNSS filenames (proprietary receiver output, legacy RINEX v2 short names, custom layouts) | Available |
| `canvod-airflow` | Airflow DAG definitions (daily SBF/RINEX/SBF-agency + backfill) for canvodpy pipelines | Available |

## Installing an extension

Extensions are not published to PyPI. The monorepo's root `pyproject.toml`
already points `canvod-filemap` at the public repo over git, so a plain

```bash
uv sync --extra filemap
```

resolves and installs it on any machine — no sibling checkout required.

If you have both repositories cloned as sibling directories locally (common
for contributors iterating on `canvod-filemap` itself), you can override the
source in your own uncommitted local checkout to pick up changes without
reinstalling:

```toml
# pyproject.toml (local override — do not commit)
[tool.uv.sources]
canvod-filemap = { path = "../canvodpy-extensions/packages/canvod-filemap" }
```

!!! warning "Don't commit a local path source"

    A path-based source only works on machines that happen to have
    `canvodpy-extensions` cloned as a sibling directory. `uv` resolves
    optional-dependency-group sources even when the extra isn't requested,
    so committing a local path breaks `uv run`/`uv sync` for everyone else.
    Keep the git source in version control; only override it locally.

`canvod-airflow` is installed directly rather than via a canvodpy extra
(it depends on `canvodpy`, not the other way around — wiring it as a
`canvodpy` extra would create a circular reference):

```bash
uv add "canvod-airflow[airflow] @ git+https://github.com/nfb2021/canvodpy-extensions.git#subdirectory=packages/canvod-airflow"
```

See [canvod-airflow's overview](https://nfb2021.github.io/canvodpy-extensions/packages/airflow/overview/)
for DAG structure, deployment, and configuration.

## What happens if an extension isn't installed

canvodpy checks for each extension lazily, only where it's needed, and
falls back to sensible defaults:

- Without `canvod-filemap`: file discovery falls back to canonical
  canVOD-only glob patterns (`*.rnx`, `*.sbf`). Non-canonical filenames
  require the extension — see [Configuration → Optional: non-canonical
  filenames](configuration.md#optional-non-canonical-filenames).

You will never see an import error from a regular canvodpy install.
