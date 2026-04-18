"""Infrastructure: store round-trip audit.

Reads each group from the store, writes to NetCDF, reads back, and
verifies bit-identical results.

Stores used
-----------
canvodpy RINEX : produced by ``produce_canvodpy_store.py``

Results (2026-03-10)
--------------------
- canopy_01: PASS
- reference_01_canopy_01: PASS
"""

from __future__ import annotations

import os
from pathlib import Path

from canvod.audit.runners import audit_store_round_trip
from canvod.audit.runners.common import open_store

AUDIT_ROOT = Path(
    os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
)
CANVODPY_RINEX = str(AUDIT_ROOT / "tier0_rinex/Rosalia/canvodpy_RINEX_store")

store = open_store(CANVODPY_RINEX)
result = audit_store_round_trip(store)
print(result.summary())
