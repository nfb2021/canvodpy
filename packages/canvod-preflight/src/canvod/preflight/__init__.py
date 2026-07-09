"""canvod-preflight: Pre-flight validation for GNSS-T data directories."""

__version__ = "0.1.0"

# Config models — describe the site/receiver naming setup
from .config_models import DirectoryLayout, ReceiverNamingConfig, SiteNamingConfig

# Convention types — needed when callers inspect matched files
from .convention import (
    AgencyId,
    CanVODFilename,
    ContentCode,
    Duration,
    FileType,
    ReceiverType,
    SiteId,
)

# Mapping engine — physical filenames -> canonical names
from .mapping import FilenameMapper, VirtualFile

# Pattern registry — glob/regex matching for known filename styles
from .patterns import BUILTIN_PATTERNS, SourcePattern, match_pattern

# Validation API — primary public surface
from .validator import DataDirectoryValidator, ValidationReport

__all__ = [
    "BUILTIN_PATTERNS",
    "AgencyId",
    "CanVODFilename",
    "ContentCode",
    "DataDirectoryValidator",
    "DirectoryLayout",
    "Duration",
    "FileType",
    "FilenameMapper",
    "ReceiverNamingConfig",
    "ReceiverType",
    "SiteId",
    "SiteNamingConfig",
    "SourcePattern",
    "ValidationReport",
    "VirtualFile",
    "match_pattern",
]
