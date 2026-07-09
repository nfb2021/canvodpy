"""Plot smoothed global daily Galileo VOD for both antennas on one figure.

Loads the two NetCDF outputs from `dev/compute_galileo_vod_timeseries.py`
(lower + upper antenna), collapses each to a single daily timeseries (median
across all Galileo-observed grid cells), smooths with a Savitzky-Golay
filter, and plots both lines on one matplotlib figure.

Usage
-----
    uv run python dev/plot_galileo_vod_comparison.py \\
        --lower dev/output/VOD_lower_antenna_2deg_median.nc \\
        --upper dev/output/VOD_upper_antenna_2deg_median.nc \\
        --output dev/output/galileo_vod_comparison.png
"""

import argparse
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from scipy.signal import savgol_filter


def global_daily_series(path: Path) -> pd.Series:
    """Collapse a (cell, time) per-cell dataset to one daily series (median across cells)."""
    ds = xr.open_dataset(path)
    stat = ds.attrs.get("stat", "median")
    with warnings.catch_warnings():
        # A fully-NaN day is reported explicitly below (with counts) instead
        # of left as numpy's generic "All-NaN slice" background warning.
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        values = np.nanmedian(ds["cell_timeseries"].values, axis=0)
    index = pd.to_datetime(ds["time"].values)
    label = ds.attrs.get("source_group", path.stem)
    series = pd.Series(values, index=index, name=f"{label} ({stat}-of-{stat})")

    n_valid_days = int(series.notna().sum())
    print(f"[{series.name}] {n_valid_days} / {len(series)} days have any valid cell.")
    return series


def smooth(series: pd.Series, window_days: int, polyorder: int) -> pd.Series | None:
    """Savitzky-Golay smoothing; interpolates small NaN gaps first (savgol can't handle them).

    Returns None (with a printed warning) if the series has no valid data at
    all — the caller skips plotting that line instead of crashing.
    """
    if series.notna().sum() == 0:
        print(
            f"[{series.name}] every day is NaN — skipping this line. "
            "This points to near-zero valid (cell, day) coverage in the "
            "source dataset, not a plotting issue; check the compute step's "
            "own 'Coverage: X / Y' output for this group."
        )
        return None

    window = window_days if window_days % 2 == 1 else window_days + 1
    if window != window_days:
        print(
            f"[{series.name}] window_days={window_days} is even; using {window} (odd, required by savgol_filter)."
        )
    window = min(window, len(series) - (1 - len(series) % 2))
    if window < polyorder + 1:
        raise ValueError(
            f"[{series.name}] series too short ({len(series)} days) for "
            f"window={window}, polyorder={polyorder}."
        )

    filled = series.interpolate(limit_direction="both")
    n_nan = int(filled.isna().sum())
    if n_nan:
        print(
            f"[{series.name}] {n_nan} unfillable NaN day(s) remain after interpolation."
        )

    smoothed_values = savgol_filter(
        filled.to_numpy(), window_length=window, polyorder=polyorder
    )
    return pd.Series(smoothed_values, index=series.index, name=series.name)


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
        "--window", type=int, default=30, help="Savitzky-Golay window (days)"
    )
    parser.add_argument(
        "--polyorder", type=int, default=2, help="Savitzky-Golay polynomial order"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dev/output/galileo_vod_comparison.png"),
        help="Output image path",
    )
    parser.add_argument(
        "--show", action="store_true", help="Also display the plot interactively"
    )
    args = parser.parse_args()

    fig, ax = plt.subplots(figsize=(10, 5))

    n_plotted = 0
    for path, color in [(args.lower, "tab:green"), (args.upper, "tab:blue")]:
        if not path.exists():
            print(f"Skipping missing file: {path}")
            continue
        raw = global_daily_series(path)
        smoothed = smooth(raw, args.window, args.polyorder)
        if smoothed is None:
            continue
        ax.plot(
            smoothed.index,
            smoothed.values,
            label=smoothed.name,
            color=color,
            linewidth=1.5,
        )
        n_plotted += 1

    if n_plotted == 0:
        raise SystemExit(
            "Nothing to plot — both inputs were either missing or entirely "
            "NaN. See the messages above for which."
        )

    ax.set_xlabel("Date")
    ax.set_ylabel("VOD")
    ax.set_title(
        f"Galileo VOD — {args.window}-day Savitzky-Golay smoothed (both antennas)"
    )
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    print(f"Saved to {args.output}")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
