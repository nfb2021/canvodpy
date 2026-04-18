"""VOD computation helper with explicit strategies.

Provides two strategies for computing Vegetation Optical Depth:

- ``compute_day()`` — inline per-day computation from in-memory datasets.
  Calls ``.load()`` on Dask-backed datasets to materialize into main-process
  memory, then computes VOD single-threaded.  For daily cron / Airflow.

- ``compute_bulk()`` — bulk computation from an Icechunk RINEX store.
  Opens groups directly, reads the full time range, deduplicates/sorts,
  then computes.  For backfill or reprocessing.

Both strategies share core logic via ``_compute_and_write()``.

Examples
--------
Per-day (inside a processing loop)::

    vod = VodComputer(site)

    with site.pipeline() as pipeline:
        for date_key, datasets in pipeline.process_range(...):
            vod.compute_day(datasets, "canopy_01_vs_reference_01")

Bulk reprocessing::

    vod = VodComputer(site)
    vod.compute_bulk("canopy_01_vs_reference_01")

Custom calculator::

    vod = VodComputer(site, calculator="dual_freq_vod")
    vod.compute_day(datasets, "canopy_01_vs_reference_01")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from canvodpy.logging import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    import xarray as xr

    from canvodpy.api import Site


class VodComputer:
    """Helper for VOD computation with explicit inline and bulk strategies.

    Parameters
    ----------
    site : Site
        Site object providing access to stores and configuration.
    calculator : str
        Registered VOD calculator name (default ``"tau_omega"``).
        Future calculators register via ``VODFactory.register()``.
    rechunk : dict, optional
        Chunk specification for VOD output before writing.
        Default: ``{"epoch": 34560, "sid": -1}``.
    """

    def __init__(
        self,
        site: Site,
        calculator: str = "tau_omega",
        rechunk: dict[str, int] | None = None,
    ) -> None:
        self._site = site
        self._calculator_name = calculator
        self._rechunk = rechunk or {"epoch": 34560, "sid": -1}
        self.log = get_logger(__name__).bind(site=site.name, calculator=calculator)

    def compute_day(
        self,
        datasets: dict[str, xr.Dataset],
        analysis_name: str,
        *,
        write: bool = True,
    ) -> xr.Dataset:
        """Compute VOD inline from per-day datasets.

        Materializes Dask-backed datasets into memory via ``.load()``,
        then computes VOD single-threaded.

        Parameters
        ----------
        datasets : dict[str, xr.Dataset]
            Per-receiver datasets keyed by receiver name (e.g. from
            ``process_range()``).  May be Dask-backed.
        analysis_name : str
            Configured VOD analysis name (e.g. ``"canopy_01_vs_reference_01"``).
        write : bool
            If ``True`` (default), write result to the VOD store.

        Returns
        -------
        xr.Dataset
            Computed VOD dataset.

        Raises
        ------
        KeyError
            If the required receiver groups are not in ``datasets``.
        ValueError
            If ``analysis_name`` is not configured.
        """
        log = self.log.bind(analysis=analysis_name)
        log.info("compute_day_started")

        canopy_ds, sky_ds = self._extract_pair(datasets, analysis_name)

        # Materialize into memory (safe for single-day data ~1.5GB)
        canopy_ds = canopy_ds.load()
        sky_ds = sky_ds.load()

        log.info(
            "datasets_loaded",
            canopy_epochs=canopy_ds.sizes.get("epoch", 0),
            sky_epochs=sky_ds.sizes.get("epoch", 0),
        )

        return self._compute_and_write(canopy_ds, sky_ds, analysis_name, write=write)

    def compute_bulk(
        self,
        analysis_name: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        write: bool = True,
    ) -> xr.Dataset:
        """Compute VOD from the RINEX Icechunk store.

        Opens canopy and reference groups directly from the store,
        reads the full (or filtered) time range, then computes VOD.

        Parameters
        ----------
        analysis_name : str
            Configured VOD analysis name.
        start : datetime, optional
            Start of time range filter.
        end : datetime, optional
            End of time range filter.
        write : bool
            If ``True`` (default), write result to the VOD store.

        Returns
        -------
        xr.Dataset
            Computed VOD dataset.
        """
        import xarray as xr

        log = self.log.bind(analysis=analysis_name)
        log.info("compute_bulk_started", start=str(start), end=str(end))

        analysis_cfg = self._get_analysis_config(analysis_name)
        canopy_name = analysis_cfg.canopy_receiver
        ref_name = analysis_cfg.reference_receiver

        store = self._site.rinex_store

        with store.readonly_session() as session:
            canopy_ds = xr.open_zarr(
                store=session.store, group=canopy_name, consolidated=False
            )
            try:
                sky_ds = xr.open_zarr(
                    store=session.store, group=ref_name, consolidated=False
                )
            except Exception:
                # Paired naming: reference_01_canopy_01 instead of reference_01
                paired_name = f"{ref_name}_{canopy_name}"
                log.info("group_fallback", original=ref_name, paired=paired_name)
                sky_ds = xr.open_zarr(
                    store=session.store, group=paired_name, consolidated=False
                )

        # Time-range filter
        if start or end:
            canopy_ds = self._filter_time(canopy_ds, start, end)
            sky_ds = self._filter_time(sky_ds, start, end)

        # Deduplicate and sort by epoch
        canopy_ds = self._dedup_sort(canopy_ds)
        sky_ds = self._dedup_sort(sky_ds)

        # Load into memory for computation
        canopy_ds = canopy_ds.load()
        sky_ds = sky_ds.load()

        log.info(
            "bulk_data_loaded",
            canopy_epochs=canopy_ds.sizes.get("epoch", 0),
            sky_epochs=sky_ds.sizes.get("epoch", 0),
        )

        return self._compute_and_write(canopy_ds, sky_ds, analysis_name, write=write)

    # ------------------------------------------------------------------
    # Shared core
    # ------------------------------------------------------------------

    def _compute_and_write(
        self,
        canopy_ds: xr.Dataset,
        sky_ds: xr.Dataset,
        analysis_name: str,
        *,
        write: bool = True,
    ) -> xr.Dataset:
        """Compute VOD and optionally write to the VOD store.

        Parameters
        ----------
        canopy_ds : xr.Dataset
            In-memory canopy dataset.
        sky_ds : xr.Dataset
            In-memory sky/reference dataset.
        analysis_name : str
            Analysis name for store write.
        write : bool
            Whether to persist the result.

        Returns
        -------
        xr.Dataset
            VOD dataset.
        """
        from canvodpy.factories import VODFactory

        calculator = VODFactory.create(
            self._calculator_name,
            canopy_ds=canopy_ds,
            sky_ds=sky_ds,
        )

        vod_ds = calculator.calculate_vod()

        self.log.info(
            "vod_computed",
            analysis=analysis_name,
            variables=list(vod_ds.data_vars),
        )

        if write:
            self._write_to_store(vod_ds, analysis_name)

        return vod_ds

    def _write_to_store(
        self,
        vod_ds: xr.Dataset,
        analysis_name: str,
    ) -> None:
        """Write VOD dataset to the site's VOD store."""
        # Clear encodings that may conflict with Zarr write
        for var in vod_ds.data_vars:
            vod_ds[var].encoding.clear()
        for coord in vod_ds.coords:
            vod_ds[coord].encoding.clear()

        # Rechunk for efficient storage
        vod_ds = vod_ds.chunk(self._rechunk)

        self._site._site.store_vod_analysis(
            vod_dataset=vod_ds,
            analysis_name=analysis_name,
        )

        self.log.info("vod_written_to_store", analysis=analysis_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_pair(
        self,
        datasets: dict[str, xr.Dataset],
        analysis_name: str,
    ) -> tuple[xr.Dataset, xr.Dataset]:
        """Extract canopy and sky datasets from a dict of receiver datasets."""
        analysis_cfg = self._get_analysis_config(analysis_name)
        canopy_name = analysis_cfg.canopy_receiver
        ref_name = analysis_cfg.reference_receiver

        if canopy_name not in datasets:
            raise KeyError(
                f"Canopy receiver '{canopy_name}' not in datasets. "
                f"Available: {list(datasets.keys())}"
            )
        if ref_name not in datasets:
            paired_name = f"{ref_name}_{canopy_name}"
            if paired_name in datasets:
                self.log.info(
                    "extract_pair_fallback", original=ref_name, paired=paired_name
                )
                ref_name = paired_name
            else:
                raise KeyError(
                    f"Reference receiver '{ref_name}' (also tried '{paired_name}') "
                    f"not in datasets. Available: {list(datasets.keys())}"
                )

        return datasets[canopy_name], datasets[ref_name]

    def _get_analysis_config(self, analysis_name: str) -> Any:
        """Get the VodAnalysisConfig for the given analysis name."""
        analyses = self._site.vod_analyses
        if analysis_name not in analyses:
            raise ValueError(
                f"VOD analysis '{analysis_name}' not configured. "
                f"Available: {list(analyses.keys())}"
            )
        return analyses[analysis_name]

    @staticmethod
    def _filter_time(
        ds: xr.Dataset,
        start: datetime | None,
        end: datetime | None,
    ) -> xr.Dataset:
        """Filter dataset by epoch time range."""
        import numpy as np
        import pandas as pd

        # Convert bounds to match the epoch dtype.
        # Newer NumPy (2.x / Python 3.14) no longer auto-coerces datetime.datetime
        # to datetime64 in comparisons, so we must convert explicitly.
        if np.issubdtype(ds.epoch.dtype, np.integer):
            # Icechunk epoch stored as int64 nanoseconds
            start = pd.Timestamp(start).value if start is not None else None  # ty: ignore[invalid-assignment]
            end = pd.Timestamp(end).value if end is not None else None  # ty: ignore[invalid-assignment]
        else:
            # datetime64[ns] — plain datetime.datetime is not comparable on NumPy 2.x
            start = np.datetime64(start, "ns") if start is not None else None  # ty: ignore[invalid-assignment]
            end = np.datetime64(end, "ns") if end is not None else None  # ty: ignore[invalid-assignment]

        if start is not None:
            ds = ds.sel(epoch=ds.epoch >= start)
        if end is not None:
            ds = ds.sel(epoch=ds.epoch <= end)
        return ds

    @staticmethod
    def _dedup_sort(ds: xr.Dataset) -> xr.Dataset:
        """Deduplicate and sort dataset by epoch."""
        import numpy as np

        _, unique_idx = np.unique(ds.epoch.values, return_index=True)
        ds = ds.isel(epoch=np.sort(unique_idx))
        return ds.sortby("epoch")

    def __repr__(self) -> str:
        return (
            f"VodComputer(site={self._site.name!r}, "
            f"calculator={self._calculator_name!r})"
        )
