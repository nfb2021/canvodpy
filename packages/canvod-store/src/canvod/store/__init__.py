"""canvod-store: Icechunk storage for GNSS VOD data.

This package provides versioned storage for GNSS VOD data using Icechunk.
Manages both RINEX observation storage and VOD analysis results.
"""

from importlib.metadata import version as _version

from canvod.store.manager import GnssResearchSite
from canvod.store.reader import IcechunkDataReader
from canvod.store.store import (
    MyIcechunkStore,
    create_gnss_store,
    create_vod_store,
)
from canvod.store.zarr_concurrency import scoped_zarr_concurrency

__version__ = _version("canvod-store")

__all__ = [
    "GnssResearchSite",
    "IcechunkDataReader",
    "MyIcechunkStore",
    "create_gnss_store",
    "create_vod_store",
    "scoped_zarr_concurrency",
]
