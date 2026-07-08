"""canvodpy CLI — process GNSS observations and compute VOD.

Usage
-----
    # Process a specific range
    uv run canvodpy run --site Rosalia --start 2025001 --end 2025007

    # Process new data only (auto-detect start from store, end = today)
    uv run canvodpy run --site Rosalia

    # Multiple sites in one invocation (processed sequentially)
    uv run canvodpy run --site Rosalia OtherSite

    # Cron: run daily, picks up new data automatically
    # 0 3 * * * cd /path/to/canvodpy && uv run canvodpy run --site Rosalia

    # Observation ingestion only, no VOD
    uv run canvodpy run --site Rosalia --no-vod

    # Preview what would be processed
    uv run canvodpy run --site Rosalia --dry-run
"""

from __future__ import annotations

import argparse
import os
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
        nargs="+",
        metavar="SITE",
        help=(
            "One or more site names as defined in sites.yaml (e.g. Rosalia). "
            "Multiple sites are processed sequentially."
        ),
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
    p.add_argument(
        "--config",
        default=None,
        metavar="FILE",
        help="Overlay config YAML applied on top of the main canvod-settings.yaml",
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


def _site_groups(site) -> list[str]:
    """List receiver-group names as used in the Icechunk store.

    Canopy receivers write under their own name (``canopy_01``); each
    reference/canopy pair writes under ``{reference}_{canopy}``.
    """
    canopy_names = [
        name
        for name, cfg in site.active_receivers.items()
        if cfg.get("type") == "canopy"
    ]
    pair_names = [
        f"{ref}_{canopy}" for ref, canopy in site._site.get_reference_canopy_pairs()
    ]
    return canopy_names + pair_names


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


def _compute_vod_for_day(
    datasets: dict[str, xr.Dataset],
    vod_analyses: dict,
    date_key: str,
    reporter=None,
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
            if reporter:
                reporter.on_vod_result(analysis_name, n_valid, n_total, dt)
            else:
                pct = 100 * n_valid / n_total if n_total else 0
                print(
                    f"  VOD {analysis_name}: {n_valid}/{n_total} valid ({pct:.0f}%)  {dt:.1f}s"
                )
            results[analysis_name] = vod_ds

        except Exception as e:
            log.error(
                "vod_failed",
                analysis=analysis_name,
                date=date_key,
                error=str(e),
            )
            if reporter:
                reporter.on_vod_failed(analysis_name, str(e))
            else:
                print(f"  VOD {analysis_name}: FAILED — {e}")

    return results


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from pathlib import Path

    from canvod.utils.config import load_config

    config_file: Path | None = None
    if args.config is not None:
        config_file = Path(args.config)
        if not config_file.exists():
            print(
                f"Error: overlay config file not found: {config_file}", file=sys.stderr
            )
            return 1
        os.environ["CANVOD_CONFIG_FILE"] = str(config_file.expanduser().resolve())

    config = load_config(config_file=config_file)

    from canvodpy.api import Site

    site_names: list[str] = args.site

    if args.dry_run:
        for site_name in site_names:
            site = Site(site_name)
            with site.pipeline(
                n_workers=args.workers,
                days_per_batch=args.days_per_batch,
                dry_run=True,
            ) as pipeline:
                plan = pipeline.preview()
                print(f"Dry-run plan for {site_name}:")
                for k, v in plan.items():
                    print(f"  {k}: {v}")
        return 0

    from canvodpy.cli.dashboard import day_count, make_reporter

    # Resolve every site upfront: date range + receiver-group rows, so a
    # multi-site run shows the full picture from the start.
    site_infos: list[tuple[str, Site, str, str]] = []
    rows: list[tuple[str, str, int]] = []
    for site_name in site_names:
        site = Site(site_name)
        start, end = _resolve_date_range(args, site)
        total = day_count(start, end)
        for group in _site_groups(site):
            rows.append((site_name, group, total))
        site_infos.append((site_name, site, start, end))

    total_days = 0
    total_vod = 0
    t_total = time.perf_counter()

    with make_reporter(rows) as reporter:
        for site_name, site, start, end in site_infos:
            reporter.set_current_site(site_name, start, end)
            reporter.print_header(site_name, start, end, config, args)

            # Resolve VOD analysis pairs for this site
            vod_analyses = site.vod_analyses if not args.no_vod else {}

            if vod_analyses:
                reporter.log(f"  VOD analyses: {list(vod_analyses.keys())}")

            # Access the underlying GnssResearchSite for VOD store writes
            research_site = site._site

            def _on_group_written(group_name: str, _site_name: str = site_name) -> None:
                reporter.advance(_site_name, group_name)

            with site.pipeline(
                n_workers=args.workers,
                days_per_batch=args.days_per_batch,
                dry_run=False,
                on_group_written=_on_group_written,
            ) as pipeline:
                gen = pipeline.process_range(start=start, end=end)
                while True:
                    t_pipeline = time.perf_counter()
                    try:
                        date_key, datasets = next(gen)
                    except StopIteration:
                        break
                    dt_pipeline = time.perf_counter() - t_pipeline

                    total_days += 1
                    reporter.on_day_start(date_key)
                    reporter.on_datasets(datasets)

                    dt_vod = 0.0
                    dt_vod_store = 0.0
                    if vod_analyses:
                        t_vod = time.perf_counter()
                        vod_results = _compute_vod_for_day(
                            datasets, vod_analyses, date_key, reporter
                        )
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

                    reporter.on_timing(dt_pipeline, dt_vod, dt_vod_store)

        dt_total = time.perf_counter() - t_total
        reporter.on_done(total_days, total_vod, dt_total)

    return 0


if __name__ == "__main__":
    sys.exit(main())
