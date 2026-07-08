"""High-level public API for canvodpy.

This module provides the user-friendly API that wraps proven gnssvodpy logic.

Recommended surfaces:
- Run the pipeline via the ``canvodpy`` CLI (production runs, resumable).
- Script a configured pipeline run in Python via ``Site.pipeline()``
  (``Pipeline`` class) — this is what the CLI wraps internally.
- Component-level scripting/analysis (custom readers, ephemeris source,
  grid, VOD calculator) via ``canvodpy.functional``.

``process_date()``, ``calculate_vod()``, and ``preview_processing()`` below
are deprecated convenience wrappers around ``Pipeline`` — use
``Site.pipeline()`` directly instead.

Examples
--------
Object-oriented (recommended for Python-native pipeline runs):
    >>> from canvodpy import Site, Pipeline
    >>> site = Site("Rosalia")
    >>> pipeline = site.pipeline()
    >>> data = pipeline.process_date("2025001")

Low-level (full control):
    >>> from canvod.store import GnssResearchSite
    >>> from canvodpy.processor.pipeline_orchestrator import PipelineOrchestrator
    >>> # Direct access to internals

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canvodpy._deprecation import deprecated

# Lazy imports to avoid circular dependencies

if TYPE_CHECKING:
    from collections.abc import Generator

    import xarray as xr

    from canvod.store import MyIcechunkStore
    from canvodpy.vod_computer import VodComputer


class Site:
    """User-friendly wrapper around GnssResearchSite.

    Provides a clean, modern API for site management while using
    the proven GnssResearchSite implementation internally.

    Parameters
    ----------
    name : str
        Site name from configuration (e.g., "Rosalia")

    Attributes
    ----------
    name : str
        Site name
    receivers : dict
        All configured receivers
    active_receivers : dict
        Only active receivers
    vod_analyses : dict
        Configured VOD analysis pairs
    rinex_store
        Access to RINEX data store
    vod_store
        Access to VOD results store

    Examples
    --------
    >>> site = Site("Rosalia")
    >>> print(site.receivers)
    {'canopy_01': {...}, 'reference_01': {...}}

    >>> # Create pipeline
    >>> pipeline = site.pipeline()

    >>> # Access stores
    >>> site.rinex_store.list_groups()

    """

    def __init__(self, name: str) -> None:
        # Lazy import to avoid circular dependency
        from canvod.store import GnssResearchSite

        # Use proven implementation
        self._site = GnssResearchSite(name)
        self.name = name

    @property
    def receivers(self) -> dict:
        """Get all configured receivers."""
        return self._site.receivers

    @property
    def active_receivers(self) -> dict:
        """Get only active receivers."""
        return self._site.active_receivers

    @property
    def vod_analyses(self) -> dict:
        """Get configured VOD analysis pairs."""
        return self._site.active_vod_analyses

    @property
    def vod(self) -> VodComputer:
        """Lazy VOD computation helper."""
        if not hasattr(self, "_vod_computer"):
            from canvodpy.vod_computer import VodComputer

            self._vod_computer = VodComputer(self)
        return self._vod_computer

    @property
    def rinex_store(self) -> MyIcechunkStore:
        """Access RINEX data store."""
        return self._site.rinex_store

    @property
    def vod_store(self) -> MyIcechunkStore:
        """Access VOD results store."""
        return self._site.vod_store

    def pipeline(
        self,
        keep_vars: list[str] | None = None,
        aux_agency: str | None = None,
        n_workers: int | None = None,
        dry_run: bool = False,
        days_per_batch: int | None = None,
        max_memory_gb: float | None = None,
        cpu_affinity: list[int] | None = None,
        nice_priority: int | None = None,
        threads_per_worker: int | None = None,
        show_progress: bool = True,
    ) -> Pipeline:
        """Create a processing pipeline for this site.

        All parameters default to ``None``, which means "read from config".
        Explicit values override the config.

        Reader format is configured per-receiver via ``reader_format`` in
        ``sites.yaml`` (default: ``"auto"``).

        Parameters
        ----------
        keep_vars : list[str], optional
            RINEX variables to keep. Default: from config.
        aux_agency : str, optional
            Analysis center for auxiliary data (COD, ESA, GFZ, JPL).
            Default: from config.
        n_workers : int, optional
            Number of parallel workers. Default: from config.
        dry_run : bool, default False
            If True, simulate processing without execution.
        days_per_batch : int, optional
            Number of DOYs per loky wave. Default: from config.
        max_memory_gb : float, optional
            Total RAM budget across all workers. Default: from config.
        cpu_affinity : list[int], optional
            Pin workers to specific CPU core IDs (Linux only).
            Default: from config.
        nice_priority : int, optional
            Process nice value (0=normal, 19=lowest). Default: from config.
        threads_per_worker : int, optional
            Threads per worker process. Default: from config.
        show_progress : bool, default True
            Render the per-receiver Rich progress bars. Set False when the
            caller already owns a Rich ``Live`` display (e.g. the CLI) —
            two concurrent ``Live`` instances on one terminal corrupt each
            other's output.

        Returns
        -------
        Pipeline
            Configured pipeline for this site

        Examples
        --------
        >>> site = Site("Rosalia")
        >>> pipeline = site.pipeline(n_workers=8, max_memory_gb=16)
        >>> data = pipeline.process_date("2025001")

        """
        return Pipeline(
            site=self,
            keep_vars=keep_vars,
            aux_agency=aux_agency,
            n_workers=n_workers,
            dry_run=dry_run,
            days_per_batch=days_per_batch,
            max_memory_gb=max_memory_gb,
            cpu_affinity=cpu_affinity,
            nice_priority=nice_priority,
            threads_per_worker=threads_per_worker,
            show_progress=show_progress,
        )

    def __repr__(self) -> str:
        n_receivers = len(self.active_receivers)
        n_analyses = len(self.vod_analyses)
        return f"Site('{self.name}', receivers={n_receivers}, analyses={n_analyses})"

    def __str__(self) -> str:
        return f"GNSS Site: {self.name}"


class Pipeline:
    """User-friendly wrapper around PipelineOrchestrator.

    Provides a clean API for processing workflows while using
    proven orchestrator logic internally.

    All parameters default to ``None``, which means "read from
    ``config/processing.yaml``". Explicit values override the config.

    Reader format is configured per-receiver via ``reader_format`` in
    ``sites.yaml`` (default: ``"auto"``).

    Parameters
    ----------
    site : Site or str
        Site object or site name
    keep_vars : list[str], optional
        RINEX variables to keep. Default: from config.
    aux_agency : str, optional
        Analysis center for auxiliary data. Default: from config.
    n_workers : int, optional
        Number of parallel Dask workers. Default: from config
        (``processing.n_max_threads``).
    dry_run : bool, default False
        If True, simulate without execution.
    days_per_batch : int, optional
        Calendar days to pool per processing wave. Default: from config.
    max_memory_gb : float, optional
        Total RAM budget across all workers. Default: from config.
    cpu_affinity : list[int], optional
        Pin workers to specific CPU core IDs. Default: from config.
    nice_priority : int, optional
        Process nice value (0=normal, 19=lowest). Default: from config.
    threads_per_worker : int, optional
        Threads per Dask worker process. Default: from config.
    show_progress : bool, default True
        Render the per-receiver Rich progress bars. Set False when the
        caller already owns a Rich ``Live`` display (e.g. the CLI).

    Examples
    --------
    >>> # From site object
    >>> site = Site("Rosalia")
    >>> pipeline = Pipeline(site)

    >>> # Or directly from name
    >>> pipeline = Pipeline("Rosalia")

    >>> # Process single date
    >>> data = pipeline.process_date("2025001")

    >>> # Process range
    >>> for date, datasets in pipeline.process_range("2025001", "2025007"):
    ...     print(f"Processed {date}")

    """

    def __init__(
        self,
        site: Site | str,
        keep_vars: list[str] | None = None,
        aux_agency: str | None = None,
        n_workers: int | None = None,
        dry_run: bool = False,
        days_per_batch: int | None = None,
        max_memory_gb: float | None = None,
        cpu_affinity: list[int] | None = None,
        nice_priority: int | None = None,
        threads_per_worker: int | None = None,
        show_progress: bool = True,
    ) -> None:
        # Handle both Site object and string
        if isinstance(site, str):
            site = Site(site)

        self.site = site

        from canvod.utils.config import load_config

        config = load_config()
        proc = config.processing.params

        # All params default to config values; explicit values override
        if keep_vars is None:
            keep_vars = proc.keep_gnss_observables
        if aux_agency is None:
            aux_agency = config.processing.aux_data.agency
        if days_per_batch is None:
            days_per_batch = proc.days_per_batch

        # Resource resolution: explicit n_workers overrides everything,
        # otherwise use resolve_resources() which respects resource_mode.
        if n_workers is not None:
            # Caller explicitly set n_workers → manual-like behavior
            if max_memory_gb is None:
                max_memory_gb = proc.max_memory_gb
            if cpu_affinity is None:
                cpu_affinity = proc.cpu_affinity
            if nice_priority is None:
                nice_priority = proc.nice_priority
            if threads_per_worker is None:
                threads_per_worker = proc.threads_per_worker
        else:
            # No explicit n_workers → use resource_mode from config
            resources = proc.resolve_resources()
            n_workers = resources["n_workers"]
            if max_memory_gb is None:
                max_memory_gb = resources["max_memory_gb"]
            if cpu_affinity is None:
                cpu_affinity = resources["cpu_affinity"]
            if nice_priority is None:
                nice_priority = resources["nice_priority"]
            if threads_per_worker is None:
                threads_per_worker = resources["threads_per_worker"]

        self.keep_vars = keep_vars
        self.aux_agency = aux_agency
        self.n_workers = n_workers
        self.dry_run = dry_run
        self.days_per_batch = days_per_batch

        # Setup logging
        from canvodpy.logging import get_logger

        self.log = get_logger(__name__).bind(
            site=site.name,
            component="pipeline",
        )

        # Lazy import to avoid circular dependency
        from canvodpy.orchestrator import PipelineOrchestrator

        # Use proven orchestrator implementation
        self._orchestrator = PipelineOrchestrator(
            site=site._site,
            n_max_workers=n_workers,
            dry_run=dry_run,
            days_per_batch=days_per_batch,
            max_memory_gb=max_memory_gb,
            cpu_affinity=cpu_affinity,
            nice_priority=nice_priority,
            threads_per_worker=threads_per_worker,
            show_progress=show_progress,
        )

        self.log.info(
            "pipeline_initialized",
            aux_agency=aux_agency,
            n_workers=n_workers,
            keep_vars=len(self.keep_vars),
            dry_run=dry_run,
            days_per_batch=days_per_batch,
            max_memory_gb=max_memory_gb,
            nice_priority=nice_priority,
            threads_per_worker=threads_per_worker,
        )

    def close(self) -> None:
        """Shut down the Dask cluster managed by the orchestrator."""
        self._orchestrator.close()

    def __enter__(self) -> Pipeline:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def process_date(self, date: str) -> dict[str, xr.Dataset]:
        """Process RINEX data for one date.

        Parameters
        ----------
        date : str
            Date in YYYYDOY format (e.g., "2025001" for Jan 1, 2025)

        Returns
        -------
        dict[str, xr.Dataset]
            Processed datasets for each receiver

        Examples
        --------
        >>> pipeline = Pipeline("Rosalia")
        >>> data = pipeline.process_date("2025001")
        >>> print(data.keys())
        dict_keys(['canopy_01', 'canopy_02', 'reference_01'])

        >>> # Access individual receiver
        >>> canopy_data = data['canopy_01']
        >>> print(canopy_data.dims)
        Dimensions: (epoch: 2880, sv: 32, ...)

        """
        log = self.log.bind(date=date)
        log.info("date_processing_started")

        # Use proven orchestrator logic
        for _date_key, datasets, _timing in self._orchestrator.process_by_date(
            keep_vars=self.keep_vars,
            start_from=date,
            end_at=date,
        ):
            log.info(
                "date_processing_complete",
                receivers=len(datasets),
                receiver_names=list(datasets.keys()),
            )
            return datasets  # Return first (only) date

        log.warning("no_data_processed", date=date)
        return {}  # No data processed

    def process_range(
        self,
        start: str,
        end: str,
    ) -> Generator[tuple[str, dict[str, xr.Dataset]]]:
        """Process RINEX data for a date range.

        Parameters
        ----------
        start : str
            Start date (YYYYDOY)
        end : str
            End date (YYYYDOY)

        Yields
        ------
        tuple[str, dict[str, xr.Dataset]]
            (date_key, datasets) for each processed date

        Examples
        --------
        >>> pipeline = Pipeline("Rosalia")
        >>> for date, datasets in pipeline.process_range("2025001", "2025007"):
        ...     print(f"Processed {date}: {len(datasets)} receivers")
        Processed 2025001: 3 receivers
        Processed 2025002: 3 receivers
        ...

        """
        # Use proven orchestrator logic
        for date_key, datasets, _timing in self._orchestrator.process_by_date(
            keep_vars=self.keep_vars,
            start_from=start,
            end_at=end,
        ):
            yield date_key, datasets

    def calculate_vod(
        self,
        canopy: str,
        reference: str,
        date: str,
        write_to_store: bool = True,
    ) -> xr.Dataset:
        """Calculate VOD for a receiver pair.

        Parameters
        ----------
        canopy : str
            Canopy receiver name (e.g., "canopy_01")
        reference : str
            Reference receiver name (e.g., "reference_01")
        date : str
            Date in YYYYDOY format

        Returns
        -------
        xr.Dataset
            VOD analysis results

        Examples
        --------
        >>> pipeline = Pipeline("Rosalia")
        >>> vod = pipeline.calculate_vod("canopy_01", "reference_01", "2025001")
        >>> print(vod.vod.mean().values)
        0.42

        """
        log = self.log.bind(date=date, canopy=canopy, reference=reference)
        log.info("vod_calculation_started")

        try:
            # Convert YYYYDOY string to a one-day time_slice for read_group
            import datetime

            from canvod.utils.tools.date_utils import YYYYDOY

            _d = YYYYDOY.from_str(date).date
            if _d is None:
                raise ValueError(f"Could not parse date from {date!r}")
            _time_slice = slice(str(_d), str(_d + datetime.timedelta(days=1)))
            # Load processed data from stores
            # canopy_data = self.site.rinex_store.read_group(canopy, date=date)
            # ref_data = self.site.rinex_store.read_group(reference, date=date)
            canopy_data = self.site.rinex_store.read_group(
                canopy, time_slice=_time_slice
            )
            try:
                ref_data = self.site.rinex_store.read_group(
                    reference, time_slice=_time_slice
                )
            except Exception:
                paired_name = f"{reference}_{canopy}"
                log.info("group_fallback", original=reference, paired=paired_name)
                ref_data = self.site.rinex_store.read_group(
                    paired_name, time_slice=_time_slice
                )

            # Lazy import to avoid circular dependency
            from canvod.vod import TauOmegaZerothOrder

            # Use proven VOD calculator
            calculator = TauOmegaZerothOrder(canopy_ds=canopy_data, sky_ds=ref_data)
            vod_results = calculator.calculate_vod()

            # Store results
            analysis_name = f"{canopy}_vs_{reference}"
            if write_to_store:
                self.site.vod_store.write_or_append_group(vod_results, analysis_name)

            log.info(
                "vod_calculation_complete",
                analysis=analysis_name,
                vod_mean=float(vod_results.vod.mean().values)
                if "vod" in vod_results
                else None,
            )
            return vod_results
        except Exception as e:
            log.error(
                "vod_calculation_failed",
                error=str(e),
                exception=type(e).__name__,
            )
            raise

    def preview(self) -> dict:
        """Preview processing plan without execution.

        Returns
        -------
        dict
            Summary of dates, receivers, and files

        Examples
        --------
        >>> pipeline = Pipeline("Rosalia")
        >>> plan = pipeline.preview()
        >>> print(f"Total files: {plan['total_files']}")

        """
        return self._orchestrator.preview_processing_plan()

    def __repr__(self) -> str:
        return (
            f"Pipeline(site='{self.site.name}', "
            f"keep_vars={len(self.keep_vars)} vars, "
            f"workers={self.n_workers}, "
            f"days_per_batch={self.days_per_batch})"
        )


# ============================================================================
# Deprecated convenience functions — use Site.pipeline() instead
# ============================================================================


@deprecated(
    "process_date() is deprecated. Use Site(site).pipeline().process_date(date) "
    "instead, or run the pipeline via the `canvodpy` CLI."
)
def process_date(
    site: str,
    date: str,
    keep_vars: list[str] | None = None,
    aux_agency: str | None = None,
    n_workers: int | None = None,
) -> dict[str, xr.Dataset]:
    """Process RINEX data for one date (convenience function).

    This is the simplest way to process GNSS data - just provide
    the site name and date. All optional parameters default to
    values from ``config/processing.yaml``.

    Parameters
    ----------
    site : str
        Site name (e.g., "Rosalia")
    date : str
        Date in YYYYDOY format (e.g., "2025001")
    keep_vars : list[str], optional
        RINEX variables to keep. Default: from config.
    aux_agency : str, optional
        Analysis center for auxiliary data. Default: from config.
    n_workers : int, optional
        Number of parallel workers. Default: from config.

    Returns
    -------
    dict[str, xr.Dataset]
        Processed datasets for each receiver

    Examples
    --------
    >>> from canvodpy import process_date
    >>> data = process_date("Rosalia", "2025001")
    >>> print(data.keys())
    dict_keys(['canopy_01', 'canopy_02', 'reference_01'])

    >>> # With custom settings
    >>> data = process_date(
    ...     "Rosalia",
    ...     "2025001",
    ...     keep_vars=["C1C", "L1C"],
    ...     aux_agency="ESA"
    ... )

    """
    with Pipeline(
        site=site,
        keep_vars=keep_vars,
        aux_agency=aux_agency,
        n_workers=n_workers,
    ) as pipeline:
        return pipeline.process_date(date)


@deprecated(
    "calculate_vod() is deprecated. Use "
    "Site(site).pipeline().calculate_vod(canopy, reference, date) instead, "
    "or run the pipeline via the `canvodpy` CLI."
)
def calculate_vod(
    site: str,
    canopy: str,
    reference: str,
    date: str,
    keep_vars: list[str] | None = None,
    aux_agency: str | None = None,
    write_to_store: bool = True,
) -> xr.Dataset:
    """Calculate VOD for a receiver pair (convenience function).

    This is the simplest way to calculate VOD - just provide
    site, receivers, and date. All optional parameters default to
    values from ``config/processing.yaml``.

    Parameters
    ----------
    site : str
        Site name
    canopy : str
        Canopy receiver name
    reference : str
        Reference receiver name
    date : str
        Date in YYYYDOY format
    keep_vars : list[str], optional
        RINEX variables to keep. Default: from config.
    aux_agency : str, optional
        Analysis center. Default: from config.

    Returns
    -------
    xr.Dataset
        VOD analysis results

    Examples
    --------
    >>> from canvodpy import calculate_vod
    >>> vod = calculate_vod(
    ...     site="Rosalia",
    ...     canopy="canopy_01",
    ...     reference="reference_01",
    ...     date="2025001"
    ... )
    >>> print(vod.vod.mean().values)
    0.42

    """
    with Pipeline(
        site=site,
        keep_vars=keep_vars,
        aux_agency=aux_agency,
    ) as pipeline:
        return pipeline.calculate_vod(
            canopy, reference, date, write_to_store=write_to_store
        )


@deprecated(
    "preview_processing() is deprecated. Use "
    "Site(site).pipeline(dry_run=True).preview() instead."
)
def preview_processing(site: str) -> dict:
    """Preview processing plan for a site (convenience function).

    Parameters
    ----------
    site : str
        Site name

    Returns
    -------
    dict
        Processing plan summary

    Examples
    --------
    >>> from canvodpy import preview_processing
    >>> plan = preview_processing("Rosalia")
    >>> print(f"Total files: {plan['total_files']}")
    Total files: 8640

    """
    with Pipeline(site, dry_run=True) as pipeline:
        return pipeline.preview()
