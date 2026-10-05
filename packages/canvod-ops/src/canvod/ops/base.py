"""Base abstractions for preprocessing operations."""

import importlib.metadata
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

import xarray as xr


def ops_version() -> str:
    """Installed canvod-ops version, recorded with every preprocessing."""
    return importlib.metadata.version("canvod-ops")


@dataclass(frozen=True)
class OpResult:
    """Immutable record of a single preprocessing operation."""

    op_name: str
    parameters: dict[str, Any]
    input_shape: dict[str, int]
    output_shape: dict[str, int]
    duration_seconds: float
    notes: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def step(self) -> dict[str, Any]:
        """This operation's entry in the preprocessing record.

        ``settings`` are the configured parameters, ``result`` what the
        operation measured or derived (see
        ``canvod.config.models.preprocessing_record``).
        """
        return {"op": self.op_name, "settings": self.parameters, "result": self.result}


class Op(ABC):
    """Abstract base class for a preprocessing operation.

    Each ``Op`` is a callable carrying config set at construction time.
    At call time it is a pure ``Dataset -> (Dataset, OpResult)`` transform.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]: ...
