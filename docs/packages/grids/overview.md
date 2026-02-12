# canvod-grids

## Purpose

The `canvod-grids` package provides spatial grid implementations for hemispheric GNSS signal analysis. It discretizes the hemisphere visible from a ground-based receiver into cells, which is required for spatially resolved VOD estimation.

## Grid Types

Seven grid implementations are available, all inheriting from `BaseGridBuilder`:

| Builder | Grid Type | Notes |
|---------|-----------|-------|
| `EqualAreaBuilder` | Equal-area | Cells of approximately equal solid angle (recommended) |
| `EqualAngleBuilder` | Equal-angle | Regular angular spacing; cells near zenith are smaller |
| `EquirectangularBuilder` | Equirectangular | Simple rectangular latitude/longitude grid |
| `HEALPixBuilder` | HEALPix | Hierarchical Equal Area isoLatitude Pixelization (requires `healpy`) |
| `GeodesicBuilder` | Geodesic | Icosahedron subdivision; near-uniform cell area |
| `FibonacciBuilder` | Fibonacci | Fibonacci-sphere sampling (requires `scipy`) |
| `HTMBuilder` | HTM | Hierarchical Triangular Mesh |

All builders accept `angular_resolution` (degrees) and produce a `GridData` object.

## Usage

### Factory function

```python
from canvod.grids import create_hemigrid

grid = create_hemigrid("equal_area", angular_resolution=5.0)
```

### Builder pattern

```python
from canvod.grids import EqualAreaBuilder

builder = EqualAreaBuilder(angular_resolution=5.0, cutoff_theta=10.0)
grid = builder.build()
```

### Via canvodpy factory

```python
from canvodpy import GridFactory

builder = GridFactory.create("equal_area", angular_resolution=5.0)
grid = builder.build()
```

## GridData

The `GridData` object returned by all builders provides:

- `df` — Polars DataFrame with cell geometry (boundaries, centers, solid angles)
- `ncells` — Total number of grid cells
- `nbands` — Number of elevation bands
- `definition` — Human-readable grid description

## Operations

Functions in `canvod.grids.operations` handle the interface between grids and xarray Datasets:

| Function | Purpose |
|----------|---------|
| `add_cell_ids_to_ds_fast` | Assign each observation to a grid cell |
| `add_cell_ids_to_vod` | Assign cell IDs to VOD datasets |
| `add_cell_ids_to_vod_fast` | Assign cell IDs to VOD datasets (KD-tree accelerated) |
| `grid_to_dataset` | Convert GridData to an xarray Dataset |
| `extract_grid_vertices` | Get cell boundary polygons |
| `store_grid` / `load_grid` | Persist and load grid definitions |

## Aggregation

`CellAggregator` and associated functions compute summary statistics over grid cells:

- `aggregate_data_to_grid` — Assign data to grid cells and aggregate
- `compute_hemisphere_percell` — Per-cell statistics across the full hemisphere
- `compute_zenith_percell` — Zenith-weighted per-cell statistics
- `compute_percell_timeseries` — Per-cell time series
- `compute_global_average` / `compute_regional_average` — Spatial averages
- `analyze_diurnal_patterns` / `analyze_spatial_patterns` — Pattern analysis

## Analysis Subpackage

`canvod.grids.analysis` provides per-cell and global analysis tools:

| Module | Purpose |
|--------|---------|
| `filtering` | Global statistical filters (IQR, Z-score) |
| `per_cell_filtering` | Per-cell variants of the above filters |
| `hampel_filtering` | Hampel (median-MAD) outlier filtering |
| `sigma_clip_filter` | Numba-accelerated sigma-clipping |
| `masking` | Spatial and temporal mask construction |
| `weighting` | Per-cell weight calculators |
| `solar` | Solar geometry (elevation, azimuth) |
| `temporal` | Weighted temporal aggregation and diurnal analysis |
| `spatial` | Per-cell spatial statistics |
| `per_cell_analysis` | Multi-dataset per-cell VOD analysis |
| `analysis_storage` | Persistent Icechunk storage for results (requires `canvod-store`) |

## Workflows

`canvod.grids.workflows` contains the end-to-end pipeline classes that tie together filtering, grid operations, and Icechunk persistence. This module requires `canvod-store` at runtime.

- `AdaptedVODWorkflow` — Full pipeline: filtering, grid operations, Icechunk persistence
- `get_workflow_for_store` — Create a workflow from an existing Icechunk store path
- `check_processed_data_status` — Check which dates have already been processed

## Role in the VOD Pipeline

Grids discretize the hemisphere above the receiver into cells. Each GNSS satellite observation is assigned to a grid cell based on its elevation and azimuth angles (computed by canvod-auxiliary). VOD is then estimated per cell or aggregated across the hemisphere.

## Coordinate Convention

All grids use standard spherical coordinates:

- **phi** — Azimuth angle, 0 to 2pi (0 = North, pi/2 = East, clockwise)
- **theta** — Polar angle from zenith, 0 to pi/2 (0 = zenith, pi/2 = horizon)
