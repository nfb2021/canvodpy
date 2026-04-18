"""Tier 1: Broadcast vs agency ephemeris — internal consistency comparison.

Compares canvodpy SBF stores produced with broadcast ephemeris (from SBF
SatVisibility records) vs agency final products (SP3/CLK from CODE).
Both stores use the same SBF input files.

Expected differences
--------------------
- SNR: identical (ephemeris source does not affect raw observables)
- phi/theta: ~0.001-0.01 deg differences from ~1-2 m orbit accuracy
  difference between broadcast and final products
- NaN rates may differ: broadcast and SP3 cover different satellite sets

Stores required
---------------
BROADCAST_STORE: ``tier1_broadcast_vs_agency/Rosalia/canvodpy_SBF_broadcast_store``
    Produced by ``produce_sbf_store_broadcast.py``
    (config: sbf input, ephemeris_source: broadcast,
     stores_root_dir: tier1_broadcast_vs_agency,
     rinex_store_name: canvodpy_SBF_broadcast_store)

AGENCY_STORE   : ``tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store``
    Produced by ``produce_sbf_store_final.py``
    (config: sbf input, ephemeris_source: final,
     stores_root_dir: tier1_sbf_vs_rinex,
     rinex_store_name: canvodpy_SBF_store)

Prerequisites
-------------
1. SBF agency store from ``produce_sbf_store_final.py``
2. SBF broadcast store from ``produce_sbf_store_broadcast.py``
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from canvod.audit.core import compare_datasets
from canvod.audit.reporting.typst import to_typst
from canvod.audit.runners.common import load_group, open_store
from canvod.audit.runners.ephemeris import DEFAULT_VARIABLES, EPHEMERIS_TOLERANCES
from canvod.audit.tolerances import ToleranceTier

AUDIT_ROOT = Path(
    os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
)

# ── Store paths ──────────────────────────────────────────────────────────
BROADCAST_STORE = (
    AUDIT_ROOT / "tier1_broadcast_vs_agency/Rosalia/canvodpy_SBF_broadcast_store"
)
AGENCY_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store"

GROUPS = ["canopy_01", "reference_01_canopy_01"]
REPORT_DIR = AUDIT_ROOT / "reports"


def main() -> None:
    s_broad = open_store(BROADCAST_STORE)
    s_agency = open_store(AGENCY_STORE)

    for group in GROUPS:
        print("=" * 60)
        print(f"Broadcast vs Agency: {group}")
        print("=" * 60)

        ds_broad = load_group(s_broad, group)
        ds_agency = load_group(s_agency, group)

        print(f"Broadcast: {dict(ds_broad.sizes)}, vars={list(ds_broad.data_vars)}")
        print(f"Agency:    {dict(ds_agency.sizes)}, vars={list(ds_agency.data_vars)}")

        # ── Formal comparison at APPROXIMATE tier ──────────────────────
        r = compare_datasets(
            ds_broad,
            ds_agency,
            tier=ToleranceTier.SCIENTIFIC,
            variables=DEFAULT_VARIABLES,
            tolerance_overrides=EPHEMERIS_TOLERANCES,
            label=f"Broadcast vs Agency: {group}",
        )

        print(f"\nPassed: {r.passed}")
        print(f"Alignment: {r.alignment}")
        print(f"Failures: {r.failures}")
        for vname, vs in r.variable_stats.items():
            print(
                f"  {vname}: rmse={vs.rmse:.6g}, max_abs={vs.max_abs_diff:.6g}, "
                f"bias={vs.bias:.6g}, nan_agree={vs.nan_agreement_rate:.6f}, "
                f"n_compared={vs.n_compared}"
            )

        # ── Typst report ──────────────────────────────────────────────
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"tier1_broadcast_vs_agency_{group}.typ"
        to_typst(
            r,
            title=f"Tier 1b: Broadcast vs Agency Ephemeris — {group}",
            path=report_path,
            compile=True,
            notes=[
                "Both stores use the same SBF input files. Only the ephemeris "
                "source differs: broadcast (SBF SatVisibility records, real-time, "
                ") vs agency final (COD SP3/CLK, some days "
                "latency).",
                "SNR is independent of ephemeris and must be identical. Any "
                "difference would indicate a reader bug.",
                "phi/theta differences reflect the real orbit accuracy "
                "difference between broadcast and final products. These are "
                "expected and not a bug. The question is whether they are large "
                "enough to cause downstream issues for canvodpy users",
            ],
        )
        print(f"\nReport → {report_path.with_suffix('.pdf')}")

        # ── Deep dive per variable ─────────────────────────────────────
        print(f"\n--- {group} deep dive ---")
        shared_epochs = np.intersect1d(ds_broad.epoch.values, ds_agency.epoch.values)
        shared_sids = np.intersect1d(ds_broad.sid.values, ds_agency.sid.values)
        print(f"Shared: {len(shared_epochs)} epochs, {len(shared_sids)} sids")

        b = ds_broad.sel(epoch=shared_epochs, sid=shared_sids)
        a = ds_agency.sel(epoch=shared_epochs, sid=shared_sids)

        for var in ["SNR", "Doppler", "Phase", "Pseudorange", "phi", "theta"]:
            bv = b[var].values
            av = a[var].values
            both_valid = ~np.isnan(bv) & ~np.isnan(av)
            diff = bv[both_valid] - av[both_valid]
            nonzero = int(np.sum(np.abs(diff) > 0))
            total = len(diff)
            pct = f"({100 * nonzero / total:.2f}%)" if total > 0 else "(no data)"
            print(f"\n{var}: {nonzero}/{total} non-zero {pct}")
            if nonzero > 0:
                absdiff = np.abs(diff[np.abs(diff) > 0])
                unit = "rad" if var in ("phi", "theta") else ""
                print(f"  max={np.max(absdiff):.8f} {unit}")
                print(f"  mean={np.mean(absdiff):.8f} {unit}")
                print(
                    f"  p50={np.percentile(absdiff, 50):.8f} {unit}, "
                    f"  p99={np.percentile(absdiff, 99):.8f} {unit}"
                )
                if var in ("phi", "theta"):
                    print(
                        f"  (in deg: max={np.degrees(np.max(absdiff)):.4f}°, "
                        f"mean={np.degrees(np.mean(absdiff)):.4f}°, "
                        f"p99={np.degrees(np.percentile(absdiff, 99)):.4f}°)"
                    )

            # NaN coverage
            broad_valid = int(np.sum(~np.isnan(bv)))
            agency_valid = int(np.sum(~np.isnan(av)))
            print(f"  Valid cells: broadcast={broad_valid}, agency={agency_valid}")


if __name__ == "__main__":
    main()
