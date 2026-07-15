# Demo notebook → docs integration plan

Status: **implemented**. Companion to the `refactor/demo-notebooks-cli-first`
work (19 restructured notebooks in the `demo/` submodule, commit `345759d`).

Built: `scripts/export_demo_notebooks.sh` + `just docs-export-notebooks`
(all 19 notebooks minus 2 skipped, static `marimo export html`), callouts on
all 20 planned docs pages, `docs/notebooks/index.md` rewritten as the full
catalogue, `docs/index.md` CTA, `.github/workflows/deploy_docs.yml` wired
to export before build. Verified with a real `zensical build` (no new
"page does not exist" warnings vs. baseline) and a local `http.server`
smoke test against the built `site/`.

## 1. WASM was tried first, then dropped — here's why

`marimo export` has two backends:

| Backend | What it does |
|---|---|
| `marimo export html-wasm <nb>.py -o <dir>` | Ships the notebook + a Pyodide runtime; can run **live, in the reader's browser** |
| `marimo export html <nb>.py -o <file>` | Runs the notebook for real at **build time** and freezes it into static HTML, source code included by default |

First pass split notebooks between the two: `html-wasm` for anything that
doesn't touch Icechunk (`icechunk` — canvod-store's core dependency —
publishes no `wasm32`/`emscripten` wheel and its sdist needs a Rust
toolchain Pyodide doesn't have, so store-bound notebooks can't import it in
a WASM sandbox), static `html` for the rest.

That split was correct on the import-graph question but wrong on the actual
goal. `html-wasm`'s default `run` mode is **app mode — it hides code
entirely**, showing only outputs. The available escape hatches don't fit:
`--show-code` only applies to run mode and doesn't restore the point of a
teaching notebook, and `--mode edit` gives a live editable notebook but
still doesn't solve the underlying issue for a *documentation* embed. The
real problem: to make a run-mode WASM notebook show its code, you'd have to
duplicate the code into `mo.md(...)` markdown text (which is exactly the
"illustrative code block" pattern already used in a few notebooks for
prose asides) — applied notebook-wide, that duplication becomes a
maintenance burden and makes the *actual* editable notebook clunkier for
its primary use.

Static `html` export already includes code by default (`--include-code`,
confirmed via `--help` and by inspecting the exported HTML for codemirror
elements) — no duplication needed. Once that was clear, there was no
reason to keep two export mechanisms: **all 19 notebooks now export via
static `html`**, uniformly. The icechunk/WASM incompatibility that started
this investigation is moot once WASM isn't in the picture at all.

## 2. Two real bugs found while building this

- **`load_config()` resolution breaks across the submodule boundary.**
  `canvod.config.get_default_config_dir()`'s "dev-mode convenience" walk
  stops at `demo/`'s own `.git`, so bare `load_config()` calls (14's real
  `read_rinex(..., write_global_attrs=True)` cell, which calls
  `canvod.readers.gnss_specs.metadata.load_config()` internally) fell
  through to the XDG default and failed on any machine without
  `~/.config/canvodpy/`. Fixed by exporting `CANVOD_CONFIG_DIR` to the real
  repo-root `config/` before running exports (both in the script and the
  CI workflow) — no code changes needed, just the documented env var.
- **The molab source links resolve against `main`, which doesn't have any
  of this work.** `refactor/demo-notebooks-cli-first` is a local-only
  branch — nothing has been pushed to `canvodpy-demo` on GitHub. Every
  molab link added to the docs currently 404s with "Could not download the
  file from GitHub." This is expected, not a bug in the docs build; it
  resolves once the branch is pushed (and the links updated to point at it,
  or at `main` once merged). Flagged inline in `docs/notebooks/index.md`
  so it isn't a silent surprise; not fixed here per explicit instruction
  to leave the push for later.

## 3. Build mechanism

`scripts/export_demo_notebooks.sh`, invoked via `just docs-export-notebooks`:

```bash
NOTEBOOKS=(00_cli_quickstart 01_naming_convention ... 18_grid_exploration)  # 17 of 19
for nb in "${NOTEBOOKS[@]}"; do
    uv run --project "$REPO_ROOT" marimo export html "${nb}.py" -o "$OUT_DIR/${nb}.html"
done
```

`08_icechunk_store` and `17_store_operations` are excluded: their bundled
`rosalia_rinex` store fixture is an empty first-commit snapshot with no
populated data, so export fails with `IcechunkError: object not found`.
Pre-existing, not introduced by this pipeline — fix the fixture, then add
both names back into the list.

Wired into `.github/workflows/deploy_docs.yml` (submodule checkout, `canvodpy
config init` for a settings file, export step before `zensical build`).
Each static export is ~100-170KB (vs. ~27MB per WASM bundle in the
abandoned approach) — 17 exports total a few MB, not hundreds.

## 4. Placement: link notebooks *from* the docs pages that discuss them

Per the explicit ask — not a lazy append, contextual links back from the
package/guide pages that already discuss the relevant functionality:

| Docs page (`zensical.toml` nav) | Notebook(s) |
|---|---|
| `guides/quickstart.md` | 00 |
| `index.md` (homepage) | "Browse interactive notebooks" CTA → `notebooks/index.md` |
| `packages/naming/overview.md` (canvod-preflight) | 01 |
| `packages/readers/rinex-format.md` | 02 |
| `packages/readers/satellite-catalog.md` | 03 |
| `packages/readers/sbf.md`, `sbf-decoding.md` | 04 |
| `packages/readers/ephemeris-sources.md` + `packages/auxiliary/coordinates.md`, `interpolation.md` | 05 |
| `packages/grids/overview.md` | 06, 18 |
| `packages/vod/overview.md` | 07 |
| `packages/store/overview.md`, `icechunk.md`, `storage-strategies.md` | 08, 17 (source link only, pending fixture fix) |
| `packages/store-metadata/overview.md` | 09 |
| `packages/viz/overview.md` | 10 |
| `guides/configuration.md` + `guides/diagnostics.md` | 11 |
| `guides/api-levels.md` | 12, 13, 14, 15 |
| `guides/parallel-processing.md` | 16 |

Callout convention on each page:

```markdown
!!! example "Try it"
    [02 — RINEX v3 Observation Reading](../../notebooks/_build/02_rinex_reading.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_rinex_reading.py)
```

`docs/notebooks/index.md` stays the full browsable catalogue for the
"browse everything" path; the per-page callouts are the "found it while
reading about the thing" path. Both point at the same built assets.

## 5. Remaining follow-ups (not yet actioned)

1. Push `refactor/demo-notebooks-cli-first` to `canvodpy-demo` on GitHub
   (branch and/or PR — user's call) so molab source links resolve.
2. Fix the `rosalia_rinex` store fixture so 08/17 can join the export list.
3. Once demo work is pushed, decide whether molab links should point at the
   feature branch until merge, or wait for merge to `main`.
