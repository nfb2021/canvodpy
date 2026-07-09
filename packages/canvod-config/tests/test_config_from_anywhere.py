#!/usr/bin/env python3
"""Test config loader works from any directory."""

import shutil
import subprocess
from pathlib import Path

import pytest


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
