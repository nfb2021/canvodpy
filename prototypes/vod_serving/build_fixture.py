"""Shared 24h observation fixture for the three grid-storage strategies.

Pulls ONE calendar day of VOD for all three pairs from the corrected `main`
store (via canvod's guard-railed `TauOmegaZerothOrder`, reusing
`precompute_vod_summary.vod_for_day`), and saves the **raw per-observation**
(phi, theta, VOD) arrays — finite only.

Why raw obs (not pre-binned)? Strategy 1 & 3 bin to canvod's equal-area cells;
Strategy 2 re-tessellates onto HEALPix. They must share the *same input obs*,
so the fixture is the obs themselves, not any one grid's binning.

Output: grid_storage/_fixture/obs_24h.npz
  date            (str)
  pairs           (3,) labels
  <pair>__phi     (n_obs,) azimuth   [rad, from N clockwise]  (canvod convention)
  <pair>__theta   (n_obs,) polar     [rad, from zenith]
  <pair>__vod     (n_obs,) VOD
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from precompute_vod_summary import PAIRS, open_session, vod_for_day  # noqa: E402

DAY = pd.Timestamp("2025-10-08")  # inside the dense SNR window, all pairs present
OUT = Path(__file__).resolve().parent / "_fixture" / "obs_24h.npz"


def day_slice_bounds(ep: np.ndarray, day: pd.Timestamp) -> tuple[int, int]:
    d = ep.astype("datetime64[D]")
    lo = np.datetime64(day.date())
    idx = np.where(d == lo)[0]
    if idx.size == 0:
        return 0, 0
    return int(idx[0]), int(idx[-1] + 1)


def main() -> None:
    sess = open_session()
    out: dict[str, np.ndarray] = {
        "date": np.array(str(DAY.date())),
        "pairs": np.array([p for p, _, _ in PAIRS]),
    }
    for pair, c_grp, s_grp in PAIRS:
        can_ds = xr.open_zarr(sess.store, group=c_grp, consolidated=False)
        sky_ds = xr.open_zarr(sess.store, group=s_grp, consolidated=False)
        c0, c1 = day_slice_bounds(can_ds.epoch.values, DAY)
        if c1 <= c0:
            print(f"[{pair}] no obs on {DAY.date()}", flush=True)
            out[f"{pair}__phi"] = np.array([])
            out[f"{pair}__theta"] = np.array([])
            out[f"{pair}__vod"] = np.array([])
            continue
        ds = vod_for_day(can_ds, sky_ds, c0, c1)
        v = ds["VOD"].values.ravel()
        th = ds["theta"].values.ravel()
        ph = ds["phi"].values.ravel()
        fin = np.isfinite(v) & np.isfinite(th) & np.isfinite(ph)
        out[f"{pair}__phi"] = ph[fin].astype(np.float64)
        out[f"{pair}__theta"] = th[fin].astype(np.float64)
        out[f"{pair}__vod"] = v[fin].astype(np.float64)
        print(
            f"[{pair}] {int(fin.sum()):,} finite obs on {DAY.date()} "
            f"(VOD median {np.median(v[fin]):.2f})",
            flush=True,
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez(OUT, **out)
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
