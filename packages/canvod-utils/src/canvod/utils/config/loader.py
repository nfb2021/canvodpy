"""
Configuration loader for canvodpy.

Loads configuration from multiple YAML files with priority:
1. Package defaults (lowest priority)
2. User configuration files (highest priority)
"""

import functools
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import CanvodConfig, ProcessingConfig, SidsConfig, SitesConfig


def find_monorepo_root() -> Path:
    """Find the monorepo root by looking for a .git directory.

    Returns
    -------
    Path
        Monorepo root directory.

    Raises
    ------
    RuntimeError
        If the monorepo root cannot be found.
    """
    current = Path.cwd().resolve()

    # Walk up directory tree looking for .git directory (not file).
    for parent in [current, *list(current.parents)]:
        git_path = parent / ".git"
        if git_path.exists() and git_path.is_dir():
            return parent

    # Fallback: if this file is in
    # packages/canvod-utils/src/canvod/utils/config/loader.py then monorepo root
    # is 7 levels up.
    try:
        loader_file = Path(__file__).resolve()
        # loader.py -> config -> utils -> canvod -> src -> canvod-utils ->
        # packages -> root.
        monorepo_root = loader_file.parent.parent.parent.parent.parent.parent.parent
        git_path = monorepo_root / ".git"
        if git_path.exists() and git_path.is_dir():
            return monorepo_root
    except Exception:
        pass

    raise RuntimeError("Cannot find monorepo root (no .git directory found)")


class ConfigLoader:
    """
    Load and merge configuration from YAML files.

    Parameters
    ----------
    config_dir : Path | None, optional
        Directory containing config files. If None, uses monorepo_root/config.
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        """Initialize the loader with an optional config directory.

        Parameters
        ----------
        config_dir : Path | None, optional
            Directory containing config files. If None, uses the monorepo
            root config directory or a local fallback.
        """
        if config_dir is None:
            try:
                monorepo_root = find_monorepo_root()
                config_dir = monorepo_root / "config"
            except RuntimeError:
                # Fallback if monorepo root cannot be found
                config_dir = Path.cwd() / "config"

        self.config_dir = Path(config_dir)
        self.defaults_dir = Path(__file__).parent / "defaults"

    def load(self) -> CanvodConfig:
        """
        Load complete configuration.

        Priority: Package defaults < User config files

        Returns
        -------
        CanvodConfig
            Validated configuration object.

        Raises
        ------
        SystemExit
            If configuration is invalid or required files are missing.
        """
        # Load each section
        processing = self._load_processing()
        sites = self._load_sites()
        sids = self._load_sids()

        # Build complete config
        try:
            config = CanvodConfig(
                processing=processing,
                sites=sites,
                sids=sids,
            )
        except ValidationError as e:
            self._show_validation_error(e)
            sys.exit(1)

        return config

    def _load_processing(self) -> ProcessingConfig:
        """Load processing config with merge."""
        # Load defaults
        defaults = self._load_yaml(self.defaults_dir / "processing.yaml")

        # Load user config (if exists)
        user_file = self.config_dir / "processing.yaml"
        if user_file.exists():
            user_config = self._load_yaml(user_file)
            defaults = self._deep_merge(defaults, user_config)
        else:
            print(f"\n⚠️  Warning: {user_file} not found, using defaults")
            print("   Run: just config-init\n")

        return ProcessingConfig(**defaults)

    def _load_sites(self) -> SitesConfig:
        """Load sites config.

        Returns an empty SitesConfig if sites.yaml is missing (e.g. CI, tests).
        """
        user_file = self.config_dir / "sites.yaml"

        if not user_file.exists():
            print(f"\n⚠️  Warning: {user_file} not found, no sites configured")
            print("   Run: just config-init\n")
            return SitesConfig(sites={})

        data = self._load_yaml(user_file)
        return SitesConfig(**data)

    def _load_sids(self) -> SidsConfig:
        """Load SIDs config with defaults."""
        defaults = self._load_yaml(self.defaults_dir / "sids.yaml")

        user_file = self.config_dir / "sids.yaml"
        if user_file.exists():
            user_config = self._load_yaml(user_file)
            defaults = self._deep_merge(defaults, user_config)

        return SidsConfig(**defaults)

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """
        Load YAML file.

        Parameters
        ----------
        path : Path
            Path to YAML file.

        Returns
        -------
        dict[str, Any]
            YAML content (empty dict if file empty).
        """
        with open(path) as f:
            return yaml.safe_load(f) or {}

    def _deep_merge(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Deep merge override dictionary into base dictionary.

        Parameters
        ----------
        base : dict[str, Any]
            Base dictionary.
        override : dict[str, Any]
            Override dictionary.

        Returns
        -------
        dict[str, Any]
            Merged dictionary.
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _show_validation_error(self, error: ValidationError) -> None:
        """Show a user-friendly validation error.

        Parameters
        ----------
        error : ValidationError
            Validation error raised by Pydantic.

        Returns
        -------
        None
        """
        print("\n" + "=" * 70)
        print("❌ Configuration Validation Error")
        print("=" * 70)
        print(f"\nConfig directory: {self.config_dir}\n")
        print(error)
        print("\n" + "=" * 70)


@functools.lru_cache(maxsize=8)
def load_config(config_dir: Path | None = None) -> CanvodConfig:
    """
    Load configuration from YAML files.

    This is the main entry point for loading configuration.

    Parameters
    ----------
    config_dir : Path | None, optional
        Directory containing config files. If None, automatically finds
        monorepo root and uses {monorepo_root}/config.

    Returns
    -------
    CanvodConfig
        Validated configuration object.

    Examples
    --------
    >>> from canvod.utils.config import load_config
    >>> config = load_config()
    >>> print(config.nasa_earthdata_acc_mail)
    >>> print(config.processing.aux_data.agency)
    """
    if config_dir is None:
        env_dir = os.environ.get("CANVOD_CONFIG_DIR")
        if env_dir:
            config_dir = Path(env_dir)
    loader = ConfigLoader(config_dir)
    return loader.load()
