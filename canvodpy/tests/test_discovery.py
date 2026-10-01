"""Tests for the file discovery shared by ``canvodpy run`` and its dry run."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from canvodpy.orchestrator.discovery import (
    DiscoveredFile,
    canonical_name_for,
    check_recipe_receivers,
    detect_reader_format,
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
    rnx = discover_files(tmp_path, "rinex3")
    sbf = discover_files(tmp_path, "sbf")
    both = discover_files(tmp_path, "auto")
    assert [f.path.name for f in rnx] == [CANONICAL]
    assert rnx[0].canonical_name == CANONICAL
    assert [f.path.suffix for f in sbf] == [".sbf"]
    assert len(both) == 2


def test_non_canonical_files_are_ignored(tmp_path: Path) -> None:
    """Without a recipe only names following the convention are processed."""
    _touch(
        tmp_path,
        CANONICAL,
        "rref001a00.25o",  # RINEX v2 short name
        "ROSA00AUT_R_20250010000_01D_30S_MO.rnx",  # RINEX v3 long name
        "rosa001a.rnx",
        "ROSA01TUW_R_20250010045_15M_05S_AA.RNX",  # upper-case extension
        "ROSA01TUW_R_20250010015_15M_05S_AA.rnx.gz",  # compressed
        "ROSA01TUW_R_20250010030_15M_05S_AA.ubx",  # no reader
    )
    assert [f.path.name for f in discover_files(tmp_path, None)] == [CANONICAL]


def test_installed_filemap_does_not_widen_discovery(tmp_path: Path) -> None:
    """Having canvod-filemap installed must not change non-recipe discovery."""
    _touch(tmp_path, CANONICAL, "rref001a00.25o", "rosa001a.rnx")
    fake_patterns = SimpleNamespace(
        BUILTIN_PATTERNS={"any": SimpleNamespace(file_globs=("*",))},
        auto_match_order=lambda: ("any",),
    )
    with mock.patch.dict("sys.modules", {"canvod.filemap.patterns": fake_patterns}):
        found = discover_files(tmp_path, None)
    assert [f.path.name for f in found] == [CANONICAL]


def test_detect_reader_format() -> None:
    rnx = DiscoveredFile(Path("a"), CANONICAL)
    sbf = DiscoveredFile(Path("b"), CANONICAL.replace(".rnx", ".sbf"))
    assert detect_reader_format([sbf]) == "sbf"
    assert detect_reader_format([rnx, sbf]) == "rinex3"
    assert detect_reader_format([]) == "rinex3"


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


def _recipes(**recipes: SimpleNamespace):
    """Patch recipe loading to return the given recipes by name."""
    return (
        mock.patch(
            "canvodpy.orchestrator.discovery.resolve_recipe_path",
            side_effect=lambda name: name,
        ),
        mock.patch(
            "canvodpy.orchestrator.discovery._load_recipe",
            side_effect=lambda name: recipes[name],
        ),
    )


def _recipe(receiver_type: str, number: int) -> SimpleNamespace:
    return SimpleNamespace(
        site="ROS", agency="TUW", receiver_type=receiver_type, receiver_number=number
    )


def test_recipe_receivers_with_distinct_identities_pass() -> None:
    receivers = {
        "reference_01": {"type": "reference", "recipe": "ref"},
        "canopy_01": {"type": "canopy", "recipe": "can1"},
        "canopy_02": {"type": "canopy", "recipe": "can2"},
        "canopy_03": {"type": "canopy", "recipe": None},
    }
    a, b = _recipes(
        ref=_recipe("reference", 1),
        can1=_recipe("canopy", 1),
        can2=_recipe("canopy", 2),
    )
    with a, b:
        check_recipe_receivers(receivers)


def test_shared_recipe_identity_is_rejected() -> None:
    """Two canopies sharing one recipe would both be named ROSA01TUW."""
    receivers = {
        "canopy_01": {"type": "canopy", "recipe": "can"},
        "canopy_02": {"type": "canopy", "recipe": "can"},
    }
    a, b = _recipes(can=_recipe("canopy", 1))
    with a, b, pytest.raises(ValueError, match="ROSA01TUW"):
        check_recipe_receivers(receivers)


def test_recipe_receiver_type_must_match() -> None:
    receivers = {"canopy_01": {"type": "canopy", "recipe": "ref"}}
    a, b = _recipes(ref=_recipe("reference", 1))
    with a, b, pytest.raises(ValueError, match="receiver_type 'reference'"):
        check_recipe_receivers(receivers)
