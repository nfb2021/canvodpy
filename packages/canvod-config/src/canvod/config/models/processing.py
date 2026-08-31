"""Complete processing configuration — composes the sub-sections below."""

from __future__ import annotations

from pydantic import Field

from .aux_data import AuxDataConfig
from .base import _StrictModel
from .compression import IcechunkConfig, NetcdfCompressionConfig
from .logging import LoggingConfig
from .metadata import CredentialsConfig, MetadataConfig
from .preprocessing import PreprocessingConfig
from .processing_params import ProcessingParams
from .references import ReferencesConfig
from .storage import StorageConfig


class ProcessingConfig(_StrictModel):
    """Complete processing configuration."""

    metadata: MetadataConfig
    credentials: CredentialsConfig = Field(
        default_factory=CredentialsConfig,
        description="Credentials for external data services",
    )
    aux_data: AuxDataConfig = Field(default_factory=AuxDataConfig)
    params: ProcessingParams = Field(default_factory=ProcessingParams)
    netcdf_compression: NetcdfCompressionConfig = Field(
        default_factory=NetcdfCompressionConfig,
        description="Compression settings for NetCDF output from RINEX readers",
    )
    icechunk: IcechunkConfig = Field(default_factory=IcechunkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    preprocessing: PreprocessingConfig = Field(
        default_factory=PreprocessingConfig,
    )
    references: ReferencesConfig = Field(
        default_factory=ReferencesConfig,
        description="Publication and funding references",
    )

    @property
    def processing(self) -> ProcessingParams:
        """Deprecated: use .params instead."""
        import warnings

        warnings.warn(
            "ProcessingConfig.processing is deprecated; use .params",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.params

    @property
    def compression(self) -> NetcdfCompressionConfig:
        """Deprecated: use .netcdf_compression instead."""
        import warnings

        warnings.warn(
            "ProcessingConfig.compression is deprecated; use .netcdf_compression",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.netcdf_compression
