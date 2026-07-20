"""
Pydantic models for canvodpy configuration.

These models provide:
- Type validation for all configuration values
- Serialization support (YAML/JSON/dict)
- API-ready data transfer objects
- IDE autocomplete and type hints

Split across focused submodules by config section (dev/todo_later.md §4) —
this ``__init__.py`` re-exports everything, so ``from canvod.config.models
import X`` keeps working exactly as it did when this was a single file.
"""

from .aux_data import AuxDataConfig
from .base import _StrictModel
from .compression import (
    ChunkStrategy,
    CompressionConfig,
    IcechunkConfig,
    NetcdfCompressionConfig,
)
from .logging import LoggingConfig
from .metadata import CredentialsConfig, MetadataConfig
from .preprocessing import (
    GridAssignmentConfig,
    HistogramBinsConfig,
    PreprocessingConfig,
    StatisticsConfig,
    TemporalAggregationConfig,
)
from .processing import ProcessingConfig
from .processing_params import ProcessingParams
from .references import FundingRef, PublicationRef, ReferencesConfig
from .root import CanvodConfig
from .sids import SidsConfig
from .sites import ReceiverConfig, SiteConfig, SitesConfig, VodAnalysisConfig
from .storage import MaintenanceConfig, StorageConfig

__all__ = [
    "AuxDataConfig",
    "CanvodConfig",
    "ChunkStrategy",
    "CompressionConfig",
    "CredentialsConfig",
    "FundingRef",
    "GridAssignmentConfig",
    "HistogramBinsConfig",
    "IcechunkConfig",
    "LoggingConfig",
    "MaintenanceConfig",
    "MetadataConfig",
    "NetcdfCompressionConfig",
    "PreprocessingConfig",
    "ProcessingConfig",
    "ProcessingParams",
    "PublicationRef",
    "ReceiverConfig",
    "ReferencesConfig",
    "SidsConfig",
    "SiteConfig",
    "SitesConfig",
    "StatisticsConfig",
    "StorageConfig",
    "TemporalAggregationConfig",
    "VodAnalysisConfig",
    "_StrictModel",
]
