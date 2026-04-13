"""RINEX format readers.

Supports multiple RINEX versions:
- v3.04 (current)
- v2.x (future)
- v4.x (future)
"""

from canvod.readers.rinex.v2_11 import Rnxv2Obs
from canvod.readers.rinex.v3_04 import Rnxv3Obs
from canvod.readers.rinex.v3_05_stripped import Rnxv3StrippedObs, StrippedRinexError

__all__ = [
    "Rnxv2Obs",
    "Rnxv3Obs",
    "Rnxv3StrippedObs",
    "StrippedRinexError",
]
