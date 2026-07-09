"""Plot the reference-vs-drought VOD difference (raw and normalized).

Treats the lower antenna as the undisturbed reference and the upper antenna
as the drought-subjected one. Computes, per day:

    diff      = reference - stressed          (lower - upper)
    norm_diff = (reference - stressed) / reference

Positive values mean the drought-subjected antenna has LOWER VOD than the
reference — i.e. a drought stress signal. Both are smoothed with the same
Savitzky-Golay approach as `plot_galileo_vod_comparison.py` and plotted as
two stacked panels on one figure, with raw (unsmoothed) daily values shown
as a semi-transparent scatter underneath each line.

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
from plot_galileo_vod_comparison import global_daily_series, smooth


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

    # Only compare days where BOTH antennas have a valid value — a
    # difference is meaningless if one side is NaN.
    aligned = reference.to_frame("reference").join(
        stressed.to_frame("stressed"), how="inner"
    )
    n_common = int((aligned["reference"].notna() & aligned["stressed"].notna()).sum())
    print(f"{n_common} / {len(aligned)} days have both reference and stressed values.")

    diff = (aligned["reference"] - aligned["stressed"]).rename("diff")
    norm_diff = (diff / aligned["reference"]).rename("norm_diff")

    fig, (ax_diff, ax_norm) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    for ax, series, ylabel, title in [
        (ax_diff, diff, "VOD difference", "Reference − stressed (raw units)"),
        (
            ax_norm,
            norm_diff,
            "Normalized VOD difference",
            "(Reference − stressed) / reference",
        ),
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
        f"Drought signal (positive = stressed antenna lower VOD), "
        f"{args.window}-day Savitzky-Golay smoothed"
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
