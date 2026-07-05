"""Fluent workflow API with deferred execution.

Provides a chainable, lazy pipeline where steps are recorded and
executed only when a terminal method is called.

Examples
--------
Process RINEX data and compute VOD:

    >>> import canvodpy
    >>> result = (canvodpy.workflow("Rosalia")
    ...     .read("2025001")
    ...     .preprocess(agency="COD")
    ...     .grid("equal_area", angular_resolution=5.0)
    ...     .vod("canopy_01", "reference_01")
    ...     .result())

Preview the execution plan without running it:

    >>> plan = (canvodpy.workflow("Rosalia")
    ...     .read("2025001")
    ...     .preprocess()
    ...     .grid()
    ...     .vod("canopy_01", "reference_01")
    ...     .explain())

"""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Any

from canvodpy.api import Site
from canvodpy.factories import GridFactory, ReaderFactory, VODFactory
from canvodpy.logging import get_logger

if TYPE_CHECKING:
    import xarray as xr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concat_epoch_datasets(datasets: list) -> Any:
    """Concatenate xarray Datasets along 'epoch' without xr.concat overhead.

    Direct numpy concatenation bypasses xarray's alignment checks and
    intermediate copies. Safe when all datasets share the same 'sid' axis,
    which is guaranteed after pad_to_global_sid=True (the default).
    """
    import numpy as np
    import xarray as xr

    if len(datasets) == 1:
        return datasets[0]

    first = datasets[0]
    merged_vars: dict = {}
    for var in first.data_vars:
        epoch_ax = list(first[var].dims).index("epoch")
        merged_vars[var] = (
            first[var].dims,
            np.concatenate([ds[var].values for ds in datasets], axis=epoch_ax),
        )

    coords: dict = {}
    for k, coord in first.coords.items():
        if "epoch" in coord.dims:
            ax = list(coord.dims).index("epoch")
            coords[k] = (
                coord.dims,
                np.concatenate([ds.coords[k].values for ds in datasets], axis=ax),
            )
        else:
            coords[k] = coord

    return xr.Dataset(merged_vars, coords=coords, attrs=first.attrs)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def step(method):
    """Record a pipeline step for deferred execution.

    The decorated method is not called immediately. Instead, a reference
    to the method and its arguments is appended to ``self._plan``.
    The method returns ``self`` so calls can be chained.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        self._plan.append((method, args, kwargs))
        return self

    return wrapper


def terminal(method):
    """Execute all recorded steps, then run the terminal method.

    Iterates over ``self._plan``, calling each recorded step in order,
    then invokes the decorated method and returns its result.  The plan
    is cleared after execution so the workflow can be reused.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        for fn, a, kw in self._plan:
            fn(self, *a, **kw)
        self._plan.clear()
        return method(self, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# FluentWorkflow
# ---------------------------------------------------------------------------


class FluentWorkflow:
    """Chainable, deferred-execution workflow for VOD analysis.

    Parameters
    ----------
    site : str or Site
        Site name or :class:`~canvodpy.api.Site` object.
    reader : str
        Registered reader name (default ``"rinex3"``).
    grid_type : str
        Registered grid type (default ``"equal_area"``).
    vod_calculator : str
        Registered VOD calculator (default ``"tau_omega"``).
    keep_vars : list[str], optional
        RINEX variables to retain.  Defaults to :data:`KEEP_RNX_VARS`.
    """

    def __init__(
        self,
        site: str | Site,
        reader: str = "rinex3",
        grid_type: str = "equal_area",
        vod_calculator: str = "tau_omega",
        keep_vars: list[str] | None = None,
    ) -> None:
        self._plan: list[tuple] = []

        # State populated by steps
        self._datasets: dict[str, xr.Dataset] = {}
        self._vod_result: xr.Dataset | None = None
        self._grid: Any = None
        self._last_date: str | None = None

        # Configuration
        self._site = Site(site) if isinstance(site, str) else site
        self._reader_name = reader
        self._grid_type = grid_type
        self._vod_calculator_name = vod_calculator
        if keep_vars is None:
            from canvod.utils.config import load_config

            keep_vars = load_config().processing.processing.keep_rnx_vars
        self._keep_vars = keep_vars

        self.log = get_logger(__name__).bind(site=self._site.name)

    # ------------------------------------------------------------------
    # Steps (deferred)
    # ------------------------------------------------------------------

    @step
    def read(self, date: str, receivers: list[str] | None = None) -> FluentWorkflow:
        """Load RINEX observations for *date*.

        Uses :class:`~canvod.virtualiconvname.FilenameMapper` for file
        discovery when naming config is available, preventing duplicate
        files (e.g. daily + sub-daily) from being concatenated.  Falls
        back to naive glob when naming config is missing.

        Parameters
        ----------
        date : str
            Date in ``YYYYDOY`` format (e.g. ``"2025001"``).
        receivers : list[str], optional
            Receiver names to load.  If ``None``, all active receivers
            for the site are loaded.
        """
        self._last_date = date
        receiver_list = receivers or list(self._site.active_receivers.keys())
        log = self.log.bind(date=date)

        from pathlib import Path

        from canvod.utils.config import load_config

        config = load_config()
        site_cfg = config.sites.sites[self._site.name]
        data_root = Path(site_cfg.gnss_site_data_root)

        year = int(date[:4])
        doy = int(date[4:])

        for name in receiver_list:
            recv_cfg = site_cfg.receivers[name]
            recv_base = data_root / recv_cfg.directory

            rnx_files = self._discover_files(
                site_cfg,
                recv_cfg,
                name,
                recv_base,
                year,
                doy,
                log,
            )
            if not rnx_files:
                continue

            datasets_for_recv = []
            for fpath in rnx_files:
                reader_obj = ReaderFactory.create(self._reader_name, fpath=fpath)
                ds = reader_obj.to_ds(write_global_attrs=True)

                # Filter variables
                if self._keep_vars:
                    drop = [v for v in ds.data_vars if v not in set(self._keep_vars)]
                    if drop:
                        ds = ds.drop_vars(drop)

                datasets_for_recv.append(ds)

            if datasets_for_recv:
                self._datasets[name] = _concat_epoch_datasets(datasets_for_recv)
                log.info("read_complete", receiver=name, files=len(datasets_for_recv))

        return self  # never reached (decorator returns self), but aids type checkers

    @staticmethod
    def _discover_files(
        site_cfg,
        recv_cfg,
        recv_name,
        recv_base,
        year,
        doy,
        log,
    ) -> list:
        """Discover RINEX files using FilenameMapper or fallback glob."""

        # Try FilenameMapper when naming config is available
        if site_cfg.naming and recv_cfg.naming:
            try:
                from canvod.virtualiconvname import (
                    FilenameMapper,
                    ReceiverNamingConfig,
                    SiteNamingConfig,
                )

                mapper = FilenameMapper(
                    site_naming=SiteNamingConfig(**site_cfg.naming),
                    receiver_naming=ReceiverNamingConfig(**recv_cfg.naming),
                    receiver_type=recv_cfg.type,
                    receiver_base_dir=recv_base,
                )
                vfs = mapper.discover_for_date(year, doy)

                # Check for overlaps
                overlaps = FilenameMapper.detect_overlaps(vfs)
                if overlaps:
                    overlap_msgs = [
                        f"  {a.canonical_str} <-> {b.canonical_str}"
                        for a, b in overlaps[:5]
                    ]
                    log.warning(
                        "temporal_overlaps_detected",
                        receiver=recv_name,
                        overlaps=overlap_msgs,
                    )

                if vfs:
                    log.info(
                        "files_discovered",
                        receiver=recv_name,
                        n_files=len(vfs),
                        method="FilenameMapper",
                    )
                    return [vf.physical_path for vf in vfs]

                log.warning("no_files_via_mapper", receiver=recv_name)
                return []

            except Exception as exc:
                log.warning(
                    "filename_mapper_failed_fallback_to_glob",
                    receiver=recv_name,
                    error=str(exc),
                )

        # Fallback: naive glob (no naming config)
        doy_dir = f"{year % 100:02d}{doy:03d}"
        recv_dir = recv_base / doy_dir
        if not recv_dir.exists():
            log.warning("no_data_dir", receiver=recv_name, path=str(recv_dir))
            return []

        rnx_files = sorted(recv_dir.glob("*.25o"))
        if not rnx_files:
            log.warning("no_rinex_files", receiver=recv_name, path=str(recv_dir))
            return []

        log.info(
            "files_discovered",
            receiver=recv_name,
            n_files=len(rnx_files),
            method="glob_fallback",
        )
        return rnx_files

    @step
    def preprocess(self, agency: str = "COD") -> FluentWorkflow:
        """Apply auxiliary preprocessing to loaded datasets.

        Parameters
        ----------
        agency : str
            Analysis centre for auxiliary products (default ``"COD"``).
        """
        log = self.log.bind(agency=agency)

        for name, ds in self._datasets.items():
            try:
                from canvod.auxiliary import preprocess_aux_for_interpolation

                ds = preprocess_aux_for_interpolation(ds)
                self._datasets[name] = ds
                log.info("preprocess_complete", receiver=name)
            except ImportError:
                log.debug("canvod.auxiliary not available, skipping preprocessing")

        return self

    @step
    def augment(
        self,
        source: str = "final",
        agency: str = "COD",
        date: str | None = None,
    ) -> FluentWorkflow:
        """Augment loaded datasets with theta/phi from ephemeris data.

        Parameters
        ----------
        source : str
            Ephemeris source: ``"final"`` (SP3/CLK), ``"rapid"``,
            ``"broadcast"`` (SBF only).
        agency : str
            Analysis centre code (default ``"COD"``).
        date : str, optional
            Date in ``YYYYDOY`` format.  If not provided, inferred from
            the most recent ``.read()`` call.
        """
        from canvod.auxiliary.ephemeris.provider import (
            AgencyEphemerisProvider,
        )
        from canvod.utils.config import load_config

        log = self.log.bind(source=source, agency=agency)

        config = load_config()
        site_cfg = config.sites.sites[self._site.name]

        if source in ("final", "rapid"):
            provider = AgencyEphemerisProvider(
                agency=agency,
                product_type=source,
            )
            _date = date or self._last_date
            if _date:
                provider.preprocess_day(_date, site_cfg)

            from canvod.auxiliary.position.position import ECEFPosition

            for name, ds in self._datasets.items():
                try:
                    rx_pos = ECEFPosition.from_ds_metadata(ds)
                except (KeyError, ValueError):  # fmt: skip
                    log.warning(
                        "no_receiver_position",
                        receiver=name,
                    )
                    continue
                self._datasets[name] = provider.augment_dataset(
                    ds,
                    rx_pos,
                )
                log.info("augment_complete", receiver=name)
        else:
            log.warning("augment_source_not_supported", source=source)

        return self

    @step
    def grid(self, kind: str | None = None, **params: Any) -> FluentWorkflow:
        """Build a hemisphere grid and assign cell IDs to all datasets.

        Parameters
        ----------
        kind : str, optional
            Grid type override.  Defaults to the value set at init.
        **params
            Passed to :meth:`GridFactory.create` (e.g.
            ``angular_resolution=5.0``).
        """
        from canvod.grids import add_cell_ids_to_ds_fast

        grid_type = kind or self._grid_type
        builder = GridFactory.create(grid_type, **params)
        self._grid = builder.build()

        for name, ds in self._datasets.items():
            self._datasets[name] = add_cell_ids_to_ds_fast(ds, self._grid, grid_type)

        self.log.info("grid_complete", grid=grid_type, ncells=self._grid.ncells)
        return self

    @step
    def vod(self, canopy: str, reference: str) -> FluentWorkflow:
        """Compute vegetation optical depth for a receiver pair.

        Parameters
        ----------
        canopy : str
            Canopy receiver name (e.g. ``"canopy_01"``).
        reference : str
            Sky/reference receiver name (e.g. ``"reference_01"``).
        """
        canopy_ds = self._datasets[canopy]
        ref_ds = self._datasets[reference]

        calculator = VODFactory.create(
            self._vod_calculator_name,
            canopy_ds=canopy_ds,
            sky_ds=ref_ds,
        )
        self._vod_result = calculator.calculate_vod()

        self.log.info("vod_complete", canopy=canopy, reference=reference)
        return self

    # ------------------------------------------------------------------
    # Terminals (trigger execution)
    # ------------------------------------------------------------------

    @terminal
    def result(self) -> xr.Dataset | dict[str, xr.Dataset]:
        """Execute the plan and return the final data.

        Returns the VOD dataset if a ``.vod()`` step was included,
        otherwise returns the dict of per-receiver datasets.
        """
        if self._vod_result is not None:
            return self._vod_result
        return dict(self._datasets)

    @terminal
    def to_store(self) -> FluentWorkflow:
        """Execute the plan and write results to Icechunk storage."""
        if self._vod_result is not None:
            # Store VOD result — requires a store name convention
            self.log.info("to_store_vod")
            self._site.vod_store.write_or_append_group(self._vod_result, "vod_result")
        else:
            for name, ds in self._datasets.items():
                self.log.info("to_store_dataset", receiver=name)
                self._site.rinex_store.write_or_append_group(ds, name)
        return self

    @terminal
    def plot(self) -> Any:
        """Execute the plan and visualise the result."""
        from canvod.viz import HemisphereVisualizer

        viz = HemisphereVisualizer(self._grid)
        return viz.plot_2d()

    # ------------------------------------------------------------------
    # Plan inspection (does NOT execute)
    # ------------------------------------------------------------------

    def explain(self) -> list[dict[str, Any]]:
        """Return a description of the recorded plan without executing it.

        Returns
        -------
        list[dict]
            One entry per step with keys ``"step"``, ``"args"``, and
            ``"kwargs"``.
        """
        return [
            {"step": fn.__name__, "args": args, "kwargs": kwargs}
            for fn, args, kwargs in self._plan
        ]

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n = len(self._plan)
        return f"FluentWorkflow(site={self._site.name!r}, pending_steps={n})"
