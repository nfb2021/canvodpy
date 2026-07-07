"""canvod-virtualiconvname: Filename convention, mapping engine, and catalog for canVODpy."""

__version__ = "0.1.0"

from .config_models import DirectoryLayout, ReceiverNamingConfig, SiteNamingConfig
from .convention import (
    AgencyId,
    CanVODFilename,
    ContentCode,
    Duration,
    FileType,
    ReceiverType,
    SiteId,
)
from .mapping import FilenameMapper, VirtualFile
from .patterns import BUILTIN_PATTERNS, SourcePattern, match_pattern
from .recipe import NamingRecipe
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
    "NamingRecipe",
    "ReceiverNamingConfig",
    "ReceiverType",
    "SiteId",
    "SiteNamingConfig",
    "SourcePattern",
    "ValidationReport",
    "VirtualFile",
    "match_pattern",
]
