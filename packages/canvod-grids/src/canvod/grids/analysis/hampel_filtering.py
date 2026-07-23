"""Parallelized Hampel filtering for gridded VOD data.

Spatial-batch multiprocessing Hampel filter with complete temporal
coverage (no temporal chunking).  Each (cell_id, SID) time series is
filtered independently using median absolute deviation (MAD).

Functions
---------
``process_spatial_batch_worker``      – picklable worker for one spatial batch.
``hampel_cell_sid_parallelized``      – main entry point (no temporal aggregation).
``aggr_hampel_cell_sid_parallelized`` – with optional temporal aggregation.

Notes
-----
* Worker function is module-level so it can be pickled by
  ``multiprocessing.Pool``.
* Default spatial batch size is 500 cells; tune based on available
  memory.
* Expected throughput: 300–700 K cell-SID combinations / s on a
  typical multi-core machine.

"""

from __future__ import annotations

import time
import warnings
from multiprocessing import Pool, cpu_count
from typing import Any, cast

import numpy as np
import structlog
import xarray as xr

from canvod.grids import add_cell_ids_to_vod_fast, create_hemigrid

logger = structlog.get_logger(__name__)


# ----------------------------------------------------------------------
# Picklable worker
# ----------------------------------------------------------------------


def process_spatial_batch_worker(args: tuple) -> dict:
    """Process a single spatial batch for one SID.

    Designed to be pickled and dispatched to worker processes.
    Returns compact index lists to minimise IPC memory transfer.

    Parameters
    ----------
    args : tuple
        ``(batch_cells, vod_values_sid, cell_ids_sid, valid_indices,
        threshold, min_obs_per_sid, batch_idx, sid_idx)``

        batch_cells : np.ndarray
            Cell IDs in this batch.
        vod_values_sid : np.ndarray
            VOD values for the current SID (valid entries only).
        cell_ids_sid : np.ndarray
            Corresponding cell IDs (same length as *vod_values_sid*).
        valid_indices : np.ndarray
            Original epoch indices of the valid entries.
        threshold : float
            MAD threshold for outlier detection.
        min_obs_per_sid : int
            Minimum observations required per cell to run filter.
        batch_idx : int
            Batch index (for bookkeeping).
        sid_idx : int
            SID index (for bookkeeping).

    Returns
    -------
    dict
        Keys: ``batch_idx``, ``sid_idx``, ``outlier_indices``,
        ``processing_indices``, ``combinations``, ``filtered``.

    """
    (
        batch_cells,
        vod_values_sid,
        cell_ids_sid,
        valid_indices,
        threshold,
        min_obs_per_sid,
        batch_idx,
        sid_idx,
    ) = args

    batch_outlier_indices: list[int] = []
    batch_processing_indices: list[int] = []
    batch_combinations = 0
    batch_filtered = 0

    for cell_id in batch_cells:
        batch_combinations += 1

        cell_mask = cell_ids_sid == cell_id
        if not np.any(cell_mask):
            continue

        cell_vod = vod_values_sid[cell_mask]
        cell_indices = valid_indices[cell_mask]

        if len(cell_vod) < min_obs_per_sid:
            continue

        batch_processing_indices.extend(cell_indices)
        batch_filtered += 1

        median_val = np.median(cell_vod)
        mad_val = np.median(np.abs(cell_vod - median_val))

        if mad_val > 0:
            outliers = np.abs(cell_vod - median_val) > threshold * mad_val
            if np.any(outliers):
                batch_outlier_indices.extend(cell_indices[outliers])

    return {
        "batch_idx": batch_idx,
        "sid_idx": sid_idx,
        "outlier_indices": batch_outlier_indices,
        "processing_indices": batch_processing_indices,
        "combinations": batch_combinations,
        "filtered": batch_filtered,
    }


# ----------------------------------------------------------------------
# Core filtering
# ----------------------------------------------------------------------


def hampel_cell_sid_parallelized(
    vod_ds: xr.Dataset,
    grid_name: str = "equal_area_2deg",
    threshold: float = 3.0,
    min_obs_per_sid: int = 20,
    spatial_batch_size: int = 500,
    n_workers: int | None = None,
) -> xr.Dataset:
    """Parallelized cell–SID Hampel filter with complete temporal coverage.

    Each (cell_id, SID) time series is filtered independently using
    global (non-chunked) statistics.  Spatial work is distributed
    across *n_workers* processes.

    Parameters
    ----------
    vod_ds : xr.Dataset
        Input dataset containing ``'VOD'`` and a ``cell_id_<grid_name>``
        variable, with dimensions ``(epoch, sid)``.
    grid_name : str
        Grid identifier used to locate the cell-ID variable, e.g.
        ``'equal_area_2deg'``.
    threshold : float
        MAD multiplier for outlier detection.
    min_obs_per_sid : int
        Minimum valid observations per cell-SID to run the filter.
    spatial_batch_size : int
        Number of cells per parallel batch.
    n_workers : int or None
        Number of worker processes.  Defaults to ``min(cpu_count(), 8)``.

    Returns
    -------
    xr.Dataset
        Copy of *vod_ds* with additional variables:

        * ``VOD_filtered_hampel`` – filtered VOD (outliers set to NaN).
        * ``hampel_processing_mask`` – boolean mask of processed
          observations.

        Dataset-level attrs include full processing metadata.

    """
    warnings.warn(
        "hampel_cell_sid_parallelized() has no callers in this codebase — use "
        "aggr_hampel_cell_sid_parallelized() instead, which additionally "
        "supports optional temporal aggregation.",
        DeprecationWarning,
        stacklevel=2,
    )
    if n_workers is None:
        n_workers = min(cpu_count(), 8)

    cell_id_var = f"cell_id_{grid_name}"
    n_epochs, n_sids = vod_ds.VOD.shape
    cell_ids = vod_ds[cell_id_var].values
    vod_values = vod_ds.VOD.values

    logger.info(
        "Parallelized Hampel filter: shape=%s, threshold=%.1f, "
        "min_obs=%d, workers=%d, batch_size=%d",
        vod_ds.VOD.shape,
        threshold,
        min_obs_per_sid,
        n_workers,
        spatial_batch_size,
    )

    # Unique cells and spatial batches
    unique_cells = np.unique(cell_ids[np.isfinite(cell_ids)])
    n_spatial_batches = int(np.ceil(len(unique_cells) / spatial_batch_size))

    cell_batches = [
        (unique_cells[i : i + spatial_batch_size], i // spatial_batch_size)
        for i in range(0, len(unique_cells), spatial_batch_size)
    ]

    # Result arrays
    outlier_mask = np.zeros((n_epochs, n_sids), dtype=bool)
    processing_mask = np.zeros((n_epochs, n_sids), dtype=bool)

    total_combinations_processed = 0
    total_combinations_filtered = 0
    overall_start = time.time()

    for sid_idx in range(n_sids):
        if sid_idx % 25 == 0:
            elapsed = time.time() - overall_start
            if sid_idx > 0 and elapsed > 0:
                rate = total_combinations_processed / elapsed
                logger.debug(
                    "SID %d/%d | rate=%.0f combinations/s",
                    sid_idx + 1,
                    n_sids,
                    rate,
                )

        valid_mask = np.isfinite(vod_values[:, sid_idx]) & np.isfinite(
            cell_ids[:, sid_idx]
        )
        if not np.any(valid_mask):
            total_combinations_processed += len(unique_cells)
            continue

        valid_indices = np.where(valid_mask)[0]
        sid_cells = cell_ids[valid_mask, sid_idx]
        sid_vod = vod_values[valid_mask, sid_idx]

        batch_args = [
            (
                batch_cells,
                sid_vod,
                sid_cells,
                valid_indices,
                threshold,
                min_obs_per_sid,
                batch_idx,
                sid_idx,
            )
            for batch_cells, batch_idx in cell_batches
        ]

        with Pool(n_workers) as pool:
            batch_results = pool.map(process_spatial_batch_worker, batch_args)

        for result in batch_results:
            if result["outlier_indices"]:
                outlier_mask[result["outlier_indices"], sid_idx] = True
            if result["processing_indices"]:
                processing_mask[result["processing_indices"], sid_idx] = True
            total_combinations_processed += result["combinations"]
            total_combinations_filtered += result["filtered"]

    total_time = time.time() - overall_start

    # Build result dataset
    vod_filtered = vod_values.copy()
    vod_filtered[outlier_mask] = np.nan

    result_ds = vod_ds.copy()
    result_ds["VOD_filtered_hampel"] = (["epoch", "sid"], vod_filtered)
    result_ds["hampel_processing_mask"] = (["epoch", "sid"], processing_mask)

    # Statistics for logging
    original_valid = int(np.sum(np.isfinite(vod_values)))
    outliers_removed = int(np.sum(outlier_mask))
    outlier_pct = outliers_removed / original_valid * 100 if original_valid > 0 else 0.0

    logger.info(
        "Hampel complete: time=%.1fs, rate=%.0f comb/s, "
        "outliers=%d (%.2f%%), processed=%d combinations",
        total_time,
        total_combinations_processed / total_time if total_time > 0 else 0,
        outliers_removed,
        outlier_pct,
        total_combinations_processed,
    )

    # Metadata
    result_ds.attrs.update(
        {
            "hampel_filtering": "parallelized_complete_temporal",
            "hampel_threshold": threshold,
            "min_obs_per_sid": min_obs_per_sid,
            "spatial_batch_size": spatial_batch_size,
            "n_workers": n_workers,
            "spatial_batches": n_spatial_batches,
            "temporal_chunking": "none",
            "temporal_coverage": "complete",
            "processing_time_seconds": total_time,
            "processing_rate_combinations_per_second": (
                total_combinations_processed / total_time if total_time > 0 else 0
            ),
            "combinations_processed": total_combinations_processed,
            "combinations_filtered": total_combinations_filtered,
            "parallel_efficiency": (
                total_combinations_processed / (n_workers * total_time)
                if total_time > 0
                else 0
            ),
            "outliers_removed": outliers_removed,
            "outlier_percentage": outlier_pct,
            "scientific_validity": "complete_temporal_continuity",
            "parallelization_method": "multiprocessing_spatial_batches",
        }
    )

    result_ds["VOD_filtered_hampel"].attrs.update(
        {
            "long_name": (
                "VOD filtered with parallelized complete temporal Hampel method"
            ),
            "method": "global_statistics_per_cell_sid",
            "temporal_coverage": "complete_no_chunking",
            "parallelization": f"{n_workers}_workers_spatial_batching",
        }
    )

    result_ds["hampel_processing_mask"].attrs.update(
        {
            "long_name": "Mask of observations processed by parallel Hampel filter",
            "temporal_coverage": "complete",
            "processing_method": "parallel_spatial_batches",
        }
    )

    return result_ds


# ----------------------------------------------------------------------
# With optional temporal aggregation
# ----------------------------------------------------------------------

# Frequency → window in seconds
_FREQ_MAP: dict[str, int] = {
    "30s": 30,
    "1min": 60,
    "5min": 300,
    "10min": 600,
    "15min": 900,
    "30min": 1800,
    "1H": 3600,
    "3H": 10800,
    "6H": 21600,
    "12H": 43200,
    "1D": 86400,
}


def _compute_time_bins(global_times: np.ndarray, temporal_agg: str) -> np.ndarray:
    """Compute unique time-bin edges from epoch array and frequency string."""
    if temporal_agg not in _FREQ_MAP:
        raise ValueError(
            f"Unsupported temporal aggregation: {temporal_agg}. "
            f"Valid: {list(_FREQ_MAP.keys())}"
        )
    window_s = _FREQ_MAP[temporal_agg]
    times_sec = global_times.astype("datetime64[s]").astype(np.int64)
    time_bins = (times_sec // window_s) * window_s
    return np.unique(time_bins).astype("datetime64[s]")


def _aggregate_temporally(
    valid_times: np.ndarray,
    sid_cells: np.ndarray,
    sid_vod: np.ndarray,
    temporal_agg: str,
    agg_method: str = "mean",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Aggregate one SID's data into temporal bins.

    Parameters
    ----------
    valid_times : np.ndarray
        Epoch values (datetime64) for valid observations.
    sid_cells : np.ndarray
        Corresponding cell IDs.
    sid_vod : np.ndarray
        Corresponding VOD values.
    temporal_agg : str
        Frequency string (e.g. ``'1H'``).
    agg_method : str
        ``'mean'`` or ``'median'``.

    Returns
    -------
    agg_times, agg_cells, agg_vod : np.ndarray
        Aggregated arrays.

    """
    window_s = _FREQ_MAP[temporal_agg]
    times_sec = valid_times.astype("datetime64[s]").astype(np.int64)
    time_bins = (times_sec // window_s) * window_s

    # Composite key: cell_id * 10^10 + time_bin_seconds
    composite_key = sid_cells.astype(np.int64) * 10**10 + time_bins

    order = np.argsort(composite_key)
    composite_key = composite_key[order]
    sid_vod = sid_vod[order]
    sid_cells = sid_cells[order]
    time_bins = time_bins[order]

    unique_keys, idx, counts = np.unique(
        composite_key, return_index=True, return_counts=True
    )

    if agg_method == "mean":
        agg_vod = np.add.reduceat(sid_vod, idx) / counts
    elif agg_method == "median":
        agg_vod = np.array(
            [np.median(sid_vod[i : i + c]) for i, c in zip(idx, counts)],
            dtype=float,
        )
    else:
        raise ValueError("agg_method must be 'mean' or 'median'")

    agg_cells = (unique_keys // 10**10).astype(float)
    agg_times = (unique_keys % 10**10).astype("datetime64[s]")
    return agg_times, agg_cells, agg_vod


def aggr_hampel_cell_sid_parallelized(
    vod_ds: xr.Dataset,
    grid_name: str = "equal_area_2deg",
    threshold: float = 3.0,
    min_obs_per_sid: int = 20,
    spatial_batch_size: int = 500,
    n_workers: int | None = None,
    temporal_agg: str | None = None,
    agg_method: str = "mean",
) -> xr.Dataset:
    """Parallelized cell–SID Hampel filter with optional temporal aggregation.

    Each (cell_id, SID) series is filtered independently.  When
    *temporal_agg* is set, data is first binned into temporal windows
    before filtering; φ, θ and cell IDs are reassigned consistently on
    the output.

    Parameters
    ----------
    vod_ds : xr.Dataset
        Input dataset with ``'VOD'``, ``'phi'``, ``'theta'`` and a
        ``cell_id_<grid_name>`` variable.
    grid_name : str
        Grid identifier (e.g. ``'equal_area_2deg'``).  Used to locate
        or create the cell-ID variable.
    threshold : float
        MAD multiplier.
    min_obs_per_sid : int
        Minimum valid observations per cell-SID.
    spatial_batch_size : int
        Cells per parallel batch.
    n_workers : int or None
        Worker count (defaults to ``min(cpu_count(), 8)``).
    temporal_agg : str or None
        Temporal aggregation frequency (e.g. ``'1H'``, ``'1D'``).
        ``None`` → no aggregation.
    agg_method : str
        ``'mean'`` or ``'median'`` for temporal aggregation.

    Returns
    -------
    xr.Dataset
        Dataset with ``'VOD'`` (aggregated raw), ``'VOD_filtered_hampel'``,
        ``'hampel_outlier_mask'``, ``'hampel_processing_mask'``,
        reassigned ``phi``, ``theta`` and ``cell_id_<grid_name>``.

    """
    if n_workers is None:
        n_workers = min(cpu_count(), 8)

    # --- Parse grid_name → (grid_type, resolution) ---
    parts = grid_name.split("_")
    if not parts[-1].endswith("deg"):
        raise ValueError(f"Grid name '{grid_name}' must end with '<N>deg'")
    try:
        resolution = float(parts[-1].replace("deg", ""))
    except ValueError as e:
        raise ValueError(
            f"Could not parse resolution from grid name '{grid_name}'"
        ) from e
    grid_type = "_".join(parts[:-1])

    grid = create_hemigrid(
        angular_resolution=resolution,
        grid_type=cast(Any, grid_type),
    )

    cell_id_var = f"cell_id_{grid_name}"
    if cell_id_var not in vod_ds:
        logger.info("No '%s' in input dataset — assigning now.", cell_id_var)
        vod_ds = add_cell_ids_to_vod_fast(vod_ds, grid=grid, grid_name=grid_name)

    vod_values = vod_ds["VOD"].values
    cell_ids = vod_ds[cell_id_var].values
    n_epochs, n_sids = vod_values.shape

    unique_cells = np.unique(cell_ids[np.isfinite(cell_ids)])
    cell_batches = [
        (unique_cells[i : i + spatial_batch_size], i // spatial_batch_size)
        for i in range(0, len(unique_cells), spatial_batch_size)
    ]

    logger.info(
        "aggr_hampel: shape=%s, threshold=%.1f, workers=%d, temporal_agg=%s",
        vod_ds.VOD.shape,
        threshold,
        n_workers,
        temporal_agg,
    )

    # --- Epoch grid ---
    if temporal_agg:
        new_epochs = _compute_time_bins(vod_ds["epoch"].values, temporal_agg)
        logger.info("Temporal aggregation → %d epoch bins", len(new_epochs))
    else:
        new_epochs = vod_ds["epoch"].values

    # --- Preallocate ---
    vod_filtered = np.full((len(new_epochs), n_sids), np.nan)
    vod_agg = np.full((len(new_epochs), n_sids), np.nan)
    outlier_mask = np.zeros((len(new_epochs), n_sids), dtype=bool)
    processing_mask = np.zeros((len(new_epochs), n_sids), dtype=bool)

    total_combinations_processed = 0
    total_combinations_filtered = 0
    start_time = time.time()

    for sid_idx in range(n_sids):
        valid_mask = np.isfinite(vod_values[:, sid_idx]) & np.isfinite(
            cell_ids[:, sid_idx]
        )
        if not np.any(valid_mask):
            continue

        sid_cells = cell_ids[valid_mask, sid_idx]
        sid_vod = vod_values[valid_mask, sid_idx]
        valid_times = vod_ds["epoch"].values[valid_mask]

        if temporal_agg:
            valid_times, sid_cells, sid_vod = _aggregate_temporally(
                valid_times, sid_cells, sid_vod, temporal_agg, agg_method
            )

        # Parallel filtering
        batch_args = [
            (
                batch_cells,
                sid_vod,
                sid_cells,
                np.arange(len(valid_times)),
                threshold,
                min_obs_per_sid,
                batch_idx,
                sid_idx,
            )
            for batch_cells, batch_idx in cell_batches
        ]

        with Pool(n_workers) as pool:
            batch_results = pool.map(process_spatial_batch_worker, batch_args)

        for res in batch_results:
            if res["outlier_indices"]:
                t_idx = np.searchsorted(
                    new_epochs,
                    valid_times[res["outlier_indices"]],
                )
                outlier_mask[t_idx, sid_idx] = True
            if res["processing_indices"]:
                t_idx = np.searchsorted(
                    new_epochs,
                    valid_times[res["processing_indices"]],
                )
                processing_mask[t_idx, sid_idx] = True
            total_combinations_processed += res["combinations"]
            total_combinations_filtered += res["filtered"]

        # Assign aggregated values
        bin_index = np.searchsorted(new_epochs, valid_times)
        for i, t_idx in enumerate(bin_index):
            if 0 <= t_idx < len(new_epochs):
                vod_agg[t_idx, sid_idx] = np.nanmean(
                    [vod_agg[t_idx, sid_idx], sid_vod[i]]
                )
                vod_filtered[t_idx, sid_idx] = np.nanmean(
                    [vod_filtered[t_idx, sid_idx], sid_vod[i]]
                )

    total_time = time.time() - start_time

    # --- Build output dataset ---
    result_ds = xr.Dataset(
        data_vars={
            "VOD": (["epoch", "sid"], vod_agg),
            "VOD_filtered_hampel": (["epoch", "sid"], vod_filtered),
            "hampel_outlier_mask": (["epoch", "sid"], outlier_mask),
            "hampel_processing_mask": (["epoch", "sid"], processing_mask),
        },
        coords={"epoch": new_epochs, "sid": vod_ds["sid"].values},
        attrs=vod_ds.attrs.copy(),
    )

    # Copy geometry if present
    if "phi" in vod_ds and "theta" in vod_ds:
        phi_tmpl = vod_ds["phi"].isel(epoch=0).values
        theta_tmpl = vod_ds["theta"].isel(epoch=0).values
        result_ds["phi"] = (
            ["epoch", "sid"],
            np.repeat(phi_tmpl[None, :], len(new_epochs), axis=0),
        )
        result_ds["theta"] = (
            ["epoch", "sid"],
            np.repeat(theta_tmpl[None, :], len(new_epochs), axis=0),
        )

    # Reassign cell IDs consistently
    logger.info("Reassigning cell IDs for output dataset.")
    result_ds = add_cell_ids_to_vod_fast(result_ds, grid=grid, grid_name=grid_name)

    # Metadata
    result_ds.attrs.update(
        {
            "processing": "parallelized_hampel_with_optional_aggregation",
            "temporal_aggregation": temporal_agg or "none",
            "aggregation_method": agg_method,
            "threshold": threshold,
            "min_obs_per_sid": min_obs_per_sid,
            "spatial_batch_size": spatial_batch_size,
            "n_workers": n_workers,
            "execution_time_s": total_time,
            "combinations_processed": int(total_combinations_processed),
            "combinations_filtered": int(total_combinations_filtered),
        }
    )

    logger.info(
        "aggr_hampel complete: epochs=%d, sids=%d, time=%.1fs",
        len(new_epochs),
        n_sids,
        total_time,
    )

    return result_ds
