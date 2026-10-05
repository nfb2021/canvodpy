"""The last step before every write of a dataset into a store group."""

from __future__ import annotations

from typing import Any

import xarray as xr
from canvod.config.models import split_preprocessing

from canvod.store.time_encoding import prepare_times


def prepare_write(ds: xr.Dataset, store: Any, group: str) -> xr.Dataset:
    """Return ``ds`` as it is written into ``group``.

    Drops the in-memory preprocessing record (it goes into the log book, see
    ``canvod.config.models.PREPROCESSING_ATTR``), so stored data have the
    signature of data without preprocessing, and checks and sets the time
    encoding (:func:`~canvod.store.time_encoding.prepare_times`). Call it
    right before every write into a store group.
    """
    attrs, _ = split_preprocessing(ds.attrs)
    ds = ds.copy(deep=False)
    ds.attrs = attrs
    return prepare_times(ds, store, group)
