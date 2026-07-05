"""Add a cumulative temporal ROLLUP to the SAME icechunk store (no second store).

For each pair, bin the native obs by time and store the CUMULATIVE (prefix-sum)
per-cell moments. Any window [a,b] is then `cum[b] - cum[a]` — O(1), instant,
read straight from icechunk. The 24h pipeline would append one cumulative slice
per day in the same commit that appends the obs.

Writes group `rollup/<pair>` into the existing store:
    dims (edge, cell)   edge = bin boundaries (n_bins+1, cum[0]=0)
    cum_sum, cum_sumsq, cum_count                 -> mean, std, count for any window
    cum_count_G/E/C/R                             -> per-constellation counts (additive)
    coord edge_time(edge)                         -> map a time window to edge indices

Prototype bins by HOUR (the 24h store). On the full store this is per-DAY; the
code is identical, only `FREQ` changes.

Run: cd canvodpy && uv run python ../grid_storage/build_rollup.py
"""

from __future__ import annotations

import os
from pathlib import Path

import icechunk
import numpy as np
import pandas as pd
import xarray as xr

# Override via env for the full store:
#   ROLLUP_STORE=.../vod_native_full.icechunk ROLLUP_FREQ=1D
_DEFAULT = "/home/nbader/Developer/GNSS/carbonara_plotter/grid_storage/_out/vod_native.icechunk"
STORE = Path(os.environ.get("ROLLUP_STORE", _DEFAULT))
PAIRS = ["base_up_vs_sky_up", "nadir_in_vs_sky_up", "nadir_out_vs_sky_up"]
CONS = ["G", "E", "C", "R"]
FREQ = os.environ.get("ROLLUP_FREQ", "1h")  # prototype: hourly; full store -> "1D"


def cons_per_obs(obs: xr.Dataset, sid_lut: np.ndarray | None) -> np.ndarray:
    """First-letter constellation per obs, vectorized for both store schemas.

    24h store carries the string `sid` coord directly; the full store carries
    `sid_code` (int16) indexing the `meta` group's `sid` lookup. The string path
    over 1e8 obs must NOT be a Python loop, so build a small per-code letter
    table and fancy-index it.
    """
    if sid_lut is not None:  # full store: int codes
        code = obs.sid_code.values
        letters = np.array([s[0] for s in sid_lut.astype(str)])  # len = n_sid (small)
        return letters[code]
    return np.array([s[0] for s in obs.sid.values.astype(str)])  # 24h store


def rollup_for_pair(
    obs: xr.Dataset, ncells: int, sid_lut: np.ndarray | None
) -> xr.Dataset:
    ep = pd.to_datetime(obs.epoch.values)
    cid = obs.cell_id.values.astype(np.int32)
    v = obs.vod.values.astype(float)
    cons = cons_per_obs(obs, sid_lut)

    edges = pd.date_range(ep.min().floor(FREQ), ep.max().ceil(FREQ), freq=FREQ)
    nb = len(edges) - 1
    binidx = np.clip(
        np.searchsorted(edges.values, ep.values, side="right") - 1, 0, nb - 1
    ).astype(np.int32)

    def per_bin(weights=None, sel=None):
        out = np.zeros((nb, ncells))
        m = np.ones(cid.size, bool) if sel is None else sel
        w = (np.ones(cid.size) if weights is None else weights)[m]
        flat = (
            binidx[m].astype(np.int64) * ncells + cid[m]
        )  # max ~nb*ncells, fits int64
        out.ravel()[:] = np.bincount(flat, weights=w, minlength=nb * ncells)
        return out

    bin_sum = per_bin(v)
    bin_sumsq = per_bin(v * v)
    bin_cnt = per_bin()
    cons_cnt = {c: per_bin(sel=(cons == c)) for c in CONS}

    def cum(a):  # prepend a zero edge -> cum[k] = sum of first k bins
        return np.concatenate([np.zeros((1, ncells)), np.cumsum(a, axis=0)], axis=0)

    data = {
        "cum_sum": (("edge", "cell"), cum(bin_sum)),
        "cum_sumsq": (("edge", "cell"), cum(bin_sumsq)),
        "cum_count": (("edge", "cell"), cum(bin_cnt)),
    }
    for c in CONS:
        data[f"cum_count_{c}"] = (("edge", "cell"), cum(cons_cnt[c]))
    return xr.Dataset(
        data,
        coords={"edge_time": ("edge", edges.values)},
        attrs={"freq": FREQ, "n_bins": nb},
    )


def main() -> None:
    print(f"store={STORE.name}  freq={FREQ}", flush=True)
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(STORE)))
    rs = repo.readonly_session("main")
    ncells = xr.open_zarr(rs.store, group="grid", consolidated=False).sizes["n_face"]

    # full store encodes constellation as sid_code -> meta/sid; 24h store has none
    try:
        sid_lut = xr.open_zarr(rs.store, group="meta", consolidated=False).sid.values
    except KeyError, FileNotFoundError, ValueError:
        sid_lut = None

    sess = repo.writable_session("main")
    for pair in PAIRS:
        obs = xr.open_zarr(rs.store, group=pair, consolidated=False).load()
        roll = rollup_for_pair(obs, ncells, sid_lut)
        del obs
        roll.to_zarr(
            sess.store,
            group=f"rollup/{pair}",
            mode="w",
            consolidated=False,
            zarr_format=3,
        )
        print(
            f"[{pair}] rollup {dict(roll.sizes)} edges; "
            f"size≈{sum(roll[v].nbytes for v in roll.data_vars) / 1e6:.1f} MB",
            flush=True,
        )
    cid = sess.commit("add cumulative temporal rollup (same store, no second store)")
    print(f"committed {cid[:12]} — rollup/<pair> groups added in place", flush=True)


if __name__ == "__main__":
    main()
