"""Test RINEX v2.11 reader functionality."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from canvod.readers.gnss_specs.constellations import V2_UNRESOLVED_CODES
from canvod.readers.preprocessing import pad_to_global_sid
from canvod.readers.rinex.v2_11 import Rnxv2Header, Rnxv2Obs, _v2_tracking_code

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


# Spec rows: rinex211.txt Table A1 ("C: Pseudorange GPS: C/A, L2C; Glonass:
# C/A; Galileo: All", "P: Pseudorange GPS and Glonass: P code") and section
# 10.1 (v2 codes cannot express the underlying code or channel).
_V2_TRACKING_CODE_CASES = [
    ("G", "C1", "L1", "C"),  # C/A: defined by the v2 code
    ("G", "P1", "L1", "p"),  # P family: P/W/Y/D under AS not recorded
    ("G", "C2", "L2", "l"),  # L2C family: S/L/X channel not recorded
    ("G", "P2", "L2", "p"),
    ("G", "L1", "L1", "u"),  # phase: no code information at all
    ("G", "S2", "L2", "u"),  # SNR belongs to "the respective phase"
    ("G", "D1", "L1", "u"),
    ("G", "C5", "L5", "u"),  # L5 I/Q/X not recorded
    ("R", "C1", "G1", "C"),  # GLONASS C/A
    ("R", "P2", "G2", "P"),  # GLONASS P code is unencrypted: exact
    ("R", "L1", "G1", "u"),
    ("R", "C1", "G1_FDMA", "C"),  # same codes without FDMA aggregation
    ("E", "C1", "E1", "u"),  # Galileo "C" means "All"
    ("E", "L5", "E5a", "u"),
    ("S", "C1", "L1", "C"),  # SBAS L1 carries only C/A ...
    ("S", "L1", "L1", "C"),  # ... so even phase/SNR resolve exactly
    ("S", "C5", "L5", "u"),
]


class TestRnxv2TrackingCodes:
    """Tracking codes follow RINEX 2.11 instead of guessed RINEX 3 attributes."""

    @pytest.mark.parametrize(
        ("system", "obs_code", "band", "expected"), _V2_TRACKING_CODE_CASES
    )
    def test_tracking_code_follows_rinex211(self, system, obs_code, band, expected):
        assert _v2_tracking_code(system, obs_code, band) == expected

    def test_markers_can_never_be_rinex_attributes(self):
        # RINEX observation codes are uppercase-only; a marker must not
        # collide with a real attribute (e.g. "X" = L2C M+L).
        assert len(set(V2_UNRESOLVED_CODES)) == len(V2_UNRESOLVED_CODES)
        assert all(code.islower() and len(code) == 1 for code in V2_UNRESOLVED_CODES)

    def test_mixed_file_sids(self, rinex_v2_file):
        """Obs types L1 L2 C1 P1 P2 S1 S2 yield exactly these band|code pairs."""
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"], pad_global_sid=False
        )
        by_system: dict[str, set[str]] = {}
        for sid in ds.sid.values:
            sv, band_code = str(sid).split("|", 1)
            by_system.setdefault(sv[0], set()).add(band_code)
        assert by_system["G"] == {"L1|C", "L1|p", "L1|u", "L2|p", "L2|u"}
        assert by_system["R"] == {"G1|C", "G1|P", "G1|u", "G2|P", "G2|u"}
        assert by_system["E"] == {"E1|u"}
        assert by_system["S"] == {"L1|C"}

    def test_observables_land_on_their_sids(self, rinex_v2_file):
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"], pad_global_sid=False
        )
        gps = ds.sel(sid=[s for s in ds.sid.values if str(s).startswith("G")])
        has = {
            var: {
                str(s).split("|", 1)[1]
                for s in gps.sid.values[gps[var].notnull().any("epoch").values]
            }
            for var in ("Pseudorange", "Phase", "SNR")
        }
        assert has["Pseudorange"] == {"L1|C", "L1|p", "L2|p"}
        assert has["Phase"] == {"L1|u", "L2|u"}
        assert has["SNR"] == {"L1|u", "L2|u"}

    def test_global_padding_keeps_every_observation(self, rinex_v2_file):
        """Regression: padding onto the global sid space used to drop GLONASS,
        SBAS and Galileo phase/SNR (41 % of them in this file), because their
        v2 sids were not in any constellation's BAND_CODES."""
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR", "Pseudorange", "Phase"], pad_global_sid=False
        )
        padded = pad_to_global_sid(ds)
        assert set(ds.sid.values) <= set(padded.sid.values)
        for var in ("SNR", "Pseudorange", "Phase"):
            assert int(np.isfinite(padded[var]).sum()) == int(
                np.isfinite(ds[var]).sum()
            )

    def test_markers_documented_in_attrs(self, rinex_v2_file):
        ds = Rnxv2Obs(fpath=rinex_v2_file).to_ds(
            keep_data_vars=["SNR"], pad_global_sid=False
        )
        assert ds.attrs["RINEX Version"] == "2.11"
        assert "'u' = carrier band only" in ds.attrs["Tracking Code Markers"]

    def test_header_codes_are_system_specific(self, rinex_v2_file):
        codes = Rnxv2Header.from_file(rinex_v2_file).obs_codes_per_system
        assert codes["G"] == ["L1u", "L2u", "C1C", "C1p", "C2p", "S1u", "S2u"]
        assert codes["R"] == ["L1u", "L2u", "C1C", "C1P", "C2P", "S1u", "S2u"]


def _v2_obs_field(value: float, lli: int | None) -> str:
    """One F14.3 + LLI + SSI observation field."""
    return f"{value:14.3f}{'' if lli is None else lli:1}{' '}"


def test_lli_flags_of_phase_and_snr_are_merged(rinex_v2_file, tmp_path):
    """Phase and signal strength share a sid. teqc sets the AS bit (4) on every
    observable, so S1's LLI must not overwrite L1's slip bit (LLI 5 = 4 | 1)."""
    lines = rinex_v2_file.read_text(encoding="ascii", errors="replace").splitlines()
    header = lines[
        : next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    ]
    # obs types: L1 L2 C1 P1 P2 S1 S2 (5 fields per line)
    fields = [
        _v2_obs_field(1.0e8, 5),  # L1: slip + AS
        _v2_obs_field(8.0e7, 4),  # L2: AS
        _v2_obs_field(2.1e7, 4),  # C1
        _v2_obs_field(2.1e7, 4),  # P1
        _v2_obs_field(2.1e7, 4),  # P2
        _v2_obs_field(45.0, 4),  # S1: AS only
        _v2_obs_field(40.0, 4),  # S2
    ]
    body = [
        " 25  1  1  0  0  0.0000000  0  1G01",
        "".join(fields[:5]),
        "".join(fields[5:]),
    ]
    path = tmp_path / "lli.25o"
    path.write_text("\n".join([*header, *body]) + "\n", encoding="ascii")

    ds = Rnxv2Obs(fpath=path).to_ds(
        keep_data_vars=["Phase", "SNR", "LLI"], pad_global_sid=False
    )
    assert int(ds.LLI.sel(sid="G01|L1|u").item()) == 5
    assert int(ds.LLI.sel(sid="G01|L2|u").item()) == 4


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
