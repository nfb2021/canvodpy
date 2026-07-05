# Strategy 3 — canvod equal-area as a UGRID unstructured mesh (uxarray)

**One line:** keep canvod's equal-area cells (grid identity preserved) but
express them as a first-class **UGRID unstructured mesh** — explicit nodes,
quad faces, and `face_node_connectivity` — the Pangeo home for arbitrary
tessellations.

## What it is

```
mesh:        UGRID-1.0   n_node=12604 nodes, n_face=6448 quad faces, connectivity
data_vars:   vod_sum, vod_sumsq, count   on (pair, time, n_face)   additive moments
outputs:     _out/strategy3_ugrid.nc     (UGRID netCDF, uxarray-native)
             _out/strategy3_ugrid.zarr   (same, zarr)
```

Each canvod equal-area cell becomes a **quad face**; its four bbox corners
become **nodes** (deduplicated so shared edges share nodes). `n_face` order **is**
canvod `cell_id`, so values line up cell-for-cell with Strategy 1 and with every
existing canvod product (the round-trip image is pixel-identical to Strategy 1).

## Topocentric → pseudo-geographic

uxarray expects lon/lat in degrees, so we map:
`node_lon = azimuth°`, `node_lat = 90 − zenith°` (zenith→+90 lat, horizon→0).
uxarray then computes `face_areas ≈ 9.57e-4 sr`, matching the true equal-area
`2π/6448 ≈ 9.75e-4 sr` — i.e. the mesh topology is geometrically faithful. As
with Strategy 2, **the lon/lat are not Earth coordinates**; they're a device to
use unstructured-grid machinery on a local sky.

## How it complies with canvod

- Cells, assignment (`_build_kdtree`/`_query_points`) and render
  (`HemisphereVisualizer.plot_2d`) are all canvod's — see
  `../00_canvod_grids_viz_review.md`. Only the *container* is UGRID.
- canvod already stores cells corner-wise in `grid_to_dataset`
  (`vertices_phi/theta`, `n_vertices`) — Strategy 3 is essentially that idea
  promoted to a standards-compliant UGRID mesh with shared nodes.
- Note: canvod's **geodesic** grid is *already* UGRID-shaped (shared `vertices`
  + `geodesic_vertices` index); the same builder would yield a triangular UGRID
  mesh with no corner dedup needed — a natural future variant.

## uxarray payoff

`ux.open_dataset(...)` returns a `UxDataset` whose `.uxgrid` understands the
topology: `n_node`, `n_face`, `face_areas`, neighbour/connectivity queries, and
uxarray's own viz (datashader/holoviews) and remapping. Verified in the build
output (areas computed from connectivity).

## Pros / cons

**Pros**
- Preserves canvod equal-area identity (face order = `cell_id`), like Strategy 1.
- Real, standards-compliant mesh topology (nodes/faces/connectivity) — works
  with *any* tessellation (quad now, triangular geodesic later), no HEALPix
  re-tessellation needed.
- uxarray ecosystem: areas, connectivity, unstructured remapping, viz.
- UGRID netCDF is a recognised geoscience standard (DOI/archival-friendly).

**Cons**
- Heaviest representation: stores explicit nodes + connectivity (n_node ≈ 2× n_face).
- Pseudo-geographic framing (same fiction as Strategy 2).
- Extra dep (`uxarray`, which pulls a large stack); the 0/360 azimuth seam is
  left as duplicate nodes (cosmetic; could be stitched with wrap logic).
- No hierarchical multi-resolution (that's HEALPix/Strategy 2's strength).

## Distributability

UGRID `.nc` (one file, standard, DOI) **and** zarr (lazy/cloud). uxarray reads
both. Larger than Strategies 1/2 due to explicit connectivity.

## Run

```bash
cd canvodpy && uv run --with uxarray \
    python ../grid_storage/strategy3_uxarray_ugrid/build.py
```
