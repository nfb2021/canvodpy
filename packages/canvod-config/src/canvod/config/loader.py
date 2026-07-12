"""Configuration loader for canvodpy."""

import functools
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import CanvodConfig, ProcessingConfig, SidsConfig, SitesConfig

logger = logging.getLogger("canvod.config")


class ConfigValidationError(ValueError):
    """Raised when configuration YAML fails Pydantic validation.

    Attributes
    ----------
    validation_error : ValidationError
        The underlying Pydantic validation error.
    config_dir : Path
        The config directory that was loaded.
    """

    def __init__(self, error: ValidationError, config_dir: Path) -> None:
        self.validation_error = error
        self.config_dir = config_dir
        super().__init__(str(error))


def find_monorepo_root() -> Path:
    """Find the monorepo root by looking for a .git entry.

    A repo root's ``.git`` is a directory for a normal clone, but a file
    (containing a ``gitdir:`` pointer) for a git worktree or submodule — both
    are valid roots, so any ``.git`` entry (file or directory) counts.

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

    # Walk up directory tree looking for a .git entry (directory or file).
    for parent in [current, *list(current.parents)]:
        git_path = parent / ".git"
        if git_path.exists():
            return parent

    # Fallback: if this file is in
    # packages/canvod-config/src/canvod/config/loader.py then monorepo root
    # is 6 levels up.
    try:
        loader_file = Path(__file__).resolve()
        # loader.py -> config -> canvod -> src -> canvod-config ->
        # packages -> root.
        monorepo_root = loader_file.parent.parent.parent.parent.parent.parent
        git_path = monorepo_root / ".git"
        if git_path.exists():
            return monorepo_root
    except Exception:
        pass

    raise RuntimeError("Cannot find monorepo root (no .git entry found)")


class ConfigLoader:
    """
    Load and merge configuration from YAML files.

    Parameters
    ----------
    config_dir : Path | None, optional
        Directory containing config files. If None, uses monorepo_root/config.
    config_file : Path | None, optional
        Optional overlay YAML file applied on top of the main config.
        Keys in the overlay take precedence over the main file.
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        config_file: Path | None = None,
    ) -> None:
        """Initialize the loader with an optional config directory.

        Parameters
        ----------
        config_dir : Path | None, optional
            Directory containing config files. If None, uses the monorepo
            root config directory or a local fallback.
        config_file : Path | None, optional
            Optional overlay YAML file applied on top of the main config.
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
        self.config_file: Path | None = None
        if config_file is not None:
            p = Path(config_file)
            if not p.exists():
                msg = f"Overlay config file not found: {p}"
                raise FileNotFoundError(msg)
            self.config_file = p

    def load(self) -> CanvodConfig:
        """
        Load complete configuration.

        Loads ``canvod-settings.yaml`` from the config directory.

        Returns
        -------
        CanvodConfig
            Validated configuration object.

        Raises
        ------
        ConfigValidationError
            If configuration is invalid (wraps Pydantic ValidationError).
        FileNotFoundError
            If ``canvod-settings.yaml`` does not exist in the config directory.
        """
        settings_yaml = self.config_dir / "canvod-settings.yaml"
        if not settings_yaml.exists():
            raise FileNotFoundError(
                f"Settings file not found: {settings_yaml}\n"
                "Run 'canvodpy config init' to create it from the template."
            )
        return self._load_single_file(settings_yaml)

    def _load_single_file(self, path: Path) -> CanvodConfig:
        """Load from a unified settings file (canvod-settings.yaml).

        Expected top-level keys: ``processing:``, ``sites:``, ``sids:``.
        ``sites:`` values are site names directly (no nested ``sites:`` wrapper).
        """
        data = self._load_yaml(path)

        # Processing: merge user section with package defaults.
        proc_defaults = self._load_yaml(self.defaults_dir / "processing.yaml")
        proc_data = self._deep_merge(proc_defaults, data.get("processing", {}))

        # Apply overlay file if set.
        if self.config_file is not None:
            overlay = self._load_yaml(self.config_file)
            overlay_proc = overlay.get("processing", {})
            # Normalize deprecated 'processing:' key in overlay before merging.
            if "processing" in overlay_proc:
                nested = overlay_proc.pop("processing")
                overlay_proc["params"] = self._deep_merge(
                    overlay_proc.get("params", {}), nested
                )
            proc_data = self._deep_merge(proc_data, overlay_proc)
            sids_overlay = overlay.get("sids", {})
            sites_raw_overlay = overlay.get("sites", {})
        else:
            sids_overlay: dict = {}
            sites_raw_overlay: dict = {}

        # Sids: merge user section with package defaults, then overlay.
        sids_defaults = self._load_yaml(self.defaults_dir / "sids.yaml")
        sids_data = self._deep_merge(sids_defaults, data.get("sids", {}))
        if sids_overlay:
            sids_data = self._deep_merge(sids_data, sids_overlay)

        # Sites: top-level keys in the 'sites:' section are site names.
        sites_raw = data.get("sites", {})
        if sites_raw_overlay:
            sites_raw = self._deep_merge(sites_raw, sites_raw_overlay)

        try:
            return CanvodConfig(
                processing=ProcessingConfig(**proc_data),
                sites=SitesConfig(sites=sites_raw),
                sids=SidsConfig(**sids_data),
            )
        except ValidationError as e:
            raise ConfigValidationError(e, self.config_dir) from e

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """Load YAML file.

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
        """Deep merge override dictionary into base dictionary.

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


@functools.lru_cache(maxsize=8)
def load_config(
    config_dir: Path | None = None,
    config_file: Path | None = None,
) -> CanvodConfig:
    """Load configuration from YAML files.

    This is the main entry point for loading configuration.

    Parameters
    ----------
    config_dir : Path | None, optional
        Directory containing config files. If None, automatically finds
        monorepo root and uses {monorepo_root}/config.
    config_file : Path | None, optional
        Optional overlay YAML file applied on top of the main config.
        Can also be set via the ``CANVOD_CONFIG_FILE`` environment variable.

    Returns
    -------
    CanvodConfig
        Validated configuration object.

    Raises
    ------
    ConfigValidationError
        If configuration YAML is invalid.
    FileNotFoundError
        If ``config_file`` is specified but does not exist.

    Examples
    --------
    >>> from canvod.config import load_config
    >>> config = load_config()
    >>> print(config.nasa_earthdata_acc_mail)
    >>> print(config.processing.aux_data.agency)
    """
    if config_dir is None:
        env_dir = os.environ.get("CANVOD_CONFIG_DIR")
        if env_dir:
            config_dir = Path(env_dir)
    if config_file is None:
        env_file = os.environ.get("CANVOD_CONFIG_FILE")
        if env_file:
            config_file = Path(env_file)
    loader = ConfigLoader(config_dir, config_file=config_file)
    return loader.load()
