"""Spatial (per-cell) map of the drought residual — where in the sky is the stress?

Extends `plot_galileo_vod_drought_diff.py`'s regression approach spatially.
That script collapses to one global daily number per antenna, fits
`stressed ~= slope * reference + intercept` via Theil-Sen across the whole
record, and looks at the residual over time. This script uses the SAME
global fit (one slope/intercept, not per-cell -- fit once from the daily
global series so it reflects the overall relationship, not overfit to any
one cell's noise), but does NOT collapse across cells before computing the
residual. Instead:

    predicted_cell(t) = slope * reference_cell(t) + intercept
    residual_cell(t)  = stressed_cell(t) - predicted_cell(t)

then aggregates residual_cell(t) over a date window (median across time,
per cell) to get one spatial map. Negative = that look direction reads
below what the reference antenna's overall relationship predicts -- i.e.
localized drought signal. If stress is uniform across the whole canopy,
this map should look uniform; if it's concentrated in specific sky
directions (e.g. a damaged/exposed branch), it'll show up as spatial
structure here that a single collapsed daily number can't reveal.

Usage
-----
    uv run python dev/plot_vod_residual_hemiplot.py \\
        --reference dev/output/VOD_lower_antenna_2deg_median.nc \\
        --stressed dev/output/VOD_upper_antenna_2deg_median.nc \\
        --start 2026-01-01 --end 2026-04-30 \\
        --output dev/output/galileo_vod_residual_hemiplot.png
"""

import argparse
import warnings
from pathlib import Path

import numpy as np
import xarray as xr
from plot_galileo_vod_comparison import global_daily_series
from scipy.stats import theilslopes

from canvod.grids import create_hemigrid
from canvod.viz import HemisphereVisualizer2D, PolarPlotStyle


def fit_global_relationship(
    reference_path: Path, stressed_path: Path
) -> tuple[float, float]:
    """Theil-Sen fit of stressed ~= slope * reference + intercept, whole record."""
    reference = global_daily_series(reference_path)
    stressed = global_daily_series(stressed_path)
    aligned = reference.to_frame("reference").join(
        stressed.to_frame("stressed"), how="inner"
    )
    aligned = aligned.dropna()
    slope, intercept, lo, hi = theilslopes(
        aligned["stressed"].to_numpy(), aligned["reference"].to_numpy()
    )
    print(
        f"Global fit: stressed = {slope:.4f} * reference + {intercept:.4f} "
        f"(slope 95% CI: [{lo:.4f}, {hi:.4f}])"
    )
    return slope, intercept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("dev/output/VOD_lower_antenna_2deg_median.nc"),
        help="Undisturbed reference antenna's per-cell dataset",
    )
    parser.add_argument(
        "--stressed",
        type=Path,
        default=Path("dev/output/VOD_upper_antenna_2deg_median.nc"),
        help="Drought-subjected antenna's per-cell dataset",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=2.0,
        help="Grid resolution (deg) -- must match what compute_galileo_vod_timeseries.py used",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Window start date (inclusive); default = whole record",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Window end date (inclusive); default = whole record",
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=5,
        help="Minimum overlapping valid days per cell to include it in the map",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dev/output/galileo_vod_residual_hemiplot.png"),
        help="Output image path",
    )
    parser.add_argument(
        "--show", action="store_true", help="Also display the plot interactively"
    )
    args = parser.parse_args()

    slope, intercept = fit_global_relationship(args.reference, args.stressed)

    ref_ds = xr.open_dataset(args.reference)
    stressed_ds = xr.open_dataset(args.stressed)

    ref_da, stressed_da = xr.align(
        ref_ds["cell_timeseries"], stressed_ds["cell_timeseries"], join="inner"
    )

    if args.start is not None or args.end is not None:
        ref_da = ref_da.sel(time=slice(args.start, args.end))
        stressed_da = stressed_da.sel(time=slice(args.start, args.end))
    n_days = ref_da.sizes["time"]
    print(
        f"Window: {ref_da.time.values[0]} to {ref_da.time.values[-1]} ({n_days} days)"
    )

    predicted = slope * ref_da + intercept
    residual = stressed_da - predicted  # (cell, time)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        residual_map = np.nanmedian(residual.values, axis=1)
        valid_days_per_cell = np.isfinite(residual.values).sum(axis=1)

    residual_map = np.where(valid_days_per_cell >= args.min_days, residual_map, np.nan)
    n_valid_cells = int(np.isfinite(residual_map).sum())
    print(
        f"{n_valid_cells} / {len(residual_map)} cells have >= {args.min_days} "
        f"overlapping valid days and are shown."
    )

    cell_ids = ref_da["cell"].values.astype(int)
    grid = create_hemigrid("equal_area", angular_resolution=args.resolution)
    full = np.full(grid.ncells, np.nan)
    full[cell_ids] = residual_map

    finite = full[np.isfinite(full)]
    if len(finite) == 0:
        raise SystemExit("No cells have enough valid overlapping days to plot.")
    abs_max = float(np.abs(finite).max())

    viz = HemisphereVisualizer2D(grid)
    style = PolarPlotStyle(
        title=(
            f"Residual VOD (stressed − predicted), median over "
            f"{args.start or 'record start'} to {args.end or 'record end'}"
        ),
        cmap="RdBu",
        vmin=-abs_max,
        vmax=abs_max,
        edgecolor="none",
        colorbar_label="Residual VOD (negative = more stressed than predicted)",
        figsize=(9, 9),
    )
    fig, _ax = viz.plot_grid_patches(data=full, style=style)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")

    if args.show:
        import matplotlib.pyplot as plt

        plt.show()


if __name__ == "__main__":
    main()
