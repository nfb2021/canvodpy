"""Test RINEX v2.11 reader functionality."""

from pathlib import Path

import pytest
import xarray as xr

from canvod.readers.rinex.v2_11 import Rnxv2Header, Rnxv2Obs

# Test data paths
TEST_DATA_DIR = Path(__file__).parent / "test_data"
RINEX_V2_FILE = (
    TEST_DATA_DIR
    / "valid/rinex_v2_11/02_Moflux/01_reference/25001/MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
)


@pytest.fixture
def rinex_v2_file():
    """Fixture providing path to test RINEX v2.11 file."""
    if not RINEX_V2_FILE.exists():
        pytest.skip(f"Test file not found: {RINEX_V2_FILE}")
    return RINEX_V2_FILE


class TestRnxv2Header:
    """Tests for RINEX v2.11 header parsing."""

    def test_header_from_file(self, rinex_v2_file):
        """Test header can be parsed from file."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header is not None
        assert header.version == pytest.approx(2.11)
        assert header.fpath == rinex_v2_file

    def test_header_required_fields(self, rinex_v2_file):
        """Test header contains required fields."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.marker_name
        assert header.receiver_type
        assert header.antenna_type
        assert header.observer
        assert header.agency

    def test_header_position_data(self, rinex_v2_file):
        """Test header position information."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert len(header.approx_position) == 3
        assert len(header.antenna_delta) == 3

        for pos in header.approx_position:
            assert hasattr(pos, "magnitude")
            assert hasattr(pos, "units")

    def test_header_observation_types(self, rinex_v2_file):
        """Test v2 observation types are parsed."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.obs_types
        assert isinstance(header.obs_types, list)
        assert len(header.obs_types) > 0
        # v2 uses 2-char codes like L1, L2, C1, P1, P2, S1, S2
        for ot in header.obs_types:
            assert len(ot) == 2

    def test_header_obs_codes_per_system(self, rinex_v2_file):
        """Test obs codes are mapped to v3 format per system."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.obs_codes_per_system
        assert isinstance(header.obs_codes_per_system, dict)
        assert len(header.obs_codes_per_system) > 0

        # Mapped codes should be 3-char v3 format
        for sys_codes in header.obs_codes_per_system.values():
            for code in sys_codes:
                assert len(code) == 3

    def test_header_version_is_v2(self, rinex_v2_file):
        """Test that parsed version is 2.x."""
        header = Rnxv2Header.from_file(rinex_v2_file)
        assert header.version >= 2.0
        assert header.version < 3.0

    def test_header_time_of_first_obs(self, rinex_v2_file):
        """Test time of first observation is parsed."""
        header = Rnxv2Header.from_file(rinex_v2_file)

        assert header.t0
        assert len(header.t0) > 0
        assert header.time_system in ("GPS", "GLO", "GAL", "UTC")

    def test_header_mixed_system(self, rinex_v2_file):
        """Test mixed system file is recognized."""
        header = Rnxv2Header.from_file(rinex_v2_file)
        # The test file has "M (MIXED)" in the header
        assert header.systems == "M"


class TestRnxv2Obs:
    """Tests for RINEX v2.11 observation reader."""

    def test_obs_initialization(self, rinex_v2_file):
        """Test Rnxv2Obs can be initialized."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        assert obs is not None
        assert obs.fpath == rinex_v2_file
        assert obs.header is not None

    def test_obs_header_access(self, rinex_v2_file):
        """Test header is accessible from obs object."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        assert obs.header.version == pytest.approx(2.11)
        assert obs.header.marker_name

    def test_epoch_iteration(self, rinex_v2_file):
        """Test epoch iteration works."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        epochs = list(obs.iter_epochs())

        assert len(epochs) > 0

        first_epoch = epochs[0]
        assert first_epoch.year == 2025
        assert first_epoch.month == 1
        assert first_epoch.day == 1
        assert len(first_epoch.satellites) > 0

    def test_epoch_has_satellites(self, rinex_v2_file):
        """Test epochs contain satellite observations."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        first_epoch = next(obs.iter_epochs())

        assert first_epoch.num_satellites > 0
        assert len(first_epoch.satellite_list) > 0
        assert len(first_epoch.satellites) > 0

    def test_sampling_interval_inference(self, rinex_v2_file):
        """Test sampling interval can be inferred."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        interval = obs.infer_sampling_interval()

        if interval is not None:
            assert interval.magnitude > 0
            assert hasattr(interval, "units")

    def test_to_ds_basic(self, rinex_v2_file):
        """Test conversion to xarray Dataset."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "SNR" in ds.data_vars

    def test_to_ds_coordinates(self, rinex_v2_file):
        """Test Dataset has required coordinates."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        required_coords = ["epoch", "sid", "sv", "system", "band", "code"]
        for coord in required_coords:
            assert coord in ds.coords, f"Missing coordinate: {coord}"

    def test_to_ds_frequency_info(self, rinex_v2_file):
        """Test Dataset has frequency information."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert "freq_center" in ds.coords
        assert "freq_min" in ds.coords
        assert "freq_max" in ds.coords

    def test_to_ds_metadata(self, rinex_v2_file):
        """Test Dataset has required global attributes."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert "Created" in ds.attrs
        assert "Software" in ds.attrs
        assert "Institution" in ds.attrs
        assert "File Hash" in ds.attrs

    def test_file_hash_generation(self, rinex_v2_file):
        """Test file hash is generated."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        file_hash = obs.file_hash

        assert file_hash
        assert len(file_hash) == 16
        assert all(c in "0123456789abcdef" for c in file_hash)

    def test_multiple_data_vars(self, rinex_v2_file):
        """Test keeping multiple data variables."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"],
            pad_global_sid=False,
        )

        assert "SNR" in ds.data_vars
        assert "Pseudorange" in ds.data_vars
        assert "Phase" in ds.data_vars

    def test_create_rinex_netcdf_with_signal_id(self, rinex_v2_file):
        """Test the raw dataset creation method."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)

        ds = obs.create_rinex_netcdf_with_signal_id()

        assert isinstance(ds, xr.Dataset)
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        # Raw dataset should have all data vars
        assert "SNR" in ds.data_vars
        assert "Pseudorange" in ds.data_vars
        assert "Phase" in ds.data_vars
        assert "Doppler" in ds.data_vars
        assert "LLI" in ds.data_vars
        assert "SSI" in ds.data_vars


class TestRnxv2SignalMapping:
    """Tests for signal ID mapping in RINEX v2."""

    def test_signal_ids_format(self, rinex_v2_file):
        """Test signal IDs have correct SV|BAND|CODE format."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        for sid in ds.sid.values:
            parts = str(sid).split("|")
            assert len(parts) == 3, f"Invalid signal ID format: {sid}"

            sv, band, code = parts
            assert len(sv) == 3, f"SV should be 3 chars: {sv}"
            assert sv[0] in "GRECJSI", f"Invalid system prefix: {sv[0]}"
            assert sv[1:3].isdigit(), f"PRN should be digits: {sv[1:3]}"

    def test_system_coordinate_matches_sid(self, rinex_v2_file):
        """Test system coordinate matches signal IDs."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        for i, sid in enumerate(ds.sid.values):
            sv_system = str(sid).split("|")[0][0]
            dataset_system = str(ds.system.values[i])

            if dataset_system == "nan":
                continue

            assert dataset_system == sv_system

    def test_mixed_constellations(self, rinex_v2_file):
        """Test that multiple GNSS systems are present in mixed file."""
        obs = Rnxv2Obs(fpath=rinex_v2_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        systems_found = set()
        for sid in ds.sid.values:
            systems_found.add(str(sid).split("|")[0][0])

        # The test file is mixed (M), should have multiple systems
        assert len(systems_found) > 1, (
            f"Expected multiple systems, got: {systems_found}"
        )


class TestRnxv2ErrorHandling:
    """Tests for error handling."""

    def test_nonexistent_file(self):
        """Test error on nonexistent file."""
        with pytest.raises((ValueError, FileNotFoundError)):
            Rnxv2Obs(fpath=Path("/nonexistent/file.25o"))

    def test_header_nonexistent_file(self):
        """Test error on nonexistent file for header."""
        with pytest.raises((ValueError, FileNotFoundError)):
            Rnxv2Header.from_file(Path("/nonexistent/file.25o"))


class TestRnxv2MultipleFiles:
    """Tests reading multiple RINEX v2.11 files."""

    CANOPY_DIR = TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/02_canopy/25001"
    REFERENCE_DIR = TEST_DATA_DIR / "valid/rinex_v2_11/02_Moflux/01_reference/25001"

    def test_read_canopy_file(self):
        """Test reading a canopy receiver file."""
        canopy_file = self.CANOPY_DIR / "MOZA01CAL_R_20250010000_01H_15S_AA.rnx"
        if not canopy_file.exists():
            pytest.skip(f"Test file not found: {canopy_file}")

        obs = Rnxv2Obs(fpath=canopy_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_read_reference_file(self):
        """Test reading a reference receiver file."""
        ref_file = self.REFERENCE_DIR / "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
        if not ref_file.exists():
            pytest.skip(f"Test file not found: {ref_file}")

        obs = Rnxv2Obs(fpath=ref_file)
        ds = obs.to_ds(keep_data_vars=["SNR"], pad_global_sid=False)

        assert isinstance(ds, xr.Dataset)
        assert ds.sizes["epoch"] > 0
        assert ds.sizes["sid"] > 0

    def test_reference_and_canopy_share_sids(self):
        """Test that reference and canopy files share common signal IDs."""
        ref_file = self.REFERENCE_DIR / "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
        canopy_file = self.CANOPY_DIR / "MOZA01CAL_R_20250010000_01H_15S_AA.rnx"

        if not ref_file.exists() or not canopy_file.exists():
            pytest.skip("Test files not found")

        ref_ds = Rnxv2Obs(fpath=ref_file).to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False
        )
        canopy_ds = Rnxv2Obs(fpath=canopy_file).to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False
        )

        ref_sids = set(str(s) for s in ref_ds.sid.values)
        canopy_sids = set(str(s) for s in canopy_ds.sid.values)

        common_sids = ref_sids & canopy_sids
        assert len(common_sids) > 0, "Reference and canopy should share signal IDs"

    def test_file_hashes_differ(self):
        """Test that different files produce different hashes."""
        ref_file = self.REFERENCE_DIR / "MOZR01CAL_R_20250010000_01H_15S_AA.rnx"
        canopy_file = self.CANOPY_DIR / "MOZA01CAL_R_20250010000_01H_15S_AA.rnx"

        if not ref_file.exists() or not canopy_file.exists():
            pytest.skip("Test files not found")

        ref_obs = Rnxv2Obs(fpath=ref_file)
        canopy_obs = Rnxv2Obs(fpath=canopy_file)

        assert ref_obs.file_hash != canopy_obs.file_hash


@pytest.mark.parametrize("data_var", ["SNR", "Pseudorange", "Phase", "Doppler"])
def test_individual_data_vars(rinex_v2_file, data_var):
    """Test each data variable can be read individually."""
    obs = Rnxv2Obs(fpath=rinex_v2_file)
    ds = obs.to_ds(keep_data_vars=[data_var], pad_global_sid=False)

    assert data_var in ds.data_vars
    assert ds[data_var].dims == ("epoch", "sid")
