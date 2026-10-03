"""Tests for the write-time overlap check among the files of one batch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor


def _processor() -> RinexDataProcessor:
    proc = object.__new__(RinexDataProcessor)
    store = SimpleNamespace(load_metadata_for_dedup=lambda _receiver: None)
    proc.site = SimpleNamespace(gnss_store=store)
    proc._logger = mock.MagicMock()
    return proc


def _file(name: str, start: str, minutes: int) -> tuple[Path, xr.Dataset]:
    epochs = np.datetime64(start) + np.arange(0, minutes * 60, 5).astype(
        "timedelta64[s]"
    )
    return Path(name), xr.Dataset(coords={"epoch": epochs})


def _skipped(*files: tuple[Path, xr.Dataset]) -> set[str]:
    hashes = {fname: fname.name for fname, _ in files}
    return _processor()._check_existing_with_temporal_overlap("rx", list(files), hashes)


def test_adjacent_files_are_kept() -> None:
    assert not _skipped(
        _file("a", "2025-01-01T00:00", 15), _file("b", "2025-01-01T00:15", 15)
    )


def test_daily_file_next_to_sub_daily_files_is_skipped() -> None:
    files = [_file("day", "2025-01-01T00:00", 1440)] + [
        _file(f"q{i}", f"2025-01-01T00:{15 * i:02d}", 15) for i in range(4)
    ]
    assert _skipped(*files) == {"day"}


@pytest.mark.parametrize(
    ("second", "start"),
    [("same", "2025-01-01T00:00"), ("partial", "2025-01-01T00:10")],
)
def test_of_two_overlapping_files_one_is_kept(second: str, start: str) -> None:
    assert _skipped(
        _file("first", "2025-01-01T00:00", 15), _file(second, start, 15)
    ) == {second}
