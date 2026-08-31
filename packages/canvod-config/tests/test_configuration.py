#!/usr/bin/env python3
"""Test script to verify YAML configuration system works correctly.

This script tests:
1. Config loads from YAML files
2. Credentials are read from processing.yaml
3. Site data roots are read from sites.yaml
4. Integration with aux pipeline config
"""

from pathlib import Path

import pytest


def test_config_loads():
    """Test config loads from YAML files."""
    from canvod.config import load_config

    config_dir = Path("config")
    sites_yaml = config_dir / "sites.yaml"

    if not sites_yaml.exists():
        pytest.skip(
            "Config files not found (user-specific). "
            "Run 'just config-init' to create them."
        )

    config = load_config()

    assert config.processing.metadata.author is not None
    assert config.processing.aux_data.agency is not None
    assert len(config.sites.sites) > 0


def test_credentials_from_yaml():
    """Test credentials are read from processing.yaml."""
    from canvod.config import load_config

    config_dir = Path("config")
    if not (config_dir / "processing.yaml").exists():
        pytest.skip("Config files not found.")

    config = load_config()

    # Credentials should always exist (with defaults)
    assert config.processing.credentials is not None
    # The property should work
    _ = config.nasa_earthdata_acc_mail


def test_site_data_roots():
    """Test each site has gnss_site_data_root."""
    from canvod.config import load_config

    config_dir = Path("config")
    if not (config_dir / "sites.yaml").exists():
        pytest.skip("Config files not found.")

    config = load_config()

    for name, site in config.sites.sites.items():
        assert site.gnss_site_data_root is not None
        assert isinstance(site.get_base_path(), Path)


def test_imports():
    """Test all critical imports work."""
    from canvod.config.models import (
        CredentialsConfig,
    )

    # CredentialsConfig should work with defaults
    creds = CredentialsConfig()
    assert creds.nasa_earthdata_acc_mail is None

    # CredentialsConfig should accept an email
    creds_with_mail = CredentialsConfig(nasa_earthdata_acc_mail="test@example.com")
    assert creds_with_mail.nasa_earthdata_acc_mail == "test@example.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
