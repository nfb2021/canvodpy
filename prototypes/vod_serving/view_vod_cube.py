"""Marimo viewer — native gridded VOD store, DRAGGABLE timeline, SERVED aggregation.

A wigglystuff box-brush over the per-day timeline selects a time window. Instead
of scanning the windowed obs locally, the viewer is now a THIN CLIENT: each brush
issues `GET /hemisphere/{pair}?t0=&t1=&layer=&cons=` to the running
`serve_hemisphere.py`, which answers in O(1) by prefix subtraction over the
cumulative daily rollup (`cum[t1] - cum[t0]`). The per-brush payload is ~6448
numbers, not up to 1e8 observations. The store is still opened locally for the
static mesh + the tiny daily timeline (day_date/count/mean).

Layers served by the rollup: mean · std · count. The constellation filter applies
to `count` only (the rollup stores per-cons COUNTS, not per-cons sum/sumsq);
`n_sats` is not in the rollup. Both are future polish (per-cons moments / HLL).

Requires the server, pointed at the SAME (full) store:
  cd canvodpy && SERVE_STORE=$PWD/../grid_storage/_out/vod_native_full.icechunk \
      uv run --with xpublish --with fastapi --with uvicorn \
      python ../grid_storage/serve_hemisphere.py
Run the viewer (override the URL with HEMI_ENDPOINT if not 127.0.0.1:8000):
  cd canvodpy && uv run --with marimo --with plotly --with wigglystuff --with httpx \
      --with ipywidgets \
      marimo edit ../grid_storage/view_vod_cube.py
(ipywidgets is required: the 3D plot is a plotly FigureWidget so the camera
 persists across brushes — it is recolored in place, not rebuilt.)
"""

import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import os
    from pathlib import Path

    import httpx
    import marimo as mo
    import matplotlib
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    import plotly.graph_objects as go

    return Path, go, httpx, matplotlib, mdates, mo, np, os, plt


@app.cell
def _(Path, mo, np):
    import icechunk
    import xarray as xr

    STORE = Path(__file__).resolve().parent / "_out" / "vod_native_full.icechunk"
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(STORE)))
    sess = repo.readonly_session("main")

    meshg = xr.open_zarr(sess.store, group="grid", consolidated=False)
    NODE = np.stack([meshg.node_x.values, meshg.node_y.values, meshg.node_z.values], 1)
    CONN = meshg.face_node_connectivity.values.astype(int)
    NCELLS = meshg.sizes["n_face"]

    PAIRS = ["base_up_vs_sky_up", "nadir_in_vs_sky_up", "nadir_out_vs_sky_up"]
    DAYS = {}
    for p in PAIRS:
        _o = xr.open_zarr(
            sess.store, group=p, consolidated=False
        )  # LAZY (day index only)
        DAYS[p] = {
            "date": _o.day_date.values,
            "count": _o.day_count.values.astype(np.int64),
            "mean": _o.day_mean_vod.values,
        }
    mo.md(
        f"**Native store** `{STORE.name}` — {NCELLS} cells, "
        + ", ".join(
            f"{p.split('_vs')[0]}={int(DAYS[p]['count'].sum()):,} obs/"
            f"{DAYS[p]['date'].size}d"
            for p in PAIRS
        )
    )
    return CONN, DAYS, NCELLS, NODE, PAIRS


@app.cell
def _(httpx, mo, os):
    ENDPOINT = os.environ.get("HEMI_ENDPOINT", "http://127.0.0.1:8000")
    try:
        _up = httpx.get(f"{ENDPOINT}/pairs", timeout=3.0).status_code == 200
    except Exception:
        _up = False
    _msg = (
        f"🛰️ aggregating on **`{ENDPOINT}`** — O(1) prefix subtraction over the "
        "daily rollup, ~6448 numbers per brush"
        if _up
        else f"⚠️ **no server at `{ENDPOINT}`.** Start it (same full store):\n\n"
        "```\ncd canvodpy && SERVE_STORE=$PWD/../grid_storage/_out/"
        "vod_native_full.icechunk \\\n  uv run --with xpublish --with fastapi "
        "--with uvicorn \\\n  python ../grid_storage/serve_hemisphere.py\n```"
    )
    mo.callout(mo.md(_msg), kind="success" if _up else "warn")
    return (ENDPOINT,)


@app.cell
def _(PAIRS, mo):
    pair = mo.ui.dropdown(PAIRS, value=PAIRS[0], label="pair")
    layer = mo.ui.dropdown(["mean", "std", "count"], value="mean", label="layer")
    cons = mo.ui.dropdown(
        ["All", "G (GPS)", "E (Galileo)", "C (BeiDou)", "R (GLONASS)"],
        value="All",
        label="constellation",
    )
    proj = mo.ui.radio(
        ["flat (equidistant)", "over-zenith (orthographic)"],
        value="flat (equidistant)",
        label="2D radial",
    )
    mo.hstack([pair, layer, proj, cons])
    return cons, layer, pair, proj


@app.cell
def _(DAYS, mo, pair, plt):
    from wigglystuff import ChartSelect

    _d = DAYS[pair.value]
    _dates = _d["date"].astype("datetime64[D]")
    _figt, _ax = plt.subplots(figsize=(9, 1.8))
    _ax.plot(_dates, _d["mean"], "-", lw=1.2, color="#1b7837")
    _ax.fill_between(_dates, 0, _d["mean"], color="#1b7837", alpha=0.12)
    _ax.set_ylabel("daily mean VOD", fontsize=8)
    _ax.set_title(
        f"timeline — {pair.value}  (drag a box to select a time window)", fontsize=9
    )
    _ax.margins(x=0.01)
    _ax.tick_params(labelsize=7)
    timeline = mo.ui.anywidget(ChartSelect(_figt, mode="box", modes=["box"]))
    plt.close(_figt)
    timeline
    return (timeline,)


@app.cell
def _(DAYS, mdates, np, pair, timeline):
    # resolve brushed window -> day indices -> ISO timestamps for the endpoint
    _d = DAYS[pair.value]
    _dates = _d["date"].astype("datetime64[ns]")
    lo_i, hi_i = 0, _dates.size - 1
    if getattr(timeline, "has_selection", False) and timeline.selection:
        _s = timeline.selection
        _lo = np.datetime64(mdates.num2date(_s["x_min"]).replace(tzinfo=None), "ns")
        _hi = np.datetime64(mdates.num2date(_s["x_max"]).replace(tzinfo=None), "ns")
        _in = np.where((_dates >= _lo) & (_dates <= _hi))[0]
        if _in.size:
            lo_i, hi_i = int(_in[0]), int(_in[-1])
    # daily rollup edges are day boundaries; t1 is exclusive so +1 day includes hi_i
    t0 = str(_d["date"][lo_i].astype("datetime64[D]"))
    t1 = str(_d["date"][hi_i].astype("datetime64[D]") + np.timedelta64(1, "D"))
    span = f"{str(_d['date'][lo_i])[:10]} … {str(_d['date'][hi_i])[:10]}"
    return span, t0, t1


@app.cell
def _(ENDPOINT, NCELLS, cons, httpx, layer, np, pair, t0, t1):
    # thin client: the server aggregates the window (prefix subtraction) and
    # returns one per-cell array. cons filter only bites on the count layer.
    import time as _time

    _params = {"t0": t0, "t1": t1, "layer": layer.value}
    if cons.value != "All" and layer.value == "count":
        _params["cons"] = cons.value[0]
    _t = _time.perf_counter()
    _r = httpx.get(f"{ENDPOINT}/hemisphere/{pair.value}", params=_params, timeout=60.0)
    _r.raise_for_status()
    _j = _r.json()
    ms = (_time.perf_counter() - _t) * 1e3
    val = np.array([np.nan if x is None else x for x in _j["values"]], float)
    if val.size != NCELLS:  # defensive: mesh/rollup mismatch
        val = np.full(NCELLS, np.nan)
    nobs = int(_j["nobs"])
    filled = int(_j["filled_cells"])
    vmax_srv = float(_j["vmax"])
    return filled, ms, nobs, val, vmax_srv


@app.cell
def _(NCELLS, cons, filled, layer, mo, ms, nobs, pair, span, vmax_srv):
    _warn = (
        "  ·  ⚠️ constellation filter applies to **count** only"
        if cons.value != "All" and layer.value != "count"
        else ""
    )
    mo.md(
        f"**{pair.value}** · `{layer.value}` · {span} · **{nobs:,}** obs · "
        f"{filled}/{NCELLS} cells · vmax≈{vmax_srv:.2f} · server {ms:.0f} ms{_warn}"
    )
    return


@app.cell
def _(CONN, NODE, np):
    tris = np.concatenate([CONN[:, [0, 1, 2]], CONN[:, [0, 2, 3]]], axis=0)
    face_of_tri = np.concatenate([np.arange(CONN.shape[0])] * 2)
    NX, NY, NZ = NODE[:, 0], NODE[:, 1], NODE[:, 2]
    return NX, NY, NZ, face_of_tri, tris


@app.cell
def _(face_of_tri, matplotlib, np):
    def facecolors(val, cmap):
        fin = np.isfinite(val)
        vmax = float(np.nanpercentile(val[fin], 98)) if fin.any() else 1.0
        norm = matplotlib.colors.Normalize(0, vmax if vmax > 0 else 1.0)
        rgba = matplotlib.colormaps[cmap](norm(val))
        rgba[~fin] = (0.92, 0.92, 0.92, 1.0)
        cols = [
            f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})" for r, g, b, _ in rgba
        ]
        return [cols[f] for f in face_of_tri], vmax

    return (facecolors,)


@app.cell
def _(NX, NY, NZ, go, tris):
    # Build the 3D widget ONCE (depends only on the static mesh, so it never
    # re-mounts). Brush updates mutate facecolor in place on this same widget,
    # so the user's camera/orbit survives — a fresh go.Figure would reset it.
    fig3d = go.FigureWidget(
        go.Mesh3d(
            x=NX,
            y=NY,
            z=NZ,
            i=tris[:, 0],
            j=tris[:, 1],
            k=tris[:, 2],
            facecolor=["rgb(235,235,235)"] * tris.shape[0],
            flatshading=True,
            hoverinfo="skip",
        )
    )
    fig3d.update_layout(
        height=440,
        margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            aspectmode="data",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            camera=dict(eye=dict(x=1.1, y=1.1, z=0.9)),
        ),
    )
    fig3d
    return (fig3d,)


@app.cell
def _(facecolors, fig3d, layer, nobs, pair, span, val):
    # in-place recolor of the persistent widget (camera untouched)
    _cmap = "viridis" if layer.value == "count" else "YlGn"
    _tcol, _ = facecolors(val, _cmap)
    with fig3d.batch_update():
        fig3d.data[0].facecolor = _tcol
        fig3d.layout.title = (
            f"3D — {pair.value} · {layer.value} · {span} · {nobs:,} obs"
        )
    return


@app.cell
def _(NX, NY, NZ, facecolors, go, layer, mo, np, pair, proj, span, tris, val):
    _theta = np.arccos(np.clip(NZ, -1, 1))
    _phi = np.arctan2(NY, NX)
    _rho = _theta / (np.pi / 2) if proj.value.startswith("flat") else np.sin(_theta)
    _X = _rho * np.sin(_phi)
    _Y = _rho * np.cos(_phi)
    _cmap = "viridis" if layer.value == "count" else "YlGn"
    _tcol, _vmax = facecolors(val, _cmap)
    fig2d = go.Figure(
        go.Mesh3d(
            x=_X,
            y=_Y,
            z=np.zeros_like(_X),
            i=tris[:, 0],
            j=tris[:, 1],
            k=tris[:, 2],
            facecolor=_tcol,
            flatshading=True,
            hoverinfo="skip",
        )
    )
    fig2d.update_layout(
        height=440,
        margin=dict(l=0, r=0, t=30, b=0),
        uirevision="keep",  # preserve pan/zoom across brush updates
        title=f"2D {proj.value} — {pair.value} · {layer.value} (vmax≈{_vmax:.2f})",
        scene=dict(
            aspectmode="data",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            camera=dict(
                up=dict(x=0, y=1, z=0),
                eye=dict(x=0, y=0, z=2.4),
                projection=dict(type="orthographic"),
            ),
        ),
    )
    mo.ui.plotly(fig2d)
    return


if __name__ == "__main__":
    app.run()
