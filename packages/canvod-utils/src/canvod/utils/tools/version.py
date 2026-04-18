"""Version utilities for canVODpy packages."""

import tomllib
from pathlib import Path


def get_version_from_pyproject(pyproject_path: Path | None = None) -> str:
    """
    Get version from pyproject.toml.

    Parameters
    ----------
    pyproject_path : Path, optional
        Path to pyproject.toml. If None, automatically finds it by traversing
        up from the current file location.

    Returns
    -------
    str
        Version string from pyproject.toml.

    Examples
    --------
    >>> version = get_version_from_pyproject()
    >>> print(version)  # e.g., "0.1.0"
    """
    if pyproject_path is None:
        # Automatically find pyproject.toml at package root
        # Start from this file and go up until we find pyproject.toml
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "pyproject.toml"
            if candidate.exists():
                pyproject_path = candidate
                break

        if pyproject_path is None:
            msg = "Could not find pyproject.toml"
            raise FileNotFoundError(msg)

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    return data["project"]["version"]
