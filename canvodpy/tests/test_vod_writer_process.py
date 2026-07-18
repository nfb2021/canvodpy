"""Tests for the dedicated VOD-writer subprocess (2026-07-18 crash investigation).

icechunk routes every async operation through one Tokio runtime shared by
every Repository/Store object in a process, not one per object. A Site
opens both rinex_store and vod_store eagerly and holds both alive for the
run's whole lifetime, so the VOD store's Repository was never isolated from
whatever runtime/thread-pool state the RINEX store's heavy ingest burst
left behind, in the same process. Isolating VOD writes in a dedicated,
persistent subprocess gives them a genuinely fresh Tokio runtime.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from unittest import mock

import numpy as np
import pytest
import xarray as xr
from canvodpy.cli import run as run_module
from canvodpy.cli.run import _submit_and_wait


def _identity(x):
    return x


def _raise(exc_type_name: str):
    # Must be module-level-picklable; raising a builtin by name keeps this
    # simple without needing a dedicated module-level exception factory.
    raise RuntimeError(f"boom: {exc_type_name}")


class TestSubmitAndWait:
    def test_returns_the_result(self):
        with ProcessPoolExecutor(max_workers=1) as pool:
            assert _submit_and_wait(pool, _identity, 42) == 42

    def test_reraises_worker_exception_in_caller_process(self):
        with ProcessPoolExecutor(max_workers=1) as pool:
            with pytest.raises(RuntimeError, match="boom: ValueError"):
                _submit_and_wait(pool, _raise, "ValueError")


class TestVodDatasetPicklesAcrossProcessBoundary:
    """The real risk this design depends on: a .chunk()'d VOD dataset
    (exactly what _compute_vod_for_day produces before handing it to the
    writer) must survive a pickle round-trip through a real subprocess."""

    @staticmethod
    def _load_and_sum(ds: xr.Dataset) -> tuple[tuple[int, ...], float]:
        ds = ds.load()
        return ds["VOD"].shape, float(ds["VOD"].values.sum())

    def test_chunked_dataset_round_trips_correctly(self):
        rng = np.random.default_rng(0)
        ds = xr.Dataset(
            {"VOD": (("epoch", "sid"), rng.uniform(0, 1, (100, 5)))},
            coords={
                "epoch": np.arange(100),
                "sid": [f"G{i:02d}|L1|C" for i in range(5)],
            },
        )
        ds = ds.chunk({"epoch": 17280, "sid": -1})
        for var in ds.data_vars:
            ds[var].encoding = {}
        expected_sum = float(ds.load()["VOD"].values.sum())

        with ProcessPoolExecutor(max_workers=1) as pool:
            shape, total = _submit_and_wait(pool, self._load_and_sum, ds)

        assert shape == (100, 5)
        assert total == pytest.approx(expected_sum)


class TestSubprocessWorkerLogic:
    """_ensure_vod_metadata_in_subprocess / _write_vod_result_in_subprocess
    run *inside* the dedicated subprocess -- test their internal logic
    directly against a mocked _vod_writer_site rather than through a real
    pool, matching this session's established pattern for code with no
    lightweight Site/store test harness."""

    def test_ensure_metadata_requires_initializer_to_have_run(self, monkeypatch):
        monkeypatch.setattr(run_module, "_vod_writer_site", None)
        with pytest.raises(AssertionError, match="_init_vod_writer_process"):
            run_module._ensure_vod_metadata_in_subprocess("tau_omega")

    def test_write_result_requires_initializer_to_have_run(self, monkeypatch):
        monkeypatch.setattr(run_module, "_vod_writer_site", None)
        with pytest.raises(AssertionError, match="_init_vod_writer_process"):
            run_module._write_vod_result_in_subprocess(
                "VOD_lower_antenna", "tau_omega", mock.MagicMock(), {}, {}, None
            )

    def test_ensure_metadata_delegates_to_the_process_local_site(self, monkeypatch):
        fake_site = mock.MagicMock()
        monkeypatch.setattr(run_module, "_vod_writer_site", fake_site)
        with mock.patch(
            "canvodpy.vod_computer.ensure_vod_store_metadata"
        ) as mock_ensure:
            run_module._ensure_vod_metadata_in_subprocess("tau_omega")
        mock_ensure.assert_called_once_with(fake_site, "tau_omega")

    def test_write_result_delegates_to_the_process_local_site(self, monkeypatch):
        fake_site = mock.MagicMock()
        fake_site._site.store_vod_analysis.return_value = True
        monkeypatch.setattr(run_module, "_vod_writer_site", fake_site)

        vod_ds = mock.MagicMock()
        result = run_module._write_vod_result_in_subprocess(
            "VOD_lower_antenna",
            "tau_omega",
            vod_ds,
            {"canopy_01": "hash1"},
            {"canopy_01": "/path/to/store"},
            "commit msg",
        )

        assert result is True
        fake_site._site.store_vod_analysis.assert_called_once_with(
            vod_dataset=vod_ds,
            analysis_name="VOD_lower_antenna",
            calculator_name="tau_omega",
            source_file_hashes={"canopy_01": "hash1"},
            source_gnss_stores={"canopy_01": "/path/to/store"},
            commit_message="commit msg",
        )
