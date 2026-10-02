"""Summarize the data held in a store for its metadata record.

The temporal coverage and the ``summaries`` section describe the store's
contents, so they are recomputed from the store after every write instead of
being fixed when the store is created.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import zarr

from .io import _open_repo

_CONSTELLATIONS = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "I": "NavIC",
    "S": "SBAS",
}

_CF_UNITS = {
    "nanoseconds": "ns",
    "microseconds": "us",
    "milliseconds": "ms",
    "seconds": "s",
    "minutes": "m",
    "hours": "h",
    "days": "D",
}

# Log-book actions whose file is part of the stored data.
_STORED_ACTIONS = {"initial", "written", "appended", "overwritten"}


def _decode_epochs(arr: zarr.Array) -> np.ndarray:
    """Epoch values as ``datetime64[ns]``, decoding CF time units if needed."""
    values = np.asarray(arr[...])
    if np.issubdtype(values.dtype, np.datetime64):
        return values.astype("M8[ns]")
    unit, _, reference = str(arr.attrs["units"]).partition(" since ")
    ref = np.datetime64(reference.strip().replace(" ", "T").split("+")[0], "ns")
    return ref + values.astype("i8").astype(f"m8[{_CF_UNITS[unit.strip()]}]")


def _array(group: zarr.Group, path: str) -> zarr.Array:
    """The array at ``path`` in ``group``."""
    member = group[path]
    if not isinstance(member, zarr.Array):
        msg = f"{path} in {group.path or '/'} is a group, not an array"
        raise TypeError(msg)
    return member


def _iso(t: np.datetime64) -> str:
    return f"{np.datetime_as_string(t, unit='s')}Z"


def _iso_duration(seconds: float) -> str:
    return f"PT{seconds:g}S"


def _data_groups(root: zarr.Group) -> dict[str, zarr.Group]:
    """Groups holding data (an ``epoch`` array), keyed by their path."""
    return {
        name: member
        for name, member in root.members(max_depth=None)
        if isinstance(member, zarr.Group) and "epoch" in member
    }


def _group_summary(group: zarr.Group) -> dict[str, Any]:
    epochs = np.unique(_decode_epochs(_array(group, "epoch")))
    variables = sorted(name for name, arr in group.arrays() if len(arr.shape) >= 2)
    sids = np.asarray(_array(group, "sid")[...]) if "sid" in group else np.array([])
    systems = (
        {str(s) for s in np.asarray(_array(group, "system")[...])}
        if "system" in group
        else set()
    )
    return {
        "epochs": epochs,
        "sids": {str(s) for s in sids},
        "variables": variables,
        "systems": systems,
    }


def _stored_file_count(group: zarr.Group) -> int | None:
    """Distinct stored files in a GNSS group's log book, if it has one."""
    if "metadata/table" not in group:
        return None
    table = group["metadata/table"]
    if (
        not isinstance(table, zarr.Group)
        or "rinex_hash" not in table
        or "action" not in table
    ):
        return None
    hashes = np.asarray(_array(table, "rinex_hash")[...])
    actions = np.asarray(_array(table, "action")[...])
    return len(
        {str(h) for h, a in zip(hashes, actions, strict=True) if a in _STORED_ACTIONS}
    )


def _store_size_mb(store_path: Path) -> float:
    size = sum(f.stat().st_size for f in store_path.rglob("*") if f.is_file())
    return round(size / 1e6, 3)


def summarize_store(
    store_path: Path,
    branch: str = "main",
    receivers: set[str] | None = None,
) -> dict[str, Any]:
    """Metadata updates describing the data currently in a store.

    Parameters
    ----------
    store_path : Path
        Path to the Icechunk store.
    branch : str
        Branch to summarize.
    receivers : set[str] | None
        Receiver names present in ``instruments.receivers``. Each receiver
        with data in the store also gets its per-receiver fields updated,
        from the group named after it and any ``{receiver}_*`` groups.

    Returns
    -------
    dict[str, Any]
        Dotted-key updates for :func:`update_metadata` (or
        :func:`apply_updates`). Empty if the store holds no data yet.
    """
    session = _open_repo(store_path).readonly_session(branch=branch)
    root = zarr.open_group(session.store, mode="r")
    data_groups = _data_groups(root)
    groups = {name: _group_summary(g) for name, g in data_groups.items()}
    if not groups:
        return {}

    epochs = np.unique(np.concatenate([g["epochs"] for g in groups.values()]))
    start, end = _iso(epochs[0]), _iso(epochs[-1])
    steps = np.diff(epochs).astype("m8[ns]").astype("i8") / 1e9
    resolution = float(np.median(steps)) if steps.size else None
    systems = set().union(*(g["systems"] for g in groups.values()))
    file_counts = [
        n
        for n in (_stored_file_count(g) for g in data_groups.values())
        if n is not None
    ]

    updates: dict[str, Any] = {
        "temporal.collected_start": start,
        "temporal.collected_end": end,
        "temporal.time_coverage_start": start,
        "temporal.time_coverage_end": end,
        "temporal.time_coverage_duration": _iso_duration(
            (epochs[-1] - epochs[0]) / np.timedelta64(1, "s")
        ),
        "temporal.time_coverage_resolution": (
            _iso_duration(resolution) if resolution is not None else None
        ),
        "spatial.extent_temporal_interval": [[start, end]],
        "summaries.total_epochs": int(epochs.size),
        "summaries.total_sids": len(set().union(*(g["sids"] for g in groups.values()))),
        "summaries.constellations": sorted(_CONSTELLATIONS.get(s, s) for s in systems),
        "summaries.variables": sorted(
            set().union(*(g["variables"] for g in groups.values()))
        ),
        "summaries.temporal_resolution_s": resolution,
        "summaries.file_count": sum(file_counts) if file_counts else None,
        "summaries.store_size_mb": _store_size_mb(store_path),
    }
    for receiver in sorted(receivers or ()):
        # A reference receiver is stored once per canopy it is paired with
        # (e.g. ``reference_01_canopy_01``); combine all of its groups.
        own = [
            g
            for name, g in groups.items()
            if name == receiver or name.startswith(f"{receiver}_")
        ]
        if not own:
            continue
        r_epochs = np.unique(np.concatenate([g["epochs"] for g in own]))
        prefix = f"instruments.receivers.{receiver}"
        updates[f"{prefix}.epochs"] = int(r_epochs.size)
        updates[f"{prefix}.sids"] = len(set().union(*(g["sids"] for g in own)))
        updates[f"{prefix}.variables"] = sorted(
            set().union(*(g["variables"] for g in own))
        )
        updates[f"{prefix}.temporal_range"] = [_iso(r_epochs[0]), _iso(r_epochs[-1])]
    return updates
