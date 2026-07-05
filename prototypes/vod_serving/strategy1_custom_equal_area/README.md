# Strategy 1 — canvod equal-area as a plain xarray cube

**One line:** keep canvod's equal-area grid exactly; store the cube as plain
xarray on an unstructured `cell` axis with CF cell-bounds; emit zarr + netCDF.
Zero new dependencies.

## What it is

```
dims:        (pair, time, cell)            cell = canvod cell_id (6448 @ 2°)
data_vars:   vod_sum, vod_sumsq, count     additive moments → poolable mean/std
coords:      cell_theta(cell), cell_phi(cell)          centres [rad]
             theta_bounds(cell,4), phi_bounds(cell,4)  corners [rad], CF `bounds`
             solid_angle(cell) [sr]
attrs:       grid_type=equal_area, angular_resolution_deg=2.0,
             coordinate_frame=topocentric, Conventions=CF-1.10, provenance
outputs:     _out/strategy1_equal_area.zarr   (chunked on time, canonical)
             _out/strategy1_equal_area.nc     (single CF file, archival/DOI)
```

The spatial axis **is** canvod's `cell_id`. Geometry travels as CF coordinate
**bounds** (`cell_theta` → `theta_bounds`, `cell_phi` → `phi_bounds`), so the
cells are fully described without any grid library to *load* the data — only
`xarray`. To *render*, hand the per-cell vector straight to canvod-viz.

## How it complies with canvod

- Tessellation: `create_hemigrid("equal_area", 2.0)` — unchanged, the only
  scientifically-validated grid (see `../00_canvod_grids_viz_review.md` §2).
- Assignment: canvod's own `_build_kdtree` + `_query_points` (§3) — identical to
  what the production precomputes use, so binning matches existing products.
- Render: `HemisphereVisualizer.plot_2d` consumes `vod_sum/count` → mean; the
  round-trip proof `roundtrip_base_up.png` is produced from the **stored zarr**,
  confirming the cube is renderer-agnostic and lossless.

## Why store moments, not finished stats

`mean = Σsum/Σcount`, `std = √(Σsumsq/Σcount − mean²)`. Storing the additive
trio keeps every quantity exactly poolable over any concatenation of `time`
tiles (the whole point of tiling). Means/stds are derived on read.

## Pros / cons

**Pros**
- No new deps; readable by any xarray/Pangeo user; trivial round-trip to canvod.
- Preserves canvod grid identity bit-for-bit (cell_id is the axis).
- zarr (lazy, chunked, cloud) **and** single-file netCDF (DOI/archival) for free.
- CF bounds make the cells self-describing and renderer-agnostic.

**Cons**
- No native neighbour / multi-resolution / cell-algebra operators — those are
  DIY (you have centres + bounds, but no index structure).
- Not a "recognised" DGGS/UGRID object, so DGGS/unstructured tooling
  (xdggs, uxarray) won't auto-recognise it (though the data is standard).
- `cell` is just an integer index; cross-dataset joins rely on matching the
  same grid build (stable, but implicit).

## Distributability

- `.zarr` → object store / OSN / S3, lazy partial reads, chunked on `time`.
- `.nc`  → one file, Zenodo DOI, universally readable.
- (`.zarr.zip` trivially if a single-file zarr is wanted.)

## Notes / rough edges observed

- zarr-v3 emits an `UnstableSpecificationWarning` for fixed-length unicode coords
  (`pair`, `time`); harmless here. Could store `pair` as an int code + lookup,
  or `time` as int64 epoch, to silence it for stricter cross-reader portability.
- Consolidated metadata is non-standard in zarr-v3; kept for fast open, drop if
  targeting strict v3 readers.

## Run

```bash
cd canvodpy && uv run python ../grid_storage/strategy1_custom_equal_area/build.py
```
