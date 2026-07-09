"""Check whether a VOD Icechunk store group actually contains valid data.

Diagnostic for exactly this failure mode: `compute_galileo_vod_timeseries.py`
runs to completion and writes an .nc file, but the result is entirely NaN.
This inspects the RAW group (before any grid assignment/aggregation) to
narrow down where the data goes bad — VOD itself, or the phi/theta
coordinates it depends on (grid cell assignment silently drops any point
where phi or theta is non-finite, so NaN coordinates look identical to NaN
VOD once you're looking at the aggregated output).

Usage
-----
    # List available groups
    uv run python dev/inspect_vod_group.py /path/to/vod_store

    # Inspect one group
    uv run python dev/inspect_vod_group.py /path/to/vod_store --group VOD_upper_antenna
"""

import argparse
import sys

import numpy as np
from compute_galileo_vod_timeseries import load_group, select_galileo_sids

from canvod.store import MyIcechunkStore


def valid_fraction(arr: np.ndarray) -> float:
    """Fraction of finite (non-NaN, non-inf) values in an array."""
    return float(np.isfinite(arr).mean())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_path", help="Path to the VOD Icechunk store")
    parser.add_argument("--branch", default="main", help="Branch to read from")
    parser.add_argument(
        "--group", default=None, help="Group name. Omit to list groups."
    )
    args = parser.parse_args()

    store = MyIcechunkStore(args.store_path)
    available_groups = store.list_groups(branch=args.branch)

    if args.group is None:
        print(f"Available groups on branch {args.branch!r}: {available_groups}")
        print("Re-run with --group <name> to inspect.")
        sys.exit(0)

    if args.group not in available_groups:
        print(f"Group {args.group!r} not found. Available: {available_groups}")
        sys.exit(1)

    print(f"Loading group {args.group!r}...")
    vod_ds = load_group(store, args.branch, args.group)
    print(f"Shape: {dict(vod_ds.sizes)}")

    for var in ("VOD", "phi", "theta"):
        if var not in vod_ds.variables:
            print(f"  {var}: NOT PRESENT in this group")
            continue
        arr = vod_ds[var].values
        frac = valid_fraction(arr)
        print(f"  {var}: {frac:.1%} finite ({np.isfinite(arr).sum():,} / {arr.size:,})")
        if frac > 0:
            finite = arr[np.isfinite(arr)]
            print(
                f"    min={finite.min():.4g}  max={finite.max():.4g}  mean={finite.mean():.4g}"
            )

    galileo_sids = select_galileo_sids(vod_ds)
    print(f"\nGalileo SIDs: {len(galileo_sids)} / {vod_ds.sizes['sid']} total")

    if galileo_sids:
        gal_ds = vod_ds.sel(sid=galileo_sids)
        print("Within Galileo SIDs only:")
        for var in ("VOD", "phi", "theta"):
            if var not in gal_ds.variables:
                continue
            arr = gal_ds[var].values
            frac = valid_fraction(arr)
            print(
                f"  {var}: {frac:.1%} finite ({np.isfinite(arr).sum():,} / {arr.size:,})"
            )

        # Points where VOD is valid but phi/theta aren't (or vice versa) are
        # exactly what silently vanishes during grid cell assignment.
        if all(v in gal_ds.variables for v in ("VOD", "phi", "theta")):
            vod_ok = np.isfinite(gal_ds["VOD"].values)
            coord_ok = np.isfinite(gal_ds["phi"].values) & np.isfinite(
                gal_ds["theta"].values
            )
            both_ok = vod_ok & coord_ok
            print(
                f"\nVOD finite: {vod_ok.sum():,} | "
                f"phi+theta finite: {coord_ok.sum():,} | "
                f"both finite (usable by grid assignment): {both_ok.sum():,}"
            )
            if vod_ok.sum() > 0 and both_ok.sum() == 0:
                print(
                    "VOD has valid values but phi/theta don't overlap with them at "
                    "all — grid cell assignment will drop every point. This points "
                    "to a coordinate augmentation issue for this specific group, "
                    "not a VOD computation issue."
                )


if __name__ == "__main__":
    main()
