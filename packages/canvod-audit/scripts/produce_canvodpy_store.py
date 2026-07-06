"""Produce the canvodpy RINEX Icechunk store used for Tier 0 audits.

This script runs the canvodpy processing pipeline on the test RINEX data
to create the store used in audit comparisons.

Prerequisites
-------------
Before running, ensure ``config/sites.yaml`` and ``config/processing.yaml``
are configured as follows:

sites.yaml::

    sites:
      Rosalia:
        gnss_site_data_root: <repo>/packages/canvod-readers/tests/test_data/valid/rinex_v3_04/01_Rosalia
        receivers:
          reference_01:
            directory: 01_reference/01_GNSS/01_raw
            reader_format: rinex3
          canopy_01:
            directory: 02_canopy/01_GNSS/01_raw
            reader_format: rinex3

processing.yaml::

    processing:
      ephemeris_source: final
    storage:
      aux_data_dir: <repo>/packages/canvod-readers/tests/test_data/valid/rinex_v3_04/01_Rosalia
      gnss_store_name: canvodpy_Rinex_Icechunk_Store
      gnss_store_strategy: append

Input data
----------
- 96 RINEX v3.04 files per receiver (canopy + reference), DOY 2025001
- SP3: COD0MGXFIN_20250010000_01D_05M_ORB.SP3
- CLK: COD0MGXFIN_20250010000_01D_30S_CLK.CLK

Output
------
Icechunk store at ``{stores_root_dir}/Rosalia/canvodpy_Rinex_Icechunk_Store/``
with groups: canopy_01, reference_01_canopy_01
"""

from __future__ import annotations

from canvodpy import process_date

if __name__ == "__main__":
    process_date("Rosalia", "2025001")
