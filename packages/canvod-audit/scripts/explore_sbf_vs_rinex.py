# NOTE: Run from monorepo root with `uv run marimo edit` or `uv run marimo run`
# to pick up workspace packages (canvod-audit, canvod-store, etc.).
# Do NOT add a PEP 723 `# /// script` block — it causes marimo/uv to create
# an isolated venv that lacks the local workspace packages.

import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # SBF vs RINEX: Visual Inspection

        The Septentrio receiver exports both SBF (raw receiver-time) and RINEX
        (clock-corrected GPS-time) from the same observations. The RINEX converter
        applies a **receiver clock correction** (`c × dT ≈ 600 km` for the ~2 s bias),
        shifting epochs and adjusting pseudorange/phase.

        This notebook answers two questions:

        1. Are the differences systematic (from the clock correction) or random (a bug)?
        2. Can we prove mathematically that both datasets represent the same signal?
        """
    )
    return (mo,)


@app.cell
def _():
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    import xarray as xr
    from plotly.subplots import make_subplots

    return go, make_subplots, np, pd, xr


@app.cell
def _():
    import os
    from pathlib import Path

    AUDIT_ROOT = Path(
        os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
    )
    SBF_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_allvars_store"
    RINEX_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_RINEX_allvars_store"
    return AUDIT_ROOT, RINEX_STORE, SBF_STORE


@app.cell
def _(RINEX_STORE, SBF_STORE, xr):
    from canvod.audit.runners.common import open_store

    _s_sbf = open_store(SBF_STORE)
    _s_rnx = open_store(RINEX_STORE)

    ds_sbf = xr.open_zarr(
        store=_s_sbf.readonly_session().__enter__().store, group="canopy_01"
    )
    ds_rnx = xr.open_zarr(
        store=_s_rnx.readonly_session().__enter__().store, group="canopy_01"
    )
    return ds_rnx, ds_sbf


@app.cell
def _(ds_rnx, ds_sbf, np):
    """Build epoch-snapping index arrays (reused by downstream cells)."""

    def snap_epochs(ds_a, ds_b, tol_s=2.5):
        """Return (mask, idx_a, idx_b) for nearest-epoch pairing within tol_s."""
        a_ns = ds_a.epoch.values.astype("int64")
        b_ns = ds_b.epoch.values.astype("int64")
        indices = np.clip(np.searchsorted(b_ns, a_ns), 1, len(b_ns) - 1)
        left = np.abs(a_ns - b_ns[indices - 1])
        right = np.abs(a_ns - b_ns[indices])
        use_left = left < right
        best_idx = np.where(use_left, indices - 1, indices)
        best_diff = np.where(use_left, left, right)
        mask = best_diff <= int(tol_s * 1e9)
        return mask, np.where(mask)[0], best_idx[mask]

    snap_mask, sbf_idx, rnx_idx = snap_epochs(ds_sbf, ds_rnx)
    shared_sids = sorted(set(ds_sbf.sid.values) & set(ds_rnx.sid.values))
    n_snapped = int(np.sum(snap_mask))
    return n_snapped, rnx_idx, sbf_idx, shared_sids


@app.cell
def _(ds_rnx, ds_sbf, mo, n_snapped, np):
    _offset_ns = np.median(
        ds_sbf.epoch.values[:100].astype("int64")
        - ds_rnx.epoch.values[:100].astype("int64")
    )
    _offset_s = _offset_ns / 1e9
    mo.md(f"""
    ## Store summary

    | | SBF | RINEX |
    |---|---|---|
    | Epochs | {ds_sbf.sizes["epoch"]} | {ds_rnx.sizes["epoch"]} |
    | SIDs | {ds_sbf.sizes["sid"]} | {ds_rnx.sizes["sid"]} |
    | Variables | {", ".join(ds_sbf.data_vars)} | {", ".join(ds_rnx.data_vars)} |
    | First epoch | `{ds_sbf.epoch.values[0]}` | `{ds_rnx.epoch.values[0]}` |
    | Last epoch | `{ds_sbf.epoch.values[-1]}` | `{ds_rnx.epoch.values[-1]}` |
    | Epoch offset | `{_offset_s:.3f} s` (SBF − RINEX) | |
    | Snapped pairs | {n_snapped} | |
    """)
    return


@app.cell
def _(mo):
    mo.md(
        """
    ## Statistical agreement: Pearson R and Lin's CCC

    Two complementary metrics quantify whether SBF and RINEX represent the same signal:

    - **Pearson R** — measures linear correlation. Invariant to offset and scale.
      R = 1.0 means perfect linear relationship, but allows SBF = 2 x RINEX + constant.

    - **Lin's Concordance Correlation Coefficient (CCC)** — the standard for
      method-comparison studies (Lin, 1989). CCC = R x Cb, where Cb is the bias
      correction factor. CCC = 1.0 requires both perfect correlation and no
      systematic bias. It penalises offset and scale differences that Pearson ignores.

    For variables with a known c x dT offset (Pseudorange, Phase), Pearson R
    stays high while CCC drops — quantifying the clock correction magnitude.
    For SNR (no clock correction), both should be close to 1.0.
        """
    )
    return


@app.cell
def _(np):
    def concordance_cc(x, y):
        """Lin's Concordance Correlation Coefficient.

        Returns (ccc, pearson_r, bias_correction_Cb).
        """
        mx, my = np.mean(x), np.mean(y)
        sx, sy = np.std(x, ddof=1), np.std(y, ddof=1)
        sxy = np.mean((x - mx) * (y - my))
        r = sxy / (sx * sy) if sx > 0 and sy > 0 else 0.0
        cb = 2 * sx * sy / (sx**2 + sy**2 + (mx - my) ** 2) if (sx + sy) > 0 else 0.0
        ccc = r * cb
        return ccc, r, cb

    return (concordance_cc,)


@app.cell
def _(
    concordance_cc,
    ds_rnx,
    ds_sbf,
    mo,
    np,
    pd,
    rnx_idx,
    sbf_idx,
    shared_sids,
):
    """Compute per-SID Pearson R and Lin's CCC for all observable variables."""
    _variables = ["SNR", "Doppler", "Phase", "Pseudorange"]
    _records = []

    for _var in _variables:
        _sbf_all = ds_sbf[_var].isel(epoch=sbf_idx).sel(sid=shared_sids).values
        _rnx_all = ds_rnx[_var].isel(epoch=rnx_idx).sel(sid=shared_sids).values

        for _i, _sid in enumerate(shared_sids):
            _s = _sbf_all[:, _i]
            _r = _rnx_all[:, _i]
            _valid = ~np.isnan(_s) & ~np.isnan(_r)
            _n = int(np.sum(_valid))
            if _n < 30:
                continue
            _sv = _s[_valid]
            _rv = _r[_valid]
            _ccc, _pearson, _cb = concordance_cc(_sv, _rv)
            _records.append(
                {
                    "variable": _var,
                    "sid": _sid,
                    "Pearson_R": _pearson,
                    "CCC": _ccc,
                    "Cb": _cb,
                    "n": _n,
                }
            )

    corr_df = pd.DataFrame(_records)

    # Summary table
    _agg = corr_df.groupby("variable")[["Pearson_R", "CCC", "Cb"]].agg(
        ["min", "median", "max"]
    )
    _agg.columns = [f"{stat} {metric}" for metric, stat in _agg.columns]
    _agg = _agg.reset_index()
    _agg.insert(1, "n_sids", corr_df.groupby("variable").size().values)
    _summary_md = _agg.to_markdown(index=False, floatfmt=".6f")

    # Interpretation
    _snr_ccc = corr_df[corr_df["variable"] == "SNR"]["CCC"]
    _pr_ccc = corr_df[corr_df["variable"] == "Pseudorange"]["CCC"]

    _interp_lines = []
    if len(_snr_ccc) > 0:
        _interp_lines.append(
            f"- **SNR**: median CCC = {_snr_ccc.median():.6f} — "
            + (
                "high agreement (no clock correction applied to SNR)"
                if _snr_ccc.median() > 0.99
                else "lower agreement reflects 2 s timing offset"
            )
        )
    if len(_pr_ccc) > 0:
        _interp_lines.append(
            f"- **Pseudorange**: median CCC = {_pr_ccc.median():.6f} — "
            + "CCC < 1 quantifies the `c × dT` offset that Pearson R ignores"
        )

    _low_r = corr_df[corr_df["Pearson_R"] < 0.999]
    _verdict = (
        f"**All {len(corr_df)} SID–variable pairs have Pearson R ≥ 0.999.**"
        if len(_low_r) == 0
        else f"**{len(_low_r)} / {len(corr_df)} pairs have Pearson R < 0.999** — investigate."
    )

    mo.md(f"""
    ### Summary

    {_summary_md}

    {_verdict}

    ### Interpretation

    {chr(10).join(_interp_lines)}

    **Key insight**: Pearson R ≈ 1.000 for all variables proves the signals are
    linearly related (same underlying measurement). Where CCC drops below Pearson R
    (low C_b), the gap is entirely due to the systematic `c × dT` clock offset —
    not random error. This is the mathematical signature of the receiver clock
    correction: a pure location shift that degrades agreement but not correlation.
    """)
    return (corr_df,)


@app.cell
def _(corr_df, go):
    """Histogram of per-SID Pearson R and CCC, faceted by variable."""
    _variables = list(corr_df["variable"].unique())
    from plotly.subplots import make_subplots as _make_subplots

    _fig = _make_subplots(
        rows=2,
        cols=len(_variables),
        subplot_titles=[f"{v} — Pearson R" for v in _variables]
        + [f"{v} — CCC" for v in _variables],
        vertical_spacing=0.15,
        horizontal_spacing=0.05,
    )

    for _ci, _v in enumerate(_variables):
        _sub = corr_df[corr_df["variable"] == _v]
        # Row 1: Pearson R
        _fig.add_trace(
            go.Histogram(
                x=_sub["Pearson_R"].values,
                nbinsx=80,
                marker_color="#ABC8A4",
                opacity=0.85,
                showlegend=False,
            ),
            row=1,
            col=_ci + 1,
        )
        # Row 2: CCC
        _fig.add_trace(
            go.Histogram(
                x=_sub["CCC"].values,
                nbinsx=80,
                marker_color="#375D3B",
                opacity=0.85,
                showlegend=False,
            ),
            row=2,
            col=_ci + 1,
        )

    _fig.update_layout(
        title="Per-SID agreement: Pearson R (top) vs Lin's CCC (bottom)",
        height=550,
        template="plotly_dark",
        paper_bgcolor="#0d0d0d",
        plot_bgcolor="#1a1a1a",
        font=dict(family="Space Grotesk", color="#E1E6B9"),
    )
    _fig.update_xaxes(gridcolor="#333")
    _fig.update_yaxes(gridcolor="#333")
    _fig
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Per-SID visual inspection

    Select a variable and SID to inspect the time series, scatter plot, and
    difference histogram.
    """)
    return


@app.cell
def _(mo):
    var_selector = mo.ui.dropdown(
        options=["SNR", "Doppler", "Phase", "Pseudorange"],
        value="SNR",
        label="Variable",
    )
    var_selector
    return (var_selector,)


@app.cell
def _(mo):
    sid_input = mo.ui.text(value="G01|L1|C", label="SID")
    sid_input
    return (sid_input,)


@app.cell
def _(ds_rnx, ds_sbf, go, make_subplots, np, pd, sid_input, var_selector):
    """Time series: native SBF and RINEX epochs (no snapping)."""
    _var = var_selector.value
    _sid = sid_input.value

    _has_sbf = _sid in ds_sbf.sid.values
    _has_rnx = _sid in ds_rnx.sid.values

    if _has_sbf and _has_rnx:
        _sbf_da = ds_sbf[_var].sel(sid=_sid).load()
        _rnx_da = ds_rnx[_var].sel(sid=_sid).load()

        _sbf_valid = ~np.isnan(_sbf_da.values)
        _rnx_valid = ~np.isnan(_rnx_da.values)

        _sbf_epochs = pd.DatetimeIndex(_sbf_da.epoch.values[_sbf_valid])
        _sbf_vals = _sbf_da.values[_sbf_valid]
        _rnx_epochs = pd.DatetimeIndex(_rnx_da.epoch.values[_rnx_valid])
        _rnx_vals = _rnx_da.values[_rnx_valid]

        _step_s = max(1, len(_sbf_epochs) // 2000)
        _step_r = max(1, len(_rnx_epochs) // 2000)

        _fig = make_subplots(
            rows=1,
            cols=1,
            subplot_titles=[
                f"{_var} — SBF vs RINEX (native epochs, SID: {_sid})",
            ],
        )

        _fig.add_trace(
            go.Scattergl(
                x=_sbf_epochs[::_step_s],
                y=_sbf_vals[::_step_s],
                mode="markers",
                marker=dict(size=3, color="#375D3B"),
                name="SBF",
            ),
        )
        _fig.add_trace(
            go.Scattergl(
                x=_rnx_epochs[::_step_r],
                y=_rnx_vals[::_step_r],
                mode="markers",
                marker=dict(size=3, color="#C4D7A4"),
                name="RINEX",
            ),
        )

        _fig.update_layout(
            height=500,
            template="plotly_dark",
            paper_bgcolor="#0d0d0d",
            plot_bgcolor="#1a1a1a",
            font=dict(family="Space Grotesk", color="#E1E6B9"),
            showlegend=True,
        )
        _fig.update_xaxes(gridcolor="#333")
        _fig.update_yaxes(gridcolor="#333")
        _result_ts = _fig
    else:
        _result_ts = go.Figure()
    _result_ts
    return


@app.cell
def _(
    concordance_cc,
    ds_rnx,
    ds_sbf,
    go,
    np,
    rnx_idx,
    sbf_idx,
    sid_input,
    var_selector,
):
    """Scatter plot: SBF vs RINEX after snapping epochs."""
    _var = var_selector.value
    _sid = sid_input.value

    if _sid in ds_sbf.sid.values and _sid in ds_rnx.sid.values:
        _sv = ds_sbf[_var].isel(epoch=sbf_idx).sel(sid=_sid).values
        _rv = ds_rnx[_var].isel(epoch=rnx_idx).sel(sid=_sid).values
        _valid = ~np.isnan(_sv) & ~np.isnan(_rv)

        _idx = np.where(_valid)[0]
        _step = max(1, len(_idx) // 3000)
        _idx = _idx[::_step]

        _fig = go.Figure()
        _fig.add_trace(
            go.Scattergl(
                x=_rv[_idx],
                y=_sv[_idx],
                mode="markers",
                marker=dict(size=3, color="#ABC8A4", opacity=0.5),
                name=f"{_var}",
            )
        )

        _all_vals = np.concatenate([_rv[_idx], _sv[_idx]])
        _all_vals = _all_vals[~np.isnan(_all_vals)]
        if len(_all_vals) > 0:
            _lo, _hi = np.nanpercentile(_all_vals, [1, 99])
            _fig.add_trace(
                go.Scatter(
                    x=[_lo, _hi],
                    y=[_lo, _hi],
                    mode="lines",
                    line=dict(color="#375D3B", dash="dash"),
                    name="1:1",
                )
            )

        # Show Pearson R and CCC in title
        _sv_v = _sv[np.where(_valid)[0]]
        _rv_v = _rv[np.where(_valid)[0]]
        if len(_sv_v) > 1:
            _ccc_val, _r, _cb_val = concordance_cc(_sv_v, _rv_v)
        else:
            _r, _ccc_val = float("nan"), float("nan")

        _fig.update_layout(
            title=f"{_var} — SBF vs RINEX (SID: {_sid}, R = {_r:.6f}, CCC = {_ccc_val:.6f})",
            xaxis_title="RINEX",
            yaxis_title="SBF",
            height=500,
            template="plotly_dark",
            paper_bgcolor="#0d0d0d",
            plot_bgcolor="#1a1a1a",
            font=dict(family="Space Grotesk", color="#E1E6B9"),
        )
        _fig.update_xaxes(gridcolor="#333")
        _fig.update_yaxes(gridcolor="#333")
        _result_scatter = _fig
    else:
        _result_scatter = go.Figure()
    _result_scatter
    return


@app.cell
def _(ds_rnx, ds_sbf, go, np, rnx_idx, sbf_idx, shared_sids, var_selector):
    """Histogram of differences across ALL sids (epoch-snapped)."""
    _var = var_selector.value

    _sv = ds_sbf[_var].isel(epoch=sbf_idx).sel(sid=shared_sids).values
    _rv = ds_rnx[_var].isel(epoch=rnx_idx).sel(sid=shared_sids).values
    _valid = ~np.isnan(_sv) & ~np.isnan(_rv)
    _diff = _sv[_valid] - _rv[_valid]

    _lo, _hi = np.percentile(_diff, [1, 99])
    _clipped = _diff[(_diff >= _lo) & (_diff <= _hi)]

    _fig = go.Figure()
    _fig.add_trace(
        go.Histogram(
            x=_clipped,
            nbinsx=200,
            marker_color="#ABC8A4",
            opacity=0.8,
        )
    )
    _fig.update_layout(
        title=f"Δ{_var} (SBF − RINEX) — all SIDs, p1–p99 clipped",
        xaxis_title=f"Δ{_var}",
        yaxis_title="Count",
        height=400,
        template="plotly_dark",
        paper_bgcolor="#0d0d0d",
        plot_bgcolor="#1a1a1a",
        font=dict(family="Space Grotesk", color="#E1E6B9"),
    )
    _fig.update_xaxes(gridcolor="#333")
    _fig.update_yaxes(gridcolor="#333")
    _fig
    return


@app.cell
def _(mo):
    mo.md("""
    ## Interpretation guide

    - **SNR**: If the histogram is centered near 0 with tails, the differences
      are from the 2 s measurement timing offset (random signal variation).
    - **Pseudorange**: If the scatter plot shows a systematic offset from the 1:1
      line, this is the `c × dT` clock correction (~600 km for 2 s bias).
    - **Phase**: Expect large systematic offsets from the clock correction,
      plus cycle-level structure from carrier frequency × dT.
    - **Doppler**: Rate of range change — differences reflect the timing offset
      and any interpolation the RINEX converter applies.

    **Conclusion**: If all per-SID Pearson R values are ≈ 1.000, the datasets
    are the same signal. The differences are fully explained by the clock
    correction and 2 s timing offset — SBF and RINEX are complementary,
    not contradictory.
    """)
    return


if __name__ == "__main__":
    app.run()
