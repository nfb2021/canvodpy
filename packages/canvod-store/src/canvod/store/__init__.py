"""canvod-store: Icechunk storage for GNSS VOD data.

This package provides versioned storage for GNSS VOD data using Icechunk.
Manages both RINEX observation storage and VOD analysis results.
"""

from canvod.store.manager import GnssResearchSite
from canvod.store.reader import IcechunkDataReader
from canvod.store.store import (
    MyIcechunkStore,
    create_rinex_store,
    create_vod_store,
)
from canvod.store.zarr_concurrency import scoped_zarr_concurrency

__version__ = "0.1.0"

__all__ = [
    "GnssResearchSite",
    "IcechunkDataReader",
    "MyIcechunkStore",
    "create_rinex_store",
    "create_vod_store",
    "scoped_zarr_concurrency",
]
