"""Side-by-side VOD hemisphere plots for both antennas, same date window.

Loads the per-cell (cell, time) NetCDF outputs from
`compute_galileo_vod_timeseries.py`, collapses each cell's values over a
given date window (median across time, same statistic used everywhere else
in this analysis), and plots each antenna as a polar "sky view" — radius is
zenith angle theta (0 = overhead at center, ~90 deg = horizon at the rim),
angle is compass azimuth phi (0 = North, clockwise) — with both antennas on
a shared color scale so they're visually comparable.

Usage
-----
    uv run python dev/plot_vod_hemiplot.py \\
        --lower dev/output/VOD_lower_antenna_2deg_median.nc \\
        --upper dev/output/VOD_upper_antenna_2deg_median.nc \\
        --start 2025-08-18 --end 2025-08-31 \\
        --output dev/output/galileo_vod_hemiplot_august.png
"""

import argparse
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


def cell_window_stat(
    path: Path, start: str, end: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Median VOD per cell over [start, end], plus each cell's phi/theta (degrees)."""
    ds = xr.open_dataset(path)
    window = ds["cell_timeseries"].sel(time=slice(start, end))
    n_days = window.sizes["time"]
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        values = np.nanmedian(window.values, axis=1)
    return values, ds["cell_phi"].values, ds["cell_theta"].values, n_days


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lower",
        type=Path,
        default=Path("dev/output/VOD_lower_antenna_2deg_median.nc"),
        help="Lower-antenna per-cell dataset",
    )
    parser.add_argument(
        "--upper",
        type=Path,
        default=Path("dev/output/VOD_upper_antenna_2deg_median.nc"),
        help="Upper-antenna per-cell dataset",
    )
    parser.add_argument(
        "--start", default="2025-08-18", help="Window start date (inclusive)"
    )
    parser.add_argument(
        "--end", default="2025-08-31", help="Window end date (inclusive)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dev/output/galileo_vod_hemiplot.png"),
        help="Output image path",
    )
    parser.add_argument(
        "--point-size", type=float, default=40, help="Marker size for each grid cell"
    )
    parser.add_argument(
        "--show", action="store_true", help="Also display the plot interactively"
    )
    args = parser.parse_args()

    panels = []
    all_values = []
    for path, label in [(args.lower, "Lower antenna"), (args.upper, "Upper antenna")]:
        values, phi_deg, theta_deg, n_days = cell_window_stat(
            path, args.start, args.end
        )
        n_valid = int(np.isfinite(values).sum())
        print(f"{label}: {n_valid} / {len(values)} cells have data over {n_days} days")
        panels.append((label, values, phi_deg, theta_deg))
        all_values.append(values[np.isfinite(values)])

    all_values = (
        np.concatenate(all_values)
        if any(len(v) for v in all_values)
        else np.array([0.0, 1.0])
    )
    if len(all_values) == 0:
        raise SystemExit(
            f"No valid VOD data in either antenna for {args.start} to {args.end}."
        )
    vmin, vmax = float(all_values.min()), float(all_values.max())

    fig, axes = plt.subplots(
        1, 2, figsize=(11, 5.5), subplot_kw={"projection": "polar"}
    )

    scatter = None
    for ax, (label, values, phi_deg, theta_deg) in zip(axes, panels, strict=True):
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_rlim(0, 90)
        ax.set_rticks([30, 60, 90])
        ax.set_title(label)

        phi_rad = np.deg2rad(phi_deg)
        scatter = ax.scatter(
            phi_rad,
            theta_deg,
            c=values,
            s=args.point_size,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            edgecolors="none",
        )

    fig.colorbar(
        scatter, ax=axes, orientation="vertical", shrink=0.8, label="VOD (median)"
    )
    fig.suptitle(f"Galileo VOD hemisphere — {args.start} to {args.end}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    print(f"Saved to {args.output}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
