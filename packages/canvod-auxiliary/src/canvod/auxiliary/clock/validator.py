"""CLK format validator.

This module provides validation functions for CLK file data, including
checks for required dimensions, data quality, and temporal consistency.
"""

import numpy as np
import xarray as xr


def validate_clk_dataset(ds: xr.Dataset) -> dict[str, bool | float | int]:
    """Validate CLK dataset structure and data quality.

    Checks:
        - Required variable exists (clock_offset)
        - Required coordinates exist (epoch, sv)
        - Data completeness (percentage of valid values)
        - Temporal consistency (monotonic epochs)

    Parameters
    ----------
    ds : xr.Dataset
        Dataset from a CLK file.

    Returns
    -------
    dict[str, bool | float | int]
        Validation results with keys:
        - has_clock_offset
        - has_epoch
        - has_sv
        - valid_data_percent
        - epochs_monotonic
        - num_epochs
        - num_satellites
    """
    results = {}

    # Check required variable
    results["has_clock_offset"] = "clock_offset" in ds.data_vars

    # Check required coordinates
    results["has_epoch"] = "epoch" in ds.coords
    results["has_sv"] = "sv" in ds.coords

    if results["has_clock_offset"]:
        # Calculate data completeness
        clock_data = ds["clock_offset"].values
        total_values = clock_data.size
        valid_values = np.sum(~np.isnan(clock_data))
        results["valid_data_percent"] = (valid_values / total_values) * 100
    else:
        results["valid_data_percent"] = 0.0

    if results["has_epoch"]:
        # Check temporal consistency
        epochs = ds["epoch"].values
        results["epochs_monotonic"] = bool(np.all(epochs[:-1] <= epochs[1:]))
        results["num_epochs"] = len(epochs)
    else:
        results["epochs_monotonic"] = False
        results["num_epochs"] = 0

    if results["has_sv"]:
        results["num_satellites"] = len(ds["sv"])
    else:
        results["num_satellites"] = 0

    return results


def check_clk_data_quality(ds: xr.Dataset, min_coverage: float = 80.0) -> bool:
    """Check if CLK data meets minimum quality requirements.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset from a CLK file.
    min_coverage : float, default 80.0
        Minimum required data coverage percentage.

    Returns
    -------
    bool
        True if data quality is acceptable.
    """
    results = validate_clk_dataset(ds)

    # Must have all required components
    if not (results["has_clock_offset"] and results["has_epoch"] and results["has_sv"]):
        return False

    # Must have monotonic epochs
    if not results["epochs_monotonic"]:
        return False

    # Must meet minimum coverage requirement
    if results["valid_data_percent"] < min_coverage:
        return False

    return True
