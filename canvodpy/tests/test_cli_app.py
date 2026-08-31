"""Tests for canvodpy's top-level CLI app entry point."""

from __future__ import annotations

import re

from canvodpy.cli.app import main_app
from typer.testing import CliRunner

runner = CliRunner()


class TestVersion:
    def test_version_flag_prints_version_and_exits(self):
        result = runner.invoke(main_app, ["--version"])

        assert result.exit_code == 0
        assert re.match(r"canvodpy \d+\.\d+\.\d+", result.output)

    def test_version_flag_does_not_require_a_subcommand(self):
        result = runner.invoke(main_app, ["--version"])

        assert "Traceback" not in result.output

    def test_no_args_shows_help_not_error(self):
        result = runner.invoke(main_app, [])

        assert "canvodpy CLI tools" in result.output
        assert "Commands" in result.output
