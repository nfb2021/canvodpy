"""
CLI for canvodpy configuration management.

Provides commands for:
- Initializing configuration files from templates
- Validating configuration
- Viewing current configuration
- Editing configuration files
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .loader import find_monorepo_root
from .models import ProcessingConfig, SidsConfig, SitesConfig

# Main app
main_app = typer.Typer(
    name="canvodpy",
    help="canvodpy CLI tools",
    no_args_is_help=True,
)

# Config subcommand
config_app = typer.Typer(
    name="config",
    help="Configuration management",
    no_args_is_help=True,
)

console = Console()

# Always use monorepo root config directory
try:
    MONOREPO_ROOT = find_monorepo_root()
    DEFAULT_CONFIG_DIR = MONOREPO_ROOT / "config"
except RuntimeError:
    # Fallback if we can't find monorepo root
    DEFAULT_CONFIG_DIR = Path.cwd() / "config"

CONFIG_DIR_OPTION = typer.Option(
    "--config-dir",
    "-c",
    help="Configuration directory",
)


@config_app.callback()
def config_callback(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Overlay config file applied on top of the main canvod-settings.yaml",
            show_default=False,
        ),
    ] = None,
) -> None:
    if config is not None:
        if not config.exists():
            typer.echo(f"Error: overlay config file not found: {config}", err=True)
            raise typer.Exit(1)
        os.environ["CANVOD_CONFIG_FILE"] = str(config.expanduser().resolve())


@config_app.command()
def init(
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing files",
    ),
) -> None:
    """Initialize configuration from the canvod-settings.yaml template.

    Creates:
      - config/canvod-settings.yaml
      - config/recipes/*.yaml (example naming recipes)

    Parameters
    ----------
    config_dir : Path
        Directory where configuration files are created.
    force : bool
        Overwrite existing files.

    Returns
    -------
    None
    """
    console.print("\n[bold]Initializing canvodpy configuration...[/bold]\n")

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)

    # Get template directory (from monorepo root)
    try:
        monorepo_root = find_monorepo_root()
        template_dir = monorepo_root / "config"
    except RuntimeError:
        # Fallback to path calculation if monorepo root not found
        template_dir = (
            Path(__file__).parent.parent.parent.parent.parent.parent.parent / "config"
        )

    if not template_dir.exists():
        console.print(
            f"[red]❌ Template directory not found: {template_dir}[/red]",
        )
        console.print("\nMake sure you're running from the repository root.")
        raise typer.Exit(1)

    files_created = []
    files_skipped = []

    # Copy unified template (canvod-settings.yaml.example → canvod-settings.yaml)
    canvod_example = template_dir / "canvod-settings.yaml.example"
    canvod_dest = config_dir / "canvod-settings.yaml"
    if canvod_example.exists():
        if canvod_dest.exists() and not force:
            files_skipped.append(canvod_dest)
        else:
            shutil.copy(canvod_example, canvod_dest)
            files_created.append(canvod_dest)
    else:
        console.print(f"[yellow]⚠️  Template not found: {canvod_example}[/yellow]")

    # Copy example recipe files
    recipes_src = template_dir / "recipes"
    recipes_dest = config_dir / "recipes"
    if recipes_src.exists():
        recipes_dest.mkdir(parents=True, exist_ok=True)
        for recipe_file in sorted(recipes_src.glob("*.yaml")):
            dest = recipes_dest / recipe_file.name
            if dest.exists() and not force:
                files_skipped.append(dest)
            else:
                shutil.copy(recipe_file, dest)
                files_created.append(dest)

    # Show results
    if files_created:
        console.print("[green]✓ Created:[/green]")
        for f in files_created:
            console.print(f"  {f}")

    if files_skipped:
        console.print("\n[yellow]⊘ Skipped (already exist):[/yellow]")
        for f in files_skipped:
            console.print(f"  {f}")
        console.print("\n  Use --force to overwrite")

    # Next steps
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit config/canvod-settings.yaml:")
    console.print("     - processing.metadata: fill in author, email, institution")
    console.print("     - processing.storage.stores_root_dir: set your store path")
    console.print("     - sites: replace the example site with your own")
    console.print("  2. For NASA CDDIS access, set this environment variable:")
    console.print(
        "       export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=you@example.com"
    )
    console.print("  3. Edit config/recipes/*.yaml to match your filename format")
    console.print("  4. Run: canvod config validate\n")


@config_app.command()
def validate(
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
) -> None:
    """Validate configuration files.

    Parameters
    ----------
    config_dir : Path
        Directory containing config files.

    Returns
    -------
    None
    """
    from .loader import load_config

    console.print("\n[bold]Validating configuration...[/bold]\n")

    try:
        config = load_config(config_dir)
        console.print("[green]✓ Configuration is valid![/green]\n")

        # Show summary
        console.print(f"  Sites: {len(config.sites.sites)}")
        for name in config.sites.sites.keys():
            console.print(f"    - {name}")

        console.print(f"\n  SID mode: {config.sids.mode}")
        console.print(f"  Agency: {config.processing.aux_data.agency}")

        # Show site data roots
        for name, site in config.sites.sites.items():
            console.print(f"  {name} data root: {site.gnss_site_data_root}")

        # Show credentials from config
        email = config.processing.credentials.nasa_earthdata_acc_mail
        if email:
            console.print(f"  NASA Earthdata email: {email}")
            console.print("  [green]✓ NASA CDDIS enabled[/green]")
        else:
            console.print("  [yellow]⊘ NASA CDDIS disabled (ESA only)[/yellow]")

        console.print()

        # Check receiver directories exist and contain data
        console.print("[bold]Checking receiver directories...[/bold]")
        dir_errors: list[str] = []

        try:
            from canvod.readers.gnss_specs.constants import (
                FORMAT_GLOB_PATTERNS,
                RINEX_OBS_GLOB_PATTERNS,
            )
        except ImportError:
            FORMAT_GLOB_PATTERNS = {}
            RINEX_OBS_GLOB_PATTERNS = ()

        for site_name, site in config.sites.sites.items():
            base_path = site.get_base_path()
            for recv_name, recv in site.receivers.items():
                recv_dir = base_path / recv.directory
                if not recv_dir.exists():
                    msg = f"  [red]❌ {site_name}/{recv_name}: {recv_dir} (directory not found)[/red]"
                    console.print(msg)
                    dir_errors.append(f"{site_name}/{recv_name}")
                    continue

                # Check for any GNSS data files anywhere in the tree
                has_data = False
                if RINEX_OBS_GLOB_PATTERNS:
                    has_data = any(
                        f
                        for pattern in RINEX_OBS_GLOB_PATTERNS
                        for f in recv_dir.rglob(pattern)
                        if f.is_file()
                    )
                else:
                    # Fallback: any file anywhere
                    has_data = any(True for _ in recv_dir.rglob("*") if _.is_file())

                if has_data:
                    # Detect format from files on disk
                    detected_fmt = None
                    if FORMAT_GLOB_PATTERNS:
                        for fmt, patterns in FORMAT_GLOB_PATTERNS.items():
                            if any(
                                f
                                for pat in patterns
                                for f in recv_dir.rglob(pat)
                                if f.is_file()
                            ):
                                detected_fmt = fmt
                                break
                    configured_fmt = recv.reader_format
                    if configured_fmt == "auto" and detected_fmt:
                        fmt_info = f"format: auto \u2192 {detected_fmt}"
                    elif configured_fmt == "auto":
                        fmt_info = "format: auto"
                    else:
                        fmt_info = f"format: {configured_fmt}"
                    console.print(
                        f"  [green]\u2713 {site_name}/{recv_name}: {recv_dir} ({fmt_info})[/green]"
                    )
                else:
                    console.print(
                        f"  [yellow]⚠️  {site_name}/{recv_name}: {recv_dir} "
                        f"(directory exists but no GNSS data files found)[/yellow]"
                    )

        if dir_errors:
            console.print(
                f"\n[red]❌ {len(dir_errors)} receiver director(y/ies) not found.[/red]"
            )
            console.print(
                "  Check gnss_site_data_root and receiver directory settings in canvod-settings.yaml"
            )
            console.print()
            raise typer.Exit(1)

        console.print()

    except Exception as e:
        console.print("[red]❌ Validation failed:[/red]\n")
        console.print(str(e))
        console.print()
        raise typer.Exit(1) from e


@config_app.command()
def show(
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
    section: str = typer.Option(
        None,
        "--section",
        "-s",
        help="Show specific section (processing, sites, sids)",
    ),
) -> None:
    """Display current configuration.

    Parameters
    ----------
    config_dir : Path
        Directory containing config files.
    section : str
        Optional section name (processing, sites, sids).

    Returns
    -------
    None
    """
    from .loader import load_config

    try:
        config = load_config(config_dir)
    except Exception as e:
        console.print(f"\n[red]❌ Error loading config:[/red] {e}\n")
        raise typer.Exit(1) from e

    console.print("\n[bold]Current Configuration[/bold]\n")

    if section == "processing" or section is None:
        _show_processing(config.processing)

    if section == "sites" or section is None:
        _show_sites(config.sites)

    if section == "sids" or section is None:
        _show_sids(config.sids)

    console.print()


@config_app.command()
def edit(
    config_dir: Annotated[Path, CONFIG_DIR_OPTION] = DEFAULT_CONFIG_DIR,
) -> None:
    """Open canvod-settings.yaml in $EDITOR.

    Parameters
    ----------
    config_dir : Path
        Directory containing config files.

    Returns
    -------
    None
    """
    import os

    file_path = config_dir / "canvod-settings.yaml"

    if not file_path.exists():
        console.print(f"[red]File not found:[/red] {file_path}")
        console.print("\nRun: just config-init")
        raise typer.Exit(1)

    editor = os.getenv("EDITOR", "nano")
    subprocess.run([editor, str(file_path)])


def _show_processing(config: ProcessingConfig) -> None:
    """Display processing config.

    Parameters
    ----------
    config : ProcessingConfig
        Processing configuration object.

    Returns
    -------
    None
    """
    console.print("[bold]Processing Configuration:[/bold]")
    table = Table(show_header=False, padding=(0, 2))

    email = config.credentials.nasa_earthdata_acc_mail
    table.add_row(
        "NASA Earthdata Email",
        email or "[yellow]Not set (ESA only)[/yellow]",
    )
    if email:
        table.add_row("FTP Priority", "NASA CDDIS -> ESA (fallback)")
    else:
        table.add_row("FTP Priority", "ESA only")

    table.add_row("Agency", config.aux_data.agency)
    table.add_row("Product Type", config.aux_data.product_type)
    table.add_row("Resource Mode", config.params.resource_mode)
    table.add_row(
        "Max Threads",
        str(config.params.n_max_threads or "auto"),
    )
    table.add_row(
        "Keep GNSS Observables", ", ".join(config.params.keep_gnss_observables)
    )
    table.add_row("Days per Batch", str(config.params.days_per_batch))
    mem_str = (
        f"{config.params.max_memory_gb} GB"
        if config.params.max_memory_gb
        else "[dim]no limit[/dim]"
    )
    table.add_row("Max Memory", mem_str)
    affinity_str = (
        str(config.params.cpu_affinity)
        if config.params.cpu_affinity
        else "[dim]no restriction[/dim]"
    )
    table.add_row("CPU Affinity", affinity_str)
    table.add_row("Nice Priority", str(config.params.nice_priority))
    console.print(table)
    console.print()

    # Storage
    console.print("[bold]Storage:[/bold]")
    st = config.storage
    console.print(f"  Stores root:       {st.stores_root_dir}")
    console.print(f"  GNSS store name:   {st.gnss_store_name}")
    console.print(f"  VOD store name:    {st.vod_store_name}")
    aux_dir = str(st.aux_data_dir) if st.aux_data_dir else "[dim]system temp[/dim]"
    console.print(f"  Aux data dir:      {aux_dir}")
    console.print(f"  GNSS strategy:     {st.gnss_store_strategy}")
    console.print(f"  VOD strategy:      {st.vod_store_strategy}")
    console.print()

    # Icechunk
    ic = config.icechunk
    console.print("[bold]Icechunk:[/bold]")
    console.print(
        f"  Compression:       {ic.compression_algorithm} (level {ic.compression_level})"
    )
    console.print(f"  Inline threshold:  {ic.inline_chunk_threshold_bytes} bytes")
    console.print(f"  Get concurrency:   {ic.get_partial_values_concurrency}")
    for store_name, strategy in ic.chunk_strategies.items():
        console.print(
            f"  Chunks ({store_name}): epoch={strategy.epoch}, sid={strategy.sid}"
        )
    console.print()

    # Logging
    lg = config.logging
    console.print("[bold]Logging:[/bold]")
    log_dir = str(lg.log_dir) if lg.log_dir else "[dim]<monorepo>/.logs[/dim]"
    console.print(f"  Log directory:     {log_dir}")
    console.print(f"  Log file name:     {lg.log_file_name}")
    console.print(f"  Log path depth:    {lg.log_path_depth}")
    console.print()


def _show_sites(config: SitesConfig) -> None:
    """Display sites config.

    Parameters
    ----------
    config : SitesConfig
        Sites configuration object.

    Returns
    -------
    None
    """
    from .loader import load_config as _load_config

    try:
        full_config = _load_config()
        storage = full_config.processing.storage
    except Exception:
        storage = None

    console.print("[bold]Research Sites:[/bold]")

    for site_name, site in config.sites.items():
        base_path = site.get_base_path()

        console.print(f"\n  [bold cyan]{site_name}[/bold cyan]")
        console.print(f"    Data root: {site.gnss_site_data_root}")

        # Store paths
        if storage:
            console.print(f"    GNSS store:  {storage.get_gnss_store_path(site_name)}")
            console.print(f"    VOD store:   {storage.get_vod_store_path(site_name)}")

        # Receivers table
        canopy_names = site.get_canopy_receiver_names()
        ref_names = [n for n, c in site.receivers.items() if c.type == "reference"]

        console.print(
            f"\n    [bold]Receivers[/bold] "
            f"({len(canopy_names)} canopy, {len(ref_names)} reference):"
        )

        for recv_name, recv in site.receivers.items():
            abs_dir = str(base_path / recv.directory)
            type_color = "magenta" if recv.type == "reference" else "blue"
            console.print(
                f"      [green]{recv_name}[/green] "
                f"[{type_color}]({recv.type})[/{type_color}]"
            )
            console.print(f"        dir: {abs_dir}")
            if recv.recipe:
                console.print(f"        recipe: {recv.recipe}")
            if recv.paired_canopies is not None:
                if recv.paired_canopies == "all":
                    console.print(f"        paired_canopies: all -> {canopy_names}")
                else:
                    console.print(f"        paired_canopies: {recv.paired_canopies}")

        # Reference-canopy pairs (expanded from paired_canopies)
        pairs = site.get_reference_canopy_pairs()
        if pairs:
            console.print(
                f"\n    [bold]Reference x Canopy store groups[/bold] ({len(pairs)}):"
            )
            pair_table = Table(
                show_header=True, padding=(0, 1), box=None, pad_edge=False
            )
            pair_table.add_column("Store Group", style="green")
            pair_table.add_column("Reference")
            pair_table.add_column("Position From")

            for ref_name, canopy_name in pairs:
                group_name = f"{ref_name}_{canopy_name}"
                pair_table.add_row(group_name, ref_name, canopy_name)

            console.print(pair_table)

        # VOD analyses
        if site.vod_analyses:
            console.print(
                f"\n    [bold]VOD Analyses[/bold] ({len(site.vod_analyses)}):"
            )
            vod_table = Table(
                show_header=True, padding=(0, 1), box=None, pad_edge=False
            )
            vod_table.add_column("Name", style="green")
            vod_table.add_column("Canopy")
            vod_table.add_column("Reference")

            for analysis_name, analysis in site.vod_analyses.items():
                vod_table.add_row(
                    analysis_name,
                    analysis.canopy_receiver,
                    analysis.reference_receiver,
                )

            console.print(vod_table)


def _show_sids(config: SidsConfig) -> None:
    """Display SIDs config.

    Parameters
    ----------
    config : SidsConfig
        SIDs configuration object.

    Returns
    -------
    None
    """
    console.print("[bold]Signal IDs:[/bold]")
    table = Table(show_header=False)
    table.add_row("Mode", config.mode)
    if config.mode == "preset":
        table.add_row("Preset", config.preset or "")
    elif config.mode == "custom":
        table.add_row("Custom SIDs", f"{len(config.custom_sids)} defined")
    console.print(table)
    console.print()


# Register config subcommand
main_app.add_typer(config_app, name="config")

# ============================================================================
# Stats subcommand
# ============================================================================

stats_app = typer.Typer(
    name="stats",
    help="Streaming statistics management",
    no_args_is_help=True,
)


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
    from .loader import load_config

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
    from .loader import load_config

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
        console.print("Install canvod-ops: uv pip install canvod-ops")
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
    from .loader import load_config

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

    import shutil as _shutil

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


main_app.add_typer(stats_app, name="stats")


def main() -> None:
    """Run the CLI entry point."""
    main_app()


if __name__ == "__main__":
    main()
