# Grid-storage strategies — comparison & scorecard

Three ways to store the CARBONARA VOD hemisphere "cube", all built from the
**same** 24h fixture (`_fixture/obs_24h.npz`, 2025-10-08; base_up 105k /
nadir_in 522k / nadir_out 384k obs) and all rendered back through the **same**
canvod-viz polar renderer (round-trip PNGs in each strategy folder are
pixel-faithful). See `00_canvod_grids_viz_review.md` for the canvod internals
these build on.

> Scope caveat: numbers below are **1 time-step (24h) × 3 pairs**. Sizes scale
> ~linearly with `time`; the *relative* ordering holds. Storage choice is
> **orthogonal** to the metadata layers — all three carry the identical additive
> trio `vod_sum / vod_sumsq / count` (→ poolable mean & std), so the
> metadata-inventory question (`../vod_cube_design_brainstorm.md` §9b) is
> independent of this grid decision.

## Measured (this run)

| strategy | cells | zarr MB | nc MB | open+load ms |
|---|--:|--:|--:|--:|
| **S1** custom equal-area (xarray + CF bounds) | 6448 | 0.36 | 1.10 | 13.9 |
| **S2** HEALPix + xdggs | 6208 | 0.26 | — | 10.6 |
| **S3** uxarray UGRID | 6448 | 0.33 | 0.89 | 11.7 |

At this scale all three are tiny and fast; size/speed are **not** the
deciding factors. (`compare.py` regenerates this table.)

## Scorecard (qualitative)

Legend: ✅ strong · ◑ partial / with caveats · ❌ weak

| Axis | S1 custom equal-area | S2 HEALPix + xdggs | S3 uxarray UGRID |
|---|---|---|---|
| **canvod grid identity** | ✅ exact (`cell`=`cell_id`) | ❌ re-tessellated to HEALPix | ✅ exact (`n_face`=`cell_id`) |
| **Round-trip fidelity** | ✅ lossless | ✅ exact (own pixels) | ✅ lossless (= S1) |
| **New dependencies** | ✅ none (xarray/zarr) | ◑ healpy + xdggs | ◑ uxarray (large stack) |
| **Pangeo interop surface** | ◑ plain xarray only | ✅ DGGS ecosystem (xdggs) | ✅ unstructured ecosystem (uxarray) |
| **Native cell ops** (neighbours, areas) | ❌ DIY | ✅ built-in | ✅ areas/connectivity built-in |
| **Multi-resolution** (coarsen/refine) | ❌ | ✅ hierarchical | ❌ |
| **Exact membership** | ◑ KDTree centre (fine for equal-area) | ✅ `ang2pix` | ◑ KDTree centre (= S1) |
| **Viz (decoupled, canvod-viz)** | ✅ | ✅ (true `healpy.boundaries`) | ✅ |
| **Coordinate honesty** | ✅ native topocentric θ/φ | ◑ topo→pseudo lon/lat | ◑ topo→pseudo lon/lat |
| **One-file distributable** | ✅ `.nc` + zarr (+`.zarr.zip`) | ◑ zarr (DGGS-native) | ✅ UGRID `.nc` + zarr |
| **Standard / recognised format** | ◑ CF on unstructured axis | ✅ HEALPix/DGGS | ✅ UGRID-1.0 |
| **Storage footprint** | ✅ small | ✅ smallest | ◑ +connectivity (still small) |
| **Re-use of canvod code** | ✅ grid+assign+viz | ◑ nside only; geom via healpy | ✅ grid+assign+viz |

## How to read the trade

The decision is **one axis**: *keep canvod's validated equal-area cells*, or
*adopt a recognised DGGS/mesh standard for richer tooling*.

- **S1 and S3 keep grid identity** (cell ↔ `cell_id`); their stored values are
  pixel-identical (S3 just adds explicit mesh topology). Choose between them by
  *how much grid-awareness you want in the container*: S1 = nothing extra, plain
  xarray; S3 = real UGRID faces/nodes/areas via uxarray.
- **S2 trades grid identity for capability**: exact `ang2pix`, neighbours, and —
  uniquely — **hierarchical multi-resolution**. But it leaves canvod's cells, so
  cross-product joins must be re-derived on the HEALPix axis.

Three things are **common to all** and therefore not differentiators:
1. the additive metadata layers (sum/sumsq/count → poolable mean/std);
2. the decoupled canvod-viz renderer (topocentric polar sky);
3. the topocentric frame — S2/S3 both fake lon/lat to borrow machinery, which
   must be flagged loudly wherever the cube is shared (it is, in each `attrs`).

## Recommendation (for discussion — you asked to explore all three)

- **Default / first published cube → S1.** Zero deps, exact identity, `.zarr` +
  `.nc`, trivial canvod round-trip. It is the lowest-risk "ship it" cube and
  everything (notebook, GIF, collaborators) can read it today.
- **Add S3 when you want unstructured-grid operators** (areas, neighbours,
  remapping, uxarray viz) *without* leaving the equal-area cells. S1→S3 is a pure
  container upgrade; values don't change. Natural once geodesic/triangular meshes
  enter the picture (canvod's geodesic grid is already UGRID-shaped).
- **Add S2 only if multi-resolution / DGGS interop becomes a real requirement**
  (e.g. coarsening for overviews, joining to other HEALPix datasets). Treat it as
  a *derived view*, not the system of record, because it changes grid identity.

Net: **S1 as the canonical store; S3 as the power-user mesh view; S2 as a DGGS
derivative.** All three are reproducible from `main` via the scripts here, so the
choice is reversible and can be re-litigated as needs evolve.

## Files

```
grid_storage/
  00_canvod_grids_viz_review.md     canvod-grids/-viz code review (+ incompleteness)
  build_fixture.py                  24h obs fixture from the corrected `main` store
  _common.py                        shared canvod-backed helpers
  strategy1_custom_equal_area/      build.py + README + roundtrip PNG
  strategy2_healpix_xdggs/          build.py + README + roundtrip PNG
  strategy3_uxarray_ugrid/          build.py + README + roundtrip PNG
  compare.py                        scorecard (sizes / load times)
  _out/                             generated cubes (zarr/nc)  [gitignore-able]
  COMPARISON.md                     this file
```
