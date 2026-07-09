"""Trace grid-cell assignment step by step to find where valid points get dropped.

Motivated by a specific, confirmed anomaly: VOD_upper_antenna has 170M+ points
where VOD, phi, and theta are ALL simultaneously finite (confirmed via
inspect_vod_group.py), yet compute_galileo_vod_timeseries.py's full run
produces 0 / 2,946,736 valid (cell, day) results. That's not a data gap —
data exists and passes every finiteness check. Something in grid cell
assignment or the valid_mask logic in canvod.grids._process_chunk_percell
is dropping every single one of those points for this specific group.

This script reproduces exactly what that internal function does, on a small
time slice (fast enough to iterate on), printing the count of points
surviving each individual condition:

    1. VOD finite
    2. cell_id finite (i.e. grid assignment succeeded at all)
    3. cell_id is a member of the grid's full cell set
    4. all three simultaneously (this is what canvod.grids actually requires)

Usage
-----
    uv run python dev/debug_cell_assignment.py /path/to/vod_store \\
        --group VOD_upper_antenna --days 2
"""

import argparse

import numpy as np
from compute_galileo_vod_timeseries import load_group, select_galileo_sids

from canvod.grids import add_cell_ids_to_ds_fast, create_hemigrid
from canvod.store import MyIcechunkStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_path", help="Path to the VOD Icechunk store")
    parser.add_argument("--branch", default="main", help="Branch to read from")
    parser.add_argument("--group", required=True, help="Group name")
    parser.add_argument(
        "--resolution", type=float, default=2.0, help="Grid resolution (deg)"
    )
    parser.add_argument(
        "--days", type=int, default=2, help="How many days to slice for debugging"
    )
    args = parser.parse_args()

    store = MyIcechunkStore(args.store_path)
    print(f"Loading group {args.group!r}...")
    vod_ds = load_group(store, args.branch, args.group)

    galileo_sids = select_galileo_sids(vod_ds)
    print(f"Galileo SIDs: {len(galileo_sids)} / {vod_ds.sizes['sid']}")
    vod_ds = vod_ds.sel(sid=galileo_sids)

    start = vod_ds.epoch.values[0]
    end = start + np.timedelta64(args.days, "D")
    slice_ds = vod_ds.sel(epoch=slice(start, end))
    print(f"Slice: {start} to {end} -> {dict(slice_ds.sizes)}")

    grid_name = f"equal_area_{args.resolution:g}deg"
    grid = create_hemigrid("equal_area", angular_resolution=args.resolution)
    print(f"Grid: {grid.ncells} cells")

    ds_with_cells = add_cell_ids_to_ds_fast(slice_ds, grid, grid_name)
    cell_var = f"cell_id_{grid_name}"

    print("\nMaterializing slice (this triggers the actual dask computation)...")
    vod_values = ds_with_cells["VOD"].values
    cell_values = ds_with_cells[cell_var].values
    theta_values = ds_with_cells["theta"].values
    phi_values = ds_with_cells["phi"].values

    n_total = vod_values.size
    print(f"\nTotal points in slice: {n_total:,}")

    vod_ok = np.isfinite(vod_values)
    print(f"1. VOD finite: {vod_ok.sum():,} ({vod_ok.mean():.1%})")

    cell_finite = np.isfinite(cell_values)
    print(
        f"2. cell_id finite (grid assignment succeeded): {cell_finite.sum():,} ({cell_finite.mean():.1%})"
    )

    if cell_finite.sum() > 0:
        finite_cells = cell_values[cell_finite]
        print(
            f"   cell_id range: min={finite_cells.min():.1f} max={finite_cells.max():.1f} "
            f"unique={len(np.unique(finite_cells))}"
        )

    all_cell_ids = grid.grid["cell_id"].to_numpy()
    print(
        f"   grid's full cell_id set: min={all_cell_ids.min()} max={all_cell_ids.max()} count={len(all_cell_ids)}"
    )

    cell_in_grid = cell_finite & np.isin(cell_values, all_cell_ids)
    print(f"3. cell_id finite AND in grid's cell set: {cell_in_grid.sum():,}")

    both_ok = vod_ok & cell_finite
    print(f"4. VOD finite AND cell_id finite: {both_ok.sum():,}")

    all_ok = vod_ok & cell_in_grid
    print(
        f"5. VOD finite AND cell_id finite AND in grid set (= what canvod.grids requires): {all_ok.sum():,}"
    )

    # If step 2 already drops everything, the bug is in add_cell_ids_to_ds_fast
    # / the KDTree query itself, not in the downstream filtering logic.
    if vod_ok.sum() > 0 and cell_finite.sum() == 0:
        print(
            "\n>>> Grid assignment itself produced zero finite cell_ids despite "
            "finite phi/theta input. Checking phi/theta values at VOD-valid points..."
        )
        sample_idx = np.argwhere(vod_ok)[:5]
        for idx in sample_idx:
            i, j = int(idx[0]), int(idx[1])
            print(
                f"    epoch[{i}] sid[{j}]: VOD={vod_values[i, j]:.4g} "
                f"theta={theta_values[i, j]:.6g} phi={phi_values[i, j]:.6g} "
                f"cell_id={cell_values[i, j]}"
            )


if __name__ == "__main__":
    main()
