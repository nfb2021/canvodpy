"""Pydantic v2 model for the canVOD file naming convention.

Convention::

    {SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]

    SIT         3-char site ID, uppercase            (e.g. ROS, HAI, FON, LBS)
    T           Receiver type, single uppercase char  (R=reference, A=active/below-canopy)
    NN          Receiver number, zero-padded 01-99
    AGC         3-char data provider ID, uppercase    (e.g. GFZ, TUD, TUW, MPI)
    _R          Literal - 'R' for Receiver
    YYYY        4-digit year
    DOY         3-digit day of year (001-366)
    HHMM        Start time, hours + minutes
    PERIOD      Batch size: 2-digit value + unit      (e.g. 01D, 15M, 01H)
    SAMPLING    Data frequency: 2-digit value + unit  (e.g. 01S, 05S, 05M)
    CONTENT     2-char user field, default 'AA'
    TYPE        File type, lowercase                  (rnx, sbf, ubx, nmea)
    COMPRESSION Optional compression extension        (zip, gz, bz2, zst, ...)

Examples::

    HAIA01GFZ_R_20250010000_01D_01S_AA.rnx.zip
    ROSR01TUW_R_20250010000_01D_05S_AA.rnx
    ROSR35TUW_R_20232221530_15M_05S_AA.sbf
"""

from __future__ import annotations

import re
from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Self

from pydantic import ConfigDict, Field, StringConstraints, field_validator
from pydantic.dataclasses import dataclass

# -- Constrained string types ------------------------------------------------

SiteId = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[A-Z]{3}$"),
]

AgencyId = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[A-Z]{3}$"),
]

Duration = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^\d{2}[SMHD]$"),
]

ContentCode = Annotated[
    str,
    StringConstraints(to_upper=True, strip_whitespace=True, pattern=r"^[A-Z0-9]{2}$"),
]

# -- Enums --------------------------------------------------------------------


class ReceiverType(StrEnum):
    """Char 4: receiver role at the site."""

    REFERENCE = "R"
    ACTIVE = "A"


class FileType(StrEnum):
    """File format / observation type."""

    RNX = "rnx"
    SBF = "sbf"
    UBX = "ubx"
    NMEA = "nmea"


# -- Helpers ------------------------------------------------------------------

_DURATION_UNIT_SECONDS = {"S": 1, "M": 60, "H": 3600, "D": 86400}

_FILENAME_RE = re.compile(
    r"^(?P<site>[A-Z]{3})"
    r"(?P<receiver_type>[RA])"
    r"(?P<receiver_number>\d{2})"
    r"(?P<agency>[A-Z]{3})"
    r"_R"
    r"_(?P<year>\d{4})(?P<doy>\d{3})(?P<hour>\d{2})(?P<minute>\d{2})"
    r"_(?P<period>\d{2}[SMHD])"
    r"_(?P<sampling>\d{2}[SMHD])"
    r"_(?P<content>[A-Z0-9]{2})"
    r"\.(?P<file_type>rnx|sbf|ubx|nmea)"
    r"(?:\.(?P<compression>[a-z0-9]+))?$"
)


def _duration_to_timedelta(code: str) -> timedelta:
    """Convert a duration code like '05S' or '01D' to a timedelta."""
    value = int(code[:2])
    unit = code[2]
    return timedelta(seconds=value * _DURATION_UNIT_SECONDS[unit])


# -- Model --------------------------------------------------------------------


@dataclass(config=ConfigDict(frozen=True, str_strip_whitespace=True))
class CanVODFilename:
    """Structured representation of a canVOD-compliant filename.

    Construct directly with keyword arguments, or parse from a filename string
    with :meth:`from_filename`.  Render back to a string with :attr:`name`.
    """

    site: SiteId
    receiver_type: ReceiverType
    receiver_number: Annotated[int, Field(ge=1, le=99)]
    agency: AgencyId
    year: Annotated[int, Field(ge=2000, le=2099)]
    doy: Annotated[int, Field(ge=1, le=366)]
    hour: Annotated[int, Field(ge=0, le=23)] = 0
    minute: Annotated[int, Field(ge=0, le=59)] = 0
    period: Duration = "01D"
    sampling: Duration = "05S"
    content: ContentCode = "AA"
    file_type: FileType = FileType.RNX
    compression: str | None = None

    # -- Validators -----------------------------------------------------------

    @field_validator("compression")
    @classmethod
    def _validate_compression(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.lower().strip()
            if not v:
                return None
        return v

    # -- Computed properties --------------------------------------------------

    @property
    def sampling_interval(self) -> timedelta:
        """Sampling frequency as a timedelta."""
        return _duration_to_timedelta(self.sampling)

    @property
    def batch_duration(self) -> timedelta:
        """Batch / file period as a timedelta."""
        return _duration_to_timedelta(self.period)

    @property
    def name(self) -> str:
        """Full filename including optional compression extension."""
        stem = (
            f"{self.site}{self.receiver_type.value}"
            f"{self.receiver_number:02d}"
            f"{self.agency}"
            f"_R"
            f"_{self.year:04d}{self.doy:03d}{self.hour:02d}{self.minute:02d}"
            f"_{self.period}"
            f"_{self.sampling}"
            f"_{self.content}"
            f".{self.file_type.value}"
        )
        if self.compression:
            return f"{stem}.{self.compression}"
        return stem

    @property
    def stem(self) -> str:
        """Filename without the compression extension (if any)."""
        parts = self.name.rsplit(".", 1) if self.compression else [self.name]
        return parts[0]

    # -- Constructors ---------------------------------------------------------

    @classmethod
    def from_filename(cls, filename: str) -> Self:
        """Parse a canVOD-compliant filename string into a model instance.

        Accepts a bare filename (no directory components).  Leading path
        segments are stripped automatically.

        Raises
        ------
        ValueError
            If the filename does not match the convention.
        """
        basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

        m = _FILENAME_RE.match(basename)
        if m is None:
            raise ValueError(
                f"Filename does not match the canVOD convention: {basename!r}"
            )

        return cls(
            site=m.group("site"),
            receiver_type=ReceiverType(m.group("receiver_type")),
            receiver_number=int(m.group("receiver_number")),
            agency=m.group("agency"),
            year=int(m.group("year")),
            doy=int(m.group("doy")),
            hour=int(m.group("hour")),
            minute=int(m.group("minute")),
            period=m.group("period"),
            sampling=m.group("sampling"),
            content=m.group("content"),
            file_type=FileType(m.group("file_type")),
            compression=m.group("compression"),
        )

    def __str__(self) -> str:
        return self.name
