"""Tests for the file discovery shared by ``canvodpy run`` and its dry run."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from canvodpy.orchestrator.discovery import (
    canonical_name_for,
    discover_files,
    recipe_for_data_dir,
    resolve_recipe_path,
)

CANONICAL = "ROSA01TUW_R_20250010000_15M_05S_AA.rnx"


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("")


def test_canonical_name_for() -> None:
    assert canonical_name_for(Path("/data") / CANONICAL) == CANONICAL
    assert canonical_name_for("rref001a00.25o") == ""


def test_convention_discovery_by_reader_format(tmp_path: Path) -> None:
    _touch(tmp_path, CANONICAL, "ROSA01TUW_R_20250010000_15M_05S_AA.sbf", "x.txt")
    with mock.patch.dict("sys.modules", {"canvod.filemap.patterns": None}):
        rnx = discover_files(tmp_path, "rinex3")
        sbf = discover_files(tmp_path, "sbf")
    assert [f.path.name for f in rnx] == [CANONICAL]
    assert rnx[0].canonical_name == CANONICAL
    assert [f.path.suffix for f in sbf] == [".sbf"]


def test_missing_directory_yields_nothing(tmp_path: Path) -> None:
    assert discover_files(tmp_path / "absent", "rinex3") == []


def test_recipe_for_data_dir(tmp_path: Path) -> None:
    site_config = SimpleNamespace(
        get_base_path=lambda: tmp_path,
        receivers={
            "reference_01": SimpleNamespace(directory="01_reference", recipe="ref"),
            "canopy_01": SimpleNamespace(directory="02_canopy", recipe=None),
        },
    )
    assert (
        recipe_for_data_dir(site_config, tmp_path / "01_reference" / "25001") == "ref"
    )
    assert recipe_for_data_dir(site_config, tmp_path / "02_canopy" / "25001") is None
    assert recipe_for_data_dir(site_config, tmp_path / "other" / "25001") is None


def test_resolve_recipe_path_prefers_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch(tmp_path / "recipes", "ref.yaml")
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    assert resolve_recipe_path("ref") == tmp_path / "recipes" / "ref.yaml"
    with pytest.raises(FileNotFoundError):
        resolve_recipe_path("does_not_exist")


def test_recipe_drives_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receiver recipe selects non-canonical files and maps their names."""
    pytest.importorskip("canvod.filemap.recipe")
    (tmp_path / "recipes").mkdir()
    (tmp_path / "recipes" / "ros_ref.yaml").write_text(
        "name: ros_ref\n"
        "site: ROS\n"
        "agency: TUW\n"
        "receiver_number: 1\n"
        "receiver_type: reference\n"
        "sampling: '05S'\n"
        "period: '15M'\n"
        "file_type: rnx\n"
        "glob: '*.??o'\n"
        "fields:\n"
        "  - skip: 4\n"
        "  - doy: 3\n"
        "  - hour_letter: 1\n"
        "  - minute: 2\n"
        "  - skip: 1\n"
        "  - yy: 2\n"
        "  - skip: 1\n"
    )
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    data_dir = tmp_path / "01_reference" / "25001"
    _touch(data_dir, "rref001a15.25o", CANONICAL)

    found = discover_files(data_dir, "rinex3", recipe="ros_ref")

    assert [f.path.name for f in found] == ["rref001a15.25o"]
    assert found[0].canonical_name == "ROSR01TUW_R_20250010015_15M_05S_AA.rnx"
