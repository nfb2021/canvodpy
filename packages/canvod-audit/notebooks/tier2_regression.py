import os

import marimo

__generated_with = "0.21.1"
app = marimo.App(
    width="medium",
    app_title="Tier 2 — Regression Testing",
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

    def render_audit_result(audit):
        """Render an AuditResult (multiple ComparisonResults) as a vstack."""
        if not audit.results:
            return mo.callout(
                mo.md("No comparisons were run."),
                kind="warn",
            )

        overall_kind = "success" if audit.passed else "danger"
        overall_text = "ALL PASSED ✓" if audit.passed else "SOME FAILED ✗"
        summary_header = mo.callout(
            mo.md(
                f"### {overall_text}  "
                f"({audit.n_passed}/{audit.n_total} comparisons passed)"
            ),
            kind=overall_kind,
        )

        comparison_cards = []
        for name, r in audit.results.items():
            kind = "success" if r.passed else "danger"
            header = mo.callout(
                mo.md(
                    f"**{'PASSED ✓' if r.passed else 'FAILED ✗'}** `{name}` — {r.label}"
                ),
                kind=kind,
            )

            align_md = mo.md("")
            if r.alignment:
                a = r.alignment
                align_md = mo.md(
                    f"Domain: {a.n_shared_epochs:,} epochs × {a.n_shared_sids} SIDs"
                )

            rows = []
            for vname, vs in r.variable_stats.items():
                failed = vname in r.failures
                rows.append(
                    {
                        "Variable": vname,
                        "Match": "✓" if vs.exact_match else "✗",
                        "N compared": f"{vs.n_compared:,}",
                        "Max |Δ|": _fmt(vs.max_abs_diff),
                        "RMSE": _fmt(vs.rmse),
                        "NaN% A": f"{vs.pct_nan_a:.1%}",
                        "NaN% B": f"{vs.pct_nan_b:.1%}",
                        "Result": "FAIL ✗" if failed else "PASS ✓",
                    }
                )
            table = mo.ui.table(rows, selection=None)

            card_elements = [header, align_md, table]
            if r.failures:
                lines = ["**Failures:**"]
                for var, reason in r.failures.items():
                    lines.append(f"- `{var}`: {reason}")
                card_elements.append(mo.callout(mo.md("\n".join(lines)), kind="warn"))

            comparison_cards.append(mo.vstack(card_elements, gap=1))

        return mo.vstack([summary_header, *comparison_cards], gap=2)

    return (render_audit_result,)


@app.cell
def _(mo):
    mo.md(r"""
    # Tier 2: Regression Testing

    **What this test checks:**  Current store outputs are compared
    bit-identically against frozen **checkpoint files** (NetCDF snapshots
    of known-good outputs).  Any change in output after a code modification
    is immediately visible.

    **Why this matters:**  The GNSS-T pipeline involves many numerical steps
    — SP3 interpolation, coordinate transforms, NaN masking — where a
    seemingly innocuous refactor can silently shift values.  The regression
    tier is the safety net: *if it passes, the algorithm is unchanged*.

    **Workflow:**

    ```
    1. Freeze baseline  →  run_tier2_freeze.py   (once, before code changes)
    2. Make code changes
    3. Check regression →  this notebook          (after each change)
    ```

    **Checkpoints are stored per store under:**
    ```
    /Volumes/ExtremePro/canvod_audit_output/tier2_checkpoints/<store_name>/
    ```

    Each `*.nc` file is a frozen snapshot of one store group (e.g. `canopy_01_v0.3.0.nc`).
    The tolerance tier is **EXACT** — outputs must be bit-identical unless an
    intentional algorithm change was made and the checkpoints were re-frozen.

    > **Re-freezing after a deliberate change:**  Update the checkpoint by running
    > `run_tier2_freeze.py` again with a new version label.

    ---
    """)
    return


@app.cell
def _():
    from pathlib import Path

    AUDIT_ROOT = Path(
        os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
    )
    CHECKPOINT_DIR = AUDIT_ROOT / "tier2_checkpoints"

    STORES = {
        "tier0_rinex": AUDIT_ROOT
        / "tier0_rinex_vs_gnssvodpy"
        / "Rosalia"
        / "canvodpy_RINEX_store",
        "tier0_vod": AUDIT_ROOT
        / "tier0_rinex_vs_gnssvodpy"
        / "Rosalia"
        / "canvodpy_VOD_store",
        "tier1_sbf_agency": AUDIT_ROOT
        / "tier1_sbf_vs_rinex"
        / "Rosalia"
        / "canvodpy_SBF_store",
        "tier1_sbf_broadcast": AUDIT_ROOT
        / "tier1_broadcast_vs_agency"
        / "Rosalia"
        / "canvodpy_SBF_broadcast_store",
    }
    return AUDIT_ROOT, CHECKPOINT_DIR, STORES


@app.cell
def _(CHECKPOINT_DIR, STORES, mo):
    """Show available checkpoints and store status."""
    rows = []
    for _label, _store_path in STORES.items():
        _cp_dir = CHECKPOINT_DIR / _label
        _checkpoints = sorted(_cp_dir.glob("*.nc")) if _cp_dir.exists() else []
        _store_ok = "✓" if _store_path.exists() else "✗ missing"
        _cp_names = ", ".join(p.name for p in _checkpoints) if _checkpoints else "—"
        rows.append(
            {
                "Store": _label,
                "Store exists": _store_ok,
                "Checkpoints": f"{len(_checkpoints)} file(s)",
                "Files": _cp_names,
            }
        )

    status_table = mo.ui.table(rows, selection=None, label="Checkpoints & stores")
    status_table
    return (status_table,)


@app.cell
def _(STORES, mo):
    store_selector = mo.ui.multiselect(
        options=list(STORES.keys()),
        value=list(STORES.keys()),
        label="Stores to check",
    )
    store_selector
    return (store_selector,)


@app.cell
def _(mo):
    run_button = mo.ui.run_button(label="Run regression check")
    run_button
    return (run_button,)


@app.cell
def _(
    CHECKPOINT_DIR,
    STORES,
    is_script_mode,
    run_button,
    store_selector,
):
    from canvod.audit.runners.common import AuditResult
    from canvod.audit.runners.regression import audit_regression
    from canvod.audit.tolerances import ToleranceTier

    audit = None

    if is_script_mode or run_button.value:
        selected = store_selector.value if store_selector.value else list(STORES.keys())
        audit = AuditResult()

        for _label in selected:
            _store_path = STORES[_label]
            _cp_dir = CHECKPOINT_DIR / _label
            if not _cp_dir.exists() or not _store_path.exists():
                continue
            _r = audit_regression(
                store=str(_store_path),
                checkpoint_dir=str(_cp_dir),
                tier=ToleranceTier.EXACT,
            )
            for _k, _v in _r.results.items():
                audit.results[f"{_label}/{_k}"] = _v

    return (audit,)


@app.cell
def _(audit, mo, render_audit_result):
    output = (
        mo.md("_Select stores and click **Run regression check** to start._")
        if audit is None
        else render_audit_result(audit)
    )
    output
    return


if __name__ == "__main__":
    app.run()
