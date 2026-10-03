"""Core adapted VOD workflow.

Orchestrates the full VOD analysis pipeline: loading data from an
Icechunk store, applying cell-SID Hampel filtering (vectorised or
parallelised), and persisting results back to a ``processing`` branch.

Classes
-------
``AdaptedVODWorkflow``
    Main workflow entry-point.  Lazily imports ``canvod-store`` so the
    package can be imported even when the store is not installed.

Functions
---------
``get_workflow_for_store``
    Convenience factory.
``check_processed_data_status``
    Introspect the store for previously filtered data.
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import structlog
import xarray as xr

if TYPE_CHECKING:
    from canvod.store.store import MyIcechunkStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store(store_path: Path) -> MyIcechunkStore:
    """Lazy import and instantiate ``MyIcechunkStore``."""
    try:
        from canvod.store.store import MyIcechunkStore as _Store
    except ImportError as exc:
        raise ImportError(
            "AdaptedVODWorkflow requires 'canvod-store'. "
            "Install it with: uv add canvod-store"
        ) from exc
    return _Store(store_path, store_type="vod_store")


def normalize_datetime_for_comparison(
    dt: datetime.date | datetime.datetime,
) -> datetime.datetime:
    """Coerce date to datetime at midnight for safe comparison.

    Parameters
    ----------
    dt : datetime.date | datetime.datetime
        Date-like input.

    Returns
    -------
    datetime.datetime
        Datetime at midnight.

    """
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        return datetime.datetime.combine(dt, datetime.time.min)
    return dt


# ---------------------------------------------------------------------------
# Workflow class
# ---------------------------------------------------------------------------


class AdaptedVODWorkflow:
    """Core VOD analysis workflow with polars-optimised loading and refined
    temporal matching.

    All heavy lifting (filtering, grid operations) is delegated to
    ``canvod.grids.analysis``.  This class is responsible only for
    Icechunk I/O and orchestration.

    Parameters
    ----------
    vod_store_path : Path or str
        Path to the VOD Icechunk store directory.

    """

    def __init__(self, vod_store_path: Path | str) -> None:
        """Initialize the workflow.

        Parameters
        ----------
        vod_store_path : Path | str
            Path to the VOD Icechunk store directory.

        """
        self.vod_store_path = Path(vod_store_path)
        self.vod_store: MyIcechunkStore = _get_store(self.vod_store_path)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_vod_data(
        self,
        group_name: str = "reference_01_canopy_01",
        branch: str = "main",
    ) -> xr.Dataset:
        """Load a VOD dataset from the store.

        Parameters
        ----------
        group_name : str
            Zarr group path inside the store.
        branch : str
            Icechunk branch to read from.

        Returns
        -------
        xr.Dataset
            Lazy-loaded VOD dataset.

        """
        logger.info("Loading VOD data from branch=%s group=%s", branch, group_name)
        with self.vod_store.readonly_session(branch=branch) as session:
            vod_ds = xr.open_zarr(session.store, group=group_name, consolidated=False)
        logger.info("Loaded VOD dataset: %s", dict(vod_ds.sizes))
        return vod_ds

    # ------------------------------------------------------------------
    # Temporal coverage checks
    # ------------------------------------------------------------------

    def check_temporal_coverage_compatibility(
        self,
        main_ds: xr.Dataset,
        processed_ds: xr.Dataset,
        requested_time_range: tuple[datetime.date, datetime.date] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """Check whether *processed_ds* adequately covers a time range.

        When *requested_time_range* is ``None`` the method checks that the
        processed dataset covers at least 70 % of the main dataset's span.
        When a range is given it verifies that both endpoints fall within the
        processed dataset (with a 1-day tolerance).

        Parameters
        ----------
        main_ds : xr.Dataset
            Reference (unfiltered) dataset.
        processed_ds : xr.Dataset
            Filtered dataset to validate.
        requested_time_range : tuple of date, optional
            ``(start, end)`` to check against.

        Returns
        -------
        compatible : bool
        coverage_info : dict
            Diagnostic information with ``main_range``, ``processed_range``,
            and ``requested_range``.

        """

        def _date_range(ds: xr.Dataset) -> tuple[datetime.date, datetime.date]:
            """Return the date range for a dataset.

            Parameters
            ----------
            ds : xr.Dataset
                Dataset with an epoch coordinate.

            Returns
            -------
            tuple[datetime.date, datetime.date]
                Start and end dates.

            """
            return (
                pd.to_datetime(ds.epoch.min().values).date(),
                pd.to_datetime(ds.epoch.max().values).date(),
            )

        main_start, main_end = _date_range(main_ds)
        proc_start, proc_end = _date_range(processed_ds)

        coverage_info: dict[str, Any] = {
            "main_range": (main_start, main_end),
            "processed_range": (proc_start, proc_end),
            "requested_range": requested_time_range,
        }

        if requested_time_range is None:
            main_days = (main_end - main_start).days
            proc_days = (proc_end - proc_start).days
            ratio = proc_days / main_days if main_days > 0 else 0.0
            logger.info(
                "Coverage check: main=%d days, processed=%d days, ratio=%.1f%%",
                main_days,
                proc_days,
                ratio * 100,
            )
            return ratio >= 0.7, coverage_info

        req_start, req_end = requested_time_range
        one_day = datetime.timedelta(days=1)
        start_ok = proc_start <= req_start <= proc_end + one_day
        end_ok = proc_start - one_day <= req_end <= proc_end
        compatible = start_ok and end_ok

        if not compatible:
            logger.warning(
                "Temporal coverage mismatch: processed=%s→%s, requested=%s→%s",
                proc_start,
                proc_end,
                req_start,
                req_end,
            )
        return compatible, coverage_info

    # ------------------------------------------------------------------
    # Filtering entry-points
    # ------------------------------------------------------------------

    def create_processed_data_fast_hampel_complete(
        self,
        start_date: datetime.date | datetime.datetime,
        end_date: datetime.date | datetime.datetime,
        force_recreate: bool = False,
        window_hours: float = 1.0,
        sigma_threshold: float = 3.0,
        min_points: int = 5,
        ultra_fast_mode: bool = False,
        cell_batch_size: int = 200,
        n_workers: int | None = None,
    ) -> str | None:
        """Run the vectorised / ultra-fast Hampel pipeline end-to-end.

        Delegates the actual filtering to
        :func:`canvod.grids.analysis.sigma_clip_filter.astropy_hampel_vectorized_fast`
        (or its ultra-fast variant) and persists the result on a
        ``processing`` branch.

        Parameters
        ----------
        start_date, end_date : date or datetime
            Temporal extent to process.
        force_recreate : bool
            Overwrite existing filtered data.
        window_hours : float
            Hampel temporal window in hours.
        sigma_threshold : float
            MAD-based outlier threshold.
        min_points : int
            Minimum observations required per window.
        ultra_fast_mode : bool
            Use the pure-NumPy sigma-clip path (faster, less precise).
        cell_batch_size : int
            Number of cells per spatial batch.
        n_workers : int, optional
            Parallel workers.  ``None`` → auto-detect.

        Returns
        -------
        str or None
            Icechunk snapshot ID, or ``None`` if existing data was kept.

        """
        return _create_processed_data_fast_hampel(
            workflow_instance=self,
            start_date=start_date,
            end_date=end_date,
            force_recreate=force_recreate,
            window_hours=window_hours,
            sigma_threshold=sigma_threshold,
            min_points=min_points,
            ultra_fast_mode=ultra_fast_mode,
            cell_batch_size=cell_batch_size,
            n_workers=n_workers,
        )

    def create_processed_data_hampel_parallel_complete(
        self,
        start_date: datetime.date | datetime.datetime,
        end_date: datetime.date | datetime.datetime,
        force_recreate: bool = False,
        threshold: float = 3.0,
        min_obs_per_sid: int = 20,
        spatial_batch_size: int = 500,
        n_workers: int | None = None,
        temporal_agg: str | None = None,
        agg_method: str | None = None,
    ) -> str | None:
        """Run the parallelised cell-SID Hampel pipeline end-to-end.

        Loads the complete requested time range (no temporal chunking) and
        applies
        :func:`canvod.grids.analysis.hampel_filtering.aggr_hampel_cell_sid_parallelized`
        with spatial batching.

        Parameters
        ----------
        start_date, end_date : date or datetime
            Temporal extent to process.
        force_recreate : bool
            Overwrite existing filtered data.
        threshold : float
            MAD-based outlier threshold.
        min_obs_per_sid : int
            Minimum observations per cell-SID combination.
        spatial_batch_size : int
            Cells per spatial batch.
        n_workers : int, optional
            Parallel workers.  ``None`` → auto-detect.
        temporal_agg : str, optional
            Post-filtering aggregation frequency (e.g. ``'1H'``, ``'1D'``).
        agg_method : str, optional
            Aggregation method (e.g. ``'mean'``).

        Returns
        -------
        str or None
            Icechunk snapshot ID, or ``None`` if existing data was kept.

        """
        from canvod.grids import create_hemigrid
        from canvod.grids.analysis.hampel_filtering import (
            aggr_hampel_cell_sid_parallelized,
        )
        from canvod.grids.operations import add_cell_ids_to_ds_fast

        logger.info("=" * 60)
        logger.info("PARALLEL HAMPEL — complete temporal coverage")
        logger.info(
            "Range: %s → %s | threshold=%.1f | min_obs=%d | batch=%d | workers=%s",
            start_date,
            end_date,
            threshold,
            min_obs_per_sid,
            spatial_batch_size,
            n_workers or "auto",
        )

        # --- guard: existing data ---
        if not self._force_or_skip("processing", force_recreate):
            return None

        # --- load complete time range ---
        logger.info("Loading complete time range for parallel processing")
        with self.vod_store.readonly_session(branch="main") as session:
            vod_ds = xr.open_zarr(session.store, group="reference_01_canopy_01")

        vod_ds_complete = vod_ds.sel(epoch=slice(start_date, end_date))

        if "cell_id_equal_area_2deg" not in vod_ds_complete:
            grid = create_hemigrid(grid_type="equal_area", angular_resolution=2)
            vod_ds_complete = add_cell_ids_to_ds_fast(
                vod_ds_complete, grid, "equal_area_2deg"
            )

        logger.info("Dataset loaded: %s", dict(vod_ds_complete.sizes))

        # --- filter ---
        t0 = time.time()
        resolved_agg_method = agg_method or "mean"
        vod_ds_filtered = aggr_hampel_cell_sid_parallelized(
            vod_ds_complete,
            threshold=threshold,
            min_obs_per_sid=min_obs_per_sid,
            spatial_batch_size=spatial_batch_size,
            n_workers=n_workers,
            temporal_agg=temporal_agg,
            agg_method=resolved_agg_method,
        )
        logger.info("Parallel filtering completed in %.1f s", time.time() - t0)

        # --- persist ---
        snapshot_id = self._persist_filtered(
            vod_ds_filtered,
            "parallel Cell-SID Hampel",
        )
        logger.info("Parallel Hampel complete. Snapshot: %s", snapshot_id)
        return snapshot_id

    # ------------------------------------------------------------------
    # High-level orchestration
    # ------------------------------------------------------------------

    def run_complete_workflow(
        self,
        group_name: str = "reference_01_canopy_01",
        branch: str = "auto",
        time_range: tuple[datetime.date, datetime.date] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Orchestrate a complete analysis run.

        Auto-detection logic (``branch='auto'``) looks for Hampel-filtered
        data on the ``processing`` branch first.  If found and temporally
        compatible it is used directly; otherwise raw data from ``main`` is
        returned.

        Parameters
        ----------
        group_name : str
            Zarr group for the raw VOD data.
        branch : str
            ``'auto'`` for detection, or an explicit branch name.
        time_range : tuple of date, optional
            ``(start, end)`` to select.

        Returns
        -------
        dict
            Keys: ``final_data`` (Dataset), ``source_branch``,
            ``pre_filtered`` (bool), ``filter_type``.

        """
        logger.info("=" * 60)
        logger.info("HAMPEL-FILTERED VOD ANALYSIS WORKFLOW")
        logger.info("branch=%s group=%s time_range=%s", branch, group_name, time_range)

        results: dict[str, Any] = {}

        if branch == "auto":
            hampel_ds = self._try_load_hampel()

            if hampel_ds is not None:
                # Validate temporal coverage when a range is requested
                if time_range is not None:
                    dataset_start = pd.to_datetime(hampel_ds.epoch.min().values).date()
                    dataset_end = pd.to_datetime(hampel_ds.epoch.max().values).date()

                    start_ok = normalize_datetime_for_comparison(
                        time_range[0]
                    ) >= normalize_datetime_for_comparison(dataset_start)
                    end_ok = normalize_datetime_for_comparison(
                        time_range[1]
                    ) <= normalize_datetime_for_comparison(dataset_end)

                    if start_ok and end_ok:
                        hampel_ds = hampel_ds.sel(
                            epoch=slice(time_range[0], time_range[1])
                        )
                    else:
                        logger.warning(
                            "Hampel data (%s→%s) does not cover requested "
                            "range (%s→%s); falling back to main branch",
                            dataset_start,
                            dataset_end,
                            time_range[0],
                            time_range[1],
                        )
                        hampel_ds = None

                if hampel_ds is not None:
                    logger.info("Using Hampel filtered data from processing branch")
                    return {
                        "final_data": hampel_ds,
                        "source_branch": "processing",
                        "pre_filtered": True,
                        "filter_type": "hampel",
                    }

            logger.info("No usable Hampel data found; using raw data from main branch")
            branch = "main"

        # --- main branch (raw) ---
        logger.info("Loading raw data from branch=%s", branch)
        vod_ds = self.load_vod_data(group_name, branch)

        if time_range is not None:
            vod_ds = vod_ds.sel(epoch=slice(time_range[0], time_range[1]))

        results = {
            "final_data": vod_ds,
            "source_branch": branch,
            "pre_filtered": False,
            "filter_type": "none",
        }
        logger.info("Workflow complete — source=%s", branch)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _try_load_hampel(self) -> xr.Dataset | None:
        """Attempt to load Hampel-filtered data from the processing branch."""
        try:
            with self.vod_store.readonly_session(branch="processing") as session:
                ds = xr.open_zarr(
                    session.store,
                    group="reference_01_canopy_01_hampel_filtered",
                    consolidated=False,
                )
            logger.info("Found Hampel filtered data on processing branch")
            return ds
        except Exception:
            logger.debug("No Hampel data on processing branch", exc_info=True)
            return None

    def _force_or_skip(self, branch: str, force_recreate: bool) -> bool:
        """Guard pattern: return ``True`` to proceed, ``False`` to skip.

        If filtered data already exists and *force_recreate* is ``False``
        the method logs a warning and returns ``False``.  When
        *force_recreate* is ``True`` it deletes the branch first.
        """
        exists = self._try_load_hampel() is not None
        if exists and not force_recreate:
            logger.warning(
                "Filtered data already exists. Pass force_recreate=True to overwrite."
            )
            return False
        if exists and force_recreate:
            try:
                self.vod_store.delete_branch(branch)
                logger.info("Deleted existing %s branch", branch)
            except Exception:
                logger.warning("Could not delete branch %s", branch, exc_info=True)
        return True

    def _persist_filtered(
        self,
        ds: xr.Dataset,
        label: str,
        target_group: str = "reference_01_canopy_01_hampel_filtered",
    ) -> str:
        """Write a filtered dataset to the ``processing`` branch.

        Rechunks variables along the ``epoch`` dimension (max 50 000 epochs
        per chunk) before writing.

        Returns the Icechunk snapshot ID.
        """
        from icechunk.xarray import to_icechunk

        # Ensure processing branch exists
        try:
            current_snapshot = next(self.vod_store.repo.ancestry(branch="main")).id
            self.vod_store.repo.create_branch("processing", current_snapshot)
        except Exception:
            pass  # branch may already exist

        with self.vod_store.writable_session("processing") as session:
            logger.info("Persisting filtered data (%s)", label)
            for var_name in ds.data_vars:
                if "epoch" in ds[var_name].dims:
                    epoch_size = ds[var_name].sizes["epoch"]
                    ds[var_name] = ds[var_name].chunk(
                        {"epoch": min(epoch_size, 50000), "sid": -1}
                    )
            to_icechunk(ds, session, group=target_group, mode="w", safe_chunks=False)
            snapshot_id: str = session.commit(label)

        return snapshot_id


# ---------------------------------------------------------------------------
# Module-level integration function (ported from sigma_clip_filter)
# ---------------------------------------------------------------------------


def _create_processed_data_fast_hampel(
    workflow_instance: AdaptedVODWorkflow,
    start_date: datetime.date | datetime.datetime,
    end_date: datetime.date | datetime.datetime,
    force_recreate: bool = False,
    window_hours: float = 1.0,
    sigma_threshold: float = 3.0,
    min_points: int = 5,
    ultra_fast_mode: bool = False,
    cell_batch_size: int = 200,
    n_workers: int | None = None,
) -> str | None:
    """End-to-end fast Hampel pipeline.

    Loads data, runs
    :func:`~canvod.grids.analysis.sigma_clip_filter.astropy_hampel_vectorized_fast`
    (or the ultra-fast variant), and persists the result.

    Parameters
    ----------
    workflow_instance : AdaptedVODWorkflow
        Provides store access and persistence helpers.
    start_date, end_date : date or datetime
        Temporal extent.
    force_recreate : bool
        Overwrite existing filtered data.
    window_hours : float
        Hampel window in hours.
    sigma_threshold : float
        MAD outlier threshold.
    min_points : int
        Minimum observations per window.
    ultra_fast_mode : bool
        Use pure-NumPy path (faster, less precise).
    cell_batch_size : int
        Cells per spatial batch.
    n_workers : int, optional
        Parallel workers.

    Returns
    -------
    str or None
        Snapshot ID, or ``None`` if existing data was kept.

    """
    from canvod.grids import create_hemigrid
    from canvod.grids.analysis.sigma_clip_filter import (
        astropy_hampel_ultra_fast,
        astropy_hampel_vectorized_fast,
    )
    from canvod.grids.operations import add_cell_ids_to_ds_fast

    mode_name = "ULTRA-FAST" if ultra_fast_mode else "VECTORIZED"
    logger.info("=" * 60)
    logger.info("CREATING %s HAMPEL FILTERED DATA", mode_name)
    logger.info(
        "window=%.1fh sigma=%.1f min_points=%d cell_batch=%d workers=%s",
        window_hours,
        sigma_threshold,
        min_points,
        cell_batch_size,
        n_workers or "auto",
    )

    # --- guard ---
    if not workflow_instance._force_or_skip("processing", force_recreate):
        return None

    # --- setup grid & load data ---
    try:
        from canvod.store.grid_adapters.complete_grid_vod_workflow import (
            store_grid_to_vod_store,
        )

        grid = create_hemigrid(grid_type="equal_area", angular_resolution=2)
        store_grid_to_vod_store(
            grid=grid,
            store_path=workflow_instance.vod_store_path,
            grid_name="equal_area_2deg",
        )
    except ImportError:
        logger.warning(
            "canvod-store grid_adapters not available; skipping grid persistence"
        )

    logger.info("Loading dataset for fast Hampel processing")
    with workflow_instance.vod_store.readonly_session(branch="main") as session:
        vod_ds = xr.open_zarr(session.store, group="reference_01_canopy_01")

    vod_ds_complete = vod_ds.sel(epoch=slice(start_date, end_date))

    if "cell_id_equal_area_2deg" not in vod_ds_complete:
        grid = create_hemigrid(grid_type="equal_area", angular_resolution=2)
        vod_ds_complete = add_cell_ids_to_ds_fast(
            vod_ds_complete, grid, "equal_area_2deg"
        )

    logger.info("Dataset loaded: %s", dict(vod_ds_complete.sizes))

    # --- filter ---
    t0 = time.time()
    if ultra_fast_mode:
        vod_ds_filtered = astropy_hampel_ultra_fast(
            vod_ds_complete,
            window_hours=window_hours,
            sigma_threshold=sigma_threshold,
            min_points=min_points,
        )
    else:
        vod_ds_filtered = astropy_hampel_vectorized_fast(
            vod_ds_complete,
            window_hours=window_hours,
            sigma_threshold=sigma_threshold,
            min_points=min_points,
            cell_batch_size=cell_batch_size,
            n_workers=n_workers,
        )
    logger.info("%s filtering completed in %.1f s", mode_name, time.time() - t0)

    # --- persist ---
    snapshot_id = workflow_instance._persist_filtered(
        vod_ds_filtered, f"{mode_name} Hampel filtering"
    )
    logger.info("%s Hampel complete. Snapshot: %s", mode_name, snapshot_id)
    return snapshot_id


# ---------------------------------------------------------------------------
# Convenience / introspection
# ---------------------------------------------------------------------------


def get_workflow_for_store(vod_store_path: Path | str) -> AdaptedVODWorkflow:
    """Create an :class:`AdaptedVODWorkflow` for the given store path.

    Parameters
    ----------
    vod_store_path : Path or str
        Path to VOD Icechunk store.

    Returns
    -------
    AdaptedVODWorkflow

    """
    return AdaptedVODWorkflow(vod_store_path)


def check_processed_data_status(vod_store_path: Path | str) -> dict[str, Any]:
    """Introspect the store for Hampel-filtered data.

    Parameters
    ----------
    vod_store_path : Path or str
        Path to VOD Icechunk store.

    Returns
    -------
    dict
        Keys: ``has_processing_branch``, ``has_hampel_data``,
        ``temporal_coverage`` (tuple of dates or ``None``),
        ``data_size`` (dict or ``None``).

    """
    workflow = AdaptedVODWorkflow(vod_store_path)

    status: dict[str, Any] = {
        "has_processing_branch": False,
        "has_hampel_data": False,
        "temporal_coverage": None,
        "data_size": None,
    }

    try:
        with workflow.vod_store.readonly_session(branch="processing") as session:
            hampel_ds = xr.open_zarr(
                session.store,
                group="reference_01_canopy_01_hampel_filtered",
                consolidated=False,
            )

        status["has_processing_branch"] = True
        status["has_hampel_data"] = True
        status["temporal_coverage"] = (
            pd.to_datetime(hampel_ds.epoch.min().values).date(),
            pd.to_datetime(hampel_ds.epoch.max().values).date(),
        )
        status["data_size"] = dict(hampel_ds.sizes)

    except Exception as exc:
        status["error"] = str(exc)

    return status
