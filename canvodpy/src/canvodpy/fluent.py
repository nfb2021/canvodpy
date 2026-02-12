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
from canvodpy.globals import KEEP_RNX_VARS
from canvodpy.logging import get_logger

if TYPE_CHECKING:
    import xarray as xr


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

        # Configuration
        self._site = Site(site) if isinstance(site, str) else site
        self._reader_name = reader
        self._grid_type = grid_type
        self._vod_calculator_name = vod_calculator
        self._keep_vars = keep_vars or KEEP_RNX_VARS

        self.log = get_logger(__name__).bind(site=self._site.name)

    # ------------------------------------------------------------------
    # Steps (deferred)
    # ------------------------------------------------------------------

    @step
    def read(self, date: str, receivers: list[str] | None = None) -> FluentWorkflow:
        """Load RINEX observations for *date*.

        Parameters
        ----------
        date : str
            Date in ``YYYYDOY`` format (e.g. ``"2025001"``).
        receivers : list[str], optional
            Receiver names to load.  If ``None``, all active receivers
            for the site are loaded.
        """
        receiver_list = receivers or list(self._site.active_receivers.keys())
        log = self.log.bind(date=date)

        for name in receiver_list:
            path = self._site._site.get_rinex_path(name, date)
            reader_obj = ReaderFactory.create(self._reader_name, path=path)
            ds = reader_obj.read()

            # Filter variables
            if self._keep_vars:
                drop = [v for v in ds.data_vars if v not in set(self._keep_vars)]
                if drop:
                    ds = ds.drop_vars(drop)

            self._datasets[name] = ds
            log.info("read_complete", receiver=name)

        return self  # never reached (decorator returns self), but aids type checkers

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
            self._datasets[name] = add_cell_ids_to_ds_fast(ds, self._grid)

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
            self._site.vod_store.write_group("vod_result", self._vod_result)
        else:
            for name, ds in self._datasets.items():
                self.log.info("to_store_dataset", receiver=name)
                self._site.rinex_store.write_group(name, ds)
        return self

    @terminal
    def plot(self) -> Any:
        """Execute the plan and visualise the result."""
        from canvod.viz import HemisphereVisualizer

        data = self._vod_result if self._vod_result is not None else self._datasets
        viz = HemisphereVisualizer()
        return viz.plot_2d(data)

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
