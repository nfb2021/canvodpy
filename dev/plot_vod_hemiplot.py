"""Side-by-side VOD hemisphere plots for both antennas, same date window.

Loads the per-cell (cell, time) NetCDF outputs from
`compute_galileo_vod_timeseries.py`, collapses each cell's values over a
given date window (median across time, same statistic used everywhere else
in this analysis), and renders each antenna with canvod-viz's
`HemisphereVisualizer2D` — proper filled grid-cell patches on a polar axis
(radius = sin(theta) for an equal-area-preserving projection, angle =
compass azimuth phi, 0 = North, clockwise), both antennas on a shared color
scale so they're visually comparable.

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

from canvod.grids import create_hemigrid
from canvod.viz import HemisphereVisualizer2D, PolarPlotStyle


def cell_window_stat(
    path: Path, start: str, end: str, ncells: int
) -> tuple[np.ndarray, int]:
    """Median VOD per cell over [start, end], as a length-ncells array indexed by cell_id."""
    ds = xr.open_dataset(path)
    window = ds["cell_timeseries"].sel(time=slice(start, end))
    n_days = window.sizes["time"]
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        values = np.nanmedian(window.values, axis=1)

    # HemisphereVisualizer2D indexes `data` positionally by the grid's own
    # row order, which is what cell_id encodes -- place each value at its
    # cell_id position rather than assuming the nc file's cell dim is
    # already in that exact order.
    cell_ids = ds["cell"].values.astype(int)
    full = np.full(ncells, np.nan)
    full[cell_ids] = values
    return full, n_days


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
        "--resolution",
        type=float,
        default=2.0,
        help="Grid resolution (deg) -- must match what compute_galileo_vod_timeseries.py used",
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
        "--show", action="store_true", help="Also display the plot interactively"
    )
    args = parser.parse_args()

    grid = create_hemigrid("equal_area", angular_resolution=args.resolution)

    panels = []
    all_values = []
    for path, label in [(args.lower, "Lower antenna"), (args.upper, "Upper antenna")]:
        values, n_days = cell_window_stat(path, args.start, args.end, grid.ncells)
        n_valid = int(np.isfinite(values).sum())
        print(f"{label}: {n_valid} / {grid.ncells} cells have data over {n_days} days")
        panels.append((label, values))
        all_values.append(values[np.isfinite(values)])

    all_values = np.concatenate(all_values) if any(len(v) for v in all_values) else None
    if all_values is None or len(all_values) == 0:
        raise SystemExit(
            f"No valid VOD data in either antenna for {args.start} to {args.end}."
        )
    vmin, vmax = float(all_values.min()), float(all_values.max())

    fig, axes = plt.subplots(
        1, 2, figsize=(13, 6.5), subplot_kw={"projection": "polar"}
    )

    for ax, (label, values) in zip(axes, panels, strict=True):
        viz = HemisphereVisualizer2D(grid)
        style = PolarPlotStyle(
            title=label,
            cmap="viridis",
            vmin=vmin,
            vmax=vmax,
            edgecolor="none",
            colorbar_label="VOD (median)",
        )
        viz.plot_grid_patches(data=values, style=style, ax=ax)

    fig.suptitle(f"Galileo VOD hemisphere — {args.start} to {args.end}", y=1.02)
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
