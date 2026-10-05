"""Pipeline for chaining preprocessing operations."""

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
import xarray as xr

from canvod.config.models import preprocessing_record
from canvod.ops.base import Op, OpResult, ops_version

logger = structlog.get_logger(__name__)


@dataclass
class PipelineResult:
    """Aggregated result from running a full pipeline."""

    results: list[OpResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0

    def record(self) -> str:
        """Preprocessing record (JSON) of the operations, in the order they ran."""
        return preprocessing_record([r.step() for r in self.results], ops_version())

    def to_metadata_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for ``ds.attrs``."""
        return {
            "preprocessing_ops": [r.to_dict() for r in self.results],
            "preprocessing_total_seconds": self.total_duration_seconds,
        }


class Pipeline:
    """Ordered chain of :class:`~canvod.ops.base.Op` instances."""

    def __init__(self, ops: list[Op] | None = None) -> None:
        self._ops: list[Op] = list(ops) if ops else []

    def __len__(self) -> int:
        """Number of operations."""
        return len(self._ops)

    def add(self, op: Op) -> Pipeline:
        """Append an operation and return self for chaining."""
        self._ops.append(op)
        return self

    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, PipelineResult]:
        t0 = time.perf_counter()
        results: list[OpResult] = []

        for op in self._ops:
            logger.info("running_op", op_name=op.name)
            ds, op_result = op(ds)
            results.append(op_result)

        total = time.perf_counter() - t0
        pr = PipelineResult(results=results, total_duration_seconds=total)

        logger.info(
            "pipeline_complete",
            n_ops=len(results),
            duration_s=round(total, 2),
        )
        return ds, pr
