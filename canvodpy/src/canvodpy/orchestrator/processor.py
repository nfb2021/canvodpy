"""RINEX processing orchestration and Icechunk writing helpers."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Generator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime
from datetime import time as dt_time
from pathlib import Path

import numpy as np
import polars as pl
import pydantic_core
import xarray as xr
import zarr
import zarr.errors
from icechunk.session import ForkSession
from icechunk.xarray import to_icechunk
from natsort import natsorted
from pydantic import ValidationError
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from canvod.auxiliary.cache_fingerprint import (
    CANONICAL_AUX_GRID_SECONDS,
    compute_aux_cache_fingerprint,
)
from canvod.auxiliary.pipeline import AuxDataPipeline
from canvod.auxiliary.position import (
    ECEFPosition,
    add_spherical_coords_to_dataset,
    compute_spherical_coordinates,
)
from canvod.config import load_config
from canvod.readers import DataDirMatcher, MatchedDirs
from canvod.store import GnssResearchSite, scoped_zarr_concurrency
from canvod.utils.tools import (
    _worker_init,
    get_version_from_pyproject,
    sanitize_directory,
)
from canvodpy.logging import get_logger, stage_timer
from canvodpy.logging.run_context import get_run_id, set_run_id
from canvodpy.orchestrator.interpolator import (
    ClockConfig,
    ClockInterpolationStrategy,
    Sp3Config,
    Sp3InterpolationStrategy,
)

# ============================================================================
# MODULE-LEVEL FUNCTIONS (Required for loky / ProcessPoolExecutor serialization)
# ============================================================================


def _worker_init_with_run_id(
    nice: int, affinity: list[int] | None, run_id: str | None
) -> None:
    """Initialize a worker process, then bind the current run_id.

    Wraps ``canvod.utils.tools``'s ``_worker_init`` (which must stay free of
    any canvodpy dependency) rather than modifying it directly. Contextvars
    don't cross process boundaries, so a worker started under a
    ``ProcessPoolExecutor``/loky pool needs ``run_id`` set explicitly at
    startup for its log records to be correlated with the run that spawned
    it -- see ``logging/run_context.py``.
    """
    _worker_init(nice, affinity)
    if run_id is not None:
        set_run_id(run_id)


def _processing_progress(disable: bool = False) -> Progress:
    """Create a Rich progress bar for RINEX processing tasks."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("eta"),
        TimeRemainingColumn(),
        disable=disable,
    )


def preprocess_with_hermite_aux(
    rnx_file: Path,
    keep_vars: list[str] | None,
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
    use_sbf_geometry: bool = False,
    store_radial_distance: bool = False,
    store_sbf_raw_observables: bool = True,
    broadcast_canopy_file: Path | None = None,
    broadcast_canopy_fmt: str | None = None,
    pad_global_sid: bool = True,
    aux_group: str | None = None,
) -> tuple[Path, xr.Dataset, dict[str, xr.Dataset], dict[str, list[str]]]:
    """Read RINEX and compute coordinates using Hermite-interpolated aux data from Zarr.

    This function runs in separate processes, so it must be at module level.
    The aux data has already been interpolated using proper Hermite splines.

    Parameters
    ----------
    rnx_file : Path
        RINEX file path
    keep_vars : List[str]
        Variables to keep
    aux_zarr_path : Path
        Path to preprocessed aux data Zarr store (with Hermite interpolation)
    receiver_position : ECEFPosition
        Receiver position (computed once)
    receiver_type : str
        Receiver type
    keep_sids : list[str] | None, default None
        List of specific SIDs to keep. If None, keeps all possible SIDs.
    use_sbf_geometry : bool, default False
        If True and reader_name is "sbf", skip external orbit/clock downloads
        and transfer theta/phi directly from SBF SatVisibility blocks.
    store_radial_distance : bool, default False
        If True, keep the radial distance variable ``r`` in the output.
    broadcast_canopy_file : Path | None, default None
        Path to the matching canopy SBF file. When provided (for reference
        receivers in shared position mode), its sbf_obs theta/phi override
        the reference file's own geometry.
    broadcast_canopy_fmt : str | None, default None
        Reader format for the canopy file (e.g. "sbf").
    aux_group : str | None, default None
        Zarr group within ``aux_zarr_path`` to read this day's aux data
        from (§44 shared-cache mode). ``None`` reads the store root,
        matching legacy per-site aux Zarr layout.

    Returns
    -------
    tuple[Path, xr.Dataset, dict[str, xr.Dataset], dict[str, list[str]]]
        File path, augmented dataset with phi/theta/r, auxiliary datasets dict,
        and SID issue dict with keys ``not_in_global_space``, ``dropped_by_filter``,
        ``dropped_no_ephemeris``.

    """
    import re

    log = get_logger(__name__).bind(
        file=str(rnx_file.name), receiver_type=receiver_type
    )

    with stage_timer(
        "rinex.process_file", file=str(rnx_file.name), receiver=receiver_type
    ):
        try:
            t0 = time.perf_counter()
            log.info("rinex_preprocessing_started")

            # 1. Read GNSS file (reader selected via factory)
            log.debug("reading_gnss_file", file=str(rnx_file.name), reader=reader_name)
            from canvodpy.factories import ReaderFactory

            rnx = ReaderFactory.create(reader_name, fpath=rnx_file)
            ds, aux_datasets = rnx.to_ds_and_auxiliary(
                keep_data_vars=keep_vars,
                write_global_attrs=True,
                keep_sids=keep_sids,
                store_raw_observables=store_sbf_raw_observables,
                pad_global_sid=pad_global_sid,
            )
            ds.attrs["File Hash"] = rnx.file_hash
            t_rinex = time.perf_counter()

            # SBF-geometry fast path: use receiver-reported theta/phi, skip ephemeris
            if reader_name == "sbf" and use_sbf_geometry:
                # Use canopy file's sbf_obs when provided (reference receiver
                # in shared position mode), else this file's own sbf_obs
                if broadcast_canopy_file is not None:
                    from canvodpy.factories import ReaderFactory

                    canopy_rnx = ReaderFactory.create(
                        broadcast_canopy_fmt or "sbf", fpath=broadcast_canopy_file
                    )
                    _, canopy_aux = canopy_rnx.to_ds_and_auxiliary(
                        keep_data_vars=None,
                        write_global_attrs=False,
                        keep_sids=keep_sids,
                    )
                    meta_ds = canopy_aux.get("sbf_obs")
                else:
                    meta_ds = aux_datasets.get("sbf_obs")
                if (
                    meta_ds is not None
                    and "broadcast_theta" in meta_ds
                    and "broadcast_phi" in meta_ds
                ):
                    # Extract broadcast geometry (already in radians from reader)
                    bt = meta_ds["broadcast_theta"]
                    bp = meta_ds["broadcast_phi"]

                    # Align to obs epoch space
                    if "epoch" in bt.dims:
                        common_epochs = np.intersect1d(ds.epoch.values, bt.epoch.values)
                        bt = bt.sel(epoch=common_epochs).reindex(
                            epoch=ds.epoch.values, fill_value=np.nan
                        )
                        bp = bp.sel(epoch=common_epochs).reindex(
                            epoch=ds.epoch.values, fill_value=np.nan
                        )

                    # Align to obs SID space
                    common_sids = sorted(set(ds.sid.values) & set(bt.sid.values))
                    bt = bt.sel(sid=common_sids).reindex(
                        sid=ds.sid.values, fill_value=np.nan
                    )
                    bp = bp.sel(sid=common_sids).reindex(
                        sid=ds.sid.values, fill_value=np.nan
                    )

                    from canvod.auxiliary.position.spherical_coords import (
                        add_broadcast_spherical_coords_to_dataset,
                    )

                    # .values prevents epoch-level coord leakage (pdop, hdop, …)
                    ds = add_broadcast_spherical_coords_to_dataset(
                        ds, bt.values, bp.values
                    )
                from canvod.auxiliary.preprocessing import flush_sid_accumulators

                sid_issues = flush_sid_accumulators()
                sid_issues["dropped_no_ephemeris"] = []
                return rnx_file, ds, aux_datasets, sid_issues
            log.debug(
                "rinex_loaded",
                dims=dict(ds.sizes),
                data_vars=list(ds.data_vars.keys()),
                coords=list(ds.coords.keys()),
                epochs=len(ds.epoch),
                sids=len(ds.sid),
            )

            # Filter variables
            if keep_vars:
                available_vars = [var for var in keep_vars if var in ds.data_vars]
                if available_vars:
                    ds = ds[available_vars]

            # 2. Open preprocessed aux data and select matching epochs
            aux_store = xr.open_zarr(
                aux_zarr_path,
                group=aux_group,
                decode_timedelta=True,
                consolidated=False,
            )
            aux_slice = aux_store.sel(epoch=ds.epoch, method="nearest")

            # Eagerly load aux slice — batches all Zarr reads (X, Y, Z, clock)
            # in one pass instead of 3-4 separate lazy loads later
            aux_slice = aux_slice.load()
            t_aux = time.perf_counter()

            # 3. Find common SIDs between RINEX and aux data (inner join)
            rinex_sids = set(ds.sid.values)
            aux_sids = set(aux_slice.sid.values)
            common_sids = sorted(rinex_sids.intersection(aux_sids))

            if not common_sids:
                log.error(
                    "sid_intersection_empty",
                    rinex_sids=len(rinex_sids),
                    aux_sids=len(aux_sids),
                )
                raise ValueError(
                    f"No common SIDs found between RINEX ({len(rinex_sids)} sids) "
                    f"and aux data ({len(aux_sids)} sids)"
                )

            # Filter both datasets to common SIDs
            rinex_only = rinex_sids - aux_sids
            aux_only = aux_sids - rinex_sids
            ds = ds.sel(sid=common_sids)
            aux_slice = aux_slice.sel(sid=common_sids)
            t_sid = time.perf_counter()

            log.debug(
                "sid_filtering_complete",
                rinex_sids=len(rinex_sids),
                aux_sids=len(aux_sids),
                common_sids=len(common_sids),
                rinex_only=len(rinex_only),
                aux_only=len(aux_only),
            )
            if rinex_only:
                log.warning(
                    "sids_dropped_no_ephemeris",
                    file=str(rnx_file.name),
                    count=len(rinex_only),
                    sids=sorted(rinex_only),
                    hint=(
                        "These SIDs were observed in the file but have no matching "
                        "entry in the ephemeris/clock aux data and will be absent "
                        "from the stored dataset."
                    ),
                )

            # 4. Compute spherical coordinates (phi, theta, r) from ephemerides
            log.debug("computing_spherical_coordinates")
            ds_augmented = _compute_spherical_coords_fast(
                ds,
                aux_slice,
                receiver_position,
            )
            if not store_radial_distance and "r" in ds_augmented:
                ds_augmented = ds_augmented.drop_vars("r")
            t_coords = time.perf_counter()

            log.info(
                "rinex_preprocessing_complete",
                total_seconds=round(t_coords - t0, 2),
                rinex_read_seconds=round(t_rinex - t0, 2),
                aux_load_seconds=round(t_aux - t_rinex, 2),
                sid_filter_seconds=round(t_sid - t_aux, 4),
                coords_seconds=round(t_coords - t_sid, 2),
                dataset_size=dict(ds_augmented.sizes),
            )

            # Additive stage_timing for the performance dashboard's
            # per-iteration breakdown (reading/validating/augmenting/
            # writing) -- reuses the checkpoints already computed above
            # rather than restructuring this function into nested
            # stage_timer() context managers.
            _date_key_match = re.search(r"_R_(\d{7})\d{4}_", rnx_file.name)
            _date_key = _date_key_match.group(1) if _date_key_match else None
            _stage_ctx = {"receiver": receiver_type, "date_key": _date_key}
            log.info(
                "stage_timing",
                stage="reading",
                duration_seconds=round(t_rinex - t0, 2),
                status="ok",
                **_stage_ctx,
            )
            log.info(
                "stage_timing",
                stage="validating",
                duration_seconds=round(t_sid - t_aux, 4),
                status="ok",
                **_stage_ctx,
            )
            log.info(
                "stage_timing",
                stage="augmenting",
                duration_seconds=round((t_aux - t_rinex) + (t_coords - t_sid), 2),
                status="ok",
                **_stage_ctx,
            )
        except (OSError, RuntimeError, ValueError, ValidationError) as e:
            log.error(
                "rinex_preprocessing_failed",
                error=str(e),
                exception=type(e).__name__,
                file=str(rnx_file.name),
                traceback_available=True,
            )
            raise

    from canvod.auxiliary.preprocessing import flush_sid_accumulators

    sid_issues = flush_sid_accumulators()
    sid_issues["dropped_no_ephemeris"] = sorted(rinex_only)
    return rnx_file, ds_augmented, aux_datasets, sid_issues


def preprocess_reference_with_hermite_aux_fanout(
    rnx_file: Path,
    keep_vars: list[str] | None,
    aux_zarr_path: Path,
    canopy_positions: dict[str, ECEFPosition],
    receiver_type: str,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
    store_radial_distance: bool = False,
    store_sbf_raw_observables: bool = True,
    pad_global_sid: bool = True,
    aux_group: str | None = None,
) -> tuple[Path, dict[str, xr.Dataset], dict[str, xr.Dataset], dict[str, list[str]]]:
    """Read a shared reference file once, then compute geometry per canopy pairing.

    A reference receiver paired with N canopies gets read, SID-filtered, and
    ephemeris-joined identically for every pairing -- only the geometry step
    (``_compute_spherical_coords_fast``, which substitutes in the paired
    canopy's position) actually differs per pairing. Doing steps 1-3 once
    here, inside a single worker call, avoids re-parsing the same file N
    times (dev/todo_later.md §47) without serializing the parsed
    intermediate across a process-pool boundary.

    This intentionally omits the ``use_sbf_geometry``/broadcast-canopy fast
    path from ``preprocess_with_hermite_aux`` -- confirmed out of scope,
    no live deployment pairs ``use_sbf_geometry=True`` with shared position
    mode.

    Parameters
    ----------
    canopy_positions : dict[str, ECEFPosition]
        ``{pairing_name: canopy_receiver_position}`` for every canopy this
        reference file is paired against (e.g. ``{"reference_01_canopy_01":
        ECEFPosition(...), "reference_01_canopy_02": ECEFPosition(...)}``).
    aux_group : str | None, default None
        Zarr group within ``aux_zarr_path`` to read this day's aux data
        from (§44 shared-cache mode). ``None`` reads the store root.

    Returns
    -------
    tuple[Path, dict[str, xr.Dataset], dict[str, xr.Dataset], dict[str, list[str]]]
        File path, ``{pairing_name: ds_augmented}`` for every pairing in
        ``canopy_positions``, auxiliary datasets dict, and SID issue dict.

    """
    import re

    log = get_logger(__name__).bind(
        file=str(rnx_file.name), receiver_type=receiver_type
    )

    with stage_timer(
        "rinex.process_file", file=str(rnx_file.name), receiver=receiver_type
    ):
        try:
            t0 = time.perf_counter()
            log.info("rinex_preprocessing_started", pairings=len(canopy_positions))

            # 1. Read GNSS file (reader selected via factory)
            from canvodpy.factories import ReaderFactory

            rnx = ReaderFactory.create(reader_name, fpath=rnx_file)
            ds, aux_datasets = rnx.to_ds_and_auxiliary(
                keep_data_vars=keep_vars,
                write_global_attrs=True,
                keep_sids=keep_sids,
                store_raw_observables=store_sbf_raw_observables,
                pad_global_sid=pad_global_sid,
            )
            ds.attrs["File Hash"] = rnx.file_hash
            t_rinex = time.perf_counter()

            if keep_vars:
                available_vars = [var for var in keep_vars if var in ds.data_vars]
                if available_vars:
                    ds = ds[available_vars]

            # 2. Open preprocessed aux data and select matching epochs
            aux_store = xr.open_zarr(
                aux_zarr_path,
                group=aux_group,
                decode_timedelta=True,
                consolidated=False,
            )
            aux_slice = aux_store.sel(epoch=ds.epoch, method="nearest")
            aux_slice = aux_slice.load()
            t_aux = time.perf_counter()

            # 3. Find common SIDs between RINEX and aux data (inner join)
            rinex_sids = set(ds.sid.values)
            aux_sids = set(aux_slice.sid.values)
            common_sids = sorted(rinex_sids.intersection(aux_sids))

            if not common_sids:
                log.error(
                    "sid_intersection_empty",
                    rinex_sids=len(rinex_sids),
                    aux_sids=len(aux_sids),
                )
                raise ValueError(
                    f"No common SIDs found between RINEX ({len(rinex_sids)} sids) "
                    f"and aux data ({len(aux_sids)} sids)"
                )

            rinex_only = rinex_sids - aux_sids
            aux_only = aux_sids - rinex_sids
            ds = ds.sel(sid=common_sids)
            aux_slice = aux_slice.sel(sid=common_sids)
            t_sid = time.perf_counter()

            log.debug(
                "sid_filtering_complete",
                rinex_sids=len(rinex_sids),
                aux_sids=len(aux_sids),
                common_sids=len(common_sids),
                rinex_only=len(rinex_only),
                aux_only=len(aux_only),
            )
            if rinex_only:
                log.warning(
                    "sids_dropped_no_ephemeris",
                    file=str(rnx_file.name),
                    count=len(rinex_only),
                    sids=sorted(rinex_only),
                    hint=(
                        "These SIDs were observed in the file but have no matching "
                        "entry in the ephemeris/clock aux data and will be absent "
                        "from the stored dataset."
                    ),
                )

            # 4. Compute spherical coordinates (phi, theta, r) once per
            # pairing -- the only step that depends on which canopy's
            # position is substituted in.
            ds_augmented_by_pairing: dict[str, xr.Dataset] = {}
            for pairing_name, receiver_position in canopy_positions.items():
                ds_augmented = _compute_spherical_coords_fast(
                    ds,
                    aux_slice,
                    receiver_position,
                )
                if not store_radial_distance and "r" in ds_augmented:
                    ds_augmented = ds_augmented.drop_vars("r")
                ds_augmented_by_pairing[pairing_name] = ds_augmented
            t_coords = time.perf_counter()

            log.info(
                "rinex_preprocessing_complete",
                total_seconds=round(t_coords - t0, 2),
                rinex_read_seconds=round(t_rinex - t0, 2),
                aux_load_seconds=round(t_aux - t_rinex, 2),
                sid_filter_seconds=round(t_sid - t_aux, 4),
                coords_seconds=round(t_coords - t_sid, 2),
                pairings=len(canopy_positions),
            )

            _date_key_match = re.search(r"_R_(\d{7})\d{4}_", rnx_file.name)
            _date_key = _date_key_match.group(1) if _date_key_match else None
            _stage_ctx = {"receiver": receiver_type, "date_key": _date_key}
            log.info(
                "stage_timing",
                stage="reading",
                duration_seconds=round(t_rinex - t0, 2),
                status="ok",
                **_stage_ctx,
            )
            log.info(
                "stage_timing",
                stage="validating",
                duration_seconds=round(t_sid - t_aux, 4),
                status="ok",
                **_stage_ctx,
            )
            log.info(
                "stage_timing",
                stage="augmenting",
                duration_seconds=round((t_aux - t_rinex) + (t_coords - t_sid), 2),
                status="ok",
                **_stage_ctx,
            )
        except (OSError, RuntimeError, ValueError, ValidationError) as e:
            log.error(
                "rinex_preprocessing_failed",
                error=str(e),
                exception=type(e).__name__,
                file=str(rnx_file.name),
                traceback_available=True,
            )
            raise

    from canvod.auxiliary.preprocessing import flush_sid_accumulators

    sid_issues = flush_sid_accumulators()
    sid_issues["dropped_no_ephemeris"] = sorted(rinex_only)
    return rnx_file, ds_augmented_by_pairing, aux_datasets, sid_issues


def _compute_spherical_coords_fast(
    rinex_ds: xr.Dataset,
    aux_ds: xr.Dataset,
    rx_pos: ECEFPosition,
) -> xr.Dataset:
    """Compute spherical coordinates using shared utility function.

    This function is used by the parallel processor and must remain
    at module level for loky / ProcessPoolExecutor serialization.
    """
    # Get satellite positions (already interpolated with Hermite splines)
    sat_x = aux_ds["X"].values
    sat_y = aux_ds["Y"].values
    sat_z = aux_ds["Z"].values

    # Compute using shared function
    r, theta, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, rx_pos)

    # Add to dataset using shared function
    rinex_ds = add_spherical_coords_to_dataset(rinex_ds, r, theta, phi)

    # Optionally add clock corrections if available
    if "clock" in aux_ds.data_vars:
        rinex_ds = rinex_ds.assign({"clock": aux_ds["clock"]})

    return rinex_ds


# ============================================================================
# Coordinated Parallel Writing to Icechunk
# ============================================================================


def _sanitize_ds_for_write(ds: xr.Dataset) -> xr.Dataset:
    # Make a shallow copy and strip obviously non-serializable attrs
    ds = ds.copy()
    # Keep only simple types in .attrs
    clean_attrs = {}
    for k, v in list(ds.attrs.items()):
        if isinstance(v, (str, int, float, bool, type(None), np.generic)):
            clean_attrs[k] = v
        # allow numpy scalars
        elif isinstance(v, (np.integer, np.floating, np.bool_)):
            clean_attrs[k] = v.item()
        # else drop it silently
    ds.attrs = clean_attrs

    # Normalize encodings to be conservative (avoid dtype surprises)
    for vname in ds.data_vars:
        var = ds[vname]
        enc = var.encoding or {}
        # ensure dtype is a concrete numpy dtype if present
        if "dtype" in enc:
            enc["dtype"] = np.dtype(var.dtype)
        # drop object encodings we don't control
        for bad in ("compressor", "filters", "chunks", "preferred_chunks"):
            enc.pop(bad, None)
        var.encoding = enc
    return ds


def write_initial_rinex_ds_to_store(
    *,
    ds: xr.Dataset,
    fork: ForkSession,
    group: str,
) -> ForkSession:
    """Write a new receiver group to the store."""
    ds = _sanitize_ds_for_write(ds)
    ds.to_zarr(
        fork.store,
        group=group,
        consolidated=False,
        mode="w",  # create group
    )
    return fork


def append_rinex_ds_to_store(
    *,
    ds: xr.Dataset,
    fork: ForkSession,
    group: str,
) -> ForkSession:
    """Append to an existing receiver group in the store."""
    ds = _sanitize_ds_for_write(ds)
    ds.to_zarr(
        fork.store,
        region="auto",
        group=group,
        consolidated=False,
        mode="a",
    )
    return fork


def worker_task(
    rinex_file: Path,
    keep_vars: list[str],
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    receiver_name: str,
    fork: ForkSession,
    is_first: bool,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
) -> tuple[Path, ForkSession]:
    """Build an augmented dataset and write it to the given fork."""
    # 1) build augmented dataset
    fname, ds_augmented, _aux, _sids = preprocess_with_hermite_aux(
        rinex_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_type,
        keep_sids,
        reader_name,
    )

    # 2) write to this fork (initial or append)
    if is_first:
        write_initial_rinex_ds_to_store(
            ds=ds_augmented,
            fork=fork,
            group=receiver_name,
        )
    else:
        append_rinex_ds_to_store(
            ds=ds_augmented,
            fork=fork,
            group=receiver_name,
        )

    # 3) return ONLY pickleable things (Path + ForkSession)
    return fname, fork


def worker_task_append_only(
    rinex_file: Path,
    keep_vars: list[str],
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    receiver_name: str,
    fork: ForkSession,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
) -> tuple[Path, ForkSession]:
    """Worker that only appends (group already exists)."""
    fname, ds_augmented, _aux, _sids = preprocess_with_hermite_aux(
        rinex_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_type,
        keep_sids,
        reader_name,
    )

    ds_clean = _sanitize_ds_for_write(ds_augmented)
    ds_clean.to_zarr(
        fork.store,
        group=receiver_name,
        mode="a",
        append_dim="epoch",
        consolidated=False,
    )

    return fname, fork


def worker_task_with_region_auto(
    rinex_file: Path,
    keep_vars: list[str],
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    receiver_name: str,
    fork: ForkSession,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
    store_sbf_raw_observables: bool = True,
) -> ForkSession:
    """Worker uses region='auto' to write to correct position."""
    _fname, ds, _aux, _sids = preprocess_with_hermite_aux(
        rinex_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_type,
        keep_sids,
        reader_name,
        store_sbf_raw_observables=store_sbf_raw_observables,
    )

    ds_clean = _sanitize_ds_for_write(ds)
    ds_clean.to_zarr(
        fork.store,
        group=receiver_name,
        mode="a",
        region="auto",  # ✅ Let xarray infer the region
        consolidated=False,
    )

    return fork  # Return the modified fork


# ============================================================================
# MAIN (HALF-PARALLEL) PROCESSOR CLASS
# ============================================================================


class RinexDataProcessor:
    """Orchestrates RINEX data processing with optimized parallelization.

    Pipeline:
    1. Initialize auxiliary data (ephemerides, clock) - ONCE
    2. Preprocess aux data with Hermite splines to disk - ONCE per day
    3. Parallel process RINEX files via ProcessPoolExecutor
    4. Each worker reads its time slice from preprocessed Zarr
    5. Compute spherical coordinates and append to Icechunk store
    6. Yield final daily datasets

    Parameters
    ----------
    matched_data_dirs : MatchedDirs
        Matched directories for canopy and reference data
    site : GnssResearchSite
        Research site with Icechunk stores
    aux_file_path : Path, optional
        Root path for auxiliary files
    n_max_workers : int | None, default None
        Maximum parallel workers (CPUs) for RINEX processing.
        ``None`` lets ``ProcessPoolExecutor`` auto-detect via
        ``os.cpu_count()``.

    """

    def __init__(
        self,
        matched_data_dirs: MatchedDirs,
        site: GnssResearchSite,
        aux_file_path: Path | None = None,
        n_max_workers: int | None = None,
        reader_name: str = "rinex3",
        use_sbf_geometry: bool = False,
    ) -> None:
        t_init_start = time.perf_counter()

        self.matched_data_dirs = matched_data_dirs
        self.site = site
        self.aux_file_path = aux_file_path
        if n_max_workers is not None:
            self.n_max_workers = min(n_max_workers, os.cpu_count() or n_max_workers)
        else:
            self.n_max_workers = None
        self._reader_name = reader_name  # fallback; prefer per-receiver reader_format
        # use_sbf_geometry: explicit param wins, otherwise read from config
        self._use_sbf_geometry_override = use_sbf_geometry
        self._logger = get_logger(__name__).bind(
            site=site.site_name,
            workers=self.n_max_workers or os.cpu_count(),
            component="processor",  # Enable component-specific logging
        )
        # Dedicated logger for icechunk store operations
        self._icechunk_log = get_logger(__name__).bind(
            site=site.site_name,
            component="icechunk",
        )

        t_config_start = time.perf_counter()
        config = load_config()
        self._config = config  # cache to avoid re-reading YAML in methods
        self._keeper_tags_enabled: bool = config.processing.storage.keeper_tags
        self.keep_sids = config.sids.get_sids()

        # Resolve ephemeris source: explicit param > config > default (final)
        if self._use_sbf_geometry_override:
            self.use_sbf_geometry = True
        else:
            self.use_sbf_geometry = (
                config.processing.params.ephemeris_source == "broadcast"
            )

        # Cache config values formerly in globals
        aux_cfg = config.processing.aux_data
        self._agency = aux_cfg.agency
        self._product_type = aux_cfg.product_type
        servers = aux_cfg.get_ftp_servers(config.nasa_earthdata_acc_mail)
        self._ftp_server = servers[0][0]
        self._gnss_store_strategy = config.processing.storage.gnss_store_strategy
        t_config_end = time.perf_counter()

        self._logger.info(
            "processor_initialized",
            aux_file_path=str(aux_file_path) if aux_file_path else None,
            sid_filtering=len(self.keep_sids) if self.keep_sids else "all",
            cpu_count=os.cpu_count(),
            config_load_seconds=round(t_config_end - t_config_start, 4),
        )

        # Initialize auxiliary data pipeline (loads SP3 and CLK files)
        # Skip when using broadcast ephemerides (no SP3/CLK needed)
        if self.use_sbf_geometry:
            self.aux_pipeline = None
            self._logger.info(
                "aux_pipeline_skipped",
                reason="ephemeris_source=broadcast, using SBF SatVisibility",
            )
        else:
            self.aux_pipeline = self._initialize_aux_pipeline()

        t_init_end = time.perf_counter()
        self._logger.info(
            "processor_init_complete",
            total_init_seconds=round(t_init_end - t_init_start, 2),
            config_seconds=round(t_config_end - t_config_start, 4),
            aux_pipeline_seconds=round(t_init_end - t_config_end, 2),
        )

    def _initialize_aux_pipeline(self) -> AuxDataPipeline:
        """Initialize and load auxiliary data pipeline.

        Returns
        -------
        AuxDataPipeline
            Loaded pipeline with ephemerides and clock data

        """
        t0 = time.perf_counter()
        self._logger.info(
            "aux_pipeline_initialization_started",
            agency=self._agency,
            product_type=self._product_type,
        )

        # Use cached config (avoids re-reading YAML)
        config = self._config
        user_email = config.nasa_earthdata_acc_mail

        # Determine aux_file_path: explicit > config aux_data_dir > site data root
        aux_file_path = self.aux_file_path
        if aux_file_path is None:
            configured_aux_dir = config.processing.storage.aux_data_dir
            if configured_aux_dir is not None:
                aux_file_path = configured_aux_dir
            else:
                aux_file_path = Path(self.site.site_config["gnss_site_data_root"])

        t1 = time.perf_counter()
        pipeline = AuxDataPipeline.create_standard(
            matched_dirs=self.matched_data_dirs,
            aux_file_path=aux_file_path,
            agency=self._agency,
            product_type=self._product_type,
            ftp_server=self._ftp_server,
            user_email=user_email,
            keep_sids=self.keep_sids,
        )
        t2 = time.perf_counter()

        self._logger.info(
            "aux_pipeline_create_standard_complete",
            duration_seconds=round(t2 - t1, 2),
        )

        # Load all auxiliary files into memory
        pipeline.load_all()
        t3 = time.perf_counter()

        self._logger.info(
            "aux_pipeline_initialization_complete",
            total_seconds=round(t3 - t0, 2),
            create_standard_seconds=round(t2 - t1, 2),
            load_all_seconds=round(t3 - t2, 2),
            products=list(pipeline._cache.keys())
            if hasattr(pipeline, "_cache")
            else [],
        )
        return pipeline

    def _make_reader(self, fpath: Path, reader_format: str | None = None):
        """Instantiate the configured GNSS reader for *fpath*.

        Parameters
        ----------
        fpath : Path
            GNSS data file.
        reader_format : str | None
            Reader format override.  Falls back to ``self._reader_name``.

        """
        from canvodpy.factories import ReaderFactory

        aggregate = self._config.processing.params.aggregate_glonass_fdma
        return ReaderFactory.create(
            reader_format or self._reader_name,
            fpath=fpath,
            aggregate_glonass_fdma=aggregate,
        )

    @staticmethod
    def _parse_sampling_interval_from_filename(filename: str) -> float | None:
        """Extract sampling interval from RINEX v3 long filename.

        RINEX v3.04 long filenames encode the data frequency at a fixed
        position, e.g. ``ROSA01TUW_R_20250020000_01D_05S_AA.rnx`` where
        ``05S`` means 5-second sampling.

        Parameters
        ----------
        filename : str
            RINEX filename (stem or full name).

        Returns
        -------
        float or None
            Sampling interval in seconds, or None if parsing fails.

        """
        import re

        # RINEX v3 long filename: XXXXNNXXX_R_YYYYDDDHHMM_DUR_FREQ_AA.rnx
        # The frequency field is the 5th underscore-separated component
        parts = Path(filename).stem.split("_")
        if len(parts) >= 5:
            freq = parts[4]  # e.g. "05S", "30S", "01Z" (1 Hz)
            m = re.match(r"^(\d+)([SMHDZC])$", freq)
            if m:
                value, unit = int(m.group(1)), m.group(2)
                multipliers = {"S": 1, "M": 60, "H": 3600, "D": 86400}
                if unit == "Z":  # Hz -> seconds
                    return 1.0 / value if value else None
                if unit in multipliers:
                    return float(value * multipliers[unit])
        return None

    def _preprocess_aux_data_with_hermite(
        self,
        rinex_files: list[Path],
        output_path: Path,
        reader_format: str | None = None,
        group: str | None = None,
        grid_seconds: float | None = None,
    ) -> float:
        """Preprocess auxiliary data using proper interpolation strategies.

        Parameters
        ----------
        group : str | None
            Zarr group to write under (e.g. a §44 shared-cache fingerprint
            path). ``None`` (default) writes to the store root, unchanged
            legacy behavior.
        grid_seconds : float | None
            When set (§44 shared-cache mode), build the target epoch grid
            from this fixed interval instead of the detected
            ``sampling_interval`` -- a site-independent grid is required
            for the cache entry to be safely shared across sites with
            different sampling rates. ``sampling_interval`` is still
            detected and returned either way.
        """
        t0 = time.perf_counter()
        self._logger.info(
            "aux_preprocessing_started",
            rinex_files=len(rinex_files),
            output_path=str(output_path),
            interpolation_method="hermite_cubic",
        )

        # 1. Detect sampling interval from filename (fast path)
        sampling_interval = self._parse_sampling_interval_from_filename(
            rinex_files[0].name,
        )
        # Derive day_start from the YYYYDOY we already know
        day_date = self.matched_data_dirs.yyyydoy.date
        day_start = np.datetime64(day_date, "D")

        if sampling_interval is not None:
            t1 = time.perf_counter()
            self._logger.info(
                "sampling_detected",
                sampling_interval_seconds=sampling_interval,
                source="filename",
                detection_seconds=round(t1 - t0, 4),
            )
        else:
            # Fallback: read first GNSS file (slow path)
            self._logger.debug(
                "sampling_detection_started",
                sample_file=rinex_files[0].name,
                reason="filename_parse_failed",
            )
            first_rnx = self._make_reader(rinex_files[0], reader_format)
            first_ds = first_rnx.to_ds(
                keep_data_vars=[],
                write_global_attrs=True,
            )
            t1 = time.perf_counter()
            time_diff = (first_ds.epoch[1] - first_ds.epoch[0]).values
            sampling_interval = float(time_diff / np.timedelta64(1, "s"))
            first_epoch = first_ds.epoch.values[0]
            day_start = np.datetime64(first_epoch.astype("datetime64[D]"))
            self._logger.info(
                "sampling_detected",
                sampling_interval_seconds=sampling_interval,
                source="full_rinex_read",
                rinex_read_seconds=round(t1 - t0, 2),
            )

        self._logger.debug(
            "day_boundaries_detected",
            day_start=str(day_start),
            sampling_interval=sampling_interval,
        )

        effective_grid_seconds = (
            grid_seconds if grid_seconds is not None else sampling_interval
        )
        n_epochs = int(24 * 3600 / effective_grid_seconds)
        target_epochs = day_start + np.arange(n_epochs) * np.timedelta64(
            int(effective_grid_seconds), "s"
        )

        self._logger.info(
            "epoch_grid_generated",
            n_epochs=len(target_epochs),
            day_start=str(target_epochs[0]),
            day_end=str(target_epochs[-1]),
            coverage_hours=24,
        )

        # 4. Get auxiliary datasets from pipeline
        t2 = time.perf_counter()
        self._logger.debug("fetching_auxiliary_datasets")
        assert self.aux_pipeline is not None, "aux_pipeline must be initialized"
        ephem_ds = self.aux_pipeline.get("ephemerides")
        clock_ds = (
            self.aux_pipeline.get("clock")
            if self.aux_pipeline.is_loaded("clock")
            else None
        )
        t3 = time.perf_counter()
        self._logger.debug(
            "auxiliary_datasets_fetched",
            duration_seconds=round(t3 - t2, 4),
            ephemeris_dims=dict(ephem_ds.sizes) if ephem_ds else None,
            clock_dims=dict(clock_ds.sizes) if clock_ds is not None else None,
            ephemeris_vars=list(ephem_ds.data_vars.keys()) if ephem_ds else [],
            clock_vars=list(clock_ds.data_vars.keys()) if clock_ds is not None else [],
        )

        # 5. Interpolate ephemerides using Hermite splines
        self._logger.info(
            "ephemeris_interpolation_started",
            method="hermite_cubic_with_velocities",
            target_epochs=len(target_epochs),
        )
        sp3_config = Sp3Config(use_velocities=True, fallback_method="linear")
        sp3_interpolator = Sp3InterpolationStrategy(config=sp3_config)

        t4 = time.perf_counter()
        ephem_interp = sp3_interpolator.interpolate(ephem_ds, target_epochs)
        t5 = time.perf_counter()

        self._logger.info(
            "ephemeris_interpolation_complete",
            duration_seconds=round(t5 - t4, 2),
            output_shape=dict(ephem_interp.sizes),
            sids=len(ephem_interp.sid),
        )

        # Store interpolation metadata
        ephem_interp.attrs["interpolator_config"] = sp3_interpolator.to_attrs()

        # 6. Interpolate clock corrections using piecewise linear (unless
        # fetch_clock is disabled in config — see AuxDataConfig.fetch_clock)
        t6 = time.perf_counter()
        if clock_ds is not None:
            self._logger.info(
                "clock_interpolation_started",
                method="piecewise_linear",
                target_epochs=len(target_epochs),
            )
            clock_config = ClockConfig(window_size=9, jump_threshold=1e-6)
            clock_interpolator = ClockInterpolationStrategy(config=clock_config)

            clock_interp = clock_interpolator.interpolate(clock_ds, target_epochs)
            t7 = time.perf_counter()

            self._logger.info(
                "clock_interpolation_complete",
                duration_seconds=round(t7 - t6, 2),
                output_shape=dict(clock_interp.sizes),
            )

            # Store interpolation metadata
            clock_interp.attrs["interpolator_config"] = clock_interpolator.to_attrs()

            # 7. Merge ephemerides and clock into single dataset
            self._logger.debug("merging_auxiliary_datasets")
            aux_processed = xr.merge([ephem_interp, clock_interp])
            t8 = time.perf_counter()
            self._logger.debug(
                "merge_complete",
                duration_seconds=round(t8 - t7, 4),
                final_dims=dict(aux_processed.sizes),
                final_vars=list(aux_processed.data_vars.keys()),
            )
        else:
            self._logger.info(
                "clock_interpolation_skipped", reason="fetch_clock disabled"
            )
            t7 = t6
            aux_processed = ephem_interp
            t8 = time.perf_counter()

        # 8. Write to Zarr
        self._logger.info(
            "aux_zarr_write_started",
            output_path=str(output_path),
            group=group,
            data_size=dict(aux_processed.sizes),
        )
        with scoped_zarr_concurrency(
            self._config.processing.aux_data.zarr_async_concurrency
        ):
            aux_processed.to_zarr(
                output_path, group=group, mode="w", consolidated=False
            )
        t9 = time.perf_counter()

        self._logger.info(
            "aux_preprocessing_complete",
            total_seconds=round(t9 - t0, 2),
            rinex_read_seconds=round(t1 - t0, 2),
            aux_fetch_seconds=round(t3 - t2, 4),
            ephem_interp_seconds=round(t5 - t4, 2),
            clock_interp_seconds=round(t7 - t6, 2),
            merge_seconds=round(t8 - t7, 4),
            zarr_write_seconds=round(t9 - t8, 2),
            data_size=dict(aux_processed.sizes),
            output_path=str(output_path),
        )

        return sampling_interval

    def _get_rinex_files(
        self, rinex_dir: Path, reader_format: str | None = None
    ) -> list[Path]:
        """Get sorted list of GNSS data files from directory.

        Uses ``BUILTIN_PATTERNS`` from canvod-filemap when installed.
        Falls back to canonical canVOD globs (``*.rnx``, ``*.sbf``) otherwise.

        Parameters
        ----------
        rinex_dir : Path
            Directory to search.
        reader_format : str | None
            If ``"sbf"``, restrict to SBF glob patterns only.
            Otherwise discovers all recognized GNSS file types.

        """
        if not rinex_dir.exists():
            self._logger.warning("Directory does not exist: %s", rinex_dir)
            return []

        try:
            from canvod.filemap.patterns import (
                BUILTIN_PATTERNS,
                auto_match_order,
            )

            _has_patterns = True
        except ImportError:
            _has_patterns = False

        if _has_patterns:
            if reader_format == "sbf":
                globs = set(BUILTIN_PATTERNS["septentrio_sbf"].file_globs)
                globs.update(
                    g for g in BUILTIN_PATTERNS["canvod"].file_globs if ".sbf" in g
                )
            elif reader_format in ("rinex3", "rinex"):
                rinex_pattern_names = [
                    n for n in auto_match_order() if n != "septentrio_sbf"
                ]
                globs: set[str] = set()
                for name in rinex_pattern_names:
                    globs.update(BUILTIN_PATTERNS[name].file_globs)
            else:
                globs: set[str] = set()
                for name in auto_match_order():
                    globs.update(BUILTIN_PATTERNS[name].file_globs)
        else:
            # Fallback: canonical canVOD names only (*.rnx, *.sbf).
            # Non-canonical filenames require canvod-filemap + a recipe.
            if reader_format == "sbf":
                globs = {"*.sbf", "*.SBF"}
            elif reader_format in ("rinex3", "rinex"):
                globs = {"*.rnx", "*.RNX"}
            else:
                globs = {"*.rnx", "*.RNX", "*.sbf", "*.SBF"}

        rinex_files: list[Path] = []
        seen: set[Path] = set()
        for g in sorted(globs):
            for path in rinex_dir.glob(g):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    rinex_files.append(path)

        return natsorted(rinex_files)

    def _get_virtual_files(
        self,
        receiver_name: str,
        receiver_base_dir: Path,
        year: int,
        doy: int,
    ) -> list:
        """Discover and validate files using FilenameMapper.

        Parameters
        ----------
        receiver_name : str
            Receiver name from config.
        receiver_base_dir : Path
            Root directory for this receiver's data.
        year, doy : int
            Date to discover files for.

        Returns
        -------
        list[VirtualFile]
            Sorted virtual files for the given date.

        Raises
        ------
        ValueError
            If validation fails (unmatched files or overlaps).
        """
        try:
            from canvod.filemap import (
                FilenameMapper,
                ReceiverNamingConfig,
                SiteNamingConfig,
            )
        except ImportError as exc:
            raise ImportError(
                "canvod-filemap is required for recipe-based filename "
                "mapping but is not installed. Install it separately or remove "
                "the 'recipe:' field from your receiver config."
            ) from exc

        # Resolve site and receiver naming config
        site_config = self._get_site_config()
        receiver_cfg = site_config.receivers[receiver_name]

        if not site_config.naming or not receiver_cfg.naming:
            self._logger.warning(
                "naming_config_missing, falling back to _get_rinex_files",
                receiver=receiver_name,
            )
            return []

        site_naming = SiteNamingConfig(**site_config.naming)
        receiver_naming = ReceiverNamingConfig(**receiver_cfg.naming)
        receiver_type = receiver_cfg.type

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=receiver_naming,
            receiver_type=receiver_type,
            receiver_base_dir=receiver_base_dir,
        )

        vfs = mapper.discover_for_date(year, doy)

        # Validate: detect overlaps
        overlaps = FilenameMapper.detect_overlaps(vfs)
        if overlaps:
            overlap_msgs = [
                f"  {a.canonical_str} <-> {b.canonical_str}" for a, b in overlaps[:10]
            ]
            msg = (
                f"Temporal overlaps detected for {receiver_name} "
                f"on {year}/{doy:03d}:\n" + "\n".join(overlap_msgs)
            )
            raise ValueError(msg)

        return vfs

    def _get_site_config(self):
        """Get the SiteConfig for the current site."""
        sites_cfg = self._config.sites
        # Find our site by matching site name
        for site_name, site_cfg in sites_cfg.sites.items():
            if site_name == self.site.site_name:
                return site_cfg
        msg = f"Site '{self.site.site_name}' not found in config"
        raise ValueError(msg)

    def _compute_receiver_position(
        self,
        position_files: list[Path],
        receiver_name: str,
        reader_format: str | None = None,
    ) -> ECEFPosition | None:
        """Compute ECEF position from the first valid GNSS file.

        Uses the ``ReaderFactory`` to create a minimal dataset (header-only)
        and extracts the ECEF position from its attributes.  This works for
        any registered reader format (RINEX, SBF, …) without format-specific
        logic.

        Parameters
        ----------
        position_files : list[Path]
            GNSS files to try (first valid one wins).
        receiver_name : str
            Receiver name for logging.
        reader_format : str | None
            Reader format name (e.g. ``"rinex3"``, ``"sbf"``).
            Falls back to ``self._reader_name`` when *None*.

        Returns
        -------
        ECEFPosition | None
            Computed position, or None if no valid file found.

        """
        fmt = reader_format or self._reader_name

        for ff in position_files:
            try:
                reader = self._make_reader(ff, reader_format=fmt)
                ds = reader.to_ds(keep_data_vars=[], write_global_attrs=True)
                receiver_position = ECEFPosition.from_ds_metadata(ds)
                self._logger.info(
                    "Computed receiver position for %s: %s",
                    receiver_name,
                    receiver_position,
                )
                return receiver_position
            except (ValidationError, pydantic_core.ValidationError) as e:
                self._logger.warning(
                    "Validation error for %s: %s",
                    ff.name,
                    e,
                )
            except (KeyError, OSError, RuntimeError, ValueError) as e:
                self._logger.warning(
                    "Could not extract position from %s: %s",
                    ff.name,
                    e,
                )

        self._logger.error(
            "No valid GNSS files found for position extraction for %s",
            receiver_name,
        )
        return None

    def _resolve_receiver_positions(
        self,
        normalized_configs: list[tuple],
        files_by_dir: dict,
    ) -> dict:
        """Resolve every receiver's ECEF position upfront (Phase 1).

        Returns dict keyed by receiver_name (store group name).
        Positions are computed once per unique source directory and shared.
        """
        position_mode = self._config.processing.params.receiver_position_mode
        pos_by_source: dict = {}  # (source_dir, fmt) -> ECEFPosition | None
        result: dict = {}

        for name, rtype, data_dir, position_data_dir, fmt in normalized_configs:
            if position_mode == "per_receiver":
                source_dir = data_dir
                self._logger.warning(
                    "receiver_position_mode='per_receiver': using %s's own "
                    "position (breaks direct SNR comparability)",
                    name,
                )
            else:
                source_dir = (
                    position_data_dir if position_data_dir is not None else data_dir
                )

            key = (source_dir, fmt)
            if key not in pos_by_source:
                files = files_by_dir.get(key) or self._get_rinex_files(source_dir, fmt)
                pos_by_source[key] = self._compute_receiver_position(
                    files, name, reader_format=fmt
                )
            result[name] = pos_by_source[key]

        return result

    def _recompute_scs_for_position(
        self,
        cached_datasets: list,
        aux_zarr_path,
        receiver_position,
    ) -> list:
        """Recompute spherical coordinates for a new receiver position.

        Opens the aux Zarr once (hoisted outside the per-file loop) and
        recomputes theta/phi/r for every cached dataset using the new position.
        """
        if aux_zarr_path is None:
            raise RuntimeError(
                "SCS recompute from cache requires an aux zarr; "
                "not available with SBF geometry"
            )
        # Hoist open_zarr outside the per-file loop (was reopened per file)
        aux_store = xr.open_zarr(
            aux_zarr_path, decode_timedelta=True, consolidated=False
        )
        augmented_datasets = []
        try:
            for fpath, ds in cached_datasets:
                scs_vars = [v for v in ("theta", "phi", "r") if v in ds.data_vars]
                ds_no_scs = ds.drop_vars(scs_vars)
                common_sids = sorted(
                    set(ds_no_scs.sid.values) & set(aux_store.sid.values)
                )
                aux_slice = aux_store.sel(epoch=ds_no_scs.epoch, method="nearest").sel(
                    sid=common_sids
                )
                ds_recomputed = _compute_spherical_coords_fast(
                    ds_no_scs, aux_slice, receiver_position
                )
                # Mirror Wave A: drop r if it was absent in the cached dataset
                if "r" not in scs_vars and "r" in ds_recomputed.data_vars:
                    ds_recomputed = ds_recomputed.drop_vars("r")
                augmented_datasets.append((fpath, ds_recomputed))
        finally:
            aux_store.close()
        return augmented_datasets

    @staticmethod
    def _build_compute_waves(
        normalized_configs: list,
        skipped: set,
    ) -> tuple[list, list, dict]:
        """Group receivers into Wave A (parse) and Wave B (SCS recompute).

        Returns (wave_a, wave_b, parse_owner) where:
        - wave_a: [(name, data_dir, fmt)] — one parse job per unique (data_dir, fmt)
        - wave_b: [(name, data_dir, fmt)] — SCS recompute from Wave A cache
        - parse_owner: {(data_dir, fmt): name} — which receiver owns each parse job
        """
        parse_owner: dict = {}
        wave_a: list = []
        wave_b: list = []
        for name, rtype, data_dir, _pos, fmt in normalized_configs:
            if name in skipped:
                continue
            key = (data_dir, fmt)
            if key not in parse_owner:
                parse_owner[key] = name
                wave_a.append((name, data_dir, fmt))
            else:
                wave_b.append((name, data_dir, fmt))
        return wave_a, wave_b, parse_owner

    def _ensure_aux_data_preprocessed(
        self,
        canopy_files: list[Path],
        date_str: str,
        reader_format: str | None = None,
    ) -> tuple[Path, str | None]:
        """Ensure auxiliary data is preprocessed and available.

        When ``StorageConfig.shared_aux_cache_dir`` is set (dev/todo_later.md
        §44), checks a network-wide, fingerprint-keyed cache before
        rebuilding -- ephemeris products are satellite-based, not
        site-based, so multiple sites sharing the same agency/product/date
        can reuse one cache entry instead of each rebuilding it. Falls back
        to the legacy per-site behavior (always rebuild) when unset.

        Parameters
        ----------
        canopy_files : list[Path]
            GNSS files for sampling detection
        date_str : str
            Date string (e.g., '2025213')
        reader_format : str | None
            Reader format for the files (used in sampling fallback).

        Returns
        -------
        tuple[Path, str | None]
            ``(store_path, group)`` -- the Zarr store to open and the group
            within it holding this day's aux data. ``group`` is ``None`` in
            legacy (non-shared-cache) mode, meaning the store root.

        Raises
        ------
        RuntimeError
            If preprocessing fails or the data isn't present after it
        """
        shared_cache_dir = self._config.processing.storage.get_shared_aux_cache_dir()
        if shared_cache_dir is not None:
            return self._ensure_shared_aux_cache(
                canopy_files, date_str, shared_cache_dir, reader_format=reader_format
            )

        import shutil

        t0 = time.perf_counter()
        aux_base_dir = self._config.processing.storage.get_aux_data_dir()
        # Nest alongside canvod-auxiliary's 01_SP3/02_CLK download subdirs
        # instead of littering aux_base_dir's root with one aux_*.zarr per date.
        aux_zarr_path = aux_base_dir / "00_aux_zarr" / f"aux_{date_str}.zarr"
        aux_zarr_path.parent.mkdir(parents=True, exist_ok=True)

        # Always reprocess from raw SP3/CLK files — the Hermite interpolation
        # is cheap and this avoids stale caches when SIDs change.
        had_cache = aux_zarr_path.exists()
        if had_cache:
            try:
                shutil.rmtree(aux_zarr_path)
            except OSError as _rmtree_err:
                if _rmtree_err.errno == 66:  # ENOTEMPTY — macOS Finder race; retry
                    shutil.rmtree(aux_zarr_path, ignore_errors=True)
                else:
                    raise

        t1 = time.perf_counter()
        self._logger.info(
            "aux_preprocessing_required",
            output_path=str(aux_zarr_path),
            interpolation="hermite_cubic",
            cache_cleared=had_cache,
            rmtree_seconds=round(t1 - t0, 4) if had_cache else 0,
        )
        try:
            self._preprocess_aux_data_with_hermite(
                canopy_files, aux_zarr_path, reader_format=reader_format
            )

            if not aux_zarr_path.exists():
                raise RuntimeError(
                    f"Aux preprocessing completed but file not found: {aux_zarr_path}"
                )

            # macOS creates .DS_Store inside directories Finder/Spotlight has
            # touched; zarr's group listing then warns on the unrecognized
            # member. Same fix as MyIcechunkStore._clean_ds_store() in
            # canvod-store, applied here since this plain aux Zarr isn't
            # opened through that class.
            sanitize_directory(aux_zarr_path)

            self._logger.info(
                "aux_preprocessing_verified",
                file_exists=True,
                path=str(aux_zarr_path),
            )
        except Exception as e:
            self._logger.error(
                "aux_preprocessing_failed",
                error=str(e),
                exception=type(e).__name__,
                path=str(aux_zarr_path),
            )
            raise

        return aux_zarr_path, None

    def _ensure_shared_aux_cache(
        self,
        canopy_files: list[Path],
        date_str: str,
        shared_cache_dir: Path,
        reader_format: str | None = None,
    ) -> tuple[Path, str]:
        """§44 shared-cache lookup/populate, called when the cache is enabled.

        On a miss, writes to a per-attempt temp group and renames it into
        place only on success, rather than writing directly to the final
        path -- a network-wide cache has a wider blast radius than a
        per-site one if a torn/partial write is ever read by a different
        site's concurrent run. NOTE: ``Path.rename()`` is one syscall from
        Python's side, but a zarr group is a directory tree (many chunk
        files + zarr.json) -- whether the underlying filesystem honors a
        directory rename as a single atomic operation is server/protocol
        dependent, not a hard guarantee the way a single-file rename
        typically is. This is strictly better than a direct write, not a
        fully closed risk -- verifiable only on the actual (CIFS) mount
        this is meant to protect, which has already dropped mid-operation
        three times this week for unrelated reasons.
        """
        import shutil
        import uuid

        cache_root = shared_cache_dir / "aux_cache.zarr"
        assert self.aux_pipeline is not None, "aux_pipeline must be initialized"
        fingerprint = compute_aux_cache_fingerprint(
            agency=self._config.processing.aux_data.agency,
            product_type=self._config.processing.aux_data.product_type,
            ephemeris_source=self._config.processing.params.ephemeris_source,
            canonical_grid_seconds=CANONICAL_AUX_GRID_SECONDS,
            source_file_paths=self.aux_pipeline.source_file_paths(),
        )
        group = f"{fingerprint}/{date_str}"

        if (cache_root / group).exists():
            self._logger.info("aux_cache_hit", fingerprint=fingerprint, date=date_str)
            # Sweep on every hit, not just on populate (below) -- Finder can
            # drop a fresh .DS_Store into a shared/mounted cache dir between
            # runs, and a hit path that skips this leaves every subsequent
            # xr.open_zarr() on cache_root tripping zarr's group-listing
            # warning until the next miss happens to populate+sweep it.
            sanitize_directory(cache_root)
            return cache_root, group

        self._logger.info("aux_cache_miss", fingerprint=fingerprint, date=date_str)
        tmp_group = f"{fingerprint}/.tmp-{date_str}-{uuid.uuid4().hex[:8]}"
        try:
            self._preprocess_aux_data_with_hermite(
                canopy_files,
                cache_root,
                reader_format=reader_format,
                group=tmp_group,
                grid_seconds=CANONICAL_AUX_GRID_SECONDS,
            )
            if not (cache_root / tmp_group).exists():
                raise RuntimeError(
                    f"Aux preprocessing completed but group not found: "
                    f"{cache_root}/{tmp_group}"
                )
            # Promotion, not a second write to the final path. If two sites
            # race the same miss, the loser's rename just overwrites the
            # winner's with an equally-valid result (both did legitimate,
            # correct work) -- what this avoids is a *torn* write at the
            # final path from concurrent writers, not the (benign)
            # redundant computation itself.
            (cache_root / tmp_group).rename(cache_root / group)

            # macOS creates .DS_Store inside directories Finder/Spotlight has
            # touched; zarr's group listing then warns on the unrecognized
            # member. Same fix as MyIcechunkStore._clean_ds_store() in
            # canvod-store, applied here since this is a plain Zarr store
            # (cache_root), not opened through that class. Sweeps the whole
            # cache_root tree, not just this date's group, since a stray
            # .DS_Store anywhere above it (e.g. at the fingerprint level)
            # would still trigger the warning on every future open.
            sanitize_directory(cache_root)
        except Exception as e:
            self._logger.error(
                "aux_cache_populate_failed",
                error=str(e),
                exception=type(e).__name__,
                fingerprint=fingerprint,
                date=date_str,
            )
            # Best-effort cleanup -- a failed attempt (e.g. a CIFS hiccup
            # mid-write) shouldn't leave a permanent orphaned .tmp- dir in
            # a shared, multi-site cache store with no GC mechanism.
            shutil.rmtree(cache_root / tmp_group, ignore_errors=True)
            raise

        self._logger.info("aux_cache_populated", fingerprint=fingerprint, date=date_str)
        return cache_root, group

    def _parallel_process_rinex(
        self,
        rinex_files: list[Path],
        keep_vars: list[str],
        aux_zarr_path: Path,
        receiver_position: ECEFPosition,
        receiver_type: str,
        reader_format: str | None = None,
        show_progress: bool = True,
        pool_workers: int | None = None,
        aux_group: str | None = None,
    ) -> tuple[
        list[tuple[Path, xr.Dataset]],
        dict[Path, dict[str, xr.Dataset]],
        dict[str, list[str]],
    ]:
        """Parallel process RINEX files using ProcessPoolExecutor.

        Uses TRUE parallelism (no GIL) with separate processes.
        Each worker reads only its time slice from the Zarr store.

        Parameters
        ----------
        rinex_files : list[Path]
            List of RINEX files to process
        keep_vars : list[str]
            Variables to keep
        aux_zarr_path : Path
            Path to preprocessed aux Zarr store (with Hermite interpolation)
        receiver_position : ECEFPosition
            Receiver position (computed once)
        receiver_type : str
            Receiver type
        reader_format : str | None
            Per-receiver reader format. Falls back to ``self._reader_name``.
        show_progress : bool
            Whether to show the Rich progress bar (default True).
        pool_workers : int | None
            Override for worker count. When None, uses ``self.n_max_workers``.
        aux_group : str | None
            Zarr group within ``aux_zarr_path`` to read aux data from (§44
            shared-cache mode). None reads the store root.

        Returns
        -------
        tuple
            (augmented_datasets, aux_datasets_by_file, sid_issues) where
            augmented_datasets is sorted chronologically by filename.

        """
        effective_reader = reader_format or self._reader_name
        store_r = self._config.processing.params.store_radial_distance
        store_raw = self._config.processing.params.store_sbf_raw_observables
        return self._parallel_process_rinex_pool(
            rinex_files,
            keep_vars,
            aux_zarr_path,
            receiver_position,
            receiver_type,
            effective_reader,
            store_r,
            store_raw,
            show_progress=show_progress,
            pool_workers=pool_workers,
            aux_group=aux_group,
        )

    def _parallel_process_rinex_pool(
        self,
        rinex_files: list[Path],
        keep_vars: list[str],
        aux_zarr_path: Path,
        receiver_position: ECEFPosition,
        receiver_type: str,
        reader_format: str | None = None,
        store_radial_distance: bool = False,
        store_sbf_raw_observables: bool = True,
        show_progress: bool = True,
        pool_workers: int | None = None,
        aux_group: str | None = None,
    ) -> tuple[
        list[tuple[Path, xr.Dataset]],
        dict[Path, dict[str, xr.Dataset]],
        dict[str, list[str]],
    ]:
        """Fallback: process RINEX files via ProcessPoolExecutor."""
        start_time = time.time()
        workers = pool_workers if pool_workers is not None else self.n_max_workers
        effective_workers = workers or os.cpu_count() or 1
        self._logger.info(
            "parallel_processing_started",
            workers=effective_workers,
            files=len(rinex_files),
            receiver_type=receiver_type,
            executor_type="ProcessPoolExecutor",
        )

        self._logger.debug(
            "parallel_config",
            max_workers=workers,
            cpu_count=os.cpu_count(),
            files_per_worker=round(len(rinex_files) / effective_workers, 1),
        )

        results: list[tuple[Path, xr.Dataset]] = []
        aux_datasets_by_file: dict[Path, dict[str, xr.Dataset]] = {}
        sid_issues_agg: dict[str, set] = {}
        task_submission_start = time.time()

        effective_reader = reader_format or self._reader_name
        _res = self._config.processing.params.resolve_resources()
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_worker_init_with_run_id,
            initargs=(_res["nice_priority"], _res["cpu_affinity"], get_run_id()),
        ) as executor:
            futures = {
                executor.submit(
                    preprocess_with_hermite_aux,
                    rinex_file,
                    keep_vars,
                    aux_zarr_path,
                    receiver_position,
                    receiver_type,
                    self.keep_sids,
                    effective_reader,
                    self.use_sbf_geometry,
                    store_radial_distance,
                    store_sbf_raw_observables,
                    aux_group=aux_group,
                ): rinex_file
                for rinex_file in rinex_files
            }

            task_submission_time = time.time() - task_submission_start
            self._logger.debug(
                "tasks_submitted",
                task_count=len(futures),
                submission_time_seconds=round(task_submission_time, 3),
            )

            completed_count = 0
            failed_count = 0

            yyyydoy = self.matched_data_dirs.yyyydoy.to_str()
            desc = f"{yyyydoy} {receiver_type}"
            with _processing_progress(disable=not show_progress) as progress:
                task = progress.add_task(desc, total=len(futures))
                for fut in as_completed(futures):
                    try:
                        fname, ds_augmented, aux, sids = fut.result()
                        results.append((fname, ds_augmented))
                        aux_datasets_by_file[fname] = aux
                        for key, vals in sids.items():
                            sid_issues_agg.setdefault(key, set()).update(vals)
                        completed_count += 1

                        if completed_count % 10 == 0:
                            self._logger.debug(
                                "processing_progress",
                                completed=completed_count,
                                total=len(futures),
                                failed=failed_count,
                                progress_pct=round(
                                    100 * completed_count / len(futures), 1
                                ),
                            )
                    except BrokenProcessPool as e:
                        failed_file = futures[fut].name
                        failed_count += 1
                        self._logger.error(
                            "worker_pool_broken",
                            file=failed_file,
                            error=str(e),
                            failed_count=failed_count,
                            hint="worker process likely killed by OOM or segfault",
                        )
                    except (OSError, RuntimeError, ValueError) as e:
                        failed_file = futures[fut].name
                        failed_count += 1
                        self._logger.error(
                            "file_processing_failed",
                            file=failed_file,
                            error=str(e),
                            exception=type(e).__name__,
                            failed_count=failed_count,
                        )
                    progress.advance(task)

        # Sort chronologically by filename
        self._logger.debug("sorting_results_chronologically")
        results.sort(key=lambda x: x[0].name)

        duration = time.time() - start_time
        self._logger.info(
            "parallel_processing_complete",
            files_processed=len(results),
            files_total=len(rinex_files),
            files_failed=len(rinex_files) - len(results),
            duration_seconds=round(duration, 2),
            avg_time_per_file=round(duration / len(rinex_files), 2)
            if rinex_files
            else 0,
            throughput_files_per_sec=round(len(results) / duration, 2)
            if duration > 0
            else 0,
        )
        sid_issues_final = {k: sorted(v) for k, v in sid_issues_agg.items()}
        return results, aux_datasets_by_file, sid_issues_final

    def _check_store_vars_consistency(
        self,
        session: ForkSession,
        receiver_name: str,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
    ) -> None:
        """Warn if the store has different variables than the current batch.

        Detects stale variables from previous runs with different keep_gnss_observables.
        """
        try:
            ds_store = xr.open_zarr(
                session.store, group=receiver_name, consolidated=False
            )
            store_vars = set(ds_store.data_vars)
        except KeyError, zarr.errors.GroupNotFoundError:
            return  # New group, nothing to check

        if not augmented_datasets:
            return
        _, first_ds = augmented_datasets[0]
        batch_vars = set(first_ds.data_vars)

        stale_vars = store_vars - batch_vars
        missing_vars = batch_vars - store_vars

        if stale_vars:
            self._logger.warning(
                "store_has_stale_variables",
                receiver=receiver_name,
                stale_vars=sorted(stale_vars),
                hint=(
                    "The store contains variables not in the current keep_gnss_observables. "
                    "This causes dimension conflicts on read-back. "
                    "With gnss_store_strategy='overwrite', stale vars will be "
                    "dropped automatically. Otherwise delete the store and reprocess."
                ),
            )
        if missing_vars:
            self._logger.info(
                "store_missing_new_variables",
                receiver=receiver_name,
                new_vars=sorted(missing_vars),
            )

    def _prepare_store_for_overwrite(
        self,
        session: ForkSession,
        receiver_name: str,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        existing_hashes: set[str],
        file_hash_map: dict[Path, str | None],
    ) -> None:
        """Remove epochs that will be overwritten and drop stale variables.

        Reads the existing group, masks out temporal ranges of files being
        overwritten, drops data_vars not present in the incoming batch,
        then rewrites the group with mode="w".
        """
        log = self._logger

        # 1. Read existing store data
        try:
            ds_store = xr.open_zarr(
                session.store, group=receiver_name, consolidated=False
            ).compute(
                scheduler="synchronous"
            )  # synchronous avoids Dask serialization error
        except KeyError, zarr.errors.GroupNotFoundError:
            return  # New group, nothing to prepare

        # 2. Collect epoch ranges to remove (files that exist and will be overwritten)
        epochs_to_remove = []
        for fname, ds in augmented_datasets:
            h = file_hash_map.get(fname)
            if h and h in existing_hashes:
                start = np.datetime64(ds.epoch.min().values)
                end = np.datetime64(ds.epoch.max().values)
                epochs_to_remove.append((start, end))

        if not epochs_to_remove:
            return  # Nothing to overwrite

        log.info(
            "prepare_overwrite",
            receiver=receiver_name,
            ranges_to_remove=len(epochs_to_remove),
        )

        # 3. Build combined mask: keep epochs NOT covered by any overwrite range
        epoch_vals = ds_store.epoch.values
        keep_mask = np.ones(len(epoch_vals), dtype=bool)
        for start, end in epochs_to_remove:
            keep_mask &= (epoch_vals < start) | (epoch_vals > end)

        ds_filtered = ds_store.isel(epoch=keep_mask)

        # 4. Drop stale variables not in current batch
        if augmented_datasets:
            _, first_ds = augmented_datasets[0]
            batch_vars = set(first_ds.data_vars)
            stale_vars = set(ds_filtered.data_vars) - batch_vars
            if stale_vars:
                log.warning(
                    "dropping_stale_variables",
                    receiver=receiver_name,
                    stale_vars=sorted(stale_vars),
                )
                ds_filtered = ds_filtered.drop_vars(stale_vars)

        # 5. Backup metadata, rewrite group, restore metadata
        metadata_backup = self.site.gnss_store.backup_metadata_table(
            receiver_name, session
        )

        ds_filtered = self.site.gnss_store._normalize_encodings(ds_filtered)

        if ds_filtered.sizes.get("epoch", 0) > 0:
            to_icechunk(ds_filtered, session, group=receiver_name, mode="w")
        else:
            # No epochs remain — write empty structure from first incoming dataset
            _, first_ds = augmented_datasets[0]
            empty = self.site.gnss_store._normalize_encodings(first_ds.isel(epoch=[]))
            to_icechunk(empty, session, group=receiver_name, mode="w")

        if metadata_backup is not None:
            self.site.gnss_store.restore_metadata_table(
                receiver_name, metadata_backup, session
            )

    def _check_existing_with_temporal_overlap(
        self,
        receiver_name: str,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        file_hash_map: dict[Path, str | None],
    ) -> set[str]:
        """Check for existing files by hash AND temporal overlap.

        Performs three checks:
        1. Hash match against store metadata (exact duplicate)
        2. Temporal overlap against store metadata (e.g. re-run)
        3. Intra-batch overlap (e.g. daily concat + 15-min sub-files
           in the same batch)

        Returns the union of all flagged hashes so the caller can treat
        them as ``exists=True``.
        """
        valid_hashes = [h for h in file_hash_map.values() if h]

        # Load the metadata table once and share it with both checks below
        # instead of each doing its own full-table read (dev/todo_later.md
        # §34 -- confirmed 2026-07-15 that batch_check duration tracks
        # metadata_rows almost exactly, so halving the reads halves that
        # cost directly). `None` means fresh store / no metadata yet.
        metadata_df = self.site.gnss_store.load_metadata_for_dedup(receiver_name)
        if metadata_df is None:
            existing_hashes: set[str] = set()
        else:
            existing_hashes = self.site.gnss_store.batch_check_existing(
                receiver_name, valid_hashes, metadata_df=metadata_df
            )

            # Check 2: temporal overlap against store metadata
            new_hashes = [h for h in valid_hashes if h not in existing_hashes]
            if new_hashes:
                file_intervals = []
                for fname, ds in augmented_datasets:
                    h = file_hash_map[fname]
                    if h and h not in existing_hashes:
                        file_intervals.append(
                            (
                                h,
                                np.datetime64(ds.epoch.min().values),
                                np.datetime64(ds.epoch.max().values),
                            )
                        )
                if file_intervals:
                    temporal_overlaps = self.site.gnss_store.check_temporal_overlaps(
                        receiver_name, file_intervals, metadata_df=metadata_df
                    )
                    existing_hashes |= temporal_overlaps

        # Check 3: intra-batch overlap detection
        # If a file's time range fully contains other files' ranges,
        # it's a concatenation file — flag it as redundant.
        intervals = []
        for fname, ds in augmented_datasets:
            h = file_hash_map[fname]
            if h and h not in existing_hashes:
                intervals.append(
                    (
                        h,
                        np.datetime64(ds.epoch.min().values),
                        np.datetime64(ds.epoch.max().values),
                        len(ds.epoch),
                    )
                )

        if len(intervals) > 1:
            intra_overlaps: set[str] = set()
            for i, (h_i, s_i, e_i, n_i) in enumerate(intervals):
                for j, (h_j, s_j, e_j, n_j) in enumerate(intervals):
                    if i == j:
                        continue
                    # Check if file i fully contains file j
                    if s_i <= s_j and e_i >= e_j:
                        # File i contains file j — flag the larger file
                        # (prefer keeping the smaller sub-files)
                        intra_overlaps.add(h_i)
                        self._logger.warning(
                            "intra_batch_overlap",
                            container_hash=h_i[:16],
                            container_epochs=n_i,
                            contained_hash=h_j[:16],
                            contained_epochs=n_j,
                            message="Skipping concatenation file that "
                            "contains sub-files in same batch",
                        )
                        break  # Once flagged, no need to check more
            existing_hashes |= intra_overlaps

        return existing_hashes

    def _append_to_icechunk(
        self,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        receiver_name: str,
        rinex_files: list[Path],
        aux_datasets: dict[Path, dict[str, xr.Dataset]] | None = None,
        sid_issues: dict[str, list[str]] | None = None,
        reader_format: str | None = None,
    ) -> set[str]:
        """Batch append with single commit.

        Returns the set of file hashes that were skipped due to dedup (already
        in the store). An empty set means all files were written successfully.
        Callers can use this to decide whether to build the daily dataset from
        in-memory parts (empty) or fall back to a store read (non-empty).

        This method:
        1. Opens ONE session for all data writes
        2. Uses only to_icechunk() within the session (no nested sessions)
        3. Makes ONE commit for all data
        4. Writes metadata separately after commit succeeds
        5. Writes any auxiliary datasets (e.g. SBF metadata) after commit
        """
        _ = rinex_files
        log = self._logger
        version = get_version_from_pyproject()

        t_start = time.time()

        self._icechunk_log.info(
            "batch_write_session_started",
            receiver=receiver_name,
            total_files=len(augmented_datasets),
            strategy="single_commit",
        )

        # STEP 1: Batch check which files exist
        log.info("Batch checking %s files...", len(augmented_datasets))
        t1 = time.time()

        self._icechunk_log.debug(
            "batch_check_started",
            receiver=receiver_name,
            files=len(augmented_datasets),
        )

        file_hash_map = {
            fname: ds.attrs.get("File Hash") for fname, ds in augmented_datasets
        }

        existing_hashes = self._check_existing_with_temporal_overlap(
            receiver_name, augmented_datasets, file_hash_map
        )

        t2 = time.time()
        self._icechunk_log.info(
            "batch_check_complete",
            receiver=receiver_name,
            duration_seconds=round(t2 - t1, 2),
            existing=len(existing_hashes),
            total=len(augmented_datasets),
            # Metadata-table row count at check time -- lets a future run
            # correlate batch_check duration against store growth directly
            # instead of assuming O(rows) scaling (dev/todo_later.md
            # perf-degradation investigation, 2026-07-14).
            metadata_rows=self.site.gnss_store.metadata_row_count(receiver_name),
        )
        log.info(
            "Batch check complete in %.2fs: %s/%s existing",
            t2 - t1,
            len(existing_hashes),
            len(augmented_datasets),
        )

        # STEP 2: Branch-stage-promote for overwrite; direct main for others
        is_overwrite = self._gnss_store_strategy == "overwrite"
        temp_branch = None

        # Timing for perf-degradation investigation (dev/perf_degradation_
        # findings_2026_07_15.md follow-up, 2026-07-18): batch_write_complete's
        # `timings` dict left several calls unaccounted for, so its residual
        # (duration_seconds - sum(timings)) grew 12x over a 63-min local-store
        # run and correlated r=0.95 with manifest/snapshot count without
        # pinning down which call. These four timers close that gap. Default
        # 0.0 for steps that don't run this batch (e.g. non-overwrite runs
        # skip branch_setup entirely).
        t_branch_setup = 0.0
        if is_overwrite:
            _t_branch0 = time.perf_counter()
            yyyydoy = self.matched_data_dirs.yyyydoy.to_str()
            temp_branch = f"overwrite_{receiver_name}_{yyyydoy}"
            current_snapshot = next(
                self.site.gnss_store.repo.ancestry(branch="main")
            ).id
            try:
                self.site.gnss_store.repo.create_branch(temp_branch, current_snapshot)
            except Exception:
                # Branch may exist from a failed previous run; delete and recreate
                self.site.gnss_store.repo.delete_branch(temp_branch)
                self.site.gnss_store.repo.create_branch(temp_branch, current_snapshot)
            log.info(
                "Created temp branch '%s' for overwrite (snapshot: %s...)",
                temp_branch,
                current_snapshot[:8],
            )
            branch = temp_branch
            t_branch_setup = time.perf_counter() - _t_branch0
        else:
            branch = "main"

        log.info("Opening Icechunk session...")
        t3 = time.time()
        with self.site.gnss_store.writable_session(branch) as session:
            groups = self.site.gnss_store.list_groups() or []
            t4 = time.time()
            log.info("Session opened in %.2fs", t4 - t3)

            # Fires on every batch after the group's first write -- this
            # opens the group via xr.open_zarr(), a candidate for O(manifest
            # count) cost as the store grows (see comment above).
            t_vars_consistency = 0.0
            if receiver_name in groups:
                _t_vars0 = time.perf_counter()
                self._check_store_vars_consistency(
                    session, receiver_name, augmented_datasets
                )
                t_vars_consistency = time.perf_counter() - _t_vars0

            # Prepare store for overwrite (remove old epochs, drop stale vars)
            t_overwrite_prep = 0.0
            if is_overwrite and receiver_name in groups:
                _t_ovr0 = time.perf_counter()
                self._prepare_store_for_overwrite(
                    session,
                    receiver_name,
                    augmented_datasets,
                    existing_hashes,
                    file_hash_map,
                )
                t_overwrite_prep = time.perf_counter() - _t_ovr0

            actions = {
                "initial": 0,
                "skipped": 0,
                "appended": 0,
                "written": 0,
                "overwritten": 0,
            }
            metadata_records = []  # Collect metadata to write before commit

            try:
                # STEP 3: Process all datasets using ONLY to_icechunk()
                log.info(
                    "Processing %s datasets...",
                    len(augmented_datasets),
                )
                t5 = time.time()
                file_append_seconds: list[float] = []
                total_epochs = 0
                total_nbytes = 0

                for idx, (fname, ds) in enumerate(augmented_datasets):
                    # Progress logging
                    if idx % 20 == 0 and idx > 0:
                        elapsed = time.time() - t5
                        rate = idx / elapsed if elapsed > 0 else 0
                        log.info(
                            "  Progress: %s/%s (%.1f files/s)",
                            idx,
                            len(augmented_datasets),
                            rate,
                        )

                    try:
                        rel_path = self.site.gnss_store.rel_path_for_commit(fname)
                        rinex_hash = file_hash_map[fname]

                        if not rinex_hash:
                            log.debug("No hash for %s, skipping", fname)
                            continue

                        # Get time range for metadata
                        start_epoch = np.datetime64(ds.epoch.min().values)
                        end_epoch = np.datetime64(ds.epoch.max().values)

                        # Fast hash check
                        exists = rinex_hash in existing_hashes

                        # Cleanse dataset
                        ds_clean = self.site.gnss_store._cleanse_dataset_attrs(
                            ds,
                        )
                        ds_clean = self.site.gnss_store._normalize_encodings(
                            ds_clean,
                        )

                        # Collect metadata for ALL files (write later)
                        metadata_records.append(
                            {
                                "fname": fname,
                                "rinex_hash": rinex_hash,
                                "start": start_epoch,
                                "end": end_epoch,
                                "dataset_attrs": ds.attrs.copy(),
                                "exists": exists,
                                "rel_path": rel_path,
                                "canonical_name": ds.attrs.get("canonical_name", ""),
                                "physical_path": ds.attrs.get(
                                    "physical_path", str(fname)
                                ),
                            }
                        )

                        # Handle data writes using ONLY to_icechunk() with our session
                        t_file = time.perf_counter()
                        action = "skipped"
                        match (exists, self._gnss_store_strategy):
                            case (False, _) if receiver_name not in groups:
                                # Initial group creation (first non-skipped file).
                                # encoding= fixes physical chunk shape to match
                                # chunk_strategies config (2026-07-18) -- Zarr
                                # fixes chunk shape at creation, and nothing
                                # previously applied config here, leaving it
                                # to Zarr's own default (see store.py's
                                # chunk_encoding_for docstring for the full
                                # investigation).
                                to_icechunk(
                                    ds_clean,
                                    session,
                                    group=receiver_name,
                                    encoding=self.site.gnss_store.chunk_encoding_for(
                                        ds_clean
                                    ),
                                )
                                groups.append(receiver_name)
                                actions["initial"] += 1
                                action = "initial"
                                log.debug("Initial: %s", rel_path)

                            case (True, "skip"):
                                # File exists, skip writing data
                                actions["skipped"] += 1
                                log.debug("Skipped: %s", rel_path)

                            case (True, "unsafe_append"):
                                # File exists but write again anyway -- no
                                # epoch-uniqueness check, see StorageConfig.
                                # gnss_store_strategy docstring for the risk.
                                to_icechunk(
                                    ds_clean,
                                    session,
                                    group=receiver_name,
                                    append_dim="epoch",
                                )
                                actions["appended"] += 1
                                action = "appended"
                                log.debug("Appended (unsafe): %s", rel_path)

                            case (False, _):
                                # New file, write it
                                to_icechunk(
                                    ds_clean,
                                    session,
                                    group=receiver_name,
                                    append_dim="epoch",
                                )
                                actions["written"] += 1
                                action = "written"
                                log.debug("Wrote: %s", rel_path)

                            case (True, "overwrite"):
                                # Old data already removed by _prepare_store_for_overwrite
                                to_icechunk(
                                    ds_clean,
                                    session,
                                    group=receiver_name,
                                    append_dim="epoch",
                                )
                                actions["overwritten"] += 1
                                action = "overwritten"
                                log.debug("Overwrote: %s", rel_path)

                            case _:
                                log.warning(
                                    "Unhandled strategy: exists=%s, strategy=%s for %s",
                                    exists,
                                    self._gnss_store_strategy,
                                    rel_path,
                                )
                                action = "unhandled"

                        # Per-file append timing (dev/todo_later.md perf-degradation
                        # investigation, 2026-07-14): breaks open the "process_data"
                        # aggregate below into per-file numbers so a future run can
                        # tell whether cost grows uniformly within a batch (session/
                        # manifest state) or is concentrated in specific files.
                        dt_file = time.perf_counter() - t_file
                        file_append_seconds.append(dt_file)
                        n_epochs = int(ds_clean.sizes.get("epoch", 0))
                        total_epochs += n_epochs
                        total_nbytes += int(ds_clean.nbytes)
                        self._icechunk_log.info(
                            "icechunk.file_append",
                            duration_seconds=round(dt_file, 4),
                            receiver=receiver_name,
                            date=str(self.matched_data_dirs.yyyydoy),
                            file=fname.name,
                            file_index=idx,
                            action=action,
                            n_epochs=n_epochs,
                            n_sids=int(ds_clean.sizes.get("sid", 0)),
                        )

                    except (OSError, RuntimeError, ValueError):  # fmt: skip
                        log.exception("Failed to process %s", fname.name)

                t6 = time.time()
                log.info("Dataset processing complete in %.2fs", t6 - t5)

                # STEP 4: Write metadata, then single commit for data + metadata
                summary = ", ".join(f"{k}={v}" for k, v in actions.items() if v > 0)
                commit_msg = (
                    f"[v{version}] {receiver_name} "
                    f"{self.matched_data_dirs.yyyydoy}: {summary}"
                )

                log.info(
                    "Writing metadata for %s files...",
                    len(metadata_records),
                )
                t9 = time.time()
                try:
                    self.site.gnss_store.append_metadata_bulk(
                        group_name=receiver_name,
                        rows=metadata_records,
                        session=session,
                    )
                except (OSError, RuntimeError, ValueError):  # fmt: skip
                    log.warning("Metadata write failed, committing data only")
                t10 = time.time()
                log.info("Metadata write complete in %.2fs", t10 - t9)

                log.info("Committing: %s", summary)
                t7 = time.time()
                _commit_meta: dict = {
                    "receiver": receiver_name,
                    "date": str(self.matched_data_dirs.yyyydoy),
                    "files": str(len(metadata_records)),
                }
                if metadata_records:
                    _commit_meta["start"] = str(
                        min(r["start"] for r in metadata_records)
                    )
                    _commit_meta["end"] = str(max(r["end"] for r in metadata_records))
                    _commit_meta["rinex_hashes"] = ",".join(
                        str(r["rinex_hash"])
                        for r in metadata_records
                        if r.get("rinex_hash")
                    )
                    _commit_meta["canonical_names"] = ",".join(
                        str(r["canonical_name"])
                        for r in metadata_records
                        if r.get("canonical_name")
                    )
                snapshot_id = session.commit(commit_msg, metadata=_commit_meta)
                t8 = time.time()
                log.info(
                    "Commit complete in %.2fs (snapshot: %s...)",
                    t8 - t7,
                    snapshot_id[:8],
                )

                # Retention keeper tag (dev/perf_degradation_findings_2026_
                # 07_15.md, Problem B) -- additive, inert, off by default.
                # Never fails the write: create_keeper_tag() swallows tag
                # name collisions itself.
                t_keeper_tag = 0.0
                if self._keeper_tags_enabled:
                    _t_keeper0 = time.perf_counter()
                    self.site.gnss_store.create_keeper_tag(
                        receiver_name,
                        str(self.matched_data_dirs.yyyydoy),
                        snapshot_id,
                    )
                    t_keeper_tag = time.perf_counter() - _t_keeper0

                # Cheap on-disk store-internal stats (manifest/snapshot/
                # transaction directory entry counts) sampled once per
                # batch -- a directional proxy for Icechunk-internal growth,
                # to test whether the write-side slowdown tracks manifest
                # count (dev/todo_later.md perf-degradation investigation,
                # 2026-07-14). Deliberately skips chunks/ (unbounded).
                t_stats = time.perf_counter()
                dir_counts = self.site.gnss_store.dir_entry_counts()
                t_store_stats = time.perf_counter() - t_stats
                self._icechunk_log.info(
                    "store_stats",
                    duration_seconds=round(t_store_stats, 4),
                    receiver=receiver_name,
                    date=str(self.matched_data_dirs.yyyydoy),
                    **dir_counts,
                )

                # GC is intentionally skipped here. Running garbage_collect() after
                # every commit performs a full reachability scan over all snapshots,
                # manifests, and chunk objects — cost grows O(n) per batch → O(n²)
                # over a multi-year backfill. Call store.expire_old_snapshots() or
                # store.maintenance() once after the pipeline completes instead.

                # Timing summary
                t_end = time.time()

                if file_append_seconds:
                    _sorted = sorted(file_append_seconds)
                    _n = len(_sorted)
                    process_data_per_file = {
                        "n": _n,
                        "mean": round(sum(_sorted) / _n, 4),
                        "p50": round(_sorted[_n // 2], 4),
                        "p95": round(_sorted[min(_n - 1, int(_n * 0.95))], 4),
                        "max": round(_sorted[-1], 4),
                        "first": round(file_append_seconds[0], 4),
                        "last": round(file_append_seconds[-1], 4),
                    }
                else:
                    process_data_per_file = {}

                self._icechunk_log.info(
                    "batch_write_complete",
                    receiver=receiver_name,
                    date=str(self.matched_data_dirs.yyyydoy),
                    snapshot_id=snapshot_id[:12],
                    total_files=len(augmented_datasets),
                    total_epochs=total_epochs,
                    total_nbytes=total_nbytes,
                    duration_seconds=round(t_end - t_start, 2),
                    timings={
                        "batch_check": round(t2 - t1, 2),
                        "branch_setup": round(t_branch_setup, 2),
                        "open_session": round(t4 - t3, 2),
                        "vars_consistency": round(t_vars_consistency, 2),
                        "overwrite_prep": round(t_overwrite_prep, 2),
                        "process_data": round(t6 - t5, 2),
                        "commit": round(t8 - t7, 2),
                        "metadata": round(t10 - t9, 2),
                        "keeper_tag": round(t_keeper_tag, 2),
                        "store_stats": round(t_store_stats, 2),
                    },
                    process_data_per_file=process_data_per_file,
                    actions=actions,
                    throughput_files_per_sec=round(
                        len(augmented_datasets) / (t_end - t_start), 2
                    ),
                )

                log.info("\nTIMING BREAKDOWN:")
                log.info("  Batch check:    %.2fs", t2 - t1)
                log.info("  Open session:   %.2fs", t4 - t3)
                log.info("  Process data:   %.2fs", t6 - t5)
                log.info("  Commit:         %.2fs", t8 - t7)
                log.info("  Metadata:       %.2fs", t10 - t9)
                log.info("  TOTAL:          %.2fs", t_end - t_start)

                log.info(
                    "Successfully processed %s files for '%s'",
                    len(augmented_datasets),
                    receiver_name,
                )

            except (OSError, RuntimeError, ValueError):  # fmt: skip
                log.exception("Batch append failed")
                raise

        # STEP 5: Set source_format root attr (once, idempotent)
        if self.site.gnss_store.source_format is None:
            reader_fmt = reader_format or self._reader_name
            try:
                self.site.gnss_store.set_root_attrs(
                    {"source_format": reader_fmt}, branch=branch
                )
                log.info("Set store source_format='%s'", reader_fmt)
            except Exception:
                log.warning("Failed to set source_format root attr")

        # STEP 5b: Write rich store metadata (once, on first ingest); on
        # subsequent ingests, re-snapshot the config and record any drift —
        # otherwise a store's config section silently freezes at whatever
        # was true on the very first ingest, forever (dev/todo_later.md §4).
        try:
            from canvod.store_metadata import (
                collect_config_snapshot,
                collect_metadata,
                metadata_exists,
                read_metadata,
                update_metadata,
                write_metadata,
            )

            store_path = self.site.gnss_store.store_path
            site_name = self.site.site_name

            # Find site config from CanvodConfig
            sites_cfg = self._config.sites
            site_cfg = None
            for sn, sc in sites_cfg.sites.items():
                if sn == site_name:
                    site_cfg = sc
                    break

            if site_cfg is not None:
                reader_fmt = reader_format or self._reader_name
                if not metadata_exists(store_path, branch=branch):
                    resources = self._config.processing.params.resolve_resources()
                    meta = collect_metadata(
                        config=self._config,
                        site_name=site_name,
                        site_config=site_cfg,
                        store_type="gnss_store",
                        source_format=reader_fmt,
                        store_path=store_path,
                        dask_workers=resources.get("n_workers"),
                        dask_threads_per_worker=resources.get("threads_per_worker"),
                    )
                    write_metadata(store_path, meta, branch=branch)
                    log.info("Wrote rich store metadata")
                else:
                    now = datetime.now(UTC).isoformat()
                    existing_meta = read_metadata(store_path, branch=branch)
                    new_snapshot = collect_config_snapshot(self._config)

                    history_entries = [
                        f"{now}: Ingested {len(augmented_datasets)}"
                        f" files for {receiver_name}"
                    ]
                    updates: dict[str, object] = {"temporal.updated": now}

                    drifted = (
                        new_snapshot.config_hash != existing_meta.config.config_hash
                    )
                    if drifted:
                        old_hash = (existing_meta.config.config_hash or "unknown")[:12]
                        new_hash = (new_snapshot.config_hash or "unknown")[:12]
                        history_entries.append(
                            f"{now}: Config changed ({old_hash} -> {new_hash})"
                        )
                        updates["config"] = new_snapshot.model_dump(mode="json")

                    # update_metadata() replaces (doesn't append to) list
                    # fields, so merge history here rather than in io.py —
                    # keeps that generic dotted-update helper's semantics
                    # unchanged for its other callers.
                    updates["summaries.history"] = [
                        *existing_meta.summaries.history,
                        *history_entries,
                    ]

                    update_metadata(store_path, updates, branch=branch)
                    log.info(
                        "Updated store metadata%s",
                        " (config drift detected)" if drifted else "",
                    )
        except Exception:
            log.debug(
                "canvod-store-metadata not available or write failed",
                exc_info=True,
            )

        # STEP 6: Write SBF metadata datasets (sbf_obs) per receiver
        # Each file produces its own sbf_obs dataset.  We write them
        # incrementally to the store (first=overwrite, rest=append) to
        # avoid an expensive xr.concat in memory.
        if aux_datasets:
            sbf_parts = [
                aux_dict["sbf_obs"]
                for aux_dict in aux_datasets.values()
                if "sbf_obs" in aux_dict
            ]
            if sbf_parts:
                try:
                    self.site.gnss_store.append_metadata_datasets(
                        sbf_parts, receiver_name, "sbf_obs", branch
                    )
                    n_epochs = sum(p.sizes.get("epoch", 0) for p in sbf_parts)
                    log.info(
                        "Wrote sbf_obs metadata for %s (%d parts, %d epochs)",
                        receiver_name,
                        len(sbf_parts),
                        n_epochs,
                    )
                except Exception:
                    log.warning(
                        "Failed to write sbf_obs for %s",
                        receiver_name,
                        exc_info=True,
                    )

        # Promote temp branch to main after successful commit
        if is_overwrite and temp_branch:
            try:
                new_tip = next(
                    self.site.gnss_store.repo.ancestry(branch=temp_branch)
                ).id
                self.site.gnss_store.repo.reset_branch("main", new_tip)
                log.info(
                    "Promoted %s to main (snapshot: %s...)",
                    temp_branch,
                    new_tip[:8],
                )
            finally:
                with contextlib.suppress(Exception):
                    self.site.gnss_store.repo.delete_branch(temp_branch)

        # Additive stage_timing for the performance dashboard's per-iteration
        # breakdown (reading/validating/augmenting/writing) -- reuses the
        # already-computed t_start rather than restructuring this function's
        # control flow into a stage_timer() context manager.
        log.info(
            "stage_timing",
            stage="writing",
            duration_seconds=round(time.time() - t_start, 2),
            status="ok",
            receiver=receiver_name,
            date_key=self.matched_data_dirs.yyyydoy.to_str(),
        )

        return existing_hashes

    def _resolve_receiver_paths(self, receiver_type: str) -> tuple[Path, str | None]:
        """Resolve paths and receiver name for receiver type.

        Parameters
        ----------
        receiver_type : str
            Type of receiver ('canopy' or 'reference')

        Returns
        -------
        tuple[Path, str | None]
            (rinex_dir, receiver_name)

        """
        if receiver_type == "canopy":
            rinex_dir = self.matched_data_dirs.canopy_data_dir
        elif receiver_type == "reference":
            rinex_dir = self.matched_data_dirs.reference_data_dir
        else:
            msg = f"Unknown receiver type: {receiver_type}"
            raise ValueError(msg)

        # Get receiver name from site configuration
        receiver_name = None
        for name, config in self.site.active_receivers.items():
            if config.get("type") == receiver_type:
                receiver_name = name
                break

        return rinex_dir, receiver_name

    def parsed_rinex_data_gen_2_receivers(
        self,
        keep_vars: list[str] | None = None,
        receiver_types: list[str] | None = None,
    ) -> Generator[xr.Dataset]:
        """Generate datasets from RINEX files and append to Icechunk stores.

        Pipeline:
        1. Preprocess aux data ONCE per day with Hermite splines → Zarr
        2. Compute receiver position ONCE (shared for all receivers)
        3. For each receiver type (canopy, reference):
           a. Get list of RINEX files
           b. Parallel process via ProcessPoolExecutor
           c. Each worker: read RINEX + slice Zarr + compute φ, θ, r
           d. Sequential append to Icechunk store
           e. Yield final daily dataset

        Parameters
        ----------
        keep_vars : List[str], optional
            Variables to keep in datasets (default: from globals)
        receiver_types : List[str], optional
            Receiver types to process (default: ['canopy', 'reference'])

        Yields
        ------
        xr.Dataset
            Processed and augmented daily dataset for each receiver type

        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        if keep_vars is None:
            keep_vars = load_config().processing.params.keep_gnss_observables

        self._logger.info(
            "Starting RINEX processing pipeline for: %s",
            receiver_types,
        )

        # Pre-flight: Get canopy files to infer sampling and compute position
        canopy_dir = self.matched_data_dirs.canopy_data_dir
        canopy_files = self._get_rinex_files(canopy_dir)
        if not canopy_files:
            msg = "No canopy RINEX files found - cannot infer sampling rate"
            raise ValueError(msg)

        # ====================================================================
        # STEP 1: Preprocess aux data ONCE per day with Hermite splines
        # (routes through _ensure_aux_data_preprocessed, dev/todo_later.md
        # §44 -- this call site used to duplicate the rmtree+rebuild logic
        # inline, bypassing the shared-cache lookup entirely)
        # ====================================================================
        self._logger.info("Preprocessing aux data with Hermite splines (once per day)")
        aux_zarr_path, aux_group = self._ensure_aux_data_preprocessed(
            canopy_files, self.matched_data_dirs.yyyydoy.to_str()
        )

        # ====================================================================
        # STEP 2: Compute receiver position
        # ====================================================================
        position_mode = self._config.processing.params.receiver_position_mode
        first_rnx = self._make_reader(canopy_files[0])
        first_ds = first_rnx.to_ds(keep_data_vars=[], write_global_attrs=True)
        shared_position = ECEFPosition.from_ds_metadata(first_ds)

        if position_mode == "per_receiver":
            self._logger.warning(
                "receiver_position_mode='per_receiver': each receiver will use "
                "its own RINEX header position. This breaks direct SNR "
                "comparability between receivers."
            )
        else:
            self._logger.info(
                "Computed receiver position (shared): %s",
                shared_position,
            )

        # ====================================================================
        # STEP 3: Process each receiver type
        # ====================================================================
        for receiver_type in receiver_types:
            self._logger.info("Processing receiver type: %s", receiver_type)

            # 3a. Resolve directories and receiver name
            rinex_dir, receiver_name = self._resolve_receiver_paths(receiver_type)

            if not receiver_name:
                self._logger.warning(
                    "No configured receiver for %s, skipping",
                    receiver_type,
                )
                continue

            # 3b. Get RINEX files for this receiver type
            rinex_files = self._get_rinex_files(rinex_dir)
            if not rinex_files:
                self._logger.warning(
                    "No RINEX files found in %s",
                    rinex_dir,
                )
                continue

            self._logger.info(
                "Found %s RINEX files to process",
                len(rinex_files),
            )

            # 3b'. Determine receiver position for this receiver
            if position_mode == "per_receiver":
                receiver_position = self._compute_receiver_position(
                    rinex_files, receiver_name
                )
                if receiver_position is None:
                    self._logger.error(
                        "Could not compute position for %s, skipping",
                        receiver_name,
                    )
                    continue
            else:
                receiver_position = shared_position

            # 3c. Parallel process via ProcessPoolExecutor
            augmented_datasets, aux_datasets, sid_issues = self._parallel_process_rinex(
                rinex_files=rinex_files,
                keep_vars=keep_vars,
                aux_zarr_path=aux_zarr_path,
                receiver_position=receiver_position,
                receiver_type=receiver_name,
                aux_group=aux_group,
            )

            # 3d. Sequential append to Icechunk store
            self._append_to_icechunk(
                augmented_datasets=augmented_datasets,
                receiver_name=receiver_name,
                rinex_files=rinex_files,
                aux_datasets=aux_datasets,
                sid_issues=sid_issues,
            )

            # 3e. Yield final daily dataset
            # Read back from store to get complete daily dataset
            date_obj = self.matched_data_dirs.yyyydoy.date
            assert date_obj is not None, "yyyydoy.date must not be None"
            start_time = datetime.combine(date_obj, datetime.min.time())
            end_time = datetime.combine(date_obj, datetime.max.time())
            time_range = (start_time, end_time)

            daily_dataset = self.site.read_receiver_data(
                receiver_name=receiver_name, time_range=time_range
            )

            self._logger.info(
                "Yielding daily dataset for %s ('%s'): %s",
                receiver_type,
                receiver_name,
                dict(daily_dataset.sizes),
            )

            yield daily_dataset

    def prepare_batch_tasks(
        self,
        keep_vars: list[str] | None,
        receiver_configs: list[tuple[str, str, Path, Path | None, str]],
    ) -> tuple[list[tuple], list[tuple[str, list[Path]]]]:
        """Prepare aux Zarr and task descriptors for flat loky submission.

        Performs Phase 1 work for one DOY without submitting to loky:
        normalize configs, preprocess aux data, compute positions, and
        build a flat list of task arguments.

        Parameters
        ----------
        keep_vars : list[str] | None
            Variables to keep in datasets.
        receiver_configs : list[tuple[str, str, Path, Path | None, str]]
            ``(receiver_name, receiver_type, data_dir, position_data_dir, reader_format)``
            tuples.

        Returns
        -------
        task_descriptors : list[tuple]
            Each tuple's last element is a bool marking its shape: ``False``
            tuples carry ``preprocess_with_hermite_aux`` args (one per
            (file, receiver) pair); ``True`` tuples carry
            ``preprocess_reference_with_hermite_aux_fanout`` args -- one per
            physical reference file, bundling every paired canopy's position
            into a single ``canopy_positions`` dict so the file is only
            parsed once regardless of how many canopies it's paired against
            (dev/todo_later.md §47). Element 4 is always a lane key (either
            the receiver/pairing name or a per-reference-file lane key) for
            ``_interleave_by_receiver``.
        receiver_file_map : list[tuple[str, list[Path]]]
            ``(receiver_name, rinex_files)`` for each receiver/pairing —
            needed for the Icechunk write phase.

        """
        t_batch_start = time.perf_counter()
        if keep_vars is None:
            keep_vars = self._config.processing.params.keep_gnss_observables

        # Get first receiver files to infer sampling rate for aux preprocessing
        first_receiver_name, _first_type, first_data_dir, _, first_fmt = (
            receiver_configs[0]
        )
        first_files = self._get_rinex_files(first_data_dir, first_fmt)

        if not first_files:
            msg = (
                f"No RINEX files found for {first_receiver_name} - "
                "cannot infer sampling rate"
            )
            self._logger.error(
                "prepare_batch_failed",
                reason="no_rinex_files",
                receiver=first_receiver_name,
            )
            raise ValueError(msg)

        date_str = self.matched_data_dirs.yyyydoy.to_str()
        if self.use_sbf_geometry:
            aux_zarr_path = None
            aux_group = None
            self._logger.info(
                "aux_preprocessing_skipped",
                reason="ephemeris_source=broadcast",
            )
        else:
            aux_zarr_path, aux_group = self._ensure_aux_data_preprocessed(
                first_files, date_str, reader_format=first_fmt
            )
        t_aux_done = time.perf_counter()

        task_descriptors: list[tuple] = []
        receiver_file_map: list[tuple[str, list[Path]]] = []

        # In broadcast + shared position mode, build a mapping from
        # timestamp suffix → canopy file path so reference tasks can
        # read the matching canopy file's sbf_obs on the fly
        canopy_file_by_timestamp: dict[str, Path] | None = None
        canopy_reader_fmt: str | None = None
        position_mode = self._config.processing.params.receiver_position_mode
        if self.use_sbf_geometry and position_mode == "shared":
            for rc_name, rc_type, rc_dir, _, rc_fmt in receiver_configs:
                if rc_type == "canopy":
                    canopy_files = self._get_rinex_files(rc_dir, rc_fmt)
                    if canopy_files:
                        import re

                        canopy_file_by_timestamp = {}
                        canopy_reader_fmt = rc_fmt or self._reader_name
                        for cf in canopy_files:
                            # Extract timestamp: last chars before extension
                            # e.g. "ract001a15.25_" → "a15"
                            m = re.search(r"([a-x]\d{2})\.\d{2}_$", cf.name)
                            if m:
                                canopy_file_by_timestamp[m.group(1)] = cf
                        self._logger.info(
                            "canopy_broadcast_file_index_built",
                            canopy_files=len(canopy_file_by_timestamp),
                        )
                    break

        # Reference receivers paired against multiple canopies share the same
        # physical file set (same data_dir/reader_format) -- group them so
        # each file gets one fan-out task instead of one task per (file,
        # pairing) below (dev/todo_later.md §47). Only applies to the
        # Hermite-aux path: use_sbf_geometry pairs a reference with its own
        # SBF geometry per canopy via broadcast_canopy_file, a separate
        # mechanism left untouched.
        reference_groups: dict[tuple[Path, str], list[tuple[str, Path | None]]] = {}
        if not self.use_sbf_geometry:
            for (
                receiver_name,
                _receiver_type,
                data_dir,
                position_data_dir,
                reader_format,
            ) in receiver_configs:
                if _receiver_type == "reference":
                    reference_groups.setdefault((data_dir, reader_format), []).append(
                        (receiver_name, position_data_dir)
                    )
        fanned_out_receiver_names = {
            receiver_name
            for pairings in reference_groups.values()
            for receiver_name, _pos_dir in pairings
        }

        for (
            receiver_name,
            _receiver_type,
            data_dir,
            position_data_dir,
            reader_format,
        ) in receiver_configs:
            if receiver_name in fanned_out_receiver_names:
                continue  # handled by the reference fan-out pass below

            rinex_files = self._get_rinex_files(data_dir, reader_format)
            if not rinex_files:
                self._logger.warning(
                    "no_rinex_files_found",
                    receiver=receiver_name,
                    data_dir=str(data_dir),
                    reader_format=reader_format,
                )
                continue

            if position_mode == "per_receiver":
                position_files = rinex_files
                self._logger.warning(
                    "receiver_position_mode='per_receiver': using %s's own "
                    "position (breaks direct SNR comparability)",
                    receiver_name,
                )
            else:
                position_files = (
                    self._get_rinex_files(position_data_dir, reader_format)
                    if position_data_dir
                    else rinex_files
                )
            t_pos_start = time.perf_counter()
            receiver_position = self._compute_receiver_position(
                position_files, receiver_name, reader_format=reader_format
            )
            t_pos_end = time.perf_counter()
            self._logger.info(
                "position_computed",
                receiver=receiver_name,
                position_seconds=round(t_pos_end - t_pos_start, 4),
                success=receiver_position is not None,
            )
            if receiver_position is None:
                continue

            receiver_file_map.append((receiver_name, rinex_files))

            effective_reader = reader_format or self._reader_name
            for rnx_file in rinex_files:
                # For reference receivers in broadcast + shared mode,
                # find matching canopy file by timestamp suffix
                broadcast_canopy_file = None
                if (
                    _receiver_type == "reference"
                    and canopy_file_by_timestamp is not None
                ):
                    import re

                    m = re.search(r"([a-x]\d{2})\.\d{2}_$", rnx_file.name)
                    if m:
                        broadcast_canopy_file = canopy_file_by_timestamp.get(m.group(1))

                task_descriptors.append(
                    (
                        rnx_file,
                        keep_vars,
                        aux_zarr_path,
                        receiver_position,
                        receiver_name,
                        self.keep_sids,
                        effective_reader,
                        self.use_sbf_geometry,
                        False,  # store_radial_distance
                        broadcast_canopy_file,
                        canopy_reader_fmt,
                        # NOTE: broadcast_canopy_file/canopy_reader_fmt above
                        # are already positionally misaligned against
                        # preprocess_with_hermite_aux's store_sbf_raw_
                        # observables/broadcast_canopy_file params (a
                        # pre-existing, dormant bug outside use_sbf_geometry=
                        # True + shared-position-mode -- confirmed, not
                        # fixed here). The two explicit values below exist
                        # only to preserve that exact pre-existing (buggy)
                        # positional mapping unchanged while correctly
                        # placing aux_group in ITS real parameter slot --
                        # without them aux_group silently lands on
                        # broadcast_canopy_fmt's slot instead and never
                        # reaches the function at all.
                        None,  # broadcast_canopy_fmt (preserves prior default)
                        True,  # pad_global_sid (preserves prior default)
                        aux_group,
                        False,  # is_reference_fanout
                    )
                )

        # Reference fan-out pass: one task per physical reference file,
        # bundling every paired canopy's position so the file is parsed once.
        for (data_dir, reader_format), pairings in reference_groups.items():
            rinex_files = self._get_rinex_files(data_dir, reader_format)
            if not rinex_files:
                self._logger.warning(
                    "no_rinex_files_found",
                    receiver=[name for name, _pos_dir in pairings],
                    data_dir=str(data_dir),
                    reader_format=reader_format,
                )
                continue

            canopy_positions: dict[str, ECEFPosition] = {}
            for receiver_name, position_data_dir in pairings:
                if position_mode == "per_receiver":
                    position_files = rinex_files
                    self._logger.warning(
                        "receiver_position_mode='per_receiver': using %s's own "
                        "position (breaks direct SNR comparability)",
                        receiver_name,
                    )
                else:
                    position_files = (
                        self._get_rinex_files(position_data_dir, reader_format)
                        if position_data_dir
                        else rinex_files
                    )
                t_pos_start = time.perf_counter()
                receiver_position = self._compute_receiver_position(
                    position_files, receiver_name, reader_format=reader_format
                )
                t_pos_end = time.perf_counter()
                self._logger.info(
                    "position_computed",
                    receiver=receiver_name,
                    position_seconds=round(t_pos_end - t_pos_start, 4),
                    success=receiver_position is not None,
                )
                if receiver_position is None:
                    continue
                canopy_positions[receiver_name] = receiver_position
                receiver_file_map.append((receiver_name, rinex_files))

            if not canopy_positions:
                continue

            effective_reader = reader_format or self._reader_name
            reference_lane_key = f"reference:{data_dir.name}"
            for rnx_file in rinex_files:
                task_descriptors.append(
                    (
                        rnx_file,
                        keep_vars,
                        aux_zarr_path,
                        canopy_positions,
                        reference_lane_key,
                        self.keep_sids,
                        effective_reader,
                        False,  # store_radial_distance (matches non-fanout path)
                        True,  # store_sbf_raw_observables
                        True,  # pad_global_sid
                        aux_group,
                        True,  # is_reference_fanout
                    )
                )

        t_batch_end = time.perf_counter()
        self._logger.info(
            "prepare_batch_tasks_complete",
            date=date_str,
            total_seconds=round(t_batch_end - t_batch_start, 2),
            aux_seconds=round(t_aux_done - t_batch_start, 2),
            receivers_prepared=len(receiver_file_map),
            total_tasks=len(task_descriptors),
        )
        return task_descriptors, receiver_file_map

    def parsed_rinex_data_gen(
        self,
        keep_vars: list[str] | None = None,
        receiver_configs: list[tuple[str, str, Path]]
        | list[tuple[str, str, Path, Path | None]]
        | list[tuple[str, str, Path, Path | None, str]]
        | None = None,
    ) -> Generator[tuple[str, xr.Dataset, float]]:
        """Generate datasets from RINEX files and append to Icechunk stores.

        Pipeline:
        1. Preprocess aux data ONCE per day with Hermite splines → Zarr
        2. For each receiver:
        a. Compute receiver position (from own files or position_data_dir)
        b. Parallel process RINEX files via ProcessPoolExecutor
        c. Append to Icechunk store with receiver_name as group
        d. Yield final daily dataset

        Parameters
        ----------
        keep_vars : list[str], optional
            Variables to keep in datasets (default: from globals)
        receiver_configs : list[tuple], optional
            List of (receiver_name, receiver_type, data_dir),
            (receiver_name, receiver_type, data_dir, position_data_dir), or
            (receiver_name, receiver_type, data_dir, position_data_dir, reader_format)
            tuples.
            When position_data_dir is provided, the receiver position is
            computed from files in that directory instead of data_dir.
            If None, uses default behavior with matched_data_dirs.

        Yields
        ------
        xr.Dataset
            Processed and augmented daily dataset for each receiver

        """
        if receiver_configs is None:
            receiver_configs = self._get_default_receiver_configs()

        # Normalize to 5-tuples
        normalized_configs: list[tuple[str, str, Path, Path | None, str]] = []
        for cfg in receiver_configs:
            if len(cfg) == 3:
                normalized_configs.append((*cfg, None, self._reader_name))
            elif len(cfg) == 4:
                normalized_configs.append((*cfg, self._reader_name))
            else:
                normalized_configs.append(cfg)

        if keep_vars is None:
            keep_vars = load_config().processing.params.keep_gnss_observables

        pipeline_start = time.perf_counter()
        self._logger.info(
            "rinex_pipeline_started",
            receivers=len(normalized_configs),
            date=self.matched_data_dirs.yyyydoy.to_str(),
            keep_vars=keep_vars,
        )

        # ====================================================================
        # STEP 1: Preprocess aux data ONCE per day with Hermite splines
        # ====================================================================
        # Get first receiver files to infer sampling rate
        first_receiver_name, _first_receiver_type, first_data_dir, _, first_fmt = (
            normalized_configs[0]
        )
        first_files = self._get_rinex_files(first_data_dir, first_fmt)

        if not first_files:
            msg = (
                f"No RINEX files found for {first_receiver_name} - "
                "cannot infer sampling rate"
            )
            self._logger.error(
                "pipeline_failed",
                reason="no_rinex_files",
                receiver=first_receiver_name,
            )
            raise ValueError(msg)

        date_str = self.matched_data_dirs.yyyydoy.to_str()
        if self.use_sbf_geometry:
            aux_zarr_path = None
            aux_group = None
        else:
            aux_zarr_path, aux_group = self._ensure_aux_data_preprocessed(
                first_files, date_str, reader_format=first_fmt
            )

        # ====================================================================
        # PHASE 0.5 — file discovery upfront (one pass, keyed by (dir, fmt))
        # ====================================================================
        files_by_dir: dict = {}
        skipped: set = set()

        assert len({c[0] for c in normalized_configs}) == len(normalized_configs), (
            "Duplicate receiver names in normalized_configs"
        )

        for name, rtype, data_dir, pos_dir, fmt in normalized_configs:
            key = (data_dir, fmt)
            if key not in files_by_dir:
                files_by_dir[key] = self._get_rinex_files(data_dir, fmt)
            if not files_by_dir[key]:
                self._logger.warning(
                    "no_rinex_files_found",
                    receiver=name,
                    data_dir=str(data_dir),
                    reader_format=fmt,
                )
                skipped.add(name)

        # ====================================================================
        # PHASE 1 — resolve all receiver positions upfront
        # ====================================================================
        active_configs = [c for c in normalized_configs if c[0] not in skipped]
        # Build position-source files dict (may include position_data_dir entries)
        pos_files: dict = dict(files_by_dir)
        for name, rtype, data_dir, position_data_dir, fmt in active_configs:
            if position_data_dir is not None:
                key = (position_data_dir, fmt)
                if key not in pos_files:
                    pos_files[key] = self._get_rinex_files(position_data_dir, fmt)

        positions = self._resolve_receiver_positions(active_configs, pos_files)
        for name, pos in positions.items():
            if pos is None:
                skipped.add(name)

        # ====================================================================
        # PHASE 2 — parallel RINEX compute
        # ====================================================================
        wave_a, wave_b, parse_owner = self._build_compute_waves(
            normalized_configs, skipped
        )

        total_cores = self.n_max_workers or os.cpu_count() or 1
        outer_workers = min(len(wave_a), total_cores) if wave_a else 1
        inner_workers = max(1, total_cores // max(1, outer_workers))

        per_receiver_results: dict = {}  # name -> (augmented, aux_datasets, sid_issues)
        compute_durations: dict = {}  # name -> float (seconds)
        failed_dirs: set = set()

        def _parse_job(job_name, data_dir, fmt):
            t = time.perf_counter()
            result = self._parallel_process_rinex(
                rinex_files=files_by_dir[(data_dir, fmt)],
                keep_vars=keep_vars,
                aux_zarr_path=aux_zarr_path,  # ty: ignore[invalid-argument-type]
                receiver_position=positions[job_name],
                receiver_type=job_name,
                reader_format=fmt,
                show_progress=(len(wave_a) == 1),
                pool_workers=inner_workers if len(wave_a) > 1 else None,
                aux_group=aux_group,
            )
            return result, time.perf_counter() - t

        # Wave A: parse (one job per unique data_dir)
        if len(wave_a) <= 1:
            # Single receiver — run inline, full pool width, progress bar on
            for name, data_dir, fmt in wave_a:
                self._logger.info(
                    "receiver_processing_started",
                    receiver=name,
                    receiver_type="canopy",
                    data_dir=str(data_dir),
                )
                try:
                    (aug, aux_ds, sid_iss), dur = _parse_job(name, data_dir, fmt)
                    per_receiver_results[name] = (aug, aux_ds, sid_iss)
                    compute_durations[name] = dur
                except Exception as e:
                    self._logger.error(
                        "receiver_parse_failed",
                        receiver=name,
                        error=str(e),
                    )
                    failed_dirs.add((data_dir, fmt))
        else:
            with ThreadPoolExecutor(max_workers=outer_workers) as tpe:
                futs = {}
                for name, data_dir, fmt in wave_a:
                    self._logger.info(
                        "receiver_processing_started",
                        receiver=name,
                        receiver_type="parallel",
                        data_dir=str(data_dir),
                    )
                    futs[tpe.submit(_parse_job, name, data_dir, fmt)] = (
                        name,
                        data_dir,
                        fmt,
                    )
                for fut in as_completed(futs):
                    name, data_dir, fmt = futs[fut]
                    try:
                        (aug, aux_ds, sid_iss), dur = fut.result()
                        per_receiver_results[name] = (aug, aux_ds, sid_iss)
                        compute_durations[name] = dur
                    except Exception as e:
                        self._logger.error(
                            "receiver_parse_failed",
                            receiver=name,
                            error=str(e),
                        )
                        failed_dirs.add((data_dir, fmt))

        # Mark all receivers whose dir failed
        for name, rtype, data_dir, _pos, fmt in normalized_configs:
            if (data_dir, fmt) in failed_dirs and name not in skipped:
                skipped.add(name)

        # Wave B: SCS recompute from cached parse results
        recompute_jobs = [
            (name, data_dir, fmt)
            for name, data_dir, fmt in wave_b
            if name not in skipped and (data_dir, fmt) not in failed_dirs
        ]
        if recompute_jobs:

            def _recompute_job(job_name, data_dir, fmt):
                owner = parse_owner[(data_dir, fmt)]
                cached_aug, _, _ = per_receiver_results[owner]
                self._logger.info(
                    "recomputing_scs_from_cache",
                    receiver=job_name,
                    cached_files=len(cached_aug),
                    new_position=str(positions[job_name]),
                )
                t = time.perf_counter()
                result = self._recompute_scs_for_position(
                    cached_aug, aux_zarr_path, positions[job_name]
                )
                return result, time.perf_counter() - t

            if len(recompute_jobs) <= 1:
                for name, data_dir, fmt in recompute_jobs:
                    try:
                        aug, dur = _recompute_job(name, data_dir, fmt)
                        per_receiver_results[name] = (aug, None, None)
                        compute_durations[name] = dur
                    except Exception as e:
                        self._logger.error(
                            "scs_recompute_failed",
                            receiver=name,
                            error=str(e),
                        )
                        skipped.add(name)
            else:
                with ThreadPoolExecutor(
                    max_workers=min(len(recompute_jobs), total_cores)
                ) as tpe:
                    futs = {
                        tpe.submit(_recompute_job, n, d, f): (n, d, f)
                        for n, d, f in recompute_jobs
                    }
                    for fut in as_completed(futs):
                        name, data_dir, fmt = futs[fut]
                        try:
                            aug, dur = fut.result()
                            per_receiver_results[name] = (aug, None, None)
                            compute_durations[name] = dur
                        except Exception as e:
                            self._logger.error(
                                "scs_recompute_failed",
                                receiver=name,
                                error=str(e),
                            )
                            skipped.add(name)

        # ====================================================================
        # PHASE 3 — sequential writes + yields (deterministic, original order)
        # ====================================================================
        date_obj = self.matched_data_dirs.yyyydoy.date
        assert date_obj is not None, "yyyydoy.date must not be None"
        start_time = datetime.combine(date_obj, datetime.min.time())
        end_time = datetime.combine(date_obj, datetime.max.time())
        time_range = (start_time, end_time)

        n_written = 0
        for name, rtype, data_dir, _pos, fmt in normalized_configs:
            if name in skipped:
                continue
            augmented, aux_datasets, sid_issues = per_receiver_results[name]
            rinex_files = files_by_dir[(data_dir, fmt)]

            t_write_start = time.perf_counter()
            self._append_to_icechunk(
                augmented_datasets=augmented,
                receiver_name=name,
                rinex_files=rinex_files,
                aux_datasets=aux_datasets,
                sid_issues=sid_issues,
                reader_format=fmt,
            )
            t_write_end = time.perf_counter()

            t_read_start = time.perf_counter()
            daily_dataset = self.site.read_receiver_data(
                receiver_name=name, time_range=time_range
            )
            t_read_end = time.perf_counter()

            compute_s = compute_durations.get(name, 0.0)
            total_s = (
                compute_s + (t_write_end - t_write_start) + (t_read_end - t_read_start)
            )
            self._logger.info(
                "receiver_processing_complete",
                receiver=name,
                total_seconds=round(total_s, 2),
                rinex_parallel_seconds=round(compute_s, 2),
                icechunk_write_seconds=round(t_write_end - t_write_start, 2),
                store_readback_seconds=round(t_read_end - t_read_start, 2),
                dataset_size=dict(daily_dataset.sizes),
                epochs=len(daily_dataset.epoch) if "epoch" in daily_dataset.dims else 0,
            )
            n_written += 1
            yield name, daily_dataset, total_s

        self._logger.info(
            "rinex_pipeline_complete",
            date=self.matched_data_dirs.yyyydoy.to_str(),
            receivers_written=n_written,
            receivers_skipped=len(skipped),
        )

    def _get_default_receiver_configs(
        self,
    ) -> list[tuple[str, str, Path, Path | None]]:
        """Get default receiver configs from matched_data_dirs.

        Returns a list of (store_group_name, receiver_type, data_dir,
        position_data_dir) tuples. For canopy receivers, position_data_dir
        is None (use own files). For reference receivers, one entry is
        created per canopy in scs_from, with position_data_dir pointing
        to the canopy's RINEX directory.

        Returns
        -------
        list[tuple[str, str, Path, Path | None]]
            Receiver processing configurations.
        """
        configs: list[tuple[str, str, Path, Path | None]] = []
        site_config = self.site._site_config

        # Collect canopy data dirs for resolving position sources
        canopy_data_dirs: dict[str, Path] = {}
        base_path = site_config.get_base_path()

        _yydoy = self.matched_data_dirs.yyyydoy.yydoy
        assert _yydoy is not None, "yyyydoy.yydoy must not be None"
        for name, cfg in site_config.receivers.items():
            if cfg.type == "canopy":
                canopy_data_dirs[name] = base_path / cfg.directory / _yydoy

        # Add all canopy receivers (each uses own position)
        for name, cfg in site_config.receivers.items():
            if cfg.type == "canopy" and name in canopy_data_dirs:
                configs.append((name, "canopy", canopy_data_dirs[name], None))

        # Add reference receivers — one entry per canopy in paired_canopies
        for name, cfg in site_config.receivers.items():
            if cfg.type != "reference":
                continue
            ref_data_dir = base_path / cfg.directory / _yydoy
            canopy_names = site_config.resolve_paired_canopies(name)
            for canopy_name in canopy_names:
                store_group = f"{name}_{canopy_name}"
                position_dir = canopy_data_dirs.get(canopy_name)
                configs.append((store_group, "reference", ref_data_dir, position_dir))

        return configs

    def should_skip_day(
        self,
        receiver_types: list[str] | None = None,
        completeness_threshold: float = 1,
    ) -> tuple[bool, dict]:
        """Check if this day should be skipped based on existing data coverage.

        Parameters
        ----------
        receiver_types : list[str], optional
            Receiver types to check. Defaults to ['canopy', 'reference']
        completeness_threshold : float
            Fraction of expected epochs (default 0.95 = 95%)

        Returns
        -------
        tuple[bool, dict]
            (should_skip, coverage_info) where coverage_info contains details
            per receiver.

        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        # Expected epochs for 24h at 30s sampling
        expected_epochs = int(24 * 3600 / 30)  # 2880
        required_epochs = int(expected_epochs * completeness_threshold)

        # Get datetime objects from YYYYDOY.date
        yyyydoy_date = self.matched_data_dirs.yyyydoy.date
        assert yyyydoy_date is not None, "yyyydoy.date must not be None"
        day_start = np.datetime64(
            datetime.combine(yyyydoy_date, dt_time.min),
            "ns",
        )
        day_end = np.datetime64(
            datetime.combine(yyyydoy_date, dt_time.max),
            "ns",
        )

        coverage_info = {}

        for receiver_type in receiver_types:
            # Get receiver name
            receiver_name = None
            for name, config in self.site.active_receivers.items():
                if config.get("type") == receiver_type:
                    receiver_name = name
                    break

            if not receiver_name:
                coverage_info[receiver_type] = {
                    "exists": False,
                    "reason": "No receiver configured",
                }
                return False, coverage_info

            try:
                # Read metadata table
                with self.site.gnss_store.readonly_session("main") as session:
                    zmeta = zarr.open_group(session.store, mode="r")[
                        f"{receiver_name}/metadata/table"
                    ]
                    data = {col: zmeta[col][:] for col in zmeta.array_keys()}  # ty: ignore[invalid-argument-type, not-subscriptable, unresolved-attribute]
                    df = pl.DataFrame(data)

                # Cast datetime columns
                df = df.with_columns(
                    [
                        pl.col("start").cast(pl.Datetime("ns")),
                        pl.col("end").cast(pl.Datetime("ns")),
                    ]
                )

                # Filter to this day
                day_rows = df.filter(
                    (pl.col("start") >= day_start) & (pl.col("end") <= day_end)  # ty: ignore[invalid-argument-type]
                )

                if day_rows.is_empty():
                    coverage_info[receiver_type] = {
                        "exists": False,
                        "epochs": 0,
                        "expected": expected_epochs,
                        "percent": 0.0,
                    }
                    return False, coverage_info

                # Calculate total epochs
                day_rows = day_rows.with_columns(
                    [
                        (
                            (pl.col("end") - pl.col("start")).dt.total_seconds() / 30
                        ).alias("n_epochs")
                    ]
                )

                total_epochs = int(day_rows["n_epochs"].sum())
                percent = total_epochs / expected_epochs * 100

                coverage_info[receiver_type] = {
                    "exists": True,
                    "epochs": total_epochs,
                    "expected": expected_epochs,
                    "percent": percent,
                    "complete": total_epochs >= required_epochs,
                }

                if total_epochs < required_epochs:
                    return False, coverage_info

            except (KeyError, OSError, RuntimeError, ValueError) as e:
                coverage_info[receiver_type] = {
                    "exists": False,
                    "reason": str(e),
                    "epochs": 0,
                    "expected": expected_epochs,
                    "percent": 0.0,
                }
                return False, coverage_info

        # All receivers are complete
        return True, coverage_info

    def __repr__(self) -> str:
        return (
            "RinexDataProcessor("
            f"date={self.matched_data_dirs.yyyydoy.to_str()}, "
            f"site={self.site.site_name}, "
            f"aux_pipeline={self.aux_pipeline})"
        )


class DistributedRinexDataProcessor(RinexDataProcessor):
    """Under development. Use with caution.

    In `MyIcechunkStore`, attrs `MyIcechunkStore.compression_algorithm` and
    `MyIcechunkStore.config` must be disabled, so that any instance becomes
    serializable.

    Subclass of RinexDataProcessor that uses cooperative distributed writing.

    See:
        https://icechunk.io/en/latest/parallel/#cooperative-distributed-writes

    """

    def __init__(
        self,
        matched_data_dirs: MatchedDirs,
        site: GnssResearchSite,
        aux_file_path: Path | None = None,
        n_max_workers: int = 12,
    ) -> None:
        super().__init__(matched_data_dirs, site, aux_file_path, n_max_workers)

    def __repr__(self) -> str:
        return (
            "DistributedRinexDataProcessor("
            f"date={self.matched_data_dirs.yyyydoy.to_str()}, "
            f"site={self.site.site_name}, "
            f"aux_pipeline={self.aux_pipeline})"
        )

    def _cooperative_distributed_writing(
        self,
        rinex_files: list[Path],
        keep_vars: list[str],
        aux_zarr_path: Path,
        receiver_position: ECEFPosition,
        receiver_type: str,
        receiver_name: str,
    ) -> list[Path]:
        version = get_version_from_pyproject()
        repo = self.site.gnss_store.repo
        rinex_files_sorted = sorted(rinex_files, key=lambda p: p.name)

        # STEP 1: Initialize dataset structure with ALL files' time coordinates
        # This creates the full epoch dimension upfront
        session = repo.writable_session("main")

        # Collect all epochs from all files (or create empty structure)
        # Option A: Process all files first to get full time range
        all_epochs = []
        store_raw = self._config.processing.params.store_sbf_raw_observables
        for rinex_file in rinex_files_sorted:
            _fname, ds, _aux, _sids = preprocess_with_hermite_aux(
                rinex_file,
                keep_vars,
                aux_zarr_path,
                receiver_position,
                receiver_type,
                self.keep_sids,
                self._reader_name,
                store_sbf_raw_observables=store_raw,
            )
            all_epochs.extend(ds.epoch.values)

        # Create empty dataset with full structure
        _first_fname, first_ds, _aux, _sids = preprocess_with_hermite_aux(
            rinex_files_sorted[0],
            keep_vars,
            aux_zarr_path,
            receiver_position,
            receiver_type,
            self.keep_sids,
            self._reader_name,
            store_sbf_raw_observables=store_raw,
        )

        # Initialize with full epoch dimension
        empty_ds = first_ds.isel(epoch=[]).expand_dims({"epoch": len(all_epochs)})
        empty_ds = empty_ds.assign_coords({"epoch": np.sort(all_epochs)})

        to_icechunk(empty_ds, session, group=receiver_name, mode="w")
        session.commit(f"Initialize {receiver_name} structure")

        # STEP 2: Now do cooperative distributed writes
        session = repo.writable_session("main")
        fork = session.fork()  # ONE fork

        remote_sessions = []

        self._logger.info(
            "cooperative_writing_started",
            executor_type="ProcessPoolExecutor",
            files=len(rinex_files_sorted),
        )
        _res2 = self._config.processing.params.resolve_resources()
        with ProcessPoolExecutor(
            max_workers=self.n_max_workers,
            initializer=_worker_init_with_run_id,
            initargs=(_res2["nice_priority"], _res2["cpu_affinity"], get_run_id()),
        ) as ex:
            futures = [
                ex.submit(
                    worker_task_with_region_auto,
                    rinex_file,
                    keep_vars,
                    aux_zarr_path,
                    receiver_position,
                    receiver_type,
                    receiver_name,
                    fork,
                    self.keep_sids,
                    self._reader_name,
                    store_raw,
                )
                for rinex_file in rinex_files_sorted
            ]

            yyyydoy = self.matched_data_dirs.yyyydoy.to_str()
            desc = f"{yyyydoy} Writing {receiver_name}"
            with _processing_progress() as progress:
                task = progress.add_task(desc, total=len(futures))
                for fut in as_completed(futures):
                    try:
                        returned_fork = fut.result()
                    except BrokenProcessPool as e:
                        self._logger.error(
                            "worker_pool_broken",
                            receiver=receiver_name,
                            error=str(e),
                            hint="worker process likely killed by OOM or segfault",
                        )
                        raise
                    except Exception as e:
                        self._logger.error(
                            "worker_task_failed",
                            receiver=receiver_name,
                            error=str(e),
                            exception=type(e).__name__,
                        )
                        raise
                    remote_sessions.append(returned_fork)
                    progress.advance(task)

        # Merge all remote sessions
        session.merge(*remote_sessions)
        _snapshot_id = session.commit(
            f"[v{version}] Cooperative write for {receiver_name}"
        )

        return [f.name for f in rinex_files_sorted]  # ty: ignore[invalid-return-type]

    def parsed_rinex_data_gen_parallel(
        self,
        keep_vars: list[str] | None = None,
        receiver_types: list[str] | None = None,
    ) -> Generator[xr.Dataset]:
        """Generate datasets from RINEX files and append to Icechunk stores.

        Pipeline:
        1. Preprocess aux data ONCE per day with Hermite splines → Zarr
        2. Compute receiver position ONCE (shared for all receivers)
        3. For each receiver type (canopy, reference):
           a. Get list of RINEX files
           b. Parallel process via ProcessPoolExecutor
           c. Each worker: read RINEX + slice Zarr + compute φ, θ, r
           d. Sequential append to Icechunk store
           e. Yield final daily dataset

        Parameters
        ----------
        keep_vars : List[str], optional
            Variables to keep in datasets (default: from globals)
        receiver_types : List[str], optional
            Receiver types to process (default: ['canopy', 'reference'])

        Yields
        ------
        xr.Dataset
            Processed and augmented daily dataset for each receiver type

        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        if keep_vars is None:
            keep_vars = load_config().processing.params.keep_gnss_observables

        self._logger.info(
            "Starting RINEX processing pipeline for: %s",
            receiver_types,
        )

        # Pre-flight: Get canopy files to infer sampling and compute position
        canopy_dir = self.matched_data_dirs.canopy_data_dir
        canopy_files = self._get_rinex_files(canopy_dir)
        if not canopy_files:
            msg = "No canopy RINEX files found - cannot infer sampling rate"
            raise ValueError(msg)

        # ====================================================================
        # STEP 1: Preprocess aux data ONCE per day with Hermite splines
        # ====================================================================
        import shutil as _shutil

        _aux_base_dir = load_config().processing.storage.get_aux_data_dir()
        aux_zarr_path = _aux_base_dir / (
            f"aux_{self.matched_data_dirs.yyyydoy.to_str()}.zarr"
        )

        # Always reprocess from raw SP3/CLK files to avoid stale SID caches
        if aux_zarr_path.exists():
            _shutil.rmtree(aux_zarr_path)

        self._logger.info("Preprocessing aux data with Hermite splines (once per day)")
        _sampling_interval = self._preprocess_aux_data_with_hermite(
            canopy_files, aux_zarr_path
        )

        # ====================================================================
        # STEP 2: Compute receiver position
        # ====================================================================
        position_mode = self._config.processing.params.receiver_position_mode
        first_rnx = self._make_reader(canopy_files[0])
        first_ds = first_rnx.to_ds(keep_data_vars=[], write_global_attrs=True)
        shared_position = ECEFPosition.from_ds_metadata(first_ds)

        if position_mode == "per_receiver":
            self._logger.warning(
                "receiver_position_mode='per_receiver': each receiver will use "
                "its own RINEX header position. This breaks direct SNR "
                "comparability between receivers."
            )
        else:
            self._logger.info(
                "Computed receiver position (shared): %s",
                shared_position,
            )

        # ====================================================================
        # STEP 3: Process each receiver type
        # ====================================================================
        for receiver_type in receiver_types:
            self._logger.info("Processing receiver type: %s", receiver_type)

            # 3a. Resolve directories and receiver name
            rinex_dir, receiver_name = self._resolve_receiver_paths(receiver_type)

            if not receiver_name:
                self._logger.warning(
                    "No configured receiver for %s, skipping",
                    receiver_type,
                )
                continue

            # 3b. Get RINEX files for this receiver type
            rinex_files = self._get_rinex_files(rinex_dir)
            if not rinex_files:
                self._logger.warning(
                    "No RINEX files found in %s",
                    rinex_dir,
                )
                continue

            self._logger.info(
                "Found %s RINEX files to process",
                len(rinex_files),
            )

            # 3b'. Determine receiver position for this receiver
            if position_mode == "per_receiver":
                receiver_position = self._compute_receiver_position(
                    rinex_files, receiver_name
                )
                if receiver_position is None:
                    self._logger.error(
                        "Could not compute position for %s, skipping",
                        receiver_name,
                    )
                    continue
            else:
                receiver_position = shared_position

            # 3c. Parallel process via ProcessPoolExecutor
            _ = self._cooperative_distributed_writing(
                rinex_files=rinex_files,
                keep_vars=keep_vars,
                aux_zarr_path=aux_zarr_path,
                receiver_position=receiver_position,
                receiver_type=receiver_type,
                receiver_name=receiver_name,
            )

            # 3e. Yield final daily dataset
            # Read back from store to get complete daily dataset
            date_obj = self.matched_data_dirs.yyyydoy.date
            assert date_obj is not None, "yyyydoy.date must not be None"
            start_time = datetime.combine(date_obj, datetime.min.time())
            end_time = datetime.combine(date_obj, datetime.max.time())
            time_range = (start_time, end_time)

            daily_dataset = self.site.read_receiver_data(
                receiver_name=receiver_name, time_range=time_range
            )

            self._logger.info(
                "Yielding daily dataset for %s ('%s'): %s",
                receiver_type,
                receiver_name,
                dict(daily_dataset.sizes),
            )

            yield daily_dataset


if __name__ == "__main__":
    print(f"stared main block at {datetime.now(UTC)}")

    matcher = DataDirMatcher(
        root=Path("."),
        reference_pattern=Path("01_reference/01_GNSS/01_raw"),
        canopy_pattern=Path("02_canopy/01_GNSS/01_raw"),
    )

    site = GnssResearchSite(site_name="ExampleSite")

    stats = {"processed": 0, "skipped": 0, "failed": 0}

    for md in matcher:
        yyyydoy_str = md.yyyydoy.to_str()

        if yyyydoy_str != "2024258":
            continue

        try:
            print(f"instantiating processor for {yyyydoy_str}: {datetime.now(UTC)}")
            # Create processor first to check completeness
            processor = RinexDataProcessor(
                matched_data_dirs=md, site=site, n_max_workers=12
            )

            # Check if should skip
            if processor._gnss_store_strategy in ["skip", "unsafe_append"]:
                should_skip, coverage = processor.should_skip_day()

                if should_skip:
                    print(f"✓ Skipping {yyyydoy_str} - already complete:")
                    for receiver_type, info in coverage.items():
                        print(
                            f"  {receiver_type}: {info['epochs']}/"
                            f"{info['expected']} ({info['percent']:.1f}%)"
                        )
                    stats["skipped"] += 1
                    continue
                else:
                    print(f"⚠ Processing {yyyydoy_str} - incomplete coverage:")
                    for receiver_type, info in coverage.items():
                        if info["exists"]:
                            print(
                                f"  {receiver_type}: {info['epochs']}/"
                                f"{info['expected']} ({info['percent']:.1f}%)"
                            )
                        else:
                            print(f"  {receiver_type}: No data")

            # Process data
            print(
                f"about to call parsed_rinex_data_gen for {yyyydoy_str}: "
                f"{datetime.now(UTC)}"
            )
            data_generator = processor.parsed_rinex_data_gen()
            print(f"calling next for canopy: {datetime.now(UTC)}")
            canopy_ds = next(data_generator)
            print(f"calling next for reference: {datetime.now(UTC)}")
            reference_ds = next(data_generator)

            stats["processed"] += 1
            print(f"✓ Processed {yyyydoy_str}")

        except (OSError, RuntimeError, ValueError) as e:
            print(f"✗ Failed {yyyydoy_str}: {e}")
            stats["failed"] += 1
