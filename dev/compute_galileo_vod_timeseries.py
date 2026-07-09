"""Compute a Galileo-only, per-cell daily-median VOD timeseries and save it to disk.

This is the processing half of the Galileo VOD timeseries workflow — run it
from the CLI on the machine where the store actually lives. The companion
notebook (`dev/plot_galileo_vod_timeseries.py`) only loads the small output
file this script produces and visualizes it; it does no store reads or
grid/aggregation work itself, so it stays fast and interactive even though
the underlying store may be hundreds of days of (epoch, sid) data.

Usage
-----
    # List available groups (no --group given)
    uv run python dev/compute_galileo_vod_timeseries.py /path/to/vod_store

    # Compute and save
    uv run python dev/compute_galileo_vod_timeseries.py /path/to/vod_store \\
        --group VOD_lower_antenna --resolution 2.0 --stat median \\
        --output dev/output/galileo_vod_lower_2deg_median.nc

No rechunk needed before this: the known epoch-chunk misalignment
(epoch=34560 tuned for 2.5s sampling vs. this site's 5s sampling, see
dev/todo_later.md §19) is a write-amplification problem, not a read one — a
single bulk read-and-aggregate pass like this reads every chunk once
regardless of how they're cut. The diagnostic below reports the actual
on-disk chunk shape so you can confirm that rather than assume it.

Note: importing ``canvod.store`` pulls in canvodpy's shared logging config,
which routes the console to WARNING+ only (full detail goes to ``.logs/``).
Progress here is printed directly rather than logged so it's actually
visible when you run this interactively.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr

from canvod.grids import (
    add_cell_ids_to_ds_fast,
    compute_percell_timeseries,
    create_hemigrid,
)
from canvod.store import MyIcechunkStore

log = logging.getLogger(__name__)


def report_chunk_layout(vod_ds: xr.Dataset) -> None:
    """Print the on-disk epoch chunk layout — answers 'should I rechunk first?'."""
    epoch_axis = vod_ds["VOD"].dims.index("epoch")
    chunks = vod_ds["VOD"].chunks

    if chunks is None:
        print("VOD is not dask-backed (loaded eagerly) — chunk layout not applicable.")
        return

    epoch_chunk_sizes = chunks[epoch_axis]
    unique_sizes = sorted(set(epoch_chunk_sizes))
    print(
        f"Epoch chunks: {len(epoch_chunk_sizes)} chunks, sizes "
        f"{unique_sizes[:5]}{'...' if len(unique_sizes) > 5 else ''} "
        f"({len(unique_sizes)} distinct size{'s' if len(unique_sizes) != 1 else ''})."
    )
    if len(unique_sizes) <= 2:
        print(
            "Uniform (or near-uniform) chunk sizes — just oversized per chunk "
            "relative to a calendar day, not fragmented. No rechunk needed for "
            "this bulk read-and-aggregate pass."
        )
    else:
        print(
            "Many distinct chunk sizes — likely fragmented from read-modify-write "
            "churn during backfill. Reads still correct, just less efficient than "
            "a clean chunk grid. See dev/todo_later.md §19 for rechunk_group()."
        )


def load_group(store: MyIcechunkStore, branch: str, group: str) -> xr.Dataset:
    """Open one VOD group lazily and make sure epoch is real datetime64."""
    with store.readonly_session(branch=branch) as session:
        vod_ds = xr.open_zarr(session.store, group=group, consolidated=False)

    if not np.issubdtype(vod_ds["epoch"].dtype, np.datetime64):
        # Zarr can't store datetime64 directly — xr.open_zarr normally CF-decodes
        # an encoded int64 + units/calendar attrs back into datetime64
        # automatically. If that didn't happen, decode explicitly rather than
        # silently grouping raw integers into "days".
        vod_ds = xr.decode_cf(vod_ds)
        assert np.issubdtype(vod_ds["epoch"].dtype, np.datetime64), (
            f"epoch is {vod_ds['epoch'].dtype}, not datetime64, even after "
            "xr.decode_cf — check the group's epoch encoding/units attrs."
        )
    return vod_ds


def select_galileo_sids(vod_ds: xr.Dataset) -> list[str]:
    """Return SIDs whose system is Galileo ('E'), all bands/codes included."""
    all_sids = [str(s) for s in vod_ds.sid.values]

    if "system" in vod_ds.coords or "system" in vod_ds.variables:
        # Prefer the explicit per-SID `system` coordinate over parsing the sid
        # string — it's what canvodpy backfills for every SID and is robust to
        # any future change in SID string formatting.
        system_values = [str(s) for s in vod_ds["system"].values]
        return [
            sid for sid, sys in zip(all_sids, system_values, strict=True) if sys == "E"
        ]
    return [s for s in all_sids if s.startswith("E")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store_path", type=Path, help="Path to the VOD Icechunk store")
    parser.add_argument("--branch", default="main", help="Branch to read from")
    parser.add_argument(
        "--group",
        default=None,
        help="Group name (e.g. VOD_lower_antenna). Omit to list available groups.",
    )
    parser.add_argument(
        "--resolution", type=float, default=2.0, help="Equal-area grid resolution (deg)"
    )
    parser.add_argument(
        "--stat",
        choices=["median", "mean"],
        default="median",
        help="Per-cell statistic",
    )
    parser.add_argument(
        "--min-obs",
        type=int,
        default=1,
        help="Minimum observations per (cell, day) to keep",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=21,
        help="Days per processing chunk (bounds memory use during aggregation)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output NetCDF path (default: dev/output/<group>_<resolution>deg_<stat>.nc)",
    )
    args = parser.parse_args()

    store = MyIcechunkStore(args.store_path)
    available_groups = store.list_groups(branch=args.branch)

    if args.group is None:
        print(f"Available groups on branch {args.branch!r}: {available_groups}")
        print("Re-run with --group <name> to compute.")
        sys.exit(0)

    if args.group not in available_groups:
        log.error("Group %r not found. Available: %s", args.group, available_groups)
        sys.exit(1)

    print(f"Loading group {args.group!r}...")
    t0 = time.time()
    vod_ds = load_group(store, args.branch, args.group)
    print(f"Loaded {dict(vod_ds.sizes)} in {time.time() - t0:.1f}s")

    report_chunk_layout(vod_ds)

    galileo_sids = select_galileo_sids(vod_ds)
    print(f"Galileo SIDs: {len(galileo_sids)} / {vod_ds.sizes['sid']} total")
    if not galileo_sids:
        log.error("No Galileo SIDs found — check the store's 'system'/'sid' values.")
        sys.exit(1)

    # Filter to Galileo BEFORE grid assignment, not after. The sid dimension
    # is typically one dask chunk (chunks={"epoch": ..., "sid": -1}), so
    # selecting a sid subset *after* add_cell_ids_to_ds_fast's map_blocks call
    # still forces that call to materialize over the full sid dimension —
    # cell assignment for every non-Galileo SID would run for nothing. On a
    # store with hundreds of SIDs and millions of epochs this is the
    # difference between assigning cells for ~277 SIDs vs. only the ~1/4 that
    # are actually Galileo.
    vod_ds = vod_ds.sel(sid=galileo_sids)

    grid_name = f"equal_area_{args.resolution:g}deg"
    grid = create_hemigrid("equal_area", angular_resolution=args.resolution)
    ds_with_cells = add_cell_ids_to_ds_fast(vod_ds, grid, grid_name)

    print(f"Computing per-cell daily {args.stat}...")
    t1 = time.time()
    percell_ds = compute_percell_timeseries(
        data_ds=ds_with_cells,
        grid=grid,
        cell_var=f"cell_id_{grid_name}",
        temporal_resolution="1D",
        chunk_days=args.chunk_days,
        stat=args.stat,
        min_obs_per_cell_time=args.min_obs,
    )
    print(
        f"Done in {time.time() - t1:.1f}s: "
        f"{percell_ds.sizes['cell']} cells x {percell_ds.sizes['time']} days"
    )

    percell_ds.attrs.update(
        {
            "source_store": str(args.store_path),
            "source_group": args.group,
            "source_branch": args.branch,
            "galileo_sid_count": len(galileo_sids),
            "grid_resolution_deg": args.resolution,
            "stat": args.stat,
            "min_obs_per_cell_time": args.min_obs,
        }
    )

    output_path = args.output or Path("dev/output") / (
        f"{args.group}_{args.resolution:g}deg_{args.stat}.nc"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    percell_ds.to_netcdf(output_path)
    print(f"Saved to {output_path}")
    print(
        "Visualize with: uv run marimo edit dev/plot_galileo_vod_timeseries.py "
        f"(point it at {output_path})"
    )


if __name__ == "__main__":
    main()
