"""CLI for canvod-ops streaming statistics management."""

import shutil as _shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from canvodpy.cli.config import CONFIG_DIR_OPTION, DEFAULT_CONFIG_DIR

stats_app = typer.Typer(
    name="stats",
    help="Streaming statistics management",
    no_args_is_help=True,
)

console = Console()


@stats_app.command("compute")
def stats_compute(
    site: str = typer.Argument(..., help="Site name"),
    receiver: str = typer.Argument(..., help="Receiver name"),
    from_date: str | None = typer.Option(
        None, "--from", help="Start date (YYYY-MM-DD)"
    ),
    to_date: str | None = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
) -> None:
    """Compute streaming statistics for a site/receiver.

    Loads data, runs the UpdateStatistics pipeline, and saves results
    to the statistics Zarr store.
    """
    from canvod.config.loader import load_config

    try:
        config = load_config(config_dir)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise typer.Exit(1) from e

    site_config = config.sites.sites.get(site)
    if site_config is None:
        console.print(f"[red]Unknown site:[/red] {site}")
        console.print(f"Available: {list(config.sites.sites.keys())}")
        raise typer.Exit(1)

    if receiver not in site_config.receivers:
        console.print(f"[red]Unknown receiver:[/red] {receiver}")
        console.print(f"Available: {list(site_config.receivers.keys())}")
        raise typer.Exit(1)

    recv_config = site_config.receivers[receiver]
    store_path = config.processing.storage.get_statistics_store_path(site)

    console.print(f"\n[bold]Computing statistics for {site}/{receiver}[/bold]")
    console.print(f"  Store path: {store_path}")
    console.print(f"  Receiver type: {recv_config.type}")
    if from_date:
        console.print(f"  From: {from_date}")
    if to_date:
        console.print(f"  To: {to_date}")

    console.print(
        "\n[yellow]Not yet implemented — pipeline integration pending.[/yellow]"
    )
    console.print("Use the Python API directly:")
    console.print("  from canvod.ops import build_statistics_pipeline, ProfileRegistry")
    console.print()


@stats_app.command("show")
def stats_show(
    site: str = typer.Argument(..., help="Site name"),
    receiver_type: str | None = typer.Option(
        None, "--receiver", "-r", help="Receiver type filter"
    ),
    variable: str | None = typer.Option(
        None, "--variable", "-v", help="Variable filter"
    ),
    cell: int | None = typer.Option(None, "--cell", "-c", help="Cell ID filter"),
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
) -> None:
    """Display stored statistics for a site."""
    from canvod.config.loader import load_config

    try:
        config = load_config(config_dir)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise typer.Exit(1) from e

    store_path = config.processing.storage.get_statistics_store_path(site)

    if not store_path.exists():
        console.print(f"[yellow]No statistics store found at {store_path}[/yellow]")
        raise typer.Exit(0)

    try:
        import zarr

        from canvod.ops.statistics.store import (
            StatisticsStore,  # type: ignore[unresolved-import]
        )

        root = zarr.open_group(str(store_path), mode="r")
        store = StatisticsStore(root)
        rx_types = store.list_receiver_types()

        if not rx_types:
            console.print("[yellow]No statistics data found.[/yellow]")
            raise typer.Exit(0)

        console.print(f"\n[bold]Statistics for site: {site}[/bold]")
        console.print(f"  Store: {store_path}")
        console.print(f"  Receiver types: {rx_types}\n")

        for rx in rx_types:
            if receiver_type and rx != receiver_type:
                continue

            registry = store.load(rx)
            summary = registry.summary()

            console.print(f"  [bold cyan]{rx}[/bold cyan]")

            table = Table(show_header=True, padding=(0, 1))
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Keys", str(summary["n_keys"]))
            table.add_row(
                "Total observations", str(summary.get("total_observations", 0))
            )
            table.add_row("Variables", ", ".join(summary.get("variables", [])))
            table.add_row("Cells", str(summary.get("n_cells", 0)))
            table.add_row("GK epsilon", str(summary.get("gk_epsilon", "N/A")))
            console.print(table)
            console.print()

    except ImportError as e:
        console.print(f"[red]Missing dependency:[/red] {e}")
        console.print("canvod.ops.statistics is not yet implemented.")
        raise typer.Exit(1) from e


@stats_app.command("reset")
def stats_reset(
    site: str = typer.Argument(..., help="Site name"),
    receiver_type: str | None = typer.Option(
        None, "--receiver", "-r", help="Reset specific receiver type only"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
) -> None:
    """Delete the statistics store for a site."""
    from canvod.config.loader import load_config

    try:
        config = load_config(config_dir)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise typer.Exit(1) from e

    store_path = config.processing.storage.get_statistics_store_path(site)

    if not store_path.exists():
        console.print(f"[yellow]No statistics store at {store_path}[/yellow]")
        raise typer.Exit(0)

    target = f"{store_path}/{receiver_type}" if receiver_type else str(store_path)

    if not yes:
        confirm = typer.confirm(f"Delete statistics at {target}?")
        if not confirm:
            console.print("Aborted.")
            raise typer.Exit(0)

    if receiver_type:
        rx_path = store_path / receiver_type
        if rx_path.exists():
            _shutil.rmtree(rx_path)
            console.print(f"[green]Deleted {rx_path}[/green]")
        else:
            console.print(f"[yellow]No data for receiver type {receiver_type}[/yellow]")
    else:
        _shutil.rmtree(store_path)
        console.print(f"[green]Deleted {store_path}[/green]")
