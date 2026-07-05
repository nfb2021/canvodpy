"""Strategy 2 — re-tessellate onto HEALPix, store with xdggs conventions (zarr).

HEALPix is the equal-area sphere tessellation that the Pangeo DGGS stack
(`xdggs`) understands natively: cell indexing, neighbours, parent/child
multi-resolution, lon/lat decode — all for free. The cost is that we LEAVE
canvod's equal-area cells and re-bin onto HEALPix pixels.

Compliance choices (see ../00_canvod_grids_viz_review.md §6):
  * nside is chosen by canvod's own `HEALPixBuilder` (so it matches what
    `create_hemigrid("healpix", ...)` would build).
  * Geometry + assignment use **healpy directly** (`ang2pix`, `pix2ang`), NOT
    canvod's stored bbox (which is approximate) — exact pixel membership.
  * Rendering reuses canvod-viz, which draws true `healpy.boundaries`.

    dims:        (pair, time, cell)         cell = hemisphere HEALPix pixels
    coords:      cell_ids(cell)  + xdggs attrs {grid_name, level, indexing_scheme}
                 cell_theta/cell_phi(cell)  centres [rad]
    data_vars:   vod_sum, vod_sumsq, count  additive → poolable
    output:      _out/strategy2_healpix.zarr

Run: cd canvodpy && uv run --with healpy --with xdggs \
        python ../grid_storage/strategy2_healpix_xdggs/build.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import PAIRS, dir_size_mb, load_fixture

OUT = Path(__file__).resolve().parent.parent / "_out"
ZARR = OUT / "strategy2_healpix.zarr"
RES = 2.0


def main() -> None:
    import healpy as hp

    from canvod.grids import create_hemigrid

    fx = load_fixture()
    time = pd.to_datetime([fx["date"]])

    # nside from canvod's builder (stay consistent with create_hemigrid)
    cgrid = create_hemigrid("healpix", angular_resolution=RES)
    nside = int(cgrid.grid["healpix_nside"][0])
    level = int(np.log2(nside))
    print(
        f"canvod HEALPixBuilder -> nside={nside} (level={level}), "
        f"res~{hp.nside2resol(nside, arcmin=True) / 60:.2f} deg",
        flush=True,
    )

    # hemisphere pixel set (centre colatitude <= 90 deg), RING ordering -> the cube axis
    npix = hp.nside2npix(nside)
    all_theta, all_phi = hp.pix2ang(nside, np.arange(npix))
    hemi = np.where(all_theta <= np.pi / 2 + 1e-9)[0]
    hemi = np.sort(hemi)
    ncells = hemi.size
    ipix_to_cell = {int(ip): i for i, ip in enumerate(hemi)}
    print(f"hemisphere HEALPix pixels: {ncells}", flush=True)

    vsum = np.zeros((len(PAIRS), 1, ncells))
    vsq = np.zeros((len(PAIRS), 1, ncells))
    cnt = np.zeros((len(PAIRS), 1, ncells))
    for p, pair in enumerate(PAIRS):
        theta = fx[f"{pair}__theta"]  # colatitude (zenith=pole), matches healpy
        phi = fx[f"{pair}__phi"]
        vod = fx[f"{pair}__vod"]
        ipix = hp.ang2pix(nside, theta, phi)  # EXACT membership (not nearest-centre)
        # map global ipix -> cube cell index (all obs are in hemisphere by construction)
        cell = np.array([ipix_to_cell.get(int(ip), -1) for ip in ipix])
        ok = cell >= 0
        np.add.at(vsum[p, 0], cell[ok], vod[ok])
        np.add.at(vsq[p, 0], cell[ok], vod[ok] ** 2)
        np.add.at(cnt[p, 0], cell[ok], 1.0)
        print(
            f"[{pair}] {int(ok.sum()):,} obs -> {int((cnt[p, 0] > 0).sum())} "
            f"filled pixels",
            flush=True,
        )

    ctheta, cphi = hp.pix2ang(nside, hemi)
    ds = xr.Dataset(
        data_vars={
            "vod_sum": (("pair", "time", "cell"), vsum),
            "vod_sumsq": (("pair", "time", "cell"), vsq),
            "count": (("pair", "time", "cell"), cnt),
        },
        coords={
            "pair": ("pair", np.array(PAIRS)),
            "time": ("time", time),
            "cell_ids": (
                "cell",
                hemi.astype(np.int64),
                {
                    # xdggs grid descriptor — lets `ds.dggs.decode()` recognise it
                    "grid_name": "healpix",
                    "level": level,
                    "indexing_scheme": "ring",
                },
            ),
            "cell_theta": (
                "cell",
                ctheta,
                {
                    "units": "rad",
                    "long_name": "pixel-centre colatitude (=zenith angle)",
                },
            ),
            "cell_phi": (
                "cell",
                cphi,
                {"units": "rad", "long_name": "pixel-centre longitude (azimuth)"},
            ),
        },
        attrs={
            "title": "CARBONARA VOD hemisphere cube — HEALPix/xdggs (strategy 2)",
            "grid_type": "healpix",
            "healpix_nside": nside,
            "healpix_level": level,
            "indexing_scheme": "ring",
            "coordinate_frame": "topocentric mapped to HEALPix sphere "
            "(zenith->pole); NOT geographic",
            "spatial_axis": "cell = hemisphere HEALPix pixel (RING ipix in cell_ids)",
            "stats_rule": "store additive sum/sumsq/count; derive mean/std on read",
            "source_store_branch": "main",
        },
    )

    OUT.mkdir(parents=True, exist_ok=True)
    if ZARR.exists():
        import shutil

        shutil.rmtree(ZARR)
    ds.chunk({"time": 1}).to_zarr(ZARR, mode="w", consolidated=True)
    print(f"\nwrote {ZARR.name}  ({dir_size_mb(ZARR):.2f} MB)  dims={dict(ds.sizes)}")

    _xdggs_demo(ZARR)
    _render_proof(nside, hemi, ipix_to_cell, ds)


def _xdggs_demo(zarr_path: Path) -> None:
    """Prove the stored cube is a first-class xdggs DGGS dataset."""
    import xdggs  # noqa: F401

    ds = xr.open_zarr(zarr_path, consolidated=True)
    dec = ds.dggs.decode()  # reads cell_ids xdggs attrs
    centers = dec.dggs.cell_centers()  # lon/lat per cell, computed by xdggs
    print(
        "xdggs decode OK:",
        type(dec.dggs).__name__,
        "| cell_centers vars:",
        list(centers.coords),
    )


def _render_proof(nside, hemi, ipix_to_cell, ds) -> None:
    """Render through canvod-viz (true healpy boundaries) from the stored cube."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from canvod.grids import create_hemigrid
    from canvod.viz import HemisphereVisualizer, PolarPlotStyle

    cgrid = create_hemigrid("healpix", angular_resolution=RES)  # canvod grid for viz
    rt = xr.open_zarr(ZARR, consolidated=True)
    s = rt["vod_sum"].isel(pair=0, time=0).values
    c = rt["count"].isel(pair=0, time=0).values
    mean_by_cell = np.where(c > 0, s / np.where(c > 0, c, 1), np.nan)
    # map cube cells (ipix) -> canvod grid row order
    grid_ipix = cgrid.grid["healpix_ipix"].to_numpy()
    data = np.array(
        [
            mean_by_cell[ipix_to_cell[int(ip)]] if int(ip) in ipix_to_cell else np.nan
            for ip in grid_ipix
        ]
    )
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(6, 6))
    HemisphereVisualizer(cgrid).plot_2d(
        data=data,
        ax=ax,
        style=PolarPlotStyle(
            cmap="YlGn",
            vmin=0,
            vmax=float(np.nanpercentile(data, 98)),
            title="strategy2 round-trip: base_up VOD mean (HEALPix)",
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
