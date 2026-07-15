"""Icechunk/Zarr store path and strategy configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from .base import _StrictModel


class StorageConfig(_StrictModel):
    """Storage strategy configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    stores_root_dir: Path = Field(
        ...,
        description=(
            "Directory where canvodpy writes all processed results "
            "(Icechunk/Zarr stores). Must exist and be writable. "
            "Wizard prompt: 'Where should processed results be stored?'"
        ),
    )
    gnss_store_name: str = Field(
        "rinex",
        description="Name of the GNSS observation Icechunk store directory",
    )
    vod_store_name: str = Field(
        "vod",
        description="Name of the VOD Icechunk store directory",
    )
    statistics_store_name: str = Field(
        "statistics",
        description="Name of the statistics Zarr store directory",
    )
    rollup_store_name: str = Field(
        "rollup",
        description="Name of the canvod-streamviz hemigrid rollup Icechunk store directory",
    )
    aux_data_dir: Path | None = Field(
        None,
        description=(
            "Directory for downloaded auxiliary files (SP3, CLK) and "
            "transient Zarr caches. Raw files persist; caches are rebuilt "
            "each run. Defaults to system temp directory if not set."
        ),
    )
    gnss_store_strategy: Literal["skip", "overwrite", "append"] = "skip"
    vod_store_strategy: Literal["skip", "overwrite", "append"] = "overwrite"
    keeper_tags: bool = Field(
        False,
        description=(
            "Tag every (receiver, date) Icechunk commit as "
            "keep/{receiver}/{yyyydoy} so a future retention job can expire "
            "everything else. Default off until create_tag() cost at scale "
            "is confirmed (dev/perf_degradation_findings_2026_07_15.md, "
            "open question 8)."
        ),
    )

    @field_validator("stores_root_dir", mode="before")
    @classmethod
    def validate_stores_dir(cls, v: object) -> object:
        """Expand ~ and reject placeholder values in stores_root_dir."""
        if isinstance(v, str):
            if v.strip() in {"/path/to/stores", "/path/to/your/stores"}:
                raise ValueError(
                    f"stores_root_dir is set to placeholder {v!r} — "
                    "set a real directory path in canvod-settings.yaml"
                )
            return Path(v).expanduser()
        return v

    def get_gnss_store_path(self, site_name: str) -> Path:
        """Get the GNSS observation store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's GNSS observation store.
        """
        return self.stores_root_dir / site_name / self.gnss_store_name

    def get_rinex_store_path(self, site_name: str) -> Path:
        """Deprecated: use get_gnss_store_path instead."""
        import warnings

        warnings.warn(
            "StorageConfig.get_rinex_store_path is deprecated; use get_gnss_store_path",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_gnss_store_path(site_name)

    def get_vod_store_path(self, site_name: str) -> Path:
        """Get the VOD store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's VOD store.
        """
        return self.stores_root_dir / site_name / self.vod_store_name

    def get_statistics_store_path(self, site_name: str) -> Path:
        """Get the statistics store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's statistics store.
        """
        return self.stores_root_dir / site_name / self.statistics_store_name

    def get_rollup_store_path(self, site_name: str) -> Path:
        """Get the canvod-streamviz rollup store path for a site.

        Parameters
        ----------
        site_name : str
            Site name.

        Returns
        -------
        Path
            Path to the site's hemigrid rollup store.
        """
        return self.stores_root_dir / site_name / self.rollup_store_name

    def get_aux_data_dir(self) -> Path:
        """Get the directory for auxiliary data files.

        Returns
        -------
        Path
            Aux data directory (configured or system temp).
        """
        if self.aux_data_dir is not None:
            self.aux_data_dir.mkdir(parents=True, exist_ok=True)
            return self.aux_data_dir
        from tempfile import gettempdir

        return Path(gettempdir())
