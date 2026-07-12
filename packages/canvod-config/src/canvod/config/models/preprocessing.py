"""Preprocessing pipeline configuration: temporal aggregation, grid assignment, statistics."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import _StrictModel


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
