"""Precompute small VOD-summary artifacts from the geometry-repaired SNR store.

VOD = -ln(T) * cos(theta),  T = 10^((SNR_canopy - SNR_sky)/10)  (Tau-Omega,
zeroth order). We do NOT reimplement it: each per-day block is fed to canvod's
own `TauOmegaZerothOrder.from_datasets`, the guard-railed VOD code.

The three VOD pairs (sites.yaml `vod_analyses`, each canopy vs the sole sky_up
reference) map to store groups as:
    base_up_vs_sky_up   canopy=base_up    sky=sky_up_base_up
    nadir_in_vs_sky_up  canopy=nadir_in   sky=sky_up_nadir_in
    nadir_out_vs_sky_up canopy=nadir_out  sky=sky_up_nadir_out
The sky_up_* groups carry the reference SNR already aligned to each pair; we
inner-align per day on (epoch, sid) before computing.

Reads the corrected geometry from `main` (the geom_fix repair, promoted into
main on 2026-06-12; `geom_fix` is kept as a same-tip backup); theta/phi come from the
canopy antenna (signal path through canopy), as canvod's calculator dictates.

Outputs (mirror the SNR artifacts, instant notebook load):
  vod_daily_store.csv   date, pair, mean_vod, n_obs, mean_delta_snr  (full deployment)
  vod_hemi_window.npz   per-pair per-cell mean VOD on canvod's 2-deg equal-area
                        hemigrid, over the SAME window the SNR precompute chose
                        (read from snr_hemi_window.npz).

Run (canvodpy venv, background):
  cd canvodpy && RUST_LOG=error uv run python ../precompute_vod_summary.py \
      2>&1 | tee ~/vod_precompute.log
"""

import os
import time
from pathlib import Path

import icechunk
import numpy as np
import pandas as pd
import xarray as xr

from canvod.vod import TauOmegaZerothOrder

STORE = Path(
    "/home/nbader/shares/climers/Studies/GNSS_Vegetation_Study"
    "/05_data/03_Carbonara/02_GNSS/Icechunk_stores/tapajos/rinex"
)
BRANCH = os.environ.get("SNR_STORE_BRANCH", "main")
OUT_DIR = Path(__file__).resolve().parent
DAILY_CSV = OUT_DIR / "vod_daily_store.csv"
HEMI_NPZ = OUT_DIR / "vod_hemi_window.npz"
SNR_HEMI_NPZ = OUT_DIR / "snr_hemi_window.npz"  # reuse its window

# pair label -> (canopy group, sky/reference group)
PAIRS = [
    ("base_up_vs_sky_up", "base_up", "sky_up_base_up"),
    ("nadir_in_vs_sky_up", "nadir_in", "sky_up_nadir_in"),
    ("nadir_out_vs_sky_up", "nadir_out", "sky_up_nadir_out"),
]

GRID_TYPE = "equal_area"
GRID_RES = 2.0


def open_session():
    return icechunk.Repository.open(
        icechunk.local_filesystem_storage(str(STORE))
    ).readonly_session(BRANCH)


def day_bounds(ep: np.ndarray) -> list[tuple[np.datetime64, int, int]]:
    """(day, i0, i1) integer-index spans, one per calendar day."""
    day = ep.astype("datetime64[D]")
    out = []
    for d in np.unique(day):
        idx = np.where(day == d)[0]
        out.append((d, int(idx[0]), int(idx[-1] + 1)))
    return out


def vod_for_day(can_ds, sky_ds, c0, c1) -> xr.Dataset | None:
    """Inner-align canopy day-slice with the reference, return canvod VOD ds."""
    can = can_ds.isel(epoch=slice(c0, c1))
    # select the reference epochs overlapping this canopy day (sky has its own grid)
    t_lo, t_hi = can.epoch.values[0], can.epoch.values[-1]
    sep = sky_ds.epoch.values
    s0 = int(np.searchsorted(sep, t_lo))
    s1 = int(np.searchsorted(sep, t_hi, side="right"))
    if s1 <= s0:
        return None
    sky = sky_ds.isel(epoch=slice(s0, s1))
    can = can.load()
    sky = sky[["SNR"]].load()
    return TauOmegaZerothOrder.from_datasets(canopy_ds=can, sky_ds=sky, align=True)


def pass1_daily(sess) -> pd.DataFrame:
    rows = []
    for pair, c_grp, s_grp in PAIRS:
        can_ds = xr.open_zarr(sess.store, group=c_grp, consolidated=False)
        sky_ds = xr.open_zarr(sess.store, group=s_grp, consolidated=False)
        bounds = day_bounds(can_ds.epoch.values)
        t0 = time.time()
        for k, (d, c0, c1) in enumerate(bounds):
            ds = vod_for_day(can_ds, sky_ds, c0, c1)
            if ds is None:
                continue
            v = ds["VOD"].values
            dsnr = ds["delta_snr"].values
            fin = np.isfinite(v)
            n = int(fin.sum())
            rows.append(
                {
                    "date": pd.Timestamp(d).date(),
                    "pair": pair,
                    "mean_vod": float(np.nanmean(v[fin])) if n else np.nan,
                    "median_vod": float(np.nanmedian(v[fin])) if n else np.nan,
                    "n_obs": n,
                    "mean_delta_snr": float(np.nanmean(dsnr[np.isfinite(dsnr)]))
                    if np.isfinite(dsnr).any()
                    else np.nan,
                }
            )
            if k % 30 == 0:
                print(
                    f"  [{pair}] day {k + 1}/{len(bounds)} ({time.time() - t0:.0f}s)",
                    flush=True,
                )
        print(
            f"[{pair}] daily done in {time.time() - t0:.0f}s, days={len(bounds)}",
            flush=True,
        )
    df = pd.DataFrame(rows)
    df.to_csv(DAILY_CSV, index=False)
    print(f"wrote {DAILY_CSV} ({len(df)} rows)", flush=True)
    return df


def pass2_hemi(sess, win_start: pd.Timestamp, win_end: pd.Timestamp):
    from canvod.grids import create_hemigrid
    from canvod.grids.operations import _build_kdtree, _query_points

    grid = create_hemigrid(GRID_TYPE, angular_resolution=GRID_RES)
    tree = _build_kdtree(grid)
    cell_id_col = grid.grid["cell_id"].to_numpy()
    ncells = grid.ncells
    print(f"equal-area grid: {ncells} cells @ {GRID_RES} deg", flush=True)

    t_lo = np.datetime64(win_start, "ns")
    t_hi = np.datetime64(win_end + pd.Timedelta(days=1), "ns")
    grids = {}
    for pair, c_grp, s_grp in PAIRS:
        can_ds = xr.open_zarr(sess.store, group=c_grp, consolidated=False)
        sky_ds = xr.open_zarr(sess.store, group=s_grp, consolidated=False)
        ep = can_ds.epoch.values
        i0 = int(np.searchsorted(ep, t_lo))
        i1 = int(np.searchsorted(ep, t_hi))
        csum = np.zeros(ncells)
        ccnt = np.zeros(ncells)
        t0 = time.time()
        for d, c0, c1 in day_bounds(ep[i0:i1]):
            ds = vod_for_day(can_ds, sky_ds, i0 + c0, i0 + c1)
            if ds is None:
                continue
            v = ds["VOD"].values
            th = ds["theta"].values
            ph = ds["phi"].values
            fin = np.isfinite(v) & np.isfinite(th) & np.isfinite(ph)
            if not fin.any():
                continue
            cid = _query_points(tree, cell_id_col, ph[fin], th[fin]).astype(np.int64)
            np.add.at(csum, cid, v[fin])
            np.add.at(ccnt, cid, 1.0)
        mean = np.where(ccnt > 0, csum / np.where(ccnt > 0, ccnt, 1), np.nan)
        grids[f"{pair}__mean"] = mean
        grids[f"{pair}__cnt"] = ccnt
        print(
            f"[{pair}] hemi done in {time.time() - t0:.0f}s, "
            f"filled cells={int((ccnt > 0).sum())}/{ncells}",
            flush=True,
        )
    np.savez(
        HEMI_NPZ,
        grid_type=GRID_TYPE,
        resolution=GRID_RES,
        ncells=ncells,
        win_start=str(win_start.date()),
        win_end=str(win_end.date()),
        pairs=np.array([p for p, _, _ in PAIRS]),
        **grids,
    )
    print(f"wrote {HEMI_NPZ}", flush=True)


def main():
    import sys

    t0 = time.time()
    w = np.load(SNR_HEMI_NPZ, allow_pickle=True)
    win_start = pd.Timestamp(str(w["win_start"]))
    win_end = pd.Timestamp(str(w["win_end"]))
    print(f"using SNR window {win_start.date()} .. {win_end.date()}", flush=True)

    if "--hemi-only" not in sys.argv[1:]:
        pass1_daily(open_session())
    pass2_hemi(open_session(), win_start, win_end)
    print(f"ALL DONE in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
