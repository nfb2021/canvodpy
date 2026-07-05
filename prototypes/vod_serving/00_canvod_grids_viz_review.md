# Code review — `canvod-grids` & `canvod-viz`

> Purpose: understand exactly how canvod tessellates the hemisphere, assigns
> observations to cells, serialises grids, and renders them — so the three
> storage strategies in this folder are **fully compliant** (reuse canvod's
> grid + viz rather than reimplementing geometry). Also flags what is
> **incomplete** in canvod so we don't build on sand.
>
> Reviewed at commit on branch `master`; canvodpy monorepo `packages/`.

---

## 1. The data model: `GridData`

`canvod.grids.core.grid_data.GridData` — a **frozen dataclass**, the single
container every builder returns.

| Field | Type | Meaning |
|---|---|---|
| `grid` | `polars.DataFrame` | one row per cell; the heart of the structure |
| `theta_lims` | `np.ndarray` | outer θ edge of each ring (radians) |
| `phi_lims` | `list[np.ndarray]` | φ_min per ring |
| `cell_ids` | `list[np.ndarray]` | cell ids per ring |
| `grid_type` | `str` | `"equal_area"`, `"healpix"`, … |
| `solid_angles` | `np.ndarray?` | per-cell Ω (sr); else computed on demand |
| `metadata` | `dict?` | `angular_resolution`, `cutoff_theta`, … |
| `voronoi`/`vertices`/`points_xyz`/`vertex_phi`/`vertex_theta` | optional | extra geometry for fibonacci / triangular grids |

**`grid` DataFrame columns** (always present): `phi`, `theta` (cell centre),
`phi_min`, `phi_max`, `theta_min`, `theta_max` (bounding box), `cell_id`
(0..ncells-1, contiguous). Grid-type-specific extras: `healpix_ipix`,
`healpix_nside` (HEALPix); `geodesic_vertices` (index list into `vertices`);
`htm_vertex_0/1/2` (Cartesian); `voronoi_region` (Fibonacci).

Useful methods: `.ncells`, `.coords` (φ,θ), `.get_solid_angles()` (per-type
exact: healpy `nside2pixarea`, spherical-excess for triangles, Voronoi area;
fallback `Δφ·(cosθ_min−cosθ_max)`), `.get_grid_stats()` (solid-angle CV%, etc.),
`.get_patches()` (matplotlib `Rectangle`s — **rectangular grids only**).

### Coordinate convention (critical, and topocentric)
- **θ** = polar angle from **zenith**: 0 = straight up, π/2 = horizon.
- **φ** = azimuth from **North, clockwise** (navigation convention).
- HEALPix's native colatitude (0 = N pole) is treated as **the same** as this
  zenith θ — *no transform applied* (`healpix_grid.py` docstring).
- This is a **local sky** frame centred on the antenna, **not** Earth lon/lat.
  Every Pangeo grid tool assumes geographic lon/lat, so this mismatch is the
  central tension for HEALPix/xdggs/uxarray adoption (see strategy docs).

## 2. The builders (`grids_impl/`, factory `create_hemigrid`)

`create_hemigrid(grid_type, angular_resolution=10.0, **kw)` → `GridData`.
`kw`: `cutoff_theta` (elevation mask, deg), `phi_rotation` (deg), `nside`
(HEALPix), etc. Seven `BaseGridBuilder` subclasses; `build()` applies
`phi_rotation`, merges `{angular_resolution, cutoff_theta}` into `metadata`.

| Builder | Cell shape | Equal-area? | Notes |
|---|---|---|---|
| **EqualArea** | φ×θ rectangles in rings | ✅ (by construction) | **the only scientifically validated grid**; default for GNSS-T |
| EqualAngle | φ×θ rectangles | ❌ | uniform angle, unequal Ω |
| Equirectangular | rectangles | ❌ | simple |
| HEALPix | curvilinear quads | ✅ (exact) | delegates to **healpy**; see §6 incompleteness |
| Geodesic | spherical triangles | ≈ | icosahedron subdivision; shared `vertices` + `geodesic_vertices` index — **already UGRID-shaped** |
| HTM | spherical triangles | ≈ | per-cell Cartesian vertices |
| Fibonacci | Voronoi polygons | ≈ | `SphericalVoronoi` |

**EqualArea construction** (`equal_area_grid.py`): θ-band width = `angular_resolution`;
target Ω = `2π(1−cos(Δθ/2))`; per band `n_φ = round(Ω_band/Ω_target)`, so φ-cell
count **varies by ring** (wide near zenith, narrow near horizon). This is exactly
why the grid is a ragged/unstructured mesh, not a dense θ×φ lattice. At 2° → 6448
cells. Centre = rectangle midpoint.

## 3. Cell assignment (`operations.py`)

The workhorse our precomputes already use:
- `_build_kdtree(grid)` → projects cell **centres** (φ,θ)→unit-sphere (x,y,z),
  builds `scipy.spatial.cKDTree`.
- `_query_points(tree, cell_id_col, φ, θ)` → nearest centre → `cell_id`.
- `add_cell_ids_to_vod_fast(vod_ds, grid, name)` → adds `cell_id_<name>(epoch,sid)`;
  non-finite φ/θ → NaN. Also `_vod` (elementwise) and `_ds_fast` (dask/lazy).

**Important nuance:** assignment is **nearest-cell-centre**, not true polygon
membership. For EqualArea (convex, centre-symmetric) this matches the bbox
practically exactly. For **HEALPix** the curvilinear pixels mean nearest-centre
≠ `healpy.ang2pix` at boundaries — canvod's generic path is slightly off for
HEALPix (true membership needs `ang2pix`). Our strategy-2 doc handles this.

## 4. Grid → xarray, and storage (`operations.py`)

- **`grid_to_dataset(grid)`** → `xr.Dataset` dims `(cell_id, vertex)`:
  `cell_phi`, `cell_theta`, `vertices_phi`, `vertices_theta`, `n_vertices`,
  `solid_angle`; attrs `grid_type`, `angular_resolution_deg`, `cutoff_theta_deg`,
  `n_cells`. **This is already a UGRID-lite cell+corner representation** — a
  strong foundation for all three strategies. Per type: rectangular→4 bbox
  corners; healpix→4 **bbox** corners (⚠ see §6); geodesic→3 true corners; etc.
- **`store_grid` / `load_grid`** persist that Dataset to an Icechunk `grids/<name>`
  group via `icechunk.xarray.to_icechunk`. `store_dataset_with_cell_ids` writes a
  data group carrying `cell_id_<name>` LUT columns + `grid_references` attr.

## 5. Visualization (`canvod-viz`)

`HemisphereVisualizer(grid).plot_2d(data, style=PolarPlotStyle(...), ax=…)` →
`HemisphereVisualizer2D.plot_grid_patches`:
- Builds **per-cell matplotlib `Polygon` patches** in a **polar projection**:
  radius ρ = **sin θ**, `set_theta_zero_location("N")`, `set_theta_direction(-1)`
  (clockwise). I.e. a proper **azimuthal sky plot** (zenith centre, horizon rim).
- Patch geometry is **grid-type aware**: rectangular→bbox corners;
  htm/geodesic→triangle vertices; **healpix→`healpy.boundaries(step=4)` true
  curvilinear boundary**; fibonacci→Voronoi region. Caches patches.
- `data` is a length-`ncells` array indexed by `cell_id`. **Always draws its own
  colorbar** (no toggle). `PolarPlotStyle` fields: `cmap, edgecolor, linewidth,
  alpha, vmin, vmax, title, figsize, dpi, colorbar_label/shrink/pad/fontsize,
  show_grid, grid_alpha, grid_linestyle, show_degree_labels, theta_labels`.
- `HemisphereVisualizer3D` (plotly) for 3-D; `add_tissot_indicatrix` for
  distortion overlay.

**Takeaway:** canvod-viz **is** the dedicated topocentric polar renderer our
brainstorm called for. It consumes a `(cell_id → value)` vector, independent of
how the values were stored. So all three storage strategies can share **one**
renderer — viz stays decoupled from containment.

## 6. What's INCOMPLETE / rough in canvod (build around these)

1. **HEALPix bounding boxes are fake.** `healpix_grid.py` stores `phi_min/max`,
   `theta_min/max` as `centre ± resol/2` and sets `theta_lims/phi_lims` to
   *synthetic* `linspace` values ("interface compatibility only"). `grid_to_dataset`'s
   healpix branch then serialises those **bbox corners as `vertices`** — yet
   `viz` and `extract_grid_vertices` use **true** `healpy.boundaries`. So the
   *stored* HEALPix grid geometry ≠ the *rendered* one. → Strategy 2 must take
   geometry straight from `healpy` (`pix2ang`, `boundaries`, `ang2pix`), not from
   the stored bbox.
2. **HEALPix assignment via KDTree centre** (generic path) ≠ `ang2pix`. Minor at
   2° but wrong in principle. Strategy 2 uses `ang2pix` for exact membership.
3. **`load_grid` is lossy for non-rectangular grids.** It only reconstructs
   `phi_min/max`, `theta_min/max` for equal_area/equal_angle/equirectangular and
   HTM; **healpix/geodesic/fibonacci lose their special columns** (`healpix_ipix`,
   `geodesic_vertices`, `voronoi_region`) on round-trip → the loaded grid can't
   re-render or re-assign correctly. → Don't rely on `load_grid` for HEALPix;
   store `nside` + `ipix` and rebuild via `create_hemigrid('healpix', nside=…)`.
4. **`GridData.get_patches()`** emits `Rectangle`s only — valid for rectangular
   grids; misleading for healpix/triangular (viz uses its own per-type path, so
   not used in practice).
5. **Solid angle of EqualArea** is the geometric fallback `Δφ(cosθ_min−cosθ_max)`
   — exact for the bbox, and equal across cells by construction (good).
6. **`create_hemigrid` type hint** lists `"rectangular"`/`"HTM"` casings that the
   body lowercases; harmless but loose.

## 7. Implications for the three storage strategies

- **Reuse, don't reinvent:** every strategy gets the tessellation from
  `create_hemigrid(...)` and (where possible) serialises via the *idea* of
  `grid_to_dataset`. Cell values come from the **same** `_build_kdtree`/
  `_query_points` (equal_area) or `healpy.ang2pix` (healpix) assignment.
- **One renderer:** all strategies round-trip back to a length-`ncells`
  (or per-cell) vector and render through `HemisphereVisualizer.plot_2d` — proving
  the cube is renderer-agnostic.
- **The cube axis is `cell`** (= canvod `cell_id`), with `theta/phi` + corner
  bounds as coordinates, `time` extruding it, and additive moment layers
  (`sum`,`sumsq`,`count`) per `(pair, time, cell)` — see `../vod_cube_design_brainstorm.md`.
- **Grid identity** is preserved exactly by Strategy 1 & 3 (canvod equal_area
  cells) and **re-tessellated** by Strategy 2 (HEALPix) — the core trade the
  comparison scores.

## 8. Key APIs the strategies call

```python
from canvod.grids import create_hemigrid, grid_to_dataset
from canvod.grids.operations import _build_kdtree, _query_points
from canvod.viz import HemisphereVisualizer, PolarPlotStyle

grid = create_hemigrid("equal_area", angular_resolution=2.0)   # 6448 cells
g = grid.grid            # polars DF: phi,theta,phi_min/max,theta_min/max,cell_id
tree = _build_kdtree(grid)
cid = _query_points(tree, g["cell_id"].to_numpy(), phi, theta)  # assign obs
HemisphereVisualizer(grid).plot_2d(data=per_cell_values, style=PolarPlotStyle(...))
# HEALPix (strategy 2): geometry from healpy, not the stored bbox
hgrid = create_hemigrid("healpix", angular_resolution=2.0)      # nside power-of-2
```
