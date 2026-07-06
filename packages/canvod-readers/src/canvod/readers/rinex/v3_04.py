"""RINEX v3.04 observation file reader.

Migrated from: gnssvodpy/rinexreader/rinex_reader.py

Changes from original:
- Updated imports to use canvod.readers.gnss_specs
- Added structured logging for LLM-friendly diagnostics
- Removed IcechunkPreprocessor calls (TODO: move to canvod-store)
- Preserved all other functionality

Classes:
- Rnxv3Header: Parse RINEX v3 headers
- Rnxv3Obs: Main reader class, converts RINEX to xarray Dataset
"""

import hashlib
import json
import re
import warnings
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, Self, cast

import georinex as gr
import numpy as np
import pint
import pytz
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
from canvod.readers.gnss_specs.constants import (
    EPOCH_RECORD_INDICATOR,
    UREG,
)
from canvod.readers.gnss_specs.exceptions import (
    IncompleteEpochError,
    InvalidEpochError,
    MissingEpochError,
)
from canvod.readers.gnss_specs.metadata import (
    CN0_METADATA,
    COORDS_METADATA,
    DTYPES,
    OBSERVABLES_METADATA,
    SNR_METADATA,
)
from canvod.readers.gnss_specs.models import (
    Observation,
    RINEX304ComplianceValidator,
    RnxObsFileModel,
    Rnxv3ObsEpochRecord,
    Rnxv3ObsEpochRecordCompletenessModel,
    Rnxv3ObsEpochRecordLineModel,
    RnxVersion3Model,
    Satellite,
)
from canvod.readers.gnss_specs.signals import SignalIDMapper

GLONASS_COD_PHS_MIN_COMPONENTS = 6
PGM_RUNBY_MIN_COMPONENTS = 4
TIME_OF_FIRST_OBS_MIN_COMPONENTS = 6
RECEIVER_COMPONENTS_SECOND = 2
POSITION_PARTS_MIN = 2
DELTA_PARTS_MIN = 2
OBS_SLICE_MIN_LEN = 6
OBS_SLICE_MAX_LEN = 16
OBS_SLICE_DECIMAL_POS = -6
LLI_SSI_PAIR_LEN = 2
MIN_EPOCHS_FOR_INTERVAL = 2


def _str_to_object(ds: xr.Dataset) -> xr.Dataset:
    """Cast StringDType / fixed-width unicode coords and vars to object dtype.

    NumPy 2.x introduces ``StringDType`` (kind ``"T"``) which Zarr V3 /
    Icechunk cannot round-trip.  Fixed-width unicode (kind ``"U"``) also
    causes dtype mismatches on store append.  Normalising to ``object``
    keeps behaviour identical to NumPy 1.x.
    """
    for name in list(ds.coords) + list(ds.data_vars):
        if ds[name].dtype.kind in ("U", "T"):
            ds[name] = ds[name].astype(object)
    return ds


# --- Fast-path constants ---
_EPOCH_RE = re.compile(
    r"^>\s*(\d{4})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d{2})\s+(\d+\.\d+)\s+(\d+)\s+(\d+)"
)

_CONSTELLATION_SVS: dict[str, list[str]] = {
    "G": [f"G{i:02d}" for i in range(1, 33)],
    "E": [f"E{i:02d}" for i in range(1, 37)],
    "R": [f"R{i:02d}" for i in range(1, 25)],
    "C": [f"C{i:02d}" for i in range(1, 64)],
    "J": [f"J{i:02d}" for i in range(1, 11)],
    "S": [f"S{i:02d}" for i in range(1, 37)],
    "I": [f"I{i:02d}" for i in range(1, 15)],
}

_OBS_VAL_END = 14


def _get_constellation_svs(system: str) -> list[str]:
    """Return static list of SV identifiers for a GNSS system."""
    return _CONSTELLATION_SVS.get(system, [])


def _parse_obs_fast(slice_text: str) -> tuple[float | None, int | None, int | None]:
    """Parse RINEX observation slice using direct string indexing.

    Standard RINEX v3 format: 14 chars value + 1 char LLI + 1 char SSI = 16 chars.
    """
    if len(slice_text) < OBS_SLICE_MIN_LEN:
        return None, None, None

    try:
        val_end = min(_OBS_VAL_END, len(slice_text))
        val_str = slice_text[:val_end].strip()
        if not val_str:
            return None, None, None

        value = float(val_str)

        obs_lli = None
        obs_ssi = None
        if len(slice_text) > _OBS_VAL_END:
            c = slice_text[_OBS_VAL_END]
            if c.isdigit():
                obs_lli = int(c)
        if len(slice_text) > _OBS_VAL_END + 1:
            c = slice_text[_OBS_VAL_END + 1]
            if c.isdigit():
                obs_ssi = int(c)

        return value, obs_lli, obs_ssi
    except ValueError:
        return None, None, None


class Rnxv3Header(BaseModel):
    """Enhanced RINEX v3 header following the original implementation logic.

    Key changes from previous version:
    - date field is now datetime (like original)
    - Uses the original parsing logic for __get_pgm_runby_date

    Notes
    -----
    This is a Pydantic `BaseModel` configured with `ConfigDict` (frozen,
    validate_assignment, arbitrary_types_allowed, str_strip_whitespace). Prefer
    :meth:`from_file` for construction.

    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )

    # Required fields
    fpath: Path
    version: float
    filetype: str
    rinextype: str
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
    antenna_position: list[pint.Quantity]
    t0: dict[str, datetime]
    signal_strength_unit: pint.Unit | str
    obs_codes_per_system: dict[str, list[str]]

    # Optional fields with defaults
    comment: str | None = None
    marker_number: int | None = None
    marker_type: str | None = None
    glonass_cod: str | None = None
    glonass_phs: str | None = None
    glonass_bis: str | None = None
    glonass_slot_freq_dict: dict[str, int] = Field(default_factory=dict)
    leap_seconds: pint.Quantity | None = None
    system_phase_shift: dict[str, dict[str, float | None]] = Field(default_factory=dict)

    @field_validator("marker_number", mode="before")
    @classmethod
    def parse_marker_number(cls, v: object) -> int | None:
        """Convert empty strings to None, parse valid integers."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        try:
            if not isinstance(v, (str, int, float)):
                return None
            return int(v)
        except ValueError, TypeError:
            return None

    @classmethod
    def from_file(cls, fpath: Path) -> Self:
        """Create header from a RINEX file."""
        # External validation models handle file and version checks
        _ = RnxObsFileModel(fpath=fpath)

        try:
            header = gr.rinexheader(fpath)
        except (OSError, ValueError, TypeError) as e:
            msg = f"Failed to read RINEX header: {e}"
            raise ValueError(msg) from e

        cast(Any, RnxVersion3Model).version_must_be_3(header["version"])

        # Parse and create instance using original logic
        parsed_data = cls._parse_header_data(cast(dict[str, Any], header), fpath)
        return cls.model_validate(parsed_data)

    @staticmethod
    def _parse_header_data(
        header: dict[str, Any],
        fpath: Path,
    ) -> dict[str, Any]:
        """Parse raw header into structured data using original logic.

        Parameters
        ----------
        header : dict[str, Any]
            Raw header dictionary returned by `georinex`.
        fpath : Path
            Path to the RINEX file.

        Returns
        -------
        dict[str, Any]
            Parsed header data suitable for model validation.

        """
        data = {
            "fpath": fpath,
            "version": header.get("version", 3.0),
            "filetype": header.get("filetype", ""),
            "rinextype": header.get("rinextype", ""),
            "systems": header.get("systems", ""),
        }

        if "PGM / RUN BY / DATE" in header:
            pgm, run_by, date_dt = Rnxv3Header._get_pgm_runby_date(header)
            data.update(
                {
                    "pgm": pgm,
                    "run_by": run_by,
                    "date": date_dt,  # This is now a datetime object
                }
            )
        else:
            data.update(
                {
                    "pgm": "",
                    "run_by": "",
                    "date": datetime.now(UTC),  # Default to current time
                }
            )

        if "OBSERVER / AGENCY" in header:
            observer, agency = Rnxv3Header._get_observer_agency(header)
            data.update({"observer": observer, "agency": agency})
        else:
            data.update({"observer": "", "agency": ""})

        if "REC # / TYPE / VERS" in header:
            rec_num, rec_type, rec_version = Rnxv3Header._get_receiver_num_type_version(
                header
            )
            data.update(
                {
                    "receiver_number": rec_num,
                    "receiver_type": rec_type,
                    "receiver_version": rec_version,
                }
            )
        else:
            data.update(
                {"receiver_number": "", "receiver_type": "", "receiver_version": ""}
            )

        if "ANT # / TYPE" in header:
            ant_num, ant_type = Rnxv3Header._get_antenna_num_type(header)
            data.update({"antenna_number": ant_num, "antenna_type": ant_type})
        else:
            data.update({"antenna_number": "", "antenna_type": ""})

        # Parse positions with safe fallbacks
        pos_parts = header.get("APPROX POSITION XYZ", "0 0 0").split()
        delta_parts = header.get("ANTENNA: DELTA H/E/N", "0 0 0").split()

        def safe_float(s: str, default: float = 0.0) -> float:
            try:
                return float(s)
            except ValueError, TypeError:
                return default

        pos_y = (
            safe_float(pos_parts[1]) * UREG.meters
            if len(pos_parts) > 1
            else 0.0 * UREG.meters
        )
        pos_z = (
            safe_float(pos_parts[2]) * UREG.meters
            if len(pos_parts) > POSITION_PARTS_MIN
            else 0.0 * UREG.meters
        )
        ant_y = (
            safe_float(delta_parts[1]) * UREG.meters
            if len(delta_parts) > 1
            else 0.0 * UREG.meters
        )
        ant_z = (
            safe_float(delta_parts[2]) * UREG.meters
            if len(delta_parts) > DELTA_PARTS_MIN
            else 0.0 * UREG.meters
        )

        data.update(
            {
                "approx_position": [
                    safe_float(pos_parts[0]) * UREG.meters,
                    pos_y,
                    pos_z,
                ],
                "antenna_position": [
                    safe_float(delta_parts[0]) * UREG.meters,
                    ant_y,
                    ant_z,
                ],
            }
        )

        if "TIME OF FIRST OBS" in header:
            data["t0"] = Rnxv3Header._get_time_of_first_obs(header)
        else:
            now = datetime.now(UTC)
            data["t0"] = {
                "UTC": now if now.tzinfo is not None else now.replace(tzinfo=UTC),
                "GPS": now,
            }

        # Signal strength unit
        data["signal_strength_unit"] = Rnxv3Header._get_signal_strength_unit(header)

        # Basic fields
        data.update(
            {
                "comment": header.get("COMMENT"),
                "marker_name": header.get("MARKER NAME", "").strip(),
                "marker_number": header.get("MARKER NUMBER"),
                "marker_type": header.get("MARKER TYPE"),
                "obs_codes_per_system": header.get("fields", {}),
            }
        )

        # Optional GLONASS fields using original methods
        if "GLONASS COD/PHS/BIS" in header:
            cod, phs, bis = Rnxv3Header._get_glonass_cod_phs_bis(header)
            data.update({"glonass_cod": cod, "glonass_phs": phs, "glonass_bis": bis})

        if "GLONASS SLOT / FRQ #" in header:
            data["glonass_slot_freq_dict"] = Rnxv3Header._get_glonass_slot_freq_num(
                header
            )

        # Leap seconds
        if "LEAP SECONDS" in header:
            leap_parts = header["LEAP SECONDS"].split()
            if leap_parts and leap_parts[0].lstrip("-").isdigit():
                data["leap_seconds"] = int(leap_parts[0]) * UREG.seconds

        # System phase shift using original method
        if "SYS / PHASE SHIFT" in header:
            data["system_phase_shift"] = Rnxv3Header._get_sys_phase_shift(header)
        else:
            data["system_phase_shift"] = {}

        return data

    @staticmethod
    def _get_pgm_runby_date(
        header_dict: dict[str, Any],
    ) -> tuple[str, str, datetime]:
        """Parse ``PGM / RUN BY / DATE`` into program, run_by, and datetime.

        Based on the original __get_pgm_runby_date method.
        """
        header_value = header_dict.get("PGM / RUN BY / DATE", "")
        components = header_value.split()

        if not components:
            return "", "", datetime.now(UTC)

        pgm = components[0]
        run_by = components[1] if len(components) > PGM_RUNBY_MIN_COMPONENTS else ""

        # Original logic for extracting date components
        date = (
            [components[-3], components[-2], components[-1]]
            if len(components) > 1
            else None
        )

        if date:
            try:
                # Original parsing logic
                dt = datetime.strptime(
                    date[0] + date[1],
                    "%Y%m%d%H%M%S",
                )
                tz = pytz.timezone(date[2])  # e.g., "UTC"
                localized_date = tz.localize(dt)
                return pgm, run_by, localized_date
            except (ValueError, TypeError) as e:
                print(f"Warning: Could not parse date components {date}: {e}")
                return pgm, run_by, datetime.now(UTC)
        else:
            return pgm, run_by, datetime.now(UTC)

    @staticmethod
    def _get_observer_agency(header_dict: dict[str, Any]) -> tuple[str, str]:
        """Parse ``OBSERVER / AGENCY`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str]
            (observer, agency).

        """
        header_value = header_dict.get("OBSERVER / AGENCY", "")
        try:
            observer, agency = header_value.split(maxsplit=1)
            return observer, agency
        except ValueError:
            return "", ""

    @staticmethod
    def _get_receiver_num_type_version(
        header_dict: dict[str, Any],
    ) -> tuple[str, str, str]:
        """Parse ``REC # / TYPE / VERS`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str, str]
            (receiver_number, receiver_type, receiver_version).

        """
        header_value = header_dict.get("REC # / TYPE / VERS", "")
        components = header_value.split()

        if not components:
            return "", "", ""
        if len(components) == 1:
            return components[0], "", ""
        if len(components) == RECEIVER_COMPONENTS_SECOND:
            return components[0], components[1], ""
        return components[0], " ".join(components[1:-1]), components[-1]

    @staticmethod
    def _get_antenna_num_type(header_dict: dict[str, Any]) -> tuple[str, str]:
        """Parse ``ANT # / TYPE`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str]
            (antenna_number, antenna_type).

        """
        header_value = header_dict.get("ANT # / TYPE", "")
        components = header_value.split()

        if not components:
            return "", ""
        if len(components) == 1:
            return components[0], ""
        return components[0], " ".join(components[1:])

    @staticmethod
    def _get_time_of_first_obs(
        header_dict: dict[str, Any],
    ) -> dict[str, datetime]:
        """Parse ``TIME OF FIRST OBS`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        dict[str, datetime]
            Mapping of time system labels to datetimes.

        """
        header_value = header_dict.get("TIME OF FIRST OBS", "")
        components = header_value.split()

        if len(components) < TIME_OF_FIRST_OBS_MIN_COMPONENTS:
            now = datetime.now(UTC)
            return {"UTC": now, "GPS": now}

        try:
            year, month, day = map(int, components[:3])
            hour, minute = map(int, components[3:5])
            second = float(components[5])

            dt_gps = datetime(
                year,
                month,
                day,
                hour,
                minute,
                int(second),
                int((second - int(second)) * 1e6),
                tzinfo=UTC,
            )

            gps_utc_offset = timedelta(seconds=18)
            dt_utc = dt_gps - gps_utc_offset
            tz = pytz.timezone("UTC")

            return {"UTC": tz.localize(dt_utc), "GPS": dt_gps}

        except ValueError, TypeError, IndexError:
            now = datetime.now(UTC)
            return {"UTC": now, "GPS": now}

    @staticmethod
    def _get_glonass_cod_phs_bis(
        header_dict: dict[str, Any],
    ) -> tuple[str, str, str]:
        """Parse ``GLONASS COD/PHS/BIS`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        tuple[str, str, str]
            (glonass_cod, glonass_phs, glonass_bis).

        """
        header_value = header_dict.get("GLONASS COD/PHS/BIS", "")
        components = header_value.split()

        if len(components) >= GLONASS_COD_PHS_MIN_COMPONENTS:
            c1c = f"{components[0]} {components[1]}"
            c2c = f"{components[2]} {components[3]}"
            c2p = f"{components[4]} {components[5]}"
            return c1c, c2c, c2p
        return "", "", ""

    @staticmethod
    def _get_glonass_slot_freq_num(
        header_dict: dict[str, Any],
    ) -> dict[str, int]:
        """Parse ``GLONASS SLOT / FRQ #`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        dict[str, int]
            Mapping of slot to frequency number.

        """
        header_value = header_dict.get("GLONASS SLOT / FRQ #", "")
        components = header_value.split()

        result = {}
        for i in range(1, len(components), 2):  # Skip first component
            if i + 1 < len(components):
                try:
                    slot = components[i]
                    freq_num = int(components[i + 1])
                    result[slot] = freq_num
                except ValueError, IndexError:
                    continue

        return result

    @staticmethod
    def _get_sys_phase_shift(
        header_dict: dict[str, Any],
    ) -> dict[str, dict[str, float | None]]:
        """Parse ``SYS / PHASE SHIFT`` records.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        dict[str, dict[str, float | None]]
            Mapping of system to signal phase shifts.

        """
        header_value = header_dict.get("SYS / PHASE SHIFT", "")
        components = header_value.split()

        sys_phase_shift_dict = defaultdict(dict)
        i = 0

        while i < len(components):
            if i >= len(components):
                break

            system_abbrv = components[i]

            if i + 1 >= len(components):
                break
            signal_code = components[i + 1]

            # Check if there's a phase shift value
            phase_shift = None
            if (
                i + 2 < len(components)
                and components[i + 2].replace(".", "", 1).replace("-", "", 1).isdigit()
            ):
                try:
                    phase_shift = float(components[i + 2])
                    i += 3
                except ValueError, TypeError:
                    i += 2
            else:
                i += 2

            sys_phase_shift_dict[system_abbrv][signal_code] = phase_shift

        return {k: dict(v) for k, v in sys_phase_shift_dict.items()}

    @staticmethod
    def _get_signal_strength_unit(
        header_dict: dict[str, Any],
    ) -> pint.Unit | str:
        """Parse ``SIGNAL STRENGTH UNIT`` record.

        Parameters
        ----------
        header_dict : dict[str, Any]
            Raw header dictionary.

        Returns
        -------
        pint.Unit or str
            Parsed unit or a default string.

        """
        header_value = header_dict.get("SIGNAL STRENGTH UNIT", "").strip()

        # Using match statement like original
        match header_value:
            case "DBHZ":
                return UREG.dBHz
            case "DB":
                return UREG.dB
            case _:
                return header_value if header_value else "dB"

    @property
    def is_mixed_systems(self) -> bool:
        """Check if the RINEX file contains mixed GNSS systems."""
        return self.systems == "M"

    def __repr__(self) -> str:
        """Return a concise representation for debugging."""
        return (
            f"Rnxv3Header(file='{self.fpath.name}', "
            f"version={self.version}, "
            f"systems='{self.systems}')"
        )

    def __str__(self) -> str:
        """Return a human-readable header summary."""
        systems_str = "Mixed" if self.systems == "M" else self.systems
        return (
            f"RINEX v{self.version} Header\n"
            f"  File: {self.fpath.name}\n"
            f"  Marker: {self.marker_name}\n"
            f"  Systems: {systems_str}\n"
            f"  Receiver: {self.receiver_type}\n"
            f"  Date: {self.date.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        )


class Rnxv3Obs(GNSSDataReader):
    """RINEX v3.04 observation reader.

    Attributes
    ----------
    fpath : Path
        Path to the RINEX observation file.
    polarization : str, default "RHCP"
        Polarization label for observables.
    completeness_mode : {"strict", "warn", "off"}, default "strict"
        Behavior when epoch completeness checks fail.
    expected_dump_interval : str or pint.Quantity, optional
        Expected file dump interval for completeness validation.
    expected_sampling_interval : str or pint.Quantity, optional
        Expected sampling interval for completeness validation.
    apply_overlap_filter : bool, default False
        Whether to filter overlapping signal groups.
    overlap_preferences : dict[str, str], optional
        Preferred signals for overlap resolution.
    aggregate_glonass_fdma : bool, optional
        Whether to aggregate GLONASS FDMA channels.

    Notes
    -----
    Inherits ``fpath``, its validator, and ``arbitrary_types_allowed``
    from :class:`GNSSDataReader`.

    """

    model_config = ConfigDict(frozen=True)

    polarization: str = "RHCP"

    completeness_mode: Literal["strict", "warn", "off"] = "strict"
    expected_dump_interval: str | pint.Quantity | None = None
    expected_sampling_interval: str | pint.Quantity | None = None

    apply_overlap_filter: bool = False
    overlap_preferences: dict[str, str] | None = None

    aggregate_glonass_fdma: bool = True

    _header: Rnxv3Header = PrivateAttr()
    _signal_mapper: SignalIDMapper = PrivateAttr()

    _lines: list[str] = PrivateAttr()
    _file_hash: str = PrivateAttr()
    _cached_epoch_batches: list[tuple[int, int]] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _post_init(self) -> Self:
        """Initialize derived state after validation."""
        # Load header once
        self._header = Rnxv3Header.from_file(self.fpath)

        # Initialize signal mapper
        self._signal_mapper = SignalIDMapper(
            aggregate_glonass_fdma=self.aggregate_glonass_fdma
        )

        # Optionally auto-check completeness
        if self.completeness_mode != "off":
            try:
                self.validate_epoch_completeness(
                    dump_interval=self.expected_dump_interval,
                    sampling_interval=self.expected_sampling_interval,
                )
            except MissingEpochError as e:
                if self.completeness_mode == "strict":
                    raise
                warnings.warn(str(e), RuntimeWarning, stacklevel=2)

        # Cache file lines
        self._lines = self._load_file()

        return self

    @property
    def header(self) -> Rnxv3Header:
        """Expose validated header (read-only).

        Returns
        -------
        Rnxv3Header
            Parsed and validated RINEX header.

        """
        return self._header

    def __str__(self) -> str:
        """Return a human-readable summary."""
        return (
            f"{self.__class__.__name__}:\n"
            f"  File Path: {self.fpath}\n"
            f"  Header: {self.header}\n"
            f"  Polarization: {self.polarization}\n"
        )

    def __repr__(self) -> str:
        """Return a concise representation for debugging."""
        return f"{self.__class__.__name__}(fpath={self.fpath})"

    def _load_file(self) -> list[str]:
        """Read file once, cache lines, and compute hash.

        Returns
        -------
        list[str]
            File contents split into lines.

        """
        if not hasattr(self, "_lines"):
            h = hashlib.sha256()
            with self.fpath.open("rb") as f:  # binary mode for consistent hash
                data = f.read()
                h.update(data)
                self._lines = data.decode("utf-8", errors="replace").splitlines()
            self._file_hash = h.hexdigest()[:16]  # short hash for storage
        return self._lines

    @property
    def file_hash(self) -> str:
        """Return cached SHA256 short hash of the file content.

        Returns
        -------
        str
            16-character short hash for deduplication.

        """
        return self._file_hash

    @property
    def start_time(self) -> datetime:
        """Return start time of observations from header.

        Returns
        -------
        datetime
            First observation timestamp.

        """
        return min(self.header.t0.values())

    @property
    def end_time(self) -> datetime:
        """Return end time of observations from last epoch.

        Returns
        -------
        datetime
            Last observation timestamp.

        """
        last_epoch = None
        for epoch in self.iter_epochs():
            last_epoch = epoch
        if last_epoch:
            return self.get_datetime_from_epoch_record_info(last_epoch.info)
        return self.start_time

    @property
    def systems(self) -> list[str]:
        """Return list of GNSS systems in file.

        Returns
        -------
        list of str
            System identifiers (G, R, E, C, J, S, I).

        """
        if self.header.systems == "M":
            return list(self.header.obs_codes_per_system.keys())
        return [self.header.systems]

    @property
    def num_epochs(self) -> int:
        """Return number of epochs in file.

        Returns
        -------
        int
            Total epoch count.

        """
        return len(list(self.get_epoch_record_batches()))

    @property
    def num_satellites(self) -> int:
        """Return total number of unique satellites observed.

        Returns
        -------
        int
            Count of unique satellite vehicles across all systems.

        """
        satellites = set()
        for epoch in self.iter_epochs():
            for sat in epoch.data:
                satellites.add(sat.sv)
        return len(satellites)

    def get_epoch_record_batches(
        self, epoch_record_indicator: str = EPOCH_RECORD_INDICATOR
    ) -> list[tuple[int, int]]:
        """Get the start and end line numbers for each epoch in the file.

        Parameters
        ----------
        epoch_record_indicator : str, default '>'
            Character marking epoch record lines.

        Returns
        -------
        list of tuple of int
            List of (start_line, end_line) pairs for each epoch.

        """
        if self._cached_epoch_batches is not None:
            return self._cached_epoch_batches

        lines = self._load_file()
        starts = [
            i for i, line in enumerate(lines) if line.startswith(epoch_record_indicator)
        ]
        starts.append(len(lines))  # Add EOF
        self._cached_epoch_batches = [
            (start, starts[i + 1])
            for i, start in enumerate(starts)
            if i + 1 < len(starts)
        ]
        return self._cached_epoch_batches

    def parse_observation_slice(
        self,
        slice_text: str,
    ) -> tuple[float | None, int | None, int | None]:
        """Parse a RINEX observation slice into value, LLI, and SSI.

        Enhanced to handle both standard 16-character format and
        variable-length records.

        Parameters
        ----------
        slice_text : str
            Observation slice to parse.

        Returns
        -------
        tuple[float | None, int | None, int | None]
            Parsed (value, LLI, SSI) tuple.

        """
        if not slice_text or not slice_text.strip():
            return None, None, None

        try:
            # Method 1: Standard RINEX format with decimal at position -6
            if (
                len(slice_text) >= OBS_SLICE_MIN_LEN
                and len(slice_text) <= OBS_SLICE_MAX_LEN
                and slice_text[OBS_SLICE_DECIMAL_POS] == "."
            ):
                slice_chars = list(slice_text)
                ssi = slice_chars.pop(-1) if len(slice_chars) > 0 else ""
                lli = slice_chars.pop(-1) if len(slice_chars) > 0 else ""

                # Convert LLI and SSI
                lli = int(lli) if lli.strip() and lli.isdigit() else None
                ssi = int(ssi) if ssi.strip() and ssi.isdigit() else None

                # Convert value
                value_str = "".join(slice_chars).strip()
                if value_str:
                    value = float(value_str)
                    return value, lli, ssi

        except ValueError, IndexError:
            pass

        try:
            # Method 2: Flexible parsing for variable-length records
            slice_trimmed = slice_text.strip()
            if not slice_trimmed:
                return None, None, None

            # Look for a decimal point to identify the numeric value
            if "." in slice_trimmed:
                # Find the main numeric value (supports negative numbers)
                number_match = re.search(r"(-?\d+\.\d+)", slice_trimmed)

                if number_match:
                    value = float(number_match.group(1))

                    # Check for LLI/SSI indicators after the number
                    remaining_part = slice_trimmed[number_match.end() :].strip()
                    lli = None
                    ssi = None

                    # Parse remaining characters as potential LLI/SSI
                    if remaining_part:
                        # Could be just SSI, or LLI followed by SSI
                        if len(remaining_part) == 1:
                            # Just one indicator - assume it's SSI
                            if remaining_part.isdigit():
                                ssi = int(remaining_part)
                        elif len(remaining_part) >= LLI_SSI_PAIR_LEN:
                            # Two or more characters - take last two as LLI, SSI
                            lli_char = remaining_part[-2]
                            ssi_char = remaining_part[-1]

                            if lli_char.isdigit():
                                lli = int(lli_char)
                            if ssi_char.isdigit():
                                ssi = int(ssi_char)

                    return value, lli, ssi

        except ValueError, IndexError:
            pass

        # Method 3: Last resort - try simple float parsing
        try:
            simple_value = float(slice_text.strip())
            return simple_value, None, None
        except ValueError:
            pass

        return None, None, None

    def process_satellite_data(self, s: str) -> Satellite:
        """Process satellite data line into a Satellite object with observations.

        Handles variable-length observation records correctly by adaptively parsing
        based on the actual line length and content.
        """
        sv = s[:3].strip()
        satellite = Satellite(sv=sv)
        bands_tbe = [f"{sv}|{b}" for b in self.header.obs_codes_per_system[sv[0]]]

        # Get the data part (after sv identifier)
        data_part = s[3:]

        # Process each observation adaptively
        for i, band in enumerate(bands_tbe):
            start_idx = i * 16
            end_idx = start_idx + 16

            # Check if we have enough data for this observation
            if start_idx >= len(data_part):
                # No more data available - create empty observation
                observation = Observation(
                    obs_type=band.split("|")[1][0],
                    value=None,
                    lli=None,
                    ssi=None,
                )
                satellite.add_observation(observation)
                continue

            # Extract the slice, but handle variable length
            if end_idx <= len(data_part):
                # Full 16-character slice available
                slice_data = data_part[start_idx:end_idx]
            else:
                # Partial slice - pad with spaces to maintain consistency
                available_slice = data_part[start_idx:]
                slice_data = available_slice.ljust(16)  # Pad with spaces if needed

            value, lli, ssi = self.parse_observation_slice(slice_data)

            observation = Observation(
                obs_type=band.split("|")[1][0],
                value=value,
                lli=lli,
                ssi=ssi,
            )
            satellite.add_observation(observation)

        return satellite

    @property
    def epochs(self) -> list[Rnxv3ObsEpochRecord]:
        """Materialize all epochs (legacy compatibility).

        Returns
        -------
        list of Rnxv3ObsEpochRecord
            All epochs in memory (use iter_epochs for efficiency)

        """
        return list(self.iter_epochs())

    def iter_epochs(self) -> Iterator[Rnxv3ObsEpochRecord]:
        """Yield epochs one by one instead of materializing the whole list.

        Returns
        -------
        Generator
            Generator yielding Rnxv3ObsEpochRecord objects

        Yields
        ------
        Rnxv3ObsEpochRecord
            Each epoch with timestamp and satellite observations

        """
        for start, end in self.get_epoch_record_batches():
            try:
                info = Rnxv3ObsEpochRecordLineModel.model_validate(
                    {"epoch": self._lines[start]}
                )

                # Skip event epochs (flag 2-6: special records, not observations)
                if info.epoch_flag > 1:
                    continue

                # Filter out blank/whitespace-only lines from data slice
                data = [line for line in self._lines[start + 1 : end] if line.strip()]
                epoch = Rnxv3ObsEpochRecord(
                    info=info,
                    data=[self.process_satellite_data(line) for line in data],
                )
                yield epoch
            except InvalidEpochError, IncompleteEpochError, ValueError:
                # Skip epochs with validation errors (invalid SV, malformed data,
                # pydantic ValidationError inherits from ValueError)
                pass

    def iter_epochs_in_range(
        self,
        start: datetime,
        end: datetime,
    ) -> Iterable[Rnxv3ObsEpochRecord]:
        """Yield epochs lazily that fall into the given datetime range.

        Parameters
        ----------
        start : datetime
            Start of time range (inclusive)
        end : datetime
            End of time range (inclusive)

        Returns
        -------
        Generator
            Generator yielding epochs in the specified range

        Yields
        ------
        Rnxv3ObsEpochRecord
            Epochs within the time range

        """
        for epoch in self.iter_epochs():
            dt = self.get_datetime_from_epoch_record_info(epoch.info)
            if start <= dt <= end:
                yield epoch

    def get_datetime_from_epoch_record_info(
        self,
        epoch_record_info: Rnxv3ObsEpochRecordLineModel,
    ) -> datetime:
        """Convert epoch record info to datetime object.

        Parameters
        ----------
        epoch_record_info : Rnxv3ObsEpochRecordLineModel
            Parsed epoch record line

        Returns
        -------
        datetime
            Timestamp from epoch record

        """
        return datetime(
            year=int(epoch_record_info.year),
            month=int(epoch_record_info.month),
            day=int(epoch_record_info.day),
            hour=int(epoch_record_info.hour),
            minute=int(epoch_record_info.minute),
            second=int(epoch_record_info.seconds),
            tzinfo=UTC,
        )

    @staticmethod
    def epochrecordinfo_dt_to_numpy_dt(
        epch: Rnxv3ObsEpochRecord,
    ) -> np.datetime64:
        """Convert Python datetime to numpy datetime64[ns].

        Parameters
        ----------
        epch : Rnxv3ObsEpochRecord
            Epoch record containing timestamp info

        Returns
        -------
        np.datetime64
            Numpy datetime64 with nanosecond precision

        """
        dt = datetime(
            year=int(epch.info.year),
            month=int(epch.info.month),
            day=int(epch.info.day),
            hour=int(epch.info.hour),
            minute=int(epch.info.minute),
            second=int(epch.info.seconds),
            tzinfo=UTC,
        )
        # np.datetime64 doesn't support timezone info, but datetime is already UTC
        # Convert to naive datetime (UTC) to avoid warning
        return np.datetime64(dt.replace(tzinfo=None), "ns")

    def _epoch_datetimes(self) -> list[datetime]:
        """Extract epoch datetimes from the file.

        Uses the same epoch parsing logic already implemented.
        """
        dts: list[datetime] = []

        for start, _end in self.get_epoch_record_batches():
            info = Rnxv3ObsEpochRecordLineModel.model_validate(
                {"epoch": self._lines[start]}
            )
            dts.append(
                datetime(
                    year=int(info.year),
                    month=int(info.month),
                    day=int(info.day),
                    hour=int(info.hour),
                    minute=int(info.minute),
                    second=int(info.seconds),
                    tzinfo=UTC,
                )
            )
        return dts

    def infer_sampling_interval(self) -> pint.Quantity | None:
        """Infer sampling interval from consecutive epoch deltas.

        Returns
        -------
        pint.Quantity or None
            Sampling interval in seconds, or None if cannot be inferred

        """
        dts = self._epoch_datetimes()
        if len(dts) < MIN_EPOCHS_FOR_INTERVAL:
            return None
        # Compute deltas
        deltas: list[timedelta] = [b - a for a, b in pairwise(dts) if b >= a]
        if not deltas:
            return None
        # Pick the most common delta (robust to an occasional missing epoch)
        seconds = Counter(
            int(dt.total_seconds()) for dt in deltas if dt.total_seconds() > 0
        )
        if not seconds:
            return None
        mode_seconds, _ = seconds.most_common(1)[0]
        return (mode_seconds * UREG.second).to(UREG.seconds)

    def infer_dump_interval(
        self, sampling_interval: pint.Quantity | None = None
    ) -> pint.Quantity | None:
        """Infer the intended dump interval for the RINEX file.

        Parameters
        ----------
        sampling_interval : pint.Quantity, optional
            Known sampling interval. If provided, returns (#epochs * sampling_interval)

        Returns
        -------
        pint.Quantity or None
            Dump interval in seconds, or None if cannot be inferred

        """
        idx = self.get_epoch_record_batches()
        n_epochs = len(idx)
        if n_epochs == 0:
            return None

        if sampling_interval is not None:
            return (n_epochs * sampling_interval).to(UREG.seconds)

        # Fallback: time coverage inclusive (last - first) + typical step
        dts = self._epoch_datetimes()
        if len(dts) == 0:
            return None
        if len(dts) == 1:
            # single epoch: treat as 1 * unknown step (cannot infer)
            return None

        # Estimate step from data
        est_step = self.infer_sampling_interval()
        if est_step is None:
            return None

        # Inclusive coverage often equals (n_epochs - 1) * step; intended
        # dump interval is n_epochs * step.
        return (n_epochs * est_step.to(UREG.seconds)).to(UREG.seconds)

    def validate_epoch_completeness(
        self,
        dump_interval: str | pint.Quantity | None = None,
        sampling_interval: str | pint.Quantity | None = None,
    ) -> None:
        """Validate that the number of epochs matches the expected dump interval.

        Parameters
        ----------
        dump_interval : str or pint.Quantity, optional
            Expected file dump interval. If None, inferred from epochs.
        sampling_interval : str or pint.Quantity, optional
            Expected sampling interval. If None, inferred from epochs.

        Returns
        -------
        None

        Raises
        ------
        MissingEpochError
            If total sampling time doesn't match dump interval
        ValueError
            If intervals cannot be inferred

        """
        # Normalize/Infer sampling interval
        if sampling_interval is None:
            inferred = self.infer_sampling_interval()
            if inferred is None:
                msg = "Could not infer sampling interval from epochs"
                raise ValueError(msg)
            sampling_interval = inferred
        # normalize to pint
        elif not isinstance(sampling_interval, pint.Quantity):
            sampling_interval = UREG.Quantity(sampling_interval).to(UREG.seconds)  # ty: ignore[invalid-assignment]

        # Normalize/Infer dump interval
        if dump_interval is None:
            inferred_dump = self.infer_dump_interval(
                sampling_interval=sampling_interval  # ty: ignore[invalid-argument-type]
            )
            if inferred_dump is None:
                msg = "Could not infer dump interval from file"
                raise ValueError(msg)
            dump_interval = inferred_dump
        elif not isinstance(dump_interval, pint.Quantity):
            # Accept '15 min', '1h', etc.
            dump_interval = UREG.Quantity(dump_interval).to(UREG.seconds)  # ty: ignore[invalid-assignment]

        # Build inputs for the validator model
        epoch_indices = self.get_epoch_record_batches()

        # This throws MissingEpochError automatically if inconsistent
        cast(Any, Rnxv3ObsEpochRecordCompletenessModel)(
            epoch_records_indeces=epoch_indices,
            rnx_file_dump_interval=dump_interval,
            sampling_interval=sampling_interval,
        )

    def filter_by_overlapping_groups(
        self,
        ds: xr.Dataset,
        group_preference: dict[str, str] | None = None,
    ) -> xr.Dataset:
        """Filter overlapping bands using per-group preferences.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with `sid` dimension and signal properties.
        group_preference : dict[str, str], optional
            Mapping of overlap group to preferred band.

        Returns
        -------
        xr.Dataset
            Dataset filtered to preferred overlapping bands.

        """
        if group_preference is None:
            group_preference = {
                "L1_E1_B1I": "L1",
                "L5_E5a": "L5",
                "L2_E5b_B2b": "L2",
            }

        keep = []
        for sid in ds.sid.values:
            parts = str(sid).split("|")
            band = parts[1] if len(parts) >= 2 else ""
            group = self._signal_mapper.get_overlapping_group(band)
            if group and group in group_preference:
                if band == group_preference[group]:
                    keep.append(sid)
            else:
                keep.append(sid)
        return ds.sel(sid=keep)

    def _precompute_sids_from_header(
        self,
    ) -> tuple[list[str], dict[str, dict[str, object]]]:
        """Build sorted SID list and properties from header info alone.

        Uses the header's obs_codes_per_system and static constellation
        SV lists to pre-compute the full theoretical SID set, eliminating
        the discovery pass.

        Returns
        -------
        sorted_sids : list[str]
            Sorted list of signal IDs.
        sid_properties : dict[str, dict[str, object]]
            Mapping of SID to its properties (sv, system, band, code,
            freq_center, freq_min, freq_max, bandwidth, overlapping_group).

        """
        mapper = self._signal_mapper
        signal_ids: set[str] = set()
        sid_properties: dict[str, dict[str, object]] = {}

        # Pre-compute pint arithmetic once per unique band
        band_freq_cache: dict[str, tuple[float, float, float, float]] = {}

        for system, obs_codes in self.header.obs_codes_per_system.items():
            svs = _get_constellation_svs(system)

            for obs_code in obs_codes:
                if len(obs_code) < 3:
                    continue
                band_num = obs_code[1]
                code_char = obs_code[2]

                band_name = mapper.SYSTEM_BANDS.get(system, {}).get(
                    band_num, f"UnknownBand{band_num}"
                )

                # Cache frequency arithmetic per band
                if band_name not in band_freq_cache:
                    center_frequency = mapper.get_band_frequency(band_name)
                    bandwidth = mapper.get_band_bandwidth(band_name)

                    if center_frequency is not None and bandwidth is not None:
                        bw = bandwidth[0] if isinstance(bandwidth, list) else bandwidth
                        freq_min = center_frequency - (bw / 2.0)
                        freq_max = center_frequency + (bw / 2.0)
                        band_freq_cache[band_name] = (
                            float(center_frequency),
                            float(freq_min),
                            float(freq_max),
                            float(bw),
                        )
                    else:
                        band_freq_cache[band_name] = (
                            np.nan,
                            np.nan,
                            np.nan,
                            np.nan,
                        )

                freq_center, freq_min, freq_max, bw = band_freq_cache[band_name]
                overlapping_group = mapper.get_overlapping_group(band_name)

                sid_suffix = "|" + band_name + "|" + code_char

                for sv in svs:
                    sid = sv + sid_suffix
                    if sid not in signal_ids:
                        signal_ids.add(sid)
                        sid_properties[sid] = {
                            "sv": sv,
                            "system": system,
                            "band": band_name,
                            "code": code_char,
                            "freq_center": freq_center,
                            "freq_min": freq_min,
                            "freq_max": freq_max,
                            "bandwidth": bw,
                            "overlapping_group": overlapping_group,
                        }

        sorted_sids = sorted(signal_ids)
        return sorted_sids, {s: sid_properties[s] for s in sorted_sids}

    def _create_dataset_single_pass(
        self, keep_data_vars: frozenset[str] | None = None
    ) -> xr.Dataset:
        """Create xarray Dataset in a single pass over the file.

        Pre-allocates arrays using header-derived SID set and epoch count,
        then fills them by parsing observations inline without Pydantic
        models or function-call overhead.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid) and standard variables.

        """
        lines = self._load_file()
        epoch_batches = self.get_epoch_record_batches()
        n_epochs = len(epoch_batches)

        sorted_sids, sid_properties = self._precompute_sids_from_header()
        n_sids = len(sorted_sids)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}

        # Pre-allocate only the arrays that will be kept
        _all = keep_data_vars is None
        need_snr = _all or "SNR" in keep_data_vars
        need_pseudo = _all or "Pseudorange" in keep_data_vars
        need_phase = _all or "Phase" in keep_data_vars
        need_doppler = _all or "Doppler" in keep_data_vars
        need_lli = _all or "LLI" in keep_data_vars
        need_ssi = _all or "SSI" in keep_data_vars

        timestamps = np.empty(n_epochs, dtype="datetime64[ns]")
        if need_snr:
            snr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["SNR"])
        if need_pseudo:
            pseudo = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Pseudorange"])
        if need_phase:
            phase = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Phase"])
        if need_doppler:
            doppler = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["Doppler"])
        if need_lli:
            lli = np.full((n_epochs, n_sids), -1, dtype=DTYPES["LLI"])
        if need_ssi:
            ssi = np.full((n_epochs, n_sids), -1, dtype=DTYPES["SSI"])

        # Build obs_code → (obs_type, sid_suffix) lookup per system
        mapper = self._signal_mapper
        system_obs_lut: dict[str, list[tuple[str, str]]] = {}
        for system, obs_codes in self.header.obs_codes_per_system.items():
            lut: list[tuple[str, str]] = []
            for obs_code in obs_codes:
                if len(obs_code) < 3:
                    lut.append(("", ""))
                    continue
                band_num = obs_code[1]
                code_char = obs_code[2]
                band_name = mapper.SYSTEM_BANDS.get(system, {}).get(
                    band_num, f"UnknownBand{band_num}"
                )
                obs_type = obs_code[0]
                lut.append((obs_type, "|" + band_name + "|" + code_char))
            system_obs_lut[system] = lut

        # Single pass over all epochs — skip unparseable epoch lines
        valid_mask = np.ones(n_epochs, dtype=bool)
        for t_idx, (start, end) in enumerate(epoch_batches):
            epoch_line = lines[start]

            # Inline epoch parsing (no Pydantic model)
            m = _EPOCH_RE.match(epoch_line)
            if m is None:
                valid_mask[t_idx] = False
                continue

            year, month, day = int(m[1]), int(m[2]), int(m[3])
            hour, minute = int(m[4]), int(m[5])
            seconds = float(m[6])
            sec_int = int(seconds)
            usec = int((seconds - sec_int) * 1_000_000)
            ts = np.datetime64(
                f"{year:04d}-{month:02d}-{day:02d}"
                f"T{hour:02d}:{minute:02d}:{sec_int:02d}",
                "ns",
            )
            ts += np.timedelta64(usec, "us")
            timestamps[t_idx] = ts

            # Parse satellite data lines inline
            for line_idx in range(start + 1, end):
                sat_line = lines[line_idx]
                if len(sat_line) < 3:
                    continue
                sv = sat_line[:3].strip()
                if not sv:
                    continue
                system = sv[0]
                lut_list = system_obs_lut.get(system)
                if lut_list is None:
                    continue

                data_part = sat_line[3:]
                data_part_len = len(data_part)

                for i, (obs_type, sid_suffix) in enumerate(lut_list):
                    if not obs_type:
                        continue

                    col_start = i * 16
                    if col_start >= data_part_len:
                        break

                    sid_key = sv + sid_suffix
                    s_idx = sid_to_idx.get(sid_key)
                    if s_idx is None:
                        continue

                    col_end = col_start + 16
                    slice_text = data_part[col_start:col_end]

                    value, obs_lli, obs_ssi = _parse_obs_fast(slice_text)
                    if value is None:
                        continue

                    match obs_type:
                        case "S":
                            if need_snr and value != 0:
                                snr[t_idx, s_idx] = value
                        case "C":
                            if need_pseudo:
                                pseudo[t_idx, s_idx] = value
                        case "L":
                            if need_phase:
                                phase[t_idx, s_idx] = value
                        case "D":
                            if need_doppler:
                                doppler[t_idx, s_idx] = value

                    if need_lli and obs_lli is not None:
                        lli[t_idx, s_idx] = obs_lli
                    if need_ssi and obs_ssi is not None:
                        ssi[t_idx, s_idx] = obs_ssi

        # Drop epochs that failed to parse
        if not valid_mask.all():
            timestamps = timestamps[valid_mask]
            if need_snr:
                snr = snr[valid_mask]
            if need_pseudo:
                pseudo = pseudo[valid_mask]
            if need_phase:
                phase = phase[valid_mask]
            if need_doppler:
                doppler = doppler[valid_mask]
            if need_lli:
                lli = lli[valid_mask]
            if need_ssi:
                ssi = ssi[valid_mask]

        # Build coordinate arrays from pre-computed properties
        sv_list = np.array(
            [sid_properties[sid]["sv"] for sid in sorted_sids], dtype=object
        )
        constellation_list = np.array(
            [sid_properties[sid]["system"] for sid in sorted_sids], dtype=object
        )
        band_list = np.array(
            [sid_properties[sid]["band"] for sid in sorted_sids], dtype=object
        )
        code_list = np.array(
            [sid_properties[sid]["code"] for sid in sorted_sids], dtype=object
        )
        freq_center_list = [sid_properties[sid]["freq_center"] for sid in sorted_sids]
        freq_min_list = [sid_properties[sid]["freq_min"] for sid in sorted_sids]
        freq_max_list = [sid_properties[sid]["freq_max"] for sid in sorted_sids]

        signal_id_coord = xr.DataArray(
            np.array(sorted_sids, dtype=object),
            dims=["sid"],
            attrs=COORDS_METADATA["sid"],
        )
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

        if self.header.signal_strength_unit == UREG.dBHz:
            snr_meta = CN0_METADATA
        else:
            snr_meta = SNR_METADATA

        _data_vars: dict = {}
        if need_snr:
            _data_vars["SNR"] = (["epoch", "sid"], snr, snr_meta)
        if need_pseudo:
            _data_vars["Pseudorange"] = (
                ["epoch", "sid"],
                pseudo,
                OBSERVABLES_METADATA["Pseudorange"],
            )
        if need_phase:
            _data_vars["Phase"] = (
                ["epoch", "sid"],
                phase,
                OBSERVABLES_METADATA["Phase"],
            )
        if need_doppler:
            _data_vars["Doppler"] = (
                ["epoch", "sid"],
                doppler,
                OBSERVABLES_METADATA["Doppler"],
            )
        if need_lli:
            _data_vars["LLI"] = (["epoch", "sid"], lli, OBSERVABLES_METADATA["LLI"])
        if need_ssi:
            _data_vars["SSI"] = (["epoch", "sid"], ssi, OBSERVABLES_METADATA["SSI"])

        ds = xr.Dataset(
            data_vars=_data_vars,
            coords=coords,
            attrs={**self._build_attrs()},
        )

        if self.apply_overlap_filter:
            ds = self.filter_by_overlapping_groups(ds, self.overlap_preferences)

        return ds

    def create_rinex_netcdf_with_signal_id(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> xr.Dataset:
        """Create a NetCDF dataset with signal IDs.

        Always uses the fast single-pass path.  Optionally restricts to
        epochs within a datetime range via post-filtering.

        Parameters
        ----------
        start : datetime, optional
            Start of time range (inclusive).
        end : datetime, optional
            End of time range (inclusive).

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid).

        """
        ds = self._create_dataset_single_pass()

        if start or end:
            ds = ds.sel(epoch=slice(start, end))

        return ds

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: object,
    ) -> xr.Dataset:
        """Convert RINEX observations to xarray.Dataset with signal ID structure.

        Parameters
        ----------
        outname : Path or str, optional
            If provided, saves dataset to this file path
        keep_data_vars : list of str or None, optional
            Data variables to include in dataset. Defaults to config value.
        write_global_attrs : bool, default False
            If True, adds comprehensive global attributes
        pad_global_sid : bool, default True
            If True, pads to global signal ID space
        strip_fillval : bool, default True
            If True, removes fill values
        add_future_datavars : bool, default True
            If True, adds placeholder variables for future data
        keep_sids : list of str or None, default None
            If provided, filters/pads dataset to these specific SIDs.
            If None and pad_global_sid=True, pads to all possible SIDs.

        Returns
        -------
        xr.Dataset
            Dataset with dimensions (epoch, sid) and requested data variables

        """
        outname = cast(Path | str | None, kwargs.pop("outname", None))
        write_global_attrs = bool(kwargs.pop("write_global_attrs", False))
        pad_global_sid = bool(kwargs.pop("pad_global_sid", True))
        strip_fillval = bool(kwargs.pop("strip_fillval", True))
        add_future_datavars = bool(kwargs.pop("add_future_datavars", True))
        keep_sids = cast(list[str] | None, kwargs.pop("keep_sids", None))

        if keep_data_vars is None:
            from canvod.utils.config import load_config

            keep_data_vars = load_config().processing.params.keep_gnss_observables

        ds = self._create_dataset_single_pass(frozenset(keep_data_vars))

        if pad_global_sid:
            from canvod.auxiliary.preprocessing import pad_to_global_sid

            # Pad/filter to specified sids or all possible sids
            ds = pad_to_global_sid(ds, keep_sids=keep_sids)

        if strip_fillval:
            from canvod.auxiliary.preprocessing import strip_fillvalue

            ds = strip_fillvalue(ds)

        if add_future_datavars:
            pass

        if write_global_attrs:
            ds.attrs.update(self._create_comprehensive_attrs())

        ds.attrs.update(self._build_attrs())

        if outname:
            from canvod.utils.config import load_config as _load_config

            comp = _load_config().processing.netcdf_compression
            encoding = {
                var: {"zlib": comp.zlib, "complevel": comp.complevel}
                for var in ds.data_vars
            }
            ds.to_netcdf(str(outname), encoding=encoding)

        # Normalise string dtypes for Icechunk / Zarr V3 compatibility
        ds = _str_to_object(ds)

        # Validate output structure for pipeline compatibility
        validate_dataset(ds, required_vars=keep_data_vars)

        return ds

    def validate_rinex_304_compliance(
        self,
        ds: xr.Dataset | None = None,
        strict: bool = False,
        print_report: bool = True,
    ) -> dict[str, list[str]]:
        """Run enhanced RINEX 3.04 specification validation.

        Validates:
        1. System-specific observation codes
        2. GLONASS mandatory fields (slot/frequency, biases)
        3. Phase shift records (RINEX 3.01+)
        4. Observation value ranges

        Parameters
        ----------
        ds : xr.Dataset, optional
            Dataset to validate. If None, creates one from current file.
        strict : bool
            If True, raise ValueError on validation failures
        print_report : bool
            If True, print validation report to console

        Returns
        -------
        dict[str, list[str]]
            Validation results by category

        Examples
        --------
        >>> reader = Rnxv3Obs(fpath="station.24o")
        >>> results = reader.validate_rinex_304_compliance()
        >>> # Or validate a specific dataset
        >>> ds = reader.to_ds()
        >>> results = reader.validate_rinex_304_compliance(ds=ds)

        """
        if ds is None:
            ds = self.to_ds(write_global_attrs=False)

        # Prepare header dict for validators
        header_dict: dict[str, Any] = {
            "obs_codes_per_system": self.header.obs_codes_per_system,
        }

        # Add GLONASS-specific headers if available
        if hasattr(self.header, "glonass_slot_frq"):
            header_dict["GLONASS SLOT / FRQ #"] = self.header.glonass_slot_frq

        if hasattr(self.header, "glonass_cod_phs_bis"):
            header_dict["GLONASS COD/PHS/BIS"] = self.header.glonass_cod_phs_bis

        if hasattr(self.header, "phase_shift"):
            header_dict["SYS / PHASE SHIFT"] = self.header.phase_shift

        # Run validation
        results = RINEX304ComplianceValidator.validate_all(
            ds=ds, header_dict=header_dict, strict=strict
        )

        if print_report:
            RINEX304ComplianceValidator.print_validation_report(results)

        return results

    def _create_comprehensive_attrs(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            "File Path": str(self.fpath),
            "File Type": self.header.filetype,
            "RINEX Version": self.header.version,
            "RINEX Type": self.header.rinextype,
            "Observer": self.header.observer,
            "Agency": self.header.agency,
            "Date": self.header.date.isoformat(),
            "Marker Name": self.header.marker_name,
            "Marker Number": self.header.marker_number,
            "Marker Type": self.header.marker_type,
            "Approximate Position": (
                f"(X = {self.header.approx_position[0].magnitude} "
                f"{self.header.approx_position[0].units:~}, "
                f"Y = {self.header.approx_position[1].magnitude} "
                f"{self.header.approx_position[1].units:~}, "
                f"Z = {self.header.approx_position[2].magnitude} "
                f"{self.header.approx_position[2].units:~})"
            ),
            "Receiver Type": self.header.receiver_type,
            "Receiver Version": self.header.receiver_version,
            "Receiver Number": self.header.receiver_number,
            "Antenna Type": self.header.antenna_type,
            "Antenna Number": self.header.antenna_number,
            "Antenna Position": (
                f"(X = {self.header.antenna_position[0].magnitude} "
                f"{self.header.antenna_position[0].units:~}, "
                f"Y = {self.header.antenna_position[1].magnitude} "
                f"{self.header.antenna_position[1].units:~}, "
                f"Z = {self.header.antenna_position[2].magnitude} "
                f"{self.header.antenna_position[2].units:~})"
            ),
            "Program": self.header.pgm,
            "Run By": self.header.run_by,
            "Time of First Observation": json.dumps(
                {k: v.isoformat() for k, v in self.header.t0.items()}
            ),
            "GLONASS COD": self.header.glonass_cod,
            "GLONASS PHS": self.header.glonass_phs,
            "GLONASS BIS": self.header.glonass_bis,
            "GLONASS Slot Frequency Dict": json.dumps(
                self.header.glonass_slot_freq_dict
            ),
            "Leap Seconds": f"{self.header.leap_seconds:~}",
        }
        return attrs


def adapt_existing_rnxv3obs_class(original_class_path: str | None = None) -> str:
    """Provide guidance to integrate the enhanced sid functionality.

    This function provides guidance on how to modify the existing class
    to support the new sid structure alongside the current OFT structure.

    Returns
    -------
    str
        Integration instructions

    """
    _ = original_class_path
    return """
    INTEGRATION GUIDE: Adapting Rnxv3Obs for sid Structure
    ============================================================

    To integrate the new sid functionality into your existing Rnxv3Obs class:

    1. ADD THE SIGNAL_ID_MAPPER CLASS:
       - Copy the SignalIDMapper class to your rinex_reader.py file
       - This handles the mapping logic and band properties

    2. ADD NEW METHODS TO Rnxv3Obs CLASS:

       Method: create_rinex_netcdf_with_signal_id()
       - Copy from EnhancedRnxv3Obs.create_rinex_netcdf_with_signal_id()
       - This creates the new sid-based structure

       Method: filter_by_overlapping_groups()
       - Copy from EnhancedRnxv3Obs.filter_by_overlapping_groups()
       - Handles overlapping signal filtering (Problem A solution)

       Method: to_ds()
       - Copy from EnhancedRnxv3Obs.to_ds()
       - Main interface for creating sid datasets

       Method: create_legacy_compatible_dataset()
       - Copy from EnhancedRnxv3Obs.create_legacy_compatible_dataset()
       - Provides backward compatibility

    3. UPDATE THE __init__ METHOD:
       Add: self.signal_mapper = SignalIDMapper()

    4. MODIFY EXISTING METHODS:
       - Keep existing create_rinex_netcdf_with_oft() for OFT compatibility
       - Add sid option to your main interface methods
       - Update data handlers to support sid dimension

    5. UPDATE DATA_HANDLER/RNX_PARSER.PY:
       - Modify concatenate_datasets() to handle sid dimension
       - Add sid detection alongside OFT detection
       - Update encoding to handle sid string coordinates

    6. UPDATE PROCESSOR/PROCESSOR.PY:
       - Add sid support to create_common_space_datatree()
       - Handle both OFT and sid structures in alignment logic

    BENEFITS OF THIS STRUCTURE:
    ===========================

    ✓ Solves Problem A: Bandwidth overlap handling
      - Overlapping signals kept separate with metadata for filtering
      - band properties include bandwidth information

    ✓ Solves Problem B: code-specific performance differences
      - Each sv|band|code combination gets unique sid
      - No more priority-based LUT - all combinations preserved

    ✓ Maintains compatibility:
      - Legacy conversion available
      - OFT structure still supported
      - Existing code continues to work

    ✓ Enhanced filtering capabilities:
      - Filter by system, band, code independently
      - Complex filtering with multiple criteria
      - Overlap group filtering for analysis

    MIGRATION PATH:
    ===============

    Phase 1: Add sid methods alongside existing OFT methods
    Phase 2: Update data handlers to support both structures
    Phase 3: Gradually migrate analysis code to use sid
    Phase 4: Deprecate old frequency-mapping approach (optional)

    EXAMPLE USAGE AFTER INTEGRATION:
    =================================

    # Create datasets with different structures
    ds_oft = rnx.create_rinex_netcdf_with_oft()           # Current OFT structure
    ds_signal = rnx.create_rinex_netcdf_with_signal_id()  # New sid structure
    ds_legacy = rnx.create_rinex_netcdf(mapped_epochs)    # Legacy structure

    # Advanced sid usage
    ds_enhanced = rnx.to_ds(
        keep_data_vars=["SNR", "Phase"],
        apply_overlap_filter=True,
        overlap_preferences={'L1_E1_B1I': 'L1'}  # Prefer GPS L1 over Galileo E1
    )
    """
