#!/usr/bin/env python3
"""Test config loader works from any directory."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from canvod.config import loader as loader_module


def find_monorepo_root(start_path: Path) -> Path:
    """Find monorepo root by looking for pyproject.toml."""
    current = start_path
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find monorepo root")


# Find monorepo and check if config exists
MONOREPO_ROOT = find_monorepo_root(Path(__file__).parent)
CONFIG_DIR = MONOREPO_ROOT / "config"
HAS_CONFIG = (CONFIG_DIR / "sites.yaml").exists()

# Test directories (relative to monorepo root)
TEST_DIRS = [
    ".",
    "canvodpy",
    "packages/canvod-readers",
    "packages/canvod-readers/tests",
    "packages/canvod-utils/src/canvod/utils/config",
]


@pytest.mark.skipif(not HAS_CONFIG, reason="Integration test requires config files")
@pytest.mark.parametrize("test_dir", TEST_DIRS)
def test_config_loader_from_directory(test_dir: str):
    """Test that config loader works from various directories in monorepo."""
    full_path = MONOREPO_ROOT / test_dir

    # Skip if directory doesn't exist
    if not full_path.exists():
        pytest.skip(f"Directory doesn't exist: {test_dir}")

    # Find python executable (use current interpreter)
    python_exe = shutil.which("python") or shutil.which("python3")
    if not python_exe:
        pytest.skip("Python executable not found")

    # Test loading config from this directory
    result = subprocess.run(
        [
            python_exe,
            "-c",
            "from canvod.config import load_config; "
            "config = load_config(); "
            "print(f'Sites: {list(config.sites.sites.keys())}')",
        ],
        cwd=full_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Verify it worked
    assert result.returncode == 0, (
        f"Config loading failed from {test_dir}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    # Verify expected site exists in config
    assert "rosalia" in result.stdout.lower(), (
        f"Expected 'rosalia' site in output from {test_dir}\nGot: {result.stdout}"
    )


class TestGetTemplateDir:
    """Templates ship as real package data — always reachable, no search needed."""

    def test_template_dir_exists_and_has_expected_files(self):
        template_dir = loader_module.get_template_dir()
        assert template_dir.exists()
        assert (template_dir / "canvod-settings.yaml.example").exists()
        assert (template_dir / "recipes" / "_template.yaml.example").exists()

    def test_template_dir_independent_of_monorepo_lookup(self):
        """Even if monorepo-root discovery fails, templates are still found."""
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            template_dir = loader_module.get_template_dir()
            assert template_dir.exists()


class TestGetDefaultConfigDir:
    """XDG-first default, with dev-checkout convenience when available."""

    def test_falls_back_to_xdg_when_no_monorepo_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            result = loader_module.get_default_config_dir()
        assert result == tmp_path / "canvodpy"

    def test_falls_back_to_home_config_when_no_xdg_env(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            result = loader_module.get_default_config_dir()
        assert result == Path.home() / ".config" / "canvodpy"

    def test_prefers_monorepo_config_dir_when_it_exists(self, tmp_path):
        """Dev-checkout convenience: an existing {monorepo_root}/config wins."""
        fake_root = tmp_path / "checkout"
        (fake_root / "config").mkdir(parents=True)
        with patch.object(loader_module, "find_monorepo_root", return_value=fake_root):
            result = loader_module.get_default_config_dir()
        assert result == fake_root / "config"

    def test_ignores_monorepo_root_without_config_dir(self, tmp_path, monkeypatch):
        """A .git found upward with no config/ dir still falls through to XDG."""
        fake_root = tmp_path / "checkout_no_config"
        fake_root.mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        with patch.object(loader_module, "find_monorepo_root", return_value=fake_root):
            result = loader_module.get_default_config_dir()
        assert result == tmp_path / "xdg" / "canvodpy"


if __name__ == "__main__":
    """Allow running as script for manual testing."""
    if not HAS_CONFIG:
        print("⚠️  Skipping: Config files not found")
        exit(0)

    print("=" * 70)
    print("Testing config loader from multiple directories")
    print("=" * 70)

    failed = []
    for test_dir in TEST_DIRS:
        full_path = MONOREPO_ROOT / test_dir
        if not full_path.exists():
            print(f"\n📁 Testing from: {test_dir}")
            print("   ⏭️  SKIPPED (directory doesn't exist)")
            continue

        print(f"\n📁 Testing from: {test_dir}")

        try:
            test_config_loader_from_directory(test_dir)
            print("   ✅ SUCCESS")
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            failed.append(test_dir)

    print("\n" + "=" * 70)
    if failed:
        print(f"❌ FAILED: {len(failed)}/{len(TEST_DIRS)} directories")
        for d in failed:
            print(f"   - {d}")
    else:
        print(f"✅ SUCCESS: All {len(TEST_DIRS)} directories passed!")
    print("=" * 70)
