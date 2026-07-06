"""Tests for ConfigLoader round-trip and merge logic."""

from pathlib import Path
from unittest.mock import patch

import yaml

from canvod.utils.config.loader import ConfigLoader, ConfigValidationError


class TestDeepMerge:
    """Test _deep_merge logic."""

    def test_flat_override(self):
        """Override values replace base values."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = loader._deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        """Nested dicts are merged recursively."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 99, "c": 3}}
        result = loader._deep_merge(base, override)
        assert result == {"outer": {"a": 1, "b": 99, "c": 3}}

    def test_override_adds_new_keys(self):
        """New keys in override are added to result."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"x": 1}
        override = {"y": 2}
        result = loader._deep_merge(base, override)
        assert result == {"x": 1, "y": 2}

    def test_override_replaces_non_dict_with_dict(self):
        """Non-dict value replaced by dict from override."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"key": "string"}
        override = {"key": {"nested": True}}
        result = loader._deep_merge(base, override)
        assert result == {"key": {"nested": True}}

    def test_base_unchanged(self):
        """Original base dict is not mutated."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"c": 99}}
        loader._deep_merge(base, override)
        assert base == {"a": 1, "b": {"c": 2}}


class TestConfigLoaderRoundTrip:
    """Test ConfigLoader with temporary YAML files."""

    def _write_yaml(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            yaml.dump(data, f)

    def test_load_from_temp_config_dir(self, tmp_path):
        """Config files in tmp_path should load into CanvodConfig."""
        # Write processing.yaml
        self._write_yaml(
            tmp_path / "processing.yaml",
            {
                "metadata": {
                    "author": "Test Author",
                    "email": "test@example.com",
                    "institution": "Test University",
                },
                "storage": {
                    "stores_root_dir": str(tmp_path / "stores"),
                },
            },
        )
        # Write sites.yaml
        self._write_yaml(
            tmp_path / "sites.yaml",
            {
                "sites": {
                    "TestSite": {
                        "gnss_site_data_root": str(tmp_path / "data"),
                        "receivers": {
                            "canopy_01": {
                                "type": "canopy",
                                "directory": "canopy",
                            },
                            "reference_01": {
                                "type": "reference",
                                "directory": "reference",
                                "paired_canopies": "all",
                            },
                        },
                    }
                }
            },
        )
        # Write sids.yaml
        self._write_yaml(tmp_path / "sids.yaml", {"mode": "all"})

        loader = ConfigLoader(config_dir=tmp_path)
        config = loader.load()

        assert config.processing.metadata.author == "Test Author"
        assert config.processing.metadata.email == "test@example.com"
        assert "TestSite" in config.sites.sites
        assert config.sids.mode == "all"

    def test_user_config_overrides_defaults(self, tmp_path):
        """User processing.yaml should override default values."""
        self._write_yaml(
            tmp_path / "processing.yaml",
            {
                "metadata": {
                    "author": "Custom Author",
                    "email": "custom@example.com",
                    "institution": "Custom Univ",
                },
                "aux_data": {"agency": "GFZ"},
                "storage": {
                    "stores_root_dir": str(tmp_path / "stores"),
                },
            },
        )
        self._write_yaml(tmp_path / "sites.yaml", {"sites": {}})
        self._write_yaml(tmp_path / "sids.yaml", {"mode": "all"})

        config = ConfigLoader(config_dir=tmp_path).load()

        # User value should override default
        assert config.processing.aux_data.agency == "GFZ"
        # Default values should still be present
        assert config.processing.netcdf_compression.zlib is True


class TestConfigLoaderDefaults:
    """Test fallback to defaults when user files are missing."""

    def test_missing_user_config_uses_defaults(self, tmp_path):
        """Missing user files should fall back to package defaults."""
        # Don't create any files — loader should use defaults
        loader = ConfigLoader(config_dir=tmp_path)

        # This should load defaults without crashing
        # (sites.yaml missing → empty sites, processing.yaml missing → defaults)
        config = loader.load()

        # Default processing values from package defaults
        assert config.processing.aux_data.agency == "COD"
        assert config.sids.mode == "preset"
        assert config.sids.preset == "default"
        assert len(config.sids.get_sids()) == 277


class TestConfigLoaderValidationError:
    """Test validation error handling."""

    def _write_yaml(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            yaml.dump(data, f)

    def test_invalid_config_raises_config_validation_error(self, tmp_path):
        """Invalid config should raise ConfigValidationError (not sys.exit)."""
        self._write_yaml(
            tmp_path / "processing.yaml",
            {
                "metadata": {
                    "author": "Test",
                    "email": "test@example.com",
                    "institution": "Test",
                },
                "storage": {
                    "stores_root_dir": str(tmp_path),
                },
            },
        )
        self._write_yaml(tmp_path / "sites.yaml", {"sites": {}})
        self._write_yaml(tmp_path / "sids.yaml", {"mode": "all"})

        loader = ConfigLoader(config_dir=tmp_path)

        # Force CanvodConfig validation to fail by making _load_sids return
        # an invalid type (string instead of SidsConfig)
        import pytest

        with (
            patch.object(loader, "_load_sids", return_value="not_a_sids_config"),
            pytest.raises(ConfigValidationError) as exc_info,
        ):
            loader.load()

        assert exc_info.value.config_dir == tmp_path
        assert isinstance(exc_info.value, ValueError)
