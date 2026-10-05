"""Grid cell assignment operation."""

import time
from typing import Any, cast

import structlog
import xarray as xr

from canvod.ops.base import Op, OpResult

logger = structlog.get_logger(__name__)


class GridAssignment(Op):
    """Assign each ``(epoch, sid)`` observation to a grid cell.

    Parameters
    ----------
    grid_type : str
        Grid builder name (e.g. ``"equal_area"``).
    angular_resolution : float
        Grid resolution in degrees.
    """

    packages = ("canvod-ops", "canvod-grids")

    def __init__(
        self,
        grid_type: str = "equal_area",
        angular_resolution: float = 2.0,
    ) -> None:
        self._grid_type = grid_type
        self._angular_resolution = angular_resolution
        self._grid = None  # lazy

    @property
    def name(self) -> str:
        return "grid_assign"

    def _get_grid(self):
        if self._grid is None:
            from canvod.grids import create_hemigrid

            self._grid = create_hemigrid(
                cast(Any, self._grid_type),
                angular_resolution=self._angular_resolution,
            )
        return self._grid

    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]:
        t0 = time.perf_counter()
        params: dict[str, Any] = {
            "grid_type": self._grid_type,
            "angular_resolution": self._angular_resolution,
        }
        input_shape = {str(k): int(v) for k, v in dict(ds.sizes).items()}

        # Prerequisite check: phi/theta as data variables (as the runs write
        # them) or as coordinates
        has_phi = "phi" in ds.variables and set(ds["phi"].dims) == {"epoch", "sid"}
        has_theta = "theta" in ds.variables and set(ds["theta"].dims) == {
            "epoch",
            "sid",
        }

        if not (has_phi and has_theta):
            logger.warning(
                "Grid assignment skipped: dataset has no phi/theta (epoch, sid) variables"
            )
            result = OpResult(
                op_name=self.name,
                parameters=params,
                input_shape=input_shape,
                output_shape=input_shape,
                duration_seconds=time.perf_counter() - t0,
                notes="skipped: missing phi/theta",
                result={"assigned": False, "reason": "no phi/theta (epoch, sid)"},
            )
            return ds, result

        grid = self._get_grid()
        grid_name = f"{self._grid_type}_{self._angular_resolution}deg"

        from canvod.grids.operations import add_cell_ids_to_ds_fast

        ds = add_cell_ids_to_ds_fast(ds, grid, grid_name)
        duration = time.perf_counter() - t0

        output_shape = {str(k): int(v) for k, v in dict(ds.sizes).items()}
        result = OpResult(
            op_name=self.name,
            parameters=params,
            input_shape=input_shape,
            output_shape=output_shape,
            duration_seconds=duration,
            result={
                "assigned": True,
                "variable": f"cell_id_{grid_name}",
                "n_cells": int(grid.ncells),
            },
        )
        return ds, result


def grid_assign(
    ds: xr.Dataset,
    grid_type: str = "equal_area",
    angular_resolution: float = 2.0,
) -> xr.Dataset:
    """Convenience function: assign grid cells to a dataset.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset with ``phi(epoch, sid)`` and ``theta(epoch, sid)`` coords.
    grid_type : str
        Grid builder name.
    angular_resolution : float
        Resolution in degrees.

    Returns
    -------
    xr.Dataset
        Dataset with ``cell_id_<grid_name>(epoch, sid)`` variable added.
    """
    op = GridAssignment(grid_type=grid_type, angular_resolution=angular_resolution)
    out, _ = op(ds)
    return out
