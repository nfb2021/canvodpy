"""Tests for canvodpy's config CLI, focused on the --interactive wizard."""

from __future__ import annotations

import canvodpy.cli.config as cfg
import typer
from typer.testing import CliRunner

runner = CliRunner()


def _app() -> typer.Typer:
    app = typer.Typer()
    app.add_typer(cfg.config_app, name="config")
    return app


def _run_wizard(config_dir, answers: str, force: bool = False):
    args = ["config", "init", "--config-dir", str(config_dir), "--interactive"]
    if force:
        args.append("--force")
    return runner.invoke(_app(), args, input=answers)


class TestInteractiveWizard:
    def test_writes_all_answers_and_validates_cleanly(self, tmp_path):
        config_dir = tmp_path / "config"
        answers = (
            "Nicolas Bader\n"
            "nico@example.com\n"
            "TU Wien\n"
            f"{tmp_path / 'stores'}\n"
            "Rosalia\n"
            f"{tmp_path / 'data'}\n"
            "custom_canopy\n"
            "custom_reference\n"
        )
        result = _run_wizard(config_dir, answers)

        assert result.exit_code == 0, result.output
        assert "Configuration is valid" in result.output

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert "author: Nicolas Bader" in text
        assert "email: nico@example.com" in text
        assert "institution: TU Wien" in text
        assert f"stores_root_dir: {tmp_path / 'stores'}" in text
        assert "  Rosalia:" in text
        assert f"gnss_site_data_root: {tmp_path / 'data'}" in text
        assert "directory: custom_canopy" in text
        assert "directory: custom_reference" in text

    def test_preserves_template_comments(self, tmp_path):
        """A full YAML parse/re-dump would strip these — must survive."""
        config_dir = tmp_path / "config"
        answers = f"A\nb@example.com\nC\n{tmp_path / 's'}\nSite\n{tmp_path / 'd'}\n\n\n"
        _run_wizard(config_dir, answers)

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert (
            "# ============================================================================="
            in text
        )
        assert "SID Format: PRN|Band|Code" in text

    def test_does_not_touch_commented_example_block(self, tmp_path):
        """The commented-out 'my_second_site' illustration must stay verbatim."""
        config_dir = tmp_path / "config"
        answers = f"A\nb@example.com\nC\n{tmp_path / 's'}\nSite\n{tmp_path / 'd'}\n\n\n"
        _run_wizard(config_dir, answers)

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert "#       directory: 01_reference" in text
        assert "#       directory: 02_canopy" in text

    def test_default_receiver_directories_when_answer_blank(self, tmp_path):
        config_dir = tmp_path / "config"
        answers = f"A\nb@example.com\nC\n{tmp_path / 's'}\nSite\n{tmp_path / 'd'}\n\n\n"
        _run_wizard(config_dir, answers)

        text = (config_dir / "canvod-settings.yaml").read_text()
        assert "directory: 02_canopy" in text
        assert "directory: 01_reference" in text

    def test_skips_wizard_when_config_already_exists(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        existing = config_dir / "canvod-settings.yaml"
        existing.write_text("# hand-edited, do not touch\n")

        result = _run_wizard(config_dir, answers="")

        assert result.exit_code == 0
        assert "skipping interactive setup" in result.output
        assert existing.read_text() == "# hand-edited, do not touch\n"

    def test_reports_actionable_error_for_bad_answer(self, tmp_path):
        """An answer that fails Pydantic validation shows the clean
        field-path report (format_validation_error), not a traceback."""
        config_dir = tmp_path / "config"
        answers = (
            "Your Name\n"  # still-placeholder value — same validator #4 fixed
            "b@example.com\n"
            "C\n"
            f"{tmp_path / 's'}\n"
            "Site\n"
            f"{tmp_path / 'd'}\n"
            "\n\n"
        )
        result = _run_wizard(config_dir, answers)

        assert result.exit_code == 0
        assert "still need attention" in result.output
        assert "metadata.author" in result.output
        assert "Traceback" not in result.output
