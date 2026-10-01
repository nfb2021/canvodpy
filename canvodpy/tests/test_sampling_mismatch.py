"""Tests for the warning when the ephemeris grid is coarser than the data."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import xarray as xr
from canvodpy.orchestrator.processor import _warn_if_aux_grid_coarser


def _epochs(step_s: int, n: int = 10) -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00") + np.arange(n) * np.timedelta64(
        step_s, "s"
    )
    return xr.Dataset(coords={"epoch": epochs})


def test_warns_when_data_is_finer_than_grid() -> None:
    log = mock.Mock()
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(1), _epochs(5))
    log.warning.assert_called_once()
    assert log.warning.call_args.kwargs["data_sampling_s"] == 1.0
    assert log.warning.call_args.kwargs["ephemeris_grid_s"] == 5.0


def test_silent_when_grid_matches_or_is_finer() -> None:
    log = mock.Mock()
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(5), _epochs(5))
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(30), _epochs(5))
    _warn_if_aux_grid_coarser(log, Path("f.rnx"), _epochs(5, n=1), _epochs(5))
    log.warning.assert_not_called()
