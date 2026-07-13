"""Tests for VodComputer — inline and bulk VOD computation strategies."""

from __future__ import annotations

import unittest.mock

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from canvodpy.vod_computer import VodComputer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_site(vod_analyses: dict | None = None):
    site = unittest.mock.MagicMock()
    site.name = "TestSite"
    site.vod_analyses = vod_analyses or {}
    return site


def _make_ds(n_epochs: int = 5, n_sids: int = 3) -> xr.Dataset:
    epochs = pd.date_range("2025-01-01", periods=n_epochs, freq="30s")
    sids = [f"G0{i}|L1|C" for i in range(1, n_sids + 1)]
    return xr.Dataset(
        {
            "SNR": (["epoch", "sid"], np.ones((n_epochs, n_sids))),
            "theta": (["epoch", "sid"], np.full((n_epochs, n_sids), 0.5)),
            "phi": (["epoch", "sid"], np.zeros((n_epochs, n_sids))),
        },
        coords={"epoch": epochs, "sid": sids},
    )


def _make_analysis_cfg(canopy: str = "canopy_01", reference: str = "reference_01"):
    cfg = unittest.mock.MagicMock()
    cfg.canopy_receiver = canopy
    cfg.reference_receiver = reference
    return cfg


# ---------------------------------------------------------------------------
# Construction and repr
# ---------------------------------------------------------------------------


class TestVodComputerInit:
    def test_default_rechunk(self):
        vc = VodComputer(_make_site())
        assert vc._rechunk == {"epoch": 17280, "sid": -1}

    def test_custom_rechunk(self):
        vc = VodComputer(_make_site(), rechunk={"epoch": 1000, "sid": -1})
        assert vc._rechunk["epoch"] == 1000

    def test_repr(self):
        vc = VodComputer(_make_site(), calculator="tau_omega_zeroth")
        r = repr(vc)
        assert "TestSite" in r
        assert "tau_omega_zeroth" in r


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestVodComputerStaticHelpers:
    def test_filter_time_start_only(self):
        ds = _make_ds(n_epochs=10)
        cutoff = ds.epoch.values[5]
        result = VodComputer._filter_time(ds, start=cutoff, end=None)
        assert result.sizes["epoch"] == 5

    def test_filter_time_end_only(self):
        ds = _make_ds(n_epochs=10)
        cutoff = ds.epoch.values[4]
        result = VodComputer._filter_time(ds, start=None, end=cutoff)
        assert result.sizes["epoch"] == 5

    def test_filter_time_both_bounds(self):
        ds = _make_ds(n_epochs=10)
        start = ds.epoch.values[2]
        end = ds.epoch.values[6]
        result = VodComputer._filter_time(ds, start=start, end=end)
        assert result.sizes["epoch"] == 5

    def test_filter_time_no_bounds_returns_unchanged(self):
        ds = _make_ds(n_epochs=10)
        result = VodComputer._filter_time(ds, start=None, end=None)
        assert result.sizes["epoch"] == 10

    def test_dedup_sort_removes_duplicate_epochs(self):
        epochs = pd.date_range("2025-01-01", periods=3, freq="30s")
        # Repeat the middle epoch
        dup_epochs = [epochs[0], epochs[1], epochs[1], epochs[2]]
        ds = xr.Dataset(
            {"x": (["epoch"], np.arange(4))},
            coords={"epoch": dup_epochs},
        )
        result = VodComputer._dedup_sort(ds)
        assert result.sizes["epoch"] == 3
        assert len(np.unique(result.epoch.values)) == 3

    def test_dedup_sort_preserves_sorted_unique(self):
        ds = _make_ds(n_epochs=5)
        result = VodComputer._dedup_sort(ds)
        assert result.sizes["epoch"] == 5
        assert np.all(np.diff(result.epoch.values.astype(np.int64)) > 0)

    def test_dedup_sort_sorts_unsorted_epochs(self):
        epochs = pd.date_range("2025-01-01", periods=5, freq="30s")
        shuffled = [epochs[2], epochs[0], epochs[4], epochs[1], epochs[3]]
        ds = xr.Dataset({"x": (["epoch"], np.arange(5))}, coords={"epoch": shuffled})
        result = VodComputer._dedup_sort(ds)
        assert np.all(np.diff(result.epoch.values.astype(np.int64)) > 0)


# ---------------------------------------------------------------------------
# Config and pair extraction
# ---------------------------------------------------------------------------


class TestVodComputerConfig:
    def test_get_analysis_config_known(self):
        cfg = _make_analysis_cfg()
        vc = VodComputer(_make_site({"my_analysis": cfg}))
        result = vc._get_analysis_config("my_analysis")
        assert result is cfg

    def test_get_analysis_config_unknown_raises(self):
        vc = VodComputer(_make_site({}))
        with pytest.raises(ValueError, match="not configured"):
            vc._get_analysis_config("nonexistent")

    def test_extract_pair_happy_path(self):
        cfg = _make_analysis_cfg(canopy="c", reference="r")
        vc = VodComputer(_make_site({"a": cfg}))
        canopy_ds = _make_ds()
        ref_ds = _make_ds()
        c, r = vc._extract_pair({"c": canopy_ds, "r": ref_ds}, "a")
        assert c is canopy_ds
        assert r is ref_ds

    def test_extract_pair_missing_canopy_raises(self):
        cfg = _make_analysis_cfg(canopy="canopy_01", reference="ref_01")
        vc = VodComputer(_make_site({"a": cfg}))
        with pytest.raises(KeyError, match="canopy_01"):
            vc._extract_pair({"ref_01": _make_ds()}, "a")

    def test_extract_pair_missing_reference_raises(self):
        cfg = _make_analysis_cfg(canopy="canopy_01", reference="ref_01")
        vc = VodComputer(_make_site({"a": cfg}))
        with pytest.raises(KeyError, match="ref_01"):
            vc._extract_pair({"canopy_01": _make_ds()}, "a")


# ---------------------------------------------------------------------------
# _compute_and_write
# ---------------------------------------------------------------------------


class TestVodComputerComputeAndWrite:
    def test_write_false_skips_store(self):
        cfg = _make_analysis_cfg()
        vc = VodComputer(_make_site({"a": cfg}))
        canopy_ds = _make_ds()
        sky_ds = _make_ds()
        mock_vod = xr.Dataset({"VOD": (["epoch", "sid"], np.zeros((5, 3)))})

        with (
            # VODFactory is imported locally inside _compute_and_write
            unittest.mock.patch("canvodpy.factories.VODFactory") as mock_factory_cls,
            unittest.mock.patch.object(vc, "_write_to_store") as mock_write,
        ):
            mock_factory_cls.create.return_value.calculate_vod.return_value = mock_vod
            result = vc._compute_and_write(canopy_ds, sky_ds, "a", write=False)

        mock_write.assert_not_called()
        assert "VOD" in result

    def test_write_true_calls_store(self):
        cfg = _make_analysis_cfg()
        vc = VodComputer(_make_site({"a": cfg}))
        canopy_ds = _make_ds()
        sky_ds = _make_ds()
        mock_vod = xr.Dataset({"VOD": (["epoch", "sid"], np.zeros((5, 3)))})

        with (
            unittest.mock.patch("canvodpy.factories.VODFactory") as mock_factory_cls,
            unittest.mock.patch.object(vc, "_write_to_store") as mock_write,
        ):
            mock_factory_cls.create.return_value.calculate_vod.return_value = mock_vod
            vc._compute_and_write(canopy_ds, sky_ds, "a", write=True)

        mock_write.assert_called_once_with(mock_vod, "a")

    def test_write_to_store_clears_encodings(self):
        cfg = _make_analysis_cfg()
        mock_site = _make_site({"a": cfg})
        vc = VodComputer(mock_site)

        vod_ds = xr.Dataset({"VOD": (["epoch", "sid"], np.zeros((5, 3)))})
        vod_ds["VOD"].encoding["dtype"] = "float32"

        vc._write_to_store(vod_ds, "a")

        assert vod_ds["VOD"].encoding == {}
        mock_site._site.store_vod_analysis.assert_called_once()

    def test_write_to_store_casts_string_dtype_to_object(self):
        if not hasattr(np.dtypes, "StringDType"):
            pytest.skip("requires numpy >= 2.0")

        cfg = _make_analysis_cfg()
        mock_site = _make_site({"a": cfg})
        vc = VodComputer(mock_site)

        sv_values = np.array(["G01", "G02"], dtype=np.dtypes.StringDType())
        vod_ds = xr.Dataset(
            {"VOD": (["epoch", "sid"], np.zeros((5, 2)))},
            coords={"sv": ("sid", sv_values)},
        )
        assert vod_ds["sv"].dtype.kind == "T"

        vc._write_to_store(vod_ds, "a")

        call_kwargs = mock_site._site.store_vod_analysis.call_args.kwargs
        written_ds = call_kwargs["vod_dataset"]
        assert written_ds["sv"].dtype == object
