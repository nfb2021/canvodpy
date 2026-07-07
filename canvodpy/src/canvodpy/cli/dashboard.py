"""Pipeline output reporters — plain (non-TTY) and Rich Live (TTY).

Usage
-----
    with make_reporter(site, start, end) as r:
        r.on_day_start(date_key, day_n, total_estimate)
        r.on_datasets(datasets)
        r.on_vod_result(analysis, n_valid, n_total, dt)
        r.on_timing(dt_pipeline, dt_vod, dt_vod_store)
        r.on_done(total_days, total_vod, dt_total)

Non-TTY (cron, CI, pipes): plain print() — identical to pre-dashboard output.
TTY: Rich Live display — header panel + overall progress bar at the bottom of
the terminal; per-day detail scrolls above via live.console.print().

Per-receiver progress bars (the ◉/◎ step labels from §14) are Phase 2 and
require orchestrator event hooks that are not yet wired.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray as xr
    from rich.live import Live
    from rich.progress import TaskID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _day_count(start: str, end: str) -> int:
    """Estimate calendar days between two YYYYDOY strings (inclusive)."""
    parse = lambda s: datetime.strptime(s, "%Y%j")  # noqa: E731
    return max(1, (parse(end) - parse(start)).days + 1)


# ---------------------------------------------------------------------------
# Plain reporter — non-TTY, cron, CI
# ---------------------------------------------------------------------------


class PlainReporter:
    """Writes to stdout via print(). Behaviour identical to pre-dashboard."""

    def log(self, msg: str) -> None:
        print(msg)

    def print_header(self, site: str, start: str, end: str, config, args=None) -> None:
        proc = config.processing.params
        storage = config.processing.storage
        print("=" * 72)
        print(f"canvodpy  site={site}  {start} .. {end}")
        print("=" * 72)
        print(f"  started        {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"  ephemeris      {proc.ephemeris_source}")
        print(f"  keep_vars      {proc.keep_gnss_observables}")
        if args is not None:
            print(f"  days_per_batch {args.days_per_batch or proc.days_per_batch}")
        print(f"  resource_mode  {proc.resource_mode}")
        print(f"  store_strategy {storage.gnss_store_strategy}")
        if args is not None:
            print(f"  gnss_store     {storage.gnss_store_name or 'rinex'}")
            print(f"  vod_store      {storage.vod_store_name or 'vod'}")
            print(f"  vod            {'skip' if args.no_vod else 'enabled'}")
        print()

    def on_day_start(self, date_key: str, day_n: int, total: int) -> None:
        print(f"\n--- {date_key} ---")

    def on_datasets(self, datasets: dict[str, xr.Dataset]) -> None:
        for group, ds in datasets.items():
            e = ds.sizes.get("epoch", 0)
            s = ds.sizes.get("sid", 0)
            print(f"  {group}: {e} epochs × {s} sids")

    def on_vod_result(
        self, analysis: str, n_valid: int, n_total: int, dt: float
    ) -> None:
        pct = 100 * n_valid / n_total if n_total else 0
        print(f"  VOD {analysis}: {n_valid}/{n_total} valid ({pct:.0f}%)  {dt:.1f}s")

    def on_vod_failed(self, analysis: str, error: str) -> None:
        print(f"  VOD {analysis}: FAILED — {error}")

    def on_timing(self, dt_pipeline: float, dt_vod: float, dt_vod_store: float) -> None:
        print(
            f"  pipeline={dt_pipeline:.1f}s"
            f"  vod={dt_vod:.1f}s"
            f"  vod_store={dt_vod_store:.1f}s"
        )

    def on_done(self, total_days: int, total_vod: int, dt_total: float) -> None:
        print()
        print("=" * 72)
        print(
            f"Done  {total_days} days  {total_vod} VOD analyses  {dt_total:.0f}s total"
        )
        print("=" * 72)

    def __enter__(self) -> PlainReporter:
        return self

    def __exit__(self, *_) -> None:
        pass


# ---------------------------------------------------------------------------
# Rich reporter — TTY
# ---------------------------------------------------------------------------


class RichReporter:
    """Rich Live display: header panel + overall progress at the bottom.

    Per-day detail lines are printed above the live region via
    live.console.print(), which Rich handles without flicker.
    """

    def __init__(self, site: str, start: str, end: str) -> None:
        self._site = site
        self._start = start
        self._end = end
        self._total = _day_count(start, end)
        self._day_n = 0
        self._current_day = ""
        self._task_id: TaskID | None = None
        self._live: Live | None = None

        from rich.console import Console
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        self._console = Console()
        self._progress = Progress(
            TextColumn("  [bold]Overall[/bold]"),
            BarColumn(
                bar_width=None,
                complete_style="green3",
                finished_style="dim green",
            ),
            MofNCompleteColumn(),
            TextColumn("[dim]days[/dim]"),
            TimeElapsedColumn(),
            TextColumn("[dim]eta[/dim]"),
            TimeRemainingColumn(),
            console=self._console,
        )

    def _render(self):
        try:
            from rich.group import Group  # rich >= 12.0
        except ImportError:
            from rich.console import Group  # rich < 12.0
        from rich.panel import Panel

        site4 = self._site[:4].upper()
        day_part = (
            f" · day {self._day_n} of {self._total}  {self._current_day}"
            if self._day_n
            else ""
        )
        content = f"─[◉]─  canvod · {site4} · {self._start}–{self._end}{day_part}"
        return Group(
            Panel(content, border_style="dim green", padding=(0, 1)),
            self._progress,
        )

    @property
    def _live_obj(self) -> Live:
        assert self._live is not None, "must be used as a context manager"
        return self._live

    @property
    def _task(self) -> TaskID:
        assert self._task_id is not None, "must be used as a context manager"
        return self._task_id

    def __enter__(self) -> RichReporter:
        from rich.live import Live

        self._task_id = self._progress.add_task("", total=self._total)
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
        )
        self._live.start(refresh=True)
        return self

    def __exit__(self, *_) -> None:
        if self._live is not None:
            self._live.stop()

    def log(self, msg: str) -> None:
        self._live_obj.console.print(msg)

    def print_header(self, site: str, start: str, end: str, config, args=None) -> None:
        proc = config.processing.params
        self._live_obj.console.print(
            f"[dim]  ephemeris={proc.ephemeris_source}"
            f"  resource_mode={proc.resource_mode}"
            f"  strategy={config.processing.storage.gnss_store_strategy}[/dim]"
        )

    def on_day_start(self, date_key: str, day_n: int, total: int) -> None:
        self._day_n = day_n
        self._current_day = date_key
        self._live_obj.update(self._render())
        self._live_obj.console.print(f"\n[bold]─── {date_key}[/bold]")

    def on_datasets(self, datasets: dict[str, xr.Dataset]) -> None:
        for group, ds in datasets.items():
            e = ds.sizes.get("epoch", 0)
            s = ds.sizes.get("sid", 0)
            self._live_obj.console.print(f"  [dim]{group}: {e}×{s}[/dim]")

    def on_vod_result(
        self, analysis: str, n_valid: int, n_total: int, dt: float
    ) -> None:
        pct = 100 * n_valid / n_total if n_total else 0
        self._live_obj.console.print(
            f"  [dim]VOD {analysis}: {n_valid}/{n_total} valid ({pct:.0f}%)  {dt:.1f}s[/dim]"
        )

    def on_vod_failed(self, analysis: str, error: str) -> None:
        self._live_obj.console.print(
            f"[yellow]  VOD {analysis}: FAILED — {error}[/yellow]"
        )

    def on_timing(self, dt_pipeline: float, dt_vod: float, dt_vod_store: float) -> None:
        self._live_obj.console.print(
            f"  [dim]pipeline={dt_pipeline:.1f}s"
            f"  vod={dt_vod:.1f}s"
            f"  vod_store={dt_vod_store:.1f}s[/dim]"
        )
        self._progress.advance(self._task)
        self._live_obj.update(self._render())

    def on_done(self, total_days: int, total_vod: int, dt_total: float) -> None:
        self._live_obj.console.print()
        self._live_obj.console.print(
            f"[bold green]Done  {total_days} days  "
            f"{total_vod} VOD analyses  {dt_total:.0f}s total[/bold green]"
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_reporter(
    site: str,
    start: str,
    end: str,
    *,
    tty: bool | None = None,
) -> PlainReporter | RichReporter:
    """Return a RichReporter when running in a TTY, PlainReporter otherwise."""
    if tty is None:
        tty = sys.stdout.isatty()
    if tty:
        return RichReporter(site, start, end)
    return PlainReporter()
