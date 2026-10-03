"""Apply the configured operations to consecutive files of one receiver."""

from __future__ import annotations

from collections.abc import Sequence
from functools import reduce

import numpy as np
import structlog
import xarray as xr

from canvod.config.models import (
    PREPROCESSING_ATTR,
    PreprocessingConfig,
    preprocessing_record,
)
from canvod.ops.registry import build_default_pipeline

logger = structlog.get_logger(__name__)


def preprocess_files[K](
    parts: Sequence[tuple[K, xr.Dataset]],
    config: PreprocessingConfig | None,
) -> list[tuple[K, xr.Dataset]]:
    """Apply ``processing.preprocessing`` to the files of one receiver and day.

    The files are joined along ``epoch`` before the operations run, so a time
    bin that spans two files is aggregated from the observations of both.
    The result is split back into one dataset per file: each bin goes to the
    file that holds its earliest observation. Every dataset keeps its own
    attributes (e.g. the file hash) and records the applied operations in
    the ``Preprocessing`` attribute, also when none are set.

    Parameters
    ----------
    parts : Sequence[tuple[K, xr.Dataset]]
        ``(key, dataset)`` per file, e.g. ``(path, dataset)``; datasets have
        ``(epoch, sid)`` dimensions.
    config : PreprocessingConfig | None
        The ``processing.preprocessing`` section; ``None`` applies nothing.

    Returns
    -------
    list[tuple[K, xr.Dataset]]
        ``(key, dataset)`` per file, in time order. A file whose observations
        all fall into bins of an earlier file is left out.
    """
    record = preprocessing_record(config)
    pipeline = build_default_pipeline(config) if config is not None else None
    if pipeline is None or len(pipeline) == 0:
        return [
            (key, ds.assign_attrs({PREPROCESSING_ATTR: record})) for key, ds in parts
        ]

    ordered = sorted(
        (p for p in parts if p[1].sizes.get("epoch", 0) > 0),
        key=lambda p: p[1]["epoch"].values.min(),
    )
    if not ordered:
        return []

    datasets = [ds for _, ds in ordered]
    sid_only = sorted(
        {
            str(c)
            for ds in datasets
            for c, v in ds.coords.items()
            if c != "sid" and v.dims == ("sid",)
        }
    )
    # Files of one receiver may observe different signals: take each signal's
    # sid-only coordinates (band, frequency, ...) from any file that has it.
    sid_coords = reduce(
        lambda a, b: a.combine_first(b),
        [
            xr.Dataset({c: ds.coords[c] for c in sid_only if c in ds.coords})
            for ds in datasets
        ],
    )
    joined = xr.concat(
        [ds.drop_vars(sid_only, errors="ignore") for ds in datasets],
        dim="epoch",
        join="outer",
        coords="minimal",
        compat="override",
        combine_attrs="drop",
    )
    joined = joined.assign_coords(
        {c: sid_coords[c].reindex(sid=joined["sid"]) for c in sid_coords.data_vars}
    )
    source = np.concatenate(
        [np.full(ds.sizes["epoch"], i) for i, ds in enumerate(datasets)]
    )
    epochs = joined["epoch"].values

    out, result = pipeline(joined)
    pipeline_attrs = result.to_metadata_dict()

    # Owner of each output epoch (a bin start): the file with the earliest
    # observation at or after that bin start, i.e. the bin's first observation.
    order = np.argsort(epochs, kind="stable")
    first = np.searchsorted(epochs[order], out["epoch"].values, side="left")
    owner = source[order][first]

    split: list[tuple[K, xr.Dataset]] = []
    for i, (key, ds) in enumerate(ordered):
        part = out.isel(epoch=np.flatnonzero(owner == i))
        if part.sizes["epoch"] == 0:
            logger.warning(
                "preprocessing_file_absorbed",
                file=str(key),
                hint="all observations fall into time bins of an earlier file",
            )
            continue
        attrs = dict(ds.attrs)
        attrs.update(pipeline_attrs)
        attrs[PREPROCESSING_ATTR] = record
        split.append((key, part.assign_attrs(attrs)))
    return split
