#!/usr/bin/env python3
"""Integration test to verify SID filtering works.

This test is skipped in CI environments where config files are not available.
"""

from pathlib import Path

import pytest

# Check if config files and store paths are available
CONFIG_DIR = Path.cwd() / "config"
HAS_CONFIG = (CONFIG_DIR / "sites.yaml").exists()

# Store root from processing.yaml — guard against missing external drives
_STORE_ROOT = Path("/Volumes/SanDisk/GNSS/ComparedStores/canvodpy_new_API")
HAS_STORE = _STORE_ROOT.exists()


@pytest.mark.integration
@pytest.mark.skipif(
    not (HAS_CONFIG and HAS_STORE),
    reason="Integration test requires config files and store directory",
)
def test_sid_filtering_integration():
    """Test SID filtering with full orchestrator."""
    print("=" * 80, flush=True)
    print("SID FILTERING TEST", flush=True)
    print("=" * 80, flush=True)

    print("\n1. Importing modules...", flush=True)
    from canvod.store import GnssResearchSite
    from canvodpy.globals import KEEP_RNX_VARS
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    print(f"   KEEP_RNX_VARS = {KEEP_RNX_VARS}", flush=True)

    print("\n2. Initializing site...", flush=True)
    site = GnssResearchSite(site_name="Rosalia")
    print(f"   Site: {site.site_name}", flush=True)

    print("\n3. Creating orchestrator...", flush=True)
    orchestrator = PipelineOrchestrator(site=site, dry_run=False)
    print("   Orchestrator created", flush=True)

    print("\n4. Starting processing loop (processing first date only)...", flush=True)
    counter = 0
    for date_key, _datasets, _receiver_times in orchestrator.process_by_date(
        keep_vars=KEEP_RNX_VARS, start_from=None, end_at=None
    ):
        print(f"\n   ✅ Processed date: {date_key}", flush=True)
        counter += 1
        if counter >= 1:  # Only process first date
            print("   Stopping after first date for testing", flush=True)
            break

    print("\n" + "=" * 80, flush=True)
    print("✅ TEST COMPLETE - NO ERRORS!", flush=True)
    print("=" * 80, flush=True)

    # Test assertions
    assert counter == 1, "Should have processed exactly one date"


if __name__ == "__main__":
    # Allow running as script for local testing
    import sys

    try:
        if not HAS_CONFIG:
            print("⚠️  Skipping: Config files not found")
            sys.exit(0)
        test_sid_filtering_integration()
    except Exception as e:
        print(f"\n❌ ERROR: {e}", flush=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)
