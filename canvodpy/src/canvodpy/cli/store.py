"""canvodpy store — inspect Icechunk stores from the terminal.

Thin CLI wrappers around canvod-store's existing MyIcechunkStore methods
(print_tree, print_history, plot_commit_graph, print_ops_log,
get_store_stats) — which themselves delegate to icechunk v2's native
ancestry_graph()/ops_log(). No new store-introspection logic here except
_print_group_content, a terminal port of the group-content drill-down that
canvod-store's marimo/Jupyter-only IcechunkStoreViewer renders as HTML.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

store_app = typer.Typer(
    name="store",
    help="Inspect Icechunk stores: list sites, show tree/stats, view commit history.",
    no_args_is_help=True,
)

console = Console()

_STORE_KINDS = ("gnss", "vod")


def _open_store(site_name: str, store_kind: str):
    """Resolve a site + store kind (gnss/vod) to an opened MyIcechunkStore.

    Exits cleanly with an actionable message if the site is unknown or the
    store hasn't been created yet — matches the rest of the CLI's error
    style (config.py, doctor.py), not a raw traceback.
    """
    from canvod.config import load_config
    from canvod.store import MyIcechunkStore

    config = load_config()
    sites = config.sites.sites
    if site_name not in sites:
        console.print(f"[red]❌ Unknown site:[/red] {site_name}")
        known = ", ".join(sites) or "(none configured)"
        console.print(f"  Known sites: {known}")
        raise typer.Exit(1)

    storage = config.processing.storage
    if store_kind == "gnss":
        path = storage.get_gnss_store_path(site_name)
        store_type = "rinex_store"
    else:
        path = storage.get_vod_store_path(site_name)
        store_type = "vod_store"

    if not path.exists():
        console.print(
            f"[yellow]⊘ No {store_kind} store yet for '{site_name}'[/yellow] ({path})"
        )
        raise typer.Exit(1)

    return MyIcechunkStore(path, store_type=store_type)


@store_app.command("list")
def list_stores() -> None:
    """List every configured site's GNSS and VOD store paths and status."""
    from canvod.config import load_config

    config = load_config()
    storage = config.processing.storage
    sites = config.sites.sites

    if not sites:
        console.print("[yellow]No sites configured.[/yellow]")
        return

    table = Table(show_header=True)
    table.add_column("Site")
    table.add_column("Store")
    table.add_column("Path")
    table.add_column("Status")

    path_getters = {
        "gnss": storage.get_gnss_store_path,
        "vod": storage.get_vod_store_path,
    }
    for site_name in sites:
        for kind, get_path in path_getters.items():
            path = get_path(site_name)
            status = (
                "[green]✓ exists[/green]"
                if path.exists()
                else "[dim]not yet created[/dim]"
            )
            table.add_row(site_name, kind, str(path), status)

    console.print(table)


@store_app.command()
def info(
    site: Annotated[str, typer.Argument(help="Site name, as defined in sites.yaml")],
    store: Annotated[
        str, typer.Option("--store", help="Which store: gnss or vod")
    ] = "gnss",
    branch: Annotated[str, typer.Option("--branch", help="Branch to inspect")] = "main",
    group: Annotated[
        str | None,
        typer.Option(
            "--group",
            help="Drill into one group's full content (dataset + metadata table)",
        ),
    ] = None,
) -> None:
    """Show branches, groups, and stats for one site's store."""
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    icestore = _open_store(site, store)
    stats = icestore.get_store_stats()

    console.print(f"\n[bold]{site}[/bold] — {store} store")
    console.print(f"  Path:        {stats['store_path']}")
    console.print(f"  Groups:      {stats['total_groups']}")
    console.print(
        f"  Compression: {stats['compression_algorithm']} (level {stats['compression_level']})\n"
    )

    if group is not None:
        _print_group_content(icestore, group, branch)
    else:
        icestore.print_tree()
        console.print(
            "\n[dim]Use --group <name> to see a group's dataset and metadata table.[/dim]"
        )


def _print_group_content(icestore, group_name: str, branch: str) -> None:
    """Terminal port of IcechunkStoreViewer's per-group HTML drill-down:
    plain-text xarray Dataset repr + metadata table, in a rich.Tree —
    same content, no browser/notebook required."""
    tree = Tree(f"[bold]{group_name}[/bold] (branch: {branch})")

    try:
        ds = icestore.read_group(group_name, branch=branch)
        tree.add(f"[bold]Dataset[/bold]\n{ds}")
    except Exception as e:
        tree.add(f"[red]Failed to load dataset: {e}[/red]")

    try:
        with icestore.readonly_session(branch) as session:
            metadata_df = icestore.load_metadata(session.store, group_name)
        tree.add(
            f"[bold]Metadata table[/bold] ({len(metadata_df)} rows)\n{metadata_df}"
        )
    except Exception:
        pass  # not every group has a metadata table — fine, just skip it

    console.print(tree)


@store_app.command()
def log(
    site: Annotated[str, typer.Argument(help="Site name, as defined in sites.yaml")],
    store: Annotated[
        str, typer.Option("--store", help="Which store: gnss or vod")
    ] = "gnss",
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch", help="Restrict to one branch's linear history (default: all)"
        ),
    ] = None,
    ops: Annotated[
        bool,
        typer.Option(
            "--ops", help="Show the operations audit trail instead of the commit graph"
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Max entries for --ops")] = 50,
) -> None:
    """Show commit history as a graph (or the ops audit trail with --ops)."""
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    icestore = _open_store(site, store)

    if ops:
        icestore.print_ops_log(limit=limit)
    else:
        print(icestore.plot_commit_graph(branch=branch))


@store_app.command()
def maintain(
    site: Annotated[str, typer.Argument(help="Site name, as defined in sites.yaml")],
    store: Annotated[
        str, typer.Option("--store", help="Which store: gnss or vod")
    ] = "gnss",
    expire_days: Annotated[
        int,
        typer.Option(
            "--expire-days",
            help="Snapshot retention window in days (weeks-to-months, not hours)",
        ),
    ] = 90,
    gc: Annotated[
        bool, typer.Option("--gc/--no-gc", help="Run garbage collection")
    ] = True,
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help=(
                "Actually run expiration/GC. Without this flag, only a "
                "dry-run garbage-collect report is shown -- nothing is "
                "deleted or expired."
            ),
        ),
    ] = False,
) -> None:
    """Run store maintenance (expiration + garbage collection).

    Defaults to a **dry run**: reports what garbage collection would delete
    and how many ancestry entries are older than the cutoff, without
    touching anything. Pass --execute to actually expire snapshots and
    (optionally) run garbage collection for real.

    This is an administrative operation -- never safe to run casually
    alongside an active pipeline run on the same store. See
    dev/perf_degradation_findings_2026_07_15.md for the full rationale
    (expiration/GC concurrency caveats, why the default cadence is weeks-
    to-months, and the retention-scheme design this command supports).
    """
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    from datetime import UTC, datetime, timedelta

    icestore = _open_store(site, store)
    cutoff = datetime.now(UTC) - timedelta(days=expire_days)

    if not execute:
        console.print(
            f"\n[bold]{site}[/bold] — {store} store — [yellow]DRY RUN[/yellow] "
            f"(cutoff: {cutoff.isoformat()})\n"
        )

        if gc:
            gc_result = icestore.garbage_collect(days=expire_days, dry_run=True)
            console.print("[bold]Would garbage-collect:[/bold]")
            for key in (
                "bytes_deleted",
                "chunks_deleted",
                "manifests_deleted",
                "snapshots_deleted",
                "attributes_deleted",
                "transaction_logs_deleted",
            ):
                console.print(f"  {key}: {gc_result[key]}")
        else:
            console.print("[dim]--no-gc: skipping garbage-collect dry run.[/dim]")

        stale = sum(
            1
            for snap in icestore.repo.ancestry(branch="main")
            if snap.written_at < cutoff
        )
        console.print(f"\n[bold]Ancestry entries older than cutoff:[/bold] {stale}")
        console.print(
            "\n[dim]Nothing was deleted or expired. Re-run with --execute "
            "to actually run maintenance (after confirming).[/dim]"
        )
        return

    console.print(
        f"\n[bold red]About to run maintenance on {site} ({store} store)[/bold red]"
    )
    console.print(f"  Cutoff: {cutoff.isoformat()} ({expire_days} days)")
    console.print(f"  Garbage collection: {'yes' if gc else 'no'}")
    console.print(
        "\n[yellow]This is an administrative operation. Do not run it while "
        "a pipeline run is active against this store.[/yellow]"
    )
    if not typer.confirm("Proceed?"):
        console.print("Aborted.")
        raise typer.Exit(0)

    results = icestore.maintenance(expire_days=expire_days, run_gc=gc)
    console.print("\n[bold green]Maintenance complete:[/bold green]")
    console.print(f"  Expired snapshots: {results['expired_snapshots']}")
    console.print(f"  Deleted branches:  {results['deleted_branches']}")
    if results["gc_summary"] is not None:
        console.print(f"  GC summary:        {results['gc_summary']}")
