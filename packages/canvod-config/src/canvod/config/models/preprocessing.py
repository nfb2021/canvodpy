"""Preprocessing pipeline configuration: temporal aggregation, grid assignment, statistics."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import Field, field_validator

from .base import _StrictModel

_FREQ_UNIT_SECONDS = {"s": 1, "min": 60, "h": 3600}
_FREQ = re.compile(r"^([1-9][0-9]*)(s|min|h)$")


class TemporalAggregationConfig(_StrictModel):
    """Temporal aggregation of the observations into time bins."""

    enabled: bool = Field(True, description="Apply the temporal aggregation")
    freq: str = Field(
        ...,
        description=(
            "Bin length: a whole number of seconds, minutes or hours "
            "('30s', '1min', '1h') that divides one day"
        ),
    )
    method: Literal["mean", "median"] = Field(
        ..., description="Statistic of the observations in each bin"
    )

    @field_validator("freq")
    @classmethod
    def _freq_divides_day(cls, value: str) -> str:
        match = _FREQ.match(value)
        if match is None:
            msg = (
                f"freq must be a whole number followed by 's', 'min' or 'h' "
                f"(e.g. '30s', '1min'), not {value!r}"
            )
            raise ValueError(msg)
        seconds = int(match.group(1)) * _FREQ_UNIT_SECONDS[match.group(2)]
        if 86_400 % seconds:
            msg = (
                f"freq {value!r} does not divide one day, so the bins would "
                "not start at 00:00 of every day"
            )
            raise ValueError(msg)
        return value


class GridAssignmentConfig(_StrictModel):
    """Assignment of each observation to a cell of a hemispherical grid."""

    enabled: bool = Field(True, description="Apply the grid cell assignment")
    grid_type: str = Field(..., description="Grid type, e.g. 'equal_area'")
    angular_resolution: float = Field(
        ..., gt=0, le=90, description="Angular resolution in degrees"
    )


class HistogramBinsConfig(_StrictModel):
    """Custom histogram bin specification for a variable."""

    low: float = Field(..., description="Lower edge of the first bin")
    high: float = Field(..., description="Upper edge of the last bin")
    n_bins: int = Field(..., ge=1, description="Number of bins")


class StatisticsConfig(_StrictModel):
    """Streaming statistics configuration.

    Reserved for a future release: no run reads this section yet, so setting
    it has no effect.
    """

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
    """Operations applied before the data are written to the GNSS store.

    Each operation is applied only if its section is set (and ``enabled``).
    Temporal aggregation runs first, then the grid cell assignment.
    """

    temporal_aggregation: TemporalAggregationConfig | None = Field(
        None, description="Temporal aggregation; not applied unless set"
    )
    grid_assignment: GridAssignmentConfig | None = Field(
        None, description="Grid cell assignment; not applied unless set"
    )
    statistics: StatisticsConfig = Field(
        default_factory=StatisticsConfig,
        description="Streaming statistics; reserved, not read by any run yet",
    )


#: Dataset and store-group attribute recording the applied preprocessing.
PREPROCESSING_ATTR = "Preprocessing"


def preprocessing_record(config: PreprocessingConfig | None) -> str:
    """JSON record of the operations ``config`` applies (``"{}"`` for none).

    Stored in the ``Preprocessing`` attribute of every written dataset, so a
    store group never mixes data preprocessed in different ways.

    Parameters
    ----------
    config : PreprocessingConfig | None
        The ``processing.preprocessing`` section.

    Returns
    -------
    str
        Sorted-key JSON of the enabled operations and their settings.
    """
    record: dict[str, dict] = {}
    if config is not None:
        temporal = config.temporal_aggregation
        if temporal is not None and temporal.enabled:
            record["temporal_aggregation"] = temporal.model_dump(exclude={"enabled"})
        grid = config.grid_assignment
        if grid is not None and grid.enabled:
            record["grid_assignment"] = grid.model_dump(exclude={"enabled"})
    return json.dumps(record, sort_keys=True)
