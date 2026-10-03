"""canvod.ops — Preprocessing operations pipeline for GNSS VOD data."""

__version__ = "0.1.0"

from canvod.ops.base import Op, OpResult
from canvod.ops.files import preprocess_files
from canvod.ops.grid import GridAssignment, grid_assign
from canvod.ops.pipeline import Pipeline, PipelineResult
from canvod.ops.registry import build_default_pipeline
from canvod.ops.temporal import TemporalAggregate, temporal_aggregate
