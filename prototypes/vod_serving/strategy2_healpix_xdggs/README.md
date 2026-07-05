# Strategy 2 — HEALPix + xdggs

**One line:** re-tessellate the hemisphere onto HEALPix pixels and store with
xdggs conventions, so the Pangeo DGGS stack recognises the cube natively.

## What it is

```
dims:        (pair, time, cell)            cell = hemisphere HEALPix pixels (nside=32 → 6208)
coords:      cell_ids(cell)   + xdggs attrs {grid_name:"healpix", level:5, indexing_scheme:"ring"}
             cell_theta/cell_phi(cell)     pixel centres [rad]
data_vars:   vod_sum, vod_sumsq, count     additive moments → poolable
output:      _out/strategy2_healpix.zarr
```

`nside` is chosen by **canvod's own `HEALPixBuilder`** (= `create_hemigrid("healpix",
2.0)` → nside 32, ~1.83°), so the resolution matches what canvod would build.

## How it complies with canvod (and works *around* its rough edges)

Per `../00_canvod_grids_viz_review.md` §6, canvod's stored HEALPix geometry is
approximate (fake bboxes, synthetic limits, KDTree-centre assignment, lossy
`load_grid`). So this strategy:
- takes **nside** from canvod (consistency), but
- takes **geometry + membership from `healpy` directly**: `ang2pix` for exact
  pixel assignment (not nearest-centre), `pix2ang` for centres, and
- **renders through canvod-viz**, whose HEALPix path already draws *true*
  `healpy.boundaries` (visible curvilinear pixels in `roundtrip_base_up.png`).

The round-trip image is produced from the **stored zarr**, mapping pixel `ipix`
back onto the canvod HEALPix grid row order — lossless.

## The xdggs payoff

`ds.dggs.decode()` reads the `cell_ids` attributes and returns a DGGS-aware
dataset; `ds.dggs.cell_centers()` computes `latitude`/`longitude` per cell with
**zero bespoke code** (verified in the build output). That unlocks the xdggs
ecosystem: neighbour search, parent/child coarsening/refinement (HEALPix is
hierarchical), and interop with other DGGS datasets — none of which Strategy 1
or 3 get for free.

## The catch — topocentric ≠ geographic

xdggs treats HEALPix as a **geographic** sphere (lat/lon on a globe). We map our
**topocentric** sky (zenith→pole, azimuth→longitude) onto it. So `cell_centers()`
returns lat/lon that are really *elevation/azimuth in disguise*. Everything is
internally consistent (binning, centres, and canvod's boundaries all share the
healpy frame), but **the lat/lon are not Earth coordinates** — they're a device
to borrow DGGS machinery. Document this loudly anywhere the cube is shared.

Also: HEALPix is **not** canvod's equal-area grid — this strategy *changes grid
identity*. Existing canvod products keyed on `cell_id` don't line up cell-for-cell
with HEALPix pixels; you'd re-derive any cross-product on the HEALPix axis.

## Pros / cons

**Pros**
- Native DGGS: indexing, neighbours, **multi-resolution**, lon/lat decode via xdggs.
- Exact equal-area pixels; exact membership (`ang2pix`).
- Standard zarr; Pangeo-DGGS-discoverable.

**Cons**
- Leaves canvod's validated equal-area cells (grid-identity change).
- Geographic framing is a fiction for a topocentric sky — easy to misread.
- Extra deps (`healpy`, `xdggs`); nside locked to powers of 2 (less freedom than
  canvod's arbitrary `angular_resolution`).

## Distributability

Plain zarr (object store / OSN / S3, lazy partial reads). xdggs/HEALPix is a
recognised community format, so third parties can consume it with their own DGGS
tooling. (netCDF also possible; zarr is the natural DGGS home.)

## Run

```bash
cd canvodpy && uv run --with healpy --with xdggs \
    python ../grid_storage/strategy2_healpix_xdggs/build.py
```
