"""canvodpy console-script entry point.

Composes the config/stats/run subcommands into a single Typer app. All CLI
code lives in this package — the entry point, ``config``, ``stats``, and
``run`` — matching where the rest of canvodpy's user-facing surface
(``Site``, ``Pipeline``, the functional API) already lives.
"""

import typer

main_app = typer.Typer(
    name="canvodpy",
    help="canvodpy CLI tools",
    no_args_is_help=True,
)

from canvodpy.cli.config import config_app  # noqa: E402
from canvodpy.cli.run import main as _run_main  # noqa: E402
from canvodpy.cli.stats import stats_app  # noqa: E402

main_app.add_typer(config_app, name="config")
main_app.add_typer(stats_app, name="stats")


@main_app.command(
    "run",
    help="Process GNSS observations into Icechunk stores and compute VOD.",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
    add_help_option=False,
)
def run_cmd(ctx: typer.Context) -> None:
    raise typer.Exit(code=_run_main(ctx.args))


def main() -> None:
    """Run the CLI entry point."""
    main_app()


if __name__ == "__main__":
    main()
