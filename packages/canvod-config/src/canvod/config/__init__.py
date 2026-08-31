"""
Configuration management for canvodpy.

This package provides:
- Pydantic models for type-safe configuration
- YAML-based configuration loading
- CLI for configuration management
- Validation and error reporting

Examples
--------
>>> from canvod.config import load_config
>>> config = load_config()
>>> print(config.nasa_earthdata_acc_mail)
>>> print(config.processing.aux_data.agency)
"""

from .loader import load_config
from .models import (
    CanvodConfig,
    MetadataConfig,
    ProcessingConfig,
    SidsConfig,
    SiteConfig,
    SitesConfig,
)

__all__ = [
    "CanvodConfig",
    "MetadataConfig",
    "ProcessingConfig",
    "SidsConfig",
    "SiteConfig",
    "SitesConfig",
    "load_config",
]
