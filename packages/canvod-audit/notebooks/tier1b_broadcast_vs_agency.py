import marimo

__generated_with = "0.21.1"
app = marimo.App(
    width="medium",
    app_title="Tier 1b — Broadcast vs Agency Ephemeris",
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

        elements = [header]
        if align_md:
            elements.append(align_md)
        elements.append(table)
        if r.failures:
            lines = ["**Failures:**"]
            for var, reason in r.failures.items():
                lines.append(f"- `{var}`: {reason}")
            elements.append(mo.callout(mo.md("\n".join(lines)), kind="warn"))
        return mo.vstack(elements, gap=1)

    return (render_result,)


@app.cell
def _(mo):
    mo.md(r"""
    # Tier 1b: Broadcast vs Agency Ephemeris

    **What this test checks:**  Both stores are built from the **same SBF input files**.
    The only difference is the ephemeris source used to compute satellite coordinates
    (phi / theta):

    | Source | Product | Latency | Orbit accuracy |
    |---|---|---|---|
    | **Broadcast** (A) | SBF SatVisibility records | Real-time | ~1–2 m |
    | **Agency final** (B) | COD SP3/CLK | 12–18 days | ~3 cm |

    **Why this matters:**  Broadcast ephemeris is needed for near-real-time
    operational processing where final products aren't yet available.
    This test quantifies the angular error introduced by using broadcast
    rather than final orbits — and whether those errors are large enough
    to place observations into *different* 2° hemigrid cells (which would
    affect VOD retrieval).

    **Expected outcome:**

    | Variable | Expected difference | Reason |
    |---|---|---|
    | SNR | identical (0 diff) | Ephemeris source does not affect raw observables |
    | phi | p99 ~0.01 rad (~0.6°), max ~6.28 rad (azimuth wrap) | ~1–2 m orbit error; 9 cells near 0°/360° boundary |
    | theta | p99 ~0.002 rad (~0.13°) | Same orbit error, smaller angular effect in elevation |

    The `FAILED` verdict from the tolerance check is **expected** — the tolerances
    are set tight (atol=0.01 rad) to make the differences visible.  The key question
    for scientific use is whether p99 angle differences (~0.01 rad ≈ 0.6°) exceed
    the 2° hemigrid cell resolution.  At p99, they do not.

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
    BROADCAST_STORE = (
        AUDIT_ROOT / "tier1_broadcast_vs_agency/Rosalia/canvodpy_SBF_broadcast_store"
    )
    AGENCY_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store"
    GROUPS = ["canopy_01", "reference_01_canopy_01"]
    return AGENCY_STORE, AUDIT_ROOT, BROADCAST_STORE, GROUPS


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
def _(
    AGENCY_STORE,
    BROADCAST_STORE,
    group_selector,
    is_script_mode,
    run_button,
):
    from canvod.audit.core import compare_datasets
    from canvod.audit.runners.common import load_group, open_store
    from canvod.audit.runners.ephemeris import DEFAULT_VARIABLES, EPHEMERIS_TOLERANCES
    from canvod.audit.tolerances import ToleranceTier

    result = None

    if is_script_mode or run_button.value:
        group = group_selector.value
        s_broad = open_store(BROADCAST_STORE)
        s_agency = open_store(AGENCY_STORE)
        ds_broad = load_group(s_broad, group)
        ds_agency = load_group(s_agency, group)
        result = compare_datasets(
            ds_broad,
            ds_agency,
            variables=DEFAULT_VARIABLES,
            tier=ToleranceTier.SCIENTIFIC,
            tolerance_overrides=EPHEMERIS_TOLERANCES,
            label=f"Broadcast vs Agency: {group}",
        )

    return (result,)


@app.cell
def _(mo, render_result, result):
    output = (
        mo.md("_Select a group and click **Run comparison** to start._")
        if result is None
        else render_result(result)
    )
    output
    return


if __name__ == "__main__":
    app.run()
