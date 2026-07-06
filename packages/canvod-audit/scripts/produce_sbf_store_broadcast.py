"""Produce the canvodpy SBF Icechunk store with broadcast ephemeris.

Runs the canvodpy processing pipeline on Rosalia SBF test data using
broadcast ephemerides extracted from SBF SatVisibility records.

Prerequisites
-------------
Before running, ensure ``config/sites.yaml`` and ``config/processing.yaml``
are configured as follows:

sites.yaml::

    sites:
      Rosalia:
        gnss_site_data_root: <repo>/packages/canvod-readers/tests/test_data/valid/sbf/01_Rosalia
        receivers:
          reference_01:
            directory: 01_reference
            reader_format: sbf
          canopy_01:
            directory: 02_canopy
            reader_format: sbf

processing.yaml::

    processing:
      ephemeris_source: broadcast
    storage:
      stores_root_dir: /Volumes/ExtremePro/canvod_audit_output/tier1_broadcast_vs_agency
      gnss_store_name: canvodpy_SBF_broadcast_store
      gnss_store_strategy: append

Input data
----------
- 189 SBF files per receiver (canopy + reference), DOY 2025001
- Broadcast ephemeris from SBF SatVisibility records (no SP3/CLK needed)

Output
------
Icechunk store at ``tier1_broadcast_vs_agency/Rosalia/canvodpy_SBF_broadcast_store/``
with groups: canopy_01, reference_01_canopy_01
"""

from __future__ import annotations

from canvodpy import process_date

if __name__ == "__main__":
    process_date("Rosalia", "2025001")
