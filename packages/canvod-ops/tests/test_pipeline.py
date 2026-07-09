"""Tests for the preprocessing pipeline."""

import xarray as xr

from canvod.config.models import (
    GridAssignmentConfig,
    PreprocessingConfig,
    TemporalAggregationConfig,
)
from canvod.ops.base import Op, OpResult
from canvod.ops.pipeline import Pipeline, PipelineResult
from canvod.ops.registry import build_default_pipeline
from canvod.ops.temporal import TemporalAggregate


class _NoOp(Op):
    """Trivial op for testing."""

    @property
    def name(self) -> str:
        return "noop"

    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]:
        return ds, OpResult(
            op_name=self.name,
            parameters={},
            input_shape=dict(ds.sizes),
            output_shape=dict(ds.sizes),
            duration_seconds=0.0,
        )


class TestPipeline:
    def test_empty_pipeline(self, sample_ds: xr.Dataset):
        """Empty pipeline should pass dataset through unchanged."""
        pipe = Pipeline()
        out, pr = pipe(sample_ds)

        xr.testing.assert_identical(out, sample_ds)
        assert len(pr.results) == 0

    def test_single_op(self, sample_ds: xr.Dataset):
        """Pipeline with one op should produce one result."""
        pipe = Pipeline([_NoOp()])
        out, pr = pipe(sample_ds)

        assert len(pr.results) == 1
        assert pr.results[0].op_name == "noop"

    def test_chained_ops(self, sample_ds: xr.Dataset):
        """Pipeline.add() should chain ops."""
        pipe = Pipeline()
        pipe.add(_NoOp()).add(_NoOp())
        _, pr = pipe(sample_ds)

        assert len(pr.results) == 2

    def test_total_duration(self, sample_ds: xr.Dataset):
        """PipelineResult should track total wall time."""
        pipe = Pipeline([_NoOp()])
        _, pr = pipe(sample_ds)

        assert pr.total_duration_seconds >= 0


class TestPipelineResult:
    def test_to_metadata_dict(self):
        """to_metadata_dict should produce the expected structure."""
        r = OpResult(
            op_name="test",
            parameters={"a": 1},
            input_shape={"epoch": 100},
            output_shape={"epoch": 50},
            duration_seconds=0.5,
        )
        pr = PipelineResult(results=[r], total_duration_seconds=0.5)
        d = pr.to_metadata_dict()

        assert "preprocessing_ops" in d
        assert len(d["preprocessing_ops"]) == 1
        assert d["preprocessing_ops"][0]["op_name"] == "test"
        assert d["preprocessing_total_seconds"] == 0.5


class TestBuildDefaultPipeline:
    def test_default_config(self):
        """Default config should create a pipeline with 2 ops."""
        pipe = build_default_pipeline(PreprocessingConfig())
        assert len(pipe._ops) == 2

    def test_disabled_temporal(self):
        """Disabling temporal aggregation should skip it."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(enabled=False),
        )
        pipe = build_default_pipeline(config)
        assert len(pipe._ops) == 1
        assert pipe._ops[0].name == "grid_assign"

    def test_disabled_grid(self):
        """Disabling grid assignment should skip it."""
        config = PreprocessingConfig(
            grid_assignment=GridAssignmentConfig(enabled=False),
        )
        pipe = build_default_pipeline(config)
        assert len(pipe._ops) == 1
        assert pipe._ops[0].name == "temporal_aggregate"

    def test_all_disabled(self):
        """Disabling everything should produce an empty pipeline."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(enabled=False),
            grid_assignment=GridAssignmentConfig(enabled=False),
        )
        pipe = build_default_pipeline(config)
        assert len(pipe._ops) == 0

    def test_custom_freq(self):
        """Custom freq from config should propagate to the op."""
        config = PreprocessingConfig(
            temporal_aggregation=TemporalAggregationConfig(freq="5min"),
        )
        pipe = build_default_pipeline(config)
        temporal_op = pipe._ops[0]
        assert isinstance(temporal_op, TemporalAggregate)
        assert temporal_op._freq == "5min"
