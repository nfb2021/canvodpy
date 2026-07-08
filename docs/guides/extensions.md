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
| `canvod-airflow` | Airflow DAG definitions for canvodpy pipelines | Planned |

## Installing an extension

Extensions are not published to PyPI. Install directly from the repository
with `uv`:

```bash
uv add "canvod-filemap @ git+https://github.com/nfb2021/canvodpy-extensions.git#subdirectory=packages/canvod-filemap"
```

If you have both repositories cloned as sibling directories (common for
contributors working across the ecosystem), point `uv` at the local path
instead so changes in one are picked up without reinstalling:

```toml
# pyproject.toml
[tool.uv.sources]
canvod-filemap = { path = "../canvodpy-extensions/packages/canvod-filemap" }
```

```bash
uv sync --extra filemap
```

## What happens if an extension isn't installed

canvodpy checks for each extension lazily, only where it's needed, and
falls back to sensible defaults:

- Without `canvod-filemap`: file discovery falls back to canonical
  canVOD-only glob patterns (`*.rnx`, `*.sbf`). Non-canonical filenames
  require the extension — see [Configuration → Optional: non-canonical
  filenames](configuration.md#optional-non-canonical-filenames).

You will never see an import error from a regular canvodpy install.
