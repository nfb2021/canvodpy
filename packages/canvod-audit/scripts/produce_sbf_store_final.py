"""Produce the canvodpy SBF Icechunk store with agency (final) ephemeris.

Runs the canvodpy processing pipeline on Rosalia SBF test data with
SP3/CLK final products to create a store for Tier 1 SBF vs RINEX comparison.

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
      ephemeris_source: final
    storage:
      stores_root_dir: /Volumes/ExtremePro/canvod_audit_output/tier1_sbf_vs_rinex
      aux_data_dir: <repo>/packages/canvod-readers/tests/test_data/valid/rinex_v3_04/01_Rosalia
      gnss_store_name: canvodpy_SBF_store
      gnss_store_strategy: append

Input data
----------
- 189 SBF files per receiver (canopy + reference), DOY 2025001
- SP3: COD0MGXFIN_20250010000_01D_05M_ORB.SP3
- CLK: COD0MGXFIN_20250010000_01D_30S_CLK.CLK

Output
------
Icechunk store at ``tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_store/``
with groups: canopy_01, reference_01_canopy_01
"""

from __future__ import annotations

from canvodpy import process_date

if __name__ == "__main__":
    process_date("Rosalia", "2025001")
