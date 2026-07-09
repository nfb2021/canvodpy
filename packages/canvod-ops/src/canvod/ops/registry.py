"""Default pipeline construction from configuration."""

from __future__ import annotations

from canvod.config.models import PreprocessingConfig
from canvod.ops.grid import GridAssignment
from canvod.ops.pipeline import Pipeline
from canvod.ops.temporal import TemporalAggregate


def build_default_pipeline(
    config: PreprocessingConfig | None = None,
) -> Pipeline:
    """Build the default preprocessing pipeline from config.

    Parameters
    ----------
    config : PreprocessingConfig | None
        Explicit config. If ``None``, attempts to load from the user's
        config files via ``load_config()``. Falls back to
        ``PreprocessingConfig()`` defaults if no config is available.

    Returns
    -------
    Pipeline
        Ready-to-call pipeline.
    """
    if config is None:
        try:
            from canvod.config import load_config

            config = load_config().processing.preprocessing
        except Exception:
            config = PreprocessingConfig()

    pipeline = Pipeline()

    if config.temporal_aggregation.enabled:
        pipeline.add(
            TemporalAggregate(
                freq=config.temporal_aggregation.freq,
                method=config.temporal_aggregation.method,
            )
        )

    if config.grid_assignment.enabled:
        pipeline.add(
            GridAssignment(
                grid_type=config.grid_assignment.grid_type,
                angular_resolution=config.grid_assignment.angular_resolution,
            )
        )

    return pipeline
