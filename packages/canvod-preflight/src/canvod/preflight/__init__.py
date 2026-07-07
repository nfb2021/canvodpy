"""canvod-preflight: Pre-flight validation for GNSS-T data directories."""

__version__ = "0.1.0"

# Config models — describe the site/receiver naming setup
from .config_models import DirectoryLayout, ReceiverNamingConfig, SiteNamingConfig

# Convention types — needed when callers inspect matched files
from .convention import CanVODFilename, FileType, ReceiverType

# Validation API — primary public surface
from .validator import DataDirectoryValidator, ValidationReport

__all__ = [
    "CanVODFilename",
    "DataDirectoryValidator",
    "DirectoryLayout",
    "FileType",
    "ReceiverNamingConfig",
    "ReceiverType",
    "SiteNamingConfig",
    "ValidationReport",
]
