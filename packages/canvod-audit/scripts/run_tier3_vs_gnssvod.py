"""Tier 3: canvodpy vs gnssvod (Humphrey et al.) — external comparison.

Workflow
--------
1. Trim RINEX files to one obs code per band per system (gfzrnx).
2. Run gnssvod on the trimmed RINEX:
   a. ``preprocess()`` both canopy and reference (adds Azimuth/Elevation).
   b. Save preprocessed NetCDF files.
   c. ``gather_stations()`` pairs canopy + reference.
   d. ``calc_vod()`` computes VOD from the paired data.
3. Run canvodpy on the same trimmed RINEX using the **same GFZ rapid**
   SP3/CLK files that gnssvod downloaded.
4. Compare:
   A. SNR, Azimuth, Elevation (canvodpy vs gnssvod preprocess output)
   B. VOD per band (canvodpy vs gnssvod calc_vod output)

Prerequisites
-------------
- gfzrnx installed (``/usr/local/bin/gfzrnx``)
- gnssvod installed (``uv pip install gnssvod``)

Ephemeris strategy
------------------
gnssvod forces **GFZ rapid** products (``GFZ0MGXRAP``) for GPS week >= 2038
(i.e. all data from ~2019 onwards). To ensure a fair comparison, canvodpy
is configured with ``agency="GFZ", product_type="rapid"`` so both tools
use byte-identical SP3/CLK files.

SP3 interpolation methods
-------------------------
Although both tools read the same SP3 file, they use **fundamentally
different interpolation algorithms** to compute satellite ECEF positions
at observation epochs:

- **canvodpy**: ``scipy.interpolate.CubicHermiteSpline`` — piecewise cubic,
  uses both SP3 positions **and velocities** as constraints.
- **gnssvod**: ``numpy.polyfit`` with degree-16 polynomial on 4-hour windows
  (17 SP3 epochs at 15-min spacing). Velocities derived by finite
  differencing the interpolated positions, not from SP3 velocity data.

This produces systematic (not random) differences in satellite ECEF
positions → different theta/phi → different cos(theta) in the VOD formula.
The differences are real, reproducible, and expected.

SNR dtype difference
--------------------
canvodpy stores SNR as ``float32`` (deliberate — halves memory for large
``(epoch, sid)`` arrays). gnssvod uses ``float64``. The RINEX file contains
SNR values with ~0.001 dB precision (3 decimal places). ``float32``
truncation introduces max ~2e-6 dB error — 1000x below measurement
resolution. This is not a bug.

Elevation cutoff strategy
-------------------------
gnssvod applies a hard elevation cutoff of -10 deg in ``gnssDataframe()``
(``preprocessing.py:370``), **dropping rows** with elevation <= -10 deg.
canvodpy instead masks below-horizon (elevation < 0) observations to NaN
but retains them in the array.

For a fair comparison, the adapter aligns on shared (epoch, SID) pairs via
``np.intersect1d``. Observations that gnssvod dropped are simply absent
from the gnssvod dataset and excluded from comparison. Observations that
canvodpy masked to NaN are excluded from statistics (computed on mutually
valid pairs only). The NaN rate tolerance (``nan_rate_atol``) catches any
systematic difference in missing-data patterns.

VOD comparison strategy
-----------------------
gnssvod computes VOD inside ``calc_vod()`` using paired canopy/reference
data. The formula is identical to canvodpy's ``TauOmegaZerothOrder``:

    VOD = -ln(10^((SNR_canopy - SNR_reference) / 10)) * cos(polar_angle_canopy)

Both tools use the canopy station's polar angle. The only expected
differences come from the different SP3 interpolation methods described
above (different satellite ECEF → different theta → different cos(theta) in the polar angle correction).
SNR itself is identical (same RINEX, same formula).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from canvod.audit.reporting.typst import to_typst
from canvod.audit.rinex_trimmer import gps_galileo_l1_l2
from canvod.audit.runners.common import AuditResult
from canvod.audit.runners.vs_gnssvod import audit_vs_gnssvod

# ── Configuration ────────────────────────────────────────────────────────────

ROSALIA_ROOT = Path(
    "/Users/work/Developer/GNSS/canvodpy/packages/canvod-readers"
    "/tests/test_data/valid/rinex_v3_04/01_Rosalia"
)

CANOPY_DIR = ROSALIA_ROOT / "02_canopy" / "01_GNSS" / "01_raw" / "25001"
REFERENCE_DIR = ROSALIA_ROOT / "01_reference" / "01_GNSS" / "01_raw" / "25001"

AUDIT_ROOT = Path(
    os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
)
TIER3_DIR = AUDIT_ROOT / "tier3_vs_gnssvod" / "Rosalia"

# Ephemeris: match gnssvod's GFZ rapid products
EPHEMERIS_AGENCY = "GFZ"
EPHEMERIS_PRODUCT = "rapid"

# VOD band configuration for gnssvod's calc_vod()
# Maps band name → list of observation types to search for.
# gnssvod uses np.intersect1d to find which exist → lex-sorted,
# then fills NaN in that order (C before W before X).
GNSSVOD_VOD_BANDS = {
    "VOD_L1": ["S1", "S1C", "S1X", "S1W"],
    "VOD_L2": ["S2", "S2C", "S2X", "S2W"],
}


def _find_rinex_files(directory: Path) -> list[Path]:
    """Find and sort RINEX files in a directory."""
    files = sorted(directory.glob("*.rnx"))
    if not files:
        files = sorted(directory.glob("*.RNX"))
    return files


def _extract_date_from_rinex(rnx_path: Path) -> str:
    """Extract YYYYDOY date string from RINEX filename or header.

    Tries filename conventions first (e.g. ROSA01TUW_R_20250010000...),
    then falls back to reading the header.
    """
    name = rnx_path.stem
    # Long-name RINEX v3: ...._R_YYYYDOY0000_...
    if "_R_" in name:
        parts = name.split("_R_")
        if len(parts) >= 2 and len(parts[1]) >= 7:
            return parts[1][:7]  # YYYYDOY

    # Fallback: read first few lines for TIME OF FIRST OBS
    with open(rnx_path) as f:
        for line in f:
            if "TIME OF FIRST OBS" in line:
                tokens = line.split()
                year = int(tokens[0])
                month = int(tokens[1])
                day = int(tokens[2])
                from datetime import date

                doy = (date(year, month, day) - date(year, 1, 1)).days + 1
                return f"{year}{doy:03d}"
            if "END OF HEADER" in line:
                break

    raise ValueError(f"Cannot extract date from {rnx_path}")


# ── Step 1: Trim RINEX ───────────────────────────────────────────────────────


def step1_trim_rinex() -> tuple[Path, Path | None]:
    """Trim RINEX files to GPS+Galileo L1+L2, one code per band."""
    trimmer = gps_galileo_l1_l2()

    canopy_files = _find_rinex_files(CANOPY_DIR)
    ref_files = _find_rinex_files(REFERENCE_DIR)

    print(f"Canopy: {len(canopy_files)} files")
    print(f"Reference: {len(ref_files)} files")

    if not canopy_files:
        print(f"ERROR: No RINEX files in {CANOPY_DIR}")
        sys.exit(1)

    TIER3_DIR.mkdir(parents=True, exist_ok=True)

    canopy_trimmed = TIER3_DIR / "canopy_trimmed.rnx"
    ref_trimmed = TIER3_DIR / "reference_trimmed.rnx"

    if canopy_trimmed.exists():
        print(f"\n  Canopy trimmed file exists, skipping: {canopy_trimmed}")
    else:
        print("\n── Trimming canopy ──")
        trimmer.preview(canopy_files)
        trimmer.write(canopy_files, canopy_trimmed)

    if ref_files and not ref_trimmed.exists():
        print("\n── Trimming reference ──")
        trimmer.write(ref_files, ref_trimmed)
    elif not ref_files:
        ref_trimmed = None

    # Save trimming description for reproducibility
    desc = trimmer.describe(canopy_files, canopy_trimmed)
    desc_path = TIER3_DIR / "trimming_description.txt"
    desc_path.write_text(desc)
    print(f"\nTrimming description saved: {desc_path}")

    return canopy_trimmed, ref_trimmed


# ── Step 2: Run gnssvod (full pipeline: preprocess + gather + calc_vod) ─────


def step2_run_gnssvod(
    canopy_trimmed: Path,
    ref_trimmed: Path | None,
) -> tuple[Path, Path | None]:
    """Run gnssvod's full pipeline on trimmed RINEX files.

    1. preprocess() canopy and reference (adds Azimuth/Elevation,
       applies elevation cutoff of -10 deg)
    2. Save preprocessed data as NetCDF (for gather_stations)
    3. gather_stations() to pair canopy + reference
    4. calc_vod() to compute VOD from the paired data

    Returns
    -------
    tuple[Path, Path | None]
        (canopy_preprocess_parquet, vod_output_parquet_or_None)
    """
    import gnssvod

    # Both tools share one aux directory → guarantees identical SP3/CLK files
    aux_path = str(TIER3_DIR / "shared_aux")
    Path(aux_path).mkdir(parents=True, exist_ok=True)

    nc_dir = TIER3_DIR / "gnssvod_nc"

    canopy_output = TIER3_DIR / "gnssvod_canopy_output.parquet"
    vod_output = TIER3_DIR / "gnssvod_vod_output.parquet"

    # ── 2a. Preprocess canopy ──
    canopy_nc_dir = nc_dir / "canopy"
    canopy_nc_dir.mkdir(parents=True, exist_ok=True)  # MUST exist before preprocess

    if not canopy_output.exists():
        print("\n── Running gnssvod preprocess: canopy ──")
        print(f"Input: {canopy_trimmed}")
        results = gnssvod.preprocess(
            filepattern={"canopy": str(canopy_trimmed)},
            orbit=True,
            aux_path=aux_path,
            outputdir={"canopy": str(canopy_nc_dir)},
            outputresult=True,
        )
        obs = results["canopy"][0]
        df = obs.observation
        if df is None:
            raise RuntimeError("gnssvod returned no observation data for canopy")
        print(f"gnssvod canopy: {df.shape}, columns: {list(df.columns[:10])}")
        print(f"  Index levels: {df.index.names}")
        df.to_parquet(canopy_output)
        print(f"Saved: {canopy_output}")
    else:
        print(f"\n  gnssvod canopy exists, skipping: {canopy_output}")

    # ── 2b. Preprocess reference ──
    if ref_trimmed is not None:
        ref_nc_dir = nc_dir / "reference"
        ref_nc_dir.mkdir(parents=True, exist_ok=True)  # MUST exist before preprocess

        ref_output = TIER3_DIR / "gnssvod_reference_output.parquet"
        if not ref_output.exists():
            print("\n── Running gnssvod preprocess: reference ──")
            results_ref = gnssvod.preprocess(
                filepattern={"reference": str(ref_trimmed)},
                orbit=True,
                aux_path=aux_path,
                outputdir={"reference": str(ref_nc_dir)},
                outputresult=True,
            )
            ref_obs = results_ref["reference"][0]
            ref_df = ref_obs.observation
            if ref_df is not None:
                ref_df.to_parquet(ref_output)
                print(f"Saved: {ref_output}")
            else:
                print("  WARNING: gnssvod returned no data for reference")
        else:
            print(f"\n  gnssvod reference exists, skipping: {ref_output}")

        # ── 2c. Gather stations + calc_vod ──
        if not vod_output.exists():
            _run_gnssvod_vod(canopy_nc_dir, ref_nc_dir, canopy_output, vod_output)
        else:
            print(f"\n  gnssvod VOD exists, skipping: {vod_output}")

        return canopy_output, vod_output
    else:
        print("\n  No reference RINEX — skipping gnssvod VOD calculation")
        return canopy_output, None


def _run_gnssvod_vod(
    canopy_nc_dir: Path,
    ref_nc_dir: Path,
    canopy_parquet: Path,
    vod_output: Path,
) -> None:
    """Run gnssvod's gather_stations + calc_vod pipeline."""
    from gnssvod.analysis.vod_calc import calc_vod
    from gnssvod.io.preprocessing import gather_stations

    print("\n── Running gnssvod gather_stations + calc_vod ──")

    gathered_dir = TIER3_DIR / "gnssvod_gathered"
    gathered_dir.mkdir(parents=True, exist_ok=True)

    # Determine time range from canopy data for gather_stations
    canopy_df = pd.read_parquet(canopy_parquet)
    if isinstance(canopy_df.index, pd.MultiIndex):
        epochs = canopy_df.index.get_level_values("Epoch")
    elif "Epoch" in canopy_df.columns:
        epochs = canopy_df["Epoch"]
    else:
        raise RuntimeError("Cannot find Epoch in gnssvod canopy output")

    time_intervals = pd.interval_range(
        start=pd.Timestamp(epochs.min()).normalize(),  # ty: ignore[unresolved-attribute]
        end=pd.Timestamp(epochs.max()).normalize() + pd.Timedelta("1D"),  # ty: ignore[unresolved-attribute]
        freq="1D",
    )

    # gather_stations: filepattern keys MUST match station names in pairings
    canopy_nc_pattern = str(canopy_nc_dir / "*.nc")
    ref_nc_pattern = str(ref_nc_dir / "*.nc")

    print(f"  Canopy NC: {canopy_nc_pattern}")
    print(f"  Reference NC: {ref_nc_pattern}")

    gather_stations(
        filepattern={
            "canopy": canopy_nc_pattern,
            "reference": ref_nc_pattern,
        },
        pairings={"rosalia": ("reference", "canopy")},
        timeintervals=time_intervals,
        outputdir={"rosalia": str(gathered_dir)},
    )

    # Verify gathered files exist
    gathered_files = sorted(gathered_dir.glob("*.nc"))
    if not gathered_files:
        raise RuntimeError(f"No gathered NC files in {gathered_dir}")
    print(f"  Gathered files: {len(gathered_files)}")

    # calc_vod: pairings reference station names that must exist as
    # Station index level in the gathered NC files.
    # Pairing: ("reference", "canopy") → ref=reference, grn=canopy
    # VOD = -ln(10^((SNR_canopy - SNR_reference)/10)) * cos(zenith_canopy)
    vod_results = calc_vod(
        filepattern=str(gathered_dir / "*.nc"),
        pairings={"rosalia": ("reference", "canopy")},
        bands=GNSSVOD_VOD_BANDS,
    )

    vod_df = vod_results["rosalia"]
    print(f"gnssvod VOD: {vod_df.shape}")
    print(f"  Columns: {list(vod_df.columns)}")
    print(f"  Index: {vod_df.index.names}")
    vod_df.to_parquet(vod_output)
    print(f"Saved: {vod_output}")


# ── Step 3: Run canvodpy ─────────────────────────────────────────────────────


def _parse_approx_position(rnx_path: Path):
    """Extract APPROX POSITION XYZ from RINEX header."""
    from canvod.auxiliary.position.position import ECEFPosition

    with open(rnx_path) as f:
        for line in f:
            if "APPROX POSITION XYZ" in line:
                tokens = line.split()
                return ECEFPosition(
                    x=float(tokens[0]), y=float(tokens[1]), z=float(tokens[2])
                )
            if "END OF HEADER" in line:
                break
    raise ValueError(f"No APPROX POSITION XYZ in {rnx_path}")


def _read_and_augment(trimmed_rnx: Path, date_str: str):
    """Read trimmed RINEX and augment with GFZ rapid ephemeris.

    Uses the same GFZ rapid SP3/CLK products that gnssvod downloads,
    ensuring identical satellite positions for a fair comparison.

    Returns an xarray.Dataset with SNR, phi, theta.
    """
    from canvodpy.functional import augment_with_ephemeris

    from canvod.auxiliary.position.position import ECEFPosition
    from canvod.readers.rinex.v3_04 import Rnxv3Obs

    reader = Rnxv3Obs(fpath=trimmed_rnx, completeness_mode="off")
    ds = reader.to_ds()
    print(f"  Read: {dict(ds.sizes)}, vars={list(ds.data_vars)}")

    # Receiver position from RINEX header (reader doesn't propagate to attrs,
    # so parse directly from the file header)
    try:
        rx_pos = ECEFPosition.from_ds_metadata(ds)
    except KeyError:
        rx_pos = _parse_approx_position(trimmed_rnx)
    print(f"  Receiver ECEF: ({rx_pos.x:.2f}, {rx_pos.y:.2f}, {rx_pos.z:.2f})")

    # Augment with GFZ rapid — same product and same files as gnssvod
    ds_aug = augment_with_ephemeris(
        ds,
        receiver_position=rx_pos,
        source=EPHEMERIS_PRODUCT,
        agency=EPHEMERIS_AGENCY,
        date=date_str,
        aux_data_dir=TIER3_DIR / "shared_aux",
    )
    print(f"  Augmented: vars={list(ds_aug.data_vars)}")
    return ds_aug


def step3_run_canvodpy(
    canopy_trimmed: Path,
    ref_trimmed: Path | None,
) -> Path:
    """Run canvodpy on trimmed RINEX: read, augment with GFZ rapid, compute VOD.

    Returns path to the Zarr store containing canvodpy output with
    SNR, phi, theta, and (if reference available) VOD.
    """
    store_path = TIER3_DIR / "canvodpy_trimmed_store"

    if store_path.exists():
        print(f"\n  canvodpy trimmed store exists, skipping: {store_path}")
        return store_path

    print("\n── Running canvodpy on trimmed RINEX ──")

    date_str = _extract_date_from_rinex(canopy_trimmed)
    print(f"  Date: {date_str}")

    # Read and augment canopy
    print("\n  Canopy:")
    ds_canopy = _read_and_augment(canopy_trimmed, date_str)

    # Read and augment reference (if available)
    ds_ref = None
    if ref_trimmed is not None and ref_trimmed.exists():
        print("\n  Reference:")
        ds_ref = _read_and_augment(ref_trimmed, date_str)

    # Compute VOD if both canopy and reference are available
    if ds_ref is not None:
        from canvod.vod.calculator import TauOmegaZerothOrder

        print("\n  Computing VOD ...")
        # from_datasets aligns canopy and reference via xr.align(join="inner")
        # then computes VOD = -ln(transmissivity) * cos(canopy_theta)
        vod_ds = TauOmegaZerothOrder.from_datasets(
            canopy_ds=ds_canopy,
            sky_ds=ds_ref,
        )
        print(f"  VOD: {dict(vod_ds.sizes)}, vars={list(vod_ds.data_vars)}")

        # Merge VOD back into canopy dataset (which has SNR, phi, theta)
        ds_out = ds_canopy.copy()
        if "VOD" in vod_ds.data_vars:
            ds_out["VOD"] = vod_ds["VOD"]
    else:
        print("\n  No reference available — skipping VOD calculation")
        ds_out = ds_canopy

    print(f"\n  Final output: {dict(ds_out.sizes)}, vars={sorted(ds_out.data_vars)}")

    ds_out.to_zarr(str(store_path), mode="w")
    print(f"  Written: {store_path}")

    return store_path


# ── Step 4: Compare ──────────────────────────────────────────────────────────


def step4_compare(
    canvodpy_store: Path,
    gnssvod_canopy_parquet: Path,
    gnssvod_vod_parquet: Path | None,
) -> AuditResult:
    """Compare canvodpy output against gnssvod.

    Sub-comparisons:
    A. SNR + Azimuth + Elevation (canvodpy vs gnssvod preprocess)
    B. VOD per band (canvodpy vs gnssvod calc_vod) — if available

    Note: gnssvod drops observations with elevation <= -10 deg (hard
    filter), while canvodpy masks below-horizon to NaN. The comparison
    engine aligns on shared (epoch, sid) pairs and computes statistics
    only on mutually valid (non-NaN) values. The nan_rate_atol tolerance
    detects systematic missing-data differences.
    """
    print("\n── Tier 3A: SNR + angles comparison ──")

    result_a = audit_vs_gnssvod(
        canvodpy_store=canvodpy_store,
        gnssvod_file=gnssvod_canopy_parquet,
    )

    result = AuditResult()
    for k, v in result_a.results.items():
        result.results[f"3A_{k}"] = v

    # ── VOD comparison ──
    if gnssvod_vod_parquet is not None and gnssvod_vod_parquet.exists():
        _compare_vod(canvodpy_store, gnssvod_vod_parquet, result)
    else:
        print("\n  No gnssvod VOD output — skipping VOD comparison")

    # ── Save results ──
    try:
        df = result.to_polars()
        stats_path = TIER3_DIR / "tier3_comparison_stats.csv"
        df.write_csv(str(stats_path))
        print(f"\nDetailed stats saved: {stats_path}")
    except Exception as e:
        print(f"\n  Could not save stats: {e}")

    # ── Typst reports ─────────────────────────────────────────────────
    _TIER3_NOTES = [
        "SP3 interpolation methods differ fundamentally: canvodpy uses "
        "scipy CubicHermiteSpline (piecewise cubic, SP3 positions + "
        "velocities); gnssvod uses numpy degree-16 polyfit on 4-hour "
        "windows (positions only, no velocity data). This produces "
        "systematic, reproducible differences in satellite ECEF positions "
        "→ different theta/phi → different Elevation/Azimuth → different "
        "cos(theta) in the VOD formula. All are expected and not bugs.",
        "SNR: canvodpy stores as float32 (~7 significant digits); gnssvod "
        "uses float64. RINEX SNR precision is ~0.001 dB; float32 truncation "
        "introduces max ~2e-6 dB error — 1000x below measurement resolution.",
        "Elevation cutoff: gnssvod drops observations with elevation ≤ -10° "
        "in gnssDataframe(). canvodpy masks below-horizon (< 0°) to NaN but "
        "retains the array positions. The comparison operates on shared "
        "(epoch, SID) pairs only; NaN-rate tolerance accounts for the "
        "systematic cutoff difference.",
        "Bands with 100% NaN on both sides (e.g. L5): vacuously pass — "
        "neither tool produced data for this band, which is expected given "
        "the GPS+Galileo L1+L2 trimming applied before comparison.",
    ]
    report_dir = AUDIT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, r in result.results.items():
        safe_name = name.replace("|", "_").replace(" ", "_")
        report_path = report_dir / f"tier3_{safe_name}.typ"
        try:
            to_typst(
                r,
                title=f"Tier 3: canvodpy vs gnssvod — {name}",
                path=report_path,
                compile=True,
                notes=_TIER3_NOTES,
            )
            print(f"Report → {report_path.with_suffix('.pdf')}")
        except Exception as e:
            print(f"  Could not write report for {name}: {e}")

    return result


def _compare_vod(
    canvodpy_store: Path,
    gnssvod_vod_parquet: Path,
    result: AuditResult,
) -> None:
    """Compare canvodpy VOD against gnssvod calc_vod output.

    Reports full difference statistics (no pass/fail gate on VOD — the
    difference is systematic and explained by different SP3 interpolation
    methods).  Also runs vod_difference_decomposition() to quantify how
    much of the VOD difference is explained by Δcos(θ) vs a true residual.
    """
    from canvod.audit.runners.vs_gnssvod import (
        _VOD_BUDGET_NOTE,
        gnssvod_df_to_xarray,
        print_vod_decomposition,
        vod_difference_decomposition,
    )
    from canvod.audit.stats import (
        VariableBudget,
        compute_diff_report,
        print_diff_report,
    )

    print("\n── Tier 3B: VOD comparison ──")

    ds_canvod = xr.open_zarr(str(canvodpy_store))
    gnssvod_vod_df = pd.read_parquet(gnssvod_vod_parquet)

    print(f"  gnssvod VOD columns: {list(gnssvod_vod_df.columns)}")
    print(f"  gnssvod VOD shape: {gnssvod_vod_df.shape}")
    print(f"  canvodpy vars: {sorted(ds_canvod.data_vars)}")

    if "VOD" not in ds_canvod.data_vars:
        print("  canvodpy has no VOD — skipping VOD comparison")
        return

    # Convert gnssvod VOD DataFrame to xarray
    ds_gnssvod_vod = gnssvod_df_to_xarray(gnssvod_vod_df)
    print(f"  gnssvod VOD xarray: {dict(ds_gnssvod_vod.sizes)}")
    print(f"    vars: {sorted(ds_gnssvod_vod.data_vars)}")

    # canvodpy has one VOD variable; gnssvod has VOD_L1, VOD_L2 per band.
    # Both the gnssvod VOD output and canvodpy store have Elevation/theta
    # so we can run the decomposition: predicted_ΔV from Δcos(θ) vs residual.
    band_mapping = [
        ("VOD_L1", "L1|C"),
        ("VOD_L2", "L2|W"),
    ]

    vod_budget = VariableBudget(
        budget=None,
        unit="",
        source="Different SP3 interp → different cos(θ); see decomposition.",
        note=_VOD_BUDGET_NOTE,
        vod_relevant=True,
    )

    for vod_band, canvod_band_suffix in band_mapping:
        if vod_band not in ds_gnssvod_vod.data_vars:
            print(f"  Skipping {vod_band}: not in gnssvod output")
            continue

        # Select canvodpy SIDs for this band
        matching_sids = [
            s for s in ds_canvod.sid.values if str(s).endswith(f"|{canvod_band_suffix}")
        ]
        if not matching_sids:
            print(
                f"  Skipping {vod_band}: no matching canvodpy SIDs "
                f"for |{canvod_band_suffix}"
            )
            continue

        # Build canvodpy VOD+Elevation dataset with PRN sids (matching gnssvod)
        ds_band = ds_canvod.sel(sid=matching_sids)
        prns = [str(s).split("|")[0] for s in matching_sids]

        data_vars: dict = {vod_band: (["epoch", "sid"], ds_band["VOD"].values)}
        if "theta" in ds_band.data_vars:
            elev_canvod = 90.0 - np.degrees(ds_band["theta"].values)
            data_vars["Elevation"] = (["epoch", "sid"], elev_canvod)

        ds_canvod_vod = xr.Dataset(
            data_vars,
            coords={"epoch": ds_band.epoch.values, "sid": prns},
        )

        # Align on shared (epoch, sid) pairs
        shared_sids = np.intersect1d(
            ds_canvod_vod.sid.values, ds_gnssvod_vod.sid.values
        )
        shared_epochs = np.intersect1d(
            ds_canvod_vod.epoch.values, ds_gnssvod_vod.epoch.values
        )

        if len(shared_sids) == 0 or len(shared_epochs) == 0:
            print(
                f"  Skipping {vod_band}: no shared sids/epochs "
                f"(canvod: {len(ds_canvod_vod.sid)} sids, "
                f"gnssvod: {len(ds_gnssvod_vod.sid)} sids)"
            )
            continue

        print(
            f"\n  {vod_band}: {len(shared_sids)} shared sids, "
            f"{len(shared_epochs)} shared epochs"
        )

        ds_a = ds_canvod_vod.sel(sid=shared_sids, epoch=shared_epochs)
        ds_b = ds_gnssvod_vod.sel(sid=shared_sids, epoch=shared_epochs)

        # Full difference report (budget=None — no gate, just report stats)
        budgets = {vod_band: vod_budget}
        diff_stats = compute_diff_report(
            ds_a,
            ds_b,
            budgets,
            vars_to_check=[vod_band],
            label_a="canvodpy",
            label_b="gnssvod",
        )
        print_diff_report(
            diff_stats,
            f"VOD: {vod_band}",
            label_a="canvodpy",
            label_b="gnssvod",
        )

        # VOD decomposition: how much of ΔV is explained by Δcos(θ)?
        if "Elevation" in ds_a.data_vars and "Elevation" in ds_b.data_vars:
            decomp = vod_difference_decomposition(
                ds_a["Elevation"].values.ravel(),
                ds_b["Elevation"].values.ravel(),
                ds_a[vod_band].values.ravel(),
                ds_b[vod_band].values.ravel(),
            )
            print_vod_decomposition(decomp, vod_band)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 60)
    print("Tier 3: canvodpy vs gnssvod (Humphrey et al.)")
    print(f"Ephemeris: {EPHEMERIS_AGENCY} {EPHEMERIS_PRODUCT}")
    print("=" * 60)

    # Step 1: Trim RINEX
    canopy_trimmed, ref_trimmed = step1_trim_rinex()

    # Step 2: Run gnssvod (full pipeline: preprocess + gather + calc_vod)
    gnssvod_canopy, gnssvod_vod = step2_run_gnssvod(canopy_trimmed, ref_trimmed)

    # Step 3: Run canvodpy (uses same GFZ rapid SP3/CLK)
    canvodpy_store = step3_run_canvodpy(canopy_trimmed, ref_trimmed)

    # Step 4: Compare (A: SNR+angles, B: VOD)
    result = step4_compare(canvodpy_store, gnssvod_canopy, gnssvod_vod)

    print("\n" + "=" * 60)
    if result.passed:
        print("TIER 3 PASSED")
    else:
        print("TIER 3: SOME COMPARISONS FAILED — review above output")
        for name, r in result.results.items():
            if not r.passed:
                print(f"\n{name}:")
                for var, reason in r.failures.items():
                    print(f"  {var}: {reason}")
    print("=" * 60)


if __name__ == "__main__":
    main()
