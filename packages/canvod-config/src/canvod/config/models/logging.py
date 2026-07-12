"""Logging configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from .base import _StrictModel


class LoggingConfig(_StrictModel):
    """Logging configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    log_dir: Path | None = Field(
        None,
        description=(
            "Directory for log files. "
            "Defaults to .logs/ next to config directory if not set."
        ),
    )
    log_file_name: str = Field(
        "canvodpy.log",
        description="Name of the main log file",
    )
    log_path_depth: int = Field(
        6,
        ge=1,
        le=20,
        description="Number of path components to include in log file references",
    )

    def get_log_dir(self) -> Path:
        """Get the effective log directory, creating it if needed.

        Returns
        -------
        Path
            Log directory path.
        """
        if self.log_dir is not None:
            d = self.log_dir
        else:
            # Default: .logs/ next to the config directory (monorepo root)
            from ..loader import find_monorepo_root

            d = find_monorepo_root() / ".logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_log_file(self) -> Path:
        """Get the full path to the main log file.

        Returns
        -------
        Path
            Log file path.
        """
        return self.get_log_dir() / self.log_file_name
