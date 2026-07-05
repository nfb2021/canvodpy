"""canvodpy CLI — process GNSS observations and compute VOD.

Usage
-----
    # Process a specific range
    uv run python -m canvodpy.cli.run --site Rosalia --start 2025001 --end 2025007

    # Process new data only (auto-detect start from store, end = today)
    uv run python -m canvodpy.cli.run --site Rosalia

    # Cron: run daily, picks up new data automatically
    # 0 3 * * * cd /path/to/canvodpy && uv run python -m canvodpy.cli.run --site Rosalia

    # Observation ingestion only, no VOD
    uv run python -m canvodpy.cli.run --site Rosalia --no-vod

    # Preview what would be processed
    uv run python -m canvodpy.cli.run --site Rosalia --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

import numpy as np
import structlog
import xarray as xr

log = structlog.get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="canvodpy",
        description="Process GNSS observations into Icechunk stores and compute VOD.",
    )
    p.add_argument(
        "--site",
        required=True,
        help="Site name as defined in sites.yaml (e.g. Rosalia)",
    )
    p.add_argument(
        "--start",
        default=None,
        help=(
            "Start date in YYYYDOY format (e.g. 2025001). "
            "If omitted, resumes from the last processed date in the store."
        ),
    )
    p.add_argument(
        "--end",
        default=None,
        help=(
            "End date in YYYYDOY format (e.g. 2025007). "
            "If omitted, processes up to today."
        ),
    )
    p.add_argument(
        "--no-vod",
        action="store_true",
        default=False,
        help="Skip VOD calculation (only ingest observations)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview processing plan without executing",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of Dask workers (default: from config)",
    )
    p.add_argument(
        "--days-per-batch",
        type=int,
        default=None,
        help="Number of DOYs per loky wave (default: from config)",
    )
    return p


def _last_processed_date(store) -> str | None:
    """Query the store's metadata tables for the latest processed epoch.

    Returns YYYYDOY string or None if the store is empty.
    """
    try:
        groups = store.list_groups()
    except Exception:
        return None

    if not groups:
        return None

    latest_epoch = None
    with store.readonly_session() as session:
        for group in groups:
            try:
                df = store.read_metadata_table(session, group)
                if df.is_empty():
                    continue
                group_max = df["end"].max()
                if latest_epoch is None or group_max > latest_epoch:
                    latest_epoch = group_max
            except Exception:
                continue

    if latest_epoch is None:
        return None

    # Convert polars datetime to YYYYDOY
    if hasattr(latest_epoch, "to_pydatetime"):
        dt = latest_epoch  # polars Datetime
    else:
        dt = latest_epoch

    # polars returns python datetime
    import polars as pl

    if isinstance(latest_epoch, pl.Series):
        latest_epoch = latest_epoch.item()

    if hasattr(latest_epoch, "timetuple"):
        tt = latest_epoch.timetuple()
        return f"{tt.tm_year}{tt.tm_yday:03d}"

    # numpy datetime64 fallback
    ts = (latest_epoch - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "s")
    dt = datetime.fromtimestamp(float(ts), tz=UTC).replace(tzinfo=None)
    return f"{dt.year}{dt.timetuple().tm_yday:03d}"


def _today_yyyydoy() -> str:
    now = datetime.now()
    return f"{now.year}{now.timetuple().tm_yday:03d}"


def _resolve_date_range(args, site) -> tuple[str, str]:
    """Resolve start/end from args, store state, and today's date."""
    # End date: explicit or today
    end = args.end or _today_yyyydoy()

    # Start date: explicit, or resume from store
    if args.start:
        start = args.start
    else:
        last = _last_processed_date(site.rinex_store)
        if last is not None:
            # Start from the day after the last processed date
            # (the skip strategy handles overlap, but this avoids
            #  scanning days we know are complete)
            start = last  # include last day too — skip handles duplicates
            print(f"  resuming from store (last processed: {last})")
        else:
            # Empty store: start from earliest available data
            start = "2000001"
            print("  empty store, scanning all available data")

    return start, end


def _print_header(args: argparse.Namespace, config, start: str, end: str) -> None:
    proc = config.processing.params
    storage = config.processing.storage
    print("=" * 72)
    print(f"canvodpy  site={args.site}  {start} .. {end}")
    print("=" * 72)
    print(f"  started        {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  ephemeris      {proc.ephemeris_source}")
    print(f"  keep_vars      {proc.keep_rnx_vars}")
    print(f"  days_per_batch {args.days_per_batch or proc.days_per_batch}")
    print(f"  resource_mode  {proc.resource_mode}")
    print(f"  store_strategy {storage.rinex_store_strategy}")
    print(f"  rinex_store    {storage.rinex_store_name or 'rinex'}")
    print(f"  vod_store      {storage.vod_store_name or 'vod'}")
    print(f"  vod            {'skip' if args.no_vod else 'enabled'}")
    print()


def _compute_vod_for_day(
    datasets: dict[str, xr.Dataset],
    vod_analyses: dict,
    date_key: str,
) -> dict[str, xr.Dataset]:
    """Compute VOD for all configured analysis pairs.

    Parameters
    ----------
    datasets
        ``{group_name: ds}`` dict as yielded by ``process_range``.
        Group names: ``canopy_01``, ``reference_01_canopy_01``, etc.
    vod_analyses
        VOD analysis configs from ``site.vod_analyses``.
    research_site
        ``GnssResearchSite`` instance (owns the VOD store).
    date_key
        YYYYDOY string for logging.

    Returns
    -------
    dict mapping analysis name to VOD dataset.
    """
    from canvod.vod.calculator import TauOmegaZerothOrder

    results: dict[str, xr.Dataset] = {}

    for analysis_name, analysis_cfg in vod_analyses.items():
        canopy_name = analysis_cfg.canopy_receiver
        ref_name = analysis_cfg.reference_receiver

        # The reference group in the store is "{ref}_{canopy}"
        ref_group = f"{ref_name}_{canopy_name}"

        canopy_ds = datasets.get(canopy_name)
        ref_ds = datasets.get(ref_group)

        if canopy_ds is None:
            log.warning(
                "vod_skipped",
                analysis=analysis_name,
                reason=f"canopy group '{canopy_name}' not in datasets",
                date=date_key,
            )
            continue
        if ref_ds is None:
            log.warning(
                "vod_skipped",
                analysis=analysis_name,
                reason=f"reference group '{ref_group}' not in datasets",
                date=date_key,
            )
            continue

        t0 = time.perf_counter()
        try:
            vod_ds = TauOmegaZerothOrder.from_datasets(
                canopy_ds=canopy_ds,
                sky_ds=ref_ds,
                align=True,
            )

            # Rechunk + clear encoding for clean Icechunk writes
            vod_ds = vod_ds.chunk({"epoch": 34560, "sid": -1})
            for var in vod_ds.data_vars:
                vod_ds[var].encoding = {}

            dt = time.perf_counter() - t0

            n_valid = int((~vod_ds["VOD"].isnull()).sum())
            n_total = vod_ds["VOD"].size
            print(
                f"  VOD {analysis_name}: "
                f"{n_valid}/{n_total} valid "
                f"({100 * n_valid / n_total:.0f}%)  "
                f"{dt:.1f}s"
            )
            results[analysis_name] = vod_ds

        except Exception as e:
            log.error(
                "vod_failed",
                analysis=analysis_name,
                date=date_key,
                error=str(e),
            )
            print(f"  VOD {analysis_name}: FAILED — {e}")

    return results


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from canvod.utils.config import load_config

    config = load_config()

    from canvodpy.api import Site

    site = Site(args.site)

    # Resolve date range (auto-detect from store if not specified)
    start, end = _resolve_date_range(args, site)

    _print_header(args, config, start, end)

    if args.dry_run:
        with site.pipeline(
            n_workers=args.workers,
            days_per_batch=args.days_per_batch,
            dry_run=True,
        ) as pipeline:
            plan = pipeline.preview()
            print("Dry-run plan:")
            for k, v in plan.items():
                print(f"  {k}: {v}")
        return 0

    # Resolve VOD analysis pairs
    vod_analyses = site.vod_analyses if not args.no_vod else {}
    if vod_analyses:
        print(f"VOD analyses: {list(vod_analyses.keys())}")
        print()

    # Access the underlying GnssResearchSite for VOD store writes
    research_site = site._site

    total_days = 0
    total_vod = 0
    t_total = time.perf_counter()

    with site.pipeline(
        n_workers=args.workers,
        days_per_batch=args.days_per_batch,
        dry_run=False,
    ) as pipeline:
        gen = pipeline.process_range(start=start, end=end)
        while True:
            # Time the pipeline step (RINEX read + augment + store write + dedup)
            # separately from VOD computation and VOD store write.
            t_pipeline = time.perf_counter()
            try:
                date_key, datasets = next(gen)
            except StopIteration:
                break
            dt_pipeline = time.perf_counter() - t_pipeline

            total_days += 1
            t_day = time.perf_counter()

            print(f"\n--- {date_key} ---")
            for group, ds in datasets.items():
                e, s = ds.sizes.get("epoch", 0), ds.sizes.get("sid", 0)
                print(f"  {group}: {e} epochs x {s} sids")

            dt_vod = 0.0
            dt_vod_store = 0.0
            if vod_analyses:
                t_vod = time.perf_counter()
                vod_results = _compute_vod_for_day(datasets, vod_analyses, date_key)
                dt_vod = time.perf_counter() - t_vod

                t_vod_store = time.perf_counter()
                for analysis_name, vod_ds in vod_results.items():
                    research_site.store_vod_analysis(
                        vod_dataset=vod_ds,
                        analysis_name=analysis_name,
                        commit_message=f"VOD {analysis_name} {date_key}",
                    )
                dt_vod_store = time.perf_counter() - t_vod_store
                total_vod += len(vod_results)

            dt_day = time.perf_counter() - t_day
            print(
                f"  pipeline={dt_pipeline:.1f}s"
                f"  vod={dt_vod:.1f}s"
                f"  vod_store={dt_vod_store:.1f}s"
                f"  day={dt_pipeline + dt_day:.1f}s"
            )

    dt_total = time.perf_counter() - t_total
    print()
    print("=" * 72)
    print(f"Done  {total_days} days  {total_vod} VOD analyses  {dt_total:.0f}s total")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
