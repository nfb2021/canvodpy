"""canvodpy CLI — process GNSS observations and compute VOD.

Usage
-----
    # Process a specific range
    uv run canvodpy run --site ExampleSite --start 2025001 --end 2025007

    # Process new data only (auto-detect start from store, end = today)
    uv run canvodpy run --site ExampleSite

    # Multiple sites in one invocation (processed sequentially) — repeat the flag
    uv run canvodpy run --site ExampleSite --site OtherSite

    # Cron: run daily, picks up new data automatically
    # 0 3 * * * cd /path/to/canvodpy && uv run canvodpy run --site ExampleSite

    # Observation ingestion only, no VOD
    uv run canvodpy run --site ExampleSite --no-vod

    # Preview what would be processed
    uv run canvodpy run --site ExampleSite --dry-run
"""

from __future__ import annotations

import enum
import os
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated

import numpy as np
import structlog
import typer
import xarray as xr

from canvodpy.logging import emit_run_summary
from canvodpy.logging.run_context import reset_run_id, set_run_id
from canvodpy.logging.stage_timer import reset_run_stats

log = structlog.get_logger(__name__)


def _build_vod_calculator_choice() -> type[enum.StrEnum]:
    """Build the VOD-calculator choice enum from the live factory registry.

    A dynamic StrEnum: Typer renders it as a restricted choice in --help,
    while downstream code can keep treating the value as a plain string
    (calculator_name=args.vod_calculator works unchanged).
    """
    from canvodpy.factories import VODFactory

    names = VODFactory.list_available()
    return enum.StrEnum("VodCalculatorChoice", {name: name for name in names})


VodCalculatorChoice = _build_vod_calculator_choice()


class EphemerisSourceChoice(enum.StrEnum):
    final = "final"
    broadcast = "broadcast"


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
    calculator_name: str = "tau_omega",
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
    calculator_name
        Name registered in ``VODFactory`` (e.g. ``"tau_omega"``).

    Returns
    -------
    dict mapping analysis name to VOD dataset.
    """
    from canvodpy.factories import VODFactory

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
            canopy_ds, ref_ds = xr.align(canopy_ds, ref_ds, join="inner")
            calculator = VODFactory.create(
                calculator_name, canopy_ds=canopy_ds, sky_ds=ref_ds
            )
            vod_ds = calculator.calculate_vod()

            # Rechunk + clear encoding for clean Icechunk writes
            vod_ds = vod_ds.chunk({"epoch": 17280, "sid": -1})
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


def _main_impl(args: SimpleNamespace) -> int:
    from pathlib import Path

    from canvod.config import load_config
    from canvod.config.loader import ConfigValidationError, format_validation_error

    config_file: Path | None = None
    if args.config is not None:
        config_file = Path(args.config)
        if not config_file.exists():
            print(
                f"Error: overlay config file not found: {config_file}", file=sys.stderr
            )
            return 1
        os.environ["CANVOD_CONFIG_FILE"] = str(config_file.expanduser().resolve())

    try:
        config = load_config(config_file=config_file)
    except ConfigValidationError as e:
        print(format_validation_error(e), file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.ephemeris_source is not None:
        config.processing.params.ephemeris_source = args.ephemeris_source

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
            # One run_id per site: failures are site-scoped, and this keeps
            # correlation with Icechunk commits (also per-site-store) clean.
            run_id = f"{site_name}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
            run_id_token = set_run_id(run_id)
            last_good_date_key: str | None = None
            stage = "site_init"
            site_days = 0
            site_vod = 0

            try:
                reporter.set_current_site(site_name, start, end)
                reporter.print_header(site_name, start, end, config, args)

                # Resolve VOD analysis pairs for this site
                vod_analyses = site.vod_analyses if not args.no_vod else {}

                if vod_analyses:
                    reporter.log(f"  VOD analyses: {list(vod_analyses.keys())}")

                # Access the underlying GnssResearchSite for VOD store writes
                research_site = site._site

                def _on_group_written(
                    group_name: str, _site_name: str = site_name
                ) -> None:
                    reporter.advance(_site_name, group_name)

                stage = "pipeline_process"
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
                        site_days += 1
                        reporter.on_day_start(date_key)
                        reporter.on_datasets(datasets)

                        dt_vod = 0.0
                        dt_vod_store = 0.0
                        if vod_analyses:
                            stage = "vod_calc"
                            t_vod = time.perf_counter()
                            vod_results = _compute_vod_for_day(
                                datasets,
                                vod_analyses,
                                date_key,
                                reporter,
                                calculator_name=args.vod_calculator,
                            )
                            dt_vod = time.perf_counter() - t_vod

                            stage = "vod_store"
                            t_vod_store = time.perf_counter()
                            for analysis_name, vod_ds in vod_results.items():
                                research_site.store_vod_analysis(
                                    vod_dataset=vod_ds,
                                    analysis_name=analysis_name,
                                    commit_message=f"VOD {analysis_name} {date_key}",
                                )
                            dt_vod_store = time.perf_counter() - t_vod_store
                            total_vod += len(vod_results)
                            site_vod += len(vod_results)

                        reporter.on_timing(dt_pipeline, dt_vod, dt_vod_store)
                        last_good_date_key = date_key
                        stage = "pipeline_process"

                emit_run_summary(site=site_name, days=site_days, vod_results=site_vod)
            except Exception:
                # See module docstring / logging/run_context.py: this runs
                # unattended on remote machines, so the log at the moment of
                # failure is the only forensic evidence that will exist.
                log.error(
                    "run_crashed",
                    site=site_name,
                    stage=stage,
                    last_good_date_key=last_good_date_key,
                    exc_info=True,
                )
                emit_run_summary(
                    site=site_name,
                    days=site_days,
                    vod_results=site_vod,
                    crashed=True,
                )
                raise
            finally:
                reset_run_stats(run_id)
                reset_run_id(run_id_token)

        dt_total = time.perf_counter() - t_total
        reporter.on_done(total_days, total_vod, dt_total)

    return 0


def run(
    site: Annotated[
        list[str],
        typer.Option(
            "--site",
            help=(
                "Site name as defined in sites.yaml (e.g. ExampleSite). Repeat "
                "the flag for multiple sites — processed sequentially."
            ),
        ),
    ],
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help=(
                "Start date in YYYYDOY format (e.g. 2025001). If omitted, "
                "resumes from the last processed date in the store."
            ),
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(
            "--end",
            help="End date in YYYYDOY format (e.g. 2025007). If omitted, processes up to today.",
        ),
    ] = None,
    no_vod: Annotated[
        bool,
        typer.Option(
            "--no-vod/--vod",
            help="Skip VOD calculation (only ingest observations).",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Preview processing plan without executing.",
        ),
    ] = False,
    workers: Annotated[
        int | None,
        typer.Option(
            "--workers", help="Number of Dask workers (default: from config)."
        ),
    ] = None,
    days_per_batch: Annotated[
        int | None,
        typer.Option(
            "--days-per-batch",
            help="Number of DOYs per loky wave (default: from config).",
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Overlay config YAML applied on top of the main canvod-settings.yaml.",
        ),
    ] = None,
    ephemeris_source: Annotated[
        EphemerisSourceChoice | None,
        typer.Option(
            "--ephemeris-source",
            help=(
                "Override the configured ephemeris source ('final' = agency "
                "SP3/CLK, 'broadcast' = SBF SatVisibility). Default: from "
                "canvod-settings.yaml."
            ),
        ),
    ] = None,
    vod_calculator: Annotated[
        VodCalculatorChoice,
        typer.Option("--vod-calculator", help="VOD calculator to use."),
    ] = VodCalculatorChoice["tau_omega"],
) -> None:
    """Process GNSS observations into Icechunk stores and compute VOD."""
    args = SimpleNamespace(
        site=site,
        start=start,
        end=end,
        no_vod=no_vod,
        dry_run=dry_run,
        workers=workers,
        days_per_batch=days_per_batch,
        config=config,
        ephemeris_source=ephemeris_source.value if ephemeris_source else None,
        vod_calculator=vod_calculator.value,
    )
    raise typer.Exit(code=_main_impl(args))


if __name__ == "__main__":
    typer.run(run)
