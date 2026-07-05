# Session handoff — VOD storage + visualization architecture

> Living state doc so the next session can continue. Covers the data model we
> converged on, every file in `grid_storage/`, the icechunk stores and their
> state, the running build, and the open next steps. Pairs with
> `../vod_cube_design_brainstorm.md` (earlier brainstorm) and
> `00_canvod_grids_viz_review.md` (canvod internals).

## 1. The goal

A Pangeo-native, distributable way to store + interactively visualize CARBONARA
VOD over the hemisphere, that scales to **many sites × antennas × years** and
**stays entirely inside one icechunk store** (the store is updated every 24 h; a
second store would have to be re-synced and could drift).

## 2. Architecture — DECIDED

**Storage frame.** Data lives on the **unit sphere S² in spherical coords** (the
topocentric sky dome: θ = zenith angle, φ = azimuth from N, clockwise). NEVER the
rolled-out lon/lat rectangle — that is only an artifact of geographic tooling and
is what manufactures the **zenith pole singularity** + **0/360 azimuth seam**.
Store node geometry as **Cartesian unit vectors** `node_x/y/z` → singularity-free
(zenith = (0,0,1); seam doesn't exist in xyz).

**Grid framework = uxarray / UGRID** (NOT xdggs/HEALPix). Reason: we must keep
canvod's *prescribed equal-area grid unchanged*; xdggs only speaks DGGS (HEALPix/
H3), which would re-tessellate (change the grid). UGRID represents canvod's exact
cells as an unstructured quad mesh (nodes/faces/connectivity). Native interactive
viz comes from the geo-stack (geoviews/datashader/cartopy) via a **north-polar
azimuthal projection** — proven to render our sky correctly.

**The store is GRIDDED in space, NATIVE in time.** The prescribed mesh is stored
once; every observation carries a `cell_id` (canvod KDTree assignment) — that's
the "gridded" part. But each obs keeps its own **native epoch** — no daily/weekly
snapshot binning. Snapshots / per-cell means are **downstream temporal
aggregations**, not the stored form. (This is canvod's own `add_cell_ids` pattern.)

**Serving layer for interactive viz = a cumulative ROLLUP, as groups in the SAME
icechunk store** (Earthmover-validated: serve from source, no second copy).
Per-cell **additive moments** (sum, sumsq, count, per-constellation counts)
stored **cumulatively over time bins**. Any window `[a,b]` = `cum[b] − cum[a]` →
O(1), instant brushing, tiny read. 24 h pipeline appends one cumulative slice per
day in the same commit as the obs.

**Compute = Python, no GPU — by design.** Each request moves ~6448 cells (the
*answer* is tiny; the data is huge but never moved). It's I/O-bound; zarr/icechunk
decompression is already Rust. Prefix-sum makes wide windows O(1). GPU/another
language would optimize work that's already free. Escape hatch for the one CPU
path (group-by over raw obs for a very wide window): use the rollup, not a rewrite.

**Serving stack (Earthmover pattern):** `xpublish` (FastAPI) router reads icechunk
→ does our temporal aggregation (prefix subtraction) → returns the per-cell array.
`ndpyramid`'s "multiscale-in-zarr" idea applied to **time** = our rollup (hour→day
→week levels possible). `datashader` only if ever rendering raw obs tracks.
xpublish-tiles itself is geographic + does no aggregation, so we write the small
custom router; the *pattern* (serve-from-icechunk, thin WebGL client) is theirs.

**Visualization rules (saved to memory `feedback-hemisphere-viz-principles`):**
render every cell as a **filled polygon, never markers**; **matplotlib** for
papers, **plotly** for dashboards; the 2D plot is a camera over the zenith
(ρ = sin θ, orthographic) which compresses the horizon — also offer the **flat**
azimuthal-equidistant (ρ ∝ θ, standard GNSS skyplot).

## 3. File inventory (`grid_storage/`)

| File | Role | State |
|---|---|---|
| `00_canvod_grids_viz_review.md` | code review of canvod-grids/-viz + what's incomplete | done |
| `COMPARISON.md` | scorecard of the 3 early storage strategies | done |
| `_common.py` | shared helpers (canvod grid, KDTree assign, moments) | done |
| `build_fixture.py` | 24h obs fixture (`_fixture/obs_24h.npz`) | done |
| `strategy1_custom_equal_area/`, `strategy2_healpix_xdggs/`, `strategy3_uxarray_ugrid/` | the 3 prototypes + READMEs + roundtrip PNGs | done (S3=uxarray chosen) |
| `compare.py` | sizes/load-times scorecard | done |
| `build_icechunk_cube.py` | snapshot-cube prototype + **`build_mesh()`** (UGRID, Cartesian nodes) — `build_mesh` is reused everywhere | done |
| `build_native_pointcloud.py` | 24h GRIDDED-NATIVE store (`vod_native.icechunk`): mesh + per-pair obs(epoch,sid,cell_id,vod) | done |
| `build_native_full.py` | FULL deployment native store (`vod_native_full.icechunk`); per-day index; sid as int code | **RUNNING** (see §5) |
| `build_rollup.py` | adds cumulative `rollup/<pair>` groups into `vod_native.icechunk` (hourly; full = daily) | done |
| `serve_hemisphere.py` | **xpublish router** — windowed per-cell aggregate via prefix subtraction; `--selftest` | done, validated |
| `view_vod_cube.py` | marimo viewer — timeline brush + grid-on-the-fly + cell-polygon 2D/3D | done, validated headless |
| `geometry_two_lenses.png`, `geometry_cells_on_sphere.png` | teaching figures (lon/lat vs polar; cells on S²) | done |
| `_out/` | generated stores (gitignored) | see §4 |

## 4. icechunk stores (`grid_storage/_out/`, gitignored)

- `vod_native.icechunk` — 24h (2025-10-08), 3 pairs. Groups: `grid` (mesh),
  `<pair>` (native obs), **`rollup/<pair>`** (cumulative hourly moments). The
  serving prototype + rollup were built against THIS one.
- `vod_native_full.icechunk` — FULL deployment, being written (§5). Groups: `grid`,
  `meta` (sid lookup), `<pair>` (obs + per-day index `day_date/day_count/day_mean_vod`).
  Commits only at the END, so don't read until the build finishes.
- `vod_cube.icechunk` — earlier (pair,time,n_face) snapshot-cube prototype (now a
  *derived view* concept, superseded by native+rollup). Keep for reference.

The **production VOD source store** is the rinex SNR store at
`…/Icechunk_stores/tapajos/rinex` branch `main` (geometry-corrected; see memory
`finding-eastern-horizon-obstruction`). All builds read VOD from it via canvod's
`TauOmegaZerothOrder` (guard-railed).

## 5. Full build — DONE (2026-06-12)

`build_native_full.py` committed `MXD8EHYKZ5Y7` (2129s). Read-back counts:
base_up_vs_sky_up **5,906,333** obs / 232 days; nadir_in_vs_sky_up **113,850,651** /
217; nadir_out_vs_sky_up **84,459,236** / 217. (base_up is far below the earlier
~25M guess — it is the up-looking pair, lower obs density; count verified on
read-back.) Store: `_out/vod_native_full.icechunk`, groups `grid` / `meta` /
`<pair>` / `rollup/<pair>`.

The daily rollup committed `0GJPK2BXFB1C`: each `rollup/<pair>` = 249 daily edges ×
6448 cells, ~90 MB. `build_rollup.py` was generalized — env overrides
`ROLLUP_STORE` / `ROLLUP_FREQ`, and constellation is decoded via a vectorized
`sid_code → meta/sid` letter table (no Python loop over 1e8 obs).
`serve_hemisphere.py` `STORE` is now env-overridable (`SERVE_STORE`); selftest
passes against the full store (full span 2025-09-25→2026-05-31, O(1) brushing OK).
Note: the router's `nobs` field is always the window TOTAL; the `cons` filter
lives in the per-cell `values` array, not in `nobs`.

## 6. Next steps (in order)

1. ~~Confirm full build + sanity-check counts.~~ DONE (§5).
2. ~~Build the daily rollup on the full store.~~ DONE — `0GJPK2BXFB1C`.
3. ~~Point `serve_hemisphere.py` at the full store, re-selftest.~~ DONE (`SERVE_STORE` env).
4. ~~Wire a thin client to `/hemisphere`.~~ DONE — `view_vod_cube.py` is now a
   thin client: each timeline brush issues `GET /hemisphere/{pair}?t0=&t1=&layer=&cons=`
   (the per-brush obs scan → O(1) prefix subtraction on the server, ~6448 numbers).
   Store still opened locally only for mesh + daily timeline. Layers mean/std/count;
   `n_sats` dropped and cons filter is count-only (rollup lacks per-cons moments).
   Env `HEMI_ENDPOINT` (default `127.0.0.1:8000`); server must run with
   `SERVE_STORE=…vod_native_full.icechunk`. Validated headless: `marimo export html`
   exit 0, server logged the `/hemisphere …layer=mean 200 OK`, full-window nobs
   5,906,333 rendered. **A minimal standalone WebGL page is still open** if a
   no-marimo distributable dashboard is wanted.
5. **Codify the 24 h update**: one job appends a day's obs + one cumulative rollup
   slice in a single icechunk commit.
6. Optional polish: per-constellation `sum/sumsq` in rollup (instant cons-filtered
   mean/std); HLL sketch for exact-ish `n_sats` instant; multi-site/antenna dims;
   sid int-encoding already done in full build (decode via `meta` group).
7. **Restructure canvod-grids** to emit/consume UGRID natively (grid unchanged) —
   the larger refactor the prototypes were de-risking.

## 7. How to run

```bash
cd canvodpy            # all commands from the workspace venv
# build native 24h store (prototype):   uv run python ../grid_storage/build_native_pointcloud.py
# add rollup to it:                      uv run python ../grid_storage/build_rollup.py
# self-test the serving router:          uv run --with xpublish --with fastapi --with httpx \
#                                            python ../grid_storage/serve_hemisphere.py --selftest
# live server (port 8000):               uv run --with xpublish --with fastapi --with uvicorn \
#                                            python ../grid_storage/serve_hemisphere.py
# timeline viewer:                       uv run --with marimo --with plotly --with wigglystuff \
#                                            marimo edit ../grid_storage/view_vod_cube.py
# full build (≈50 min):                  RUST_LOG=error uv run python ../grid_storage/build_native_full.py
```

## 8. Gotchas / facts

- Source store geometry was repaired + promoted to `main` 2026-06-12 (eastern-hole
  bug). `geom_fix` branch deleted.
- marimo: underscore-prefix cell-local temporaries (globals must be unique across
  cells); validate with `marimo export html <nb>` (exit 0 = clean).
- icechunk LocalFileSystem warns about concurrent commits — harmless single-writer.
- zarr v3 emits an `UnstableSpecificationWarning` for fixed-length unicode coords
  (sid/pair) — harmless; encode as int codes at scale (full build already does sid).
- The mesh's zenith **cap cell** is a degenerate quad under xyz dedup (cap is a
  polar disc, not a quad) — flagged; represent as a fan when firming the mesh.
- VOD itself must always come from canvod's `TauOmegaZerothOrder` (guard-rail);
  never reimplement the formula.
