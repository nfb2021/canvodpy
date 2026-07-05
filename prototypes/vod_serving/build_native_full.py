"""Full-deployment NATIVE gridded VOD store (fresh icechunk repo).

Gridded in space (prescribed mesh + per-obs cell_id), NATIVE in time (every
observation keeps its epoch; no snapshot binning). Built from the entire source
rinex store, chunked for the "drag a time window -> grid on the fly" app.

Per pair (icechunk group) — two dims in one group:
  obs-dim (chunked 1e6, epoch-sorted):
     epoch(obs) datetime64   sid_code(obs) int16   cell_id(obs) int32   vod(obs) float32
  day-dim (tiny, drives the timeline + window->slice mapping):
     day_date(day)  day_count(day)   (cumsum -> obs offset per day)
Group 'meta':  sid lookup (source sid coordinate) -> decode sid_code, constellation
Group 'grid':  the static UGRID mesh (node_x/y/z, face_node_connectivity, ...)

sid_code = index into the source store's fixed sid coordinate (stable, global).

Run (background):
  cd canvodpy && RUST_LOG=error uv run python ../grid_storage/build_native_full.py \
      2>&1 | tee ~/native_full.log
Optional first/last day env: NATIVE_DAYS=30 limits to first N days (quick test).
"""

from __future__ import annotations

import os
import shutil
import sys
import time
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
from precompute_vod_summary import (  # noqa: E402
    PAIRS,
    day_bounds,
    open_session,
    vod_for_day,
)

STORE = ROOT / "_out" / "vod_native_full.icechunk"
RES = 2.0
OBS_CHUNK = 1_000_000
DAY_LIMIT = int(os.environ.get("NATIVE_DAYS", "0")) or None


def pair_pointcloud(can_ds, sky_ds, grid, sid_index):
    """Stream all days of one pair -> concatenated native obs + per-day index."""
    bounds = day_bounds(can_ds.epoch.values)
    if DAY_LIMIT:
        bounds = bounds[:DAY_LIMIT]
    vod_l, cid_l, sc_l, ep_l = [], [], [], []
    day_date, day_count, day_mean = [], [], []
    t0 = time.time()
    for k, (d, c0, c1) in enumerate(bounds):
        ds = vod_for_day(can_ds, sky_ds, c0, c1)
        n = 0
        if ds is not None:
            v = ds["VOD"].values
            th = ds["theta"].values
            ph = ds["phi"].values
            ep = ds["epoch"].values
            fin = np.isfinite(v) & np.isfinite(th) & np.isfinite(ph)
            ei, si = np.where(fin)
            order = np.argsort(ep[ei], kind="stable")
            ei, si = ei[order], si[order]
            if ei.size:
                th_o, ph_o = th[ei, si], ph[ei, si]
                vod_l.append(v[ei, si].astype("float32"))
                cid_l.append(assign_equal_area(grid, ph_o, th_o).astype("int32"))
                sc_l.append(sid_index[si].astype("int16"))  # global sid code
                ep_l.append(ep[ei])
                n = ei.size
                day_mean.append(float(np.mean(v[ei, si])))
            else:
                day_mean.append(np.nan)
        else:
            day_mean.append(np.nan)
        day_date.append(np.datetime64(pd.Timestamp(d), "D"))
        day_count.append(n)
        if k % 30 == 0:
            print(
                f"    day {k + 1}/{len(bounds)} ({pd.Timestamp(d).date()}) "
                f"obs so far {sum(day_count):,} ({time.time() - t0:.0f}s)",
                flush=True,
            )
    obs = xr.Dataset(
        {
            "vod": ("obs", np.concatenate(vod_l) if vod_l else np.zeros(0, "float32")),
            "sid_code": ("obs", np.concatenate(sc_l) if sc_l else np.zeros(0, "int16")),
            "cell_id": (
                "obs",
                np.concatenate(cid_l) if cid_l else np.zeros(0, "int32"),
            ),
            "day_date": ("day", np.array(day_date)),
            "day_count": ("day", np.array(day_count, "int64")),
            "day_mean_vod": ("day", np.array(day_mean, "float32")),
        },
        coords={
            "epoch": (
                "obs",
                np.concatenate(ep_l) if ep_l else np.array([], "datetime64[ns]"),
            )
        },
    )
    return obs


def main() -> None:
    t_all = time.time()
    grid = equal_area_grid(RES)
    mesh = build_mesh(grid)
    sess0 = open_session()

    shutil.rmtree(STORE, ignore_errors=True)
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(STORE)))

    # mesh + sid lookup (static)
    sess = repo.writable_session("main")
    mesh.to_zarr(sess.store, group="grid", mode="w", consolidated=False, zarr_format=3)
    sid_vals = None
    for pair, c_grp, s_grp in PAIRS:
        can = xr.open_zarr(sess0.store, group=c_grp, consolidated=False)
        sky = xr.open_zarr(sess0.store, group=s_grp, consolidated=False)
        if sid_vals is None:
            sid_vals = np.asarray(can.sid.values).astype("U12")
            sid_index = np.arange(sid_vals.size)
            xr.Dataset({"sid": ("sid_idx", sid_vals)}).to_zarr(
                sess.store, group="meta", mode="w", consolidated=False, zarr_format=3
            )
        print(f"[{pair}] streaming days...", flush=True)
        obs = pair_pointcloud(can, sky, grid, sid_index)
        obs.chunk({"obs": OBS_CHUNK}).to_zarr(
            sess.store, group=pair, mode="w", consolidated=False, zarr_format=3
        )
        print(
            f"[{pair}] wrote {obs.sizes['obs']:,} obs, {obs.sizes['day']} days",
            flush=True,
        )
        del obs
    cid = sess.commit(f"native gridded VOD full deployment (3 pairs, {RES}deg grid)")
    print(f"\ncommitted {cid[:12]} in {time.time() - t_all:.0f}s", flush=True)

    # quick read-back summary
    rs = repo.readonly_session("main")
    for pair, _, _ in PAIRS:
        o = xr.open_zarr(rs.store, group=pair, consolidated=False)
        print(
            f"  {pair}: {o.sizes['obs']:,} obs over {o.sizes['day']} days", flush=True
        )
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
