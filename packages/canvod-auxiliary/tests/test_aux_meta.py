"""
Meta tests for canvod-aux package.

Tests basic imports and package structure to ensure
the package is properly configured.
"""

import pytest


# Helper functions for skipif conditions (must be defined before use)
def _can_import_pipeline():
    """Check if pipeline can be imported (requires gnssvodpy)."""
    try:
        from canvod.auxiliary import (
            AuxDataPipeline,  # noqa: F401  # type: ignore[unresolved-import]
        )

        return True
    except ImportError, AttributeError:
        return False


def _can_import_augmentation():
    """Check if augmentation can be imported (requires gnssvodpy)."""
    try:
        from canvod.auxiliary import AuxDataAugmenter  # noqa: F401

        return True
    except ImportError, AttributeError:
        return False


# Tests
def test_package_imports():
    """Test that main package can be imported."""
    import canvod.auxiliary

    assert canvod.auxiliary is not None


def test_internal_utilities_import():
    """Test that internal utilities can be imported."""
    from canvod.utils.tools import YYYYDOY

    from canvod.auxiliary._internal import UREG

    assert UREG is not None
    assert YYYYDOY is not None


def test_core_api_imports():
    """Test that core API classes can be imported (no gnssvodpy dependencies)."""
    from canvod.auxiliary import (
        AuxFile,
        ClkFile,
        ClockConfig,
        Interpolator,
        Sp3Config,
        Sp3File,
    )

    # Verify all imports are classes
    assert Sp3File is not None
    assert ClkFile is not None
    assert AuxFile is not None
    assert Interpolator is not None
    assert Sp3Config is not None
    assert ClockConfig is not None


def test_public_api_imports():
    """Test that all available public API classes can be imported."""
    import canvod.auxiliary

    # Core classes should always be available
    assert hasattr(canvod.auxiliary, "Sp3File")
    assert hasattr(canvod.auxiliary, "ClkFile")
    assert hasattr(canvod.auxiliary, "AuxFile")

    # Optional classes (require gnssvodpy)
    # These may or may not be available depending on whether gnssvodpy is installed


@pytest.mark.skipif(
    not _can_import_pipeline(), reason="Requires gnssvodpy (optional dependency)"
)
def test_pipeline_import():
    """Test that pipeline can be imported (requires gnssvodpy)."""
    from canvod.auxiliary import AuxDataPipeline

    assert AuxDataPipeline is not None


@pytest.mark.skipif(
    not _can_import_augmentation(), reason="Requires gnssvodpy (optional dependency)"
)
def test_augmentation_imports():
    """Test that augmentation framework can be imported (requires gnssvodpy)."""
    from canvod.auxiliary import (
        AugmentationContext,
        AugmentationStep,
        AuxDataAugmenter,
    )

    assert AuxDataAugmenter is not None
    assert AugmentationStep is not None
    assert AugmentationContext is not None


def test_interpolation_imports():
    """Test that interpolation strategies can be imported."""
    from canvod.auxiliary import (
        ClockInterpolationStrategy,
        Sp3InterpolationStrategy,
        create_interpolator_from_attrs,
    )

    assert Sp3InterpolationStrategy is not None
    assert ClockInterpolationStrategy is not None
    assert create_interpolator_from_attrs is not None


def test_container_imports():
    """Test that container utilities can be imported."""
    from canvod.auxiliary import FileDownloader, FtpDownloader, GnssData

    assert FileDownloader is not None
    assert FtpDownloader is not None
    assert GnssData is not None


def test_version_attribute():
    """Test that package has version attribute."""
    import canvod.auxiliary

    assert hasattr(canvod.auxiliary, "__version__")
    assert canvod.auxiliary.__version__ == "0.1.0"
