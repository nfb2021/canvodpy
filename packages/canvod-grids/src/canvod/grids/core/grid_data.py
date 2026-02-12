"""Grid data container for hemisphere grids."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from matplotlib.patches import Rectangle


@dataclass(frozen=True)
class GridData:
    """Immutable container for hemispherical grid structure.

    Parameters
    ----------
    grid : pl.DataFrame
        Grid cells with phi, theta, and bounds
    theta_lims : np.ndarray
        Theta band limits
    phi_lims : list[np.ndarray]
        Phi limits per theta band
    cell_ids : list[np.ndarray]
        Cell IDs per theta band
    grid_type : str
        Grid type identifier
    solid_angles : np.ndarray, optional
        Solid angles per cell [steradians]
    metadata : dict, optional
        Additional grid metadata
    voronoi : Any, optional
        Voronoi tessellation object (for Fibonacci grids)
    vertices : np.ndarray, optional
        3D vertices (for triangular grids)
    points_xyz : np.ndarray, optional
        3D point cloud (for Fibonacci grids)
    vertex_phi : np.ndarray, optional
        Vertex phi coordinates
    vertex_theta : np.ndarray, optional
        Vertex theta coordinates

    """

    grid: pl.DataFrame
    theta_lims: np.ndarray
    phi_lims: list[np.ndarray]
    cell_ids: list[np.ndarray]
    grid_type: str
    solid_angles: np.ndarray | None = None
    metadata: dict | None = None
    voronoi: Any | None = None
    vertices: np.ndarray | None = None
    points_xyz: np.ndarray | None = None
    vertex_phi: np.ndarray | None = None
    vertex_theta: np.ndarray | None = None

    @property
    def coords(self) -> pl.DataFrame:
        """Get cell coordinates."""
        return self.grid.select(["phi", "theta"])

    @property
    def ncells(self) -> int:
        """Number of cells in grid."""
        return len(self.grid)

    def get_patches(self) -> pl.Series:
        """Create matplotlib patches for polar visualization."""
        patches = [
            Rectangle(
                (row["phi_min"], row["theta_min"]),
                row["phi_max"] - row["phi_min"],
                row["theta_max"] - row["theta_min"],
                fill=True,
            )
            for row in self.grid.iter_rows(named=True)
        ]
        return pl.Series("Patches", patches)

    def get_solid_angles(self) -> np.ndarray:
        """Calculate solid angle for each cell [steradians]."""
        if self.solid_angles is not None:
            return self.solid_angles

        # HEALPix
        if self.grid_type == "healpix" and "healpix_nside" in self.grid.columns:
            try:
                import healpy as hp

                nside = int(self.grid["healpix_nside"][0])
                return np.full(
                    len(self.grid), hp.nside2pixarea(nside), dtype=np.float64
                )
            except ImportError:
                pass

        # Geodesic
        if self.grid_type == "geodesic" and "geodesic_vertices" in self.grid.columns:
            return self._compute_geodesic_solid_angles()

        # HTM
        if self.grid_type == "htm" and "htm_vertex_0" in self.grid.columns:
            return self._compute_htm_solid_angles()

        # Fibonacci
        if self.grid_type == "fibonacci" and "voronoi_region" in self.grid.columns:
            return self._compute_voronoi_solid_angles()

        # Default
        return self._geometric_solid_angles()

    def _compute_htm_solid_angles(self) -> np.ndarray:
        """Compute solid angles for HTM triangular cells."""
        solid_angles = []

        for row in self.grid.iter_rows(named=True):
            v0 = np.array(row["htm_vertex_0"])
            v1 = np.array(row["htm_vertex_1"])
            v2 = np.array(row["htm_vertex_2"])

            # Spherical excess formula
            a = np.arccos(np.clip(np.dot(v1, v2), -1, 1))
            b = np.arccos(np.clip(np.dot(v0, v2), -1, 1))
            c = np.arccos(np.clip(np.dot(v0, v1), -1, 1))

            s = (a + b + c) / 2
            tan_E_4 = np.sqrt(
                np.tan(s / 2)
                * np.tan((s - a) / 2)
                * np.tan((s - b) / 2)
                * np.tan((s - c) / 2)
            )
            E = 4 * np.arctan(tan_E_4)

            solid_angles.append(E)

        return np.array(solid_angles)

    def _compute_geodesic_solid_angles(self) -> np.ndarray:
        """Compute solid angles for geodesic triangular cells."""
        vertices = self.vertices
        if vertices is None:
            return self._geometric_solid_angles()

        solid_angles = []
        for row in self.grid.iter_rows(named=True):
            v_indices = row["geodesic_vertices"]
            v0, v1, v2 = vertices[v_indices]

            a = np.arccos(np.clip(np.dot(v1, v2), -1, 1))
            b = np.arccos(np.clip(np.dot(v0, v2), -1, 1))
            c = np.arccos(np.clip(np.dot(v0, v1), -1, 1))

            s = (a + b + c) / 2
            tan_E_4 = np.sqrt(
                np.tan(s / 2)
                * np.tan((s - a) / 2)
                * np.tan((s - b) / 2)
                * np.tan((s - c) / 2)
            )
            E = 4 * np.arctan(tan_E_4)

            solid_angles.append(E)

        return np.array(solid_angles)

    def _compute_voronoi_solid_angles(self) -> np.ndarray:
        """Compute solid angles for Voronoi cells."""
        if self.voronoi is None:
            return self._geometric_solid_angles()

        sv = self.voronoi
        solid_angles = []
        for row in self.grid.iter_rows(named=True):
            region = row["voronoi_region"]
            if len(region) < 3:
                solid_angles.append(np.nan)
                continue

            vertices = sv.vertices[region]
            center = np.array(
                [
                    np.sin(row["theta"]) * np.cos(row["phi"]),
                    np.sin(row["theta"]) * np.sin(row["phi"]),
                    np.cos(row["theta"]),
                ]
            )

            total_angle = 0
            n = len(vertices)
            for i in range(n):
                v1 = vertices[i]
                v2 = vertices[(i + 1) % n]
                a = np.arccos(np.clip(np.dot(center, v1), -1, 1))
                b = np.arccos(np.clip(np.dot(center, v2), -1, 1))
                c = np.arccos(np.clip(np.dot(v1, v2), -1, 1))
                s = (a + b + c) / 2
                tan_E_4 = np.sqrt(
                    np.tan(s / 2)
                    * np.tan((s - a) / 2)
                    * np.tan((s - b) / 2)
                    * np.tan((s - c) / 2)
                )
                E = 4 * np.arctan(tan_E_4)
                total_angle += E
            solid_angles.append(total_angle)

        return np.array(solid_angles)

    def _geometric_solid_angles(self) -> np.ndarray:
        """Fallback geometric calculation."""
        solid_angles = []
        for row in self.grid.iter_rows(named=True):
            delta_phi = row["phi_max"] - row["phi_min"]
            cos_diff = np.cos(row["theta_min"]) - np.cos(row["theta_max"])
            omega = delta_phi * cos_diff
            solid_angles.append(omega)
        return np.array(solid_angles)

    def get_grid_stats(self) -> dict:
        """Get grid statistics including solid angle uniformity."""
        solid_angles = self.get_solid_angles()

        stats = {
            "total_cells": self.ncells,
            "grid_type": self.grid_type,
            "theta_bands": len(self.theta_lims),
            "cells_per_band": [len(ids) for ids in self.cell_ids],
            "solid_angle_mean_sr": float(np.mean(solid_angles)),
            "solid_angle_std_sr": float(np.std(solid_angles)),
            "solid_angle_cv_percent": float(
                np.std(solid_angles) / np.mean(solid_angles) * 100
            ),
            "total_solid_angle_sr": float(np.sum(solid_angles)),
            "hemisphere_solid_angle_sr": 2 * np.pi,
        }

        # Add HEALPix-specific info
        if self.grid_type == "healpix" and "healpix_nside" in self.grid.columns:
            try:
                import healpy as hp

                nside = int(self.grid["healpix_nside"][0])
                stats["healpix_nside"] = nside
                stats["healpix_npix_total"] = hp.nside2npix(nside)
                stats["healpix_pixel_area_sr"] = hp.nside2pixarea(nside)
                stats["healpix_resolution_arcmin"] = hp.nside2resol(nside, arcmin=True)
            except ImportError:
                pass

        return stats
