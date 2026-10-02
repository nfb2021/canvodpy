"""Tests for how the pipeline schedules days from discovered files."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from canvodpy.orchestrator.discovery import ReceiverDay, clear_discovery_cache
from canvodpy.orchestrator.pipeline import PipelineOrchestrator


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("")


def _orchestrator(base: Path) -> PipelineOrchestrator:
    receivers = {
        "canopy_01": SimpleNamespace(
            type="canopy", directory="canopy", reader_format="rinex3", recipe=None
        ),
        "reference_01": SimpleNamespace(
            type="reference", directory="ref", reader_format="auto", recipe=None
        ),
    }
    site_config = SimpleNamespace(
        receivers=receivers,
        get_base_path=lambda: base,
        resolve_paired_canopies=lambda name: ["canopy_01"],
    )
    orch = object.__new__(PipelineOrchestrator)
    orch.site = SimpleNamespace(
        site_name="rosalia",
        _site_config=site_config,
        vod_analyses={
            "a": {"canopy_receiver": "canopy_01", "reference_receiver": "reference_01"}
        },
    )
    orch._logger = mock.MagicMock()
    return orch


def test_days_where_both_receivers_have_files(tmp_path: Path) -> None:
    """Canopy files in one flat folder, reference files in YYDDD folders:
    only the days both receivers cover are scheduled."""
    clear_discovery_cache()
    _touch(
        tmp_path / "canopy",
        "ROSA01TUW_R_20250010000_15M_05S_AA.rnx",
        "ROSA01TUW_R_20250020000_15M_05S_AA.rnx",
    )
    _touch(tmp_path / "ref" / "25002", "ROSR01TUW_R_20250020000_15M_05S_AA.sbf")
    _touch(tmp_path / "ref" / "25003", "ROSR01TUW_R_20250030000_15M_05S_AA.sbf")

    grouped = _orchestrator(tmp_path)._group_by_date_and_receiver()

    assert list(grouped) == ["2025002"]
    canopy_day, _, canopy_pos, canopy_fmt = grouped["2025002"]["canopy_01"]
    assert canopy_day == ReceiverDay("canopy_01", tmp_path / "canopy", "2025002")
    assert (canopy_pos, canopy_fmt) == (None, "rinex3")
    ref_day, ref_type, ref_pos, ref_fmt = grouped["2025002"]["reference_01_canopy_01"]
    assert ref_day == ReceiverDay("reference_01", tmp_path / "ref", "2025002")
    assert ref_type == "reference"
    assert ref_pos == canopy_day  # the canopy's same day gives the position
    assert ref_fmt == "sbf"  # detected, the receiver is configured as auto
