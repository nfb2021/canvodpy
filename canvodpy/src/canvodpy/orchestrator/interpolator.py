"""Interpolation strategies for auxiliary datasets."""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

import numpy as np
import xarray as xr
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from scipy.interpolate import CubicHermiteSpline, interp1d

MIN_SEGMENT_LEN = 2


class InterpolatorConfig:
    """Base class for interpolator configuration."""

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for attrs storage."""
        return asdict(self)  # ty: ignore[invalid-argument-type]


@dataclass
class Sp3Config(InterpolatorConfig):
    """Configuration for SP3 interpolation.

    Notes
    -----
    This is a Pydantic dataclass used for validation.

    """

    use_velocities: bool = True
    fallback_method: str = "linear"


@dataclass
class ClockConfig(InterpolatorConfig):
    """Configuration for clock interpolation.

    Notes
    -----
    This is a Pydantic dataclass used for validation.

    """

    window_size: int = 9
    jump_threshold: float = 1e-6


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Interpolator(ABC):
    """Abstract base class for interpolation strategies.

    Notes
    -----
    This is a Pydantic dataclass and an abstract base class (ABC).

    """

    config: InterpolatorConfig

    @abstractmethod
    def interpolate(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        """Interpolate dataset to match target epochs."""

    def to_attrs(self) -> dict[str, Any]:
        """Convert interpolator to attrs-compatible dictionary."""
        return {
            "interpolator_type": self.__class__.__name__,
            "config": self.config.to_dict(),
        }


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ClockInterpolationStrategy(Interpolator):
    """Optimized interpolation strategy for clock files using pure numpy.

    Notes
    -----
    This is a Pydantic dataclass.

    """

    config: ClockConfig

    def interpolate(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        """Optimized clock interpolation using vectorized operations."""
        result_ds = xr.Dataset(coords={"epoch": target_epochs, "sid": ds["sid"]})

        # Convert epochs to seconds once
        t_source = (
            (
                ds["epoch"] - ds["epoch"].values[0]  # ← Fix: .values[0] instead of [0]
            )
            .values.astype("timedelta64[s]")
            .astype(float)
        )

        t_target = (
            (
                target_epochs
                - ds["epoch"].values[0]  # ← Fix: .values[0] instead of [0]
            )
            .astype("timedelta64[s]")
            .astype(float)
        )

        # Find clock variables
        clock_vars = [
            var
            for var in ds.data_vars
            if any(
                c in str(var) for c in ["clock", "clk", "Clock", "CLK", "clock_offset"]
            )
        ]

        if not clock_vars:
            msg = "No clock variables found in dataset"
            raise ValueError(msg)

        # Process each clock variable
        for var in clock_vars:
            data = ds[var].values
            output = np.full((len(target_epochs), len(ds["sid"])), np.nan)

            # Process each sv in parallel
            with ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(
                        self._interpolate_sv_clock,
                        data[:, sv_idx],
                        t_source,
                        t_target,
                        self.config.jump_threshold,
                    )
                    for sv_idx in range(len(ds["sid"]))
                ]

                # Collect results
                for sv_idx, future in enumerate(futures):
                    output[:, sv_idx] = future.result()

            result_ds[var] = (("epoch", "sid"), output)
            if var in ds:
                result_ds[var].attrs = ds[var].attrs

        return result_ds

    def _interpolate_sv_clock(
        self,
        data: np.ndarray,
        t_source: np.ndarray,
        t_target: np.ndarray,
        threshold: float,
    ) -> np.ndarray:
        """Interpolate clock data for a single sv using vectorized operations."""
        output = np.full_like(t_target, np.nan)

        # Skip if all data is NaN
        if np.all(np.isnan(data)):
            return output

        # Find valid data points
        valid_mask = ~np.isnan(data)
        if not np.any(valid_mask):
            return output

        # Get valid data and time points
        valid_data = data[valid_mask]
        valid_time = t_source[valid_mask]

        # Find discontinuities
        jumps = np.where(np.abs(np.diff(valid_data)) > threshold)[0]
        segments = np.split(np.arange(len(valid_time)), jumps + 1)

        for seg in segments:
            if len(seg) < MIN_SEGMENT_LEN:
                continue

            seg_time = valid_time[seg]
            seg_data = valid_data[seg]

            # Find target points in this segment
            mask = (t_target >= seg_time[0]) & (t_target <= seg_time[-1])
            if not np.any(mask):
                continue

            # Use linear interpolation within segment
            interpolator = interp1d(
                seg_time, seg_data, bounds_error=False, fill_value=np.nan
            )
            output[mask] = interpolator(t_target[mask])

        return output


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Sp3InterpolationStrategy(Interpolator):
    """Optimized interpolation strategy for SP3 orbit files.

    Notes
    -----
    This is a Pydantic dataclass.

    """

    config: Sp3Config

    def interpolate(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        """Optimized SP3 orbit interpolation."""
        if self.config.use_velocities and all(v in ds for v in ["Vx", "Vy", "Vz"]):
            return self._interpolate_with_velocities(ds, target_epochs)
        return self._interpolate_positions_only(ds, target_epochs)

    def _interpolate_with_velocities(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        """Optimized Hermite interpolation using vectorized operations."""
        result_ds = xr.Dataset(coords={"epoch": target_epochs, "sid": ds["sid"]})

        # Convert epochs to seconds once
        t_source = (
            (
                ds["epoch"] - ds["epoch"].values[0]  # ← Fix: .values[0] instead of [0]
            )
            .values.astype("timedelta64[s]")
            .astype(float)
        )

        t_target = (
            (
                target_epochs
                - ds["epoch"].values[0]  # ← Fix: .values[0] instead of [0]
            )
            .astype("timedelta64[s]")
            .astype(float)
        )

        # Pre-allocate all arrays at once
        n_targets = len(target_epochs)
        n_svs = len(ds["sid"])
        coords = {
            "X": np.empty((n_targets, n_svs)),
            "Y": np.empty((n_targets, n_svs)),
            "Z": np.empty((n_targets, n_svs)),
        }

        if all(v in ds for v in ["Vx", "Vy", "Vz"]):
            vels = {
                "Vx": np.empty((n_targets, n_svs)),
                "Vy": np.empty((n_targets, n_svs)),
                "Vz": np.empty((n_targets, n_svs)),
            }

        # Process each sv in parallel
        with ThreadPoolExecutor() as executor:
            futures = []
            for i, sv in enumerate(ds["sid"].values):
                futures.append(
                    executor.submit(
                        self._interpolate_sv,
                        ds,
                        sv,
                        t_source,
                        t_target,
                        i,
                        coords,
                        vels if "Vx" in ds else None,
                    )
                )

            # Wait for all interpolations to complete
            for future in futures:
                future.result()

        # Assign all results at once
        for coord, data in coords.items():
            result_ds[coord] = (("epoch", "sid"), data)
            if coord in ds:
                result_ds[coord].attrs = ds[coord].attrs

        if all(v in ds for v in ["Vx", "Vy", "Vz"]):
            for vel, data in vels.items():
                result_ds[vel] = (("epoch", "sid"), data)
                if vel in ds:
                    result_ds[vel].attrs = ds[vel].attrs

        return result_ds

    def _interpolate_sv(
        self,
        ds: xr.Dataset,
        sv: str,
        t_source: np.ndarray,
        t_target: np.ndarray,
        idx: int,
        coords: dict[str, np.ndarray],
        vels: dict[str, np.ndarray] | None,
    ) -> None:
        """Interpolate a single satellite's data."""
        for coord, vel in [("X", "Vx"), ("Y", "Vy"), ("Z", "Vz")]:
            pos = ds[coord].sel(sid=sv).values

            # Skip if pos is all-NaN. coords[coord][:, idx] / vels[vel][:, idx]
            # were allocated with np.empty() (uninitialized memory, not
            # zeros/NaN) by the caller -- without these explicit NaN
            # writes, a skipped satellite's entire column silently keeps
            # whatever garbage was already in that memory, which then gets
            # fed into compute_spherical_coordinates() as if it were a
            # real ECEF position. Matches the canonical, correct handling
            # in canvod.auxiliary.interpolation.interpolator.
            if not np.isfinite(pos).any():
                coords[coord][:, idx] = np.nan
                if vels is not None:
                    vels[vel][:, idx] = np.nan
                continue

            if vels is not None:
                vel_data = ds[vel].sel(sid=sv).values

                # Also skip if velocities are NaN
                if not np.isfinite(vel_data).any():
                    coords[coord][:, idx] = np.nan
                    vels[vel][:, idx] = np.nan
                    continue

                interpolator = CubicHermiteSpline(t_source, pos, vel_data)
                coords[coord][:, idx] = interpolator(t_target)
                vels[vel][:, idx] = interpolator.derivative()(t_target)
            else:
                interpolator = interp1d(
                    t_source,
                    pos,
                    bounds_error=False,
                    fill_value="extrapolate",
                )
                coords[coord][:, idx] = interpolator(t_target)

    def _interpolate_positions_only(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        """Perform simple linear interpolation for positions only."""
        return ds.interp(
            epoch=target_epochs,
            method=self.config.fallback_method,  # ty: ignore[invalid-argument-type]
        )


# Example of recreating interpolator from attrs:
def create_interpolator_from_attrs(attrs: dict[str, Any]) -> Interpolator:
    """Recreate interpolator instance from dataset attributes."""
    interpolator_type = attrs["interpolator_config"]["interpolator_type"]
    config_dict = attrs["interpolator_config"]["config"]

    if interpolator_type == "Sp3InterpolationStrategy":
        config = Sp3Config(**config_dict)
        return Sp3InterpolationStrategy(config=config)
    if interpolator_type == "ClockInterpolationStrategy":
        config = ClockConfig(**config_dict)
        return ClockInterpolationStrategy(config=config)
    msg = f"Unknown interpolator type: {interpolator_type}"
    raise ValueError(msg)
