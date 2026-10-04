"""Cells without data in the 3D views."""

import numpy as np
import pytest

from canvod.grids import create_hemigrid
from canvod.viz import HemisphereVisualizer3D


@pytest.mark.parametrize("grid_type", ["equal_area", "htm", "geodesic", "fibonacci"])
def test_missing_cells_get_their_own_color(grid_type):
    """NaN cells leave the color scale and are drawn in nan_color, so they
    don't look like the minimum value."""
    grid = create_hemigrid(grid_type, angular_resolution=10.0)
    data = np.linspace(0.0, 1.0, grid.ncells)
    data[: grid.ncells // 4] = np.nan

    fig = HemisphereVisualizer3D(grid).plot_hemisphere_surface(
        data=data, nan_color="pink"
    )

    colored, empty = fig.data[0], fig.data[1]
    assert empty.name == "No data" and empty.color == "pink"
    intensity = np.asarray(colored.intensity, dtype=float)
    used = np.unique(np.concatenate([colored.i, colored.j, colored.k]))
    assert not np.isnan(intensity[used]).any()
    assert colored.cmin == pytest.approx(np.nanmin(data))


def test_without_missing_cells_one_trace():
    grid = create_hemigrid("equal_area", angular_resolution=10.0)
    fig = HemisphereVisualizer3D(grid).plot_hemisphere_surface(
        data=np.ones(grid.ncells), show_wireframe=False
    )
    assert len(fig.data) == 1


def test_cell_mesh_is_oriented_like_the_surface():
    """x is east in every 3D view: the HTM vertices are (north, east, up)."""
    grid = create_hemigrid("htm", angular_resolution=10.0)
    viz = HemisphereVisualizer3D(grid)
    mesh = viz.plot_cell_mesh(data=np.ones(grid.ncells)).data[0]
    v0 = np.asarray(grid.grid["htm_vertex_0"][0], dtype=float)
    v1 = np.asarray(grid.grid["htm_vertex_1"][0], dtype=float)
    assert list(mesh.x[:2]) == pytest.approx([v0[1], v1[1]])
    assert list(mesh.y[:2]) == pytest.approx([v0[0], v1[0]])
