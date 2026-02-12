"""Equirectangular grid implementation."""

import numpy as np
import polars as pl
from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class EquirectangularBuilder(BaseGridBuilder):
    """Simple rectangular grid in (theta, phi) space.

    The hemisphere is divided into a regular rectangular array: a constant
    number of theta bands, each containing the same constant number of phi
    sectors.  Every cell is an identical rectangle in angular coordinates.
    This is *structurally* identical to ``EqualAngleBuilder`` except for one
    difference in the zenith treatment: ``EqualAngleBuilder`` collapses the
    first band into a single zenith cap, while this builder does not — every
    band has the same number of sectors.

    Because solid angle depends on cos(theta), cells near the zenith subtend
    *more* solid angle than cells near the horizon.  This makes the grid
    biased toward the zenith for any solid-angle-weighted statistic.
    **Not recommended for scientific analysis** – use ``EqualAreaBuilder``
    instead.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle from zenith (0 = straight up,
      π/2 = horizon)

    What ``angular_resolution`` means
    ----------------------------------
    ``angular_resolution`` (degrees) is used as **both** the theta-band width
    *and* the phi-sector width.  The grid is therefore square in angular
    coordinates::

        n_theta = round((π/2 − cutoff) / Δθ)
        n_phi   = round(2π / Δθ)
        total cells = n_theta × n_phi

    Mathematical construction
    -------------------------
    1. Theta edges are placed at ``cutoff_theta``, ``cutoff_theta + Δθ``,
       ``cutoff_theta + 2Δθ``, … up to π/2.
    2. Phi edges are placed at 0, Δθ, 2Δθ, … up to 2π.
    3. Every (theta_band, phi_sector) combination produces one cell.  The
       cell centre is the midpoint of the rectangle.
    4. No special zenith cap is created; the band nearest the zenith has
       the same number of phi sectors as all other bands.

    Parameters
    ----------
    angular_resolution : float
        Angular spacing in degrees, applied identically in both theta and phi.
    cutoff_theta : float
        Elevation mask angle in degrees.  Bands whose *inner* edge is at or
        below ``π/2 − cutoff_theta`` are omitted.
    phi_rotation : float
        Rigid azimuthal rotation applied after construction, in degrees.

    """

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"equirectangular"``

        """
        return GridType.EQUIRECTANGULAR.value

    def _build_grid(
        self,
    ) -> tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]:
        """Construct the equirectangular hemisphere grid.

        Returns
        -------
        grid : pl.DataFrame
            One row per cell with columns: phi, theta, phi_min, phi_max,
            theta_min, theta_max, cell_id.
        theta_lims : np.ndarray
            Inner theta edge of each band (radians).
        phi_lims : list[np.ndarray]
            Array of phi_min values for each band (identical across bands).
        cell_ids : list[np.ndarray]
            Cell-id arrays, one per band.

        """
        max_theta = np.pi / 2

        theta_edges = np.arange(
            self.cutoff_theta_rad,
            max_theta + self.angular_resolution_rad,
            self.angular_resolution_rad,
        )
        phi_edges = np.arange(
            0, 2 * np.pi + self.angular_resolution_rad, self.angular_resolution_rad
        )

        cells = []

        for i in range(len(theta_edges) - 1):
            theta_min, theta_max = theta_edges[i], theta_edges[i + 1]

            for j in range(len(phi_edges) - 1):
                phi_min, phi_max = phi_edges[j], phi_edges[j + 1]

                cells.append(
                    {
                        "phi": (phi_min + phi_max) / 2,
                        "theta": (theta_min + theta_max) / 2,
                        "phi_min": phi_min,
                        "phi_max": min(2 * np.pi, phi_max),
                        "theta_min": theta_min,
                        "theta_max": theta_max,
                    }
                )

        grid = pl.DataFrame(cells).with_columns(
            pl.int_range(0, pl.len()).alias("cell_id")
        )

        theta_lims = theta_edges[:-1]
        phi_lims = [phi_edges[:-1] for _ in range(len(theta_edges) - 1)]
        cell_ids_list = [
            np.arange(i * (len(phi_edges) - 1), (i + 1) * (len(phi_edges) - 1))
            for i in range(len(theta_edges) - 1)
        ]

        return grid, theta_lims, phi_lims, cell_ids_list
