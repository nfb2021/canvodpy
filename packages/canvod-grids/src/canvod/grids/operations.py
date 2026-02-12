"""Cell assignment and vertex extraction for hemisphere grids.

Functions in this module operate on :class:`~canvod.grids.core.GridData`
instances and VOD xarray Datasets.

Cell assignment
---------------
``add_cell_ids_to_vod_fast``   – vectorised KDTree lookup (preferred)
``add_cell_ids_to_vod``        – element-wise fallback
``add_cell_ids_to_ds_fast``    – dask-lazy variant for out-of-core data

Vertex / grid conversion
------------------------
``extract_grid_vertices``      – flat (x, y, z) arrays for 3-D visualisation
``grid_to_dataset``            – xarray Dataset with vertices and solid angles
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr
from canvod.grids._internal import get_logger
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from canvod.grids.core import GridData

log = get_logger(__name__)


# ==============================================================================
# Internal: KDTree builder
# ==============================================================================


def _build_kdtree(grid: GridData) -> cKDTree:
    """Build a KDTree from grid cell centres (φ, θ → Cartesian)."""
    phi = grid.grid["phi"].to_numpy()
    theta = grid.grid["theta"].to_numpy()
    x = np.sin(theta) * np.cos(phi)
    y = np.sin(theta) * np.sin(phi)
    z = np.cos(theta)
    return cKDTree(np.column_stack([x, y, z]))


def _query_points(
    tree: cKDTree, cell_id_col: np.ndarray, phi: np.ndarray, theta: np.ndarray
) -> np.ndarray:
    """Vectorised nearest-cell lookup via KDTree.

    Parameters
    ----------
    tree : cKDTree
        KDTree built from grid cell centres.
    cell_id_col : np.ndarray
        ``cell_id`` column of the grid DataFrame (length = ncells).
    phi : np.ndarray
        Azimuth angles of query points.
    theta : np.ndarray
        Polar angles of query points.

    Returns
    -------
    np.ndarray
        Cell IDs for each query point.

    """
    x = np.sin(theta) * np.cos(phi)
    y = np.sin(theta) * np.sin(phi)
    z = np.cos(theta)
    _, indices = tree.query(np.column_stack([x, y, z]), workers=-1)
    return cell_id_col[indices]


# ==============================================================================
# Cell assignment
# ==============================================================================


def add_cell_ids_to_vod_fast(
    vod_ds: xr.Dataset, grid: GridData, grid_name: str
) -> xr.Dataset:
    """Assign grid cells to every observation in a VOD dataset (vectorised).

    Uses a KDTree built from the grid cell centres for O(n log m) lookup.

    Parameters
    ----------
    vod_ds : xr.Dataset
        VOD dataset with ``phi(epoch, sid)`` and ``theta(epoch, sid)``
        coordinate variables and a ``VOD`` data variable.
    grid : GridData
        Hemisphere grid instance.
    grid_name : str
        Grid identifier used to name the output coordinate
        (``cell_id_<grid_name>``).

    Returns
    -------
    xr.Dataset
        *vod_ds* with an additional ``cell_id_<grid_name>(epoch, sid)``
        variable.  Observations with non-finite φ or θ receive NaN.

    """
    start_time = time.time()
    print(f"\nAssigning cells for '{grid_name}'...")

    log.info(
        "cell_assignment_started",
        grid_name=grid_name,
        grid_cells=len(grid.grid),
        observations=vod_ds["VOD"].size,
        method="kdtree_fast",
    )

    tree = _build_kdtree(grid)
    cell_id_col = grid.grid["cell_id"].to_numpy()

    phi = vod_ds["phi"].values.ravel()
    theta = vod_ds["theta"].values.ravel()

    valid = np.isfinite(phi) & np.isfinite(theta)

    cell_ids = np.full(len(phi), np.nan, dtype=np.float64)

    if np.any(valid):
        cell_ids[valid] = _query_points(tree, cell_id_col, phi[valid], theta[valid])

    cell_ids_2d = cell_ids.reshape(vod_ds["VOD"].shape)

    coord_name = f"cell_id_{grid_name}"
    vod_ds[coord_name] = (("epoch", "sid"), cell_ids_2d)

    n_assigned = np.sum(np.isfinite(cell_ids_2d))
    n_unique = len(np.unique(cell_ids[np.isfinite(cell_ids)]))
    duration = time.time() - start_time

    print(f"  ✓ Assigned: {n_assigned:,} / {cell_ids_2d.size:,} observations")
    print(f"  ✓ Unique cells: {n_unique:,}")

    log.info(
        "cell_assignment_complete",
        grid_name=grid_name,
        duration_seconds=round(duration, 2),
        observations_assigned=int(n_assigned),
        observations_total=cell_ids_2d.size,
        unique_cells=int(n_unique),
        coverage_percent=round(100 * n_assigned / cell_ids_2d.size, 2),
    )

    return vod_ds


def add_cell_ids_to_vod(
    vod_ds: xr.Dataset, grid: GridData, grid_name: str
) -> xr.Dataset:
    """Assign grid cells to a VOD dataset (element-wise fallback).

    Slower than :func:`add_cell_ids_to_vod_fast`; kept for cases where the
    full dataset does not fit in memory as numpy arrays.

    Parameters
    ----------
    vod_ds : xr.Dataset
        VOD dataset with ``phi``, ``theta``, and ``VOD`` variables.
    grid : GridData
        Hemisphere grid instance.
    grid_name : str
        Grid identifier for the output coordinate name.

    Returns
    -------
    xr.Dataset
        *vod_ds* with ``cell_id_<grid_name>(epoch, sid)`` added.

    """
    print(f"\nAssigning cells for '{grid_name}'...")

    tree = _build_kdtree(grid)
    cell_id_col = grid.grid["cell_id"].to_numpy()

    phi_flat = vod_ds["phi"].to_numpy().ravel()
    theta_flat = vod_ds["theta"].to_numpy().ravel()

    cell_ids_flat = np.full(vod_ds["VOD"].size, np.nan)

    for i in range(len(phi_flat)):
        if np.isfinite(phi_flat[i]) and np.isfinite(theta_flat[i]):
            cell_ids_flat[i] = _query_points(
                tree, cell_id_col, np.array([phi_flat[i]]), np.array([theta_flat[i]])
            )[0]

    cell_ids_2d = cell_ids_flat.reshape(vod_ds["VOD"].shape)

    coord_name = f"cell_id_{grid_name}"
    vod_ds[coord_name] = (("epoch", "sid"), cell_ids_2d)

    n_assigned = np.sum(~np.isnan(cell_ids_2d))
    print(f"  ✓ Added coordinate '{coord_name}'")
    print(f"  ✓ Assigned: {n_assigned:,} / {cell_ids_2d.size:,} observations")

    # Track grid references in dataset attrs
    if "grid_references" not in vod_ds.attrs:
        vod_ds.attrs["grid_references"] = []
    vod_ds.attrs["grid_references"].append(f"grids/{grid_name}")

    return vod_ds


def add_cell_ids_to_ds_fast(
    ds: xr.Dataset, grid: GridData, grid_name: str, data_var: str = "VOD"
) -> xr.Dataset:
    """Assign grid cells lazily via dask (avoids loading full arrays).

    The output ``cell_id_<grid_name>`` variable is a dask array that
    computes on access or save.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with dask-backed ``phi`` and ``theta`` arrays.
    grid : GridData
        Hemisphere grid instance.
    grid_name : str
        Grid identifier for the output coordinate name.
    data_var : str
        Name of the main data variable (used only for shape reference).

    Returns
    -------
    xr.Dataset
        *ds* with a lazy ``cell_id_<grid_name>(epoch, sid)`` variable.

    """
    import dask.array as da

    print(f"\nAssigning cells for '{grid_name}'...")

    tree = _build_kdtree(grid)
    cell_id_col = grid.grid["cell_id"].to_numpy()

    def _assign_chunk(
        phi_chunk: np.ndarray,
        theta_chunk: np.ndarray,
    ) -> np.ndarray:
        """Assign cell IDs for a chunk of data.

        Parameters
        ----------
        phi_chunk : np.ndarray
            Chunk of azimuth values.
        theta_chunk : np.ndarray
            Chunk of elevation values.

        Returns
        -------
        np.ndarray
            Chunk of cell IDs.

        """
        phi_flat = phi_chunk.ravel()
        theta_flat = theta_chunk.ravel()

        valid = np.isfinite(phi_flat) & np.isfinite(theta_flat)
        cell_ids = np.full(len(phi_flat), np.nan, dtype=np.float32)

        if np.any(valid):
            cell_ids[valid] = _query_points(
                tree, cell_id_col, phi_flat[valid], theta_flat[valid]
            )

        return cell_ids.reshape(phi_chunk.shape)

    cell_ids_dask = da.map_blocks(
        _assign_chunk,
        ds["phi"].data,
        ds["theta"].data,
        dtype=np.float32,
        drop_axis=[],
    )

    coord_name = f"cell_id_{grid_name}"
    ds[coord_name] = (("epoch", "sid"), cell_ids_dask)

    print("  ✓ Cell IDs assigned as lazy dask array")
    print("  ✓ Will compute on access/save")

    return ds


# ==============================================================================
# Vertex extraction
# ==============================================================================


def extract_grid_vertices(grid: GridData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract 3D vertices from hemisphere grid cells.

    Dispatches to a grid-type–specific extractor.  The returned arrays are
    flat (not per-cell); use them directly for 3-D scatter plots.

    Parameters
    ----------
    grid : GridData
        Hemisphere grid instance.

    Returns
    -------
    x_vertices, y_vertices, z_vertices : np.ndarray
        Cartesian vertex coordinates on the unit sphere.

    """
    extractors = {
        "htm": _extract_htm_vertices,
        "geodesic": _extract_geodesic_vertices,
        "equal_area": _extract_rectangular_vertices,
        "equal_angle": _extract_rectangular_vertices,
        "equirectangular": _extract_rectangular_vertices,
        "healpix": _extract_healpix_vertices,
        "fibonacci": _extract_fibonacci_vertices,
    }
    extractor = extractors.get(grid.grid_type)
    if extractor is None:
        raise ValueError(f"Unknown grid type: {grid.grid_type}")
    return extractor(grid)


def _extract_htm_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from HTM triangular grid."""
    all_x, all_y, all_z = [], [], []

    for row in grid.grid.iter_rows(named=True):
        v0 = np.array(row["htm_vertex_0"])
        v1 = np.array(row["htm_vertex_1"])
        v2 = np.array(row["htm_vertex_2"])

        for vertex in [v0, v1, v2]:
            if vertex[2] >= -0.01:  # Small tolerance for numerical errors
                vertex[2] = max(vertex[2], 0.0)  # Clamp to hemisphere
                all_x.append(vertex[0])
                all_y.append(vertex[1])
                all_z.append(vertex[2])

    return np.array(all_x), np.array(all_y), np.array(all_z)


def _extract_rectangular_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from rectangular grid cells.

    Supports equal_area, equal_angle, and equirectangular grids.
    """
    all_x, all_y, all_z = [], [], []

    for row in grid.grid.iter_rows(named=True):
        phi_min = row["phi_min"]
        phi_max = row["phi_max"]
        theta_min = row["theta_min"]
        theta_max = row["theta_max"]

        phi_corners = [phi_min, phi_max, phi_max, phi_min]
        theta_corners = [theta_min, theta_min, theta_max, theta_max]

        for phi, theta in zip(phi_corners, theta_corners):
            x = np.sin(theta) * np.cos(phi)
            y = np.sin(theta) * np.sin(phi)
            z = np.cos(theta)
            all_x.append(x)
            all_y.append(y)
            all_z.append(z)

    return np.array(all_x), np.array(all_y), np.array(all_z)


def _extract_geodesic_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from geodesic grid triangles.

    Uses the shared vertex array and per-cell index column to return
    actual triangle vertices.  Falls back to cell centres if the shared
    vertex data is unavailable.
    """
    shared = grid.vertices  # (n_vertices, 3) from extra_kwargs
    if shared is not None and "geodesic_vertices" in grid.grid.columns:
        all_x, all_y, all_z = [], [], []
        for row in grid.grid.iter_rows(named=True):
            v_indices = np.array(row["geodesic_vertices"], dtype=int)
            for vi in v_indices:
                v = shared[vi]
                if v[2] >= -0.01:
                    all_x.append(v[0])
                    all_y.append(v[1])
                    all_z.append(max(v[2], 0.0))
        return np.array(all_x), np.array(all_y), np.array(all_z)

    # Fallback: cell centres
    phi_vals = grid.grid["phi"].to_numpy()
    theta_vals = grid.grid["theta"].to_numpy()
    x = np.sin(theta_vals) * np.cos(phi_vals)
    y = np.sin(theta_vals) * np.sin(phi_vals)
    z = np.cos(theta_vals)
    return x, y, z


def _extract_healpix_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from HEALPix grid via healpy boundaries."""
    try:
        import healpy as hp
    except ImportError:
        raise ImportError("healpy required for HEALPix vertex extraction")

    nside = int(grid.grid["healpix_nside"][0])
    all_x, all_y, all_z = [], [], []

    for row in grid.grid.iter_rows(named=True):
        ipix = int(row["healpix_ipix"])

        vertices = hp.boundaries(nside, ipix, step=1)  # shape (3, n_vertices)

        for j in range(vertices.shape[1]):
            x, y, z = vertices[:, j]
            if z >= -0.01:  # Only upper hemisphere
                all_x.append(x)
                all_y.append(max(y, 0.0))
                all_z.append(max(z, 0.0))

    return np.array(all_x), np.array(all_y), np.array(all_z)


def _extract_fibonacci_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from Fibonacci grid Voronoi regions.

    Uses per-cell ``voronoi_region`` indices and the
    :class:`~scipy.spatial.SphericalVoronoi` stored on *grid*.
    Falls back to cell centres if Voronoi data is unavailable.
    """
    voronoi = grid.voronoi
    if voronoi is not None and "voronoi_region" in grid.grid.columns:
        all_x, all_y, all_z = [], [], []
        for row in grid.grid.iter_rows(named=True):
            region = row["voronoi_region"]
            if region is None:
                continue
            verts = voronoi.vertices[np.array(region, dtype=int)]
            for v in verts:
                if v[2] >= -0.01:
                    all_x.append(v[0])
                    all_y.append(v[1])
                    all_z.append(max(v[2], 0.0))
        return np.array(all_x), np.array(all_y), np.array(all_z)

    # Fallback: cell centres
    phi_vals = grid.grid["phi"].to_numpy()
    theta_vals = grid.grid["theta"].to_numpy()
    x = np.sin(theta_vals) * np.cos(phi_vals)
    y = np.sin(theta_vals) * np.sin(phi_vals)
    z = np.cos(theta_vals)
    return x, y, z


# ==============================================================================
# Grid → xarray Dataset
# ==============================================================================


def grid_to_dataset(grid: GridData) -> xr.Dataset:
    """Convert a HemiGrid to a unified xarray Dataset with vertices.

    The returned Dataset carries cell centres, NaN-padded vertex arrays,
    vertex counts, and solid angles — all indexed by ``cell_id``.

    Parameters
    ----------
    grid : GridData
        Hemisphere grid instance.

    Returns
    -------
    xr.Dataset
        Dataset with dimensions ``(cell_id, vertex)`` and variables
        ``cell_phi``, ``cell_theta``, ``vertices_phi``, ``vertices_theta``,
        ``n_vertices``, ``solid_angle``.

    Notes
    -----
    This function is distinct from
    :meth:`HemiGridStorageAdapter._prepare_vertices_dataframe` in
    ``canvod-store``. That method produces a long-form DataFrame for zarr
    ragged-array storage; this one produces a rectangular xarray Dataset
    suitable for analysis and visualisation.

    """
    # Reuse the commented-out logic pattern from gnssvodpy vertices.py:
    # extract per-cell vertices into (n_cells, max_vertices) arrays.
    n_cells = grid.ncells
    grid_type = grid.grid_type

    if grid_type in ("equal_area", "equal_angle", "equirectangular"):
        max_v = 4
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 4, dtype=np.int32)

        for i, row in enumerate(grid.grid.iter_rows(named=True)):
            phi_min, phi_max = row["phi_min"], row["phi_max"]
            theta_min, theta_max = row["theta_min"], row["theta_max"]
            vertices_phi[i, :] = [phi_min, phi_max, phi_max, phi_min]
            vertices_theta[i, :] = [theta_min, theta_min, theta_max, theta_max]

    elif grid_type == "htm":
        max_v = 4  # padded to 4 for rectangular layout; only 3 used
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 3, dtype=np.int32)

        for i, row in enumerate(grid.grid.iter_rows(named=True)):
            for j, col in enumerate(["htm_vertex_0", "htm_vertex_1", "htm_vertex_2"]):
                v = np.array(row[col], dtype=float)
                r = np.linalg.norm(v)
                if r == 0:
                    continue
                x, y, z = v / r
                vertices_theta[i, j] = np.arccos(np.clip(z, -1, 1))
                vertices_phi[i, j] = np.mod(np.arctan2(y, x), 2 * np.pi)

    elif grid_type == "geodesic":
        max_v = 3
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 3, dtype=np.int32)

        shared = grid.vertices  # shared vertex array from GridData
        if shared is not None and "geodesic_vertices" in grid.grid.columns:
            shared = np.asarray(shared, dtype=float)
            for i, row in enumerate(grid.grid.iter_rows(named=True)):
                indices = row["geodesic_vertices"]
                for j, v_idx in enumerate(indices):
                    v = shared[int(v_idx)]
                    r = np.linalg.norm(v)
                    if r == 0:
                        continue
                    x, y, z = v / r
                    vertices_theta[i, j] = np.arccos(np.clip(z, -1, 1))
                    vertices_phi[i, j] = np.mod(np.arctan2(y, x), 2 * np.pi)
        else:
            # Fallback: use cell centres as single-point "vertices"
            n_vertices[:] = 1
            vertices_phi[:, 0] = grid.grid["phi"].to_numpy()
            vertices_theta[:, 0] = grid.grid["theta"].to_numpy()

    elif grid_type == "healpix":
        max_v = 4
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 4, dtype=np.int32)

        for i, row in enumerate(grid.grid.iter_rows(named=True)):
            phi_min, phi_max = row["phi_min"], row["phi_max"]
            theta_min, theta_max = row["theta_min"], row["theta_max"]
            vertices_phi[i, :] = [phi_min, phi_max, phi_max, phi_min]
            vertices_theta[i, :] = [theta_min, theta_min, theta_max, theta_max]

    elif grid_type == "fibonacci":
        # Point-based: single vertex per cell (the centre)
        max_v = 1
        vertices_phi = grid.grid["phi"].to_numpy().reshape(n_cells, 1)
        vertices_theta = grid.grid["theta"].to_numpy().reshape(n_cells, 1)
        n_vertices = np.ones(n_cells, dtype=np.int32)

    else:
        raise ValueError(f"Unknown grid type: {grid_type}")

    # Cell centres
    cell_phi = grid.grid["phi"].to_numpy()
    cell_theta = grid.grid["theta"].to_numpy()
    solid_angles = grid.get_solid_angles()

    ds = xr.Dataset(
        {
            "cell_phi": (["cell_id"], cell_phi),
            "cell_theta": (["cell_id"], cell_theta),
            "vertices_phi": (["cell_id", "vertex"], vertices_phi),
            "vertices_theta": (["cell_id", "vertex"], vertices_theta),
            "n_vertices": (["cell_id"], n_vertices),
            "solid_angle": (["cell_id"], solid_angles),
        },
        coords={
            "cell_id": np.arange(n_cells),
            "vertex": np.arange(max_v),
        },
        attrs={
            "grid_type": grid.grid_type,
            "angular_resolution": (
                grid.metadata.get("angular_resolution", 0.0) if grid.metadata else 0.0
            ),
            "cutoff_theta": (
                grid.metadata.get("cutoff_theta", 0.0) if grid.metadata else 0.0
            ),
            "n_cells": n_cells,
        },
    )

    return ds


# ==============================================================================
# Grid storage to Icechunk
# ==============================================================================


def store_grid(
    grid: GridData,
    store: Any,
    grid_name: str,
) -> str:
    """Store grid in unified xarray format to Icechunk store.

    Converts the grid to an xarray Dataset with vertex information
    and writes it to the ``grids/`` group in the store.

    Parameters
    ----------
    grid : GridData
        Hemisphere grid instance to store.
    store
        Icechunk store instance (e.g., MyIcechunkStore).
    grid_name : str
        Grid identifier for storage path (e.g., 'equal_area_4deg').

    Returns
    -------
    str
        Snapshot ID from the commit.

    Examples
    --------
    >>> from canvod.grids import create_hemigrid, store_grid
    >>> grid = create_hemigrid(angular_resolution=4, grid_type='equal_area')
    >>> snapshot_id = store_grid(grid, my_store, 'equal_area_4deg')

    """
    print(f"\nStoring grid '{grid_name}'...")

    # Convert to unified xarray format
    ds_grid = grid_to_dataset(grid)

    # Store in grids/ directory
    group_path = f"grids/{grid_name}"

    with store.writable_session() as session:
        from icechunk.xarray import to_icechunk

        to_icechunk(ds_grid, session, group=group_path, mode="w")
        snapshot_id = session.commit(f"Stored {grid_name} grid structure")

    print(f"  ✓ Stored to '{group_path}'")
    print(f"  ✓ Snapshot: {snapshot_id[:8]}...")
    print(f"  ✓ Cells: {grid.ncells}, Type: {grid.grid_type}")

    return snapshot_id


def load_grid(
    store: Any,
    grid_name: str,
) -> GridData:
    """Load a grid from Icechunk store.

    Loads the grid structure from ``grids/{grid_name}`` and reconstructs
    a GridData object.

    Parameters
    ----------
    store
        Icechunk store instance (e.g., MyIcechunkStore).
    grid_name : str
        Grid identifier (e.g., 'equal_area_4deg').

    Returns
    -------
    GridData
        Reconstructed grid instance.

    Examples
    --------
    >>> from canvod.grids import load_grid
    >>> grid = load_grid(my_store, 'equal_area_4deg')
    >>> print(f"Loaded {grid.ncells} cells")

    """
    import polars as pl

    print(f"\nLoading grid '{grid_name}'...")

    group_path = f"grids/{grid_name}"

    # Load from store
    with store.readonly_session() as session:
        ds_grid = xr.open_zarr(session.store, group=group_path, consolidated=False)

    # Extract metadata
    grid_type = ds_grid.attrs.get("grid_type")
    angular_resolution = ds_grid.attrs.get("angular_resolution", 0.0)
    cutoff_theta = ds_grid.attrs.get("cutoff_theta", np.pi / 2)

    if not grid_type:
        raise ValueError(f"Grid '{grid_name}' missing grid_type attribute")

    # Reconstruct grid DataFrame from cell centers
    cell_phi = ds_grid["cell_phi"].values
    cell_theta = ds_grid["cell_theta"].values
    n_cells = len(cell_phi)

    # Build basic grid DataFrame
    grid_data = {
        "cell_id": np.arange(n_cells),
        "phi": cell_phi,
        "theta": cell_theta,
    }

    # Add grid-type-specific columns
    if grid_type in ("equal_area", "equal_angle", "equirectangular"):
        # Reconstruct boundaries from vertices
        vertices_phi = ds_grid["vertices_phi"].values
        vertices_theta = ds_grid["vertices_theta"].values

        phi_min = vertices_phi[:, 0]  # All 4 vertices are corners
        phi_max = vertices_phi[:, 1]
        theta_min = vertices_theta[:, 0]
        theta_max = vertices_theta[:, 2]

        grid_data.update(
            {
                "phi_min": phi_min,
                "phi_max": phi_max,
                "theta_min": theta_min,
                "theta_max": theta_max,
            }
        )

    elif grid_type == "htm":
        # Reconstruct HTM vertices from spherical to Cartesian
        vertices_phi = ds_grid["vertices_phi"].values
        vertices_theta = ds_grid["vertices_theta"].values

        htm_v0 = []
        htm_v1 = []
        htm_v2 = []

        for i in range(n_cells):
            vertices = []
            for j in range(3):
                phi_v = vertices_phi[i, j]
                theta_v = vertices_theta[i, j]
                x = np.sin(theta_v) * np.cos(phi_v)
                y = np.sin(theta_v) * np.sin(phi_v)
                z = np.cos(theta_v)
                vertices.append([x, y, z])

            htm_v0.append(vertices[0])
            htm_v1.append(vertices[1])
            htm_v2.append(vertices[2])

        grid_data.update(
            {
                "htm_vertex_0": htm_v0,
                "htm_vertex_1": htm_v1,
                "htm_vertex_2": htm_v2,
            }
        )

    # Create Polars DataFrame
    df_grid = pl.DataFrame(grid_data)

    # Reconstruct theta_lims, phi_lims, and cell_ids from grid
    # These are required for GridData but not critical for basic usage
    unique_theta = sorted(df_grid["theta"].unique().to_list())
    theta_lims = np.array(unique_theta)

    # Group cells by theta bin
    phi_lims_list = []
    cell_ids_list = []
    for theta_val in unique_theta:
        theta_cells = df_grid.filter(pl.col("theta") == theta_val)
        phi_vals = sorted(theta_cells["phi"].to_list())
        cell_ids = theta_cells["cell_id"].to_list()

        phi_lims_list.append(np.array(phi_vals))
        cell_ids_list.append(np.array(cell_ids))

    # Create GridData instance
    from canvod.grids.core import GridData

    grid = GridData(
        grid=df_grid,
        theta_lims=theta_lims,
        phi_lims=phi_lims_list,
        cell_ids=cell_ids_list,
        grid_type=grid_type,
        metadata={
            "angular_resolution": angular_resolution,
            "cutoff_theta": cutoff_theta,
        },
    )

    print(f"  ✓ Loaded from '{group_path}'")
    print(f"  ✓ Cells: {grid.ncells}, Type: {grid.grid_type}")

    return grid
