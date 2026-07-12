"""NetCDF compression and Icechunk storage-engine configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import _StrictModel


class NetcdfCompressionConfig(_StrictModel):
    """NetCDF compression settings used by RINEX readers when writing .nc files.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    zlib: bool = Field(True, description="Use zlib compression")
    complevel: int = Field(5, ge=0, le=9, description="Compression level")


CompressionConfig = NetcdfCompressionConfig  # deprecated alias


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

    compression_level: int = Field(3, ge=0, le=22)
    compression_algorithm: Literal["zstd"] = "zstd"
    inline_chunk_threshold_bytes: int = Field(512, ge=0)
    get_partial_values_concurrency: int = Field(1, ge=1)
    max_concurrent_requests: int | None = Field(
        None,
        ge=1,
        description="Maximum number of concurrent object-store requests (None = icechunk default)",
    )
    cache_num_chunk_refs: int | None = Field(
        None,
        ge=0,
        description="Maximum number of chunk references to cache in memory (None = icechunk default)",
    )
    cache_num_bytes_chunks: int | None = Field(
        None,
        ge=0,
        description="Maximum bytes of chunk data to cache in memory (None = icechunk default)",
    )
    chunk_strategies: dict[str, ChunkStrategy] = Field(
        default_factory=lambda: {
            "gnss_store": ChunkStrategy(epoch=34560, sid=-1),
            "vod_store": ChunkStrategy(epoch=34560, sid=-1),
        },
    )
    manifest_preload_enabled: bool = Field(
        False,
        description="Enable manifest preloading for faster chunk access",
    )
    manifest_preload_max_refs: int = Field(
        10_000,
        ge=0,
        description="Maximum total chunk refs to preload across all matched arrays",
    )
    manifest_preload_max_arrays_to_scan: int = Field(
        500,
        ge=1,
        description="Maximum number of arrays to scan for preload candidates",
    )
    manifest_preload_pattern: str = Field(
        r"^(epoch|sid)$",
        description="Regex pattern matched against array names to select preload candidates",
    )
    manifest_splitting_enabled: bool = Field(
        True,
        description="Enable manifest splitting for stores with large arrays (recommended)",
    )
    manifest_splitting_epoch_range: int = Field(
        34560,
        ge=1,
        description=(
            "Split arrays along the epoch dimension every N indices. "
            "Set to match your epoch chunk size (e.g. 34560 for 24 h at 2.5 s)."
        ),
    )
