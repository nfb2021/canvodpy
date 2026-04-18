"""Tier 2: Freeze current stores as regression checkpoints.

Run this once when you have a known-good set of outputs (e.g. after
passing Tier 0 + Tier 1).  The checkpoints are NetCDF files stored
alongside the audit output.

Stores frozen
-------------
tier0_rinex     : ``tier0_rinex_vs_gnssvodpy/Rosalia/canvodpy_RINEX_store``
                  (produce_canvodpy_store.py, rinex input, final ephemeris)
tier0_vod       : ``tier0_rinex_vs_gnssvodpy/Rosalia/canvodpy_VOD_store``
                  (produce_vod_store.py, from the RINEX store above)
tier1_sbf_agency: ``tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store``
                  (produce_sbf_store_final.py, sbf input, final ephemeris)
tier1_sbf_broadcast: ``tier1_broadcast_vs_agency/Rosalia/canvodpy_SBF_broadcast_store``
                  (produce_sbf_store_broadcast.py, sbf input, broadcast ephemeris)

Prerequisites
-------------
1. Tier 0 RINEX store: ``produce_canvodpy_store.py``
2. Tier 0 VOD store: ``produce_vod_store.py``
3. Tier 1a SBF agency store: ``produce_sbf_store_final.py``
4. Tier 1b SBF broadcast store: ``produce_sbf_store_broadcast.py``
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from canvod.audit.runners.regression import freeze_checkpoint

# ── Configuration ────────────────────────────────────────────────────────────

AUDIT_ROOT = Path(
    os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
)
CHECKPOINT_DIR = AUDIT_ROOT / "tier2_checkpoints"

VERSION = "0.1.0"

STORES = {
    # (store_path, groups_to_freeze)
    "tier0_rinex": (
        AUDIT_ROOT / "tier0_rinex_vs_gnssvodpy" / "Rosalia" / "canvodpy_RINEX_store",
        ["canopy_01", "reference_01_canopy_01"],
    ),
    "tier0_vod": (
        AUDIT_ROOT / "tier0_rinex_vs_gnssvodpy" / "Rosalia" / "canvodpy_VOD_store",
        ["canopy_01_vs_reference_01"],
    ),
    "tier1_sbf_agency": (
        AUDIT_ROOT / "tier1_sbf_vs_rinex" / "Rosalia" / "canvodpy_SBF_store",
        ["canopy_01", "reference_01_canopy_01"],
    ),
    "tier1_sbf_broadcast": (
        AUDIT_ROOT
        / "tier1_broadcast_vs_agency"
        / "Rosalia"
        / "canvodpy_SBF_broadcast_store",
        ["canopy_01", "reference_01_canopy_01"],
    ),
}


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def main() -> None:
    git_hash = _git_hash()
    now = datetime.now(UTC).isoformat(timespec="seconds")

    metadata = {
        "git_hash": git_hash,
        "frozen_at": now,
        "note": "Post Tier 0 + Tier 1 baseline",
    }

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Freezing checkpoints to {CHECKPOINT_DIR}")
    print(f"  version={VERSION}, git={git_hash}, date={now}")
    print()

    for label, (store_path, groups) in STORES.items():
        if not store_path.exists():
            print(f"SKIP {label}: store not found at {store_path}")
            continue

        sub_dir = CHECKPOINT_DIR / label
        for group in groups:
            print(f"── {label} / {group} ──")
            freeze_checkpoint(
                store=str(store_path),
                group=group,
                output_dir=str(sub_dir),
                version=VERSION,
                metadata=metadata,
            )
            print()

    print("Done. Run run_tier2_regression.py after code changes to verify.")


if __name__ == "__main__":
    main()
