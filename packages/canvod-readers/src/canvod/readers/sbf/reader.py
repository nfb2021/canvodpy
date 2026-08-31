"""SBF file reader.

Wraps the ``sbf-parser`` library and converts raw SBF fields to physical
units using :mod:`_scaling`.  Physical quantities are expressed as
:class:`pint.Quantity` objects via the shared
:data:`~canvod.readers.gnss_specs.constants.UREG` registry.

GLONASS FDMA frequencies are resolved via a live ``FreqNr`` cache updated
from ChannelStatus blocks as they appear in the stream.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Any, cast

import numpy as np
import pint
import structlog
import xarray as xr
from pydantic import ConfigDict

from canvod.readers.base import GNSSDataReader, validate_dataset
from canvod.readers.gnss_specs.constants import UREG
from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)
from canvod.readers.gnss_specs.metadata import (
    CN0_METADATA,
    COORDS_METADATA,
    DTYPES,
    OBSERVABLES_METADATA,
)
from canvod.readers.sbf._registry import (
    _SIGNAL_FREQ_HZ,
    FDMA_SIGNAL_NUMS,
    SIGNAL_TABLE,
    decode_svid,
)
from canvod.readers.sbf._scaling import (
    _cn0_dbhz_f,
    _doppler2_hz_f,
    _doppler_hz_f,
    _glonass_freq_hz_f,
    _phase_cycles_f,
    _pr2_m_f,
    _pseudorange_m_f,
    cn0_dbhz,
    decode_offsets_msb,
    decode_signal_num,
    doppler2_hz,
    doppler_hz,
    glonass_freq_hz,
    phase_cycles,
    pr2_m,
    pseudorange_m,
)
from canvod.readers.sbf.models import SbfEpoch, SbfHeader, SbfSignalObs

try:
    import sbf_parser
except ImportError as _err:
    raise ImportError(
        "sbf-parser is required for SbfReader. Install it with: uv add sbf-parser"
    ) from _err

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# GPS ↔ UTC time conversion
# Source: IS-GPS-200, §20.3.3.5.2.4
# GPS epoch: 1980-01-06 00:00:00 UTC (no leap seconds at that date)
# ---------------------------------------------------------------------------

_GPS_EPOCH = datetime(1980, 1, 6, tzinfo=UTC)
_SECONDS_PER_GPS_WEEK: int = 604_800

# Leap second offset GPS - UTC.  Valid from 2017-01-01; next scheduled: TBD.
# Updated dynamically when a ReceiverTime block is available in the stream.
_DEFAULT_DELTA_LS: int = 18


def _tow_wn_to_utc(tow_ms: int, wn: int, delta_ls: int) -> datetime:
    """Convert GPS TOW + WN to a UTC datetime.

    Parameters
    ----------
    tow_ms : int
        GPS Time of Week in milliseconds.
    wn : int
        GPS Week Number (continuous, post-rollover correction applied by
        the receiver).
    delta_ls : int
        Leap second count: GPS - UTC (seconds).

    Returns
    -------
    datetime
        Timezone-aware UTC timestamp.

    Notes
    -----
    Source: IS-GPS-200, §20.3.3.5.2.4.
    """
    gps_seconds = wn * _SECONDS_PER_GPS_WEEK + tow_ms / 1000.0
    utc_seconds = gps_seconds - delta_ls
    return _GPS_EPOCH + timedelta(seconds=utc_seconds)


def _resolve_freq_hz(
    sig_num: int,
    svid: int,
    freq_nr_cache: dict[int, int],
) -> float | None:
    """Return carrier frequency in Hz as a plain float, or None if unavailable.

    Zero-allocation fast variant of SbfReader._resolve_freq() for use in the
    hot decode loop inside to_ds_and_auxiliary().  GLONASS FDMA signals return
    None when FreqNr is not yet known; L-Band MSS (sig 23) always returns None.
    """
    if sig_num in FDMA_SIGNAL_NUMS:
        freq_nr = freq_nr_cache.get(svid)
        if freq_nr is None:
            return None
        return _glonass_freq_hz_f(sig_num, freq_nr)
    return _SIGNAL_FREQ_HZ.get(sig_num)  # None for unknown / L-Band MSS


# ---------------------------------------------------------------------------
# String helpers for ReceiverSetup binary character arrays
# ---------------------------------------------------------------------------


def _decode_bytes(raw: bytes) -> str:
    """Decode a NUL-padded SBF character array to a clean Python string."""
    return raw.decode("ascii", errors="replace").rstrip("\x00").strip()


def _snr_dbhz_to_ssi(snr_dbhz: np.ndarray) -> np.ndarray:
    """Derive RINEX-convention SSI (1-9) from continuous CN0 (dB-Hz).

    SBF's raw MeasEpoch blocks carry only continuous CN0, not RINEX's
    single-digit Signal Strength Indicator -- this is the standard
    RINEX-writing-receiver conversion for CN0 given in dB-Hz (RINEX 3.04
    §5.7): ``sn_rnx = MIN(MAX(INT(sn_raw/6), 1), 9)``. NaN (no
    observation) stays at the -1 "no data" sentinel.
    """
    ssi = np.full(snr_dbhz.shape, -1, dtype=np.int8)
    valid = np.isfinite(snr_dbhz)
    ssi[valid] = np.clip(np.floor(snr_dbhz[valid] / 6.0), 1, 9).astype(np.int8)
    return ssi


# ---------------------------------------------------------------------------
# Bandwidth / frequency helpers for to_ds() and to_metadata_ds()
# ---------------------------------------------------------------------------

_CONSTELLATION_MAP: dict[str, Any] = {
    "G": GPS,
    "R": GLONASS,
    "E": GALILEO,
    "C": BEIDOU,
    "J": QZSS,
    "I": IRNSS,
    "S": SBAS,
}


def _get_bandwidth_mhz(system: str, band: str) -> float:
    """Return signal bandwidth in MHz, or NaN if unknown.

    Parameters
    ----------
    system : str
        RINEX single-letter system code.
    band : str
        Band label (e.g. "L1", "G1", "E5a").

    Returns
    -------
    float
        Bandwidth in MHz, or NaN if the band is not found.
    """
    if system == "R" and band in ("G1", "G2"):
        # FDMA G1/G2: use aggregated bandwidth table (ClassVar on GLONASS)
        bw = GLONASS.AGGR_G1_G2_BAND_PROPERTIES[band]["bandwidth"]
        return float(bw.to(UREG.MHz).magnitude)
    const = _CONSTELLATION_MAP.get(system)
    if const is None:
        return float("nan")
    try:
        bw = const.BAND_PROPERTIES[band]["bandwidth"]
        return float(bw.to(UREG.MHz).magnitude)
    except KeyError, AttributeError:
        return float("nan")


# ---------------------------------------------------------------------------
# Theta / phi provenance attributes for to_metadata_ds()
# ---------------------------------------------------------------------------

_THETA_ATTRS: dict[str, str] = {
    "long_name": "Satellite polar angle",
    "standard_name": "sensor_polar_angle",
    "units": "degrees",
    "source": "SBF SatVisibility block (Block 4012) — reported by receiver firmware",
    "comment": (
        "Polar angle (angle from vertical): theta = 90 - elevation. "
        "0 deg = satellite directly overhead; 90 deg = satellite at horizon. "
        "Computed from SatVisibility.SatInfo.Elevation (i2, scale 0.01 deg/LSB, "
        "Do-Not-Use -32768). "
        "Derived from the receiver's internal navigation solution, NOT from "
        "independently-computed satellite ephemerides."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field Elevation, p.401."
    ),
    # Missing observations encoded as NaN (IEEE float32 missing-value convention).
    # No _FillValue attr: xarray/Zarr use NaN natively for float32.
}
_PHI_ATTRS: dict[str, str] = {
    "long_name": "Satellite azimuth (geographic convention)",
    "standard_name": "sensor_azimuth_angle",
    "units": "degrees",
    "source": "SBF SatVisibility block (Block 4012) — reported by receiver firmware",
    "comment": (
        "Geographic (compass) azimuth: 0° = North, 90° = East, 180° = South, "
        "270° = West (clockwise from North). SatVisibility.SatInfo.Azimuth "
        "(u2, scale 0.01 deg/LSB, Do-Not-Use 65535). "
        "NOTE: this is NOT the mathematical spherical-coordinate azimuthal angle phi, "
        "which is measured counterclockwise from East. "
        "To convert: phi_spherical = 90 deg - phi_stored (mod 360 deg). "
        "Derived from the receiver's internal navigation solution, NOT from "
        "independently-computed satellite ephemerides."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field Azimuth, p.401."
    ),
    # Missing observations encoded as NaN (IEEE float32 missing-value convention).
    # No _FillValue attr: xarray/Zarr use NaN natively for float32.
}

# ---------------------------------------------------------------------------
# Metadata dataset variable / coordinate attributes
# (CF-convention style: long_name, units, source, comment, references)
# ---------------------------------------------------------------------------

_BROADCAST_THETA_ATTRS: dict[str, str] = {
    "long_name": "Satellite polar angle (broadcast ephemeris)",
    "short_name": "θ_B",
    "standard_name": "sensor_polar_angle",
    "units": "rad",
    "source": "SBF SatVisibility block (Block 4012) — reported by receiver firmware",
    "comment": (
        "Polar angle from vertical: 0 = overhead, π/2 = horizon. "
        "Derived from SatVisibility.SatInfo.Elevation (i2, scale 0.01 deg/LSB, "
        "Do-Not-Use -32768), converted to radians via theta = (90 - elevation_deg) * π/180. "
        "Based on the receiver's internal broadcast navigation solution, "
        "NOT independently-computed satellite ephemerides (e.g. SP3/CLK)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field Elevation, p.401."
    ),
}
_BROADCAST_PHI_ATTRS: dict[str, str] = {
    "long_name": "Satellite azimuth (broadcast ephemeris, geographic convention)",
    "short_name": "φ_B",
    "standard_name": "sensor_azimuth_angle",
    "units": "rad",
    "source": "SBF SatVisibility block (Block 4012) — reported by receiver firmware",
    "comment": (
        "Geographic azimuth: 0 = North, π/2 = East (clockwise). "
        "Derived from SatVisibility.SatInfo.Azimuth (u2, scale 0.01 deg/LSB, "
        "Do-Not-Use 65535), converted to radians via phi = azimuth_deg * π/180. "
        "Based on the receiver's internal broadcast navigation solution, "
        "NOT independently-computed satellite ephemerides (e.g. SP3/CLK)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field Azimuth, p.401."
    ),
}

_RISE_SET_ATTRS: dict[str, object] = {
    "long_name": "Satellite rise/set indicator",
    "flag_values": [0, 1],
    "flag_meanings": "setting rising",
    "source": "SBF SatVisibility block — reported by receiver firmware",
    "comment": (
        "Rise/set indicator from the SBF SatVisibility block: "
        "0 = satellite is setting (elevation decreasing), "
        "1 = satellite is rising (elevation increasing), "
        "255 (raw) indicates unknown elevation rate. "
        "Fill value -1 (int8) used for missing observations."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "SatVisibility block (Block 4012), SatInfo sub-block, field RiseSet, p.401. "
        "Raw field: u1, scale 1; 0=setting, 1=rising, 255=unknown (→ stored as -1)."
    ),
}

_MP_CORRECTION_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange multipath correction",
    "units": "m",
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Multipath mitigation correction applied to the pseudorange by the receiver. "
        "Add this value to the pseudorange to recover the raw unmitigated pseudorange. "
        "Raw field: i2, scale 0.001 m/LSB (resolution 1 mm). No Do-Not-Use value."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field MPCorrection, p.265."
    ),
}

_CODE_VAR_ATTRS: dict[str, object] = {
    "long_name": "Code tracking noise variance",
    "units": "m^2",
    "valid_max": 65534e-4,
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Estimated code tracking noise variance. "
        "Raw field: u2, scale 0.0001 m²/LSB (stored here after applying scale). "
        "Values saturate at 65534 counts (= 6.5534 m²); raw Do-Not-Use 65535 → NaN."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CodeVar, p.265."
    ),
}

_CARRIER_VAR_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase tracking noise variance",
    "units": "mcycles^2",
    "valid_max": 65534.0,
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Estimated carrier phase tracking noise variance. "
        "Raw field: u2, scale 1 mcycle²/LSB. "
        "Values saturate at 65534 mcycles²; raw Do-Not-Use 65535 → NaN. "
        "Multiply by the MeasExtra.DopplerVarFactor to obtain the Doppler "
        "measurement variance."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CarrierVar, p.265."
    ),
}

_CN0_HIGHRES_CORRECTION_ATTRS: dict[str, object] = {
    "long_name": "C/N0 high-resolution correction from MeasExtra",
    "units": "dB-Hz",
    "valid_min": 0.0,
    "valid_max": 7 * 0.03125,  # CN0HighRes max value 7 → 0.21875 dB-Hz
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "High-resolution C/N0 extension from MeasExtra.MeasExtraChannelSub.Misc "
        "bits 0-2 (CN0HighRes, u3, range 0-7). "
        "Add to the SNR variable (from MeasEpoch, 0.25 dB-Hz resolution) to obtain "
        "C/N0 at 0.03125 dB-Hz (1/32 dB-Hz) resolution: "
        "  C/N0_highres = SNR + cn0_highres_correction. "
        "NaN if MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field Misc bits 0-2 (CN0HighRes), p.265."
    ),
}

_SMOOTHING_CORR_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange Hatch-filter smoothing correction",
    "units": "m",
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Smoothing correction applied to the pseudorange by the Hatch filter. "
        "Add to the stored pseudorange to recover the raw unsmoothed measurement. "
        "Raw field: i2, scale 0.001 m/LSB. "
        "NaN if MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field SmoothingCorr, p.265."
    ),
}

_LOCK_TIME_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase lock time",
    "units": "s",
    "valid_min": 0,
    "valid_max": 65534,
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Duration of continuous carrier phase tracking for this signal. "
        "Reset to 0 on reacquisition or cycle slip. "
        "Raw field: u2, scale 1 s/LSB, clipped to 65534 s; Do-Not-Use 65535 → NaN."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field LockTime, p.265."
    ),
}

_CUM_LOSS_CONT_ATTRS: dict[str, object] = {
    "long_name": "Cumulative loss-of-continuity counter",
    "units": "1",
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Modulo-256 counter that increments each time continuous carrier phase "
        "tracking is interrupted (cycle slip or reacquisition after loss of lock). "
        "A change between consecutive epochs indicates a cycle slip. "
        "Raw field: u1, no Do-Not-Use value."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CumLossCont, p.265."
    ),
}

_CAR_MP_CORR_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase multipath correction",
    "units": "cycles",
    "source": "SBF MeasExtra block (Block 4000) — reported by receiver firmware",
    "comment": (
        "Multipath correction for the carrier phase measurement. "
        "Add to the stored carrier phase to recover the raw unmitigated phase. "
        "Raw field: i1, scale 1/512 cycles/LSB (1.953125 mcycles/LSB). "
        "NaN if MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CarMPCorr, p.265."
    ),
}

_SNR_RAW_ATTRS: dict[str, object] = {
    "long_name": "C/N0 before CN0HighRes correction (0.25 dB-Hz resolution)",
    "units": "dB-Hz",
    "valid_min": 0.0,
    "source": "SBF MeasEpoch block (Block 4027) — before CN0HighRes correction",
    "comment": (
        "Carrier-to-noise density at the native MeasEpoch resolution of 0.25 dB-Hz, "
        "before the high-resolution extension from MeasExtra is applied. "
        "SNR is the corrected version (0.03125 dB-Hz when MeasExtra is available). "
        "NaN where no observation was present."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), MeasEpochChannelType1 sub-block, "
        "field CN0, p.264."
    ),
}

_PSEUDORANGE_UNSMOOTHED_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange before Hatch-filter carrier smoothing",
    "units": "m",
    "source": "SBF MeasEpoch + MeasExtra (Blocks 4027, 4000)",
    "comment": (
        "Pseudorange with the Hatch-filter smoothing correction removed: "
        "PR_unsmoothed = Pseudorange + smoothing_corr_m. "
        "Exposes the raw code measurement before the firmware's carrier-smoothing "
        "filter is applied. NaN where MeasExtra was not logged or no measurement "
        "available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field SmoothingCorr, p.265."
    ),
}

_PSEUDORANGE_RAW_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange before Hatch-filter smoothing and multipath mitigation",
    "units": "m",
    "source": "SBF MeasEpoch + MeasExtra (Blocks 4027, 4000)",
    "comment": (
        "Pseudorange with both firmware corrections removed: "
        "PR_raw = Pseudorange + smoothing_corr_m + mp_correction_m. "
        "Exposes the code measurement before any firmware post-processing. "
        "NaN where MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "fields SmoothingCorr and MPCorrection, p.265."
    ),
}

_PHASE_RAW_ATTRS: dict[str, object] = {
    "long_name": "Carrier phase before carrier multipath correction",
    "units": "cycles",
    "source": "SBF MeasEpoch + MeasExtra (Blocks 4027, 4000)",
    "comment": (
        "Carrier phase with the firmware multipath correction removed: "
        "Phase_raw = Phase + car_mp_corr_cycles. "
        "NaN where MeasExtra was not logged or no measurement available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasExtra block (Block 4000), MeasExtraChannelSub sub-block, "
        "field CarMPCorr, p.265."
    ),
}

_PDOP_ATTRS: dict[str, object] = {
    "long_name": "Position Dilution of Precision",
    "units": "1",
    "source": "SBF DOP block (Block 4001, fallback: PVTGeodetic Block 4007) — reported by receiver firmware",
    "comment": (
        "PDOP = √(Qxx + Qyy + Qzz), where Q is the position covariance matrix "
        "in a local Cartesian frame. Smaller values indicate better satellite geometry. "
        "Raw field: u2, scale 0.01/LSB, Do-Not-Use 0 (→ NaN). "
        "NaN indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "DOP block (Block 4001), field PDOP, p.349."
    ),
}

_HDOP_ATTRS: dict[str, object] = {
    "long_name": "Horizontal Dilution of Precision",
    "units": "1",
    "source": "SBF DOP block (Block 4001, fallback: PVTGeodetic Block 4007) — reported by receiver firmware",
    "comment": (
        "HDOP = √(Qλλ + Qϕϕ), where Qλλ and Qϕϕ are the longitude and latitude "
        "components of the position covariance matrix. "
        "Raw field: u2, scale 0.01/LSB, Do-Not-Use 0 (→ NaN). "
        "NaN indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "DOP block (Block 4001), field HDOP, p.349."
    ),
}

_VDOP_ATTRS: dict[str, object] = {
    "long_name": "Vertical Dilution of Precision",
    "units": "1",
    "source": "SBF DOP block (Block 4001, fallback: PVTGeodetic Block 4007) — reported by receiver firmware",
    "comment": (
        "VDOP = √(Qhh), where Qhh is the height component of the position "
        "covariance matrix. "
        "Raw field: u2, scale 0.01/LSB, Do-Not-Use 0 (→ NaN). "
        "NaN indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "DOP block (Block 4001), field VDOP, p.349."
    ),
}

_N_SV_ATTRS: dict[str, object] = {
    "long_name": "Number of satellites used in PVT computation",
    "units": "1",
    "source": "SBF PVTGeodetic block (Block 4007) — reported by receiver firmware",
    "comment": (
        "Total number of satellites used in the Position-Velocity-Time (PVT) "
        "computation. Raw field: u1, Do-Not-Use 255 (→ stored as -1). "
        "Fill value -1 (int16) indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field NrSV, p.338."
    ),
}

_H_ACCURACY_ATTRS: dict[str, object] = {
    "long_name": "Horizontal position accuracy (2DRMS, 95%)",
    "units": "m",
    "source": "SBF PVTGeodetic block (Block 4007) — reported by receiver firmware",
    "comment": (
        "Twice the root-mean-square of the horizontal distance error (2DRMS). "
        "The horizontal distance between the true and computed positions is expected "
        "to be below this value with ≥95% probability. "
        "Raw field: u2, scale 0.01 m/LSB, Do-Not-Use 65535 (→ NaN)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field HAccuracy, p.338."
    ),
}

_V_ACCURACY_ATTRS: dict[str, object] = {
    "long_name": "Vertical position accuracy (2-sigma, 95%)",
    "units": "m",
    "source": "SBF PVTGeodetic block (Block 4007) — reported by receiver firmware",
    "comment": (
        "Two-sigma vertical accuracy. "
        "The vertical distance between the true and computed positions is expected "
        "to be below this value with ≥95% probability. "
        "Raw field: u2, scale 0.01 m/LSB, Do-Not-Use 65535 (→ NaN)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field VAccuracy, p.338."
    ),
}

_PVT_MODE_ATTRS: dict[str, object] = {
    "long_name": "PVT solution mode",
    "units": "1",
    "flag_values": [0, 1, 2, 3, 4, 5, 6, 10],
    "flag_meanings": (
        "no_pvt stand_alone differential fixed_location "
        "rtk_fixed_ambiguities rtk_float_ambiguities sbas_aided ppp"
    ),
    "source": "SBF PVTGeodetic block (Block 4007) — reported by receiver firmware",
    "comment": (
        "Bits 0-3 of PVTGeodetic.Mode (u1). "
        "0 = No PVT; 1 = Stand-Alone; 2 = Differential (DGNSS); "
        "3 = Fixed location; 4 = RTK fixed ambiguities; "
        "5 = RTK float ambiguities; 6 = SBAS-aided; 10 = PPP. "
        "Fill value -1 (int8) indicates not available."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field Mode, p.337."
    ),
}

_MEAN_CORR_AGE_ATTRS: dict[str, object] = {
    "long_name": "Mean age of differential corrections",
    "units": "s",
    "source": "SBF PVTGeodetic block — reported by receiver firmware",
    "comment": (
        "Mean age of the differential corrections used in a DGNSS or RTK solution. "
        "Only meaningful when PVT mode is Differential (2), RTK fixed (4), or "
        "RTK float (5). NaN indicates not available (raw DoNotUse value 65535)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "PVTGeodetic block (Block 4007), field MeanCorrAge, p.339. "
        "Raw field: u2, scale 0.01 s/LSB, Do-Not-Use 65535 (→ NaN)."
    ),
}

_CPU_LOAD_ATTRS: dict[str, object] = {
    "long_name": "Receiver CPU load",
    "units": "percent",
    "valid_min": 0,
    "valid_max": 100,
    "source": "SBF ReceiverStatus block — reported by receiver firmware",
    "comment": (
        "Percentage load on the receiver's main processor (0-100%). "
        "Sustained values above 80% risk data loss in the receiver. "
        "Fill value -1 (int8) indicates not available (raw DoNotUse value 255)."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "ReceiverStatus block (Block 4014), field CPULoad, p.396. "
        "Raw field: u1, scale 1 %/LSB, Do-Not-Use 255 (→ stored as -1). "
        "Sustained load > 80% risks data loss."
    ),
}

_TEMPERATURE_ATTRS: dict[str, object] = {
    "long_name": "Receiver internal temperature",
    "units": "degC",
    "source": "SBF ReceiverStatus block — reported by receiver firmware",
    "comment": (
        "Internal temperature of the receiver. "
        "The raw SBF field (u1) has 1 °C resolution and an offset of 100; "
        "stored value = raw_field − 100 (e.g. raw 120 → 20 °C). "
        "Do-Not-Use value 0 is stored as NaN."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "ReceiverStatus block (Block 4014), field Temperature, p.399. "
        "Raw field: u1, subtract 100 to obtain °C (e.g. raw 120 = 20°C). "
        "Do-Not-Use 0 (→ NaN)."
    ),
}

_RX_ERROR_ATTRS: dict[str, object] = {
    "long_name": "Receiver error status bit field",
    "units": "1",
    # CF bitmask convention: test each flag with (value & mask) != 0
    # Bit positions: 3=8, 4=16, 5=32, 6=64, 9=512, 10=1024, 11=2048
    "flag_masks": [8, 16, 32, 64, 512, 1024, 2048],
    "flag_meanings": (
        "software watchdog antenna congestion cpuoverload invalidconfig outofgeofence"
    ),
    "source": "SBF ReceiverStatus block — reported by receiver firmware",
    "comment": (
        "Bit field indicating whether the receiver previously detected an error. "
        "Non-zero value means at least one error has been detected. "
        "Multiple flags may be set simultaneously; test each with "
        "(rx_error & flag_mask) != 0. "
        "E.g. value 8 = bit 3 = software error; "
        "value 48 = bits 4+5 = watchdog + antenna."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "ReceiverStatus block (Block 4014), field RxError, p.398."
    ),
}


_SMOOTHING_FLAG_ATTRS: dict[str, object] = {
    "long_name": "Pseudorange smoothing flag",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "missing not_smoothed smoothed",
    "source": "SBF MeasEpoch block (Block 4027) — ObsInfo bit 0",
    "comment": (
        "1 = pseudorange is carrier-smoothed (smoothing filter applied by "
        "the receiver), 0 = not smoothed, -1 = no observation. "
        "Extracted from the ObsInfo byte (bit 0) of each MeasEpoch "
        "Type1/Type2 sub-block."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), field ObsInfo bit 0, pp. 260-263."
    ),
}
_HALF_CYCLE_ATTRS: dict[str, object] = {
    "long_name": "Carrier-phase half-cycle ambiguity flag",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "missing resolved half_cycle_ambiguous",
    "source": "SBF MeasEpoch block (Block 4027) — ObsInfo bit 2",
    "comment": (
        "1 = the carrier phase of this observation may contain an "
        "unresolved 0.5-cycle ambiguity, 0 = ambiguity resolved, "
        "-1 = no observation. Extracted from the ObsInfo byte (bit 2) "
        "of each MeasEpoch Type1/Type2 sub-block."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), field ObsInfo bit 2, pp. 260-263."
    ),
}

# ---------------------------------------------------------------------------
# QualityInd (Block 4082) indicator attributes
# ---------------------------------------------------------------------------

_QUAL_COMMENT_TAIL = (
    "Score on a 0 (poor) to 10 (excellent) scale; -1 = unknown / not "
    "reported (raw value 15 or indicator absent). Decoded from QualityInd "
    "indicator words: bits 0-7 = indicator type, bits 8-11 = value."
)
_QUAL_REFERENCE = (
    "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
    "QualityInd block (Block 4082), field Indicators."
)
_QUAL_OVERALL_ATTRS: dict[str, object] = {
    "long_name": "Overall receiver quality indicator",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 0",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_GNSS_MAIN_ATTRS: dict[str, object] = {
    "long_name": "GNSS signal quality, main antenna",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 1",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_RF_MAIN_ATTRS: dict[str, object] = {
    "long_name": "RF power level quality, main antenna",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 11",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_CPU_ATTRS: dict[str, object] = {
    "long_name": "CPU headroom quality indicator",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 21",
    "comment": _QUAL_COMMENT_TAIL,
    "references": _QUAL_REFERENCE,
}
_QUAL_SCINT_ATTRS: dict[str, object] = {
    "long_name": "Ionospheric scintillation score",
    "valid_range": [0, 10],
    "source": "SBF QualityInd block (Block 4082), indicator type 29",
    "comment": (_QUAL_COMMENT_TAIL + " Indicator type 29 requires firmware >= 4.15.1."),
    "references": _QUAL_REFERENCE,
}

# ---------------------------------------------------------------------------
# RFStatus (Block 4092) flag attributes
# ---------------------------------------------------------------------------

_SPOOFING_FLAG_ATTRS: dict[str, object] = {
    "long_name": "GNSS spoofing detection flag",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "not_available no_spoofing spoofing_detected",
    "source": "SBF RFStatus block (Block 4092) — Flags bit 0",
    "comment": (
        "1 = the receiver detected suspected spoofing of GNSS signals at "
        "this epoch, 0 = no spoofing detected, -1 = no RFStatus block "
        "available for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "RFStatus block (Block 4092), field Flags bit 0."
    ),
}
_NMA_FAIL_ATTRS: dict[str, object] = {
    "long_name": "Navigation message authentication failure flag",
    "flag_values": [-1, 0, 1],
    "flag_meanings": "not_available authentication_ok authentication_failed",
    "source": "SBF RFStatus block (Block 4092) — Flags bit 1",
    "comment": (
        "1 = navigation message authentication (e.g. Galileo OSNMA) failed "
        "at this epoch, 0 = no authentication failure, -1 = no RFStatus "
        "block available for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "RFStatus block (Block 4092), field Flags bit 1."
    ),
}

# ---------------------------------------------------------------------------
# ChannelStatus (Block 4013) tracking / PVT status attributes
# ---------------------------------------------------------------------------

_TRACKING_STATUS_RAW_ATTRS: dict[str, object] = {
    "long_name": "Raw per-satellite tracking status bitfield (main antenna)",
    "source": (
        "SBF ChannelStatus block (Block 4013) — ChannelStateInfo.TrackingStatus"
    ),
    "comment": (
        "Raw u2 bitfield with 2 bits per signal type: 0 = Idle, 1 = Search, "
        "2 = Sync, 3 = Tracking. Bit positions are constellation-specific "
        "(e.g. GPS: bits 0-1 = L1CA, 2-3 = P1Y, 4-5 = P2Y, 6-7 = L2C, "
        "8-9 = L5, 10-11 = L1C). The same per-satellite value is broadcast "
        "to all SIDs of that satellite; decode the bit pair for the SID's "
        "signal type to obtain per-signal status. Main antenna only. "
        "0 also means no ChannelStatus information for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "ChannelStatus block (Block 4013), ChannelStateInfo sub-block, "
        "field TrackingStatus."
    ),
}
_PVT_STATUS_RAW_ATTRS: dict[str, object] = {
    "long_name": "Raw per-satellite PVT usage status bitfield (main antenna)",
    "source": "SBF ChannelStatus block (Block 4013) — ChannelStateInfo.PVTStatus",
    "comment": (
        "Raw u2 bitfield with 2 bits per signal type: 0 = Not used in PVT, "
        "1 = Waiting for ephemeris, 2 = Used in PVT, 3 = Rejected. Bit "
        "positions are constellation-specific and match TrackingStatus. "
        "The same per-satellite value is broadcast to all SIDs of that "
        "satellite. Main antenna only. "
        "0 also means no ChannelStatus information for this epoch."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.x Reference Guide, "
        "ChannelStatus block (Block 4013), ChannelStateInfo sub-block, "
        "field PVTStatus."
    ),
}


def _decode_quality_indicators(qualind: dict[str, Any]) -> dict[int, int]:
    """Decode QualityInd (Block 4082) indicator words to ``{type: value}``.

    ``sbf_parser`` returns the ``Indicators`` u2[N] array as raw
    little-endian bytes; decode each 16-bit word as
    bits 0-7 = indicator type, bits 8-11 = value (0-10; 15 = unknown).

    Parameters
    ----------
    qualind : dict
        Raw QualityInd block dict from ``sbf_parser``.

    Returns
    -------
    dict of {int: int}
        Mapping indicator type → value, with 15 (unknown) mapped to -1.
    """
    raw = qualind.get("Indicators", b"")
    if isinstance(raw, (bytes, bytearray)):
        words = [
            int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw) - 1, 2)
        ]
    else:  # already a sequence of ints
        words = [int(w) for w in raw]
    out: dict[int, int] = {}
    for word in words:
        ind_type = word & 0xFF
        value = (word >> 8) & 0x0F
        out[ind_type] = -1 if value == 15 else value
    return out


def _extract_tracking_info(
    chanstatus: dict[str, Any],
) -> list[tuple[str, int, int]]:
    """Extract per-satellite tracking info from a ChannelStatus block.

    Only Main-antenna (Antenna == 0) ChannelStateInfo sub-blocks are
    considered — the primary receiver channel.

    Parameters
    ----------
    chanstatus : dict
        Raw ChannelStatus (Block 4013) dict from ``sbf_parser``.

    Returns
    -------
    list of (sv, tracking_status, pvt_status)
        One entry per satellite with a Main-antenna channel state, where
        ``sv`` is e.g. ``"G01"`` and the two status values are the raw u2
        bitfields (2 bits per signal type).
    """
    out: list[tuple[str, int, int]] = []
    sats = chanstatus.get("SatInfo") or chanstatus.get("ChannelSatInfo") or []
    for sat in sats:
        try:
            svid = int(sat["SVID"])
            if svid == 0:  # Do-Not-Use
                continue
            sys_code, prn = decode_svid(svid)
            sv = f"{sys_code}{prn:02d}"
            for state in sat.get("StateInfo") or []:
                if int(state.get("Antenna", 0)) == 0:  # Main antenna
                    out.append(
                        (
                            sv,
                            int(state["TrackingStatus"]),
                            int(state["PVTStatus"]),
                        )
                    )
                    break
        except KeyError, TypeError, ValueError:
            continue
    return out


def _build_obs_map(meas_epoch_data: dict[str, Any]) -> dict[tuple[int, int], int]:
    """Build ``(rx_channel, sig_num) → svid`` mapping from a MeasEpoch dict.

    Parameters
    ----------
    meas_epoch_data : dict
        Raw MeasEpoch block dict from ``sbf_parser``.

    Returns
    -------
    dict
        Mapping ``(rx_channel, signal_num) → svid`` for all Type1 and
        Type2 sub-blocks in the epoch.
    """
    obs_map: dict[tuple[int, int], int] = {}
    for t1 in meas_epoch_data.get("Type_1", []):
        svid = int(t1["SVID"])
        type_byte = int(t1["Type"])
        obs_info = int(t1["ObsInfo"])
        sig_num = decode_signal_num(type_byte, obs_info)
        rx_ch = int(t1["RxChannel"])
        obs_map[(rx_ch, sig_num)] = svid
        for t2 in t1.get("Type_2", []):
            type_byte2 = int(t2["Type"])
            obs_info2 = int(t2["ObsInfo"])
            sig_num2 = decode_signal_num(type_byte2, obs_info2)
            # Type2 sub-blocks carry no RxChannel field on the wire —
            # they inherit the channel of their parent Type1 sub-block.
            obs_map[(rx_ch, sig_num2)] = svid
    return obs_map


def _sid_props_from_obs(
    svid: int,
    sig_num: int,
    freq_nr_cache: dict[int, int],
) -> dict[str, Any] | None:
    """Compute sid string and properties for one (svid, signal_num) pair.

    Returns None if the signal is not in SIGNAL_TABLE.
    """
    sig_def = SIGNAL_TABLE.get(sig_num)
    if sig_def is None:
        return None
    system, prn = decode_svid(svid)
    sv = f"{system}{prn:02d}"
    sid = f"{sv}|{sig_def.band}|{sig_def.code}"

    band = sig_def.band
    if sig_num in FDMA_SIGNAL_NUMS:
        freq_nr = freq_nr_cache.get(svid)
        if freq_nr is not None:
            freq_qty = glonass_freq_hz(sig_num, freq_nr)
            freq_center_mhz = float(freq_qty.to(UREG.MHz).magnitude)
        else:
            freq_qty = GLONASS.AGGR_G1_G2_BAND_PROPERTIES[band]["freq"]
            freq_center_mhz = float(freq_qty.to(UREG.MHz).magnitude)
    elif sig_def.freq is not None:
        freq_center_mhz = float(sig_def.freq.to(UREG.MHz).magnitude)
    else:
        freq_center_mhz = float("nan")

    bw_mhz = _get_bandwidth_mhz(system, band)
    if np.isnan(freq_center_mhz) or np.isnan(bw_mhz):
        freq_min_mhz = float("nan")
        freq_max_mhz = float("nan")
    else:
        freq_min_mhz = freq_center_mhz - bw_mhz / 2.0
        freq_max_mhz = freq_center_mhz + bw_mhz / 2.0

    return {
        "sid": sid,
        "sv": sv,
        "system": system,
        "band": band,
        "code": sig_def.code,
        "freq_center": freq_center_mhz,
        "freq_min": freq_min_mhz,
        "freq_max": freq_max_mhz,
    }


# ---------------------------------------------------------------------------
# SbfReader
# ---------------------------------------------------------------------------


class SbfReader(GNSSDataReader):
    """Read and decode a Septentrio Binary Format (SBF) observation file.

    Parameters
    ----------
    fpath : Path
        Path to the ``*.sbf`` (or ``*.SBF``, or receiver-named) binary file.

    Examples
    --------
    >>> reader = SbfReader(fpath=Path("rref213a00.25_"))
    >>> print(reader.header.rx_version)
    4.14.4
    >>> for epoch in reader.iter_epochs():
    ...     for obs in epoch.observations:
    ...         print(obs.system, obs.prn, obs.cn0)

    Notes
    -----
    - All physical-unit conversions follow RefGuide-4.14.0.
    - Physical quantities are expressed as :class:`pint.Quantity` objects
      using the shared :data:`~canvod.readers.gnss_specs.constants.UREG`.
    - GLONASS FDMA frequencies are resolved from the most recently seen
      ChannelStatus block; observations before the first ChannelStatus for a
      given SVID have ``phase_cycles=None``.
    - The file is scanned once per :meth:`iter_epochs` call; use
      :attr:`num_epochs` for a pre-computed count (scans once on first access).
    - Inherits ``fpath``, its validator, and ``arbitrary_types_allowed``
      from :class:`GNSSDataReader`.
    """

    model_config = ConfigDict(extra="ignore")

    @property
    def source_format(self) -> str:
        return "sbf"

    # ------------------------------------------------------------------
    # Pre-scan caches
    # ------------------------------------------------------------------

    @cached_property
    def _freq_nr_cache(self) -> dict[int, int]:
        """Pre-scan ALL ChannelStatus blocks to build a complete SVID → FreqNr map.

        Scanning the entire file once means early GLONASS epochs also have
        accurate FDMA frequency assignments in :meth:`iter_epochs`.

        Returns
        -------
        dict of {int: int}
            Mapping from Septentrio SVID to GLONASS frequency slot number.
        """
        parser = sbf_parser.SbfParser()
        cache: dict[int, int] = {}
        for name, data in parser.read(str(self.fpath)):
            if name == "ChannelStatus":
                # sbf_parser keys the sub-block list "SatInfo";
                # keep "ChannelSatInfo" as a legacy fallback.
                for sat in data.get("SatInfo") or data.get("ChannelSatInfo") or []:
                    svid = int(sat["SVID"])
                    if svid != 0:
                        cache[svid] = int(sat["FreqNr"])
        return cache

    # ------------------------------------------------------------------
    # GNSSDataReader abstract property implementations
    # ------------------------------------------------------------------

    @cached_property
    def file_hash(self) -> str:
        """SHA-256 hex digest of the file (first 16 characters).

        Returns
        -------
        str
            16-character hexadecimal prefix of the SHA-256 hash.
        """
        h = hashlib.sha256(self.fpath.read_bytes())
        return h.hexdigest()[:16]

    @cached_property
    def start_time(self) -> datetime:
        """Return the timestamp of the first decoded epoch.

        Returns
        -------
        datetime
            Timezone-aware UTC datetime of the first observation epoch.

        Raises
        ------
        LookupError
            If the file contains no decodable epochs.
        """
        for epoch in self.iter_epochs():
            return epoch.timestamp
        raise LookupError(f"No epochs in {self.fpath}")

    @cached_property
    def end_time(self) -> datetime:
        """Return the timestamp of the last decoded epoch.

        Returns
        -------
        datetime
            Timezone-aware UTC datetime of the last observation epoch.

        Raises
        ------
        LookupError
            If the file contains no decodable epochs.
        """
        last: datetime | None = None
        for epoch in self.iter_epochs():
            last = epoch.timestamp
        if last is None:
            raise LookupError(f"No epochs in {self.fpath}")
        return last

    @cached_property
    def systems(self) -> list[str]:
        """Return sorted list of GNSS system codes present in the file.

        Returns
        -------
        list of str
            Sorted list of RINEX system letters (e.g. ``["E", "G", "R"]``).
        """
        return sorted(
            {obs.system for ep in self.iter_epochs() for obs in ep.observations}
        )

    @cached_property
    def num_satellites(self) -> int:
        """Return the number of unique satellites observed in the file.

        Returns
        -------
        int
            Count of unique ``system + PRN`` pairs across all epochs.
        """
        return len(
            {
                f"{obs.system}{obs.prn:02d}"
                for ep in self.iter_epochs()
                for obs in ep.observations
            }
        )

    # ------------------------------------------------------------------
    # Epoch count (existing cached property — kept for backward compat)
    # ------------------------------------------------------------------

    @cached_property
    def num_epochs(self) -> int:
        """Count the number of MeasEpoch blocks in the file.

        Returns
        -------
        int
            Total MeasEpoch block count (one per observation epoch).

        Notes
        -----
        Scans the entire file once; result is cached.
        """
        parser = sbf_parser.SbfParser()
        count = sum(
            1 for name, _ in parser.read(str(self.fpath)) if name == "MeasEpoch"
        )
        log.debug("sbf_epoch_count", fpath=str(self.fpath), num_epochs=count)
        return count

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    @cached_property
    def header(self) -> SbfHeader:
        """Parse the first ReceiverSetup block in the file.

        Returns
        -------
        SbfHeader
            Receiver metadata.

        Raises
        ------
        LookupError
            If no ReceiverSetup block is found.
        """
        parser = sbf_parser.SbfParser()
        for name, data in parser.read(str(self.fpath)):
            if name == "ReceiverSetup":
                return SbfHeader(
                    marker_name=_decode_bytes(data["MarkerName"]),
                    marker_number=_decode_bytes(data["MarkerNumber"]),
                    observer=_decode_bytes(data["Observer"]),
                    agency=_decode_bytes(data["Agency"]),
                    rx_serial=_decode_bytes(data["RxSerialNumber"]),
                    rx_name=_decode_bytes(data["RxName"]),
                    rx_version=_decode_bytes(data["RxVersion"]),
                    ant_serial=_decode_bytes(data["AntSerialNbr"]),
                    ant_type=_decode_bytes(data["AntType"]),
                    delta_h=float(data["deltaH"]) * UREG.meter,
                    delta_e=float(data["deltaE"]) * UREG.meter,
                    delta_n=float(data["deltaN"]) * UREG.meter,
                    latitude_rad=float(data["Latitude"]),
                    longitude_rad=float(data["Longitude"]),
                    height_m=float(data["Height"]) * UREG.meter,
                    gnss_fw_version=_decode_bytes(data["GNSSFWVersion"]),
                    product_name=_decode_bytes(data["ProductName"]),
                )
        raise LookupError(f"No ReceiverSetup block found in {self.fpath}")

    # ------------------------------------------------------------------
    # Epoch iterator
    # ------------------------------------------------------------------

    def iter_epochs(self) -> Iterator[SbfEpoch]:
        """Iterate over decoded MeasEpoch blocks.

        Yields decoded :class:`SbfEpoch` objects with all signal observations
        converted to physical units as :class:`pint.Quantity`.

        Yields
        ------
        SbfEpoch
            One decoded observation epoch.

        Notes
        -----
        - The file is scanned from start to finish on each call.
        - The :attr:`_freq_nr_cache` is pre-populated from ALL ChannelStatus
          blocks before the first call, so all GLONASS FDMA epochs have
          accurate carrier frequencies.
        - ``delta_ls`` (leap seconds) is taken from the most recent
          ReceiverTime block; defaults to 18 if none has been seen yet.
        """
        parser = sbf_parser.SbfParser()
        freq_nr_cache: dict[int, int] = self._freq_nr_cache.copy()
        delta_ls: int = _DEFAULT_DELTA_LS

        for name, data in parser.read(str(self.fpath)):
            match name:
                case "ReceiverTime":
                    _dls = int(data["DeltaLS"])
                    if _dls != -128:  # -128 = DNU sentinel in SBF spec
                        delta_ls = _dls

                case "ChannelStatus":
                    # sbf_parser keys the sub-block list "SatInfo";
                    # keep "ChannelSatInfo" as a legacy fallback.
                    for sat in data.get("SatInfo") or data.get("ChannelSatInfo") or []:
                        svid = int(sat["SVID"])
                        if svid != 0:
                            freq_nr_cache[svid] = int(sat["FreqNr"])

                case "MeasEpoch":
                    epoch = self._decode_epoch(data, freq_nr_cache, delta_ls)
                    if epoch is not None:
                        yield epoch

    # ------------------------------------------------------------------
    # Dataset construction — observations
    # ------------------------------------------------------------------

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        pad_global_sid: bool = True,
        strip_fillval: bool = True,
        **kwargs: object,
    ) -> xr.Dataset:
        """Convert SBF observations to an ``(epoch, sid)`` xarray Dataset.

        Produces the same structure as :class:`~canvod.readers.rinex.v3_04.Rnxv3Obs`
        and passes :func:`~canvod.readers.base.validate_dataset`.

        Parameters
        ----------
        keep_data_vars : list of str, optional
            Data variables to retain.  If ``None``, all five variables are
            kept: ``SNR``, ``Pseudorange``, ``Phase``, ``Doppler``, ``SSI``.
            Note: ``LLI`` is not produced — SBF has no loss-of-lock indicator.
        pad_global_sid : bool, default True
            If ``True``, pads the dataset to the global SID space via
            :func:`canvod.auxiliary.preprocessing.pad_to_global_sid`.
        strip_fillval : bool, default True
            If ``True``, removes fill values via
            :func:`canvod.auxiliary.preprocessing.strip_fillvalue`.
        **kwargs
            Ignored (for ABC compatibility).

        Returns
        -------
        xr.Dataset
            Dataset with dimensions ``(epoch, sid)`` that passes
            :func:`~canvod.readers.base.validate_dataset`.
        """
        import math

        freq_nr_cache = self._freq_nr_cache.copy()
        # PERF C3: memoize (svid, sig_num) → sid props; only a few hundred
        # unique pairs exist per file vs ~1M observation decodes.
        _sid_memo: dict[tuple[int, int], dict[str, Any] | None] = {}

        # --- Single pass: collect timestamps, SID properties, and per-epoch obs ---
        # Stores per-epoch obs as dicts (SID → value) so we only scan the file once.
        # Array construction happens afterwards in fast in-memory loops.
        sid_props: dict[str, dict[str, Any]] = {}
        timestamps: list[np.datetime64] = []
        # Per-epoch accumulator: list of (snr_dict, pr_dict, ph_dict, dop_dict)
        epoch_rows: list[
            tuple[
                dict[str, float],
                dict[str, float],
                dict[str, float],
                dict[str, float],
                dict[str, int],
                dict[str, int],
            ]
        ] = []

        for epoch in self.iter_epochs():
            ts_np = np.datetime64(epoch.timestamp.replace(tzinfo=None), "ns")
            timestamps.append(ts_np)

            e_snr: dict[str, float] = {}
            e_pr: dict[str, float] = {}
            e_ph: dict[str, float] = {}
            e_dop: dict[str, float] = {}
            e_smooth: dict[str, int] = {}
            e_half: dict[str, int] = {}

            for obs in epoch.observations:
                _key = (obs.svid, obs.signal_num)
                if _key not in _sid_memo:
                    _sid_memo[_key] = _sid_props_from_obs(
                        obs.svid, obs.signal_num, freq_nr_cache
                    )
                props = _sid_memo[_key]
                if props is None:
                    continue
                sid = props["sid"]
                if sid not in sid_props:
                    sid_props[sid] = props
                if obs.cn0 is not None:
                    e_snr[sid] = float(obs.cn0.to(UREG.dBHz).magnitude)
                if obs.pseudorange is not None:
                    e_pr[sid] = float(obs.pseudorange.to(UREG.meter).magnitude)
                if obs.phase_cycles is not None:
                    e_ph[sid] = obs.phase_cycles
                if obs.doppler is not None:
                    e_dop[sid] = float(obs.doppler.to(UREG.Hz).magnitude)
                # ObsInfo bit 0 = smoothing, bit 2 = half-cycle ambiguity
                e_smooth[sid] = int(obs.obs_info & 0x01)
                e_half[sid] = int((obs.obs_info >> 2) & 0x01)

            epoch_rows.append((e_snr, e_pr, e_ph, e_dop, e_smooth, e_half))

        sorted_sids = sorted(sid_props)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        n_epochs = len(timestamps)
        n_sids = len(sorted_sids)

        # Allocate arrays (LLI is dropped — SBF has no loss-of-lock indicator)
        snr_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["SNR"])
        pr_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Pseudorange"])
        ph_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Phase"])
        dop_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Doppler"])
        # ObsInfo flags: -1 = no observation, 0 = flag clear, 1 = flag set
        smoothing_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)
        half_cycle_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)

        for t_idx, (e_snr, e_pr, e_ph, e_dop, e_smooth, e_half) in enumerate(
            epoch_rows
        ):
            for sid, val in e_snr.items():
                snr_arr[t_idx, sid_to_idx[sid]] = val
            for sid, val in e_pr.items():
                pr_arr[t_idx, sid_to_idx[sid]] = val
            for sid, val in e_ph.items():
                ph_arr[t_idx, sid_to_idx[sid]] = val
            for sid, val in e_dop.items():
                dop_arr[t_idx, sid_to_idx[sid]] = val
            for sid, flag in e_smooth.items():
                smoothing_arr[t_idx, sid_to_idx[sid]] = flag
            for sid, flag in e_half.items():
                half_cycle_arr[t_idx, sid_to_idx[sid]] = flag

        # SBF has no native RINEX-style SSI field -- derive it from the
        # continuous CN0 just filled above.
        ssi_arr = _snr_dbhz_to_ssi(snr_arr).astype(DTYPES["SSI"])

        # Build coordinate arrays
        freq_center = np.asarray(
            [sid_props[s]["freq_center"] for s in sorted_sids],
            dtype=DTYPES["freq_center"],
        )
        freq_min = np.asarray(
            [sid_props[s]["freq_min"] for s in sorted_sids], dtype=DTYPES["freq_min"]
        )
        freq_max = np.asarray(
            [sid_props[s]["freq_max"] for s in sorted_sids], dtype=DTYPES["freq_max"]
        )

        coords: dict[str, Any] = {
            "epoch": ("epoch", timestamps, COORDS_METADATA["epoch"]),
            "sid": xr.DataArray(
                np.array(sorted_sids, dtype=object),
                dims=["sid"],
                attrs=COORDS_METADATA["sid"],
            ),
            "sv": (
                "sid",
                np.array([sid_props[s]["sv"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["sv"],
            ),
            "system": (
                "sid",
                np.array([sid_props[s]["system"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["system"],
            ),
            "band": (
                "sid",
                np.array([sid_props[s]["band"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["band"],
            ),
            "code": (
                "sid",
                np.array([sid_props[s]["code"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["code"],
            ),
            "freq_center": ("sid", freq_center, COORDS_METADATA["freq_center"]),
            "freq_min": ("sid", freq_min, COORDS_METADATA["freq_min"]),
            "freq_max": ("sid", freq_max, COORDS_METADATA["freq_max"]),
        }

        attrs = cast(dict[str, Any], self._build_attrs())

        # Add ECEF position from ReceiverSetup header for pipeline compatibility.
        # ECEFPosition.from_ds_metadata() reads "APPROX POSITION X/Y/Z".
        try:
            import pymap3d as pm

            hdr = self.header
            lat_deg = math.degrees(hdr.latitude_rad)
            lon_deg = math.degrees(hdr.longitude_rad)
            h_m = float(hdr.height_m.to(UREG.meter).magnitude)
            x, y, z = pm.geodetic2ecef(lat_deg, lon_deg, h_m)
            attrs["APPROX POSITION X"] = float(x)
            attrs["APPROX POSITION Y"] = float(y)
            attrs["APPROX POSITION Z"] = float(z)
        except LookupError, AttributeError:
            pass  # SBF file without a ReceiverSetup block

        ds = xr.Dataset(
            data_vars={
                "SNR": (["epoch", "sid"], snr_arr, CN0_METADATA),
                "Pseudorange": (
                    ["epoch", "sid"],
                    pr_arr,
                    OBSERVABLES_METADATA["Pseudorange"],
                ),
                "Phase": (["epoch", "sid"], ph_arr, OBSERVABLES_METADATA["Phase"]),
                "Doppler": (["epoch", "sid"], dop_arr, OBSERVABLES_METADATA["Doppler"]),
                "SSI": (["epoch", "sid"], ssi_arr, OBSERVABLES_METADATA["SSI"]),
                "Smoothing": (
                    ["epoch", "sid"],
                    smoothing_arr,
                    _SMOOTHING_FLAG_ATTRS,
                ),
                "HalfCycle": (
                    ["epoch", "sid"],
                    half_cycle_arr,
                    _HALF_CYCLE_ATTRS,
                ),
            },
            coords=coords,
            attrs=attrs,
        )

        # Post-process
        if keep_data_vars is not None:
            for var in list(ds.data_vars):
                if var not in keep_data_vars:
                    ds = ds.drop_vars([var])

        if pad_global_sid:
            from canvod.auxiliary.preprocessing import pad_to_global_sid

            ds = pad_to_global_sid(
                ds,
                keep_sids=cast(list[str] | None, kwargs.get("keep_sids")),
            )

        if strip_fillval:
            from canvod.auxiliary.preprocessing import strip_fillvalue

            ds = strip_fillvalue(ds)

        validate_dataset(ds, required_vars=keep_data_vars)
        return ds

    # ------------------------------------------------------------------
    # Dataset construction — metadata
    # ------------------------------------------------------------------

    def to_metadata_ds(
        self, pad_global_sid: bool = True, **kwargs: object
    ) -> xr.Dataset:
        """Decode SBF metadata blocks to an ``(epoch, sid)`` xarray Dataset.

        Decodes PVTGeodetic, DOP, ReceiverStatus, SatVisibility, and
        MeasExtra blocks in a single file scan.

        Parameters
        ----------
        pad_global_sid : bool, default True
            If ``True``, pads to the global SID space via
            :func:`canvod.auxiliary.preprocessing.pad_to_global_sid`.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions ``(epoch, sid)``.  Epoch-level scalars
            (PDOP, NrSV, …) are 1-D ``(epoch,)`` coordinates.  Satellite
            geometry (theta, phi) and signal quality (MPCorrection, …) are
            ``(epoch, sid)`` data variables.
        """
        parser = sbf_parser.SbfParser()
        # PERF C4: start with an empty FreqNr map instead of the
        # _freq_nr_cache pre-scan (which costs a full extra file pass);
        # the map is filled on-the-fly from ChannelStatus blocks, which
        # appear within the first epoch in practice.
        freq_nr_cache: dict[int, int] = {}
        # PERF C3: memoize (svid, sig_num) → sid props; only a few hundred
        # unique pairs exist per file vs ~1M observation decodes.
        _sid_memo: dict[tuple[int, int], dict[str, Any] | None] = {}

        pending: dict[str, Any] = {
            "pvt": None,
            "dop": None,
            "status": None,
            "satvis": [],
            "extra": [],
            "qualind": None,
            "rfstatus": None,
            "chanstatus": None,
        }

        # Each record: (ts, pvt, dop, status, satvis, extra,
        #               qualind, rfstatus, chanstatus, obs_map)
        records: list[tuple[Any, ...]] = []

        # sid discovery — same logic as to_ds() pass 1
        sid_props: dict[str, dict[str, Any]] = {}

        delta_ls: int = _DEFAULT_DELTA_LS

        for name, data in parser.read(str(self.fpath)):
            match name:
                case "ReceiverTime":
                    _dls = int(data["DeltaLS"])
                    if _dls != -128:  # -128 = DNU sentinel in SBF spec
                        delta_ls = _dls

                case "ChannelStatus":
                    pending["chanstatus"] = data
                    # sbf_parser keys the sub-block list "SatInfo";
                    # keep "ChannelSatInfo" as a legacy fallback.
                    for sat in data.get("SatInfo") or data.get("ChannelSatInfo") or []:
                        svid_cs = int(sat["SVID"])
                        if svid_cs != 0:
                            freq_nr_cache[svid_cs] = int(sat["FreqNr"])

                case "PVTGeodetic":
                    pending["pvt"] = data

                case "DOP":
                    pending["dop"] = data

                case "ReceiverStatus":
                    pending["status"] = data

                case "SatVisibility":
                    pending["satvis"] = list(data.get("SatInfo", []))

                case "MeasExtra":
                    pending["extra"] = list(data.get("MeasExtraChannel", []))

                case "QualityInd":
                    pending["qualind"] = data

                case "RFStatus":
                    pending["rfstatus"] = data

                case "MeasEpoch":
                    tow_ms = int(data["TOW"])
                    wn = int(data["WNc"])
                    ts = _tow_wn_to_utc(tow_ms, wn, delta_ls)
                    obs_map = _build_obs_map(data)

                    # Discover sids from Type1 and Type2 sub-blocks
                    for t1 in data.get("Type_1", []):
                        svid1 = int(t1["SVID"])
                        _key1 = (
                            svid1,
                            decode_signal_num(int(t1["Type"]), int(t1["ObsInfo"])),
                        )
                        if _key1 not in _sid_memo:
                            _sid_memo[_key1] = _sid_props_from_obs(
                                svid1, _key1[1], freq_nr_cache
                            )
                        props1 = _sid_memo[_key1]
                        if props1 is not None and props1["sid"] not in sid_props:
                            sid_props[props1["sid"]] = props1

                        for t2 in t1.get("Type_2", []):
                            _key2 = (
                                svid1,
                                decode_signal_num(int(t2["Type"]), int(t2["ObsInfo"])),
                            )
                            if _key2 not in _sid_memo:
                                _sid_memo[_key2] = _sid_props_from_obs(
                                    svid1, _key2[1], freq_nr_cache
                                )
                            props2 = _sid_memo[_key2]
                            if props2 is not None and props2["sid"] not in sid_props:
                                sid_props[props2["sid"]] = props2

                    records.append(
                        (
                            ts,
                            pending["pvt"],
                            pending["dop"],
                            pending["status"],
                            list(pending["satvis"]),
                            list(pending["extra"]),
                            pending["qualind"],
                            pending["rfstatus"],
                            pending["chanstatus"],
                            obs_map,
                        )
                    )
                    pending = {
                        "pvt": None,
                        "dop": None,
                        "status": None,
                        "satvis": [],
                        "extra": [],
                        "qualind": None,
                        "rfstatus": None,
                        "chanstatus": None,
                    }

        # Build index structures
        sorted_sids = sorted(sid_props)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        n_epochs = len(records)
        n_sids = len(sorted_sids)

        # sv → list of sid indices (for SatVisibility broadcasting)
        sids_for_sv: dict[str, list[int]] = {}
        for sid in sorted_sids:
            sv = sid_props[sid]["sv"]
            sids_for_sv.setdefault(sv, []).append(sid_to_idx[sid])

        # (epoch, sid) data variable arrays
        theta_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        phi_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        rise_set_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)
        mp_corr_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        smoothing_corr_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        code_var_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        carr_var_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        lock_time_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        cum_loss_cont_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        car_mp_corr_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        cn0_highres_arr = np.full((n_epochs, n_sids), np.nan, dtype=np.float32)
        # ChannelStatus raw bitfields, broadcast per-sv (0 = idle / no info)
        tracking_status_arr = np.zeros((n_epochs, n_sids), dtype=np.uint16)
        pvt_status_arr = np.zeros((n_epochs, n_sids), dtype=np.uint16)

        # (epoch,) scalar coordinate arrays
        pdop_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        hdop_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        vdop_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        n_sv_arr = np.full(n_epochs, -1, dtype=np.int16)
        h_acc_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        v_acc_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        pvt_mode_arr = np.full(n_epochs, -1, dtype=np.int8)
        mean_corr_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        cpu_load_arr = np.full(n_epochs, -1, dtype=np.int8)
        temp_arr = np.full(n_epochs, np.nan, dtype=np.float32)
        rx_error_arr = np.full(n_epochs, 0, dtype=np.int32)
        # QualityInd scores (0-10; -1 = unknown / block absent)
        qual_overall_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_gnss_main_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_rf_main_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_cpu_arr = np.full(n_epochs, -1, dtype=np.int8)
        qual_scint_arr = np.full(n_epochs, -1, dtype=np.int8)
        # RFStatus flags (0/1; -1 = block absent)
        spoofing_arr = np.full(n_epochs, -1, dtype=np.int8)
        nma_fail_arr = np.full(n_epochs, -1, dtype=np.int8)

        timestamps: list[np.datetime64] = []

        # Fill arrays from records
        for t_idx, (
            ts,
            pvt,
            dop,
            status,
            satvis,
            extra,
            qualind,
            rfstatus,
            chanstatus,
            obs_map,
        ) in enumerate(records):
            timestamps.append(np.datetime64(ts.replace(tzinfo=None), "ns"))

            # DOP block → pdop, hdop, vdop
            if dop is not None:
                try:
                    # PDOP/HDOP/VDOP: u2, 0.01/LSB, Do-Not-Use 0 → NaN
                    raw_pdop = int(dop["PDOP"])
                    if raw_pdop != 0:
                        pdop_arr[t_idx] = raw_pdop * 0.01
                    raw_hdop = int(dop["HDOP"])
                    if raw_hdop != 0:
                        hdop_arr[t_idx] = raw_hdop * 0.01
                    raw_vdop = int(dop["VDOP"])
                    if raw_vdop != 0:
                        vdop_arr[t_idx] = raw_vdop * 0.01
                except KeyError, TypeError, ValueError:
                    pass

            # PVTGeodetic → n_sv, accuracy, mode, correction age
            if pvt is not None:
                try:
                    # NrSV: u1, Do-Not-Use 255 → sentinel -1
                    raw_nrsv = int(pvt.get("NrSV", pvt.get("NrSVAnt", 255)))
                    n_sv_arr[t_idx] = -1 if raw_nrsv == 255 else raw_nrsv
                    raw_hacc = int(pvt["HAccuracy"])
                    if raw_hacc != 65535:
                        h_acc_arr[t_idx] = raw_hacc * 0.01
                    raw_vacc = int(pvt["VAccuracy"])
                    if raw_vacc != 65535:
                        v_acc_arr[t_idx] = raw_vacc * 0.01
                    # Mode: bits 0-3 = PVT solution mode; bits 4-7 are
                    # flag bits (e.g. 2D flag) that must be masked off.
                    pvt_mode_arr[t_idx] = int(pvt["Mode"]) & 0x0F
                    # MeanCorrAge: u2, 0.01 s/LSB, Do-Not-Use 65535 → NaN
                    raw_mca = int(pvt["MeanCorrAge"])
                    if raw_mca != 65535:
                        mean_corr_arr[t_idx] = raw_mca * 0.01
                    # Also pick up DOP from PVTGeodetic if DOP block absent
                    if np.isnan(pdop_arr[t_idx]):
                        raw_pdop = int(pvt["PDOP"])
                        if raw_pdop != 0:
                            pdop_arr[t_idx] = raw_pdop * 0.01
                        raw_hdop = int(pvt["HDOP"])
                        if raw_hdop != 0:
                            hdop_arr[t_idx] = raw_hdop * 0.01
                        raw_vdop = int(pvt["VDOP"])
                        if raw_vdop != 0:
                            vdop_arr[t_idx] = raw_vdop * 0.01
                except KeyError, TypeError, ValueError:
                    pass

            # ReceiverStatus → cpu_load, temperature, rx_error
            if status is not None:
                try:
                    # CPULoad: u1, %, Do-Not-Use 255 → sentinel -1
                    raw_cpu = int(status["CPULoad"])
                    cpu_load_arr[t_idx] = -1 if raw_cpu == 255 else raw_cpu
                    raw_temp = int(status["Temperature"])
                    if raw_temp != 0:  # 0 is DoNotUse (RefGuide p.397)
                        temp_arr[t_idx] = float(raw_temp - 100)
                    rx_error_arr[t_idx] = int(status["RxError"])
                except KeyError, TypeError, ValueError:
                    pass

            # SatVisibility → broadcast theta/phi to all sids for that sv
            for sat_info in satvis:
                try:
                    svid_raw = int(sat_info["SVID"])
                    sys_code, prn = decode_svid(svid_raw)
                    sv = f"{sys_code}{prn:02d}"
                    theta_deg = 90.0 - int(sat_info["Elevation"]) * 0.01
                    phi_deg = int(sat_info["Azimuth"]) * 0.01
                    # RiseSet: u1, 255 = unknown → sentinel -1 (int8-safe)
                    rs_raw = int(sat_info["RiseSet"])
                    rs = -1 if rs_raw == 255 else rs_raw
                    for s_idx in sids_for_sv.get(sv, []):
                        theta_arr[t_idx, s_idx] = theta_deg
                        phi_arr[t_idx, s_idx] = phi_deg
                        rise_set_arr[t_idx, s_idx] = rs
                except KeyError, TypeError, ValueError:
                    pass

            # MeasExtra → per-(epoch, sid) signal quality
            for ch in extra:
                try:
                    type_byte = int(ch["Type"])
                    info_byte = int(ch.get("ObsInfo", ch.get("Info", 0)))
                    sig_num = decode_signal_num(type_byte, info_byte)
                    rx_ch = int(ch["RxChannel"])
                    svid = obs_map.get((rx_ch, sig_num))
                    if svid is None:
                        continue
                    sig_def = SIGNAL_TABLE.get(sig_num)
                    if sig_def is None:
                        continue
                    sys_code2, prn2 = decode_svid(svid)
                    sv2 = f"{sys_code2}{prn2:02d}"
                    sid = f"{sv2}|{sig_def.band}|{sig_def.code}"
                    s_idx = sid_to_idx.get(sid)
                    if s_idx is None:
                        continue
                    mp_raw = int(ch.get("MPCorrection ", ch.get("MPCorrection", 0)))
                    mp_corr_arr[t_idx, s_idx] = mp_raw * 0.001
                    # SmoothingCorr: i2, scale 0.001 m/LSB
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    raw_sc = ch.get("SmoothingCorr")
                    if raw_sc is not None:
                        smoothing_corr_arr[t_idx, s_idx] = int(raw_sc) * 0.001
                    raw_cv = ch.get("CodeVar")
                    # CodeVar: u2, scale 0.0001 m²/LSB, Do-Not-Use 65535
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_cv is not None and int(raw_cv) != 65535:
                        code_var_arr[t_idx, s_idx] = int(raw_cv) * 1e-4
                    raw_rv = ch.get("CarrierVar")
                    # CarrierVar: u2, scale 1 mcycle²/LSB, Do-Not-Use 65535
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_rv is not None and int(raw_rv) != 65535:
                        carr_var_arr[t_idx, s_idx] = float(raw_rv)
                    raw_lt = ch.get("LockTime")
                    # LockTime: u2, scale 1 s/LSB, Do-Not-Use 65535, clipped to 65534 s
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_lt is not None and int(raw_lt) != 65535:
                        lock_time_arr[t_idx, s_idx] = float(raw_lt)
                    raw_clc = ch.get("CumLossCont")
                    # CumLossCont: u1, modulo-256 counter, no Do-Not-Use
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_clc is not None:
                        cum_loss_cont_arr[t_idx, s_idx] = float(int(raw_clc))
                    raw_cmc = ch.get("CarMPCorr")
                    # CarMPCorr: i1, scale 1/512 cycles/LSB (1.953125 mcycles/LSB)
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_cmc is not None:
                        car_mp_corr_arr[t_idx, s_idx] = int(raw_cmc) / 512.0
                    raw_misc = ch.get("Misc")
                    # Misc bits 0-2: CN0HighRes (u3, 0-7), scale 0.03125 dB-Hz/LSB
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_misc is not None:
                        cn0_hr = int(raw_misc) & 0x07
                        cn0_highres_arr[t_idx, s_idx] = cn0_hr * 0.03125
                except KeyError, TypeError, ValueError:
                    pass

            # QualityInd → receiver quality indicator scores
            if qualind is not None:
                q_vals = _decode_quality_indicators(qualind)
                qual_overall_arr[t_idx] = q_vals.get(0, -1)
                qual_gnss_main_arr[t_idx] = q_vals.get(1, -1)
                qual_rf_main_arr[t_idx] = q_vals.get(11, -1)
                qual_cpu_arr[t_idx] = q_vals.get(21, -1)
                qual_scint_arr[t_idx] = q_vals.get(29, -1)

            # RFStatus → spoofing / NMA authentication flags
            if rfstatus is not None:
                try:
                    rf_flags = int(rfstatus["Flags"])
                    spoofing_arr[t_idx] = rf_flags & 0x01
                    nma_fail_arr[t_idx] = (rf_flags >> 1) & 0x01
                except KeyError, TypeError, ValueError:
                    pass

            # ChannelStatus → raw tracking / PVT status bitfields,
            # broadcast to all SIDs of each satellite (Main antenna only)
            if chanstatus is not None:
                for sv_trk, trk_raw, pvt_raw in _extract_tracking_info(chanstatus):
                    for s_idx in sids_for_sv.get(sv_trk, []):
                        tracking_status_arr[t_idx, s_idx] = trk_raw
                        pvt_status_arr[t_idx, s_idx] = pvt_raw

        # Build Dataset
        freq_center = np.asarray(
            [sid_props[s]["freq_center"] for s in sorted_sids], dtype=np.float32
        )
        freq_min = np.asarray(
            [sid_props[s]["freq_min"] for s in sorted_sids], dtype=np.float32
        )
        freq_max = np.asarray(
            [sid_props[s]["freq_max"] for s in sorted_sids], dtype=np.float32
        )

        coords: dict[str, Any] = {
            "epoch": ("epoch", timestamps, COORDS_METADATA["epoch"]),
            "sid": xr.DataArray(
                np.array(sorted_sids, dtype=object),
                dims=["sid"],
                attrs=COORDS_METADATA["sid"],
            ),
            "sv": (
                "sid",
                np.array([sid_props[s]["sv"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["sv"],
            ),
            "system": (
                "sid",
                np.array([sid_props[s]["system"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["system"],
            ),
            "band": (
                "sid",
                np.array([sid_props[s]["band"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["band"],
            ),
            "code": (
                "sid",
                np.array([sid_props[s]["code"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["code"],
            ),
            "freq_center": ("sid", freq_center, COORDS_METADATA["freq_center"]),
            "freq_min": ("sid", freq_min, COORDS_METADATA["freq_min"]),
            "freq_max": ("sid", freq_max, COORDS_METADATA["freq_max"]),
            # Epoch-level scalars (1-D over epoch)
            "pdop": ("epoch", pdop_arr, _PDOP_ATTRS),
            "hdop": ("epoch", hdop_arr, _HDOP_ATTRS),
            "vdop": ("epoch", vdop_arr, _VDOP_ATTRS),
            "n_sv": ("epoch", n_sv_arr, _N_SV_ATTRS),
            "h_accuracy_m": ("epoch", h_acc_arr, _H_ACCURACY_ATTRS),
            "v_accuracy_m": ("epoch", v_acc_arr, _V_ACCURACY_ATTRS),
            "pvt_mode": ("epoch", pvt_mode_arr, _PVT_MODE_ATTRS),
            "mean_corr_age_s": ("epoch", mean_corr_arr, _MEAN_CORR_AGE_ATTRS),
            "cpu_load": ("epoch", cpu_load_arr, _CPU_LOAD_ATTRS),
            "temperature_c": ("epoch", temp_arr, _TEMPERATURE_ATTRS),
            "rx_error": ("epoch", rx_error_arr, _RX_ERROR_ATTRS),
            "qual_overall": ("epoch", qual_overall_arr, _QUAL_OVERALL_ATTRS),
            "qual_gnss_main": ("epoch", qual_gnss_main_arr, _QUAL_GNSS_MAIN_ATTRS),
            "qual_rf_main": ("epoch", qual_rf_main_arr, _QUAL_RF_MAIN_ATTRS),
            "qual_cpu": ("epoch", qual_cpu_arr, _QUAL_CPU_ATTRS),
            "qual_scintillation": ("epoch", qual_scint_arr, _QUAL_SCINT_ATTRS),
            "spoofing_flag": ("epoch", spoofing_arr, _SPOOFING_FLAG_ATTRS),
            "nma_fail_flag": ("epoch", nma_fail_arr, _NMA_FAIL_ATTRS),
        }

        attrs = self._build_attrs()

        ds = xr.Dataset(
            data_vars={
                "broadcast_theta": (
                    ["epoch", "sid"],
                    np.deg2rad(theta_arr),
                    _BROADCAST_THETA_ATTRS,
                ),
                "broadcast_phi": (
                    ["epoch", "sid"],
                    np.deg2rad(phi_arr),
                    _BROADCAST_PHI_ATTRS,
                ),
                "rise_set": (["epoch", "sid"], rise_set_arr, _RISE_SET_ATTRS),
                "mp_correction_m": (
                    ["epoch", "sid"],
                    mp_corr_arr,
                    _MP_CORRECTION_ATTRS,
                ),
                "smoothing_corr_m": (
                    ["epoch", "sid"],
                    smoothing_corr_arr,
                    _SMOOTHING_CORR_ATTRS,
                ),
                "code_var": (["epoch", "sid"], code_var_arr, _CODE_VAR_ATTRS),
                "carrier_var": (["epoch", "sid"], carr_var_arr, _CARRIER_VAR_ATTRS),
                "lock_time_s": (["epoch", "sid"], lock_time_arr, _LOCK_TIME_ATTRS),
                "cum_loss_cont": (
                    ["epoch", "sid"],
                    cum_loss_cont_arr,
                    _CUM_LOSS_CONT_ATTRS,
                ),
                "car_mp_corr_cycles": (
                    ["epoch", "sid"],
                    car_mp_corr_arr,
                    _CAR_MP_CORR_ATTRS,
                ),
                "cn0_highres_correction": (
                    ["epoch", "sid"],
                    cn0_highres_arr,
                    _CN0_HIGHRES_CORRECTION_ATTRS,
                ),
                "tracking_status_raw": (
                    ["epoch", "sid"],
                    tracking_status_arr,
                    _TRACKING_STATUS_RAW_ATTRS,
                ),
                "pvt_status_raw": (
                    ["epoch", "sid"],
                    pvt_status_arr,
                    _PVT_STATUS_RAW_ATTRS,
                ),
            },
            coords=coords,
            attrs=attrs,
        )

        if pad_global_sid:
            from canvod.auxiliary.preprocessing import pad_to_global_sid

            ds = pad_to_global_sid(
                ds,
                keep_sids=cast(list[str] | None, kwargs.get("keep_sids")),
            )

        return ds

    # ------------------------------------------------------------------
    # Combined single-pass: observations + auxiliary metadata
    # ------------------------------------------------------------------

    def to_ds_and_auxiliary(
        self,
        keep_data_vars: list[str] | None = None,
        pad_global_sid: bool = True,
        strip_fillval: bool = True,
        store_raw_observables: bool = True,
        **kwargs: object,
    ) -> tuple[xr.Dataset, dict[str, xr.Dataset]]:
        """Single file scan producing both the obs dataset and the SBF metadata dataset.

        Performs ONE ``parser.read()`` pass, collecting MeasEpoch observations
        and PVTGeodetic/DOP/SatVisibility/MeasExtra metadata blocks simultaneously.
        ``to_ds()`` and ``to_metadata_ds()`` remain unchanged for standalone use.

        Parameters
        ----------
        keep_data_vars : list of str, optional
            Data variables to retain in the obs dataset.
        pad_global_sid : bool, default True
            Pad obs dataset to the global SID space.
        strip_fillval : bool, default True
            Strip fill values from the obs dataset.
        store_raw_observables : bool, default True
            Add pre-correction "raw" observable variables to the obs dataset:
            ``SNR_raw``, ``Pseudorange_unsmoothed``, ``Pseudorange_raw``,
            ``Phase_raw``.  Set to ``False`` to reduce dataset size when these
            are not needed.
        **kwargs
            Forwarded to ``pad_to_global_sid`` (e.g. ``keep_sids``).

        Returns
        -------
        tuple[xr.Dataset, dict[str, xr.Dataset]]
            ``(obs_ds, {"sbf_obs": meta_ds})``.
        """
        import math

        parser = sbf_parser.SbfParser()
        # PERF C4: start with an empty FreqNr map instead of the
        # _freq_nr_cache pre-scan (which costs a full extra file pass);
        # the map is filled on-the-fly from ChannelStatus blocks, which
        # appear within the first epoch in practice.
        freq_nr_cache: dict[int, int] = {}
        # PERF C3: memoize (svid, sig_num) → sid props; only a few hundred
        # unique pairs exist per file vs ~1M observation decodes.
        _sid_memo: dict[tuple[int, int], dict[str, Any] | None] = {}
        delta_ls: int = _DEFAULT_DELTA_LS

        # Separate sid discovery for obs (matches to_ds) and metadata (matches to_metadata_ds)
        sid_props_obs: dict[str, dict[str, Any]] = {}
        sid_props_meta: dict[str, dict[str, Any]] = {}

        # Obs-side accumulators (same as to_ds)
        timestamps_obs: list[np.datetime64] = []
        epoch_rows: list[
            tuple[
                dict[str, float],
                dict[str, float],
                dict[str, float],
                dict[str, float],
                dict[str, int],
                dict[str, int],
            ]
        ] = []

        # Metadata-side accumulators (same as to_metadata_ds)
        pending: dict[str, Any] = {
            "pvt": None,
            "dop": None,
            "status": None,
            "satvis": [],
            "extra": [],
            "qualind": None,
            "rfstatus": None,
            "chanstatus": None,
        }
        records: list[tuple[Any, ...]] = []

        for name, data in parser.read(str(self.fpath)):
            match name:
                case "ReceiverTime":
                    _dls = int(data["DeltaLS"])
                    if _dls != -128:  # -128 = DNU sentinel in SBF spec
                        delta_ls = _dls

                case "ChannelStatus":
                    pending["chanstatus"] = data
                    # sbf_parser keys the sub-block list "SatInfo";
                    # keep "ChannelSatInfo" as a legacy fallback.
                    for sat in data.get("SatInfo") or data.get("ChannelSatInfo") or []:
                        svid = int(sat["SVID"])
                        if svid != 0:
                            freq_nr_cache[svid] = int(sat["FreqNr"])

                case "PVTGeodetic":
                    pending["pvt"] = data

                case "DOP":
                    pending["dop"] = data

                case "ReceiverStatus":
                    pending["status"] = data

                case "SatVisibility":
                    pending["satvis"] = list(data.get("SatInfo", []))

                case "MeasExtra":
                    pending["extra"] = list(data.get("MeasExtraChannel", []))

                case "QualityInd":
                    pending["qualind"] = data

                case "RFStatus":
                    pending["rfstatus"] = data

                case "MeasEpoch":
                    # --- Obs side (fast path: zero pint/pydantic allocations) ---
                    tow_ms_obs = int(data["TOW"])
                    wn_obs = int(data["WNc"])
                    ts_np = np.datetime64(
                        _tow_wn_to_utc(tow_ms_obs, wn_obs, delta_ls).replace(
                            tzinfo=None
                        ),
                        "ns",
                    )
                    timestamps_obs.append(ts_np)
                    e_snr: dict[str, float] = {}
                    e_pr: dict[str, float] = {}
                    e_ph: dict[str, float] = {}
                    e_dop: dict[str, float] = {}
                    e_smooth: dict[str, int] = {}
                    e_half: dict[str, int] = {}
                    for t1 in data.get("Type_1", []):
                        svid1 = int(t1["SVID"])
                        obs_info1 = int(t1["ObsInfo"])
                        sig_num1 = decode_signal_num(int(t1["Type"]), obs_info1)
                        # Compute T1 scalars even when T1 signal unknown — T2 needs them.
                        pr1_f = _pseudorange_m_f(int(t1["Misc"]), int(t1["CodeLSB"]))
                        dop1_f = _doppler_hz_f(int(t1["Doppler"]))
                        freq1_hz = _resolve_freq_hz(sig_num1, svid1, freq_nr_cache)
                        # Fill T1 obs when signal is known.
                        _key1 = (svid1, sig_num1)
                        if _key1 not in _sid_memo:
                            _sid_memo[_key1] = _sid_props_from_obs(
                                svid1, sig_num1, freq_nr_cache
                            )
                        props1 = _sid_memo[_key1]
                        if props1 is not None:
                            sid1 = props1["sid"]
                            if sid1 not in sid_props_obs:
                                sid_props_obs[sid1] = props1
                            cn0_1f = _cn0_dbhz_f(int(t1["CN0"]), sig_num1)
                            if cn0_1f is not None:
                                e_snr[sid1] = cn0_1f
                            if pr1_f is not None:
                                e_pr[sid1] = pr1_f
                            if dop1_f is not None:
                                e_dop[sid1] = dop1_f
                            if pr1_f is not None and freq1_hz is not None:
                                ph1_f = _phase_cycles_f(
                                    pr1_f,
                                    int(t1["CarrierMSB"]),
                                    int(t1["CarrierLSB"]),
                                    freq1_hz,
                                )
                                if ph1_f is not None:
                                    e_ph[sid1] = ph1_f
                            # ObsInfo bit 0 = smoothing, bit 2 = half-cycle
                            e_smooth[sid1] = obs_info1 & 0x01
                            e_half[sid1] = (obs_info1 >> 2) & 0x01
                        # T2 obs: CN0 always decoded; PR/D/phase need T1 values.
                        for t2 in t1.get("Type_2", []):
                            obs_info2 = int(t2["ObsInfo"])
                            sig_num2 = decode_signal_num(int(t2["Type"]), obs_info2)
                            _key2 = (svid1, sig_num2)
                            if _key2 not in _sid_memo:
                                _sid_memo[_key2] = _sid_props_from_obs(
                                    svid1, sig_num2, freq_nr_cache
                                )
                            props2 = _sid_memo[_key2]
                            if props2 is None:
                                continue
                            sid2 = props2["sid"]
                            if sid2 not in sid_props_obs:
                                sid_props_obs[sid2] = props2
                            cn0_2f = _cn0_dbhz_f(int(t2["CN0"]), sig_num2)
                            if cn0_2f is not None:
                                e_snr[sid2] = cn0_2f
                            code_msb2, dop_msb2 = decode_offsets_msb(
                                int(t2["OffsetMSB"])
                            )
                            code_lsb2 = int(t2["CodeOffsetLSB"])
                            dop_lsb2 = int(t2["DopplerOffsetLSB"])
                            pr2_f = None
                            if pr1_f is not None:
                                pr2_f = _pr2_m_f(pr1_f, code_msb2, code_lsb2)
                                if pr2_f is not None:
                                    e_pr[sid2] = pr2_f
                            freq2_hz = _resolve_freq_hz(sig_num2, svid1, freq_nr_cache)
                            if (
                                dop1_f is not None
                                and freq1_hz is not None
                                and freq2_hz is not None
                            ):
                                d2_f = _doppler2_hz_f(
                                    dop1_f, dop_msb2, dop_lsb2, freq2_hz, freq1_hz
                                )
                                if d2_f is not None:
                                    e_dop[sid2] = d2_f
                            if pr2_f is not None and freq2_hz is not None:
                                ph2_f = _phase_cycles_f(
                                    pr2_f,
                                    int(t2["CarrierMSB"]),
                                    int(t2["CarrierLSB"]),
                                    freq2_hz,
                                )
                                if ph2_f is not None:
                                    e_ph[sid2] = ph2_f
                            e_smooth[sid2] = obs_info2 & 0x01
                            e_half[sid2] = (obs_info2 >> 2) & 0x01
                    epoch_rows.append((e_snr, e_pr, e_ph, e_dop, e_smooth, e_half))

                    # --- Metadata side (always, even if epoch decoded as None) ---
                    tow_ms = int(data["TOW"])
                    wn = int(data["WNc"])
                    ts_meta = _tow_wn_to_utc(tow_ms, wn, delta_ls)
                    obs_map = _build_obs_map(data)

                    # Discover sids from Type1/Type2 sub-blocks (same as to_metadata_ds)
                    for t1 in data.get("Type_1", []):
                        svid1 = int(t1["SVID"])
                        _key1 = (
                            svid1,
                            decode_signal_num(int(t1["Type"]), int(t1["ObsInfo"])),
                        )
                        if _key1 not in _sid_memo:
                            _sid_memo[_key1] = _sid_props_from_obs(
                                svid1, _key1[1], freq_nr_cache
                            )
                        props1 = _sid_memo[_key1]
                        if props1 is not None and props1["sid"] not in sid_props_meta:
                            sid_props_meta[props1["sid"]] = props1
                        for t2 in t1.get("Type_2", []):
                            _key2 = (
                                svid1,
                                decode_signal_num(int(t2["Type"]), int(t2["ObsInfo"])),
                            )
                            if _key2 not in _sid_memo:
                                _sid_memo[_key2] = _sid_props_from_obs(
                                    svid1, _key2[1], freq_nr_cache
                                )
                            props2 = _sid_memo[_key2]
                            if (
                                props2 is not None
                                and props2["sid"] not in sid_props_meta
                            ):
                                sid_props_meta[props2["sid"]] = props2

                    records.append(
                        (
                            ts_meta,
                            pending["pvt"],
                            pending["dop"],
                            pending["status"],
                            list(pending["satvis"]),
                            list(pending["extra"]),
                            pending["qualind"],
                            pending["rfstatus"],
                            pending["chanstatus"],
                            obs_map,
                        )
                    )
                    pending = {
                        "pvt": None,
                        "dop": None,
                        "status": None,
                        "satvis": [],
                        "extra": [],
                        "qualind": None,
                        "rfstatus": None,
                        "chanstatus": None,
                    }

        # ----------------------------------------------------------------
        # Build obs dataset (verbatim from to_ds())
        # ----------------------------------------------------------------
        sorted_sids = sorted(sid_props_obs)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}
        n_epochs = len(timestamps_obs)
        n_sids = len(sorted_sids)

        snr_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["SNR"])
        pr_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Pseudorange"])
        ph_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Phase"])
        dop_arr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Doppler"])
        # ObsInfo flags: -1 = no observation, 0 = flag clear, 1 = flag set
        smoothing_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)
        half_cycle_arr = np.full((n_epochs, n_sids), -1, dtype=np.int8)

        for t_idx, (e_snr, e_pr, e_ph, e_dop, e_smooth, e_half) in enumerate(
            epoch_rows
        ):
            for sid, val in e_snr.items():
                snr_arr[t_idx, sid_to_idx[sid]] = val
            for sid, val in e_pr.items():
                pr_arr[t_idx, sid_to_idx[sid]] = val
            for sid, val in e_ph.items():
                ph_arr[t_idx, sid_to_idx[sid]] = val
            for sid, val in e_dop.items():
                dop_arr[t_idx, sid_to_idx[sid]] = val
            for sid, flag in e_smooth.items():
                smoothing_arr[t_idx, sid_to_idx[sid]] = flag
            for sid, flag in e_half.items():
                half_cycle_arr[t_idx, sid_to_idx[sid]] = flag

        # SBF has no native RINEX-style SSI field -- derive it from the
        # continuous CN0 just filled above.
        ssi_arr = _snr_dbhz_to_ssi(snr_arr).astype(DTYPES["SSI"])

        freq_center = np.asarray(
            [sid_props_obs[s]["freq_center"] for s in sorted_sids],
            dtype=DTYPES["freq_center"],
        )
        freq_min = np.asarray(
            [sid_props_obs[s]["freq_min"] for s in sorted_sids],
            dtype=DTYPES["freq_min"],
        )
        freq_max = np.asarray(
            [sid_props_obs[s]["freq_max"] for s in sorted_sids],
            dtype=DTYPES["freq_max"],
        )

        coords_obs: dict[str, Any] = {
            "epoch": ("epoch", timestamps_obs, COORDS_METADATA["epoch"]),
            "sid": xr.DataArray(
                np.array(sorted_sids, dtype=object),
                dims=["sid"],
                attrs=COORDS_METADATA["sid"],
            ),
            "sv": (
                "sid",
                np.array([sid_props_obs[s]["sv"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["sv"],
            ),
            "system": (
                "sid",
                np.array(
                    [sid_props_obs[s]["system"] for s in sorted_sids], dtype=object
                ),
                COORDS_METADATA["system"],
            ),
            "band": (
                "sid",
                np.array([sid_props_obs[s]["band"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["band"],
            ),
            "code": (
                "sid",
                np.array([sid_props_obs[s]["code"] for s in sorted_sids], dtype=object),
                COORDS_METADATA["code"],
            ),
            "freq_center": ("sid", freq_center, COORDS_METADATA["freq_center"]),
            "freq_min": ("sid", freq_min, COORDS_METADATA["freq_min"]),
            "freq_max": ("sid", freq_max, COORDS_METADATA["freq_max"]),
        }

        attrs = cast(dict[str, Any], self._build_attrs())

        try:
            import pymap3d as pm

            hdr = self.header
            lat_deg = math.degrees(hdr.latitude_rad)
            lon_deg = math.degrees(hdr.longitude_rad)
            h_m = float(hdr.height_m.to(UREG.meter).magnitude)
            x, y, z = pm.geodetic2ecef(lat_deg, lon_deg, h_m)
            attrs["APPROX POSITION X"] = float(x)
            attrs["APPROX POSITION Y"] = float(y)
            attrs["APPROX POSITION Z"] = float(z)
        except LookupError, AttributeError:
            pass

        obs_ds = xr.Dataset(
            data_vars={
                "SNR": (["epoch", "sid"], snr_arr, CN0_METADATA),
                "Pseudorange": (
                    ["epoch", "sid"],
                    pr_arr,
                    OBSERVABLES_METADATA["Pseudorange"],
                ),
                "Phase": (["epoch", "sid"], ph_arr, OBSERVABLES_METADATA["Phase"]),
                "Doppler": (["epoch", "sid"], dop_arr, OBSERVABLES_METADATA["Doppler"]),
                "SSI": (["epoch", "sid"], ssi_arr, OBSERVABLES_METADATA["SSI"]),
                "Smoothing": (
                    ["epoch", "sid"],
                    smoothing_arr,
                    _SMOOTHING_FLAG_ATTRS,
                ),
                "HalfCycle": (
                    ["epoch", "sid"],
                    half_cycle_arr,
                    _HALF_CYCLE_ATTRS,
                ),
            },
            coords=coords_obs,
            attrs=attrs,
        )

        if pad_global_sid:
            from canvod.auxiliary.preprocessing import pad_to_global_sid

            obs_ds = pad_to_global_sid(
                obs_ds,
                keep_sids=cast(list[str] | None, kwargs.get("keep_sids")),
            )

        if strip_fillval:
            from canvod.auxiliary.preprocessing import strip_fillvalue

            obs_ds = strip_fillvalue(obs_ds)

        validate_dataset(obs_ds, required_vars=keep_data_vars)

        # ----------------------------------------------------------------
        # Build metadata dataset (verbatim from to_metadata_ds())
        # ----------------------------------------------------------------
        sorted_sids_meta = sorted(sid_props_meta)
        sid_to_idx_meta = {sid: i for i, sid in enumerate(sorted_sids_meta)}
        n_epochs_meta = len(records)
        n_sids_meta = len(sorted_sids_meta)

        sids_for_sv: dict[str, list[int]] = {}
        for sid in sorted_sids_meta:
            sv = sid_props_meta[sid]["sv"]
            sids_for_sv.setdefault(sv, []).append(sid_to_idx_meta[sid])

        theta_arr = np.full((n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32)
        phi_arr = np.full((n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32)
        rise_set_arr = np.full((n_epochs_meta, n_sids_meta), -1, dtype=np.int8)
        mp_corr_arr = np.full((n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32)
        smoothing_corr_arr = np.full(
            (n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32
        )
        code_var_arr = np.full((n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32)
        carr_var_arr = np.full((n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32)
        lock_time_arr = np.full((n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32)
        cum_loss_cont_arr = np.full(
            (n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32
        )
        car_mp_corr_arr = np.full(
            (n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32
        )
        cn0_highres_arr = np.full(
            (n_epochs_meta, n_sids_meta), np.nan, dtype=np.float32
        )
        # ChannelStatus raw bitfields, broadcast per-sv (0 = idle / no info)
        tracking_status_arr = np.zeros((n_epochs_meta, n_sids_meta), dtype=np.uint16)
        pvt_status_arr = np.zeros((n_epochs_meta, n_sids_meta), dtype=np.uint16)

        pdop_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        hdop_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        vdop_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        n_sv_arr = np.full(n_epochs_meta, -1, dtype=np.int16)
        h_acc_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        v_acc_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        pvt_mode_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        mean_corr_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        cpu_load_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        temp_arr = np.full(n_epochs_meta, np.nan, dtype=np.float32)
        rx_error_arr = np.full(n_epochs_meta, 0, dtype=np.int32)
        # QualityInd scores (0-10; -1 = unknown / block absent)
        qual_overall_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        qual_gnss_main_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        qual_rf_main_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        qual_cpu_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        qual_scint_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        # RFStatus flags (0/1; -1 = block absent)
        spoofing_arr = np.full(n_epochs_meta, -1, dtype=np.int8)
        nma_fail_arr = np.full(n_epochs_meta, -1, dtype=np.int8)

        timestamps_meta: list[np.datetime64] = []

        for t_idx, (
            ts,
            pvt,
            dop,
            status,
            satvis,
            extra,
            qualind,
            rfstatus,
            chanstatus,
            obs_map,
        ) in enumerate(records):
            timestamps_meta.append(np.datetime64(ts.replace(tzinfo=None), "ns"))

            if dop is not None:
                try:
                    # PDOP/HDOP/VDOP: u2, 0.01/LSB, Do-Not-Use 0 → NaN
                    raw_pdop = int(dop["PDOP"])
                    if raw_pdop != 0:
                        pdop_arr[t_idx] = raw_pdop * 0.01
                    raw_hdop = int(dop["HDOP"])
                    if raw_hdop != 0:
                        hdop_arr[t_idx] = raw_hdop * 0.01
                    raw_vdop = int(dop["VDOP"])
                    if raw_vdop != 0:
                        vdop_arr[t_idx] = raw_vdop * 0.01
                except KeyError, TypeError, ValueError:
                    pass

            if pvt is not None:
                try:
                    # NrSV: u1, Do-Not-Use 255 → sentinel -1
                    raw_nrsv = int(pvt.get("NrSV", pvt.get("NrSVAnt", 255)))
                    n_sv_arr[t_idx] = -1 if raw_nrsv == 255 else raw_nrsv
                    raw_hacc = int(pvt["HAccuracy"])
                    if raw_hacc != 65535:
                        h_acc_arr[t_idx] = raw_hacc * 0.01
                    raw_vacc = int(pvt["VAccuracy"])
                    if raw_vacc != 65535:
                        v_acc_arr[t_idx] = raw_vacc * 0.01
                    # Mode: bits 0-3 = PVT solution mode; bits 4-7 are
                    # flag bits (e.g. 2D flag) that must be masked off.
                    pvt_mode_arr[t_idx] = int(pvt["Mode"]) & 0x0F
                    # MeanCorrAge: u2, 0.01 s/LSB, Do-Not-Use 65535 → NaN
                    raw_mca = int(pvt["MeanCorrAge"])
                    if raw_mca != 65535:
                        mean_corr_arr[t_idx] = raw_mca * 0.01
                    if np.isnan(pdop_arr[t_idx]):
                        raw_pdop = int(pvt["PDOP"])
                        if raw_pdop != 0:
                            pdop_arr[t_idx] = raw_pdop * 0.01
                        raw_hdop = int(pvt["HDOP"])
                        if raw_hdop != 0:
                            hdop_arr[t_idx] = raw_hdop * 0.01
                        raw_vdop = int(pvt["VDOP"])
                        if raw_vdop != 0:
                            vdop_arr[t_idx] = raw_vdop * 0.01
                except KeyError, TypeError, ValueError:
                    pass

            if status is not None:
                try:
                    # CPULoad: u1, %, Do-Not-Use 255 → sentinel -1
                    raw_cpu = int(status["CPULoad"])
                    cpu_load_arr[t_idx] = -1 if raw_cpu == 255 else raw_cpu
                    raw_temp = int(status["Temperature"])
                    if raw_temp != 0:  # 0 is DoNotUse (RefGuide p.397)
                        temp_arr[t_idx] = float(raw_temp - 100)
                    rx_error_arr[t_idx] = int(status["RxError"])
                except KeyError, TypeError, ValueError:
                    pass

            for sat_info in satvis:
                try:
                    svid_raw = int(sat_info["SVID"])
                    sys_code, prn = decode_svid(svid_raw)
                    sv = f"{sys_code}{prn:02d}"
                    theta_deg = 90.0 - int(sat_info["Elevation"]) * 0.01
                    phi_deg = int(sat_info["Azimuth"]) * 0.01
                    # RiseSet: u1, 255 = unknown → sentinel -1 (int8-safe)
                    rs_raw = int(sat_info["RiseSet"])
                    rs = -1 if rs_raw == 255 else rs_raw
                    for s_idx in sids_for_sv.get(sv, []):
                        theta_arr[t_idx, s_idx] = theta_deg
                        phi_arr[t_idx, s_idx] = phi_deg
                        rise_set_arr[t_idx, s_idx] = rs
                except KeyError, TypeError, ValueError:
                    pass

            for ch in extra:
                try:
                    type_byte = int(ch["Type"])
                    info_byte = int(ch.get("ObsInfo", ch.get("Info", 0)))
                    sig_num = decode_signal_num(type_byte, info_byte)
                    rx_ch = int(ch["RxChannel"])
                    svid = obs_map.get((rx_ch, sig_num))
                    if svid is None:
                        continue
                    sig_def = SIGNAL_TABLE.get(sig_num)
                    if sig_def is None:
                        continue
                    sys_code2, prn2 = decode_svid(svid)
                    sv2 = f"{sys_code2}{prn2:02d}"
                    sid = f"{sv2}|{sig_def.band}|{sig_def.code}"
                    s_idx = sid_to_idx_meta.get(sid)
                    if s_idx is None:
                        continue
                    mp_raw = int(ch.get("MPCorrection ", ch.get("MPCorrection", 0)))
                    mp_corr_arr[t_idx, s_idx] = mp_raw * 0.001
                    # SmoothingCorr: i2, scale 0.001 m/LSB
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    raw_sc = ch.get("SmoothingCorr")
                    if raw_sc is not None:
                        smoothing_corr_arr[t_idx, s_idx] = int(raw_sc) * 0.001
                    raw_cv = ch.get("CodeVar")
                    # CodeVar: u2, scale 0.0001 m²/LSB, Do-Not-Use 65535
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_cv is not None and int(raw_cv) != 65535:
                        code_var_arr[t_idx, s_idx] = int(raw_cv) * 1e-4
                    raw_rv = ch.get("CarrierVar")
                    # CarrierVar: u2, scale 1 mcycle²/LSB, Do-Not-Use 65535
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_rv is not None and int(raw_rv) != 65535:
                        carr_var_arr[t_idx, s_idx] = float(raw_rv)
                    raw_lt = ch.get("LockTime")
                    # LockTime: u2, scale 1 s/LSB, Do-Not-Use 65535, clipped to 65534 s
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_lt is not None and int(raw_lt) != 65535:
                        lock_time_arr[t_idx, s_idx] = float(raw_lt)
                    raw_clc = ch.get("CumLossCont")
                    # CumLossCont: u1, modulo-256 counter, no Do-Not-Use
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_clc is not None:
                        cum_loss_cont_arr[t_idx, s_idx] = float(int(raw_clc))
                    raw_cmc = ch.get("CarMPCorr")
                    # CarMPCorr: i1, scale 1/512 cycles/LSB (1.953125 mcycles/LSB)
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_cmc is not None:
                        car_mp_corr_arr[t_idx, s_idx] = int(raw_cmc) / 512.0
                    raw_misc = ch.get("Misc")
                    # Misc bits 0-2: CN0HighRes (u3, 0-7), scale 0.03125 dB-Hz/LSB
                    # RefGuide-4.14.0, MeasExtra (Block 4000), MeasExtraChannelSub, p.265
                    if raw_misc is not None:
                        cn0_hr = int(raw_misc) & 0x07
                        cn0_highres_arr[t_idx, s_idx] = cn0_hr * 0.03125
                except KeyError, TypeError, ValueError:
                    pass

            # QualityInd → receiver quality indicator scores
            if qualind is not None:
                q_vals = _decode_quality_indicators(qualind)
                qual_overall_arr[t_idx] = q_vals.get(0, -1)
                qual_gnss_main_arr[t_idx] = q_vals.get(1, -1)
                qual_rf_main_arr[t_idx] = q_vals.get(11, -1)
                qual_cpu_arr[t_idx] = q_vals.get(21, -1)
                qual_scint_arr[t_idx] = q_vals.get(29, -1)

            # RFStatus → spoofing / NMA authentication flags
            if rfstatus is not None:
                try:
                    rf_flags = int(rfstatus["Flags"])
                    spoofing_arr[t_idx] = rf_flags & 0x01
                    nma_fail_arr[t_idx] = (rf_flags >> 1) & 0x01
                except KeyError, TypeError, ValueError:
                    pass

            # ChannelStatus → raw tracking / PVT status bitfields,
            # broadcast to all SIDs of each satellite (Main antenna only)
            if chanstatus is not None:
                for sv_trk, trk_raw, pvt_raw in _extract_tracking_info(chanstatus):
                    for s_idx in sids_for_sv.get(sv_trk, []):
                        tracking_status_arr[t_idx, s_idx] = trk_raw
                        pvt_status_arr[t_idx, s_idx] = pvt_raw

        freq_center_meta = np.asarray(
            [sid_props_meta[s]["freq_center"] for s in sorted_sids_meta],
            dtype=np.float32,
        )
        freq_min_meta = np.asarray(
            [sid_props_meta[s]["freq_min"] for s in sorted_sids_meta], dtype=np.float32
        )
        freq_max_meta = np.asarray(
            [sid_props_meta[s]["freq_max"] for s in sorted_sids_meta], dtype=np.float32
        )

        coords_meta: dict[str, Any] = {
            "epoch": ("epoch", timestamps_meta, COORDS_METADATA["epoch"]),
            "sid": xr.DataArray(
                sorted_sids_meta, dims=["sid"], attrs=COORDS_METADATA["sid"]
            ),
            "sv": (
                "sid",
                [sid_props_meta[s]["sv"] for s in sorted_sids_meta],
                COORDS_METADATA["sv"],
            ),
            "system": (
                "sid",
                [sid_props_meta[s]["system"] for s in sorted_sids_meta],
                COORDS_METADATA["system"],
            ),
            "band": (
                "sid",
                [sid_props_meta[s]["band"] for s in sorted_sids_meta],
                COORDS_METADATA["band"],
            ),
            "code": (
                "sid",
                [sid_props_meta[s]["code"] for s in sorted_sids_meta],
                COORDS_METADATA["code"],
            ),
            "freq_center": ("sid", freq_center_meta, COORDS_METADATA["freq_center"]),
            "freq_min": ("sid", freq_min_meta, COORDS_METADATA["freq_min"]),
            "freq_max": ("sid", freq_max_meta, COORDS_METADATA["freq_max"]),
            "pdop": ("epoch", pdop_arr, _PDOP_ATTRS),
            "hdop": ("epoch", hdop_arr, _HDOP_ATTRS),
            "vdop": ("epoch", vdop_arr, _VDOP_ATTRS),
            "n_sv": ("epoch", n_sv_arr, _N_SV_ATTRS),
            "h_accuracy_m": ("epoch", h_acc_arr, _H_ACCURACY_ATTRS),
            "v_accuracy_m": ("epoch", v_acc_arr, _V_ACCURACY_ATTRS),
            "pvt_mode": ("epoch", pvt_mode_arr, _PVT_MODE_ATTRS),
            "mean_corr_age_s": ("epoch", mean_corr_arr, _MEAN_CORR_AGE_ATTRS),
            "cpu_load": ("epoch", cpu_load_arr, _CPU_LOAD_ATTRS),
            "temperature_c": ("epoch", temp_arr, _TEMPERATURE_ATTRS),
            "rx_error": ("epoch", rx_error_arr, _RX_ERROR_ATTRS),
            "qual_overall": ("epoch", qual_overall_arr, _QUAL_OVERALL_ATTRS),
            "qual_gnss_main": ("epoch", qual_gnss_main_arr, _QUAL_GNSS_MAIN_ATTRS),
            "qual_rf_main": ("epoch", qual_rf_main_arr, _QUAL_RF_MAIN_ATTRS),
            "qual_cpu": ("epoch", qual_cpu_arr, _QUAL_CPU_ATTRS),
            "qual_scintillation": ("epoch", qual_scint_arr, _QUAL_SCINT_ATTRS),
            "spoofing_flag": ("epoch", spoofing_arr, _SPOOFING_FLAG_ATTRS),
            "nma_fail_flag": ("epoch", nma_fail_arr, _NMA_FAIL_ATTRS),
        }

        attrs_meta = self._build_attrs()

        meta_ds = xr.Dataset(
            data_vars={
                "broadcast_theta": (
                    ["epoch", "sid"],
                    np.deg2rad(theta_arr),
                    _BROADCAST_THETA_ATTRS,
                ),
                "broadcast_phi": (
                    ["epoch", "sid"],
                    np.deg2rad(phi_arr),
                    _BROADCAST_PHI_ATTRS,
                ),
                "rise_set": (["epoch", "sid"], rise_set_arr, _RISE_SET_ATTRS),
                "mp_correction_m": (
                    ["epoch", "sid"],
                    mp_corr_arr,
                    _MP_CORRECTION_ATTRS,
                ),
                "smoothing_corr_m": (
                    ["epoch", "sid"],
                    smoothing_corr_arr,
                    _SMOOTHING_CORR_ATTRS,
                ),
                "code_var": (["epoch", "sid"], code_var_arr, _CODE_VAR_ATTRS),
                "carrier_var": (["epoch", "sid"], carr_var_arr, _CARRIER_VAR_ATTRS),
                "lock_time_s": (["epoch", "sid"], lock_time_arr, _LOCK_TIME_ATTRS),
                "cum_loss_cont": (
                    ["epoch", "sid"],
                    cum_loss_cont_arr,
                    _CUM_LOSS_CONT_ATTRS,
                ),
                "car_mp_corr_cycles": (
                    ["epoch", "sid"],
                    car_mp_corr_arr,
                    _CAR_MP_CORR_ATTRS,
                ),
                "cn0_highres_correction": (
                    ["epoch", "sid"],
                    cn0_highres_arr,
                    _CN0_HIGHRES_CORRECTION_ATTRS,
                ),
                "tracking_status_raw": (
                    ["epoch", "sid"],
                    tracking_status_arr,
                    _TRACKING_STATUS_RAW_ATTRS,
                ),
                "pvt_status_raw": (
                    ["epoch", "sid"],
                    pvt_status_arr,
                    _PVT_STATUS_RAW_ATTRS,
                ),
            },
            coords=coords_meta,
            attrs=attrs_meta,
        )

        # Align meta_ds SID to obs_ds SID.
        # obs uses sid_props_obs (MeasEpoch); meta uses sid_props_meta (Type1/Type2)
        # — they can diverge.  Reindex fills missing SIDs with NaN.
        meta_ds = meta_ds.reindex(sid=obs_ds.sid, fill_value=np.nan)
        # rise_set is int8 with sentinel -1; NaN fill promotes to float — cast back.
        if meta_ds["rise_set"].dtype != np.int8:
            meta_ds["rise_set"] = meta_ds["rise_set"].fillna(-1).astype(np.int8)
        # tracking/PVT status are uint16 bitfields with fill 0 — cast back too.
        for _tv in ("tracking_status_raw", "pvt_status_raw"):
            if meta_ds[_tv].dtype != np.uint16:
                meta_ds[_tv] = meta_ds[_tv].fillna(0).astype(np.uint16)

        # Apply CN0HighRes correction from MeasExtra (Block 4000) to SNR.
        # CN0HighRes extends resolution from 0.25 to 0.03125 dB-Hz.
        # RefGuide-4.14.0, MeasExtra MeasExtraChannelSub.Misc bits 0-2, p.265.
        # Where MeasExtra was not logged the correction array is NaN → no-op.
        corr = meta_ds["cn0_highres_correction"].values  # (epoch, sid), NaN if absent
        snr_raw_values = obs_ds["SNR"].values.copy()  # preserve 0.25 dB-Hz original
        snr_corrected = snr_raw_values.copy()
        valid = ~np.isnan(snr_corrected) & ~np.isnan(corr)
        snr_corrected[valid] += corr[valid]
        snr_attrs = dict(obs_ds["SNR"].attrs)
        snr_attrs["comment"] = (
            snr_attrs.get("comment", "")
            + " CN0HighRes correction from MeasExtra (Block 4000, p.265) applied where"
            " available, improving resolution from 0.25 to 0.03125 dB-Hz."
        ).lstrip()
        obs_ds["SNR"] = xr.DataArray(
            snr_corrected,
            dims=["epoch", "sid"],
            coords=obs_ds["SNR"].coords,
            attrs=snr_attrs,
        )

        if store_raw_observables:
            # ------------------------------------------------------------------
            # Add "physically raw" observables: pre-correction versions of SNR,
            # pseudorange, and carrier phase.  NaN where MeasExtra was absent.
            # Gated by store_raw_observables (config: store_sbf_raw_observables).
            # ------------------------------------------------------------------

            # SNR_raw: 0.25 dB-Hz resolution, before CN0HighRes extension.
            obs_ds["SNR_raw"] = xr.DataArray(
                snr_raw_values,
                dims=["epoch", "sid"],
                coords=obs_ds["SNR"].coords,
                attrs=_SNR_RAW_ATTRS,
            )

            # Pseudorange_unsmoothed: Hatch-filter correction removed.
            smooth = meta_ds["smoothing_corr_m"].values
            pr_vals = obs_ds["Pseudorange"].values
            pr_unsmoothed = np.where(
                ~np.isnan(smooth), pr_vals + smooth, np.nan
            ).astype(np.float64)
            obs_ds["Pseudorange_unsmoothed"] = xr.DataArray(
                pr_unsmoothed,
                dims=["epoch", "sid"],
                coords=obs_ds["Pseudorange"].coords,
                attrs=_PSEUDORANGE_UNSMOOTHED_ATTRS,
            )

            # Pseudorange_raw: both Hatch-filter and multipath corrections removed.
            mp = meta_ds["mp_correction_m"].values
            available = ~np.isnan(smooth) & ~np.isnan(mp)
            pr_raw = np.where(available, pr_vals + smooth + mp, np.nan).astype(
                np.float64
            )
            obs_ds["Pseudorange_raw"] = xr.DataArray(
                pr_raw,
                dims=["epoch", "sid"],
                coords=obs_ds["Pseudorange"].coords,
                attrs=_PSEUDORANGE_RAW_ATTRS,
            )

            # Phase_raw: carrier multipath correction removed.
            car_mp = meta_ds["car_mp_corr_cycles"].values
            ph_vals = obs_ds["Phase"].values
            ph_raw = np.where(~np.isnan(car_mp), ph_vals + car_mp, np.nan).astype(
                np.float64
            )
            obs_ds["Phase_raw"] = xr.DataArray(
                ph_raw,
                dims=["epoch", "sid"],
                coords=obs_ds["Phase"].coords,
                attrs=_PHASE_RAW_ATTRS,
            )

        if keep_data_vars is not None:
            for var in list(obs_ds.data_vars):
                if var not in keep_data_vars:
                    obs_ds = obs_ds.drop_vars([var])

        return obs_ds, {"sbf_obs": meta_ds}

    # ------------------------------------------------------------------
    # Private decoding helpers
    # ------------------------------------------------------------------

    def _decode_epoch(  # pylint: disable=too-many-locals
        self,
        data: dict[str, Any],
        freq_nr_cache: dict[int, int],
        delta_ls: int,
    ) -> SbfEpoch | None:
        """Decode one raw MeasEpoch dict into an :class:`SbfEpoch`.

        Parameters
        ----------
        data : dict
            Raw block dict from ``sbf_parser``.
        freq_nr_cache : dict of {int: int}
            Current SVID → FreqNr mapping for GLONASS FDMA frequency lookup.
        delta_ls : int
            GPS - UTC leap second offset.

        Returns
        -------
        SbfEpoch or None
            Decoded epoch, or ``None`` if decoding fails (logged as warning).
        """
        tow_ms = int(data["TOW"])
        wn = int(data["WNc"])
        timestamp = _tow_wn_to_utc(tow_ms, wn, delta_ls)
        common_flags = int(data["CommonFlags"])
        cum_clk_jumps = int(data["CumClkJumps"])

        observations: list[SbfSignalObs] = []

        for t1 in data.get("Type_1", []):
            t1_obs, t1_freq = self._decode_type1(t1, freq_nr_cache)
            pr1: pint.Quantity | None = None
            d1: pint.Quantity | None = None
            if t1_obs is not None:
                observations.append(t1_obs)
                pr1 = t1_obs.pseudorange
                d1 = t1_obs.doppler
            # Decode linked Type2 slave observations UNCONDITIONALLY:
            # CN0 is always self-contained in the Type2 sub-block, so a
            # Do-Not-Use Type1 pseudorange/Doppler (or an unknown Type1
            # signal) must not drop the Type2 SNR (primary VOD observable).
            for t2 in t1.get("Type_2", []):
                t2_obs = self._decode_type2(
                    t2,
                    int(t1["SVID"]),
                    pr1,
                    d1,
                    t1_freq,
                    int(t1["RxChannel"]),
                    freq_nr_cache,
                )
                if t2_obs is not None:
                    observations.append(t2_obs)

        return SbfEpoch(
            tow_ms=tow_ms,
            wn=wn,
            timestamp=timestamp,
            common_flags=common_flags,
            cum_clk_jumps=cum_clk_jumps,
            observations=tuple(observations),
        )

    def _resolve_freq(
        self,
        sig_num: int,
        svid: int,
        freq_nr_cache: dict[int, int],
    ) -> pint.Quantity | None:
        """Return carrier frequency as a pint Quantity, or None if unavailable.

        Parameters
        ----------
        sig_num : int
            Signal type number (0-39).
        svid : int
            Septentrio internal SVID.
        freq_nr_cache : dict of {int: int}
            Current SVID → FreqNr map.

        Returns
        -------
        pint.Quantity or None
            Carrier frequency (in MHz), or ``None`` if GLONASS and FreqNr
            not yet known, or signal not in table (e.g. L-Band MSS).
        """
        if sig_num in FDMA_SIGNAL_NUMS:
            freq_nr = freq_nr_cache.get(svid)
            if freq_nr is None:
                return None
            return glonass_freq_hz(sig_num, freq_nr)

        sig_def = SIGNAL_TABLE.get(sig_num)
        if sig_def is None:
            return None
        return sig_def.freq  # None for L-Band MSS (sig 23)

    def _decode_type1(  # pylint: disable=too-many-locals
        self,
        t1: dict[str, Any],
        freq_nr_cache: dict[int, int],
    ) -> tuple[SbfSignalObs | None, pint.Quantity | None]:
        """Decode a Type1 sub-block dict to an SbfSignalObs.

        Parameters
        ----------
        t1 : dict
            Raw Type1 sub-block dict.
        freq_nr_cache : dict of {int: int}
            Current SVID → FreqNr map.

        Returns
        -------
        obs : SbfSignalObs or None
            Decoded observation, or ``None`` for unknown signals.
        freq : pint.Quantity or None
            Carrier frequency used (needed for Type2 Doppler scaling).
        """
        svid = int(t1["SVID"])
        type_byte = int(t1["Type"])
        obs_info = int(t1["ObsInfo"])
        sig_num = decode_signal_num(type_byte, obs_info)

        sig_def = SIGNAL_TABLE.get(sig_num)
        if sig_def is None:
            log.debug("sbf_unknown_signal", svid=svid, sig_num=sig_num)
            return None, None

        system, prn = decode_svid(svid)
        freq = self._resolve_freq(sig_num, svid, freq_nr_cache)

        misc = int(t1["Misc"])
        code_lsb = int(t1["CodeLSB"])
        pr = pseudorange_m(misc, code_lsb)
        dop = doppler_hz(int(t1["Doppler"]))
        carrier_msb = int(t1["CarrierMSB"])
        carrier_lsb = int(t1["CarrierLSB"])

        ph: float | None = None
        if pr is not None and freq is not None:
            ph = phase_cycles(pr, carrier_msb, carrier_lsb, freq)

        obs = SbfSignalObs(
            svid=svid,
            system=system,
            prn=prn,
            signal_num=sig_num,
            signal_type=sig_def.signal_type,
            rx_channel=int(t1["RxChannel"]),
            lock_time_s=int(t1["LockTime"]),
            cn0=cn0_dbhz(int(t1["CN0"]), sig_num),
            pseudorange=pr,
            doppler=dop,
            phase_cycles=ph,
            obs_info=obs_info,
            is_type2=False,
        )
        return obs, freq

    def _decode_type2(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments
        self,
        t2: dict[str, Any],
        svid: int,
        pr1: pint.Quantity | None,
        d1: pint.Quantity | None,
        freq1: pint.Quantity | None,
        rx_channel: int,
        freq_nr_cache: dict[int, int],
    ) -> SbfSignalObs | None:
        """Decode a Type2 sub-block dict to an SbfSignalObs.

        Parameters
        ----------
        t2 : dict
            Raw Type2 sub-block dict.
        svid : int
            SVID of the parent Type1 sub-block.
        pr1 : pint.Quantity or None
            Type1 pseudorange in metres, or ``None`` if Do-Not-Use.
            Only pseudorange-derived fields are skipped in that case.
        d1 : pint.Quantity or None
            Type1 Doppler in Hz, or ``None`` if Do-Not-Use.
        freq1 : pint.Quantity or None
            Type1 carrier frequency, or ``None`` if unknown.
        rx_channel : int
            Receiver channel of the parent Type1 sub-block (Type2
            sub-blocks carry no RxChannel field on the wire).
        freq_nr_cache : dict of {int: int}
            Current SVID → FreqNr map.

        Returns
        -------
        SbfSignalObs or None
            Decoded observation, or ``None`` for unknown signals.
            CN0 is always decoded; pseudorange / Doppler / phase only
            when the required Type1 reference values are available.
        """
        type_byte = int(t2["Type"])
        obs_info = int(t2["ObsInfo"])
        sig_num = decode_signal_num(type_byte, obs_info)

        sig_def = SIGNAL_TABLE.get(sig_num)
        if sig_def is None:
            log.debug("sbf_unknown_type2_signal", svid=svid, sig_num=sig_num)
            return None

        system, prn = decode_svid(svid)
        freq2 = self._resolve_freq(sig_num, svid, freq_nr_cache)

        code_msb_signed, doppler_msb_signed = decode_offsets_msb(int(t2["OffsetMSB"]))
        code_offset_lsb = int(t2["CodeOffsetLSB"])
        doppler_offset_lsb = int(t2["DopplerOffsetLSB"])
        carrier_msb = int(t2["CarrierMSB"])
        carrier_lsb = int(t2["CarrierLSB"])

        pr2: pint.Quantity | None = None
        if pr1 is not None:
            pr2 = pr2_m(pr1, code_msb_signed, code_offset_lsb)

        d2: pint.Quantity | None = None
        if d1 is not None and freq1 is not None and freq2 is not None:
            d2 = doppler2_hz(d1, doppler_msb_signed, doppler_offset_lsb, freq2, freq1)

        ph: float | None = None
        if pr2 is not None and freq2 is not None:
            ph = phase_cycles(pr2, carrier_msb, carrier_lsb, freq2)

        return SbfSignalObs(
            svid=svid,
            system=system,
            prn=prn,
            signal_num=sig_num,
            signal_type=sig_def.signal_type,
            rx_channel=rx_channel,
            lock_time_s=int(t2["LockTime"]),
            cn0=cn0_dbhz(int(t2["CN0"]), sig_num),
            pseudorange=pr2,
            doppler=d2,
            phase_cycles=ph,
            obs_info=obs_info,
            is_type2=True,
        )

    def __repr__(self) -> str:
        """Return a short string representation."""
        return f"SbfReader(file='{self.fpath.name}', epochs={self.num_epochs})"
