"""xpublish serving layer for the hemisphere viz — straight from icechunk.

A thin compute server (the Earthmover pattern: serve directly from the source
store, no second copy). It reads the cumulative ROLLUP group from the SAME
icechunk store and answers windowed queries by PREFIX SUBTRACTION:

    window [t0,t1]  ->  agg = cum[t1] - cum[t0]   (O(1), per-cell sum/sumsq/count)
                    ->  mean / std / count        (derived)

Per request it moves ~6448 numbers, not raw observations — so it is I/O-bound,
trivially CPU-light (plain numpy), no GPU. Endpoints:

    GET /pairs                                  pairs + native time range
    GET /mesh                                   static cell geometry (once)
    GET /hemisphere/{pair}?t0=&t1=&layer=&cons=  windowed per-cell array

Run a live server:  cd canvodpy && uv run --with xpublish --with fastapi --with uvicorn \
    python ../grid_storage/serve_hemisphere.py
Self-test (no server): ... python ../grid_storage/serve_hemisphere.py --selftest
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import icechunk
import numpy as np
import xarray as xr
import xpublish
from fastapi import APIRouter, HTTPException, Query
from xpublish import Dependencies, Plugin, hookimpl

# Override via env to serve the full store:
#   SERVE_STORE=.../vod_native_full.icechunk
_DEFAULT = "/home/nbader/Developer/GNSS/carbonara_plotter/grid_storage/_out/vod_native.icechunk"
STORE = Path(os.environ.get("SERVE_STORE", _DEFAULT))
PAIRS = ["base_up_vs_sky_up", "nadir_in_vs_sky_up", "nadir_out_vs_sky_up"]


def _load(store_path: Path) -> dict:
    """Load the static mesh + the small cumulative rollups into memory (once)."""
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store_path)))
    rs = repo.readonly_session("main")
    g = xr.open_zarr(rs.store, group="grid", consolidated=False)
    mesh = {
        "node": np.stack([g.node_x.values, g.node_y.values, g.node_z.values], 1),
        "faces": g.face_node_connectivity.values.astype(int),
        "ncells": int(g.sizes["n_face"]),
    }
    rolls = {}
    for p in PAIRS:
        r = xr.open_zarr(rs.store, group=f"rollup/{p}", consolidated=False).load()
        rolls[p] = r
    return {"mesh": mesh, "rolls": rolls}


STATE = _load(STORE)


def _aggregate(pair: str, t0: str, t1: str, layer: str, cons: str | None) -> dict:
    if pair not in STATE["rolls"]:
        raise HTTPException(404, f"unknown pair {pair}")
    r = STATE["rolls"][pair]
    et = r.edge_time.values
    a = int(np.clip(np.searchsorted(et, np.datetime64(t0)), 0, et.size - 1))
    b = int(np.clip(np.searchsorted(et, np.datetime64(t1)), 0, et.size - 1))
    if b <= a:
        raise HTTPException(400, "empty or reversed time window")

    def delta(name):  # prefix subtraction -> windowed total
        c = r[name].values
        return c[b] - c[a]

    cnt = delta("cum_count")
    if layer == "count":
        val = np.where(cnt > 0, delta(f"cum_count_{cons}") if cons else cnt, np.nan)
    elif layer == "mean":
        s = delta("cum_sum")
        val = np.where(cnt > 0, s / np.where(cnt > 0, cnt, 1), np.nan)
    elif layer == "std":
        s, s2 = delta("cum_sum"), delta("cum_sumsq")
        mean = np.where(cnt > 0, s / np.where(cnt > 0, cnt, 1), np.nan)
        var = np.clip(
            np.where(cnt > 0, s2 / np.where(cnt > 0, cnt, 1) - mean**2, np.nan), 0, None
        )
        val = np.where(cnt >= 2, np.sqrt(var), np.nan)
    else:
        raise HTTPException(400, f"unknown layer {layer}")
    finite = val[np.isfinite(val)]
    return {
        "pair": pair,
        "layer": layer,
        "t0": t0,
        "t1": t1,
        "nobs": int(np.nansum(cnt)),
        "ncells": val.size,
        "filled_cells": int(np.isfinite(val).sum()),
        "vmax": float(np.percentile(finite, 98)) if finite.size else 0.0,
        "values": [None if not np.isfinite(x) else round(float(x), 4) for x in val],
    }


class HemispherePlugin(Plugin):
    name: str = "hemisphere"

    @hookimpl
    def app_router(self, deps: Dependencies) -> APIRouter:
        router = APIRouter()

        @router.get("/pairs")
        def pairs():
            out = {}
            for p in PAIRS:
                et = STATE["rolls"][p].edge_time.values
                out[p] = {
                    "t_start": str(et[0]),
                    "t_end": str(et[-1]),
                    "freq": STATE["rolls"][p].attrs.get("freq"),
                }
            return out

        @router.get("/mesh")
        def mesh():
            m = STATE["mesh"]
            return {
                "ncells": m["ncells"],
                "n_node": int(m["node"].shape[0]),
                "node_xyz": m["node"].round(6).tolist(),
                "faces": m["faces"].tolist(),
            }

        @router.get("/hemisphere/{pair}")
        def hemisphere(
            pair: str,
            t0: str = Query(...),
            t1: str = Query(...),
            layer: str = "mean",
            cons: str | None = None,
        ):
            return _aggregate(pair, t0, t1, layer, cons)

        return router


def make_app():
    return xpublish.Rest({}, plugins={"hemisphere": HemispherePlugin()}).app


def _selftest():
    from fastapi.testclient import TestClient

    app = make_app()
    c = TestClient(app)
    pr = c.get("/pairs").json()
    p0 = PAIRS[0]
    t0, t1 = pr[p0]["t_start"], pr[p0]["t_end"]
    print("pairs:", {k: (v["t_start"][:16], v["t_end"][:16]) for k, v in pr.items()})
    m = c.get("/mesh").json()
    print(f"/mesh: ncells={m['ncells']} n_node={m['n_node']}")
    # full-day window, all layers
    for layer in ("mean", "std", "count"):
        r = c.get(
            f"/hemisphere/{p0}", params={"t0": t0, "t1": t1, "layer": layer}
        ).json()
        print(
            f"/hemisphere {layer}: {r['filled_cells']} cells, nobs={r['nobs']:,}, "
            f"vmax={r['vmax']:.2f}, len(values)={len(r['values'])}"
        )
    # a 2-hour brushed sub-window (prefix subtraction)
    et = STATE["rolls"][p0].edge_time.values
    w0, w1 = str(et[6]), str(et[8])
    r = c.get(f"/hemisphere/{p0}", params={"t0": w0, "t1": w1, "layer": "mean"}).json()
    print(
        f"/hemisphere mean (window {w0[11:16]}-{w1[11:16]}): "
        f"{r['filled_cells']} cells, nobs={r['nobs']:,}"
    )
    # constellation-filtered count
    r = c.get(
        f"/hemisphere/{p0}", params={"t0": t0, "t1": t1, "layer": "count", "cons": "G"}
    ).json()
    print(f"/hemisphere count (GPS only): nobs={r['nobs']:,}")
    print("SELFTEST OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        _selftest()
    else:
        import uvicorn

        uvicorn.run(make_app(), host="127.0.0.1", port=8000)
