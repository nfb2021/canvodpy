"""Every reader records the time scale of its epochs.

The epoch coordinate carries ``time_system`` (and ``time_system_name``):
RINEX epochs stay in the time system of the file (``TIME OF FIRST OBS``;
RINEX "GLO" is UTC), SBF epochs are converted to UTC, NMEA epochs are UTC.
"""

from pathlib import Path

import pytest

from canvod.readers.gnss_specs.metadata import EPOCH_TIME_SYSTEMS, epoch_coord_attrs

TEST_DATA_DIR = Path(__file__).parent / "test_data"
RINEX_V3 = (
    TEST_DATA_DIR / "valid/rinex_v3_04/01_Rosalia/02_canopy/01_GNSS/01_raw/25001/"
    "ROSA01TUW_R_20250011945_15M_05S_AA.rnx"
)
RINEX_V2 = (
    TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/01_reference/25001/"
    "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
)


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"Test file not found: {path}")
    return path


def test_rinex_v3_epoch_time_system_from_header():
    from canvod.readers.rinex.v3_04 import Rnxv3Obs

    obs = Rnxv3Obs(fpath=_require(RINEX_V3), completeness_mode="off")
    ds = obs.to_ds(keep_data_vars=["SNR"], parser="validated")
    assert obs.header.time_system == "GPS"
    assert ds["epoch"].attrs["time_system"] == "GPS"
    assert ds["epoch"].attrs["time_system_name"] == "GPS time"


def test_rinex_v2_epoch_time_system_from_header():
    from canvod.readers.rinex.v2_11 import Rnxv2Obs

    obs = Rnxv2Obs(fpath=_require(RINEX_V2))
    ds = obs.to_ds(keep_data_vars=["SNR"])
    assert ds["epoch"].attrs["time_system"] == obs.header.time_system


def test_glo_is_recorded_as_utc():
    assert epoch_coord_attrs("GLO")["time_system"] == "UTC"


@pytest.mark.parametrize("scale", sorted(EPOCH_TIME_SYSTEMS))
def test_known_time_systems(scale):
    assert epoch_coord_attrs(scale)["time_system"] == scale


def test_unknown_time_system_is_rejected():
    with pytest.raises(ValueError, match="unknown epoch time system"):
        epoch_coord_attrs("TAI")
