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
| `canvod-adapters` | Bidirectional data adapters between canvodpy and third-party GNSS-VOD tools (gnssvod) | Available |

## Installing an extension

Extensions are released on GitHub only, each package under its own tag
`<package>-v<version>` (e.g. `canvod-filemap-v1.0.0`), never on PyPI.

In a clone of this repository, `canvod-filemap` is the dependency group
`filemap`. The root `pyproject.toml` points it at a release tag of the
public repo, so

```bash
uv sync --group filemap
```

installs that release on any machine, no sibling checkout required. The
group exists only in this repository: it is not part of the `canvodpy`
package on PyPI, so `pip install "canvodpy[filemap]"` does not exist.
Elsewhere, install the package from its tag:

```bash
uv add "canvod-filemap @ git+https://github.com/nfb2021/canvodpy-extensions.git@canvod-filemap-v1.0.0#subdirectory=packages/canvod-filemap"
```

The group is pinned in the root `pyproject.toml`: the version range in
`[dependency-groups]`, the tag in `[tool.uv.sources]`:

```toml
[dependency-groups]
filemap = ["canvod-filemap>=1.0.0"]

[tool.uv.sources]
canvod-filemap = { git = "https://github.com/nfb2021/canvodpy-extensions.git", subdirectory = "packages/canvod-filemap", tag = "canvod-filemap-v1.0.0" }
```

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
    every dependency group's sources when it locks, even groups that are
    not installed, so committing a local path breaks `uv sync` for
    everyone else.
    Keep the git source in version control; only override it locally.

See [canvod-filemap's overview](https://nfb2021.github.io/canvodpy-extensions/packages/filemap/overview/)
for the recipe format and mapping API.

`canvod-airflow` is installed directly (it depends on `canvodpy`, not the
other way around):

```bash
uv add "canvod-airflow[airflow] @ git+https://github.com/nfb2021/canvodpy-extensions.git@canvod-airflow-v1.0.0#subdirectory=packages/canvod-airflow"
```

See [canvod-airflow's overview](https://nfb2021.github.io/canvodpy-extensions/packages/airflow/overview/)
for DAG structure, deployment, and configuration.

`canvod-adapters` is installed directly wherever you exchange data with
another program:

```bash
uv add "canvod-adapters[store] @ git+https://github.com/nfb2021/canvodpy-extensions.git@canvod-adapters-v1.0.0#subdirectory=packages/canvod-adapters"
```

See [canvod-adapters's overview](https://nfb2021.github.io/canvodpy-extensions/packages/adapters/overview/)
for the gnssvod conversion, including how merged VOD bands are imported.

## What happens if an extension isn't installed

canvodpy checks for each extension lazily, only where it's needed, and
falls back to sensible defaults:

- Without `canvod-filemap`: file discovery falls back to canonical
  canVOD-only glob patterns (`*.rnx`, `*.sbf`). Non-canonical filenames
  require the extension — see [Configuration → Optional: non-canonical
  filenames](configuration.md#optional-non-canonical-filenames).

You will never see an import error from a regular canvodpy install.
