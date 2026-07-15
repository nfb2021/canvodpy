# Notebooks

Interactive [marimo](https://marimo.io) notebooks covering the full canVODpy pipeline — from raw GNSS file reading to vegetation optical depth retrieval, versioned storage, and visualisation.

---

## Browser preview

Each notebook can be previewed read-only in [molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo):

!!! warning "Not runnable in the browser"

    canVODpy depends on native C extensions (icechunk, NumPy, xarray) that cannot
    compile to WebAssembly. The browser previews are **read-only** — the code is
    visible and navigable, but cells will not execute.
    To run the notebooks interactively, see [Run locally](#run-locally) below.

### Pipeline notebooks

| # | Notebook | Topic | Preview |
|---|---|---|---|
| 00 | CLI Quickstart | Raw GNSS files to a versioned VOD store with one `canvodpy` command | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/00_cli_quickstart.py) |
| 01 | Naming Convention & Validation | IGS/RINEX filename parsing and validation | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/01_naming_convention.py) |
| 02 | RINEX v3 Observation Reading | RINEX v3.04 → `xarray.Dataset` | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_rinex_reading.py) |
| 03 | Satellite Catalog | IGS SatelliteCatalog — PRN metadata | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/03_satellite_catalog.py) |
| 04 | SBF Binary Reading | Septentrio binary file reading | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_sbf_reading.py) |
| 05 | Ephemeris & Coordinate Augmentation | SP3/CLK augmentation, ECEF → spherical | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/05_ephemeris_coordinates.py) |
| 06 | Hemispheric Grids | Equal-area, equal-angle, geodesic, Fibonacci | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/06_hemispheric_grids.py) |
| 07 | VOD Retrieval | Tau-Omega radiative transfer model | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/07_vod_retrieval.py) |
| 08 | Icechunk Store | Versioned Icechunk/Zarr storage | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/08_icechunk_store.py) |
| 09 | Store Metadata & FAIR Compliance | DataCite/ACDD/STAC provenance | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/09_store_metadata.py) |
| 10 | Visualization | 2D/3D hemispheric plots | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/10_visualization.py) |
| 11 | Configuration & Diagnostics | Pydantic configuration models, two-track logging, `stage_timer` diagnostics | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/11_configuration.py) |

### API notebooks

| # | Notebook | Topic | Preview |
|---|---|---|---|
| 12 | API Overview | The CLI, `Site.pipeline()`, and the functional API side by side | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/12_api_overview.py) |
| 13 | Site Pipeline | `Site().pipeline().process_range()` — the path the CLI wraps | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/13_site_pipeline.py) |
| 14 | Functional API | L4 — pure functions in `canvodpy.functional` for custom pipelines | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/14_functional_api.py) |

### Workflow notebooks

| # | Notebook | Topic | Preview |
|---|---|---|---|
| 15 | Single-Day Workflow | End-to-end single-day processing: read, augment, grid, retrieve VOD | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/15_single_day_python.py) |
| 16 | Batch Processing | Multi-day processing — the CLI's primary use case, plus the equivalent L3 API | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/16_batch_processing.py) |
| 17 | Store Operations | Store read/write/branch operations, temporal aggregation, metadata queries | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/17_store_operations.py) |
| 18 | Grid Exploration | Interactive hemispheric grid explorer | [![molab](https://marimo.io/shield.svg)](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/18_grid_exploration.py) |

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
