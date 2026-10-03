"""Grid cell assignment operation."""

import time
from typing import Any, cast

import numpy as np
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
            )
            return ds, result

        grid = self._get_grid()
        grid_name = f"{self._grid_type}_{self._angular_resolution}deg"

        # Inline cell assignment using KDTree (avoids add_cell_ids_to_vod_fast
        # which assumes a "VOD" data variable exists).
        from canvod.grids.operations import _build_kdtree, _query_points

        tree = _build_kdtree(grid)
        cell_id_col = grid.grid["cell_id"].to_numpy()

        phi = ds["phi"].transpose("epoch", "sid")
        phi_vals = phi.values.ravel()
        theta_vals = ds["theta"].transpose("epoch", "sid").values.ravel()
        valid = np.isfinite(phi_vals) & np.isfinite(theta_vals)

        cell_ids = np.full(len(phi_vals), np.nan, dtype=np.float64)
        if np.any(valid):
            cell_ids[valid] = _query_points(
                tree, cell_id_col, phi_vals[valid], theta_vals[valid]
            )

        shape_2d = phi.shape
        cell_ids_2d = cell_ids.reshape(shape_2d)

        coord_name = f"cell_id_{grid_name}"
        ds[coord_name] = (("epoch", "sid"), cell_ids_2d)

        n_assigned = int(np.sum(np.isfinite(cell_ids_2d)))
        n_unique = len(np.unique(cell_ids[np.isfinite(cell_ids)]))
        duration = time.perf_counter() - t0

        logger.info(
            "grid_assignment_complete",
            n_cells=n_unique,
            n_assigned=n_assigned,
            duration_s=round(duration, 2),
        )

        output_shape = {str(k): int(v) for k, v in dict(ds.sizes).items()}
        result = OpResult(
            op_name=self.name,
            parameters=params,
            input_shape=input_shape,
            output_shape=output_shape,
            duration_seconds=duration,
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
