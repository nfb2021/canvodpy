"""Tier 3: Compare canvodpy against gnssvod (Humphrey et al.).

gnssvod is the established community tool for GNSS vegetation optical
depth, developed by Vincent Humphrey. It processes RINEX files into
VOD using an independent codebase.

Comparison philosophy
---------------------
This is the most important comparison in the audit suite.  canvodpy is
being validated against a peer-reviewed, community-established baseline.
Every difference must be *identified and explained* — not hidden in
tolerances.

There is no overall PASS/FAIL verdict.  Instead, each variable is
reported with full statistics and annotated against a physically-grounded
expected difference.  We flag anything that cannot be explained by the
documented mechanisms below.

Expected-difference inventory
------------------------------

SNR
    Budget: 2e-6 dB-Hz (float32 truncation).
    canvodpy stores SNR as float32 (deliberate — halves memory for large
    (epoch, sid) arrays).  gnssvod uses float64.  Both read the same
    trimmed RINEX.  float32 ULP for ~50 dB-Hz ≈ 6e-6 dB-Hz; the gate
    is set to 2e-6 dB-Hz (half-ULP rounding).  RINEX SNR precision is
    0.001 dB-Hz (F8.3), so float32 truncation is ~170× below measurement
    resolution.  Any SNR difference > 2e-6 dB-Hz indicates a decoding
    or formula bug.

Azimuth / Elevation
    Budget: None — systematic, reproducible, no fixed bound.
    canvodpy uses ``scipy.interpolate.CubicHermiteSpline`` on SP3
    positions and velocities.  gnssvod uses ``numpy.polyfit`` with a
    degree-16 polynomial on 4-hour windows (positions only, velocities
    by finite differencing).  Same SP3/CLK file, fundamentally different
    algorithms → different satellite ECEF → different angles.  The
    magnitude depends on satellite motion, window boundary effects, and
    SP3 epoch spacing.  No fixed bound is defensible.

VOD
    Budget: None — fully explained by Δcos(θ) from the angle difference.
    VOD = −ln(T) × cos(θ).  Both tools use the same RINEX (same T).
    All VOD difference should be explained by Δcos(θ).  Use
    ``vod_difference_decomposition()`` to quantify:
    - actual ΔV (observed)
    - predicted ΔV from Δcos(θ) alone
    - residual = actual − predicted  →  should be ≈ 0
    Expected max residual from float32 SNR noise: ≈ 9.2e-7 (negligible).
    A residual > 10× that bound indicates a formula or implementation
    difference beyond SP3 interpolation.

TODO
----
A canvodpy↔gnssvod grid adapter — projecting canvodpy EqualArea cells
into gnssvod's ``hemistats.Hemi`` — would enable cell-level VOD
comparison.  Not implemented here (obs-level decomposition is
sufficient and more diagnostic).

Comparison strategy
-------------------
1. Start with a **trimmed RINEX file** (see ``canvod.audit.rinex_trimmer``)
   that has exactly one observation code per band per system.  This
   eliminates signal selection ambiguity between the tools.
2. Feed the same trimmed RINEX to both canvodpy and gnssvod.
3. Use ``GnssvodAdapter`` (from ``canvod-adapters``, extracted from this
   module — see ``canvod.adapters.gnssvod``) to project canvodpy's
   (epoch, sid) dataset into gnssvod's variable space — same variable
   names, same units, same conventions.  Then compare two identically-shaped
   datasets.

Coordinate conventions
----------------------
canvodpy:
    theta = polar angle from Up, [0, π/2] rad (0=zenith, π/2=horizon)
    phi   = azimuth from North clockwise, [0, 2π) rad

gnssvod:
    Elevation = angle from horizon, [0, 90] degrees (0=horizon, 90=zenith)
    Azimuth   = angle from North clockwise, [0, 360) degrees

Mapping:
    Elevation = 90 - degrees(theta)
    Azimuth   = degrees(phi) mod 360

Usage::

    from canvod.audit.runners import audit_vs_gnssvod

    result = audit_vs_gnssvod(
        canvodpy_store="/path/to/store",
        gnssvod_file="/path/to/gnssvod_output.parquet",
        group="canopy_01",
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from canvod.adapters.gnssvod import (
    BAND_MAP,
    GnssvodAdapter,
    detect_band_map,
    gnssvod_df_to_xarray,
    gnssvod_merge_codes,
)
from canvod.audit.core import compare_datasets
from canvod.audit.runners.common import AuditResult, load_group, open_store
from canvod.audit.stats import (
    VariableBudget,
    compute_diff_report,
    print_diff_report,
)
from canvod.audit.tolerances import Tolerance, ToleranceTier

# ---------------------------------------------------------------------------
# Float32 noise floor
# ---------------------------------------------------------------------------
#
# canvodpy stores SNR as float32.  Propagation through the VOD formula:
#   VOD = -ln(T) × cos(θ),  T = 10^((SNR_canopy - SNR_ref) / 10)
#   δ(-ln T) = ln(10)/10 × δ(SNR_canopy - SNR_ref)
#   worst case: δSNR_diff ≈ 2 × 6e-6 dB-Hz (canopy + ref, both float32)
#   δVOD_residual ≤ ln(10)/10 × 1.2e-5 × 1 ≈ 2.8e-6
#
# We use 4e-6 dB-Hz for the two-SNR worst case → expected residual ≈ 9.2e-7.

_EXPECTED_FLOAT32_VOD_RESIDUAL: float = np.log(10) / 10 * 4e-6  # ≈ 9.2e-7

# ---------------------------------------------------------------------------
# Variable budgets
# ---------------------------------------------------------------------------

_FLOAT32_SNR_BUDGET = VariableBudget(
    budget=2e-6,
    unit="dB-Hz",
    source=(
        "float32 storage in canvodpy vs float64 in gnssvod; "
        "both read the same RINEX file. "
        "float32 ULP for 50 dB-Hz ≈ 6e-6 dB-Hz; gate at half-ULP = 2e-6."
    ),
    note=(
        "Deliberate canvodpy design choice: float32 halves memory for large "
        "(epoch, sid) arrays.  RINEX SNR precision is 0.001 dB-Hz (F8.3), so "
        "float32 truncation is ~170× below measurement resolution.  "
        "Any SNR difference > 2e-6 dB-Hz indicates a decoding or formula bug."
    ),
    vod_relevant=True,
)

_SP3_INTERP_SOURCE = (
    "Different SP3 interpolation algorithms (same SP3/CLK file): "
    "canvodpy CubicHermiteSpline (positions + velocities); "
    "gnssvod degree-16 polyfit on 4-hour windows (positions only, "
    "velocities by finite differencing)."
)

_SP3_INTERP_NOTE = (
    "Differences are systematic and reproducible — not numerical noise.  "
    "No analytically fixed bound exists: magnitude depends on satellite "
    "motion, SP3 epoch spacing, and polynomial window boundary effects."
)

_VOD_BUDGET_NOTE = (
    "VOD = -ln(T) × cos(θ).  T is identical for both tools (same RINEX, "
    "same formula).  All VOD difference should be explained by Δcos(θ) from "
    "different SP3 interpolation methods.  See vod_difference_decomposition() "
    "for per-observation decomposition.  Any residual > ~1e-6 indicates a "
    "formula or implementation difference beyond SP3 interpolation."
)

#: Per-variable expected-difference budgets for canvodpy vs gnssvod.
VARIABLE_BUDGETS_GNSSVOD: dict[str, VariableBudget] = {
    "Azimuth": VariableBudget(
        budget=None,
        unit="deg",
        source=_SP3_INTERP_SOURCE,
        note=(
            _SP3_INTERP_NOTE + "\n\n"
            "Wrap-around near 0°/360° is corrected before comparison "
            "via _wrap_aware_azimuth_diff()."
        ),
        vod_relevant=True,
    ),
    "Elevation": VariableBudget(
        budget=None,
        unit="deg",
        source=_SP3_INTERP_SOURCE,
        note=(
            _SP3_INTERP_NOTE + "  "
            "Elevation feeds directly into VOD via cos(polar_angle); "
            "see vod_difference_decomposition() for quantitative impact."
        ),
        vod_relevant=True,
    ),
}

# Formal SNR gate: used in compare_datasets for the float32 check only.
# nan_rate_atol=0.15 to accommodate gnssvod's hard elevation cutoff
# (drops rows with elevation ≤ -10°) vs canvodpy's NaN masking strategy.
_SNR_FORMAL_TOLERANCE = Tolerance(
    atol=2e-6,
    mae_atol=0.0,
    nan_rate_atol=0.15,
    description=_FLOAT32_SNR_BUDGET.source,
)


# ---------------------------------------------------------------------------
# VOD decomposition
# ---------------------------------------------------------------------------


def vod_difference_decomposition(
    elevation_canvod_deg: np.ndarray,
    elevation_gnssvod_deg: np.ndarray,
    vod_canvod: np.ndarray,
    vod_gnssvod: np.ndarray,
    elevation_cutoff_deg: float = 5.0,
) -> dict[str, Any]:
    """Decompose VOD difference into theta-explained and residual components.

    Both tools use the same RINEX → same T (transmittance).  All VOD
    difference must come from Δcos(θ):

    .. code-block:: text

        VOD = -ln(T) × cos(θ)
        −ln(T)        = VOD_canvodpy / cos(θ_canvod)
        predicted_ΔV  = −ln(T) × (cos(θ_canvod) − cos(θ_gnssvod))
        residual      = actual_ΔV − predicted_ΔV   →  should be ≈ 0

    Expected max residual from float32 SNR noise propagation: ≈ 9.2e-7.
    A residual > 10× that bound indicates a formula or implementation
    difference beyond SP3 interpolation.

    Parameters
    ----------
    elevation_canvod_deg, elevation_gnssvod_deg : array-like
        Elevation in degrees (flat).  Must be pre-aligned on the same
        (epoch, sid) pairs.
    vod_canvod, vod_gnssvod : array-like
        VOD values (flat), aligned with the elevation arrays.
    elevation_cutoff_deg : float
        Exclude obs below this elevation: cos(θ) → 0 near the horizon
        makes the −ln(T) inversion numerically unstable.

    Returns
    -------
    dict with keys:
        n_valid, n_excluded_horizon,
        actual_rmse, actual_max,
        predicted_rmse, predicted_max,
        residual_rmse, residual_max,
        explained_fraction,
        expected_max_residual,
        residual_exceeds_float32_noise.
    """
    elev_c = np.asarray(elevation_canvod_deg, dtype=np.float64).ravel()
    elev_g = np.asarray(elevation_gnssvod_deg, dtype=np.float64).ravel()
    vod_c = np.asarray(vod_canvod, dtype=np.float64).ravel()
    vod_g = np.asarray(vod_gnssvod, dtype=np.float64).ravel()

    both_finite = np.isfinite(vod_c) & np.isfinite(vod_g)
    both_elev = np.isfinite(elev_c) & np.isfinite(elev_g)
    above_cutoff = (elev_c > elevation_cutoff_deg) & (elev_g > elevation_cutoff_deg)
    valid = both_finite & both_elev & above_cutoff

    n_both = int(np.sum(both_finite & both_elev))
    n_excluded = n_both - int(valid.sum())

    _nan = float("nan")
    empty = {
        "n_valid": 0,
        "n_excluded_horizon": n_excluded,
        "actual_rmse": _nan,
        "actual_max": _nan,
        "predicted_rmse": _nan,
        "predicted_max": _nan,
        "residual_rmse": _nan,
        "residual_max": _nan,
        "explained_fraction": _nan,
        "expected_max_residual": _EXPECTED_FLOAT32_VOD_RESIDUAL,
        "residual_exceeds_float32_noise": False,
    }
    if valid.sum() == 0:
        return empty

    theta_c = np.radians(90.0 - elev_c[valid])
    theta_g = np.radians(90.0 - elev_g[valid])
    cos_c = np.cos(theta_c)
    cos_g = np.cos(theta_g)

    # Recover −ln(T) from canvodpy; cos_c > 0 guaranteed by elevation cutoff
    minus_ln_T = vod_c[valid] / cos_c

    actual_delta = vod_c[valid] - vod_g[valid]
    predicted_delta = minus_ln_T * (cos_c - cos_g)
    residual = actual_delta - predicted_delta

    var_actual = float(np.var(actual_delta))
    var_residual = float(np.var(residual))
    explained = 1.0 - var_residual / var_actual if var_actual > 0.0 else _nan

    res_max = float(np.max(np.abs(residual)))
    exceeds = res_max > _EXPECTED_FLOAT32_VOD_RESIDUAL * 10

    return {
        "n_valid": int(valid.sum()),
        "n_excluded_horizon": n_excluded,
        "actual_rmse": float(np.sqrt(np.mean(actual_delta**2))),
        "actual_max": float(np.max(np.abs(actual_delta))),
        "predicted_rmse": float(np.sqrt(np.mean(predicted_delta**2))),
        "predicted_max": float(np.max(np.abs(predicted_delta))),
        "residual_rmse": float(np.sqrt(np.mean(residual**2))),
        "residual_max": res_max,
        "explained_fraction": explained,
        "expected_max_residual": _EXPECTED_FLOAT32_VOD_RESIDUAL,
        "residual_exceeds_float32_noise": exceeds,
    }


def print_vod_decomposition(
    decomp: dict[str, Any],
    vod_col: str,
    elevation_cutoff_deg: float = 5.0,
) -> None:
    """Print a structured VOD decomposition summary."""
    print(f"\n  VOD decomposition: {vod_col}")
    print(
        f"  (elevation > {elevation_cutoff_deg}°, "
        f"n_valid={decomp['n_valid']:,}, "
        f"excluded near-horizon: {decomp['n_excluded_horizon']:,})"
    )
    if decomp["n_valid"] == 0:
        print("    (no valid pairs above elevation cutoff)")
        return

    exp = decomp["expected_max_residual"]
    print(
        f"    actual    ΔV : RMSE={decomp['actual_rmse']:.4g}   max={decomp['actual_max']:.4g}"
    )
    print(
        f"    predicted ΔV : RMSE={decomp['predicted_rmse']:.4g}   max={decomp['predicted_max']:.4g}  (from Δcos θ)"
    )
    print(
        f"    residual  ΔV : RMSE={decomp['residual_rmse']:.4g}   max={decomp['residual_max']:.4g}"
    )
    print(f"    explained fraction   : {decomp['explained_fraction']:.1%}")
    print(f"    expected float32 max : {exp:.2g}")
    if decomp["residual_exceeds_float32_noise"]:
        print(
            f"    *** RESIDUAL EXCEEDS 10× FLOAT32 NOISE ({10 * exp:.2g}) — "
            "investigate formula or implementation difference ***"
        )
    else:
        print(f"    OK: residual within 10× float32 noise ({10 * exp:.2g})")


# ---------------------------------------------------------------------------
# Azimuth wrap-around handling
# ---------------------------------------------------------------------------


def _wrap_aware_azimuth_diff(ds_a, ds_b, var="Azimuth"):
    """Replace Azimuth in ds_a with wrap-corrected values relative to ds_b.

    Azimuth differences near 0°/360° boundary can produce spurious ~360°
    diffs. This adjusts ds_a's Azimuth so that (ds_a - ds_b) gives the
    shortest angular distance, enabling standard abs-diff statistics.

    Returns a copy of ds_a with corrected Azimuth.
    """
    if var not in ds_a.data_vars or var not in ds_b.data_vars:
        return ds_a

    a = ds_a[var].values.copy()
    b = ds_b[var].values

    diff = a - b
    a[diff > 180] -= 360
    a[diff < -180] += 360

    ds_a = ds_a.copy()
    ds_a[var] = (ds_a[var].dims, a)
    return ds_a


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_canvodpy(canvodpy_store, canvodpy_ds, group):
    """Load canvodpy data from store or return pre-loaded dataset."""
    if canvodpy_ds is not None:
        return canvodpy_ds

    if canvodpy_store is None:
        raise ValueError("Provide either canvodpy_store or canvodpy_ds.")

    store_path = Path(canvodpy_store)
    if (
        (store_path / ".zgroup").exists()
        or (store_path / ".zmetadata").exists()
        or (store_path / "zarr.json").exists()
    ):
        ds = xr.open_zarr(str(store_path))
        print(f"canvodpy (Zarr): {dict(ds.sizes)}")
    else:
        s = open_store(canvodpy_store)
        print(f"Loading canvodpy group '{group}' ...")
        ds = load_group(s, group)
        print(f"canvodpy: {dict(ds.sizes)}")
    return ds


def _load_gnssvod(gnssvod_dataframe, gnssvod_file, epoch_col, sid_col):
    """Load gnssvod data and convert to xarray."""
    if gnssvod_dataframe is None and gnssvod_file is None:
        raise ValueError(
            "Provide either gnssvod_dataframe (a pandas DataFrame) "
            "or gnssvod_file (path to CSV/Parquet)."
        )

    if gnssvod_dataframe is None:
        gnssvod_file = Path(gnssvod_file)
        print(f"Loading gnssvod data from {gnssvod_file} ...")
        import pandas as pd

        if gnssvod_file.suffix == ".parquet":
            gnssvod_dataframe = pd.read_parquet(gnssvod_file)
        else:
            gnssvod_dataframe = pd.read_csv(gnssvod_file)

    return gnssvod_df_to_xarray(
        gnssvod_dataframe,
        epoch_col=epoch_col,
        sid_col=sid_col,
    )


# ---------------------------------------------------------------------------
# Per-band comparison
# ---------------------------------------------------------------------------


def _compare_band(
    ds_canvod_band: xr.Dataset,
    ds_gnssvod: xr.Dataset,
    band_suffix: str,
    snr_col: str,
    vod_col: str | None,
    elevation_cutoff_deg: float = 5.0,
) -> dict[str, Any] | None:
    """Compare one band.

    Returns a dict with keys:
    - ``"snr_comparison"`` : ComparisonResult or None (formal float32 gate)
    - ``"vod_decomp"``     : decomposition dict or None

    All statistics are printed; the caller decides what to store.
    Returns None if there are no shared variables or coordinates.
    """
    # Determine which variables to compare
    compare_vars = [
        v
        for v in ["Azimuth", "Elevation", snr_col]
        if v in ds_canvod_band.data_vars and v in ds_gnssvod.data_vars
    ]
    if (
        vod_col
        and vod_col in ds_canvod_band.data_vars
        and vod_col in ds_gnssvod.data_vars
    ):
        compare_vars.append(vod_col)

    if not compare_vars:
        print("  No shared variables to compare")
        return None

    # Align on shared (epoch, sid) pairs
    shared_sids = np.intersect1d(ds_canvod_band.sid.values, ds_gnssvod.sid.values)
    shared_epochs = np.intersect1d(ds_canvod_band.epoch.values, ds_gnssvod.epoch.values)
    if len(shared_sids) == 0 or len(shared_epochs) == 0:
        print(
            f"  No shared coordinates "
            f"(canvod sids={len(ds_canvod_band.sid)}, "
            f"gnssvod sids={len(ds_gnssvod.sid)})"
        )
        return None

    ds_a = ds_canvod_band.sel(sid=shared_sids, epoch=shared_epochs)
    ds_b = ds_gnssvod.sel(sid=shared_sids, epoch=shared_epochs)

    # Correct azimuth wrap-around before computing differences
    ds_a = _wrap_aware_azimuth_diff(ds_a, ds_b)

    # Build budgets dict: SNR has a tight float32 budget; angles and VOD
    # have budget=None (systematic SP3 interp difference, no fixed bound).
    budgets: dict[str, VariableBudget] = dict(VARIABLE_BUDGETS_GNSSVOD)
    budgets[snr_col] = _FLOAT32_SNR_BUDGET
    if vod_col:
        budgets[vod_col] = VariableBudget(
            budget=None,
            unit="",
            source="Different SP3 interp → different cos(θ); see decomposition below.",
            note=_VOD_BUDGET_NOTE,
            vod_relevant=True,
        )

    # ── Full observable report for all variables ──────────────────────
    diff_stats = compute_diff_report(
        ds_a,
        ds_b,
        budgets,
        vars_to_check=compare_vars,
        label_a="canvodpy",
        label_b="gnssvod",
    )
    print_diff_report(
        diff_stats,
        f"canvodpy vs gnssvod: {band_suffix}",
        label_a="canvodpy",
        label_b="gnssvod",
    )

    # ── Formal SNR gate (float32 budget) ─────────────────────────────
    snr_result = None
    if snr_col in compare_vars:
        snr_result = compare_datasets(
            ds_a,
            ds_b,
            variables=[snr_col],
            tier=ToleranceTier.SCIENTIFIC,
            tolerance_overrides={snr_col: _SNR_FORMAL_TOLERANCE},
            label=f"{band_suffix}: SNR float32 gate",
        )
        status = "PASS" if snr_result.passed else "*** FAIL ***"
        print(f"\n  SNR float32 gate [{status}]")
        if not snr_result.passed:
            for var, reason in snr_result.failures.items():
                print(f"    {var}: {reason}")

    # ── VOD decomposition ────────────────────────────────────────────
    vod_decomp = None
    if (
        vod_col
        and vod_col in compare_vars
        and "Elevation" in ds_a.data_vars
        and "Elevation" in ds_b.data_vars
    ):
        vod_decomp = vod_difference_decomposition(
            ds_a["Elevation"].values.ravel(),
            ds_b["Elevation"].values.ravel(),
            ds_a[vod_col].values.ravel(),
            ds_b[vod_col].values.ravel(),
            elevation_cutoff_deg=elevation_cutoff_deg,
        )
        print_vod_decomposition(vod_decomp, vod_col, elevation_cutoff_deg)

    return {
        "snr_comparison": snr_result,
        "vod_decomp": vod_decomp,
    }


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------


def audit_vs_gnssvod(
    canvodpy_store=None,
    canvodpy_ds=None,
    gnssvod_dataframe=None,
    gnssvod_file=None,
    *,
    group="canopy_01",
    band_map=None,
    mode="trimmed",
    epoch_col="Epoch",
    sid_col="SV",
    elevation_cutoff_deg: float = 5.0,
) -> AuditResult:
    """Compare canvodpy output against gnssvod output.

    Produces a full diagnostic comparison: every variable reported with
    actual statistics annotated against its physically-grounded expected
    difference.  There is no overall binary PASS/FAIL verdict — the tools
    are known to differ on Azimuth/Elevation/VOD due to different SP3
    interpolation methods.  The SNR float32 gate is the only hard check.

    Two comparison modes:

    ``mode="trimmed"`` (default):
        Both tools ran on the same trimmed RINEX (one code per band).
        canvodpy SIDs map 1:1 to gnssvod PRNs via ``GnssvodAdapter``.
        SNR should be within float32 precision.

    ``mode="merged"``:
        Both tools ran on the same untrimmed RINEX (multiple codes per
        band). canvodpy's per-SID values are merged using gnssvod's
        fillna logic (lexicographic priority via numpy.intersect1d) to
        produce one merged value per PRN.

    Parameters
    ----------
    canvodpy_store : str, Path, or MyIcechunkStore, optional
    canvodpy_ds : xarray.Dataset, optional
    gnssvod_dataframe : pandas.DataFrame, optional
    gnssvod_file : str or Path, optional
    group : str
    band_map : list of tuples, optional
    mode : str
    epoch_col, sid_col : str
    elevation_cutoff_deg : float
        Elevation cutoff for VOD decomposition (default 5°).

    Returns
    -------
    AuditResult
        ``result.results[f"snr_{band_suffix}"]`` contains the SNR
        ``ComparisonResult`` (float32 gate).  Azimuth/Elevation/VOD
        statistics are printed but not stored (no fixed pass/fail gate).
    """
    if mode not in ("trimmed", "merged"):
        raise ValueError(f"mode must be 'trimmed' or 'merged', got '{mode}'")

    # ── Load data ─────────────────────────────────────────────────────
    canvodpy_ds = _load_canvodpy(canvodpy_store, canvodpy_ds, group)
    print(f"  SID examples: {list(canvodpy_ds.sid.values[:5])}")
    print(f"  Variables: {sorted(canvodpy_ds.data_vars)}")

    ds_gnssvod = _load_gnssvod(gnssvod_dataframe, gnssvod_file, epoch_col, sid_col)
    print(
        f"gnssvod: {dict(ds_gnssvod.sizes)}, variables: {sorted(ds_gnssvod.data_vars)}"
    )

    # ── Auto-detect band map if needed ────────────────────────────────
    if band_map is None:
        band_map = detect_band_map(canvodpy_ds, ds_gnssvod)
        if band_map:
            print(f"\n  Auto-detected bands: {[(b, s) for b, s, _ in band_map]}")
        else:
            print("  WARNING: Could not auto-detect bands, falling back to defaults")
            band_map = BAND_MAP

    print(f"  Mode: {mode}")

    # ── Compare per band ──────────────────────────────────────────────
    result = AuditResult()

    for band_suffix, snr_col, vod_col in band_map:
        if snr_col not in ds_gnssvod.data_vars:
            print(f"\n  Skipping {band_suffix}: {snr_col} not in gnssvod output")
            continue

        print(f"\n{'─' * 60}")
        print(f"Band: {band_suffix} → {snr_col} (mode={mode})")

        if mode == "trimmed":
            matching_sids = [
                s for s in canvodpy_ds.sid.values if str(s).endswith(f"|{band_suffix}")
            ]
            if not matching_sids:
                print(f"  Skipping: no matching SIDs for |{band_suffix}")
                continue

            print(f"  canvodpy SIDs: {len(matching_sids)}")
            try:
                adapter = GnssvodAdapter(
                    canvodpy_ds,
                    band_filter=band_suffix,
                    snr_col=snr_col,
                    vod_col=vod_col,
                )
            except ValueError as e:
                print(f"  ERROR: {e}")
                continue
            ds_adapted = adapter.to_gnssvod_dataset()

        else:
            # Merged mode: replicate gnssvod's fillna across codes
            band_num = band_suffix.split("|")[0].replace("L", "")
            try:
                ds_merged = gnssvod_merge_codes(canvodpy_ds, band_num)
            except ValueError as e:
                print(f"  Skipping: {e}")
                continue

            data_vars = {}
            if "SNR" in ds_merged.data_vars:
                data_vars[snr_col] = ds_merged["SNR"]
            if "phi" in ds_merged.data_vars:
                data_vars["Azimuth"] = (
                    ds_merged["phi"].dims,
                    np.degrees(ds_merged["phi"].values) % 360.0,
                )
            if "theta" in ds_merged.data_vars:
                data_vars["Elevation"] = (
                    ds_merged["theta"].dims,
                    90.0 - np.degrees(ds_merged["theta"].values),
                )
            if vod_col and "VOD" in ds_merged.data_vars:
                data_vars[vod_col] = ds_merged["VOD"]

            ds_adapted = xr.Dataset(data_vars, coords=ds_merged.coords)

        print(
            f"  Adapted: {dict(ds_adapted.sizes)}, vars={sorted(map(str, ds_adapted.data_vars))}"
        )

        band_result = _compare_band(
            ds_adapted,
            ds_gnssvod,
            band_suffix,
            snr_col,
            vod_col,
            elevation_cutoff_deg=elevation_cutoff_deg,
        )
        if band_result is None:
            continue

        # Only store ComparisonResult objects in AuditResult (SNR gate)
        if band_result["snr_comparison"] is not None:
            result.results[f"snr_{band_suffix}"] = band_result["snr_comparison"]

    # ── Diagnostic summary ────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("Tier 3 diagnostic summary")
    print(f"{'=' * 60}")
    print("SNR float32 gate results:")
    if result.results:
        for name, r in result.results.items():
            status = "PASS" if r.passed else "FAIL ***"
            print(f"  [{status}] {r.label}")
            if r.failures:
                for var, reason in r.failures.items():
                    print(f"      {var}: {reason}")
    else:
        print("  (no SNR comparisons run)")
    print()
    print(
        "Note: Azimuth/Elevation/VOD differences are reported above per band.\n"
        "No pass/fail verdict for these variables — differences are systematic\n"
        "and explained by different SP3 interpolation methods (CubicHermiteSpline\n"
        "vs degree-16 polyfit). See vod_difference_decomposition() residuals\n"
        "for the only scientifically gated VOD check."
    )

    return result
