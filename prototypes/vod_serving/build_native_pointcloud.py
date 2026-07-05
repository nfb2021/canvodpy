"""VOD store: GRIDDED in space, NATIVE temporal resolution.

The store IS gridded — the prescribed equal-area mesh is stored once, and every
observation carries its `cell_id` (canvod's `add_cell_ids` pattern). What stays
NATIVE is time: each observation keeps its own epoch; there is NO daily/weekly
snapshot binning. Snapshots / per-cell means are a DOWNSTREAM temporal
resampling (groupby cell_id over an epoch window) — not the stored form.

Layout (icechunk, branch main):
  group 'grid'              the prescribed UGRID mesh (static): node_x/y/z,
                            face_node_connectivity, face centres, solid angles
  group '<pair>'  per pair, a 1-D `obs` dataset at native time resolution:
     coords: epoch(obs)  native timestamp        [datetime64]
             sid(obs)    satellite|band|code     -> constellation / n_sats for free
     vars:   vod(obs), theta(obs), phi(obs)      exact direction [rad]
             cell_id(obs)  assignment into the prescribed grid  (the GRIDDED part)

VOD is canvod's guard-railed TauOmegaZerothOrder; cell_id is canvod's KDTree
assignment. We persist the finite observations at native epochs instead of
binning them in time.

Run: cd canvodpy && uv run python ../grid_storage/build_native_pointcloud.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import icechunk
import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
from _common import assign_equal_area, equal_area_grid  # noqa: E402
from build_icechunk_cube import build_mesh  # noqa: E402
from precompute_vod_summary import PAIRS, open_session, vod_for_day  # noqa: E402

STORE = ROOT / "_out" / "vod_native.icechunk"
DAY = pd.Timestamp("2025-10-08")
RES = 2.0


def day_bounds(ep, day):
    d = ep.astype("datetime64[D]")
    idx = np.where(d == np.datetime64(day.date()))[0]
    return (int(idx[0]), int(idx[-1] + 1)) if idx.size else (0, 0)


def pointcloud_for_pair(can_ds, sky_ds, grid) -> xr.Dataset:
    c0, c1 = day_bounds(can_ds.epoch.values, DAY)
    ds = vod_for_day(can_ds, sky_ds, c0, c1)  # (epoch, sid): VOD, theta, phi
    v = ds["VOD"].values
    th = ds["theta"].values
    ph = ds["phi"].values
    ep = ds["epoch"].values
    sid = np.asarray(ds["sid"].values)
    fin = np.isfinite(v) & np.isfinite(th) & np.isfinite(ph)
    ei, si = np.where(fin)
    order = np.argsort(ep[ei], kind="stable")  # native time order
    ei, si = ei[order], si[order]
    th_o, ph_o, v_o = th[ei, si], ph[ei, si], v[ei, si]
    cell_id = assign_equal_area(grid, ph_o, th_o)  # GRIDDED: prescribed mesh
    return xr.Dataset(
        {
            "vod": ("obs", v_o.astype("float32")),
            "theta": ("obs", th_o.astype("float32"), {"units": "rad"}),
            "phi": ("obs", ph_o.astype("float32"), {"units": "rad"}),
            "cell_id": (
                "obs",
                cell_id.astype("int32"),
                {"long_name": "prescribed equal-area cell index", "grid": "grid"},
            ),
        },
        coords={"epoch": ("obs", ep[ei]), "sid": ("obs", sid[si].astype("U12"))},
        attrs={"long_name": "native-temporal VOD obs, gridded via cell_id"},
    )


def main() -> None:
    grid = equal_area_grid(RES)
    mesh = build_mesh(grid)
    mesh.attrs.update(
        {
            "Conventions": "UGRID-1.0",
            "grid_type": "equal_area",
            "angular_resolution_deg": RES,
        }
    )

    sess0 = open_session()
    clouds = {}
    for pair, c_grp, s_grp in PAIRS:
        can = xr.open_zarr(sess0.store, group=c_grp, consolidated=False)
        sky = xr.open_zarr(sess0.store, group=s_grp, consolidated=False)
        pc = pointcloud_for_pair(can, sky, grid)
        clouds[pair] = pc
        cons = pd.Series([s[0] for s in pc["sid"].values]).value_counts().to_dict()
        print(
            f"[{pair}] {pc.sizes['obs']:,} obs | "
            f"{int((np.bincount(pc.cell_id.values) > 0).sum())} cells touched | "
            f"constellations {cons}",
            flush=True,
        )

    shutil.rmtree(STORE, ignore_errors=True)
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(STORE)))
    sess = repo.writable_session("main")
    mesh.to_zarr(sess.store, group="grid", mode="w", consolidated=False, zarr_format=3)
    for pair, pc in clouds.items():
        pc.chunk({"obs": 200_000}).to_zarr(
            sess.store, group=pair, mode="w", consolidated=False, zarr_format=3
        )
    cid = sess.commit(f"native-temporal gridded VOD {DAY.date()} (mesh + 3 pairs)")
    print(f"\ncommitted {cid[:12]}", flush=True)
    _show(repo, grid)


def _show(repo, grid) -> None:
    sess = repo.readonly_session("main")
    pair = PAIRS[0][0]
    obs = xr.open_zarr(sess.store, group=pair, consolidated=False).load()
    meshg = xr.open_zarr(sess.store, group="grid", consolidated=False)
    print("\n" + "=" * 72)
    print("STORE: gridded (mesh) + native-temporal observations")
    print("=" * 72)
    print(
        f"group 'grid'  (static prescribed mesh): n_face={meshg.sizes['n_face']}, "
        f"n_node={meshg.sizes['n_node']}"
    )
    print(f"\ngroup '{pair}'  (native-temporal obs):")
    print(obs)

    print("\n--- native temporal subsetting (no snapshot binning) ---")
    t0, t1 = np.datetime64("2025-10-08T12:00"), np.datetime64("2025-10-08T14:00")
    win = obs.where((obs.epoch >= t0) & (obs.epoch < t1), drop=True)
    print(f"  2h window 12:00-14:00 -> {win.sizes['obs']:,} obs at native epochs")

    print("\n--- DOWNSTREAM gridded view = groupby cell_id over the window ---")
    ncells = grid.ncells
    cidv = win.cell_id.values.astype(int)
    vv = win.vod.values
    s = np.zeros(ncells)
    c = np.zeros(ncells)
    np.add.at(s, cidv, vv)
    np.add.at(c, cidv, 1.0)
    mean = np.where(c > 0, s / np.where(c > 0, c, 1), np.nan)
    print(
        f"  -> per-cell mean over the 2h window: {int((c > 0).sum())} filled cells, "
        f"median VOD {np.nanmedian(mean):.2f}"
    )
    print("  (a weekly snapshot cube is the same op over a 1-week epoch window)")


if __name__ == "__main__":
    main()
