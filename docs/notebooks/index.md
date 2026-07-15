# Notebooks

Interactive [marimo](https://marimo.io) notebooks covering the full canVODpy pipeline — from raw GNSS file reading to vegetation optical depth retrieval, versioned storage, and visualisation.

---

## Rendered notebooks

Each notebook below is executed for real against real test data at doc-build
time (`marimo export html`) and frozen into a static page — source code
included, exactly as it appears in the editor. This is deliberate rather
than a fallback: marimo's WASM export (`html-wasm`) can run notebooks live
in the browser, but its default "app" mode hides code entirely, and the
alternatives (forcing code visibility, or duplicating code into markdown
text) either don't fit the run mode or make the notebooks harder to
maintain for their primary purpose — being read and adapted as reference
code. Every notebook also links to its source on
[molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo) for forking
and live editing.

### Pipeline notebooks

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 00 | CLI Quickstart | Raw GNSS files to a versioned VOD store with one `canvodpy` command | [Notebook](_build/00_cli_quickstart.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/00_cli_quickstart.py) |
| 01 | Naming Convention & Validation | IGS/RINEX filename parsing and validation | [Notebook](_build/01_naming_convention.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/01_naming_convention.py) |
| 02 | RINEX v3 Observation Reading | RINEX v3.04 → `xarray.Dataset` | [Notebook](_build/02_rinex_reading.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_rinex_reading.py) |
| 03 | Satellite Catalog | IGS SatelliteCatalog — PRN metadata | [Notebook](_build/03_satellite_catalog.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/03_satellite_catalog.py) |
| 04 | SBF Binary Reading | Septentrio binary file reading | [Notebook](_build/04_sbf_reading.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_sbf_reading.py) |
| 05 | Ephemeris & Coordinate Augmentation | SP3/CLK augmentation, ECEF → spherical | [Notebook](_build/05_ephemeris_coordinates.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/05_ephemeris_coordinates.py) |
| 06 | Hemispheric Grids | Equal-area, equal-angle, geodesic, Fibonacci | [Notebook](_build/06_hemispheric_grids.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/06_hemispheric_grids.py) |
| 07 | VOD Retrieval | Tau-Omega radiative transfer model | [Notebook](_build/07_vod_retrieval.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/07_vod_retrieval.py) |
| 08 | Icechunk Store | Versioned Icechunk/Zarr storage | [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/08_icechunk_store.py) only — rendered snapshot pending a test-data fixture fix |
| 09 | Store Metadata & FAIR Compliance | DataCite/ACDD/STAC provenance | [Notebook](_build/09_store_metadata.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/09_store_metadata.py) |
| 10 | Visualization | 2D/3D hemispheric plots | [Notebook](_build/10_visualization.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/10_visualization.py) |
| 11 | Configuration & Diagnostics | Pydantic configuration models, two-track logging, `stage_timer` diagnostics | [Notebook](_build/11_configuration.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/11_configuration.py) |

### API notebooks

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 12 | API Overview | The CLI, `Site.pipeline()`, and the functional API side by side | [Notebook](_build/12_api_overview.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/12_api_overview.py) |
| 13 | Site Pipeline | `Site().pipeline().process_range()` — the path the CLI wraps | [Notebook](_build/13_site_pipeline.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/13_site_pipeline.py) |
| 14 | Functional API | L4 — pure functions in `canvodpy.functional` for custom pipelines | [Notebook](_build/14_functional_api.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/14_functional_api.py) |

### Workflow notebooks

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 15 | Single-Day Workflow | End-to-end single-day processing: read, augment, grid, retrieve VOD | [Notebook](_build/15_single_day_python.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/15_single_day_python.py) |
| 16 | Batch Processing | Multi-day processing — the CLI's primary use case, plus the equivalent L3 API | [Notebook](_build/16_batch_processing.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/16_batch_processing.py) |
| 17 | Store Operations | Store read/write/branch operations, temporal aggregation, metadata queries | [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/17_store_operations.py) only — rendered snapshot pending a test-data fixture fix |
| 18 | Grid Exploration | Interactive hemispheric grid explorer | [Notebook](_build/18_grid_exploration.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/18_grid_exploration.py) |

17 of 19 notebooks render; 2 (08, 17) currently link to source only, until
their bundled store fixture is fixed. See
`dev/notebook_docs_integration_plan.md` in the repo for the full technical
writeup, and `scripts/export_demo_notebooks.sh` / `just docs-export-notebooks`
for how these are rebuilt.

!!! note "Source links currently point at `main`"
    The molab source links above resolve once the notebook restructuring
    branch is pushed and merged into `canvodpy-demo`'s `main` — until then
    they 404. The rendered notebook pages work regardless, since they're
    built from the local checkout.

---

## Run locally

To run the notebooks interactively, clone (or fork)
[canvodpy-demo](https://github.com/nfb2021/canvodpy-demo) and install
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

### 1. Clone

```bash
git clone https://github.com/nfb2021/canvodpy-demo.git
cd canvodpy-demo
```

### 2. Run a notebook

Each notebook declares its own dependencies via a [PEP 723](https://peps.python.org/pep-0723/)
header. `uv` resolves and installs them automatically on first run — no `uv sync`
or manual setup required.

```bash
# Interactive editing
uv run marimo edit 07_vod_retrieval.py

# Read-only app mode
uv run marimo run 07_vod_retrieval.py
```

### 3. Test data

Notebooks that read GNSS data download the test dataset (~1.7 GB) automatically
from [Zenodo](https://zenodo.org/records/19708760) on first run and cache it at
`~/.cache/canvodpy/`. Subsequent runs are instant.

To use a local copy instead, clone the test data into `test_data/`:

```bash
git clone https://github.com/nfb2021/canvodpy-test-data.git test_data
```

`_paths.py` detects this directory automatically and skips the Zenodo download.
