"""Tests for Airflow task functions (canvodpy.workflows.tasks).

Tests use temporary directories and mock data to avoid filesystem
dependencies. Task functions are plain Python — no Airflow required.
"""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.discovery import DiscoveryError
from canvodpy.workflows.tasks import (
    _resolve_date,
    check_rinex,
    check_sbf,
    cleanup,
    parse_sampling_interval_from_filename,
    validate_data_dirs,
    validate_ingest,
)

from canvod.config.models import SiteConfig

CANOPY_RNX = "ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
REFERENCE_RNX = "ROSR01TUW_R_20250010000_15M_05S_AA.rnx"


def _site_config(tmp_path) -> MagicMock:
    """A loaded configuration with one canopy and one reference receiver."""
    site_cfg = SiteConfig(
        gnss_site_data_root=str(tmp_path),
        receivers={
            "canopy_01": {"type": "canopy", "directory": "canopy"},
            "reference_01": {
                "type": "reference",
                "directory": "reference",
                "paired_canopies": "all",
            },
        },
    )
    config = MagicMock()
    config.sites.sites = {"TestSite": site_cfg}
    return config


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestResolveDate:
    """Test YYYYDOY / Airflow ds parsing."""

    def test_yyyydoy_format(self):
        d = _resolve_date("2025001")
        assert d.year == 2025
        assert d.doy == 1
        assert d.yydoy == "25001"

    def test_airflow_ds_format(self):
        d = _resolve_date("2025-01-01")
        assert d.year == 2025
        assert d.doy == 1
        assert d.yydoy == "25001"

    def test_mid_year(self):
        d = _resolve_date("2025-07-01")
        assert d.year == 2025
        assert d.doy == 182
        assert d.yydoy == "25182"


class TestParseSamplingInterval:
    """Test RINEX v3 filename sampling interval extraction."""

    def test_5_second(self):
        assert (
            parse_sampling_interval_from_filename(
                "ROSA01TUW_R_20250010000_15M_05S_AA.rnx"
            )
            == 5.0
        )

    def test_30_second(self):
        assert (
            parse_sampling_interval_from_filename(
                "ROSA01TUW_R_20250010000_01D_30S_AA.rnx"
            )
            == 30.0
        )

    def test_1_hz(self):
        result = parse_sampling_interval_from_filename(
            "ROSA01TUW_R_20250010000_01H_01Z_AA.rnx"
        )
        assert result == pytest.approx(1.0)

    def test_unparseable(self):
        assert parse_sampling_interval_from_filename("random_file.dat") is None

    def test_short_name(self):
        assert parse_sampling_interval_from_filename("short.rnx") is None


# ---------------------------------------------------------------------------
# check_rinex / check_sbf tests
# ---------------------------------------------------------------------------


class TestCheckRinex:
    """Test check_rinex with mock config and filesystem."""

    @pytest.fixture()
    def mock_site(self, tmp_path):
        """Create a site config and one file per receiver in YYDDD folders."""
        for directory, name in (("canopy", CANOPY_RNX), ("reference", REFERENCE_RNX)):
            day_dir = tmp_path / directory / "25001"
            day_dir.mkdir(parents=True)
            (day_dir / name).touch()
        return _site_config(tmp_path)

    def test_all_files_present(self, mock_site):
        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_site):
            result = check_rinex("TestSite", "2025001")
        assert result["ready"] is True
        assert result["receivers"]["canopy_01"]["has_files"] is True
        assert result["receivers"]["reference_01"]["has_files"] is True

    def test_missing_files_raises(self, mock_site):
        # Remove canopy files
        base = mock_site.sites.sites["TestSite"].get_base_path()
        shutil.rmtree(base / "canopy" / "25001")
        (base / "canopy" / "25001").mkdir(parents=True)

        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_site):
            with pytest.raises(RuntimeError, match="missing receivers"):
                check_rinex("TestSite", "2025001")

    def test_any_folder_layout(self, tmp_path):
        """Files are found by the date in their names, not by their folder."""
        for directory, name in (("canopy", CANOPY_RNX), ("reference", REFERENCE_RNX)):
            (tmp_path / directory / "2025" / "jan").mkdir(parents=True)
            (tmp_path / directory / "2025" / "jan" / name).touch()
        config = _site_config(tmp_path)
        with patch("canvodpy.workflows.tasks.load_config", return_value=config):
            result = check_rinex("TestSite", "2025-01-01")
        assert result["receivers"]["canopy_01"]["files"] == [
            str(tmp_path / "canopy" / "2025" / "jan" / CANOPY_RNX)
        ]

    def test_overlapping_files_are_an_error(self, mock_site):
        """A daily file next to a 15-minute file of the same day stops the run."""
        base = mock_site.sites.sites["TestSite"].get_base_path()
        daily = CANOPY_RNX.replace("_15M_", "_01D_")
        (base / "canopy" / "25001" / daily).touch()
        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_site):
            with pytest.raises(DiscoveryError, match="cover the same time"):
                check_rinex("TestSite", "2025001")

    def test_receiver_role_mismatch_is_an_error(self, mock_site):
        """Canopy files in the reference directory are not processed."""
        base = mock_site.sites.sites["TestSite"].get_base_path()
        ref = base / "reference" / "25001" / REFERENCE_RNX
        ref.rename(ref.with_name(CANOPY_RNX.replace("ROSA01", "ROSA02")))
        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_site):
            with pytest.raises(DiscoveryError, match="configured as 'reference'"):
                check_rinex("TestSite", "2025001")


class TestCheckSbf:
    """Test check_sbf with mock config and filesystem."""

    @pytest.fixture()
    def mock_site_sbf(self, tmp_path):
        for directory, name in (("canopy", CANOPY_RNX), ("reference", REFERENCE_RNX)):
            day_dir = tmp_path / directory / "25001"
            day_dir.mkdir(parents=True)
            (day_dir / name.replace(".rnx", ".sbf")).touch()
        return _site_config(tmp_path)

    def test_sbf_files_found(self, mock_site_sbf):
        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_site_sbf):
            result = check_sbf("TestSite", "2025001")
        assert result["ready"] is True
        assert all(
            f.endswith(".sbf") for r in result["receivers"].values() for f in r["files"]
        )

    def test_rinex_files_ignored_by_sbf_check(self, mock_site_sbf):
        """check_sbf should NOT find .rnx files."""
        base = mock_site_sbf.sites.sites["TestSite"].get_base_path()
        # Replace .sbf with .rnx
        for sbf in (base / "canopy" / "25001").glob("*.sbf"):
            sbf.rename(sbf.with_suffix(".rnx"))
        for sbf in (base / "reference" / "25001").glob("*.sbf"):
            sbf.rename(sbf.with_suffix(".rnx"))

        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_site_sbf):
            with pytest.raises(RuntimeError, match="missing receivers"):
                check_sbf("TestSite", "2025001")


# ---------------------------------------------------------------------------
# validate_ingest tests
# ---------------------------------------------------------------------------


class TestValidateIngest:
    """Test validate_ingest quality gate."""

    def _make_good_ds(self) -> xr.Dataset:
        """Create a dataset that passes all checks."""
        n_epoch, n_sid = 100, 5
        rng = np.random.default_rng(42)
        return xr.Dataset(
            {"cn0": (("epoch", "sid"), rng.uniform(25, 50, (n_epoch, n_sid)))},
            coords={
                "epoch": np.datetime64("2025-01-01", "s")
                + np.arange(n_epoch).astype("timedelta64[s]"),
                "sid": [f"G{i:02d}|L1|C" for i in range(1, n_sid + 1)],
                "theta": (
                    ("epoch", "sid"),
                    rng.uniform(0, np.pi / 2, (n_epoch, n_sid)),
                ),
                "phi": (
                    ("epoch", "sid"),
                    rng.uniform(0, 2 * np.pi, (n_epoch, n_sid)),
                ),
            },
        )

    def test_good_data_passes(self):
        ds = self._make_good_ds()
        mock_site = MagicMock()
        mock_site.read_receiver_data.return_value = ds

        config = MagicMock()
        config.sites.sites = {"TestSite": MagicMock()}
        config.sites.sites["TestSite"].receivers = {"canopy_01": MagicMock()}

        with (
            patch("canvodpy.workflows.tasks.load_config", return_value=config),
            patch("canvod.store.GnssResearchSite", return_value=mock_site),
        ):
            result = validate_ingest("TestSite", "2025001")
        assert result["valid"] is True

    def test_bad_snr_fails(self):
        ds = self._make_good_ds()
        # Set SNR to impossible values
        ds["cn0"].values[0, 0] = 999.0

        mock_site = MagicMock()
        mock_site.read_receiver_data.return_value = ds

        config = MagicMock()
        config.sites.sites = {"TestSite": MagicMock()}
        config.sites.sites["TestSite"].receivers = {"canopy_01": MagicMock()}

        with (
            patch("canvodpy.workflows.tasks.load_config", return_value=config),
            patch("canvod.store.GnssResearchSite", return_value=mock_site),
        ):
            with pytest.raises(RuntimeError, match="validation failed"):
                validate_ingest("TestSite", "2025001")

    def test_bad_theta_fails(self):
        ds = self._make_good_ds()
        # Set theta beyond π/2
        ds.coords["theta"].values[0, 0] = 2.0

        mock_site = MagicMock()
        mock_site.read_receiver_data.return_value = ds

        config = MagicMock()
        config.sites.sites = {"TestSite": MagicMock()}
        config.sites.sites["TestSite"].receivers = {"canopy_01": MagicMock()}

        with (
            patch("canvodpy.workflows.tasks.load_config", return_value=config),
            patch("canvod.store.GnssResearchSite", return_value=mock_site),
        ):
            with pytest.raises(RuntimeError, match="validation failed"):
                validate_ingest("TestSite", "2025001")

    def test_empty_data_fails(self):
        ds = xr.Dataset(
            {"cn0": (("epoch", "sid"), np.empty((0, 0)))},
            coords={"epoch": [], "sid": []},
        )

        mock_site = MagicMock()
        mock_site.read_receiver_data.return_value = ds

        config = MagicMock()
        config.sites.sites = {"TestSite": MagicMock()}
        config.sites.sites["TestSite"].receivers = {"canopy_01": MagicMock()}

        with (
            patch("canvodpy.workflows.tasks.load_config", return_value=config),
            patch("canvod.store.GnssResearchSite", return_value=mock_site),
        ):
            with pytest.raises(RuntimeError, match="validation failed"):
                validate_ingest("TestSite", "2025001")

    def test_no_data_skips_receiver(self):
        """If read_receiver_data raises, receiver is skipped, not failed."""
        mock_site = MagicMock()
        mock_site.read_receiver_data.side_effect = KeyError("no group")

        config = MagicMock()
        config.sites.sites = {"TestSite": MagicMock()}
        config.sites.sites["TestSite"].receivers = {"canopy_01": MagicMock()}

        with (
            patch("canvodpy.workflows.tasks.load_config", return_value=config),
            patch("canvod.store.GnssResearchSite", return_value=mock_site),
        ):
            # Should not raise — receiver is skipped
            result = validate_ingest("TestSite", "2025001")
            assert "canopy_01" in result["checks"]


# ---------------------------------------------------------------------------
# cleanup tests
# ---------------------------------------------------------------------------


class TestCleanup:
    """Test cleanup task."""

    def test_removes_aux_zarr(self, tmp_path):
        aux_zarr = tmp_path / "aux_2025001.zarr"
        aux_zarr.mkdir()
        (aux_zarr / "data.bin").touch()

        mock_config = MagicMock()
        mock_config.processing.storage.get_aux_data_dir.return_value = tmp_path

        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_config):
            result = cleanup("TestSite", "2025001")

        assert not aux_zarr.exists()
        assert len(result["cleaned"]) == 1

    def test_no_zarr_is_noop(self, tmp_path):
        mock_config = MagicMock()
        mock_config.processing.storage.get_aux_data_dir.return_value = tmp_path

        with patch("canvodpy.workflows.tasks.load_config", return_value=mock_config):
            result = cleanup("TestSite", "2025001")

        assert result["cleaned"] == []


# ---------------------------------------------------------------------------
# validate_data_dirs tests
# ---------------------------------------------------------------------------


class TestValidateDataDirs:
    """validate_data_dirs runs the check of ``canvodpy config validate``."""

    @staticmethod
    def _validate(config):
        with (
            patch("canvod.config.load_config", return_value=config),
            patch("canvodpy.workflows.tasks.load_config", return_value=config),
        ):
            return validate_data_dirs("TestSite")

    def test_valid_site(self, tmp_path):
        for directory, name in (("canopy", CANOPY_RNX), ("reference", REFERENCE_RNX)):
            (tmp_path / directory).mkdir()
            (tmp_path / directory / name).touch()
            (tmp_path / directory / "notes.txt").touch()
        config = _site_config(tmp_path)
        config.processing.params.aggregate_glonass_fdma = False
        with patch(
            "canvodpy.orchestrator.data_check.data_sampling_seconds",
            return_value=5.0,
        ):
            result = self._validate(config)
        assert result["valid"] is True
        canopy = result["receivers"]["canopy_01"]
        assert canopy["identity"] == "ROSA01TUW"
        assert (canopy["days"], canopy["files"], canopy["unrecognized"]) == (1, 1, 1)

    def test_missing_directory_fails(self, tmp_path):
        (tmp_path / "canopy").mkdir()
        (tmp_path / "canopy" / CANOPY_RNX).touch()
        config = _site_config(tmp_path)
        config.processing.params.aggregate_glonass_fdma = False
        with patch(
            "canvodpy.orchestrator.data_check.data_sampling_seconds",
            return_value=5.0,
        ):
            with pytest.raises(ValueError, match=r"\[reference_01\] Directory not"):
                self._validate(config)

    def test_unknown_site(self, tmp_path):
        with pytest.raises(KeyError, match="Unknown site"):
            with patch(
                "canvodpy.workflows.tasks.load_config",
                return_value=_site_config(tmp_path),
            ):
                validate_data_dirs("Elsewhere")
