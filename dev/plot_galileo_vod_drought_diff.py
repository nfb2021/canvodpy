"""Isolate the drought-specific VOD signal, correcting for inter-tree bias.

The naive (reference - stressed) difference conflates two things:
  1. A structural bias — the two antennas observe different trees, so they
     have different baseline biomass/canopy density, and likely a different
     SCALE of response to shared seasonal dynamics too (not just an offset).
  2. The drought-specific signal we actually want to isolate.

Assumption (per domain input): the two trees' *relative* dynamics are
identical — both respond to the same weather/seasonal drivers in the same
way — except for drought-induced vegetation water changes at the stressed
antenna. Under that assumption, a robust LINEAR fit of

    stressed ≈ slope * reference + intercept

fit across the whole record describes "what stressed normally reads, given
what reference reads" — i.e. the shared dynamics plus the fixed structural
bias (both scale and offset). The RESIDUAL (observed stressed - predicted
stressed) is then the part of the stressed signal NOT explained by the
shared dynamics — which, under the stated assumption, is the drought signal.

Theil-Sen (median-of-pairwise-slopes) is used instead of ordinary
least-squares specifically because it's robust to outliers: as long as the
drought-affected days are a minority of the whole record (breakdown point
~29%), the fit reflects the "normal" (non-drought) relationship instead of
being dragged toward it by the drought period itself.

Produces a 3-panel figure:
  1. Scatter of reference vs. stressed (all days) with the fitted line —
     a visual check of "the correction," in the same joint-distribution
     terms the fit itself operates on.
  2. Residual over time (raw units): observed - predicted.
  3. Normalized residual over time: residual / predicted.

Usage
-----
    uv run python dev/plot_galileo_vod_drought_diff.py \\
        --reference dev/output/VOD_lower_antenna_2deg_median.nc \\
        --stressed dev/output/VOD_upper_antenna_2deg_median.nc \\
        --output dev/output/galileo_vod_drought_diff.png
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from plot_galileo_vod_comparison import global_daily_series, smooth
from scipy.stats import theilslopes


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
        "--start",
        default=None,
        help="Restrict the fit AND the residual to this window (inclusive); default = whole record",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Restrict the fit AND the residual to this window (inclusive); default = whole record",
    )
    parser.add_argument(
        "--window", type=int, default=7, help="Savitzky-Golay window (days)"
    )
    parser.add_argument(
        "--polyorder", type=int, default=2, help="Savitzky-Golay polynomial order"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dev/output/galileo_vod_drought_diff.png"),
        help="Output image path",
    )
    parser.add_argument(
        "--raw-alpha",
        type=float,
        default=0.3,
        help="Opacity of the raw (unsmoothed) daily points, 0-1",
    )
    parser.add_argument(
        "--raw-size", type=float, default=10, help="Marker size for raw daily points"
    )
    parser.add_argument(
        "--show", action="store_true", help="Also display the plot interactively"
    )
    args = parser.parse_args()

    reference = global_daily_series(args.reference)
    stressed = global_daily_series(args.stressed)

    aligned = reference.to_frame("reference").join(
        stressed.to_frame("stressed"), how="inner"
    )
    if args.start is not None or args.end is not None:
        aligned = aligned.loc[args.start : args.end]
    aligned = aligned.dropna()
    n_common = len(aligned)
    window_label = f"{args.start or 'record start'} to {args.end or 'record end'}"
    print(f"{n_common} days have both reference and stressed values ({window_label}).")

    x = aligned["reference"].to_numpy()
    y = aligned["stressed"].to_numpy()

    slope, intercept, slope_lo, slope_hi = theilslopes(y, x)
    print(
        f"Robust fit: stressed = {slope:.4f} * reference + {intercept:.4f} "
        f"(slope 95% CI: [{slope_lo:.4f}, {slope_hi:.4f}])"
    )

    predicted = slope * aligned["reference"] + intercept
    residual = (aligned["stressed"] - predicted).rename("residual")
    norm_residual = (residual / predicted).rename("norm_residual")

    fig = plt.figure(figsize=(10, 11))
    gs = fig.add_gridspec(3, 1, height_ratios=[1.2, 1, 1])
    ax_scatter = fig.add_subplot(gs[0])
    ax_resid = fig.add_subplot(gs[1])
    ax_norm = fig.add_subplot(gs[2], sharex=ax_resid)

    ax_scatter.scatter(x, y, alpha=args.raw_alpha, s=args.raw_size, color="tab:purple")
    x_line = np.array([x.min(), x.max()])
    ax_scatter.plot(
        x_line,
        slope * x_line + intercept,
        color="black",
        linewidth=1.5,
        label=f"stressed = {slope:.3f}·reference + {intercept:.3f}",
    )
    ax_scatter.set_xlabel("Reference VOD")
    ax_scatter.set_ylabel("Stressed VOD")
    ax_scatter.set_title("Joint distribution + robust (Theil-Sen) fit")
    ax_scatter.legend()

    for ax, series, ylabel, title in [
        (ax_resid, residual, "Residual VOD", "Stressed − predicted (raw units)"),
        (ax_norm, norm_residual, "Normalized residual", "Residual / predicted"),
    ]:
        if series.notna().sum() > 0:
            ax.scatter(
                series.index,
                series.values,
                color="tab:red",
                alpha=args.raw_alpha,
                s=args.raw_size,
                linewidths=0,
                zorder=1,
            )
        smoothed = smooth(series, args.window, args.polyorder)
        if smoothed is not None:
            ax.plot(
                smoothed.index,
                smoothed.values,
                color="tab:red",
                linewidth=1.5,
                zorder=2,
            )
        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=0)
        ax.set_ylabel(ylabel)
        ax.set_title(title)

    ax_norm.set_xlabel("Date")
    fig.suptitle(
        f"Drought signal after removing shared dynamics + inter-tree bias "
        f"(negative = stressed antenna below prediction), "
        f"{args.window}-day Savitzky-Golay smoothed, {window_label}"
    )
    fig.autofmt_xdate()
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    print(f"Saved to {args.output}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
