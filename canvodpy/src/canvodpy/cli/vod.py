"""``canvodpy vod`` — compute VOD in bulk from an existing RINEX store.

Thin wrapper around ``VodComputer.compute_bulk()``: reads canopy/reference
data directly from the site's RINEX Icechunk store (rather than inline
during a pipeline run) and writes the result under
``{calculator}/{analysis_name}`` in the VOD store. For backfill/reprocessing
outside of ``canvodpy run`` — see dev/todo_later.md §29.
"""

from __future__ import annotations

import datetime
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def vod(
    site: Annotated[
        str, typer.Option("--site", help="Site name, as defined in sites.yaml")
    ],
    analysis: Annotated[
        str,
        typer.Option(
            "--analysis", help="VOD analysis name, as defined in site.vod_analyses"
        ),
    ],
    start: Annotated[
        str | None,
        typer.Option("--start", help="Start date in YYYYDOY format (e.g. 2025001)."),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="End date in YYYYDOY format (e.g. 2025007)."),
    ] = None,
    calculator: Annotated[
        str,
        typer.Option("--calculator", help="VOD calculator to use."),
    ] = "tau_omega",
) -> None:
    """Compute VOD in bulk from an existing RINEX store and write the result."""
    from canvod.utils.tools import YYYYDOY
    from canvodpy.api import Site
    from canvodpy.vod_computer import VodComputer

    def _to_datetime(yyyydoy: str, *, end_of_day: bool) -> datetime.datetime:
        date_obj = YYYYDOY.from_str(yyyydoy).date
        assert date_obj is not None
        return datetime.datetime.combine(
            date_obj, datetime.time.max if end_of_day else datetime.time.min
        )

    start_dt = _to_datetime(start, end_of_day=False) if start else None
    end_dt = _to_datetime(end, end_of_day=True) if end else None

    site_obj = Site(site)
    if analysis not in site_obj.vod_analyses:
        console.print(f"[red]❌ Unknown VOD analysis:[/red] {analysis}")
        console.print(f"  Available: {list(site_obj.vod_analyses)}")
        raise typer.Exit(1)

    vod_computer = VodComputer(site_obj, calculator=calculator)

    console.print(
        f"Computing VOD for [bold]{site}[/bold]/{analysis} (calculator={calculator})..."
    )
    vod_ds = vod_computer.compute_bulk(analysis, start=start_dt, end=end_dt)

    n_valid = int((~vod_ds["VOD"].isnull()).sum()) if "VOD" in vod_ds else 0
    n_total = vod_ds["VOD"].size if "VOD" in vod_ds else 0
    pct = 100 * n_valid / n_total if n_total else 0
    console.print(
        f"[green]✓[/green] {n_valid}/{n_total} valid VOD values ({pct:.0f}%) "
        f"written to '{calculator}/{analysis}'"
    )


if __name__ == "__main__":
    typer.run(vod)
