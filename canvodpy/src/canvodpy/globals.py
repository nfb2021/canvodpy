"""Global constants for canvodpy.

Only true physical/technical constants live here.
All user-configurable settings are managed by the YAML config system
(``canvod.config.load_config()``).
"""

import pint

# ── Pint unit registry (singleton) ──────────────────────────────────────────
UREG = pint.get_application_registry()

if "dBHz" not in UREG:
    UREG.define("dBHz = 10 * log10(hertz)")

# ── Physical constants ──────────────────────────────────────────────────────
SPEEDOFLIGHT: pint.Quantity = 299792458 * UREG.meter / UREG.second

# ── RINEX spec constants ───────────────────────────────────────────────────
EPOCH_RECORD_INDICATOR: str = ">"

# ── Hardware / archive specs ────────────────────────────────────────────────
SEPTENTRIO_SAMPLING_INTERVALS: list[pint.Quantity] = [
    100 * UREG.millisecond,
    200 * UREG.millisecond,
    500 * UREG.millisecond,
    1 * UREG.second,
    2 * UREG.second,
    5 * UREG.second,
    10 * UREG.second,
    15 * UREG.second,
    30 * UREG.second,
    60 * UREG.second,
    2 * UREG.minute,
    5 * UREG.minute,
    10 * UREG.minute,
    15 * UREG.minute,
    30 * UREG.minute,
    60 * UREG.minute,
]

IGS_RNX_DUMP_INTERVALS: list[pint.Quantity] = [
    15 * UREG.minute,
    1 * UREG.hour,
    6 * UREG.hour,
    24 * UREG.hour,
]

# ── GNSS frequency unit ────────────────────────────────────────────────────
FREQ_UNIT = UREG.MHz
