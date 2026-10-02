"""GNSS data-file discovery shared by the pipeline run and its dry-run preview.

One code path decides which files of a receiver are processed for a day, so
``canvodpy run --dry-run`` reports exactly the files a real run would ingest.

Each receiver's configured ``directory`` is scanned recursively once per run.
Hidden directories are skipped and symbolic links are not followed. A file's
day comes from the date in its (canonical) name, not from the folder it sits
in, so any folder layout works: all files in one folder, one folder per day
(``YYDDD`` or ``YYYYDDD``), or deeper nesting. A file belongs to the day it
starts on.

Which files count:

1. **Recipe** -- when the receiver config sets ``recipe:``, the naming recipe
   (``canvod-filemap``) selects the files and maps each to its canonical
   canVOD name. This is the only way non-canonical filenames are processed,
   and the recipe sets the receiver identity (e.g. ``ROSA01TUW``).
2. **Canonical convention** -- otherwise, only files whose names follow the
   canVOD naming convention (``canvod-preflight``) are processed, restricted
   by ``reader_format``. Compressed files are not selected, because the
   readers do not decompress. Whether ``canvod-filemap`` is installed does
   not change this.

Each receiver needs its own directory: a directory whose canonical files
belong to more than one receiver identity is an error, and so are two files
that map to the same canonical name and two files of the same type whose
named time spans overlap (e.g. a daily file next to the 15-minute files of
the same day).
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any

from natsort import natsorted


@dataclass(frozen=True)
class DiscoveredFile:
    """One GNSS data file selected for processing."""

    path: Path
    canonical_name: str


@dataclass(frozen=True)
class ReceiverDay:
    """One receiver's data for one day, the unit a run processes.

    Parameters
    ----------
    receiver : str
        Receiver name in the site configuration.
    directory : Path
        The receiver's configured data directory (any layout below it).
    yyyydoy : str
        Day in ``YYYYDOY`` format.
    recipe : str | None
        Name of the receiver's naming recipe, if configured.
    """

    receiver: str
    directory: Path
    yyyydoy: str
    recipe: str | None = None

    def __str__(self) -> str:
        return f"{self.receiver} {self.yyyydoy} ({self.directory})"


class DiscoveryError(ValueError):
    """A receiver directory's files cannot be assigned unambiguously."""


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


def check_recipe_receivers(receivers: dict[str, dict[str, Any]]) -> None:
    """Check that each receiver's recipe gives it its own canonical identity.

    The canonical name of a file starts with the receiver identity
    (site, receiver type, receiver number, agency, e.g. ``ROSA01TUW``). Two
    receivers whose recipes produce the same identity cannot be told apart
    in the store, and a recipe whose receiver type differs from the
    receiver's configured type would label the files with the wrong role.

    Parameters
    ----------
    receivers : dict[str, dict]
        Receiver name to receiver configuration (``type``, ``recipe``).

    Raises
    ------
    ValueError
        Listing every problem found.
    """
    owner: dict[str, str] = {}
    problems: list[str] = []
    for name, cfg in receivers.items():
        recipe_name = cfg.get("recipe")
        if not recipe_name:
            continue
        recipe = _load_recipe(resolve_recipe_path(recipe_name))
        if recipe.receiver_type != cfg.get("type"):
            problems.append(
                f"Receiver '{name}' is configured as '{cfg.get('type')}', but its "
                f"recipe '{recipe_name}' sets receiver_type '{recipe.receiver_type}'."
            )
        role = "R" if recipe.receiver_type == "reference" else "A"
        identity = f"{recipe.site}{role}{recipe.receiver_number:02d}{recipe.agency}"
        if identity in owner:
            problems.append(
                f"Receivers '{owner[identity]}' and '{name}' both get canonical "
                f"names starting with {identity}. Give each receiver its own "
                f"recipe with a distinct receiver_number."
            )
        else:
            owner[identity] = name
    if problems:
        msg = "Naming recipe problems:\n  - " + "\n  - ".join(problems)
        raise ValueError(msg)


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


def _recipe_file(path: Path, naming_recipe: Any) -> DiscoveredFile | None:
    """``path`` as a discovered file if the recipe recognizes its name."""
    if not fnmatch(path.name, naming_recipe.glob) or not naming_recipe.matches(
        path.name
    ):
        return None
    return DiscoveredFile(
        path=path, canonical_name=naming_recipe.to_virtual_file(path).canonical_str
    )


@lru_cache(maxsize=64)
def _scan_directory(
    directory: Path, recipe: str | None
) -> dict[str, tuple[DiscoveredFile, ...]]:
    """Index a receiver directory: day (``YYYYDOY``) to its files.

    Cached for the run; :func:`clear_discovery_cache` forgets the index so
    a new run sees files added since.
    """
    from canvod.preflight.convention import CanVODFilename, find_overlaps

    naming_recipe = _load_recipe(resolve_recipe_path(recipe)) if recipe else None
    found: list[DiscoveredFile] = []
    if directory.is_dir():
        for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                path = Path(dirpath) / name
                discovered = (
                    _recipe_file(path, naming_recipe)
                    if naming_recipe is not None
                    else _canonical_file(path, _ALL_FILE_TYPES)
                )
                if discovered is not None:
                    found.append(discovered)

    by_name: dict[str, list[Path]] = defaultdict(list)
    for f in found:
        by_name[f.canonical_name].append(f.path)
    duplicates = {n: p for n, p in by_name.items() if len(p) > 1}
    if duplicates:
        lines = [
            f"{name}: " + ", ".join(str(p) for p in natsorted(paths))
            for name, paths in sorted(duplicates.items())[:5]
        ]
        msg = (
            f"In {directory}, several files map to the same canonical name, so "
            f"it is unclear which one to process:\n  - " + "\n  - ".join(lines)
        )
        raise DiscoveryError(msg)

    identities = sorted({f.canonical_name[:9] for f in found})
    if len(identities) > 1:
        msg = (
            f"{directory} contains files of {len(identities)} receivers "
            f"({', '.join(identities)}). Give each receiver its own directory."
        )
        raise DiscoveryError(msg)

    parsed_names = {
        f.canonical_name: CanVODFilename.from_filename(f.canonical_name) for f in found
    }
    overlaps = find_overlaps(found, key=lambda f: parsed_names[f.canonical_name])
    if overlaps:
        lines = [f"{a.path} overlaps {b.path}" for a, b in overlaps[:5]]
        if len(overlaps) > 5:
            lines.append(f"... and {len(overlaps) - 5} more")
        msg = (
            f"In {directory}, {len(overlaps)} pair(s) of files cover the same "
            f"time according to their names, so that data would be read "
            f"twice:\n  - " + "\n  - ".join(lines) + "\nKeep one file of each "
            "pair in the receiver directory, for example either the daily file "
            "or the 15-minute files of a day, not both."
        )
        raise DiscoveryError(msg)

    by_day: dict[str, list[DiscoveredFile]] = defaultdict(list)
    for f in found:
        parsed = parsed_names[f.canonical_name]
        by_day[f"{parsed.year:04d}{parsed.doy:03d}"].append(f)
    return {
        day: tuple(natsorted(files, key=lambda d: str(d.path)))
        for day, files in by_day.items()
    }


def clear_discovery_cache() -> None:
    """Forget the scanned directories, so the next lookup rescans them."""
    _scan_directory.cache_clear()


def _of_format(
    files: tuple[DiscoveredFile, ...], reader_format: str | None, recipe: str | None
) -> list[DiscoveredFile]:
    if recipe:  # the recipe's file_type already selects the files
        return list(files)
    file_types = _READER_FILE_TYPES.get(reader_format, _ALL_FILE_TYPES)
    return [f for f in files if Path(f.canonical_name).suffix[1:] in file_types]


def receiver_days(
    receiver: str,
    directory: Path,
    reader_format: str | None = None,
    recipe: str | None = None,
) -> list[ReceiverDay]:
    """All days for which ``directory`` holds files of the receiver, sorted."""
    index = _scan_directory(Path(directory), recipe)
    return [
        ReceiverDay(receiver, Path(directory), day, recipe)
        for day in sorted(index)
        if _of_format(index[day], reader_format, recipe)
    ]


def discover_files(
    day: ReceiverDay, reader_format: str | None = None
) -> list[DiscoveredFile]:
    """Select the GNSS data files that a run processes for ``day``.

    Parameters
    ----------
    day : ReceiverDay
        Receiver, its directory, the day and its recipe.
    reader_format : str | None
        Receiver reader format (``"rinex3"``, ``"rinex"``, ``"sbf"``, or
        ``None``/``"auto"`` for all recognized types). Ignored with a recipe,
        whose ``file_type`` selects the files.

    Returns
    -------
    list[DiscoveredFile]
        Naturally sorted by physical path.
    """
    index = _scan_directory(Path(day.directory), day.recipe)
    return _of_format(index.get(day.yyyydoy, ()), reader_format, day.recipe)


def detect_reader_format(files: list[DiscoveredFile]) -> str:
    """Reader format for a receiver whose config says ``reader_format: auto``.

    Decided from the canonical names of the discovered files: ``"sbf"`` if
    they are all SBF, otherwise ``"rinex3"``.
    """
    suffixes = {Path(f.canonical_name).suffix for f in files if f.canonical_name}
    if suffixes == {".sbf"}:
        return "sbf"
    return "rinex3"
