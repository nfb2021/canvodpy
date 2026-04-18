import marimo

__generated_with = "0.21.1"
app = marimo.App(
    width="medium",
    app_title="Tier 1a — SBF vs RINEX",
    css_file="canvod_nordic.css",
)


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    is_script_mode = mo.app_meta().mode == "script"
    return (is_script_mode,)


@app.cell
def _(mo):
    import math

    def _fmt(x):
        if x is None or (isinstance(x, float) and not math.isfinite(x)):
            return "—"
        if x == 0.0:
            return "0"
        return f"{x:.4g}"

    def render_result(r):
        """Render a ComparisonResult as a marimo vstack."""
        kind = "success" if r.passed else "danger"
        header = mo.callout(
            mo.md(f"### {'PASSED ✓' if r.passed else 'FAILED ✗'} — {r.label}"),
            kind=kind,
        )

        align_md = ""
        if r.alignment:
            a = r.alignment
            dropped_e = a.n_dropped_epochs_a + a.n_dropped_epochs_b
            dropped_s = a.n_dropped_sids_a + a.n_dropped_sids_b
            drop_note = (
                f" (dropped {dropped_e} epochs, {dropped_s} SIDs)"
                if (dropped_e or dropped_s)
                else ""
            )
            align_md = mo.md(
                f"**Domain:** {a.n_shared_epochs:,} epochs × {a.n_shared_sids} SIDs{drop_note}"
            )

        rows = []
        for name, vs in r.variable_stats.items():
            failed = name in r.failures
            rows.append(
                {
                    "Variable": name,
                    "Match": "✓" if vs.exact_match else "✗",
                    "N compared": f"{vs.n_compared:,}",
                    "Max |Δ|": _fmt(vs.max_abs_diff),
                    "RMSE": _fmt(vs.rmse),
                    "Bias": _fmt(vs.bias),
                    "p50": _fmt(vs.p50),
                    "p99": _fmt(vs.p99),
                    "NaN% A": f"{vs.pct_nan_a:.1%}",
                    "NaN% B": f"{vs.pct_nan_b:.1%}",
                    "Result": "FAIL ✗" if failed else "PASS ✓",
                }
            )
        table = mo.ui.table(rows, selection=None)

        failure_note = mo.md("")
        if r.failures:
            lines = ["**Failures:**"]
            for var, reason in r.failures.items():
                lines.append(f"- `{var}`: {reason}")
            failure_note = mo.callout(mo.md("\n".join(lines)), kind="warn")

        elements = [header]
        if align_md:
            elements.append(align_md)
        elements.append(table)
        if r.failures:
            elements.append(failure_note)
        return mo.vstack(elements, gap=1)

    return (render_result,)


@app.cell
def _(mo):
    mo.md(r"""
    # Tier 1a: SBF vs RINEX — Internal Consistency

    **What this test checks:**  Both SBF and RINEX files are produced by the same
    Septentrio receiver during the same observation session and then processed
    independently by canvodpy. If the pipeline is internally consistent, both
    paths should yield the same SNR values (within quantisation) and
    bit-identical satellite angles (same SP3 augmentation, same geometry).

    **Why this matters:**  The SBF path is used for operational ingestion;
    the RINEX path is the community-standard format used for archival and
    comparison against third-party tools.  Any systematic divergence here
    would propagate into VOD and corrupt science outputs.

    **Expected outcome per variable:**

    | Variable | Expected difference | Reason |
    |---|---|---|
    | SNR | ≤ 0.25 dB | SBF quantises to 0.25 dB steps; RINEX precision ~0.001 dB |
    | phi / theta | sub-arcsecond FP noise only | Both stores use identical COD final SP3/CLK and the same CubicHermiteSpline |
    | Doppler / Phase / Pseudorange | non-trivial | Different internal formats; not used for VOD |
    | NaN rates | may differ ≤ 5% | SBF may track fewer codes than RINEX header declares |

    **Epoch alignment:** SBF preserves raw receiver clock timestamps (:02, :07, …);
    Septentrio's RINEX converter **re-stamps** each observation to the nearest nominal
    5-s grid epoch (:00, :05, …), introducing a constant ~2 s shift.  The underlying
    measurements are 1-to-1 identical — only the reported timestamps differ.

    Epochs are matched **by position** (SBF[N] ↔ RINEX[N]), not by timestamp proximity.
    Both datasets are trimmed to the shorter length (boundary epochs only) before comparison.

    ---
    """)
    return


@app.cell
def _():
    import os
    from pathlib import Path

    AUDIT_ROOT = Path(
        os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
    )
    SBF_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store"
    RINEX_STORE = AUDIT_ROOT / "tier0_rinex_vs_gnssvodpy/Rosalia/canvodpy_RINEX_store"
    GROUPS = ["canopy_01", "reference_01_canopy_01"]
    return AUDIT_ROOT, GROUPS, RINEX_STORE, SBF_STORE


@app.cell
def _(GROUPS, mo):
    group_selector = mo.ui.dropdown(
        options=GROUPS,
        value=GROUPS[0],
        label="Receiver group",
    )
    group_selector
    return (group_selector,)


@app.cell
def _(mo):
    run_button = mo.ui.run_button(label="Run comparison")
    run_button
    return (run_button,)


@app.cell
def _(RINEX_STORE, SBF_STORE, group_selector, is_script_mode, run_button):
    import numpy as np

    from canvod.audit.core import compare_datasets
    from canvod.audit.runners.common import load_group, open_store
    from canvod.audit.runners.sbf_vs_rinex import SBF_RINEX_TOLERANCES
    from canvod.audit.tolerances import ToleranceTier

    def _reindex_sbf_to_rinex(ds_sbf, ds_rnx):
        """Positional reindex: SBF[N] ↔ RINEX[N], trim to min length."""
        n_sbf = len(ds_sbf.epoch)
        n_rnx = len(ds_rnx.epoch)
        n = min(n_sbf, n_rnx)
        ds_sbf_trimmed = ds_sbf.isel(epoch=slice(None, n))
        ds_rnx_trimmed = ds_rnx.isel(epoch=slice(None, n))
        sbf_ns = ds_sbf_trimmed.epoch.values.astype("int64")
        rnx_ns = ds_rnx_trimmed.epoch.values.astype("int64")
        offsets_s = (rnx_ns - sbf_ns) / 1e9
        ds_sbf_reindexed = ds_sbf_trimmed.assign_coords(
            epoch=ds_rnx_trimmed.epoch.values
        )
        stats = {
            "n_sbf": n_sbf,
            "n_rnx": n_rnx,
            "n_used": n,
            "offset_mean_s": float(np.mean(offsets_s)),
            "offset_std_s": float(np.std(offsets_s)),
            "offset_min_s": float(np.min(offsets_s)),
            "offset_max_s": float(np.max(offsets_s)),
        }
        return ds_sbf_reindexed, ds_rnx_trimmed, stats

    result = None
    reindex_stats = None

    if is_script_mode or run_button.value:
        group = group_selector.value
        s_sbf = open_store(SBF_STORE)
        s_rnx = open_store(RINEX_STORE)
        ds_sbf = load_group(s_sbf, group)
        ds_rnx = load_group(s_rnx, group)
        ds_sbf_reindexed, ds_rnx_trimmed, reindex_stats = _reindex_sbf_to_rinex(
            ds_sbf, ds_rnx
        )
        result = compare_datasets(
            ds_sbf_reindexed,
            ds_rnx_trimmed,
            tier=ToleranceTier.SCIENTIFIC,
            tolerance_overrides=SBF_RINEX_TOLERANCES,
            label=f"SBF vs RINEX: {group}",
        )

    return result, reindex_stats


@app.cell
def _(mo, render_result, result, reindex_stats):
    def _render():
        ri = reindex_stats
        reindex_md = (
            mo.md(
                f"**Positional reindex:** using {ri['n_used']:,}/{ri['n_sbf']:,} SBF and "
                f"{ri['n_used']:,}/{ri['n_rnx']:,} RINEX epochs  |  "
                f"Epoch offset (RINEX − SBF): "
                f"mean {ri['offset_mean_s']:.3f} ± {ri['offset_std_s']:.3f} s "
                f"[{ri['offset_min_s']:.3f}, {ri['offset_max_s']:.3f}] s"
            )
            if reindex_stats
            else mo.md("")
        )
        return mo.vstack([reindex_md, render_result(result)], gap=1)

    output = (
        mo.md("_Select a group and click **Run comparison** to start._")
        if result is None
        else _render()
    )
    output
    return


if __name__ == "__main__":
    app.run()
