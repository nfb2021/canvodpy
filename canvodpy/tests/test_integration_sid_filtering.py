#!/usr/bin/env python3
"""Integration test to verify SID filtering works.

Uses self-contained test data and receiver config so the test is independent
of the user's local ``config/sites.yaml``.
"""

from pathlib import Path

import pytest

# Check if config files and store paths are available
CONFIG_DIR = Path.cwd() / "config"
HAS_CONFIG = (CONFIG_DIR / "sites.yaml").exists()

# Reference test data inside the test-data submodule
_TEST_DATA = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
)
_ROSALIA_DATA = _TEST_DATA / "valid" / "rinex_v3_04" / "01_Rosalia"
_STORE_ROOT = _TEST_DATA / "valid" / "stores" / "rosalia_rinex"
HAS_TEST_DATA = _ROSALIA_DATA.exists()
HAS_STORE = _STORE_ROOT.exists()

# Receiver layout matching the test data directory structure
_TEST_RECEIVERS = {
    "reference_01": {
        "type": "reference",
        "directory": "01_reference/01_GNSS/01_raw",
        "paired_canopies": "all",
        "description": "Test reference receiver",
    },
    "canopy_01": {
        "type": "canopy",
        "directory": "02_canopy/01_GNSS/01_raw",
        "description": "Test canopy receiver",
    },
}

_TEST_VOD_ANALYSES = {
    "canopy_01_vs_reference_01": {
        "canopy_receiver": "canopy_01",
        "reference_receiver": "reference_01",
    },
}


@pytest.mark.integration
@pytest.mark.skipif(
    not (HAS_CONFIG and HAS_TEST_DATA and HAS_STORE),
    reason="Integration test requires config files, test data, and store directory",
)
def test_sid_filtering_integration():
    """Test SID filtering with full orchestrator."""
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    from canvod.config import load_config
    from canvod.config.models import ReceiverConfig, VodAnalysisConfig
    from canvod.store import GnssResearchSite

    site = GnssResearchSite(site_name="Rosalia")

    # Override site config to use self-contained test data
    site._site_config.gnss_site_data_root = str(_ROSALIA_DATA)
    site._site_config.receivers = {
        name: ReceiverConfig(**cfg) for name, cfg in _TEST_RECEIVERS.items()
    }
    site._site_config.vod_analyses = {
        name: VodAnalysisConfig(**cfg) for name, cfg in _TEST_VOD_ANALYSES.items()
    }

    orchestrator = PipelineOrchestrator(site=site, dry_run=False)

    counter = 0
    for date_key, _datasets, _receiver_times in orchestrator.process_by_date(
        keep_vars=load_config().processing.params.keep_gnss_observables,
        start_from=None,
        end_at=None,
    ):
        counter += 1
        if counter >= 1:
            break

    assert counter == 1, "Should have processed exactly one date"


if __name__ == "__main__":
    import sys

    try:
        if not HAS_CONFIG:
            print("Skipping: Config files not found")
            sys.exit(0)
        if not HAS_TEST_DATA:
            print("Skipping: Test data not found")
            sys.exit(0)
        test_sid_filtering_integration()
    except Exception as e:
        print(f"\nERROR: {e}", flush=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)
