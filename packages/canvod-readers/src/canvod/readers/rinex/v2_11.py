"""RINEX v2.11 observation file reader.

Implements parsing of RINEX version 2.11 observation files per the official
specification (Werner Gurtner & Lou Estey, IGS/RTCM RINEX Working Group).

Supports:
- GPS, GLONASS, Galileo, SBAS, and mixed observation files
- All v2.11 observation types: C, P, L, D, S (frequencies 1,2,5,6,7,8)
- Wavelength factor handling (full/half cycle ambiguities)
- Event flags (0-6): power failure, moving antenna, new site, header info,
  external events, cycle slip records
- More than 12 satellites per epoch (continuation lines)
- More than 5 observation types per satellite (continuation lines)
- Receiver clock offset
- 2-digit year handling (80-99 → 1980-1999, 00-79 → 2000-2079)
- Variable-length records with trailing blank truncation

Classes:
- Rnxv2Header: Parse RINEX v2.11 headers
- Rnxv2Obs: Main reader class, converts RINEX v2.11 to xarray Dataset
"""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Self

import numpy as np
import pint
import xarray as xr
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from canvod.readers.base import GNSSDataReader, validate_dataset
from canvod.readers.gnss_specs.constants import UREG
from canvod.readers.gnss_specs.exceptions import (
    IncompleteEpochError,
    InvalidEpochError,
)
from canvod.readers.gnss_specs.metadata import (
    COORDS_METADATA,
    DTYPES,
    OBSERVABLES_METADATA,
    SNR_METADATA,
    get_global_attrs,
)
from canvod.readers.gnss_specs.models import (
    Observation,
    Satellite,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper
from canvod.readers.gnss_specs.utils import get_version_from_pyproject

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

MIN_EPOCHS_FOR_INTERVAL = 2
V2_OBS_FIELD_WIDTH = 16  # F14.3 + I1 (LLI) + I1 (SSI)
V2_MAX_OBS_PER_LINE = 5  # Max observations per line (5 x 16 = 80 chars)
V2_MAX_SATS_PER_LINE = 12  # Max satellites on the epoch line
V2_SAT_FIELD_WIDTH = 3  # Each satellite field: A1 + I2
V2_EPOCH_FLAG_OK = 0
V2_EPOCH_FLAG_POWER_FAILURE = 1
V2_EPOCH_FLAG_START_MOVING = 2
V2_EPOCH_FLAG_NEW_SITE = 3
V2_EPOCH_FLAG_HEADER_INFO = 4
V2_EPOCH_FLAG_EXTERNAL_EVENT = 5
V2_EPOCH_FLAG_CYCLE_SLIP = 6
V2_YEAR_PIVOT = 80  # Two-digit year pivot: >= 80 → 19xx, < 80 → 20xx

# RINEX v2 tracking-code map.
# Only C1, P1, C2, P2 transmit an explicit ranging code.
# All other v2 obs codes do not specify the ranging code → "X".
_V2_TRACKING_CODE: dict[str, str] = {
    "C1": "C",  # C/A code pseudorange on L1
    "P1": "P",  # P-code pseudorange on L1
    "C2": "C",  # L2C civil code pseudorange
    "P2": "P",  # P-code pseudorange on L2
}

# v2 pseudorange codes P1/P2 map to obs-type "C" (pseudorange) in v3.
_V2_OBS_TYPE_REMAP: dict[str, str] = {"P": "C"}

# System identifiers recognized in RINEX v2.11
V2_SYSTEM_CODES = {"G", "R", "S", "E", " "}


def _expand_v2_year(yy: int) -> int:
    """Convert 2-digit year to 4-digit year per RINEX v2 convention.

    80-99 → 1980-1999, 00-79 → 2000-2079.
    """
    if yy >= V2_YEAR_PIVOT:
        return 1900 + yy
    return 2000 + yy


def _parse_v2_obs_code(obs_code_v2: str) -> tuple[str, str, str]:
    """Parse a RINEX v2 2-char obs code into (obs_type, freq_num, tracking_code).

    Parameters
    ----------
    obs_code_v2 : str
        Two-character RINEX v2 observation code (e.g. "L1", "P2", "C5").

    Returns
    -------
    tuple[str, str, str]
        (obs_type, freq_num, tracking_code) where:
        - obs_type: v3 observation type character ("C", "L", "D", "S")
        - freq_num: frequency number as string ("1", "2", "5", "6", "7", "8")
        - tracking_code: "C" for C1/C2, "P" for P1/P2, "X" otherwise
    """
    raw_type = obs_code_v2[0]  # C, P, L, D, S
    freq_num = obs_code_v2[1]  # 1, 2, 5, 6, 7, 8
    obs_type = _V2_OBS_TYPE_REMAP.get(raw_type, raw_type)
    tracking_code = _V2_TRACKING_CODE.get(obs_code_v2, "X")
    return obs_type, freq_num, tracking_code


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #


class Rnxv2Header(BaseModel):
    """Parsed RINEX v2.11 observation file header.

    Notes
    -----
    This is a Pydantic ``BaseModel`` configured as frozen with
    ``arbitrary_types_allowed``. Prefer :meth:`from_file` for construction.
    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )

    # Required
    fpath: Path
    version: float
    filetype: str
    systems: str
    pgm: str
    run_by: str
    date: datetime
    marker_name: str
    observer: str
    agency: str
    receiver_number: str
    receiver_type: str
    receiver_version: str
    antenna_number: str
    antenna_type: str
    approx_position: list[pint.Quantity]
    antenna_delta: list[pint.Quantity]
    obs_types: list[str]  # Original v2 2-char codes ("L1", "P2", …)
    obs_codes_per_system: dict[str, list[str]]  # Mapped to v3 3-char codes per system
    t0: dict[str, datetime]
    time_system: str

    # Optional
    comment: str | None = None
    marker_number: str | None = None
    interval: float | None = None
    wavelength_fact_l1: int = 1
    wavelength_fact_l2: int = 1
    wavelength_fact_satellites: dict[str, tuple[int, int]] = Field(default_factory=dict)
    rcv_clock_offs_appl: int = 0
    leap_seconds: pint.Quantity | None = None
    num_satellites: int | None = None

    @field_validator("marker_number", mode="before")
    @classmethod
    def parse_marker_number(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v).strip()

    @classmethod
    def from_file(cls, fpath: Path) -> Self:
        """Parse header from a RINEX v2.11 observation file."""
        fpath = Path(fpath)
        if not fpath.exists():
            msg = f"File {fpath} does not exist."
            raise FileNotFoundError(msg)

        header_lines: list[str] = []
        with fpath.open(encoding="ascii", errors="replace") as f:
            for raw_line in f:
                header_lines.append(raw_line.rstrip("\n"))
                if "END OF HEADER" in raw_line:
                    break

        parsed = cls._parse_header_lines(header_lines, fpath)
        return cls.model_validate(parsed)

    @staticmethod
    def _parse_header_lines(
        lines: list[str],
        fpath: Path,
    ) -> dict[str, Any]:
        """Parse raw header lines into structured data."""
        data: dict[str, Any] = {"fpath": fpath}

        obs_types: list[str] = []
        comments: list[str] = []
        wavelength_sat_specific: dict[str, tuple[int, int]] = {}
        wl_l1_default = 1
        wl_l2_default = 1

        for line in lines:
            # Pad line to 80 chars for fixed-width parsing
            line = line.ljust(80)
            label = line[60:80].strip()

            if label == "RINEX VERSION / TYPE":
                data["version"] = float(line[:9].strip())
                data["filetype"] = line[20:21].strip()
                sys_char = line[40:41].strip()
                data["systems"] = sys_char if sys_char else "G"

            elif label == "PGM / RUN BY / DATE":
                data["pgm"] = line[:20].strip()
                data["run_by"] = line[20:40].strip()
                date_str = line[40:60].strip()
                data["date"] = _parse_v2_header_date(date_str)

            elif label == "COMMENT":
                comments.append(line[:60].strip())

            elif label == "MARKER NAME":
                data["marker_name"] = line[:60].strip()

            elif label == "MARKER NUMBER":
                data["marker_number"] = line[:20].strip()

            elif label == "OBSERVER / AGENCY":
                data["observer"] = line[:20].strip()
                data["agency"] = line[20:60].strip()

            elif label == "REC # / TYPE / VERS":
                data["receiver_number"] = line[:20].strip()
                data["receiver_type"] = line[20:40].strip()
                data["receiver_version"] = line[40:60].strip()

            elif label == "ANT # / TYPE":
                data["antenna_number"] = line[:20].strip()
                data["antenna_type"] = line[20:40].strip()

            elif label == "APPROX POSITION XYZ":
                x = _safe_float(line[0:14]) * UREG.meters
                y = _safe_float(line[14:28]) * UREG.meters
                z = _safe_float(line[28:42]) * UREG.meters
                data["approx_position"] = [x, y, z]

            elif label == "ANTENNA: DELTA H/E/N":
                h = _safe_float(line[0:14]) * UREG.meters
                e = _safe_float(line[14:28]) * UREG.meters
                n = _safe_float(line[28:42]) * UREG.meters
                data["antenna_delta"] = [h, e, n]

            elif label == "WAVELENGTH FACT L1/2":
                wl1 = int(line[0:6].strip() or "1")
                wl2 = int(line[6:12].strip() or "1")
                num_sats_str = line[12:18].strip()
                if num_sats_str and int(num_sats_str) > 0:
                    # Satellite-specific wavelength factors
                    num_sats = int(num_sats_str)
                    for j in range(num_sats):
                        offset = 18 + j * 6
                        sat_id = line[offset : offset + 6].strip()
                        # Normalize: "G14" or " 14" → "G14"
                        if sat_id and len(sat_id) >= 2:
                            if sat_id[0] == " ":
                                sat_id = "G" + sat_id[-2:]
                            sat_id = sat_id[0] + sat_id[-2:].zfill(2)
                        wavelength_sat_specific[sat_id] = (wl1, wl2)
                else:
                    # Default wavelength factors
                    wl_l1_default = wl1
                    wl_l2_default = wl2

            elif label == "# / TYPES OF OBSERV":
                if not obs_types:
                    # First line: number of obs types + up to 9 types
                    n_obs = int(line[:6].strip())
                    for j in range(min(n_obs, 9)):
                        offset = 6 + j * 6
                        ot = line[offset + 4 : offset + 6].strip()
                        if ot:
                            obs_types.append(ot)
                else:
                    # Continuation line: up to 9 more types
                    for j in range(9):
                        offset = 6 + j * 6
                        ot = line[offset + 4 : offset + 6].strip()
                        if ot:
                            obs_types.append(ot)

            elif label == "INTERVAL":
                data["interval"] = _safe_float(line[:10])

            elif label == "TIME OF FIRST OBS":
                year = int(line[0:6].strip())
                month = int(line[6:12].strip())
                day = int(line[12:18].strip())
                hour = int(line[18:24].strip())
                minute = int(line[24:30].strip())
                sec = float(line[30:43].strip())
                time_sys = line[48:51].strip()
                dt = datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    int(sec),
                    int((sec % 1) * 1e6),
                    tzinfo=UTC,
                )
                data["time_system"] = time_sys if time_sys else "GPS"
                data["t0"] = {"GPS": dt, "UTC": dt}

            elif label == "TIME OF LAST OBS":
                pass  # Not needed for parsing

            elif label == "RCV CLOCK OFFS APPL":
                val = line[:6].strip()
                data["rcv_clock_offs_appl"] = int(val) if val else 0

            elif label == "LEAP SECONDS":
                val = line[:6].strip()
                if val:
                    data["leap_seconds"] = int(val) * UREG.seconds

            elif label == "# OF SATELLITES":
                val = line[:6].strip()
                if val:
                    data["num_satellites"] = int(val)

            elif label == "PRN / # OF OBS":
                pass  # Documentary, not needed

        # Fill defaults
        data.setdefault("marker_name", "")
        data.setdefault("observer", "")
        data.setdefault("agency", "")
        data.setdefault("receiver_number", "")
        data.setdefault("receiver_type", "")
        data.setdefault("receiver_version", "")
        data.setdefault("antenna_number", "")
        data.setdefault("antenna_type", "")
        data.setdefault("approx_position", [0 * UREG.meters] * 3)
        data.setdefault("antenna_delta", [0 * UREG.meters] * 3)
        data.setdefault("pgm", "")
        data.setdefault("run_by", "")
        data.setdefault("date", datetime.now(UTC))
        data.setdefault("time_system", "GPS")
        data.setdefault("t0", {"GPS": datetime.now(UTC)})

        data["obs_types"] = obs_types
        data["wavelength_fact_l1"] = wl_l1_default
        data["wavelength_fact_l2"] = wl_l2_default
        data["wavelength_fact_satellites"] = wavelength_sat_specific

        if comments:
            data["comment"] = "\n".join(comments)

        # Build obs_codes_per_system: map v2 codes to v3 per system
        system_char = data.get("systems", "G")
        if system_char == "M":
            # Mixed: we'll assign all obs types to each system found.
            # Actual filtering happens during observation parsing.
            systems_present = ["G", "R", "S", "E"]
        elif system_char in ("G", " ", ""):
            systems_present = ["G"]
        else:
            systems_present = [system_char]

        # Store parsed v2 obs codes per system (type+freq_num+tracking_code)
        v3_style_codes = [
            f"{t}{f}{c}" for t, f, c in (_parse_v2_obs_code(ot) for ot in obs_types)
        ]
        data["obs_codes_per_system"] = dict.fromkeys(systems_present, v3_style_codes)

        return data

    @property
    def is_mixed_systems(self) -> bool:
        """Check if the RINEX file contains mixed GNSS systems."""
        return self.systems == "M"

    def __repr__(self) -> str:
        return (
            f"Rnxv2Header(file='{self.fpath.name}', "
            f"version={self.version}, systems='{self.systems}')"
        )

    def __str__(self) -> str:
        systems_str = "Mixed" if self.systems == "M" else self.systems
        return (
            f"RINEX v{self.version} Header\n"
            f"  File: {self.fpath.name}\n"
            f"  Marker: {self.marker_name}\n"
            f"  Systems: {systems_str}\n"
            f"  Receiver: {self.receiver_type}\n"
            f"  Obs types: {', '.join(self.obs_types)}\n"
            f"  Date: {self.date.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        )


def _parse_v2_header_date(date_str: str) -> datetime:
    """Parse date string from PGM / RUN BY / DATE header.

    Tries multiple common formats used by different RINEX producers.
    """
    formats = [
        "%d-%b-%y %H:%M",  # 24-MAR-01 14:43
        "%d-%b-%Y %H:%M",  # 24-MAR-2001 14:43
        "%Y%m%d %H%M%S",  # 20050324 141200
        "%Y-%m-%d %H:%M",  # 2005-03-24 14:12
        "%y-%b-%d %H:%M",  # 01-MAR-24 14:43
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue

    # Last resort: try to extract components
    parts = date_str.split()
    if parts:
        try:
            dt = datetime.strptime(parts[0], "%d-%b-%y")
            return dt.replace(tzinfo=UTC)
        except ValueError:
            pass

    return datetime.now(UTC)


def _safe_float(s: str, default: float = 0.0) -> float:
    """Safely convert string to float."""
    try:
        return float(s.strip())
    except (ValueError, TypeError):
        return default


# --------------------------------------------------------------------------- #
# Epoch record dataclass
# --------------------------------------------------------------------------- #


class Rnxv2EpochRecord:
    """Represents a parsed RINEX v2 epoch with satellite observations.

    Attributes
    ----------
    year : int
        4-digit year.
    month, day, hour, minute : int
        Time components.
    seconds : float
        Seconds with fractional part.
    epoch_flag : int
        Epoch flag (0=OK, 1=power failure, 2-5=events, 6=cycle slips).
    num_satellites : int
        Number of satellites in this epoch.
    satellite_list : list[str]
        PRN identifiers (e.g., ["G12", "G09", "R21"]).
    receiver_clock_offset : float or None
        Receiver clock offset in seconds.
    satellites : list[Satellite]
        Parsed satellite observation data.
    """

    __slots__ = (
        "day",
        "epoch_flag",
        "hour",
        "minute",
        "month",
        "num_satellites",
        "receiver_clock_offset",
        "satellite_list",
        "satellites",
        "seconds",
        "year",
    )

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        seconds: float,
        epoch_flag: int,
        num_satellites: int,
        satellite_list: list[str],
        receiver_clock_offset: float | None,
        satellites: list[Satellite],
    ) -> None:
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.seconds = seconds
        self.epoch_flag = epoch_flag
        self.num_satellites = num_satellites
        self.satellite_list = satellite_list
        self.receiver_clock_offset = receiver_clock_offset
        self.satellites = satellites


# --------------------------------------------------------------------------- #
# Main reader
# --------------------------------------------------------------------------- #


class Rnxv2Obs(GNSSDataReader, BaseModel):
    """RINEX v2.11 observation reader.

    Parses RINEX v2.11 observation files (GPS, GLONASS, Galileo, SBAS, Mixed)
    and converts them to ``xarray.Dataset`` with ``(epoch, sid)`` dimensions,
    consistent with the v3.04 reader output.

    Attributes
    ----------
    fpath : Path
        Path to the RINEX observation file.
    polarization : str
        Polarization label for observables (default "RHCP").
    aggregate_glonass_fdma : bool
        Whether to aggregate GLONASS FDMA channels (default True).
    apply_overlap_filter : bool
        Whether to filter overlapping signal groups (default False).
    overlap_preferences : dict[str, str] or None
        Preferred signals for overlap resolution.

    Notes
    -----
    Inherits from ``GNSSDataReader`` and Pydantic ``BaseModel``.
    """

    fpath: Path
    polarization: str = "RHCP"
    aggregate_glonass_fdma: bool = True
    apply_overlap_filter: bool = False
    overlap_preferences: dict[str, str] | None = None

    _header: Rnxv2Header = PrivateAttr()
    _signal_mapper: SignalIDMapper = PrivateAttr()
    _lines: list[str] = PrivateAttr()
    _file_hash: str = PrivateAttr()
    _header_end_line: int = PrivateAttr()

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
    )

    @model_validator(mode="after")
    def _post_init(self) -> Self:
        """Initialize derived state after validation."""
        self._header = Rnxv2Header.from_file(self.fpath)
        self._signal_mapper = SignalIDMapper(
            aggregate_glonass_fdma=self.aggregate_glonass_fdma,
        )
        self._lines = self._load_file()
        return self

    @property
    def header(self) -> Rnxv2Header:
        return self._header

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}:\n"
            f"  File Path: {self.fpath}\n"
            f"  Header: {self.header}\n"
            f"  Polarization: {self.polarization}\n"
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(fpath={self.fpath})"

    # ---- File I/O --------------------------------------------------------- #

    def _load_file(self) -> list[str]:
        """Read file, cache lines, compute hash, find header end."""
        h = hashlib.sha256()
        with self.fpath.open("rb") as f:
            data = f.read()
            h.update(data)
            lines = data.decode("utf-8", errors="replace").splitlines()
        self._file_hash = h.hexdigest()[:16]

        # Find line after END OF HEADER
        self._header_end_line = 0
        for i, line in enumerate(lines):
            if "END OF HEADER" in line:
                self._header_end_line = i + 1
                break

        return lines

    @property
    def file_hash(self) -> str:
        return self._file_hash

    # ---- Abstract property implementations -------------------------------- #

    @property
    def start_time(self) -> datetime:
        return min(self.header.t0.values())

    @property
    def end_time(self) -> datetime:
        last_epoch = None
        for epoch in self.iter_epochs():
            last_epoch = epoch
        if last_epoch:
            return datetime(
                last_epoch.year,
                last_epoch.month,
                last_epoch.day,
                last_epoch.hour,
                last_epoch.minute,
                int(last_epoch.seconds),
                int((last_epoch.seconds % 1) * 1e6),
                tzinfo=UTC,
            )
        return self.start_time

    @property
    def systems(self) -> list[str]:
        if self.header.systems == "M":
            return list(self.header.obs_codes_per_system.keys())
        return [self.header.systems]

    @property
    def num_epochs(self) -> int:
        return sum(1 for _ in self.iter_epochs())

    @property
    def num_satellites(self) -> int:
        satellites = set()
        for epoch in self.iter_epochs():
            for sat in epoch.satellites:
                satellites.add(sat.sv)
        return len(satellites)

    # ---- Epoch parsing ---------------------------------------------------- #

    def _parse_epoch_line(
        self,
        line: str,
    ) -> tuple[int, int, int, int, int, float, int, int, list[str], float | None]:
        """Parse a RINEX v2 epoch/satellite line.

        Returns
        -------
        tuple
            (year, month, day, hour, minute, seconds, epoch_flag,
             num_sats, sat_list, receiver_clock_offset)

        Raises
        ------
        InvalidEpochError
            If the line cannot be parsed as an epoch record.
        """
        # Per Table A2: 1X,I2.2, 4(1X,I2), F11.7, 2X,I1, I3, 12(A1,I2), F12.9
        if len(line) < 32:
            msg = f"Epoch line too short: '{line}'"
            raise InvalidEpochError(msg)

        try:
            yy = int(line[1:3].strip() or "0")
            month = int(line[4:6].strip() or "0")
            day = int(line[7:9].strip() or "0")
            hour = int(line[10:12].strip() or "0")
            minute = int(line[13:15].strip() or "0")
            seconds = float(line[15:26].strip() or "0.0")
            epoch_flag = int(line[28:29].strip() or "0")
            num_sats = int(line[29:32].strip() or "0")
        except (ValueError, IndexError) as e:
            msg = f"Cannot parse epoch line: '{line}'"
            raise InvalidEpochError(msg) from e

        year = _expand_v2_year(yy)

        # Parse satellite list from epoch line (up to 12 per line)
        sat_list: list[str] = []
        sat_start = 32
        sats_on_line = min(num_sats, V2_MAX_SATS_PER_LINE)
        for j in range(sats_on_line):
            offset = sat_start + j * V2_SAT_FIELD_WIDTH
            if offset + V2_SAT_FIELD_WIDTH <= len(line):
                sat_str = line[offset : offset + V2_SAT_FIELD_WIDTH]
                sat_list.append(_normalize_sv(sat_str))

        # Receiver clock offset (optional, at cols 68-79)
        rcv_clock: float | None = None
        if len(line) >= 80:
            rcv_str = line[68:80].strip()
            if rcv_str:
                import contextlib

                with contextlib.suppress(ValueError):
                    rcv_clock = float(rcv_str)

        return (
            year,
            month,
            day,
            hour,
            minute,
            seconds,
            epoch_flag,
            num_sats,
            sat_list,
            rcv_clock,
        )

    def _parse_continuation_sat_lines(
        self,
        lines: list[str],
        line_idx: int,
        num_sats: int,
        sat_list: list[str],
    ) -> tuple[list[str], int]:
        """Parse satellite continuation lines when > 12 satellites.

        Returns
        -------
        tuple[list[str], int]
            (complete satellite list, next line index after continuations)
        """
        remaining = num_sats - len(sat_list)
        idx = line_idx
        while remaining > 0 and idx < len(lines):
            cont_line = lines[idx].ljust(80)
            sats_this_line = min(remaining, V2_MAX_SATS_PER_LINE)
            for j in range(sats_this_line):
                offset = 32 + j * V2_SAT_FIELD_WIDTH
                if offset + V2_SAT_FIELD_WIDTH <= len(cont_line):
                    sat_str = cont_line[offset : offset + V2_SAT_FIELD_WIDTH]
                    sat_list.append(_normalize_sv(sat_str))
            remaining = num_sats - len(sat_list)
            idx += 1
        return sat_list, idx

    def _parse_observation_value(
        self,
        field: str,
    ) -> tuple[float | None, int | None, int | None]:
        """Parse a single 16-char observation field: F14.3, I1(LLI), I1(SSI).

        Returns (value, lli, ssi).
        """
        if not field or not field.strip():
            return None, None, None

        # Pad to 16 chars if needed
        field = field.ljust(V2_OBS_FIELD_WIDTH)

        # Value is in chars 0-13 (F14.3)
        value_str = field[:14].strip()
        lli_char = field[14:15]
        ssi_char = field[15:16]

        value: float | None = None
        lli: int | None = None
        ssi: int | None = None

        if value_str:
            try:
                value = float(value_str)
                # RINEX spec: missing observations written as 0.0 or blanks
                if value == 0.0:
                    value = None
            except ValueError:
                pass

        if lli_char.strip() and lli_char.strip().isdigit():
            lli = int(lli_char)
        if ssi_char.strip() and ssi_char.strip().isdigit():
            ssi = int(ssi_char)

        return value, lli, ssi

    def _parse_satellite_observations(
        self,
        lines: list[str],
        start_idx: int,
        sv: str,
    ) -> tuple[Satellite, int]:
        """Parse observation records for a single satellite.

        RINEX v2 puts max 5 observations per line (5 x 16 = 80 chars).
        If more than 5 obs types, continuation lines follow.

        Returns
        -------
        tuple[Satellite, int]
            (Satellite object with observations, next line index)
        """
        obs_types_v2 = self.header.obs_types
        n_obs = len(obs_types_v2)
        n_lines = (n_obs + V2_MAX_OBS_PER_LINE - 1) // V2_MAX_OBS_PER_LINE

        satellite = Satellite(sv=sv)
        obs_idx = 0
        line_idx = start_idx

        for _line_num in range(n_lines):
            if line_idx >= len(lines):
                break
            obs_line = lines[line_idx]
            line_idx += 1

            # Parse up to 5 observations from this line
            for j in range(V2_MAX_OBS_PER_LINE):
                if obs_idx >= n_obs:
                    break
                col_start = j * V2_OBS_FIELD_WIDTH
                col_end = col_start + V2_OBS_FIELD_WIDTH

                field = obs_line[col_start:col_end] if col_start < len(obs_line) else ""

                value, lli, ssi = self._parse_observation_value(field)

                obs_code_v2 = obs_types_v2[obs_idx]
                obs_type_char, _freq_num, _tracking = _parse_v2_obs_code(obs_code_v2)

                observation = Observation(
                    obs_type=obs_type_char,
                    value=value,
                    lli=lli,
                    ssi=ssi,
                )
                satellite.add_observation(observation)
                obs_idx += 1

        return satellite, line_idx

    def iter_epochs(self):
        """Yield parsed epoch records from the file.

        Yields
        ------
        Rnxv2EpochRecord
            Each epoch with timestamp, flags, and satellite observations.
            Only yields epochs with epoch_flag 0 or 1 (normal observations).
        """
        lines = self._lines
        idx = self._header_end_line

        while idx < len(lines):
            line = lines[idx]

            # Skip empty lines
            if not line.strip():
                idx += 1
                continue

            # Try to parse as epoch line
            try:
                (
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    seconds,
                    epoch_flag,
                    num_sats,
                    sat_list,
                    rcv_clock,
                ) = self._parse_epoch_line(line)
            except (InvalidEpochError, ValueError):
                idx += 1
                continue

            idx += 1

            # Handle epoch flags 2-5: special records (header info, events)
            if V2_EPOCH_FLAG_START_MOVING <= epoch_flag <= V2_EPOCH_FLAG_EXTERNAL_EVENT:
                # Skip the num_sats special records that follow
                idx += num_sats
                continue

            # Handle epoch flag 6: cycle slip records
            if epoch_flag == V2_EPOCH_FLAG_CYCLE_SLIP:
                # Skip cycle slip records (same format as obs records)
                n_obs = len(self.header.obs_types)
                n_lines_per_sat = (
                    n_obs + V2_MAX_OBS_PER_LINE - 1
                ) // V2_MAX_OBS_PER_LINE
                idx += num_sats * n_lines_per_sat
                continue

            # Handle continuation lines for > 12 satellites
            if num_sats > V2_MAX_SATS_PER_LINE:
                sat_list, idx = self._parse_continuation_sat_lines(
                    lines,
                    idx,
                    num_sats,
                    sat_list,
                )

            # Parse observation records for each satellite
            satellites: list[Satellite] = []
            for sat_sv in sat_list:
                try:
                    satellite, idx = self._parse_satellite_observations(
                        lines,
                        idx,
                        sat_sv,
                    )
                    satellites.append(satellite)
                except (InvalidEpochError, IncompleteEpochError, ValueError):
                    # Skip malformed satellite data, advance to expected position
                    n_obs = len(self.header.obs_types)
                    n_lines_per_sat = (
                        n_obs + V2_MAX_OBS_PER_LINE - 1
                    ) // V2_MAX_OBS_PER_LINE
                    idx += n_lines_per_sat
                    continue

            yield Rnxv2EpochRecord(
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                seconds=seconds,
                epoch_flag=epoch_flag,
                num_satellites=num_sats,
                satellite_list=sat_list,
                receiver_clock_offset=rcv_clock,
                satellites=satellites,
            )

    # ---- Time helpers ----------------------------------------------------- #

    @staticmethod
    def epoch_to_datetime(epoch: Rnxv2EpochRecord) -> datetime:
        """Convert epoch record to datetime."""
        return datetime(
            epoch.year,
            epoch.month,
            epoch.day,
            epoch.hour,
            epoch.minute,
            int(epoch.seconds),
            int((epoch.seconds % 1) * 1e6),
            tzinfo=UTC,
        )

    @staticmethod
    def epoch_to_numpy_dt(epoch: Rnxv2EpochRecord) -> np.datetime64:
        """Convert epoch record to numpy datetime64[ns]."""
        dt = datetime(
            epoch.year,
            epoch.month,
            epoch.day,
            epoch.hour,
            epoch.minute,
            int(epoch.seconds),
            int((epoch.seconds % 1) * 1e6),
        )
        return np.datetime64(dt, "ns")

    def _epoch_datetimes(self) -> list[datetime]:
        """Extract all epoch datetimes."""
        return [self.epoch_to_datetime(e) for e in self.iter_epochs()]

    def infer_sampling_interval(self) -> pint.Quantity | None:
        """Infer sampling interval from consecutive epoch deltas."""
        if self.header.interval is not None and self.header.interval > 0:
            return (self.header.interval * UREG.second).to(UREG.seconds)

        dts = self._epoch_datetimes()
        if len(dts) < MIN_EPOCHS_FOR_INTERVAL:
            return None

        deltas = [b - a for a, b in pairwise(dts) if b >= a]
        if not deltas:
            return None

        seconds = Counter(
            int(dt.total_seconds()) for dt in deltas if dt.total_seconds() > 0
        )
        if not seconds:
            return None

        mode_seconds, _ = seconds.most_common(1)[0]
        return (mode_seconds * UREG.second).to(UREG.seconds)

    # ---- Dataset creation ------------------------------------------------- #

    def create_rinex_netcdf_with_signal_id(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> xr.Dataset:
        """Create xarray Dataset with signal ID structure.

        Two-pass approach:
        1. First pass: discover all signal IDs and collect timestamps.
        2. Second pass: fill data arrays.
        """
        # Pre-parse v2 obs codes → (obs_type, freq_num, tracking_code)
        obs_types_v2 = self.header.obs_types
        parsed_obs_codes = [_parse_v2_obs_code(ot) for ot in obs_types_v2]

        # Band frequency properties cache
        band_freq_cache: dict[str, tuple[float, float, float, float]] = {}
        mapper = self._signal_mapper
        system_bands = mapper.SYSTEM_BANDS

        signal_ids: set[str] = set()
        signal_id_to_properties: dict[str, dict[str, object]] = {}
        timestamps: list[np.datetime64] = []

        def _build_sid(sv: str, freq_num: str, tracking_code: str) -> str | None:
            """Build SID from SV, freq number, and tracking code.

            Uses SignalIDMapper.SYSTEM_BANDS to resolve the system-specific
            band name (e.g. GPS freq "1" → "L1", Galileo freq "1" → "E1",
            GLONASS freq "1" → "G1").
            """
            system = sv[0] if sv else "G"
            band_name = system_bands.get(system, {}).get(freq_num)
            if band_name is None:
                return None
            return f"{sv}|{band_name}|{tracking_code}"

        def _cache_band_freq(band: str) -> tuple[float, float, float, float]:
            if band not in band_freq_cache:
                center_frequency = mapper.get_band_frequency(band)
                bandwidth = mapper.get_band_bandwidth(band)
                if center_frequency is not None and bandwidth is not None:
                    bw = bandwidth[0] if isinstance(bandwidth, list) else bandwidth
                    if not hasattr(center_frequency, "m_as"):
                        center_frequency = center_frequency * UREG.MHz
                    if not hasattr(bw, "m_as"):
                        bw = bw * UREG.MHz
                    freq_min = center_frequency - (bw / 2.0)
                    freq_max = center_frequency + (bw / 2.0)
                    band_freq_cache[band] = (
                        float(center_frequency.m_as(UREG.MHz)),
                        float(freq_min.m_as(UREG.MHz)),
                        float(freq_max.m_as(UREG.MHz)),
                        float(bw.m_as(UREG.MHz)),
                    )
                else:
                    band_freq_cache[band] = (np.nan, np.nan, np.nan, np.nan)
            return band_freq_cache[band]

        # First pass: discover structure
        for epoch in self.iter_epochs():
            dt = self.epoch_to_datetime(epoch)
            if start and dt < start:
                continue
            if end and dt > end:
                continue

            timestamps.append(self.epoch_to_numpy_dt(epoch))

            for sat in epoch.satellites:
                sv = sat.sv
                for i, obs in enumerate(sat.observations):
                    if i >= len(parsed_obs_codes):
                        break
                    _obs_type, freq_num, tracking_code = parsed_obs_codes[i]
                    sid = _build_sid(sv, freq_num, tracking_code)
                    if sid is None:
                        continue

                    signal_ids.add(sid)

                    if sid not in signal_id_to_properties:
                        system = sv[0] if sv != "nan" else "?"
                        band_name = system_bands.get(system, {}).get(freq_num, "?")
                        overlapping_group = mapper.get_overlapping_group(band_name)
                        freq_center, freq_min, freq_max, bw = _cache_band_freq(
                            band_name
                        )

                        signal_id_to_properties[sid] = {
                            "sv": sv,
                            "system": system,
                            "band": band_name,
                            "code": tracking_code,
                            "freq_center": freq_center,
                            "freq_min": freq_min,
                            "freq_max": freq_max,
                            "bandwidth": bw,
                            "overlapping_group": overlapping_group,
                        }

        sorted_signal_ids = sorted(signal_ids)
        n_epochs = len(timestamps)
        n_signals = len(sorted_signal_ids)

        if n_epochs == 0 or n_signals == 0:
            return xr.Dataset()

        # Allocate arrays
        data_arrays = {
            "SNR": np.full((n_epochs, n_signals), np.nan, dtype=DTYPES["SNR"]),
            "Pseudorange": np.full(
                (n_epochs, n_signals),
                np.nan,
                dtype=DTYPES["Pseudorange"],
            ),
            "Phase": np.full(
                (n_epochs, n_signals),
                np.nan,
                dtype=DTYPES["Phase"],
            ),
            "Doppler": np.full(
                (n_epochs, n_signals),
                np.nan,
                dtype=DTYPES["Doppler"],
            ),
            "LLI": np.full((n_epochs, n_signals), -1, dtype=DTYPES["LLI"]),
            "SSI": np.full((n_epochs, n_signals), -1, dtype=DTYPES["SSI"]),
        }
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_signal_ids)}

        # Second pass: fill arrays
        t_idx = 0
        for epoch in self.iter_epochs():
            dt = self.epoch_to_datetime(epoch)
            if start and dt < start:
                continue
            if end and dt > end:
                continue

            for sat in epoch.satellites:
                sv = sat.sv
                for i, obs in enumerate(sat.observations):
                    if obs.value is None or i >= len(parsed_obs_codes):
                        continue
                    _ot, fn, tc = parsed_obs_codes[i]
                    sid = _build_sid(sv, fn, tc)
                    if sid is None or sid not in sid_to_idx:
                        continue
                    s_idx = sid_to_idx[sid]

                    ot = obs.obs_type
                    if ot == "S" and obs.value != 0:
                        data_arrays["SNR"][t_idx, s_idx] = obs.value
                    elif ot == "C":
                        data_arrays["Pseudorange"][t_idx, s_idx] = obs.value
                    elif ot == "L":
                        data_arrays["Phase"][t_idx, s_idx] = obs.value
                    elif ot == "D":
                        data_arrays["Doppler"][t_idx, s_idx] = obs.value

                    if obs.lli is not None:
                        data_arrays["LLI"][t_idx, s_idx] = obs.lli
                    if obs.ssi is not None:
                        data_arrays["SSI"][t_idx, s_idx] = obs.ssi

            t_idx += 1

        # Build coordinates
        signal_id_coord = xr.DataArray(
            sorted_signal_ids,
            dims=["sid"],
            attrs=COORDS_METADATA["sid"],
        )
        sv_list = [signal_id_to_properties[sid]["sv"] for sid in sorted_signal_ids]
        constellation_list = [
            signal_id_to_properties[sid]["system"] for sid in sorted_signal_ids
        ]
        band_list = [signal_id_to_properties[sid]["band"] for sid in sorted_signal_ids]
        code_list = [signal_id_to_properties[sid]["code"] for sid in sorted_signal_ids]
        freq_center_list = [
            signal_id_to_properties[sid]["freq_center"] for sid in sorted_signal_ids
        ]
        freq_min_list = [
            signal_id_to_properties[sid]["freq_min"] for sid in sorted_signal_ids
        ]
        freq_max_list = [
            signal_id_to_properties[sid]["freq_max"] for sid in sorted_signal_ids
        ]

        coords = {
            "epoch": ("epoch", timestamps, COORDS_METADATA["epoch"]),
            "sid": signal_id_coord,
            "sv": ("sid", sv_list, COORDS_METADATA["sv"]),
            "system": ("sid", constellation_list, COORDS_METADATA["system"]),
            "band": ("sid", band_list, COORDS_METADATA["band"]),
            "code": ("sid", code_list, COORDS_METADATA["code"]),
            "freq_center": (
                "sid",
                np.asarray(freq_center_list, dtype=DTYPES["freq_center"]),
                COORDS_METADATA["freq_center"],
            ),
            "freq_min": (
                "sid",
                np.asarray(freq_min_list, dtype=DTYPES["freq_min"]),
                COORDS_METADATA["freq_min"],
            ),
            "freq_max": (
                "sid",
                np.asarray(freq_max_list, dtype=DTYPES["freq_max"]),
                COORDS_METADATA["freq_max"],
            ),
        }

        # SNR metadata depends on signal strength unit
        snr_meta = SNR_METADATA

        ds = xr.Dataset(
            data_vars={
                "SNR": (["epoch", "sid"], data_arrays["SNR"], snr_meta),
                "Pseudorange": (
                    ["epoch", "sid"],
                    data_arrays["Pseudorange"],
                    OBSERVABLES_METADATA["Pseudorange"],
                ),
                "Phase": (
                    ["epoch", "sid"],
                    data_arrays["Phase"],
                    OBSERVABLES_METADATA["Phase"],
                ),
                "Doppler": (
                    ["epoch", "sid"],
                    data_arrays["Doppler"],
                    OBSERVABLES_METADATA["Doppler"],
                ),
                "LLI": (
                    ["epoch", "sid"],
                    data_arrays["LLI"],
                    OBSERVABLES_METADATA["LLI"],
                ),
                "SSI": (
                    ["epoch", "sid"],
                    data_arrays["SSI"],
                    OBSERVABLES_METADATA["SSI"],
                ),
            },
            coords=coords,
            attrs={**self._create_basic_attrs()},
        )

        if self.apply_overlap_filter:
            ds = self.filter_by_overlapping_groups(ds, self.overlap_preferences)

        return ds

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: Any,
    ) -> xr.Dataset:
        """Convert RINEX v2.11 observations to xarray.Dataset.

        Parameters
        ----------
        keep_data_vars : list of str, optional
            Data variables to include. Defaults to config value.
        **kwargs
            Additional keyword arguments:
            outname : Path or str, optional
                If provided, saves dataset to this file path.
            write_global_attrs : bool, default False
                If True, adds comprehensive global attributes.
            pad_global_sid : bool, default True
                If True, pads to global signal ID space.
            strip_fillval : bool, default True
                If True, removes fill values.
            add_future_datavars : bool, default True
                If True, adds placeholder variables for future data.
            keep_sids : list of str or None, default None
                If provided, filters/pads dataset to these specific SIDs.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid).
        """
        from typing import cast

        outname = cast(Path | str | None, kwargs.pop("outname", None))
        write_global_attrs = bool(kwargs.pop("write_global_attrs", False))
        pad_global_sid = bool(kwargs.pop("pad_global_sid", True))
        strip_fillval = bool(kwargs.pop("strip_fillval", True))
        add_future_datavars = bool(kwargs.pop("add_future_datavars", True))
        keep_sids = cast(list[str] | None, kwargs.pop("keep_sids", None))

        if keep_data_vars is None:
            from canvod.utils.config import load_config

            keep_data_vars = load_config().processing.processing.keep_rnx_vars

        ds = self.create_rinex_netcdf_with_signal_id()

        # Drop unwanted vars
        for var in list(ds.data_vars):
            if var not in keep_data_vars:
                ds = ds.drop_vars(var)

        if pad_global_sid:
            from canvod.auxiliary.preprocessing import pad_to_global_sid

            ds = pad_to_global_sid(ds, keep_sids=keep_sids)

        if strip_fillval:
            from canvod.auxiliary.preprocessing import strip_fillvalue

            ds = strip_fillvalue(ds)

        if add_future_datavars:
            pass

        if write_global_attrs:
            ds.attrs.update(self._create_comprehensive_attrs())
        ds.attrs.update(self._build_attrs())

        # Normalise string dtypes for Icechunk / Zarr V3 compatibility
        for name in list(ds.coords) + list(ds.data_vars):
            if ds[name].dtype.kind in ("U", "T"):
                ds[name] = ds[name].astype(object)

        if outname:
            from canvod.utils.config import load_config as _load_config

            comp = _load_config().processing.compression
            encoding = {
                var: {"zlib": comp.zlib, "complevel": comp.complevel}
                for var in ds.data_vars
            }
            ds.to_netcdf(str(outname), encoding=encoding)

        validate_dataset(ds, required_vars=keep_data_vars)

        return ds

    def filter_by_overlapping_groups(
        self,
        ds: xr.Dataset,
        group_preference: dict[str, str] | None = None,
    ) -> xr.Dataset:
        """Filter overlapping bands using per-group preferences."""
        if group_preference is None:
            group_preference = {
                "L1_E1_B1I": "L1",
                "L5_E5a": "L5",
                "L2_E5b_B2b": "L2",
            }

        keep = []
        for sid in ds.sid.values:
            _sv, band, _code = self._signal_mapper.parse_signal_id(str(sid))
            group = self._signal_mapper.get_overlapping_group(band)
            if group and group in group_preference:
                if band == group_preference[group]:
                    keep.append(sid)
            else:
                keep.append(sid)
        return ds.sel(sid=keep)

    # ---- Attribute helpers ------------------------------------------------ #

    def _create_basic_attrs(self) -> dict[str, object]:
        attrs = get_global_attrs()
        attrs["Created"] = datetime.now(UTC).isoformat()
        attrs["Software"] = (
            f"{attrs['Software']}, Version: {get_version_from_pyproject()}"
        )
        return attrs

    def _create_comprehensive_attrs(self) -> dict[str, object]:
        attrs = {
            "File Path": str(self.fpath),
            "File Type": self.header.filetype,
            "RINEX Version": self.header.version,
            "Systems": self.header.systems,
            "Observer": self.header.observer,
            "Agency": self.header.agency,
            "Date": self.header.date.isoformat(),
            "Marker Name": self.header.marker_name,
            "Marker Number": self.header.marker_number,
            "Approximate Position": (
                f"(X = {self.header.approx_position[0].magnitude} "
                f"{self.header.approx_position[0].units:~}, "
                f"Y = {self.header.approx_position[1].magnitude} "
                f"{self.header.approx_position[1].units:~}, "
                f"Z = {self.header.approx_position[2].magnitude} "
                f"{self.header.approx_position[2].units:~})"
            ),
            "Antenna Delta H/E/N": (
                f"(H = {self.header.antenna_delta[0].magnitude} "
                f"{self.header.antenna_delta[0].units:~}, "
                f"E = {self.header.antenna_delta[1].magnitude} "
                f"{self.header.antenna_delta[1].units:~}, "
                f"N = {self.header.antenna_delta[2].magnitude} "
                f"{self.header.antenna_delta[2].units:~})"
            ),
            "Receiver Type": self.header.receiver_type,
            "Receiver Version": self.header.receiver_version,
            "Receiver Number": self.header.receiver_number,
            "Antenna Type": self.header.antenna_type,
            "Antenna Number": self.header.antenna_number,
            "Program": self.header.pgm,
            "Run By": self.header.run_by,
            "Time System": self.header.time_system,
            "Observation Types (v2)": ", ".join(self.header.obs_types),
            "Wavelength Factor L1": self.header.wavelength_fact_l1,
            "Wavelength Factor L2": self.header.wavelength_fact_l2,
            "Time of First Observation": json.dumps(
                {k: v.isoformat() for k, v in self.header.t0.items()}
            ),
        }
        if self.header.leap_seconds is not None:
            attrs["Leap Seconds"] = f"{self.header.leap_seconds:~}"
        return attrs


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _normalize_sv(sv_str: str) -> str:
    """Normalize a RINEX v2 satellite identifier to standard 3-char format.

    Rules per section 5.1:
    - "G" or blank prefix → GPS (default)
    - "R" → GLONASS
    - "S" → Geostationary signal payload
    - "E" → Galileo

    Examples
    --------
    >>> _normalize_sv("G12")
    'G12'
    >>> _normalize_sv(" 12")
    'G12'
    >>> _normalize_sv("12")
    'G12'
    >>> _normalize_sv("R21")
    'R21'
    >>> _normalize_sv("E11")
    'E11'
    """
    sv_str = sv_str.strip()
    if not sv_str:
        return "G00"

    if len(sv_str) == 2 and sv_str.isdigit():
        # Pure numeric → GPS
        return f"G{sv_str.zfill(2)}"

    if len(sv_str) >= 2:
        prefix = sv_str[0]
        num_part = sv_str[1:].strip()

        if prefix == " " or prefix.isdigit():
            # Blank or digit prefix → GPS
            if prefix.isdigit():
                num_part = prefix + num_part
            return f"G{num_part.zfill(2)}"

        if prefix in ("G", "R", "S", "E"):
            return f"{prefix}{num_part.zfill(2)}"

    # Fallback
    return f"G{sv_str[-2:].zfill(2)}" if len(sv_str) >= 2 else f"G{sv_str.zfill(2)}"


# --------------------------------------------------------------------------- #
# Factory registration
# --------------------------------------------------------------------------- #


def _register_factory() -> None:
    """Register Rnxv2Obs with ReaderFactory on module import."""
    import contextlib

    with contextlib.suppress(ImportError):
        from canvod.readers.base import ReaderFactory

        ReaderFactory.register("rinex_v2", Rnxv2Obs)


_register_factory()
