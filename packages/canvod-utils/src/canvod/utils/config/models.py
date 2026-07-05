"""
Pydantic models for canvodpy configuration.

These models provide:
- Type validation for all configuration values
- Serialization support (YAML/JSON/dict)
- API-ready data transfer objects
- IDE autocomplete and type hints
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class _StrictModel(BaseModel):
    """Base for all config models — forbids unknown keys so YAML typos are caught."""

    model_config = ConfigDict(extra="forbid")


# ============================================================================
# Processing Configuration
# ============================================================================


class MetadataConfig(_StrictModel):
    """Metadata to be written to processed files.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    author: str = Field(..., description="Author name")
    email: EmailStr = Field(..., description="Author email")
    orcid: str | None = Field(None, description="ORCID identifier")
    institution: str = Field(..., description="Institution name")
    institution_ror: str | None = Field(None, description="ROR identifier")
    department: str | None = Field(None, description="Department name")
    research_group: str | None = Field(
        None,
        description="Research group name",
    )
    website: str | None = Field(
        None,
        description="Institution/group website",
    )
    license: str | None = Field(None, description="SPDX license identifier")
    publisher: str | None = Field(None, description="Publisher name")
    publisher_url: str | None = Field(None, description="Publisher URL")
    naming_authority: str | None = Field(None, description="Naming authority URI")

    def to_attrs_dict(self) -> dict[str, str]:
        """Convert to a dictionary for xarray attributes.

        Returns
        -------
        dict[str, str]
            Metadata as xarray-compatible attributes.
        """
        attrs = {
            "author": self.author,
            "email": self.email,
            "institution": self.institution,
        }
        if self.department:
            attrs["department"] = self.department
        if self.research_group:
            attrs["research_group"] = self.research_group
        if self.website:
            attrs["website"] = self.website
        return attrs


class CredentialsConfig(_StrictModel):
    """Credentials for external data services.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    nasa_earthdata_acc_mail: EmailStr | None = Field(
        None,
        description="NASA Earthdata email for CDDIS authentication (optional)",
    )


class AuxDataConfig(_StrictModel):
    """Auxiliary data source configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    agency: str = Field("COD", description="Analysis center code")
    product_type: Literal["final", "rapid", "ultra-rapid"] = Field(
        "final",
        description="Product type",
    )

    def get_ftp_servers(
        self,
        cddis_mail: str | None,
    ) -> list[tuple[str, str | None]]:
        """Get FTP servers in priority order.

        If cddis_mail is set: NASA first (with auth), ESA fallback (no auth).
        If cddis_mail is None: ESA only (no auth).

        Parameters
        ----------
        cddis_mail : str | None
            Optional CDDIS email for NASA authentication.

        Returns
        -------
        list[tuple[str, str | None]]
            Server URL and optional auth email pairs in priority order.
        """
        if cddis_mail:
            # NASA first (requires auth), ESA fallback (no auth)
            return [
                ("ftp://gdc.cddis.eosdis.nasa.gov", cddis_mail),
                ("ftp://gssc.esa.int", None),
            ]
        # ESA only (no auth required)
        return [("ftp://gssc.esa.int", None)]


class ProcessingParams(_StrictModel):
    """Processing parameters.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    resource_mode: Literal["auto", "manual"] = Field(
        "auto",
        description=(
            "'auto': Dask/OS auto-detects workers and memory (local machines). "
            "'manual': hard caps via n_max_threads, max_memory_gb, etc. (shared servers)."
        ),
    )
    n_max_threads: int | None = Field(
        None,
        ge=1,
        le=100,
        description=(
            "Max worker processes. Required when resource_mode='manual'. "
            "Ignored in 'auto'."
        ),
    )
    keep_rnx_vars: list[str] = Field(
        default_factory=lambda: ["SNR", "Pseudorange", "Phase", "Doppler"],
        description="RINEX variables to keep",
    )
    store_radial_distance: bool = Field(
        False,
        description="Store radial distance (r) in the output store",
    )
    store_delta_snr: bool = Field(
        False,
        description=(
            "Store delta SNR (SNR_canopy − SNR_reference, dB) in the VOD store. "
            "Useful for diagnosing canopy attenuation without the angular correction."
        ),
    )
    store_radial_diff: bool = Field(
        False,
        description=(
            "Store radial distance difference (r_canopy − r_reference, m) in the "
            "VOD store. Requires store_radial_distance=true at ingest time so that "
            "r is available in both receiver datasets."
        ),
    )
    receiver_position_mode: Literal["shared", "per_receiver"] = Field(
        "shared",
        description=(
            "'shared': all receivers use the canopy receiver position for "
            "spherical coordinate computation (default, enables 1:1 SNR "
            "comparison). 'per_receiver': each receiver uses its own RINEX "
            "header position (physically correct geometry but breaks direct "
            "SNR comparability between receivers)."
        ),
    )
    file_pairing: Literal["complete", "paired"] = Field(
        "complete",
        description=(
            "'complete': discover files per-receiver independently (all data ingested). "
            "'paired': only process dates where both receivers in an analysis pair have data."
        ),
    )
    days_per_batch: int = Field(
        1,
        ge=1,
        le=30,
        description="Number of DOYs pooled per loky wave (1 = one day at a time)",
    )
    batch_hours: float | None = Field(
        None,
        gt=0,
        le=720,
        description="Deprecated: use days_per_batch (int, days) instead",
        exclude=True,
    )

    @model_validator(mode="after")
    def _migrate_batch_hours(self) -> ProcessingParams:
        if self.batch_hours is not None:
            import warnings

            warnings.warn(
                "ProcessingParams.batch_hours is deprecated; use days_per_batch instead",
                DeprecationWarning,
                stacklevel=2,
            )
            self.days_per_batch = max(1, round(self.batch_hours / 24))
            self.batch_hours = None
        return self

    max_memory_gb: float | None = Field(
        None,
        gt=0,
        description="Soft RAM limit for processing (None = no limit)",
    )
    cpu_affinity: list[int] | None = Field(
        None,
        description="Pin workers to specific CPU core IDs (None = no restriction)",
    )
    nice_priority: int = Field(
        0,
        ge=0,
        le=19,
        description="Process nice value (0=normal, 10=low, 19=lowest)",
    )
    # TODO: investigate whether threads_per_worker is still needed after the loky /
    # ProcessPoolExecutor parallelisation refactor replaced Dask. If neither loky nor
    # the custom process-pool uses it, remove this field and its callsites in api.py.
    threads_per_worker: int | None = Field(
        None,
        ge=1,
        le=8,
        description=(
            "Threads per worker process. None lets the scheduler decide. "
            "Values >1 help with numpy/xarray ops and I/O (GIL-releasing) but not "
            "pure-Python RINEX text parsing."
        ),
    )
    ephemeris_source: Literal["final", "broadcast"] = Field(
        "final",
        description=(
            "'final': compute satellite coordinates from agency final products "
            "(SP3/CLK). 'broadcast': use broadcast ephemerides from SBF "
            "SatVisibility blocks (SBF reader_format only, skips SP3/CLK "
            "download). Broadcast is faster but less accurate (~1-2 m orbit)."
        ),
    )
    store_sbf_raw_observables: bool = Field(
        True,
        description=(
            "When reading SBF files, include the pre-correction 'raw' observable "
            "variables in obs_ds: SNR_raw (before CN0HighRes), "
            "Pseudorange_unsmoothed (before Hatch filter), "
            "Pseudorange_raw (before Hatch + multipath filters), and "
            "Phase_raw (before carrier multipath correction). "
            "Set to False to reduce dataset size when raw quantities are not needed."
        ),
    )

    @model_validator(mode="after")
    def validate_resource_mode(self) -> ProcessingParams:
        """Validate resource_mode constraints.

        In 'manual' mode, ``n_max_threads`` must be set.
        In 'auto' mode, ``n_max_threads`` is ignored with a warning if set.
        """
        if self.resource_mode == "manual" and self.n_max_threads is None:
            msg = (
                "n_max_threads is required when resource_mode='manual'. "
                "Set n_max_threads to the number of worker processes you want."
            )
            raise ValueError(msg)
        if self.resource_mode == "auto" and self.n_max_threads is not None:
            import warnings

            warnings.warn(
                f"resource_mode='auto' ignores n_max_threads={self.n_max_threads}. "
                "Set resource_mode='manual' to enforce hard caps, "
                "or remove n_max_threads for auto mode.",
                UserWarning,
                stacklevel=2,
            )
        return self

    def resolve_resources(self) -> dict:
        """Resolve effective resource settings based on resource_mode.

        Returns
        -------
        dict
            Resolved resource values with keys: ``n_workers``,
            ``max_memory_gb``, ``cpu_affinity``, ``nice_priority``.
            In auto mode, ``n_workers`` and ``max_memory_gb`` are ``None``
            (let Dask/OS decide).
        """
        if self.resource_mode == "auto":
            return {
                "n_workers": None,
                "max_memory_gb": None,
                "cpu_affinity": None,
                "nice_priority": 0,
                "threads_per_worker": self.threads_per_worker,
            }
        # manual mode
        return {
            "n_workers": self.n_max_threads,
            "max_memory_gb": self.max_memory_gb,
            "cpu_affinity": self.cpu_affinity,
            "nice_priority": self.nice_priority,
            "threads_per_worker": self.threads_per_worker,
        }


class CompressionConfig(_StrictModel):
    """Compression settings.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    zlib: bool = Field(True, description="Use zlib compression")
    complevel: int = Field(5, ge=0, le=9, description="Compression level")


class ChunkStrategy(_StrictModel):
    """Chunking strategy for a dimension.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    epoch: int = Field(
        34560,
        ge=1,
        description="Chunk size for epoch dimension",
    )
    sid: int = Field(
        -1,
        ge=-1,
        description="Chunk size for sid (-1 = don't chunk)",
    )


class IcechunkConfig(_StrictModel):
    """Icechunk storage configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    compression_level: int = Field(5, ge=0, le=22)
    compression_algorithm: Literal["zstd", "lz4", "gzip"] = "zstd"
    inline_threshold: int = Field(512, ge=0)
    get_concurrency: int = Field(1, ge=1)
    chunk_strategies: dict[str, ChunkStrategy] = Field(
        default_factory=lambda: {
            "rinex_store": ChunkStrategy(epoch=34560, sid=-1),
            "vod_store": ChunkStrategy(epoch=34560, sid=-1),
        },
    )
    manifest_preload_enabled: bool = Field(
        False,
        description="Enable manifest preloading for faster chunk access",
    )
    manifest_preload_max_refs: int = Field(
        100_000_000,
        ge=0,
        description="Maximum total refs to preload",
    )
    manifest_preload_pattern: str = Field(
        "epoch|sid",
        description="Regex pattern for coordinate names to preload",
    )
    manifest_splitting_enabled: bool = Field(
        False,
        description="Enable manifest splitting for stores with >100k chunks per array",
    )
    manifest_splitting_chunk_refs: int = Field(
        1000,
        ge=1,
        description="Split a manifest when it has more than this many chunk refs",
    )
    manifest_splitting_epoch_range: int = Field(
        34560,
        ge=1,
        description="Split obs/snr manifests along epoch dim every N indices (default: 1 day at 2.5 s)",
    )


class StorageConfig(_StrictModel):
    """Storage strategy configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    stores_root_dir: Path = Field(
        ...,
        description="Root directory for all IceChunk stores",
    )
    rinex_store_name: str = Field(
        "rinex",
        description="Name of the RINEX Icechunk store directory",
    )
    vod_store_name: str = Field(
        "vod",
        description="Name of the VOD Icechunk store directory",
    )
    statistics_store_name: str = Field(
        "statistics",
        description="Name of the statistics Zarr store directory",
    )
    aux_data_dir: Path | None = Field(
        None,
        description=(
            "Directory for downloaded auxiliary files (SP3, CLK) and "
            "transient Zarr caches. Raw files persist; caches are rebuilt "
            "each run. Defaults to system temp directory if not set."
        ),
    )
    rinex_store_strategy: Literal["skip", "overwrite", "append"] = "skip"
    rinex_store_expire_days: int = Field(2, ge=1)
    vod_store_strategy: Literal["skip", "overwrite", "append"] = "overwrite"

    @field_validator("stores_root_dir", mode="before")
    @classmethod
    def validate_stores_dir(cls, v: object) -> object:
        """Expand ~ in stores_root_dir at parse time."""
        if isinstance(v, str):
            return Path(v).expanduser()
        return v

    def get_rinex_store_path(self, site_name: str) -> Path:
        """Get the RINEX store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's RINEX store.
        """
        return self.stores_root_dir / site_name / self.rinex_store_name

    def get_vod_store_path(self, site_name: str) -> Path:
        """Get the VOD store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's VOD store.
        """
        return self.stores_root_dir / site_name / self.vod_store_name

    def get_statistics_store_path(self, site_name: str) -> Path:
        """Get the statistics store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's statistics store.
        """
        return self.stores_root_dir / site_name / self.statistics_store_name

    def get_aux_data_dir(self) -> Path:
        """Get the directory for auxiliary data files.

        Returns
        -------
        Path
            Aux data directory (configured or system temp).
        """
        if self.aux_data_dir is not None:
            self.aux_data_dir.mkdir(parents=True, exist_ok=True)
            return self.aux_data_dir
        from tempfile import gettempdir

        return Path(gettempdir())


class LoggingConfig(_StrictModel):
    """Logging configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    log_dir: Path | None = Field(
        None,
        description=(
            "Directory for log files. "
            "Defaults to .logs/ next to config directory if not set."
        ),
    )
    log_file_name: str = Field(
        "canvodpy.log",
        description="Name of the main log file",
    )
    log_path_depth: int = Field(
        6,
        ge=1,
        le=20,
        description="Number of path components to include in log file references",
    )

    def get_log_dir(self) -> Path:
        """Get the effective log directory, creating it if needed.

        Returns
        -------
        Path
            Log directory path.
        """
        if self.log_dir is not None:
            d = self.log_dir
        else:
            # Default: .logs/ next to the config directory (monorepo root)
            from .loader import find_monorepo_root

            d = find_monorepo_root() / ".logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_log_file(self) -> Path:
        """Get the full path to the main log file.

        Returns
        -------
        Path
            Log file path.
        """
        return self.get_log_dir() / self.log_file_name


class TemporalAggregationConfig(_StrictModel):
    """Temporal aggregation preprocessing settings."""

    enabled: bool = Field(True, description="Enable temporal aggregation")
    freq: str = Field("1min", description="Aggregation frequency (pandas offset alias)")
    method: Literal["mean", "median"] = Field("mean", description="Aggregation method")


class GridAssignmentConfig(_StrictModel):
    """Grid cell assignment preprocessing settings."""

    enabled: bool = Field(True, description="Enable grid cell assignment")
    grid_type: str = Field("equal_area", description="Grid type for cell assignment")
    angular_resolution: float = Field(
        2.0, gt=0, le=90, description="Angular resolution in degrees"
    )


class HistogramBinsConfig(_StrictModel):
    """Custom histogram bin specification for a variable."""

    low: float = Field(..., description="Lower edge of the first bin")
    high: float = Field(..., description="Upper edge of the last bin")
    n_bins: int = Field(..., ge=1, description="Number of bins")


class StatisticsConfig(_StrictModel):
    """Streaming statistics configuration."""

    enabled: bool = Field(False, description="Enable streaming statistics collection")
    variables: list[str] = Field(
        default_factory=lambda: ["SNR"],
        description="Variables to profile",
    )
    gk_epsilon: float = Field(
        0.01, gt=0, lt=1, description="GK sketch approximation parameter"
    )
    quantile_probs: list[float] = Field(
        default_factory=lambda: [
            0.001,
            0.01,
            0.05,
            0.1,
            0.25,
            0.5,
            0.75,
            0.9,
            0.95,
            0.99,
            0.999,
        ],
        description="Quantile probabilities to compute",
    )
    custom_histogram_bins: dict[str, HistogramBinsConfig] = Field(
        default_factory=dict,
        description="Per-variable histogram bin overrides",
    )


class PreprocessingConfig(_StrictModel):
    """Preprocessing pipeline configuration."""

    temporal_aggregation: TemporalAggregationConfig = Field(
        default_factory=TemporalAggregationConfig,
    )
    grid_assignment: GridAssignmentConfig = Field(
        default_factory=GridAssignmentConfig,
    )
    statistics: StatisticsConfig = Field(
        default_factory=StatisticsConfig,
    )


class PublicationRef(_StrictModel):
    """A publication reference."""

    doi: str
    citation: str | None = None


class FundingRef(_StrictModel):
    """A funding reference."""

    funder: str
    funder_ror: str | None = None
    grant_number: str | None = None
    award_title: str | None = None


class ReferencesConfig(_StrictModel):
    """Publications and funding references."""

    publications: list[PublicationRef] = Field(default_factory=list)
    funding: list[FundingRef] = Field(default_factory=list)


class ProcessingConfig(_StrictModel):
    """Complete processing configuration."""

    metadata: MetadataConfig
    credentials: CredentialsConfig = Field(
        default_factory=CredentialsConfig,
        description="Credentials for external data services",
    )
    aux_data: AuxDataConfig = Field(default_factory=AuxDataConfig)
    params: ProcessingParams = Field(default_factory=ProcessingParams)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
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


# ============================================================================
# Sites Configuration
# ============================================================================


class ReceiverConfig(_StrictModel):
    """Receiver configuration."""

    type: Literal["reference", "canopy"] = Field(
        ...,
        description="Receiver type",
    )
    directory: str = Field(..., description="Subdirectory for receiver data")
    paired_canopies: str | list[str] | None = Field(
        None,
        description=(
            "Which canopy receiver(s) to pair with this reference. "
            "Required for reference receivers: 'all' or a list of canopy names. "
            "Must not be set for canopy receivers."
        ),
    )
    description: str | None = Field(
        None,
        description="Human-readable description",
    )
    naming: dict | None = Field(
        None,
        description="Naming configuration (validated by canvod-virtualiconvname package)",
    )
    metadata: dict[str, str | int | float | bool] | None = Field(
        None,
        description=(
            "Freeform receiver metadata written to dataset global attrs. "
            "Example keys: site_url, antenna_height, species."
        ),
    )
    reader_format: str = Field(
        "auto",
        description=(
            "GNSS data reader format: 'auto', 'rinex3', 'sbf'. "
            "When 'auto', detected from files at pipeline start."
        ),
    )
    recipe: str | None = Field(
        None,
        description=(
            "Name of a naming recipe (e.g. 'rosalia_reference'). "
            "Resolved from config/recipes/{recipe}.yaml. "
            "When set, replaces the 'naming' block for file discovery."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_scs_from(cls, data: object) -> object:
        if isinstance(data, dict) and "scs_from" in data:
            import warnings

            warnings.warn(
                "ReceiverConfig: 'scs_from' is deprecated; use 'paired_canopies' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            data = dict(data)
            data["paired_canopies"] = data.pop("scs_from")
        return data

    @model_validator(mode="after")
    def validate_paired_canopies(self) -> ReceiverConfig:
        """Validate paired_canopies is required for reference, forbidden for canopy."""
        if self.type == "reference" and self.paired_canopies is None:
            msg = "paired_canopies is required for reference receivers"
            raise ValueError(msg)
        if self.type == "canopy" and self.paired_canopies is not None:
            msg = "paired_canopies must not be set for canopy receivers"
            raise ValueError(msg)
        return self


class VodAnalysisConfig(_StrictModel):
    """VOD analysis pair configuration."""

    canopy_receiver: str = Field(..., description="Canopy receiver name")
    reference_receiver: str = Field(..., description="Reference receiver name")
    description: str | None = Field(None, description="Analysis description")


class SiteConfig(_StrictModel):
    """Research site configuration."""

    gnss_site_data_root: str = Field(
        ..., description="Root directory for site GNSS data"
    )
    description: str | None = Field(None, description="Site description")
    country: str | None = Field(None, description="Country code (ISO 3166-1)")
    latitude: float | None = Field(None, description="WGS84 latitude")
    longitude: float | None = Field(None, description="WGS84 longitude")
    altitude_m: float | None = Field(None, description="Altitude in meters")
    receivers: dict[str, ReceiverConfig] = Field(..., description="Site receivers")
    vod_analyses: dict[str, VodAnalysisConfig] | None = Field(
        None,
        description="VOD analysis pairs",
    )
    naming: dict | None = Field(
        None,
        description="Naming configuration (validated by canvod-virtualiconvname package)",
    )

    @model_validator(mode="after")
    def validate_paired_canopies_targets(self) -> SiteConfig:
        """Validate that paired_canopies entries reference existing canopy receivers."""
        canopy_names = self.get_canopy_receiver_names()
        for name, cfg in self.receivers.items():
            if cfg.type != "reference" or cfg.paired_canopies is None:
                continue
            if isinstance(cfg.paired_canopies, str) and cfg.paired_canopies == "all":
                continue
            targets = (
                cfg.paired_canopies
                if isinstance(cfg.paired_canopies, list)
                else [cfg.paired_canopies]
            )
            for target in targets:
                if target not in canopy_names:
                    msg = (
                        f"Receiver '{name}' paired_canopies references '{target}' "
                        f"which is not a canopy receiver. "
                        f"Available canopy receivers: {canopy_names}"
                    )
                    raise ValueError(msg)
        return self

    def get_base_path(self) -> Path:
        """Get gnss_site_data_root as a Path.

        Returns
        -------
        Path
            Site data root directory as a Path object.
        """
        return Path(self.gnss_site_data_root)

    def get_canopy_receiver_names(self) -> list[str]:
        """Get names of all canopy receivers.

        Returns
        -------
        list[str]
            Canopy receiver names.
        """
        return [name for name, cfg in self.receivers.items() if cfg.type == "canopy"]

    def resolve_paired_canopies(self, receiver_name: str) -> list[str]:
        """Resolve paired_canopies for a reference receiver to a list of canopy names.

        Parameters
        ----------
        receiver_name : str
            Name of the reference receiver.

        Returns
        -------
        list[str]
            List of canopy receiver names paired with this reference.
        """
        cfg = self.receivers[receiver_name]
        if cfg.type != "reference":
            msg = f"resolve_paired_canopies only applies to reference receivers, got '{cfg.type}'"
            raise ValueError(msg)
        if cfg.paired_canopies == "all":
            return self.get_canopy_receiver_names()
        if isinstance(cfg.paired_canopies, list):
            return cfg.paired_canopies
        # Single canopy name as string
        if cfg.paired_canopies is None:
            msg = f"Receiver '{receiver_name}' has no paired_canopies configured"
            raise ValueError(msg)
        return [cfg.paired_canopies]

    def resolve_scs_from(self, receiver_name: str) -> list[str]:
        """Deprecated: use resolve_paired_canopies instead."""
        import warnings

        warnings.warn(
            "SiteConfig.resolve_scs_from is deprecated; use resolve_paired_canopies instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.resolve_paired_canopies(receiver_name)

    def get_reference_canopy_pairs(self) -> list[tuple[str, str]]:
        """Expand paired_canopies into (reference_name, canopy_name) pairs.

        Returns
        -------
        list[tuple[str, str]]
            List of (reference_name, canopy_name) pairs.
        """
        pairs = []
        for name, cfg in self.receivers.items():
            if cfg.type != "reference":
                continue
            for canopy_name in self.resolve_paired_canopies(name):
                pairs.append((name, canopy_name))
        return pairs


class SitesConfig(_StrictModel):
    """All research sites."""

    sites: dict[str, SiteConfig]

    @field_validator("sites")
    @classmethod
    def validate_at_least_one_site(
        cls,
        v: dict[str, SiteConfig],
    ) -> dict[str, SiteConfig]:
        """Warn if no sites are defined.

        Parameters
        ----------
        v : dict[str, SiteConfig]
            Sites dictionary to validate.

        Returns
        -------
        dict[str, SiteConfig]
            Validated sites dictionary.
        """
        if not v:
            import warnings

            warnings.warn(
                "No research sites defined in sites.yaml. Run: just config-init",
                UserWarning,
                stacklevel=2,
            )
        return v


# ============================================================================
# SIDs Configuration
# ============================================================================


class SidsConfig(_StrictModel):
    """Signal ID configuration."""

    mode: Literal["all", "preset", "custom"] = Field(
        "all",
        description="SID selection mode",
    )
    preset: str | None = Field(
        None,
        description="Preset name when mode=preset",
    )
    custom_sids: list[str] = Field(
        default_factory=list,
        description="Custom SID list when mode=custom",
    )

    @field_validator("preset")
    @classmethod
    def validate_preset_when_mode_preset(
        cls,
        v: str | None,
        info: ValidationInfo,
    ) -> str | None:
        """Ensure preset is set when mode is preset.

        Parameters
        ----------
        v : str | None
            Preset name.
        info : ValidationInfo
            Pydantic validation info.

        Returns
        -------
        str | None
            Preset value if valid.
        """
        mode = info.data.get("mode")
        if mode == "preset" and not v:
            msg = "preset must be specified when mode is 'preset'"
            raise ValueError(msg)
        return v

    def get_sids(self) -> list[str] | None:
        """Get the effective SID list.

        Returns
        -------
        list[str] | None
            None if mode is "all" (keep all SIDs), otherwise a SID list.
        """
        if self.mode == "all":
            return None
        if self.mode == "preset":
            return self._get_preset_sids()
        # CUSTOM
        return self.custom_sids

    def _get_preset_sids(self) -> list[str]:
        if self.preset is None:
            msg = "preset must be set when mode is 'preset'"
            raise ValueError(msg)
        presets_dir = Path(__file__).parent / "presets"
        preset_file = presets_dir / f"{self.preset}.yaml"
        if not preset_file.exists():
            known = sorted(p.stem for p in presets_dir.glob("*.yaml"))
            msg = f"Unknown SID preset '{self.preset}'. Available: {known}"
            raise ValueError(msg)
        with preset_file.open() as f:
            data = yaml.safe_load(f)
        return data.get("sids", [])


# ============================================================================
# Complete Configuration
# ============================================================================


class CanvodConfig(BaseSettings):
    """
    Complete canvodpy configuration.

    Loaded from YAML files by ConfigLoader; individual fields can be
    overridden via environment variables using the ``CANVOD__`` prefix
    and ``__`` as the nested delimiter.  Environment variables take
    priority over YAML-file values.

    Examples
    --------
    Override a single nested field without touching the YAML::

        CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7 canvodpy run ...
        CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=me@x.com canvodpy run ...
    """

    model_config = SettingsConfigDict(
        env_prefix="CANVOD__",
        env_nested_delimiter="__",
        extra="forbid",
        env_file=["config/.env", ".env"],
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )

    processing: ProcessingConfig
    sites: SitesConfig
    sids: SidsConfig

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Env vars beat YAML-loaded init kwargs; dotenv/secrets not used.
        return (env_settings, init_settings)

    @property
    def nasa_earthdata_acc_mail(self) -> str | None:
        """Return the configured NASA Earthdata email for CDDIS authentication.

        Returns
        -------
        str | None
            NASA Earthdata email address.
        """
        return self.processing.credentials.nasa_earthdata_acc_mail
