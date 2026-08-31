"""Filesystem junk-file sanitization for canVODpy."""

from collections.abc import Sequence
from pathlib import Path

DEFAULT_JUNK_FILENAMES: tuple[str, ...] = (".DS_Store",)


def sanitize_directory(
    root: Path,
    junk_filenames: Sequence[str] = DEFAULT_JUNK_FILENAMES,
) -> list[Path]:
    """Remove OS-dropped junk files (e.g. ``.DS_Store``) from a directory tree.

    macOS (Finder/Spotlight) writes ``.DS_Store`` into any directory it has
    browsed, including mounted/shared volumes. Zarr's group listing and
    Icechunk's ref listing both treat these as unrecognized/invalid store
    members -- producing warnings (plain Zarr) or hard errors ("invalid ref
    type `.DS_Store`", Icechunk). Call this on a directory-backed store
    before opening it for listing, whenever it may have been exposed to
    Finder since the last sweep.

    Parameters
    ----------
    root : Path
        Directory tree to sweep. No-op if it doesn't exist.
    junk_filenames : Sequence[str], default (".DS_Store",)
        Filenames to remove, matched anywhere in the tree.

    Returns
    -------
    list[Path]
        Paths that were removed (empty if none found or ``root`` doesn't
        exist).
    """
    if not root.exists():
        return []
    removed: list[Path] = []
    for name in junk_filenames:
        for junk_path in root.rglob(name):
            try:
                junk_path.unlink()
            except FileNotFoundError:
                # A concurrent sweep (e.g. another loky worker sanitizing
                # the same shared cache_root) already removed it -- the
                # desired end state (no junk file) already holds.
                continue
            removed.append(junk_path)
    return removed
