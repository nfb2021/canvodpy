"""Utility functions and diagnostics for canvodpy."""

from ._meta import __version__

# Submodules are imported on demand to avoid circular imports
# Use: from canvod.utils.tools import YYYYDOY, get_version_from_pyproject
# Use: from canvod.utils.diagnostics import track_time, track_memory

__all__ = [
    "__version__",
    "diagnostics",
    "tools",
]
