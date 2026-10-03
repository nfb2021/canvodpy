"""Complete processing configuration — composes the sub-sections below."""

from __future__ import annotations

from pydantic import Field, model_validator

from canvod.utils.tools import deprecated

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
        description=(
            "Deprecated: never applied by `canvodpy run`, the Python API or "
            "Airflow. Removed with the next major version."
        ),
    )
    references: ReferencesConfig = Field(
        default_factory=ReferencesConfig,
        description="Publication and funding references",
    )

    @model_validator(mode="before")
    @classmethod
    def _warn_preprocessing(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("preprocessing") is not None:
            import warnings

            warnings.warn(
                "The setting 'processing.preprocessing' is left over from development and will be removed with the next major version. "
                "No run applies it; remove it from your settings file and pass the operations to canvod.ops.Pipeline explicitly instead.",
                FutureWarning,
                stacklevel=2,
            )
        return data

    @property
    @deprecated(
        "ProcessingConfig.processing is left over from development and will be removed with the next major version. "
        "Use ProcessingConfig.params instead."
    )
    def processing(self) -> ProcessingParams:
        """Deprecated: use .params instead."""
        return self.params

    @property
    @deprecated(
        "ProcessingConfig.compression is left over from development and will be removed with the next major version. "
        "Use ProcessingConfig.netcdf_compression instead."
    )
    def compression(self) -> NetcdfCompressionConfig:
        """Deprecated: use .netcdf_compression instead."""
        return self.netcdf_compression
