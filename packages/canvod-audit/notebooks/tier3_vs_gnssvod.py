import os

import marimo

__generated_with = "0.21.1"
app = marimo.App(
    width="medium",
    app_title="Tier 3 — canvodpy vs gnssvod",
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
        if not audit.results:
            return mo.callout(mo.md("No comparisons were run."), kind="warn")

        overall_kind = "success" if audit.passed else "danger"
        overall_text = "ALL PASSED ✓" if audit.passed else "SOME FAILED ✗"
        summary_header = mo.callout(
            mo.md(
                f"### {overall_text}  "
                f"({audit.n_passed}/{audit.n_total} comparisons passed)"
            ),
            kind=overall_kind,
        )

        cards = []
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
                dropped_e = a.n_dropped_epochs_a + a.n_dropped_epochs_b
                dropped_s = a.n_dropped_sids_a + a.n_dropped_sids_b
                note = (
                    f" (dropped {dropped_e} epochs, {dropped_s} SIDs)"
                    if (dropped_e or dropped_s)
                    else ""
                )
                align_md = mo.md(
                    f"Domain: {a.n_shared_epochs:,} epochs × {a.n_shared_sids} SIDs{note}"
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
                        "Bias": _fmt(vs.bias),
                        "p50": _fmt(vs.p50),
                        "p99": _fmt(vs.p99),
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
            cards.append(mo.vstack(card_elements, gap=1))

        return mo.vstack([summary_header, *cards], gap=2)

    return (render_audit_result,)


@app.cell
def _(mo):
    mo.md(r"""
    # Tier 3: canvodpy vs gnssvod (Humphrey et al.)

    **What this test checks:**  canvodpy's outputs are compared against
    **gnssvod** — the established community implementation of GNSS-T by
    Vincent Humphrey et al.  This is the ultimate external validity check:
    do our SNR values, satellite angles, and VOD estimates agree with an
    independent codebase?

    **Input:**  Both tools are fed the **same trimmed RINEX file** (GPS + Galileo,
    L1 + L2, one obs code per band, produced by `gfzrnx`).  Trimming eliminates
    any signal-selection ambiguity between canvodpy's SID-based system and
    gnssvod's PRN-based system.

    **Ephemeris:**  Both tools use the same **GFZ rapid** SP3/CLK files.
    canvodpy is configured with `agency="GFZ", product_type="rapid"` to
    match what gnssvod downloads automatically.

    **Why differences are expected (and not bugs):**

    | Source | canvodpy | gnssvod |
    |---|---|---|
    | SP3 interpolation | `scipy.CubicHermiteSpline` (cubic, uses velocities) | `numpy.polyfit` degree-16 on 4-hour windows (no velocities) |
    | SNR dtype | `float32` (~7 sig figs) | `float64` |
    | Below-horizon handling | mask to NaN, retain positions | drop rows with elevation ≤ −10° |

    The SP3 method difference produces **systematic** (not random) angular
    differences → different Elevation/Azimuth → different `cos(θ)` in VOD.
    All are reproducible and well-understood.

    **Sub-comparisons:**

    - **3A — SNR + Angles:** per signal code (L1|C, L2|W, L5|Q) vs gnssvod `preprocess()` output
    - **3B — VOD:** per band (L1, L2) vs gnssvod `calc_vod()` output

    > **Prerequisites:**  Steps 1–3 (RINEX trimming, gnssvod preprocessing, canvodpy
    > augmentation) must already have been run via `run_tier3_vs_gnssvod.py`.
    > This notebook only runs **Step 4** (comparison) on the cached outputs.

    ---
    """)
    return


@app.cell
def _():
    from pathlib import Path

    AUDIT_ROOT = Path(
        os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
    )
    TIER3_DIR = AUDIT_ROOT / "tier3_vs_gnssvod" / "Rosalia"

    CANVODPY_STORE = TIER3_DIR / "canvodpy_trimmed_store"
    GNSSVOD_CANOPY_PARQUET = TIER3_DIR / "gnssvod_canopy_output.parquet"
    GNSSVOD_VOD_PARQUET = TIER3_DIR / "gnssvod_vod_output.parquet"
    return (
        AUDIT_ROOT,
        CANVODPY_STORE,
        GNSSVOD_CANOPY_PARQUET,
        GNSSVOD_VOD_PARQUET,
        TIER3_DIR,
    )


@app.cell
def _(CANVODPY_STORE, GNSSVOD_CANOPY_PARQUET, GNSSVOD_VOD_PARQUET, mo):
    """Show status of precomputed outputs required for step 4."""
    _files = {
        "canvodpy trimmed store": CANVODPY_STORE,
        "gnssvod canopy parquet": GNSSVOD_CANOPY_PARQUET,
        "gnssvod VOD parquet": GNSSVOD_VOD_PARQUET,
    }
    _rows = [
        {
            "File": name,
            "Status": "✓ exists" if path.exists() else "✗ missing",
            "Path": str(path),
        }
        for name, path in _files.items()
    ]
    prereq_table = mo.ui.table(_rows, selection=None, label="Prerequisites (Steps 1–3)")
    prereq_table
    return (prereq_table,)


@app.cell
def _(mo):
    run_button = mo.ui.run_button(label="Run Step 4: compare")
    run_button
    return (run_button,)


@app.cell
def _(
    CANVODPY_STORE,
    GNSSVOD_CANOPY_PARQUET,
    GNSSVOD_VOD_PARQUET,
    is_script_mode,
    run_button,
):
    import numpy as np
    import pandas as pd
    import xarray as xr

    from canvod.audit.core import compare_datasets
    from canvod.audit.runners.common import AuditResult
    from canvod.audit.runners.vs_gnssvod import (
        GNSSVOD_TOLERANCES,  # type: ignore[unresolved-import]
        audit_vs_gnssvod,
        gnssvod_df_to_xarray,
    )
    from canvod.audit.tolerances import ToleranceTier

    audit = None

    if is_script_mode or run_button.value:
        audit = AuditResult()

        # ── 3A: SNR + angles ──────────────────────────────────────────────
        result_a = audit_vs_gnssvod(
            canvodpy_store=CANVODPY_STORE,
            gnssvod_file=GNSSVOD_CANOPY_PARQUET,
        )
        for k, v in result_a.results.items():
            audit.results[f"3A_{k}"] = v

        # ── 3B: VOD per band ──────────────────────────────────────────────
        if GNSSVOD_VOD_PARQUET.exists():
            ds_canvod = xr.open_zarr(str(CANVODPY_STORE))
            gnssvod_vod_df = pd.read_parquet(GNSSVOD_VOD_PARQUET)

            if "VOD" in ds_canvod.data_vars:
                ds_gnssvod_vod = gnssvod_df_to_xarray(gnssvod_vod_df)
                _band_mapping = [("VOD_L1", "L1|C"), ("VOD_L2", "L2|W")]

                for _vod_band, _canvod_suffix in _band_mapping:
                    if _vod_band not in ds_gnssvod_vod.data_vars:
                        continue

                    _matching_sids = [
                        s
                        for s in ds_canvod.sid.values
                        if str(s).endswith(f"|{_canvod_suffix}")
                    ]
                    if not _matching_sids:
                        continue

                    _ds_band = ds_canvod.sel(sid=_matching_sids)
                    _prns = [str(s).split("|")[0] for s in _matching_sids]
                    _ds_canvod_vod = xr.Dataset(
                        {_vod_band: (["epoch", "sid"], _ds_band["VOD"].values)},
                        coords={"epoch": _ds_band.epoch.values, "sid": _prns},
                    )

                    _shared_sids = np.intersect1d(
                        _ds_canvod_vod.sid.values, ds_gnssvod_vod.sid.values
                    )
                    _shared_epochs = np.intersect1d(
                        _ds_canvod_vod.epoch.values, ds_gnssvod_vod.epoch.values
                    )
                    if len(_shared_sids) == 0 or len(_shared_epochs) == 0:
                        continue

                    _r = compare_datasets(
                        _ds_canvod_vod,
                        ds_gnssvod_vod,
                        variables=[_vod_band],
                        tier=ToleranceTier.SCIENTIFIC,
                        tolerance_overrides={_vod_band: GNSSVOD_TOLERANCES["VOD"]},
                        label=f"canvodpy vs gnssvod: {_vod_band}",
                    )
                    audit.results[f"3B_{_vod_band}"] = _r

    return (audit,)


@app.cell
def _(audit, mo, render_audit_result):
    output = (
        mo.md(
            "_Click **Run Step 4: compare** to start.  Steps 1–3 must already be complete._"
        )
        if audit is None
        else render_audit_result(audit)
    )
    output
    return


if __name__ == "__main__":
    app.run()
