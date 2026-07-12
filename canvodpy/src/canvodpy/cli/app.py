"""canvodpy console-script entry point.

Composes the config/stats/run/doctor subcommands into a single Typer app.
All CLI code lives in this package — the entry point, ``config``, ``stats``,
``run``, and ``doctor`` — matching where the rest of canvodpy's user-facing
surface (``Site``, ``Pipeline``, the functional API) already lives.
"""

import typer

main_app = typer.Typer(
    name="canvodpy",
    help="canvodpy CLI tools",
    no_args_is_help=True,
)

from canvodpy.cli.config import config_app  # noqa: E402
from canvodpy.cli.doctor import doctor as doctor_command  # noqa: E402
from canvodpy.cli.run import run as run_command  # noqa: E402
from canvodpy.cli.stats import stats_app  # noqa: E402

main_app.add_typer(config_app, name="config")
main_app.add_typer(stats_app, name="stats")
main_app.command("run")(run_command)
main_app.command(
    "doctor", help="Report canvodpy's version, environment, and config resolution."
)(doctor_command)


def main() -> None:
    """Run the CLI entry point."""
    main_app()


if __name__ == "__main__":
    main()
