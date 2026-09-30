"""GNSS data-file discovery shared by the pipeline run and its dry-run preview.

One code path decides which files in a receiver's per-day directory are
processed, so ``canvodpy run --dry-run`` reports exactly the files a real run
would ingest.

Discovery order per receiver:

1. **Recipe** -- when the receiver config sets ``recipe:``, the naming recipe
   (``canvod-filemap``) selects the files and maps each to its canonical
   canVOD name.
2. **Filename patterns** -- otherwise, ``canvod-filemap``'s built-in source
   patterns when that optional package is installed.
3. **Canonical convention** -- otherwise, canonical canVOD names only
   (``*.rnx``/``*.sbf``, restricted by ``reader_format``).

Canonical names for (2) and (3) come from parsing the physical filename
against the canVOD naming convention (``canvod-preflight``); a filename that
does not follow the convention gets an empty canonical name.
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


def _pattern_globs(reader_format: str | None) -> set[str]:
    """Glob patterns for non-recipe discovery (see module docstring, 2 and 3)."""
    try:
        from canvod.filemap.patterns import BUILTIN_PATTERNS, auto_match_order
    except ImportError:
        if reader_format == "sbf":
            return {"*.sbf", "*.SBF"}
        if reader_format in ("rinex3", "rinex"):
            return {"*.rnx", "*.RNX"}
        return {"*.rnx", "*.RNX", "*.sbf", "*.SBF"}

    if reader_format == "sbf":
        globs = set(BUILTIN_PATTERNS["septentrio_sbf"].file_globs)
        globs.update(g for g in BUILTIN_PATTERNS["canvod"].file_globs if ".sbf" in g)
        return globs
    names = auto_match_order()
    if reader_format in ("rinex3", "rinex"):
        names = tuple(n for n in names if n != "septentrio_sbf")
    globs = set()
    for name in names:
        globs.update(BUILTIN_PATTERNS[name].file_globs)
    return globs


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

    seen: set[Path] = set()
    found = []
    for g in sorted(_pattern_globs(reader_format)):
        for path in data_dir.glob(g):
            if path.is_file() and path not in seen:
                seen.add(path)
                found.append(
                    DiscoveredFile(path=path, canonical_name=canonical_name_for(path))
                )
    return natsorted(found, key=lambda d: str(d.path))


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
