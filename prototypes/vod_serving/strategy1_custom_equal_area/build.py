"""Strategy 1 — canvod equal-area cells as a plain xarray cube (zarr + netCDF).

The "cylinder" with ZERO new dependencies beyond xarray/zarr. Keeps canvod's
equal-area grid identity exactly: the spatial axis IS canvod `cell_id`. Cell
geometry is carried as CF-style coordinate **bounds** (4 corners per cell) on an
unstructured `cell` dimension — readable by any xarray user, no grid library
required to load.

    dims:        (pair, time, cell)
    data_vars:   vod_sum, vod_sumsq, count        (additive → poolable)
    coords:      cell_theta(cell), cell_phi(cell)          centres [rad]
                 theta_bounds(cell,4), phi_bounds(cell,4)  corners [rad]
                 solid_angle(cell) [sr]
    attrs:       grid_type, angular_resolution_deg, convention hints, provenance

Writes both:
    _out/strategy1_equal_area.zarr   (canonical, chunked on time)
    _out/strategy1_equal_area.nc     (archival, single CF file)

Run:  cd canvodpy && uv run python ../grid_storage/strategy1_custom_equal_area/build.py
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
ZARR = OUT / "strategy1_equal_area.zarr"
NC = OUT / "strategy1_equal_area.nc"
RES = 2.0


def main() -> None:
    fx = load_fixture()
    grid = equal_area_grid(RES)
    g = grid.grid
    ncells = grid.ncells
    time = pd.to_datetime([fx["date"]])

    # additive moment layers, per pair, single time step (the 24h day)
    vsum = np.zeros((len(PAIRS), 1, ncells))
    vsq = np.zeros((len(PAIRS), 1, ncells))
    cnt = np.zeros((len(PAIRS), 1, ncells))
    for p, pair in enumerate(PAIRS):
        cid = assign_equal_area(grid, fx[f"{pair}__phi"], fx[f"{pair}__theta"])
        s, s2, c = moments(cid, fx[f"{pair}__vod"], ncells)
        vsum[p, 0], vsq[p, 0], cnt[p, 0] = s, s2, c
        print(
            f"[{pair}] {int(c.sum()):,} obs -> {int((c > 0).sum())} filled cells",
            flush=True,
        )

    # CF cell bounds: 4 corners per equal-area cell (from canvod bbox)
    phi_b = np.stack(
        [
            g["phi_min"].to_numpy(),
            g["phi_max"].to_numpy(),
            g["phi_max"].to_numpy(),
            g["phi_min"].to_numpy(),
        ],
        axis=1,
    )
    theta_b = np.stack(
        [
            g["theta_min"].to_numpy(),
            g["theta_min"].to_numpy(),
            g["theta_max"].to_numpy(),
            g["theta_max"].to_numpy(),
        ],
        axis=1,
    )

    ds = xr.Dataset(
        data_vars={
            "vod_sum": (
                ("pair", "time", "cell"),
                vsum,
                {"long_name": "sum of VOD per cell", "units": "1"},
            ),
            "vod_sumsq": (
                ("pair", "time", "cell"),
                vsq,
                {"long_name": "sum of VOD^2 per cell", "units": "1"},
            ),
            "count": (
                ("pair", "time", "cell"),
                cnt,
                {"long_name": "observation count per cell", "units": "1"},
            ),
        },
        coords={
            "pair": ("pair", np.array(PAIRS)),
            "time": ("time", time),
            "cell": ("cell", g["cell_id"].to_numpy()),
            "cell_theta": (
                "cell",
                g["theta"].to_numpy(),
                {
                    "long_name": "cell-centre polar angle from zenith",
                    "units": "rad",
                    "bounds": "theta_bounds",
                },
            ),
            "cell_phi": (
                "cell",
                g["phi"].to_numpy(),
                {
                    "long_name": "cell-centre azimuth from north (cw)",
                    "units": "rad",
                    "bounds": "phi_bounds",
                },
            ),
            "theta_bounds": (("cell", "nv"), theta_b),
            "phi_bounds": (("cell", "nv"), phi_b),
            "solid_angle": (
                "cell",
                grid.get_solid_angles(),
                {"long_name": "cell solid angle", "units": "sr"},
            ),
        },
        attrs={
            "title": "CARBONARA VOD hemisphere cube — canvod equal-area (strategy 1)",
            "grid_type": "equal_area",
            "angular_resolution_deg": RES,
            "ncells": ncells,
            "coordinate_frame": "topocentric (theta from zenith, phi from north cw)",
            "frame_note": "LOCAL SKY frame, NOT geographic lon/lat",
            "spatial_axis": "cell = canvod cell_id (unstructured equal-area mesh)",
            "stats_rule": "store additive sum/sumsq/count; derive mean/std on read",
            "Conventions": "CF-1.10 (cell bounds on unstructured cell axis)",
            "source_store_branch": "main",
        },
    )

    # derived means for convenience (not stored as canonical; recomputed on read)
    OUT.mkdir(parents=True, exist_ok=True)
    enc = {
        v: {"zarr_format": 2} for v in ds.data_vars
    }  # zarr-v2 for broad reader compat
    if ZARR.exists():
        import shutil

        shutil.rmtree(ZARR)
    ds.chunk({"time": 1}).to_zarr(ZARR, mode="w", consolidated=True)
    ds.to_netcdf(NC)

    print(f"\nwrote {ZARR.name}  ({dir_size_mb(ZARR):.2f} MB)")
    print(f"wrote {NC.name}  ({dir_size_mb(NC):.2f} MB)")
    print(f"dims: {dict(ds.sizes)}")

    # round-trip + render proof via canvod viz (renderer-agnostic cube)
    _render_proof(grid, ds)


def _render_proof(grid, ds) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from canvod.viz import HemisphereVisualizer, PolarPlotStyle

    rt = xr.open_zarr(ZARR, consolidated=True)
    mean = (
        rt["vod_sum"].isel(pair=0, time=0)
        / rt["count"].isel(pair=0, time=0).where(lambda c: c > 0)
    ).values
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(6, 6))
    HemisphereVisualizer(grid).plot_2d(
        data=mean,
        ax=ax,
        style=PolarPlotStyle(
            cmap="YlGn",
            vmin=0,
            vmax=float(np.nanpercentile(mean, 98)),
            title="strategy1 round-trip: base_up VOD mean",
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
