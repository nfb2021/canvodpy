"""Check whether a VOD Icechunk store group actually contains valid data.

Diagnostic for exactly this failure mode: `compute_galileo_vod_timeseries.py`
runs to completion and writes an .nc file, but the result is entirely NaN.
This inspects the RAW group (before any grid assignment/aggregation) to
narrow down where the data goes bad — VOD itself, or the phi/theta
coordinates it depends on (grid cell assignment silently drops any point
where phi or theta is non-finite, so NaN coordinates look identical to NaN
VOD once you're looking at the aggregated output).

All reductions below run lazily via dask/xarray (`.compute()` only at the
final reduction) rather than materializing full (epoch, sid) arrays —
on the real store that's ~2.1 billion elements, ~16.8GB per variable as a
dense array, which is exactly what made the first version of this script
hang instead of finishing.

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
import xarray as xr
from compute_galileo_vod_timeseries import load_group, select_galileo_sids

from canvod.store import MyIcechunkStore


def report_stats(da: xr.DataArray, name: str) -> int:
    """Print finite-fraction + min/max/mean for a (possibly huge) dask-backed array.

    Stays lazy until each individual `.compute()` call, so dask only holds
    one chunk at a time in memory rather than the full array.
    """
    finite = np.isfinite(da)
    total = int(da.size)
    n_finite = int(finite.sum().compute())
    frac = n_finite / total if total else 0.0
    print(f"  {name}: {frac:.1%} finite ({n_finite:,} / {total:,})")
    if n_finite > 0:
        masked = da.where(finite)
        vmin = float(masked.min().compute())
        vmax = float(masked.max().compute())
        vmean = float(masked.mean().compute())
        print(f"    min={vmin:.4g}  max={vmax:.4g}  mean={vmean:.4g}")
    return n_finite


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

    vod_finite_count = 0
    for var in ("VOD", "phi", "theta"):
        if var not in vod_ds.variables:
            print(f"  {var}: NOT PRESENT in this group")
            continue
        n_finite = report_stats(vod_ds[var], var)
        if var == "VOD":
            vod_finite_count = n_finite

    galileo_sids = select_galileo_sids(vod_ds)
    print(f"\nGalileo SIDs: {len(galileo_sids)} / {vod_ds.sizes['sid']} total")

    if not galileo_sids:
        return

    gal_ds = vod_ds.sel(sid=galileo_sids)
    print("Within Galileo SIDs only:")
    gal_vod_finite = 0
    for var in ("VOD", "phi", "theta"):
        if var not in gal_ds.variables:
            continue
        n_finite = report_stats(gal_ds[var], var)
        if var == "VOD":
            gal_vod_finite = n_finite

    # Points where VOD is valid but phi/theta aren't (or vice versa) are
    # exactly what silently vanishes during grid cell assignment. Stays
    # lazy — only the final .sum().compute() calls trigger computation.
    if all(v in gal_ds.variables for v in ("VOD", "phi", "theta")):
        vod_ok = np.isfinite(gal_ds["VOD"])
        coord_ok = np.isfinite(gal_ds["phi"]) & np.isfinite(gal_ds["theta"])
        both_ok = vod_ok & coord_ok

        vod_ok_count = int(vod_ok.sum().compute())
        coord_ok_count = int(coord_ok.sum().compute())
        both_ok_count = int(both_ok.sum().compute())

        print(
            f"\nVOD finite: {vod_ok_count:,} | "
            f"phi+theta finite: {coord_ok_count:,} | "
            f"both finite (usable by grid assignment): {both_ok_count:,}"
        )
        if vod_ok_count > 0 and both_ok_count == 0:
            print(
                "VOD has valid values but phi/theta don't overlap with them at "
                "all — grid cell assignment will drop every point. This points "
                "to a coordinate augmentation issue for this specific group, "
                "not a VOD computation issue."
            )
        elif gal_vod_finite == 0 and vod_finite_count > 0:
            print(
                "VOD has valid values elsewhere in the store, but none among "
                "the Galileo-selected SIDs specifically — check whether the "
                "'system' coordinate correctly marks this group's Galileo "
                "SIDs, or whether Galileo VOD genuinely wasn't computed for "
                "this antenna."
            )


if __name__ == "__main__":
    main()
