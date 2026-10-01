"""GNSS data-file discovery shared by the pipeline run and its dry-run preview.

One code path decides which files in a receiver's per-day directory are
processed, so ``canvodpy run --dry-run`` reports exactly the files a real run
would ingest.

Discovery per receiver:

1. **Recipe** -- when the receiver config sets ``recipe:``, the naming recipe
   (``canvod-filemap``) selects the files and maps each to its canonical
   canVOD name. This is the only way non-canonical filenames are processed.
2. **Canonical convention** -- otherwise, only files whose names follow the
   canVOD naming convention (``canvod-preflight``) are processed, restricted
   by ``reader_format``. Other files in the directory are ignored. Compressed
   files are not selected, because the readers do not decompress.

Whether ``canvod-filemap`` is installed does not change (2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from natsort import natsorted


@dataclass(frozen=True)
class DiscoveredFile:
    """One GNSS data file selected for processing."""

    path: Path
    canonical_name: str


def canonical_name_for(path: Path | str) -> str:
    """Return the canonical canVOD filename for ``path``, or ``""``.

    The physical filename is parsed against the canVOD naming convention;
    a name that does not follow it yields ``""``.
    """
    from canvod.preflight.convention import CanVODFilename

    try:
        return CanVODFilename.from_filename(Path(path).name).name
    except ValueError:
        return ""


def resolve_recipe_path(recipe_name: str) -> Path:
    """Resolve a recipe name to ``recipes/{recipe_name}.yaml``.

    Searches the active config directory (``CANVOD_CONFIG_DIR``) first, then
    ``config/recipes/`` in the monorepo root.

    Raises
    ------
    FileNotFoundError
        If no recipe file with that name exists in either location.
    """
    candidates: list[Path] = []
    env_dir = os.environ.get("CANVOD_CONFIG_DIR")
    if env_dir:
        candidates.append(Path(env_dir) / "recipes" / f"{recipe_name}.yaml")
    try:
        from canvod.config.loader import find_monorepo_root

        candidates.append(
            find_monorepo_root() / "config" / "recipes" / f"{recipe_name}.yaml"
        )
    except RuntimeError:
        pass

    for candidate in candidates:
        if candidate.exists():
            return candidate

    searched = ", ".join(str(c) for c in candidates) or "(no search location)"
    msg = (
        f"Recipe file not found for '{recipe_name}' (searched: {searched})\n"
        f"Create it with: just naming-init {recipe_name}"
    )
    raise FileNotFoundError(msg)


@lru_cache(maxsize=32)
def _load_recipe(recipe_path: Path) -> Any:
    from canvod.filemap.recipe import NamingRecipe

    return NamingRecipe.load(recipe_path)


#: File types each reader format reads (``None``/``"auto"``: all of them).
_READER_FILE_TYPES: dict[str | None, frozenset[str]] = {
    "sbf": frozenset({"sbf"}),
    "rinex3": frozenset({"rnx"}),
    "rinex": frozenset({"rnx"}),
}
_ALL_FILE_TYPES = frozenset({"rnx", "sbf"})


def _canonical_file(path: Path, file_types: frozenset[str]) -> DiscoveredFile | None:
    """``path`` as a discovered file if its name follows the convention."""
    from canvod.preflight.convention import CanVODFilename

    try:
        parsed = CanVODFilename.from_filename(path.name)
    except ValueError:
        return None
    if parsed.compression is not None or parsed.file_type.value not in file_types:
        return None
    return DiscoveredFile(path=path, canonical_name=parsed.name)


def discover_files(
    data_dir: Path,
    reader_format: str | None = None,
    recipe: str | None = None,
) -> list[DiscoveredFile]:
    """Select the GNSS data files in ``data_dir`` that a run processes.

    Parameters
    ----------
    data_dir : Path
        A receiver's per-day data directory.
    reader_format : str | None
        Receiver reader format (``"rinex3"``, ``"rinex"``, ``"sbf"``, or
        ``None``/``"auto"`` for all recognized types). Ignored in recipe mode,
        where the recipe's glob selects the files.
    recipe : str | None
        Name of the receiver's naming recipe, if configured.

    Returns
    -------
    list[DiscoveredFile]
        Naturally sorted by physical path.
    """
    if not data_dir.exists():
        return []

    if recipe:
        naming_recipe = _load_recipe(resolve_recipe_path(recipe))
        found = [
            DiscoveredFile(
                path=f,
                canonical_name=naming_recipe.to_virtual_file(f).canonical_str,
            )
            for f in data_dir.glob(naming_recipe.glob)
            if f.is_file() and naming_recipe.matches(f.name)
        ]
        return natsorted(found, key=lambda d: str(d.path))

    file_types = _READER_FILE_TYPES.get(reader_format, _ALL_FILE_TYPES)
    found = [
        discovered
        for path in data_dir.iterdir()
        if path.is_file()
        and (discovered := _canonical_file(path, file_types)) is not None
    ]
    return natsorted(found, key=lambda d: str(d.path))


def detect_reader_format(files: list[DiscoveredFile]) -> str:
    """Reader format for a receiver whose config says ``reader_format: auto``.

    Decided from the canonical names of the discovered files: ``"sbf"`` if
    they are all SBF, otherwise ``"rinex3"``.
    """
    suffixes = {Path(f.canonical_name).suffix for f in files if f.canonical_name}
    if suffixes == {".sbf"}:
        return "sbf"
    return "rinex3"


def recipe_for_data_dir(site_config: Any, data_dir: Path) -> str | None:
    """Return the recipe of the receiver whose per-day directories hold ``data_dir``.

    Per-day directories sit at ``{gnss_site_data_root}/{receiver.directory}/{YYDDD}``.
    """
    base = site_config.get_base_path()
    parent = Path(data_dir).parent
    for receiver_cfg in site_config.receivers.values():
        if (base / receiver_cfg.directory) == parent:
            return receiver_cfg.recipe
    return None
