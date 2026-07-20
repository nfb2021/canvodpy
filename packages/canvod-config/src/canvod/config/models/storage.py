"""Icechunk/Zarr store path and strategy configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from .base import _StrictModel


class MaintenanceConfig(_StrictModel):
    """Scheduled Icechunk maintenance (expiration + garbage collection).

    Completes the retention scheme from dev/perf_degradation_findings_
    2026_07_15.md (Problem B): expire_old_snapshots()/garbage_collect()
    already exist on MyIcechunkStore and work correctly, but nothing has
    ever triggered them automatically -- this is the config surface for
    `canvodpy store maintain-due`, a non-interactive, cron-safe entry
    point (the existing `canvodpy store maintain` command requires an
    interactive typer.confirm, so it cannot itself run unattended).

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    enabled: bool = Field(
        False,
        description=(
            "Master switch for `canvodpy store maintain-due`. Off by "
            "default -- mirrors keeper_tags' precedent of shipping inert "
            "until validated against a real store (see "
            "dev/perf_degradation_findings_2026_07_15.md, open question 4: "
            "garbage_collect(dry_run=True) should be checked against the "
            "real store before this is ever enabled for real)."
        ),
    )
    dry_run_until_confirmed: bool = Field(
        True,
        description=(
            "Force every `maintain-due` invocation to dry-run only, "
            "regardless of due-ness, until explicitly set False per "
            "deployment. The interactive CLI's `maintain --execute` "
            "requires a typer.confirm a cron job can't answer; this is "
            "the config-level equivalent gate for the unattended path."
        ),
    )
    retention_days: int = Field(
        90,
        ge=7,
        description=(
            "Snapshot retention window passed to expire_old_snapshots()/ "
            "garbage_collect() by the scheduled job (weeks-to-months, a "
            "generous margin past any realistic write-session duration). "
            "Mirrors MyIcechunkStore.maintenance()'s own default; kept "
            "separate so a human running `maintain --expire-days` "
            "interactively is unaffected by this value."
        ),
    )
    expire_interval_days: int = Field(
        45,
        ge=1,
        description=(
            "How often (wall-clock days since the most recent "
            "ExpirationRan entry in the store's own ops log) the "
            "scheduled job re-runs expiration. Skill-doc guidance: every "
            "1-2 months."
        ),
    )
    gc_delay_days: int = Field(
        20,
        ge=1,
        description=(
            "Extra days to wait after the most recent expiration before "
            "running garbage_collect(), so physical deletion always lags "
            "the (reversible-in-effect) soft-delete by a safety buffer. "
            "Skill-doc guidance: GC every 15-30 days, offset from expire."
        ),
    )


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
    shared_aux_cache_dir: Path | None = Field(
        None,
        description=(
            "Network-wide, fingerprint-keyed aux (SP3/CLK Hermite) cache "
            "root (dev/todo_later.md §44). None (default) = disabled, falls "
            "back to per-site aux_data_dir/aux_{date}.zarr, rebuilt every "
            "run. Ephemeris products are satellite-based, not site-based, "
            "so pointing multiple sites at the same path lets them share "
            "one cache entry per (agency, product, date) instead of each "
            "rebuilding it independently."
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
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)

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

    def get_shared_aux_cache_dir(self) -> Path | None:
        """Get the network-wide shared aux cache directory, if configured.

        Returns
        -------
        Path | None
            The configured shared cache root, created if missing, or
            ``None`` when the feature is disabled (default).
        """
        if self.shared_aux_cache_dir is None:
            return None
        self.shared_aux_cache_dir.mkdir(parents=True, exist_ok=True)
        return self.shared_aux_cache_dir
