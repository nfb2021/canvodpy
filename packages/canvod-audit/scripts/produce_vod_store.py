"""Produce the canvodpy VOD Icechunk store.

Reads obs data from the existing rinex store (configured via
``config/processing.yaml``) and writes VOD to the vod store.

Prerequisites
-------------
Before running, ensure ``config/processing.yaml`` points to an existing
obs store and the desired vod store name, e.g.::

    storage:
      stores_root_dir: /Volumes/ExtremePro/canvod_audit_output/tier0_rinex
      gnss_store_name: canvodpy_RINEX_store
      vod_store_name: canvodpy_VOD_store

The obs store must already exist (run the appropriate produce_*_store.py
script first).

Output
------
VOD store at ``{stores_root_dir}/{site_name}/{vod_store_name}/``
with group: canopy_01_vs_reference_01
"""

from __future__ import annotations

from canvod.vod import TauOmegaZerothOrder
from canvodpy import Site

SITE = "Rosalia"
CANOPY = "canopy_01"
REFERENCE = "reference_01_canopy_01"
DATE = "2025001"

if __name__ == "__main__":
    site = Site(SITE)

    canopy_data = site.gnss_store.read_group(CANOPY, date=DATE)
    ref_data = site.gnss_store.read_group(REFERENCE, date=DATE)

    vod_results = TauOmegaZerothOrder.from_datasets(canopy_data, ref_data)

    analysis_name = "canopy_01_vs_reference_01"
    site.vod_store.write_or_append_group(vod_results, analysis_name)
    print(f"VOD written to group '{analysis_name}'")
