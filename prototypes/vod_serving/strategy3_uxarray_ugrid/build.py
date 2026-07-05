"""Strategy 3 — canvod equal-area as a UGRID unstructured mesh (uxarray).

Keeps canvod's equal-area cells (grid identity preserved, like Strategy 1) but
expresses them as a first-class **UGRID unstructured mesh**: each cell is a quad
*face*, corners are *nodes*, with explicit `face_node_connectivity`. This is the
Pangeo home for arbitrary tessellations (uxarray), and unlike Strategy 1 it
carries real mesh topology (faces, nodes, connectivity) that unstructured-grid
tooling understands.

Topocentric → pseudo-geographic mapping (uxarray expects lon/lat degrees):
    node_lon = azimuth   degrees [0,360)
    node_lat = elevation degrees = 90 - theta_deg   (zenith=90, horizon=0)

    mesh:        UGRID-1.0 (n_node nodes, n_face quad faces, connectivity)
    data_vars:   vod_sum, vod_sumsq, count   on (pair, time, n_face)  additive
    outputs:     _out/strategy3_ugrid.nc      (UGRID netCDF, uxarray-native)
                 _out/strategy3_ugrid.zarr    (same, zarr)

Run: cd canvodpy && uv run --with uxarray \
        python ../grid_storage/strategy3_uxarray_ugrid/build.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import (
    PAIRS,
    assign_equal_area,
    dir_size_mb,
    equal_area_grid,
    load_fixture,
    moments,
)

OUT = Path(__file__).resolve().parent.parent / "_out"
NC = OUT / "strategy3_ugrid.nc"
ZARR = OUT / "strategy3_ugrid.zarr"
RES = 2.0


def build_quad_mesh(grid):
    """canvod equal-area cells -> (node_lon, node_lat, face_node_conn[, ncells])."""
    g = grid.grid
    phi_min = np.rad2deg(g["phi_min"].to_numpy())
    phi_max = np.rad2deg(g["phi_max"].to_numpy())
    th_min = np.rad2deg(g["theta_min"].to_numpy())
    th_max = np.rad2deg(g["theta_max"].to_numpy())
    ncells = grid.ncells

    # 4 corners per cell, CCW: (phi_min,th_max)(phi_max,th_max)(phi_max,th_min)(phi_min,th_min)
    # lon = azimuth, lat = elevation = 90 - theta
    corner_lon = np.stack([phi_min, phi_max, phi_max, phi_min], axis=1).ravel()
    corner_lat = np.stack(
        [90 - th_max, 90 - th_max, 90 - th_min, 90 - th_min], axis=1
    ).ravel()

    # dedup corners -> nodes (round to merge shared edges; 0/360 left as a seam)
    key = np.round(np.stack([corner_lon, corner_lat], axis=1), 6)
    _, first_idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    node_lon = corner_lon[first_idx]
    node_lat = corner_lat[first_idx]
    face_node = inv.reshape(ncells, 4).astype(np.int64)
    return node_lon, node_lat, face_node, ncells


def ugrid_dataset(grid) -> xr.Dataset:
    node_lon, node_lat, face_node, ncells = build_quad_mesh(grid)
    fx = load_fixture()
    time = pd.to_datetime([fx["date"]])

    vsum = np.zeros((len(PAIRS), 1, ncells))
    vsq = np.zeros((len(PAIRS), 1, ncells))
    cnt = np.zeros((len(PAIRS), 1, ncells))
    for p, pair in enumerate(PAIRS):
        cid = assign_equal_area(grid, fx[f"{pair}__phi"], fx[f"{pair}__theta"])
        s, s2, c = moments(cid, fx[f"{pair}__vod"], ncells)
        vsum[p, 0], vsq[p, 0], cnt[p, 0] = s, s2, c
        print(
            f"[{pair}] {int(c.sum()):,} obs -> {int((c > 0).sum())} filled faces",
            flush=True,
        )

    ds = xr.Dataset(
        data_vars={
            "mesh": (
                (),
                np.int32(0),
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "node_lon node_lat",
                    "face_node_connectivity": "face_node_connectivity",
                    "face_dimension": "n_face",
                    "long_name": "Topology of canvod equal-area hemisphere mesh",
                },
            ),
            "face_node_connectivity": (
                ("n_face", "n_max_face_nodes"),
                face_node,
                {
                    "cf_role": "face_node_connectivity",
                    "start_index": 0,
                },
            ),
            "vod_sum": (
                ("pair", "time", "n_face"),
                vsum,
                {
                    "mesh": "mesh",
                    "location": "face",
                    "long_name": "sum of VOD per face",
                },
            ),
            "vod_sumsq": (
                ("pair", "time", "n_face"),
                vsq,
                {
                    "mesh": "mesh",
                    "location": "face",
                    "long_name": "sum of VOD^2 per face",
                },
            ),
            "count": (
                ("pair", "time", "n_face"),
                cnt,
                {"mesh": "mesh", "location": "face", "long_name": "obs count per face"},
            ),
        },
        coords={
            "pair": ("pair", np.array(PAIRS)),
            "time": ("time", time),
            "node_lon": (
                "n_node",
                node_lon,
                {
                    "standard_name": "longitude",
                    "units": "degrees_east",
                    "long_name": "azimuth (topocentric, mapped to lon)",
                },
            ),
            "node_lat": (
                "n_node",
                node_lat,
                {
                    "standard_name": "latitude",
                    "units": "degrees_north",
                    "long_name": "elevation = 90 - zenith angle (mapped to lat)",
                },
            ),
        },
        attrs={
            "title": "CARBONARA VOD hemisphere cube — UGRID/uxarray (strategy 3)",
            "Conventions": "UGRID-1.0",
            "grid_type": "equal_area (as UGRID quad mesh)",
            "angular_resolution_deg": RES,
            "coordinate_frame": "topocentric mapped to pseudo lon/lat "
            "(lon=azimuth, lat=90-zenith); NOT geographic",
            "spatial_axis": "n_face = canvod cell_id (face order preserved)",
            "stats_rule": "store additive sum/sumsq/count; derive mean/std on read",
            "source_store_branch": "main",
        },
    )
    return ds


def main() -> None:
    grid = equal_area_grid(RES)
    ds = ugrid_dataset(grid)

    OUT.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(NC)
    if ZARR.exists():
        import shutil

        shutil.rmtree(ZARR)
    ds.chunk({"time": 1}).to_zarr(ZARR, mode="w", consolidated=True)
    print(
        f"\nwrote {NC.name} ({dir_size_mb(NC):.2f} MB), "
        f"{ZARR.name} ({dir_size_mb(ZARR):.2f} MB)  dims={dict(ds.sizes)}"
    )

    _uxarray_demo(NC)
    _render_proof(grid)


def _uxarray_demo(nc_path: Path) -> None:
    """Prove the file opens as a first-class uxarray unstructured grid."""
    import uxarray as ux

    uxds = ux.open_dataset(nc_path, nc_path)  # grid + data from same UGRID file
    g = uxds.uxgrid
    print(
        f"uxarray open OK: n_node={g.n_node}, n_face={g.n_face}, "
        f"faces={g.n_max_face_nodes}-gon"
    )
    # exercise a grid-aware property (areas) to show topology is understood
    try:
        areas = g.face_areas
        print(f"uxarray face_areas computed: {float(areas.values.mean()):.4g} (mean)")
    except Exception as e:
        print(f"face_areas note: {type(e).__name__}: {e}")


def _render_proof(grid) -> None:
    """Render through canvod-viz from the stored UGRID (face order = cell_id)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from canvod.viz import HemisphereVisualizer, PolarPlotStyle

    rt = xr.open_zarr(ZARR, consolidated=True)
    s = rt["vod_sum"].isel(pair=0, time=0).values
    c = rt["count"].isel(pair=0, time=0).values
    mean = np.where(c > 0, s / np.where(c > 0, c, 1), np.nan)
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(6, 6))
    HemisphereVisualizer(grid).plot_2d(
        data=mean,
        ax=ax,
        style=PolarPlotStyle(
            cmap="YlGn",
            vmin=0,
            vmax=float(np.nanpercentile(mean, 98)),
            title="strategy3 round-trip: base_up VOD mean (UGRID)",
            colorbar_label="VOD",
            edgecolor="none",
        ),
    )
    out = Path(__file__).resolve().parent / "roundtrip_base_up.png"
    fig.savefig(out, dpi=90, bbox_inches="tight")
    plt.close(fig)
    print(f"render proof -> {out.name}")


if __name__ == "__main__":
    main()
