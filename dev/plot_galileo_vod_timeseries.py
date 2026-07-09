"""Visualize a precomputed Galileo VOD per-cell daily timeseries.

Pure visualization — loads the small NetCDF file produced by
`dev/compute_galileo_vod_timeseries.py` (which does the actual store read,
grid assignment, and per-cell daily aggregation). This notebook does none of
that heavy lifting, so it stays fast and interactive even though the
underlying store may be hundreds of days of (epoch, sid) data.

    # 1. Compute once (slow, run from the machine with the store):
    uv run python dev/compute_galileo_vod_timeseries.py /path/to/vod_store \\
        --group VOD_lower_antenna --resolution 2.0 --stat median

    # 2. Visualize (fast, repeatable):
    uv run marimo edit dev/plot_galileo_vod_timeseries.py
"""

import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium", app_title="Galileo VOD Timeseries")


@app.cell
def _():
    import marimo as mo

    mo.md(
        r"""
    # Galileo VOD timeseries — 2° equal-area grid, daily median

    Loads the per-cell (cell × day) dataset produced by
    `dev/compute_galileo_vod_timeseries.py` and plots it. No store access,
    grid assignment, or aggregation happens here — just visualization.
    """
    )
    return (mo,)


@app.cell
def _(mo):
    path_input = mo.ui.text(
        value="dev/output/VOD_lower_antenna_2deg_median.nc",
        label="Precomputed dataset path (.nc)",
        full_width=True,
    )
    path_input
    return (path_input,)


@app.cell
def _(mo, path_input):
    from pathlib import Path

    import xarray as xr

    _path = Path(path_input.value)
    mo.stop(
        not _path.exists(),
        mo.md(
            f"_File not found: `{_path}`. Run `compute_galileo_vod_timeseries.py` "
            "first, or point this at its output._"
        ),
    )

    percell_ds = xr.open_dataset(_path)

    mo.md(
        f"Loaded **{percell_ds.sizes['cell']} cells × {percell_ds.sizes['time']} days**\n\n"
        f"Source group: `{percell_ds.attrs.get('source_group', '?')}` · "
        f"stat: `{percell_ds.attrs.get('stat', '?')}` · "
        f"resolution: `{percell_ds.attrs.get('grid_resolution_deg', '?')}`° · "
        f"Galileo SIDs: `{percell_ds.attrs.get('galileo_sid_count', '?')}`"
    )
    return Path, percell_ds


@app.cell
def _(mo):
    mo.md("## Plots").right()
    return


@app.cell
def _(mo, percell_ds):
    import plotly.graph_objects as go

    _stat = percell_ds.attrs.get("stat", "median")

    _heatmap = go.Figure(
        data=go.Heatmap(
            z=percell_ds["cell_timeseries"].values,
            x=percell_ds["time"].values,
            y=percell_ds["cell"].values,
            colorscale="Viridis",
            colorbar=dict(title="VOD"),
        )
    )
    _heatmap.update_layout(
        title=f"Galileo VOD — daily {_stat} per grid cell",
        xaxis_title="Day",
        yaxis_title="Grid cell",
        height=500,
    )
    mo.ui.plotly(_heatmap)
    return (go,)


@app.cell
def _(mo, percell_ds):
    _cell_options = [int(c) for c in percell_ds["cell"].values]
    cell_selector = mo.ui.dropdown(
        options=[str(c) for c in _cell_options],
        value=str(_cell_options[0]),
        label="Grid cell",
    )
    cell_selector
    return (cell_selector,)


@app.cell
def _(cell_selector, go, mo, percell_ds):
    _stat = percell_ds.attrs.get("stat", "median")
    _cell_id = int(cell_selector.value)
    _series = percell_ds["cell_timeseries"].sel(cell=_cell_id)

    _line = go.Figure(
        data=go.Scatter(
            x=_series["time"].values, y=_series.values, mode="lines+markers"
        )
    )
    _line.update_layout(
        title=f"Cell {_cell_id} — daily {_stat} VOD (Galileo)",
        xaxis_title="Day",
        yaxis_title="VOD",
        height=350,
    )
    mo.ui.plotly(_line)
    return


@app.cell
def _(go, mo, percell_ds):
    import numpy as np

    # Unweighted daily median-of-medians across all Galileo-observed cells —
    # a single summary line, distinct from compute_global_average()'s
    # observation-count-weighted MEAN.
    _stat = percell_ds.attrs.get("stat", "median")
    _global_daily = np.nanmedian(percell_ds["cell_timeseries"].values, axis=0)

    _global_line = go.Figure(
        data=go.Scatter(
            x=percell_ds["time"].values, y=_global_daily, mode="lines+markers"
        )
    )
    _global_line.update_layout(
        title=f"All Galileo cells — daily {_stat}-of-{_stat} VOD",
        xaxis_title="Day",
        yaxis_title="VOD",
        height=350,
    )
    mo.ui.plotly(_global_line)
    return


if __name__ == "__main__":
    app.run()
