"""
Software metadata for canvodpy.

This module contains software identification and version information
that gets written to processed files. These values should not be
modified by users.
"""

from importlib.metadata import version as _version

__version__ = _version("canvod-utils")

SOFTWARE_NAME = "canvodpy"
SOFTWARE_URL = "https://github.com/climers-tuwien/canvodpy"
SOFTWARE_FULL = f"{SOFTWARE_NAME} v{__version__}"

# This will be written to output files
SOFTWARE_ATTRS: dict[str, str] = {
    "software": SOFTWARE_FULL,
    "software_url": SOFTWARE_URL,
    "version": __version__,
}
