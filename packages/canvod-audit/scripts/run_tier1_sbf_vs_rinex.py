"""Tier 1: SBF vs RINEX — internal consistency comparison.

Compares canvodpy stores produced from SBF and RINEX files recorded by
the same receiver during the same observation session. Both use agency
(final) ephemeris for satellite coordinate computation.

Background: structural differences between SBF and RINEX
---------------------------------------------------------
SBF (Septentrio Binary Format) and RINEX 3 represent the same physical
observables but differ in structure, time reference, quantization, and
information density.  The differences documented below are grounded in
the Septentrio AsteRx SB3 ProBase Firmware Reference Guide (v4.14.0 and
v4.15.1) and the RINEX 3.04 standard.

**Signal structure**

SBF uses a two-level hierarchical sub-block structure within the
MeasEpoch block (ID 4027): the MeasEpochChannelType1 sub-block carries
the "master" signal with absolute measurements, while nested
MeasEpochChannelType2 sub-blocks encode slave signals (e.g. L2, L5) as
delta offsets relative to the master.  This compression reduces block
size but requires reconstruction at decode time.  RINEX lists every
signal independently in a flat structure — each SID has its own
observation record with no interdependency (RefGuide-4.14.0, p.262–264;
RINEX 3.04 §5.1).

**Satellite identification**

SBF identifies satellites with a numeric SVID (u1, range 1–245) where
constellation is implied by the SVID range: 1–37 GPS, 38–70 GLONASS,
71–106 Galileo, 141–180 BeiDou, etc.  RINEX uses a single-letter
constellation prefix (G/R/E/C/J/I/S) followed by a two-digit PRN.  The
canvodpy reader normalises both to the internal SID format
``SV|Band|Code`` (RefGuide-4.14.0, §4.1.10 p.256).

**Observable precision and quantization**

All four core observables (pseudorange, carrier phase, Doppler, C/N0)
are present in both formats, but their resolution differs:

  Observable       SBF MeasEpoch          RINEX 3 (F14.3)
  ─────────────────────────────────────────────────────────
  Pseudorange      1 mm (10⁻³ m/LSB)      1 mm
  Carrier phase    0.001 cycles            0.001 cycles
  Doppler          0.1 mHz (10⁻⁴ Hz/LSB)  1 mHz
  C/N0 (standard) 0.25 dB-Hz              0.001 dB-Hz

The SNR quantization difference is the dominant source of disagreement
in this tier.  SBF MeasEpoch encodes C/N0 as a u1 field with
0.25 dB-Hz steps (RefGuide-4.14.0, p.264).  RINEX uses the F14.3
decimal format, giving 0.001 dB-Hz precision.  When the Septentrio RINEX
converter uses MeasExtra (Block 4000), it can apply the CN0HighRes
sub-field (bits 0–2, scale 1/32 dB-Hz/LSB) to improve resolution to
0.03125 dB-Hz before writing the RINEX S observable (RefGuide-4.14.0,
MeasExtra p.265).  The canvodpy SBF reader applies the same CN0HighRes
correction automatically when MeasExtra is present.

**Do-Not-Use handling**

SBF signals missing or invalid data using specific numeric sentinel
values (e.g. CN0=255, Doppler=−2³¹, CodeMSB=CodeLSB=0 for pseudorange).
These are converted to NaN by the reader.  RINEX leaves missing fields
blank.  The two representations are equivalent after decoding but produce
differences in NaN coverage depending on which signals each format
omits.

**Epoch timestamping**

SBF MeasEpoch records observations at the receiver's internal clock
ticks (Receiver Time, t_Rx), which are exact multiples of the logging
interval in the receiver time scale.  The offset from GNSS System Time
is the receiver clock bias: RxClkBias = t_Rx − t_GNSS.  In free-running
mode the firmware applies 1 ms clock jumps whenever |RxClkBias| exceeds
the synchronization threshold (default ±0.5 ms), keeping the offset
within ±0.5 ms (RefGuide-4.14.0, ReceiverTime block p.369).

The Septentrio RINEX converter (sbf2rin) maps each measurement to the
nearest nominal GNSS grid epoch and can interpolate observables to the
exact integer epoch to account for the sub-millisecond RxClkBias.  The
result is that RINEX timestamps are always on the nominal grid (:00, :05,
:10, … for 5 s data) while SBF timestamps reflect the true receiver
ticks (:02, :07, :12, …), producing a systematic ~2 s apparent offset
with an underlying 1-to-1 epoch correspondence.

**Information exclusive to SBF**

SBF provides several quality and context fields absent from the RINEX
observation format.  These are extracted by canvodpy into the ``sbf_obs``
metadata dataset (written alongside the obs store):

  - MeasExtra (Block 4000): pseudorange multipath correction
    (MPCorrection, i2, 1 mm/LSB), Hatch-filter smoothing correction
    (SmoothingCorr, i2, 1 mm/LSB), code and carrier tracking noise
    variances (CodeVar, CarrierVar), carrier multipath correction
    (CarMPCorr, i1, 1/512 cycles/LSB), lock time (LockTime, u2, s),
    and loss-of-continuity counter (CumLossCont, u1) — all on p.265.
  - PVTGeodetic (Block 4007): receiver position, velocity, number of
    tracked satellites, horizontal/vertical accuracy, correction age.
  - DOP (Block 4001): PDOP, HDOP, VDOP dilution-of-precision values.
  - SatVisibility (Block 4012): satellite azimuth (u2) and elevation
    (i2), scale 0.01 °/LSB — used as broadcast geometry for the
    SBF-geometry fast path.
  - ReceiverStatus (Block 4014): CPU load, internal temperature
    (u1, raw − 100 °C), receiver error flags.

Why SBF and RINEX stores are never identical
---------------------------------------------
The RINEX file compared here was produced by the Septentrio sbf2rin
converter directly from the same SBF binary that feeds the SBF store.
Despite having a common source, the two stores differ systematically for
every observable.  The reasons are documented below from the firmware
reference guides and verified via NotebookLM against the PDFs.

**Epoch: receiver time vs. GNSS system time + observable interpolation**

SBF MeasEpoch records each observation at the receiver's internal clock
tick (Receiver Time, t_Rx).  sbf2rin converts timestamps to GNSS System
Time using the RxClkBias stored in PVTGeodetic/PVTCartesian (Block 4007/
4006): t_GNSS = t_Rx - RxClkBias (RefGuide-4.14.0, p.337–339).  It then
places each observation on the nearest nominal grid epoch (:00, :05, :10
for 5 s data) and INTERPOLATES all observables (pseudorange, phase,
Doppler) to that exact GNSS epoch using the Doppler measurement to
account for the sub-millisecond clock offset.

The canvodpy SBF reader does none of this — it preserves the raw
receiver-time ticks (:02, :07, :12, …) and the raw, uninterpolated
observable values.  Consequently:

  - Epoch coordinates differ by the RxClkBias (~0–2 ms true offset;
    apparent ~2 s artefact from 1 ms clock-jump synchronization).
  - Observable values differ by the amount Doppler×RxClkBias, which
    is deterministic and small but non-zero.

When the receiver is in free-running mode, firmware applies 1 ms clock
jumps (CumClkJumps in MeasEpoch) whenever |RxClkBias| exceeds the ±0.5 ms
threshold (RefGuide-4.14.0, p.262).  Each jump causes a ~300 km step in
raw SBF pseudoranges (299,792.458 m per ms) and a phase discontinuity.
sbf2rin removes these artefacts by subtracting RxClkBias from all
measurements; the canvodpy SBF reader does not.  These jumps are visible
as systematic outliers in the SBF store pseudorange and phase but do not
affect SNR (the only VOD observable).

**SNR: identical if MeasExtra present; 0.25 dB-Hz steps otherwise**

sbf2rin applies the same CN0HighRes correction as canvodpy:
  SNR_RINEX = CN0_MeasEpoch × 0.25 (+ 10 for non-P signals)
              + CN0HighRes × 0.03125
where CN0HighRes comes from MeasExtra.Misc bits 0–2 (RefGuide-4.14.0,
p.265).  The RINEX S observable is written with F14.3 precision
(0.001 dB-Hz).

If MeasExtra was logged: both stores agree to 0.03125 dB-Hz; any
residual difference is F14.3 rounding (< 0.001 dB-Hz).
If MeasExtra was absent: both stores show the 0.25 dB-Hz staircase.
In practice SNR is the closest-agreement observable between the two
stores — it is also the only one that matters for VOD.

**Pseudorange: same firmware-processed value, but clock-jump artefacts**

sbf2rin writes the MeasEpoch pseudorange directly (the firmware-processed
value including Hatch smoothing and multipath mitigation) and does NOT
undo MPCorrection or SmoothingCorr from MeasExtra (RefGuide-4.14.0,
p.265).  The canvodpy reader likewise writes the same MeasEpoch value.
So the stored pseudoranges start from the same raw field.  However,
sbf2rin subtracts RxClkBias×c to convert to GNSS-referenced range and
removes clock-jump artefacts; canvodpy does not.  The result is:
pseudoranges can differ by up to ~300 km at clock-jump epochs and by a
smaller but systematic Doppler-scaled interpolation delta at every epoch.
Pseudorange is not used for VOD.

**Carrier phase: same value at source, but interpolation and clock jumps**

sbf2rin writes the mitigated carrier phase from MeasEpoch and does NOT
undo CarMPCorr (RefGuide-4.14.0, p.265).  The canvodpy reader does the
same.  However, sbf2rin interpolates phase to the nominal GNSS epoch
using Doppler: Phase_RINEX = Phase_SBF + Doppler × RxClkBias.  This
changes the fractional cycle value by a deterministic amount but
preserves integer cycle count.  Clock jumps are also removed (a 1 ms
jump corresponds to f×0.001 cycles, ~1575 cycles for GPS L1).
Phase is not used for VOD.

**Doppler: factor-10 resolution loss in RINEX**

SBF encodes Doppler as an i4 with 0.0001 Hz resolution (0.1 mHz/LSB,
RefGuide-4.14.0, p.263).  sbf2rin maps this to the RINEX Dx observable
at 0.001 Hz precision (F14.3), discarding the sub-mHz digit.  The
canvodpy reader preserves full 0.0001 Hz resolution.  Every Doppler
value in the RINEX store is therefore rounded to the nearest mHz
relative to the SBF store, producing a uniform quantization difference
of up to 0.5 mHz.  Doppler is not used for VOD.

**NaN coverage: SBF may have fewer signals per epoch**

SBF Type2 sub-blocks encode slave signals as deltas relative to the
master.  If a slave sub-block is absent, that signal produces NaN in
the SBF store.  RINEX lists each signal independently; the converter
may recover signals that the Type2 path drops or vice versa.  Typical
discrepancy is ≤ ~5% of observations.

NotebookLM verification (2026-03-26)
--------------------------------------
The three claims above were verified by querying NotebookLM against the
Septentrio AsteRx SB3 ProBase Firmware Reference Guides (v4.14.0 and
v4.15.1) and the Septentrio RxTools Manual v1.10.0 (NOAA geodesy archive,
https://geodesy.noaa.gov/pub/abilich/antcalCorbin/RxTools_Manual_v1.10.0.pdf).
All three findings were confirmed with explicit page citations:

(1) sbf2rin applies t_GNSS = t_Rx − RxClkBias (RefGuide-4.14.0
    §4.2.9–4.2.10, p.337; RxTools Manual v1.10.0 §11.8.2, p.158) and
    interpolates pseudorange and carrier phase to the nominal GNSS grid
    using Doppler×RxClkBias to correct for the sub-millisecond clock
    offset.  canvodpy stores raw receiver-time values without this
    correction.  A direct numerical comparison of PR or phase between
    the two stores is therefore meaningless — differences are structural,
    not indicative of any reader bug.

(2) sbf2rin removes 1 ms clock-jump artefacts (tracked in CumClkJumps,
    MeasEpoch Block 4027, RefGuide-4.14.0 p.262).  Each jump causes a
    simultaneous 299,792.458 m step in all pseudoranges and a
    corresponding phase step (f × 0.001 cycles, ~1575 cycles at GPS L1).
    sbf2rin eliminates these by converting to GNSS System Time; the raw
    SBF store preserves them as systematic outliers.

(3) C/N₀ is a power ratio, not a time-of-flight measurement.  The
    firmware documentation is explicit: the 1 ms clock jump (and all
    RxClkBias corrections) affects only range-dependent observables.
    sbf2rin does NOT interpolate C/N₀ for RxClkBias.  It applies the
    CN0HighRes enhancement from MeasExtra.Misc bits 0–2 (scale
    0.03125 dB-Hz/LSB, RefGuide-4.14.0 p.265) — identically to
    canvodpy — and then writes the value directly to the RINEX S
    observable with F14.3 precision.  No other transformation is applied.

Conclusion: SNR is the only SBF/RINEX observable where a direct
numerical comparison is scientifically valid.  It is also the only
observable that enters the VOD computation.  Tier 1a therefore restricts
its pass/fail criterion to SNR; pseudorange, carrier phase, and Doppler
are reported for information only with explicitly relaxed (or no) numeric
tolerances.

Epoch grid relationship
-----------------------
SBF epoch coordinates are receiver-time ticks (:02, :07, :12, …).
RINEX epoch coordinates are nominal GNSS-time grid (:00, :05, :10, …).
The correspondence is 1-to-1 by position; the apparent ~2 s offset is
an artefact of the receiver's ±0.5 ms clock-jump synchronization
(RefGuide-4.14.0, ReceiverTime p.369, PVTGeodetic p.337).

Comparison strategy: positional reindexing
------------------------------------------
Because the epoch grids are systematically offset (not randomly
misaligned), the correct comparison is positional:

    SBF observation [N]  ←→  RINEX observation [N]

We assign the RINEX epoch coordinates to the SBF dataset by position
so that ``compare_datasets`` sees a shared epoch axis.  We do NOT
attempt nearest-neighbour timestamp matching — that would obscure the
known offset and suggest a spurious correction.

If the two stores differ in epoch count (typically ≤ a handful of
boundary epochs), both are trimmed to the shorter length from the start
of the session.

Expected differences
--------------------
- SNR: negligible when MeasExtra present (< 0.001 dB-Hz F14.3 rounding);
  up to 0.25 dB-Hz when absent.  SNR is the VOD observable — this is
  the critical tolerance.
- Doppler: uniform ≤ 0.5 mHz quantization offset (RINEX F14.3 rounding).
  Not used for VOD.
- Pseudorange/Phase: non-trivial — clock-jump artefacts (~300 km per
  1 ms jump) and Doppler×RxClkBias interpolation delta at every epoch.
  Not used for VOD.
- phi/theta: sub-arcsecond FP noise only (same SP3/CLK, same code path).
- NaN rates: may differ ≤ ~5% (Type1/Type2 signal coverage vs. flat
  RINEX listing).

References
----------
- Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide:
  MeasEpoch (Block 4027) pp.261–264, MeasExtra (Block 4000) p.265,
  PVTGeodetic (Block 4007) pp.337–339, DOP (Block 4001) p.349,
  SatVisibility (Block 4012) p.400, ReceiverStatus (Block 4014)
  pp.396–399, ReceiverTime (Block 5914) p.369.
- Septentrio AsteRx SB3 ProBase Firmware v4.15.1 Reference Guide.
- Septentrio RxTools Manual v1.10.0, §11.8.2 (sbf2rin, p.158):
  https://geodesy.noaa.gov/pub/abilich/antcalCorbin/RxTools_Manual_v1.10.0.pdf
- RINEX 3.04 Observation Data File specification, IGS/RTCM-SC104.

Stores required
---------------
SBF_STORE  : ``tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store``
    Produced by ``produce_sbf_store_final.py``

RINEX_STORE: ``tier0_rinex_vs_gnssvodpy/Rosalia/canvodpy_RINEX_store``
    Reused from Tier 0 — produced by ``produce_canvodpy_store.py``
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from canvod.audit.core import compare_datasets
from canvod.audit.reporting.typst import to_typst
from canvod.audit.runners.common import load_group, open_store
from canvod.audit.runners.sbf_vs_rinex import (
    FORMAL_VARS,
    SBF_RINEX_TOLERANCES,
    compute_diff_stats,  # type: ignore[unresolved-import]
    print_diff_report,
)
from canvod.audit.tolerances import ToleranceTier

AUDIT_ROOT = Path(
    os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
)

# ── Store paths ──────────────────────────────────────────────────────────
SBF_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store"
RINEX_STORE = AUDIT_ROOT / "tier0_rinex_vs_gnssvodpy/Rosalia/canvodpy_RINEX_store"

GROUPS = ["canopy_01", "reference_01_canopy_01"]
REPORT_DIR = AUDIT_ROOT / "reports"


def reindex_sbf_to_rinex(ds_sbf, ds_rnx):
    """Reindex SBF epochs to RINEX epoch coordinates by position.

    The Septentrio RINEX converter derives RINEX from SBF by
    re-stamping each raw measurement to the nearest nominal 5-s grid
    epoch.  The offset is constant (~2 s) and the correspondence is
    purely positional: SBF[N] and RINEX[N] represent the same physical
    observation.

    We therefore assign RINEX epoch coordinates to the SBF dataset by
    position, giving both datasets a shared epoch axis for comparison.
    No nearest-neighbour matching is performed.

    If the stores differ in epoch count, both are trimmed to the shorter
    length (boundary epochs only; this is normal for daily sessions).

    Returns
    -------
    ds_sbf_reindexed : xr.Dataset
        SBF data with RINEX epoch coordinates assigned.
    ds_rnx_trimmed : xr.Dataset
        RINEX data trimmed to the same length.
    stats : dict
        n_sbf, n_rnx, n_used, offset_mean_s (mean RINEX − SBF offset).
    """
    n_sbf = len(ds_sbf.epoch)
    n_rnx = len(ds_rnx.epoch)
    n = min(n_sbf, n_rnx)

    ds_sbf_trimmed = ds_sbf.isel(epoch=slice(None, n))
    ds_rnx_trimmed = ds_rnx.isel(epoch=slice(None, n))

    # Compute the actual epoch offset for the record
    sbf_ns = ds_sbf_trimmed.epoch.values.astype("int64")
    rnx_ns = ds_rnx_trimmed.epoch.values.astype("int64")
    offsets_s = (rnx_ns - sbf_ns) / 1e9

    # Assign RINEX epoch coordinates to the (trimmed) SBF dataset
    ds_sbf_reindexed = ds_sbf_trimmed.assign_coords(epoch=ds_rnx_trimmed.epoch.values)

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


def main() -> None:
    s_sbf = open_store(SBF_STORE)
    s_rnx = open_store(RINEX_STORE)

    for group in GROUPS:
        print("=" * 60)
        print(f"SBF vs RINEX: {group}")
        print("=" * 60)

        ds_sbf = load_group(s_sbf, group)
        ds_rnx = load_group(s_rnx, group)

        print(f"SBF:   {dict(ds_sbf.sizes)}, vars={list(ds_sbf.data_vars)}")
        print(f"RINEX: {dict(ds_rnx.sizes)}, vars={list(ds_rnx.data_vars)}")

        # ── Show raw epoch grids for information ─────────────────────────
        sbf_epochs = pd.DatetimeIndex(ds_sbf.epoch.values)
        rnx_epochs = pd.DatetimeIndex(ds_rnx.epoch.values)
        print(f"\nSBF first 3:   {[str(e) for e in sbf_epochs[:3]]}")
        print(f"RINEX first 3: {[str(e) for e in rnx_epochs[:3]]}")
        print(
            f"Exact shared (for info only): {len(np.intersect1d(sbf_epochs, rnx_epochs))}"
        )

        # ── Positional reindex ───────────────────────────────────────────
        ds_sbf_reindexed, ds_rnx_trimmed, ri_stats = reindex_sbf_to_rinex(
            ds_sbf, ds_rnx
        )
        print(
            f"\nPositional reindex: using {ri_stats['n_used']}/{ri_stats['n_sbf']} SBF and "
            f"{ri_stats['n_used']}/{ri_stats['n_rnx']} RINEX epochs"
        )
        print(
            f"Epoch offset (RINEX - SBF): "
            f"mean={ri_stats['offset_mean_s']:.3f}s "
            f"std={ri_stats['offset_std_s']:.3f}s "
            f"[{ri_stats['offset_min_s']:.3f}, {ri_stats['offset_max_s']:.3f}]s"
        )

        # ── Full observable difference report ────────────────────────────
        # All variables, actual numbers, annotated against physical budget.
        # Nothing is suppressed — differences are reported and classified.
        diff_stats = compute_diff_stats(ds_sbf_reindexed, ds_rnx_trimmed)
        print_diff_report(diff_stats, group)

        # ── Formal pass/fail gate (bounded-budget variables) ─────────────
        # Gate on SNR + geometry.  PR and Phase are excluded because their
        # differences are large, structurally explained (sbf2rin clock
        # correction), and irrelevant to VOD — but they ARE reported above.
        r = compare_datasets(
            ds_sbf_reindexed,
            ds_rnx_trimmed,
            variables=FORMAL_VARS,
            tier=ToleranceTier.SCIENTIFIC,
            tolerance_overrides=SBF_RINEX_TOLERANCES,
            label=f"SBF vs RINEX: {group}",
        )

        print(f"\nFormal verdict (SNR + geometry): passed={r.passed}")
        if r.failures:
            print(f"  Failures: {r.failures}")
        for vname, vs in r.variable_stats.items():
            print(
                f"  {vname}: max_abs={vs.max_abs_diff:.6g}, "
                f"bias={vs.bias:.6g}, n={vs.n_compared}"
            )

        exceeding = [s for s in diff_stats if s.exceeds_budget]
        if exceeding:
            print(
                "\n  *** BUDGET EXCEEDED: "
                + ", ".join(
                    f"{s.var} (max={s.max_abs:.6g} {s.budget_unit}, "
                    f"budget={s.budget} {s.budget_unit})"
                    for s in exceeding
                )
            )

        # ── Typst report ─────────────────────────────────────────────────
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"tier1_sbf_vs_rinex_{group}.typ"
        to_typst(
            r,
            title=f"Tier 1a: SBF vs RINEX — {group}",
            path=report_path,
            compile=True,
            notes=[
                "SBF and RINEX are produced by the same Septentrio receiver from the "
                "same observation session. SBF preserves raw measurement timestamps "
                "(Receiver Time); Septentrio's sbf2rin converter re-stamps each "
                "observation to the nearest nominal GNSS grid epoch (t_GNSS = t_Rx − "
                "RxClkBias, RefGuide-4.14.0 p.337; RxTools Manual v1.10.0 §11.8.2 "
                "p.158), introducing a constant ~2 s shift. Epochs are matched by "
                "position (SBF[N] ↔ RINEX[N]), not by timestamp proximity. Observed "
                f"offset for this group: {ri_stats['offset_mean_s']:.2f} ± "
                f"{ri_stats['offset_std_s']:.3f} s.",
                "SNR (formal, pass/fail): Both sbf2rin and canvodpy apply the "
                "identical CN0HighRes correction (MeasExtra.Misc bits 0–2, "
                "0.03125 dB-Hz/LSB, RefGuide-4.14.0 p.265). C/N₀ is a power ratio "
                "unaffected by clock-bias corrections. Expected agreement < 0.001 "
                "dB-Hz (F14.3 rounding); tolerance = 0.032 dB-Hz (1 CN0HighRes LSB). "
                "Verified via NotebookLM against firmware PDFs, 2026-03-26.",
                "Pseudorange, Phase, Doppler (informational only, excluded from "
                "pass/fail): sbf2rin applies RxClkBias correction, removes 1 ms "
                "clock-jump artefacts (~300 km in PR, ~1575 cycles in GPS L1 phase), "
                "and truncates Doppler to F14.3 (≤ 0.5 mHz rounding). canvodpy "
                "preserves the raw SBF values. Differences are structural, not bugs.",
                "phi/theta: both stores use identical SP3/CLK agency products "
                "(COD final) and the same CubicHermiteSpline interpolation. "
                "Differences are sub-arcsecond floating-point noise only.",
            ],
        )
        print(f"\nReport → {report_path.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
