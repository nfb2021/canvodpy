"""Tests for temporal aggregation operation."""

import numpy as np
import xarray as xr

from canvod.ops.temporal import TemporalAggregate, temporal_aggregate


class TestTemporalAggregate:
    def test_basic_aggregation(self, sample_ds: xr.Dataset):
        """1-second data aggregated to 1-minute bins should reduce epochs."""
        op = TemporalAggregate(freq="1min", method="mean")
        out, result = op(sample_ds)

        assert result.op_name == "temporal_aggregate"
        # 120 seconds -> 2 full minutes
        assert out.sizes["epoch"] == 2
        assert out.sizes["sid"] == sample_ds.sizes["sid"]
        assert "SNR" in out.data_vars
        assert "no-op" not in result.notes

    def test_preserves_attrs(self, sample_ds: xr.Dataset):
        """Dataset attrs must survive aggregation."""
        op = TemporalAggregate(freq="1min")
        out, _ = op(sample_ds)

        assert out.attrs["File Hash"] == "abc123"
        assert out.attrs["source"] == "test"

    def test_preserves_sid_only_coords(self, sample_ds: xr.Dataset):
        """sid-only coords (like sv) must pass through unchanged."""
        op = TemporalAggregate(freq="1min")
        out, _ = op(sample_ds)

        assert "sv" in out.coords
        assert out.coords["sv"].dims == ("sid",)
        np.testing.assert_array_equal(
            out.coords["sv"].values, sample_ds.coords["sv"].values
        )

    def test_aggregates_phi_theta(self, sample_ds: xr.Dataset):
        """phi and theta (epoch, sid) coords should be aggregated too."""
        op = TemporalAggregate(freq="1min")
        out, _ = op(sample_ds)

        assert "phi" in out.coords
        assert "theta" in out.coords
        assert out.coords["phi"].dims == ("epoch", "sid")
        assert out.coords["theta"].dims == ("epoch", "sid")

    def test_early_exit_coarse_data(self, coarse_ds: xr.Dataset):
        """If data is already at/coarser than freq, should return unchanged."""
        op = TemporalAggregate(freq="1min")
        out, result = op(coarse_ds)

        assert "no-op" in result.notes
        xr.testing.assert_identical(out, coarse_ds)

    def test_median_method(self, sample_ds: xr.Dataset):
        """median method should work without errors."""
        op = TemporalAggregate(freq="1min", method="median")
        out, result = op(sample_ds)

        assert out.sizes["epoch"] == 2
        assert result.parameters["method"] == "median"

    def test_invalid_method_raises(self):
        """Unsupported method should raise ValueError."""
        import pytest

        with pytest.raises(ValueError, match="Unsupported aggregation method"):
            TemporalAggregate(freq="1min", method="sum")

    def test_convenience_function(self, sample_ds: xr.Dataset):
        """temporal_aggregate convenience wrapper should work."""
        out = temporal_aggregate(sample_ds, freq="1min")
        assert out.sizes["epoch"] == 2

    def test_result_shapes(self, sample_ds: xr.Dataset):
        """OpResult should record correct input/output shapes."""
        op = TemporalAggregate(freq="1min")
        _, result = op(sample_ds)

        assert result.input_shape["epoch"] == 120
        assert result.input_shape["sid"] == 3
        assert result.output_shape["epoch"] == 2
        assert result.output_shape["sid"] == 3
        assert result.duration_seconds > 0


def _five_second_ds(snr: np.ndarray, phi: np.ndarray, start: str) -> xr.Dataset:
    epochs = np.datetime64(start, "ns") + np.arange(snr.shape[0]) * np.timedelta64(
        5, "s"
    )
    return xr.Dataset(
        {
            "SNR": (("epoch", "sid"), snr, {"units": "dB-Hz"}),
            "phi": (("epoch", "sid"), phi),
        },
        coords={"epoch": epochs, "sid": [f"s{i}" for i in range(snr.shape[1])]},
    )


class TestTemporalAggregateValues:
    def test_missing_values_are_skipped(self):
        snr = np.arange(12, dtype=np.float32).reshape(12, 1)
        snr[3] = np.nan
        ds = _five_second_ds(snr, np.ones_like(snr, dtype=float), "2025-01-01")
        for method, expected in (("mean", np.nanmean(snr)), ("median", 6.0)):
            out, _ = TemporalAggregate("1min", method)(ds)
            np.testing.assert_allclose(out["SNR"].values[0, 0], expected)

    def test_bin_without_values_stays_nan(self):
        snr = np.full((24, 1), np.nan, dtype=np.float32)
        snr[:12] = 30.0
        ds = _five_second_ds(snr, np.ones((24, 1)), "2025-01-01")
        out, _ = TemporalAggregate("1min", "mean")(ds)
        assert out["SNR"].values[0, 0] == 30.0
        assert np.isnan(out["SNR"].values[1, 0])

    def test_keeps_dtype_and_attrs(self):
        ds = _five_second_ds(
            np.ones((12, 1), dtype=np.float32), np.ones((12, 1)), "2025-01-01"
        )
        out, _ = TemporalAggregate("1min", "mean")(ds)
        assert out["SNR"].dtype == np.float32
        assert out["SNR"].attrs == {"units": "dB-Hz"}

    def test_azimuth_crossing_north(self):
        """Half the bin just west of north, half just east: north, not south."""
        phi = np.r_[np.full(6, 2 * np.pi - 0.1), np.full(6, 0.3)].reshape(12, 1)
        ds = _five_second_ds(np.ones((12, 1)), phi, "2025-01-01")
        for method in ("mean", "median"):
            out, _ = TemporalAggregate("1min", method)(ds)
            np.testing.assert_allclose(out["phi"].values[0, 0], 0.1)

    def test_bins_start_at_freq_multiples(self):
        """Epochs off the bin grid are labeled with their bin start."""
        ds = _five_second_ds(np.ones((24, 1)), np.ones((24, 1)), "2025-01-01T00:00:02")
        out, _ = TemporalAggregate("1min", "mean")(ds)
        np.testing.assert_array_equal(
            out["epoch"].values,
            np.array(["2025-01-01T00:00", "2025-01-01T00:01"], dtype="datetime64[ns]"),
        )

    def test_one_epoch_per_bin_off_grid_is_relabeled(self):
        """Already 1-min data not on the bin starts still gets bin labels."""
        epochs = np.datetime64("2025-01-01T00:00:02", "ns") + np.arange(
            3
        ) * np.timedelta64(60, "s")
        ds = xr.Dataset(
            {"SNR": (("epoch", "sid"), np.ones((3, 1)))},
            coords={"epoch": epochs, "sid": ["s0"]},
        )
        out, result = TemporalAggregate("1min", "mean")(ds)
        assert "no-op" not in result.notes
        assert (out["epoch"].values.astype(np.int64) % 60_000_000_000 == 0).all()
