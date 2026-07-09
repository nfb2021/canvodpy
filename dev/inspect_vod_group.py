"""Check whether a VOD Icechunk store group actually contains valid data.

Diagnostic for exactly this failure mode: `compute_galileo_vod_timeseries.py`
runs to completion and writes an .nc file, but the result is entirely NaN.
This inspects the RAW group (before any grid assignment/aggregation) to
narrow down where the data goes bad — VOD itself, or the phi/theta
coordinates it depends on (grid cell assignment silently drops any point
where phi or theta is non-finite, so NaN coordinates look identical to NaN
VOD once you're looking at the aggregated output).

All reductions run lazily via dask/xarray and are submitted in ONE batched
`dask.compute(...)` call at the end, rather than one `.compute()` per
statistic. On a network-share-backed store (the known bottleneck for this
site — see dev/todo_later.md), a separate `.compute()` per reduction means a
separate full read of the underlying chunks each time; batching lets dask
share one read pass across every reduction instead of re-hitting the share
per-variable.

Usage
-----
    # List available groups
    uv run python dev/inspect_vod_group.py /path/to/vod_store

    # Inspect one group
    uv run python dev/inspect_vod_group.py /path/to/vod_store --group VOD_upper_antenna
"""

import argparse
import sys

import dask
import numpy as np
import xarray as xr
from compute_galileo_vod_timeseries import load_group, select_galileo_sids

from canvod.store import MyIcechunkStore


def lazy_stats(da: xr.DataArray) -> dict[str, xr.DataArray]:
    """Build (unevaluated) finite-count/min/max/mean reductions for one array."""
    finite = np.isfinite(da)
    masked = da.where(finite)
    return {
        "n_finite": finite.sum(),
        "min": masked.min(),
        "max": masked.max(),
        "mean": masked.mean(),
    }


def print_stats(name: str, total: int, computed: dict[str, float]) -> None:
    n_finite = int(computed["n_finite"])
    frac = n_finite / total if total else 0.0
    print(f"  {name}: {frac:.1%} finite ({n_finite:,} / {total:,})")
    if n_finite > 0 and np.isfinite(computed["min"]):
        print(
            f"    min={computed['min']:.4g}  max={computed['max']:.4g}  "
            f"mean={computed['mean']:.4g}"
        )


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

    galileo_sids = select_galileo_sids(vod_ds)
    gal_ds = vod_ds.sel(sid=galileo_sids) if galileo_sids else None

    # Build every reduction lazily first, keyed so results can be unpacked
    # after the single batched compute() below.
    lazy: dict[str, xr.DataArray] = {}
    sizes: dict[str, int] = {}
    variables = [v for v in ("VOD", "phi", "theta") if v in vod_ds.variables]

    for var in variables:
        for key, expr in lazy_stats(vod_ds[var]).items():
            lazy[f"full.{var}.{key}"] = expr
        sizes[f"full.{var}"] = int(vod_ds[var].size)

    if gal_ds is not None:
        for var in variables:
            for key, expr in lazy_stats(gal_ds[var]).items():
                lazy[f"gal.{var}.{key}"] = expr
            sizes[f"gal.{var}"] = int(gal_ds[var].size)

        if all(v in gal_ds.variables for v in ("VOD", "phi", "theta")):
            vod_ok = np.isfinite(gal_ds["VOD"])
            coord_ok = np.isfinite(gal_ds["phi"]) & np.isfinite(gal_ds["theta"])
            lazy["overlap.vod_ok"] = vod_ok.sum()
            lazy["overlap.coord_ok"] = coord_ok.sum()
            lazy["overlap.both_ok"] = (vod_ok & coord_ok).sum()

    print(f"\nComputing {len(lazy)} reductions in one batched pass...")
    keys = list(lazy.keys())
    computed_values = dask.compute(*(lazy[k] for k in keys))
    computed = dict(zip(keys, computed_values, strict=True))

    print()
    vod_finite_count = int(computed["full.VOD.n_finite"])
    for var in variables:
        stats = {
            "n_finite": computed[f"full.{var}.n_finite"],
            "min": computed[f"full.{var}.min"],
            "max": computed[f"full.{var}.max"],
            "mean": computed[f"full.{var}.mean"],
        }
        print_stats(var, sizes[f"full.{var}"], stats)

    print(f"\nGalileo SIDs: {len(galileo_sids)} / {vod_ds.sizes['sid']} total")

    if gal_ds is None:
        return

    print("Within Galileo SIDs only:")
    gal_vod_finite = 0
    for var in variables:
        stats = {
            "n_finite": computed[f"gal.{var}.n_finite"],
            "min": computed[f"gal.{var}.min"],
            "max": computed[f"gal.{var}.max"],
            "mean": computed[f"gal.{var}.mean"],
        }
        print_stats(var, sizes[f"gal.{var}"], stats)
        if var == "VOD":
            gal_vod_finite = int(stats["n_finite"])

    if "overlap.vod_ok" in computed:
        vod_ok_count = int(computed["overlap.vod_ok"])
        coord_ok_count = int(computed["overlap.coord_ok"])
        both_ok_count = int(computed["overlap.both_ok"])
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
