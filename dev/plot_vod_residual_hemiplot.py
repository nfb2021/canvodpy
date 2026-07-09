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

then aggregates residual_cell(t) over a date window per cell to get one
spatial map. Two aggregation statistics are available (--stat):

  median : central tendency of the residual. Negative = that look direction
           reads below what the reference antenna's overall relationship
           predicts -- a *static* localized bias if it looks the same in
           every date window (checked empirically: it does, on real data --
           see the module-level note in the fitted-parameters section of
           dev/drought_diff_methodology.md).
  std    : how much the residual *varies* over time in that cell, regardless
           of its average level. High std = a look direction whose
           departure from the predicted relationship swings around a lot
           over the season -- a different, complementary question from
           "which direction is biased" (median): "which direction changes
           the most over time." Since drought stress is a temporal
           phenomenon, cells with high residual std are better candidates
           for genuinely time-varying (season/drought-driven) behavior than
           cells that are merely offset by a constant amount.

Usage
-----
    uv run python dev/plot_vod_residual_hemiplot.py \\
        --reference dev/output/VOD_lower_antenna_2deg_median.nc \\
        --stressed dev/output/VOD_upper_antenna_2deg_median.nc \\
        --stat std \\
        --output dev/output/galileo_vod_residual_std_hemiplot.png
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
    reference_path: Path,
    stressed_path: Path,
    start: str | None = None,
    end: str | None = None,
) -> tuple[float, float]:
    """Theil-Sen fit of stressed ~= slope * reference + intercept.

    Restricted to [start, end] if given -- the fit and the residual it feeds
    should use the SAME window, otherwise "predicted" reflects a relationship
    from outside the period being analyzed.
    """
    reference = global_daily_series(reference_path)
    stressed = global_daily_series(stressed_path)
    aligned = reference.to_frame("reference").join(
        stressed.to_frame("stressed"), how="inner"
    )
    if start is not None or end is not None:
        aligned = aligned.loc[start:end]
    aligned = aligned.dropna()
    slope, intercept, lo, hi = theilslopes(
        aligned["stressed"].to_numpy(), aligned["reference"].to_numpy()
    )
    print(
        f"Global fit ({len(aligned)} days, {start or 'record start'} to "
        f"{end or 'record end'}): stressed = {slope:.4f} * reference + "
        f"{intercept:.4f} (slope 95% CI: [{lo:.4f}, {hi:.4f}])"
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
        default="2025-06-01",
        help=(
            "Window start date (inclusive), used for BOTH the fit and the "
            "residual. Defaults to the vegetated season (the drought "
            "experiment isn't active in winter dormancy, and the bias "
            "relationship itself isn't seasonally constant -- see "
            "dev/drought_diff_methodology.md). Pass an empty string for the "
            "whole record instead."
        ),
    )
    parser.add_argument(
        "--end",
        default="2025-08-31",
        help=(
            "Window end date (inclusive) -- see --start. Pass an empty "
            "string for the whole record instead."
        ),
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=5,
        help="Minimum overlapping valid days per cell to include it in the map",
    )
    parser.add_argument(
        "--stat",
        choices=["median", "std"],
        default="median",
        help="Per-cell aggregation over time: 'median' (bias) or 'std' (variability)",
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
    args.start = args.start or None
    args.end = args.end or None

    slope, intercept = fit_global_relationship(
        args.reference, args.stressed, args.start, args.end
    )

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

    min_days = max(args.min_days, 2) if args.stat == "std" else args.min_days
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        warnings.filterwarnings("ignore", message="Degrees of freedom <= 0")
        if args.stat == "median":
            residual_map = np.nanmedian(residual.values, axis=1)
        else:
            residual_map = np.nanstd(residual.values, axis=1)
        valid_days_per_cell = np.isfinite(residual.values).sum(axis=1)

    residual_map = np.where(valid_days_per_cell >= min_days, residual_map, np.nan)
    n_valid_cells = int(np.isfinite(residual_map).sum())
    print(
        f"{n_valid_cells} / {len(residual_map)} cells have >= {min_days} "
        f"overlapping valid days and are shown."
    )

    cell_ids = ref_da["cell"].values.astype(int)
    grid = create_hemigrid("equal_area", angular_resolution=args.resolution)
    full = np.full(grid.ncells, np.nan)
    full[cell_ids] = residual_map

    finite = full[np.isfinite(full)]
    if len(finite) == 0:
        raise SystemExit("No cells have enough valid overlapping days to plot.")

    window_label = f"{args.start or 'record start'} to {args.end or 'record end'}"
    if args.stat == "median":
        abs_max = float(np.abs(finite).max())
        cmap, vmin, vmax = "RdBu", -abs_max, abs_max
        title = f"Residual VOD (stressed − predicted), median over {window_label}"
        colorbar_label = "Median residual VOD (negative = more stressed than predicted)"
    else:
        cmap, vmin, vmax = "magma", 0.0, float(finite.max())
        title = f"Residual VOD variability (std over time), {window_label}"
        colorbar_label = "Residual VOD std (higher = changes more over the window)"

    viz = HemisphereVisualizer2D(grid)
    style = PolarPlotStyle(
        title=title,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        edgecolor="none",
        colorbar_label=colorbar_label,
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
