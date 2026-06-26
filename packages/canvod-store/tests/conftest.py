"""Pytest configuration and shared fixtures for canvod-store tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).parent
_FIXTURES_DIR = _TESTS_DIR / "fixtures"
DAY0_STORE_PATH = _FIXTURES_DIR / "day0_store"

TEST_DATA_ROOT = (
    Path(__file__).parents[3]  # repo root
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
    / "valid"
)

RINEX_CANOPY_DIR = (
    TEST_DATA_ROOT
    / "rinex_v3_04"
    / "01_Rosalia"
    / "02_canopy"
    / "01_GNSS"
    / "01_raw"
    / "25001"
)

RINEX_REFERENCE_DIR = (
    TEST_DATA_ROOT
    / "rinex_v3_04"
    / "01_Rosalia"
    / "01_reference"
    / "01_GNSS"
    / "01_raw"
    / "25001"
)

# ---------------------------------------------------------------------------
# Synthetic dataset helpers
# ---------------------------------------------------------------------------

# Realistic SID strings matching the canvod SV|Band|Code convention
GROUP = "canopy_01"


def _array_checksum(arr: np.ndarray) -> str:
    """SHA-256 of array bytes (NaN → 0 before hashing for stability)."""
    safe = np.where(np.isnan(arr.astype(float)), 0.0, arr.astype(float))
    return hashlib.sha256(safe.tobytes()).hexdigest()[:16]


_SIDS = [
    f"{sv}|{band}|{code}"
    for sv in [
        "G01",
        "G02",
        "G03",
        "G04",
        "G05",
        "G06",
        "G07",
        "G08",
        "E01",
        "E02",
        "E03",
        "E04",
        "E05",
        "R01",
        "R02",
        "R03",
        "R04",
        "C01",
        "C02",
        "C03",
    ]
    for band, code in [("L1", "C"), ("L2", "W")]
]
N_SIDS = len(_SIDS)  # 40 — representative, not full 321 (keeps tests fast)


def make_synthetic_dataset(
    slot: int,
    n_epochs: int = 180,
    seed: int = 0,
    day: str = "2025-01-01",
) -> xr.Dataset:
    """Return a synthetic GNSS dataset resembling real RINEX v3 output.

    Parameters
    ----------
    slot : int
        15-minute slot index (0 = 00:00, 1 = 00:15, …).
    n_epochs : int
        Number of epochs (180 = 15 min at 5 s cadence).
    seed : int
        RNG seed for reproducibility.
    day : str
        ISO date string for the epoch start.

    Returns
    -------
    xr.Dataset
        Dataset with dims ``(epoch, sid)`` and a ``"File Hash"`` attribute.
    """
    rng = np.random.default_rng(seed + slot)

    base = np.datetime64(f"{day}T{(slot * 15) // 60:02d}:{(slot * 15) % 60:02d}:00")
    epochs = base + np.arange(n_epochs) * np.timedelta64(5, "s")

    # Sparse SNR: ~80% of cells observed, rest NaN (realistic)
    s1c = rng.uniform(30.0, 55.0, (n_epochs, N_SIDS)).astype(np.float32)
    mask = rng.random((n_epochs, N_SIDS)) > 0.8
    s1c[mask] = np.nan

    s2w = s1c - rng.uniform(1.0, 3.0, (n_epochs, N_SIDS)).astype(np.float32)
    s2w[mask] = np.nan

    # Stable hash derived from slot + seed (deterministic)
    raw = f"slot={slot}|seed={seed}|day={day}".encode()
    file_hash = hashlib.sha256(raw).hexdigest()[:16]

    ds = xr.Dataset(
        {
            "S1C": xr.DataArray(s1c, dims=["epoch", "sid"]),
            "S2W": xr.DataArray(s2w, dims=["epoch", "sid"]),
        },
        coords={
            "epoch": epochs,
            "sid": _SIDS,
        },
        attrs={
            "File Hash": file_hash,
            "station": "ROST",
            "receiver": "canopy_01",
        },
    )
    return ds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def synthetic_day() -> list[xr.Dataset]:
    """Return 4 synthetic 15-min datasets covering the first hour of a day."""
    return [make_synthetic_dataset(slot=i) for i in range(4)]


@pytest.fixture
def tmp_store(tmp_path):
    """Return a fresh MyIcechunkStore in a temporary directory."""
    from canvod.store import MyIcechunkStore

    return MyIcechunkStore(tmp_path / "test_store")


@pytest.fixture(scope="session")
def day0_store_path() -> Path:
    """Return the path to the frozen day 0 regression store.

    Skip the test if the fixture hasn't been built yet — run
    ``python packages/canvod-store/tests/build_day0_store.py`` first.
    """
    if not DAY0_STORE_PATH.exists():
        pytest.skip(
            f"Day 0 store not found at {DAY0_STORE_PATH}. "
            "Run `python packages/canvod-store/tests/build_day0_store.py` first."
        )
    return DAY0_STORE_PATH


@pytest.fixture(scope="session")
def day0_snapshot(day0_store_path) -> dict[str, Any]:
    """Load the day 0 snapshot metadata from the fixture directory."""
    import json

    snapshot_file = _FIXTURES_DIR / "day0_snapshot.json"
    if not snapshot_file.exists():
        pytest.skip("Day 0 snapshot JSON not found.")
    return json.loads(snapshot_file.read_text())
