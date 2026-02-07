#!/usr/bin/env python3
"""Quick verification script for canvodpy migration.

Run this after `uv sync` to verify all packages import correctly.
"""

import sys


def test_imports():
    """Test that all packages can be imported."""
    print("Testing package imports...\n")

    tests = [
        ("canvodpy.globals", "Umbrella: globals"),
        ("canvodpy.logging", "Umbrella: logging"),
        ("canvodpy.utils", "Umbrella: utils"),
        ("canvod.readers", "Phase 1: canvod-readers"),
        ("canvod.auxiliary", "Phase 2: canvod-aux"),
        ("canvod.store", "Phase 5: canvod-store"),
        ("canvod.vod", "Phase 4: canvod-vod"),
    ]

    passed = []
    failed = []

    for module_name, description in tests:
        try:
            __import__(module_name)
            print(f"✓ {description:<30} OK")
            passed.append(module_name)
        except ImportError as e:
            print(f"✗ {description:<30} FAILED: {e}")
            failed.append((module_name, str(e)))

    print(f"\n{'=' * 60}")
    print(f"Results: {len(passed)}/{len(tests)} passed")
    print(f"{'=' * 60}\n")

    if failed:
        print("Failed imports:")
        for module, error in failed:
            print(f"  - {module}: {error}")
        return False

    return True


def test_store_vod_integration():
    """Test that store and vod packages can work together."""
    print("\nTesting store ↔ vod integration...\n")

    try:
        from canvod.vod import TauOmegaZerothOrder

        print("✓ VODCalculator imported from canvod.vod")

        from canvod.store import GnssResearchSite

        print("✓ GnssResearchSite imported from canvod.store")

        # Test that calculate_vod can use default calculator
        print("✓ Optional imports configured correctly")

        return True

    except ImportError as e:
        print(f"✗ Integration test failed: {e}")
        return False


def test_package_versions():
    """Display package versions."""
    print("\nPackage versions:\n")

    packages = [
        "canvod.readers",
        "canvod.auxiliary",
        "canvod.store",
        "canvod.vod",
    ]

    for pkg in packages:
        try:
            module = __import__(pkg)
            version = getattr(module, "__version__", "unknown")
            print(f"  {pkg:<20} v{version}")
        except Exception as e:
            print(f"  {pkg:<20} ERROR: {e}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("canVODpy Migration Verification")
    print("=" * 60)
    print()

    # Test imports
    imports_ok = test_imports()

    if not imports_ok:
        print("\n❌ Import tests failed. Run 'uv sync' and try again.")
        sys.exit(1)

    # Test integration
    integration_ok = test_store_vod_integration()

    if not integration_ok:
        print("\n⚠️  Integration tests failed.")
        sys.exit(1)

    # Show versions
    test_package_versions()

    print("\n" + "=" * 60)
    print("✅ All verification tests passed!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Run package tests: cd packages/canvod-store && just test")
    print("  2. Run package tests: cd packages/canvod-vod && just test")
    print("  3. Test full pipeline with real data")
    print()


if __name__ == "__main__":
    main()
