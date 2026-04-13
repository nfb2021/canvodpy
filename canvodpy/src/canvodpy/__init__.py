"""canvodpy: GNSS Vegetation Optical Depth Analysis.

A modern Python package for processing GNSS data and calculating
vegetation optical depth (VOD) using the tau-omega model.

Quick Start
-----------
Three levels of API to match your needs:

**Level 1: Simple (one-liners)**
    >>> from canvodpy import process_date, calculate_vod
    >>> data = process_date("Rosalia", "2025001")
    >>> vod = calculate_vod("Rosalia", "canopy_01", "reference_01", "2025001")

**Level 2: Object-oriented (more control)**
    >>> from canvodpy import Site, Pipeline
    >>> site = Site("Rosalia")
    >>> pipeline = site.pipeline()
    >>> data = pipeline.process_date("2025001")
    >>> vod = pipeline.calculate_vod("canopy_01", "reference_01", "2025001")

**Level 3: Low-level (full control)**
    >>> from canvod.store import GnssResearchSite
    >>> from canvod.vod import VODCalculator
    >>> # Direct access to all internals

Community Extensions
--------------------
Extend canvodpy with custom components using factories:

    >>> from canvodpy import VODFactory
    >>> from my_package import CustomCalculator
    >>> VODFactory.register("custom", CustomCalculator)
    >>> calc = VODFactory.create("custom", **params)

Package Structure
-----------------
- canvod.readers - RINEX file parsing
- canvod.auxiliary - Auxiliary data (ephemeris, clocks)
- canvod.grids - Hemisphere grid structures
- canvod.vod - VOD calculation algorithms
- canvod.viz - 2D/3D visualization
- canvod.store - Icechunk data storage

Configuration
-------------
Site configurations are stored in ``config/sites.yaml``.
Default variables and settings are in `globals.py`.

Examples
--------
Process one day of data:
    >>> from canvodpy import process_date
    >>> data = process_date("Rosalia", "2025001")

Process a week:
    >>> from canvodpy import Pipeline
    >>> pipeline = Pipeline("Rosalia")
    >>> for date, datasets in pipeline.process_range("2025001", "2025007"):
    ...     print(f"Processed {date}")

Calculate and visualize VOD:
    >>> from canvodpy import calculate_vod
    >>> from canvod.viz import HemisphereVisualizer
    >>> vod = calculate_vod("Rosalia", "canopy_01", "reference_01", "2025001")
    >>> viz = HemisphereVisualizer()
    >>> fig = viz.plot_2d(vod)

"""

from canvodpy.api import (
    Pipeline,
    Site,
    calculate_vod,
    preview_processing,
    process_date,
)

# Factories (for community extensions)
from canvodpy.factories import (
    AugmentationFactory,
    GridFactory,
    ReaderFactory,
    VODFactory,
)

# Fluent workflow API (deferred execution)
from canvodpy.fluent import FluentWorkflow

# Functional API (Airflow-compatible)
from canvodpy.functional import (
    assign_grid_cells,
    assign_grid_cells_to_file,
    augment_with_ephemeris,
    calculate_vod_to_file,
    create_grid,
    create_grid_to_file,
    read_rinex,
    read_rinex_to_file,
)

# Logging (for all users)
from canvodpy.logging import get_logger, setup_logging

# VOD computation helper
from canvodpy.vod_computer import VodComputer

# New workflow API
from canvodpy.workflow import VODWorkflow


def workflow(site: str, **kwargs) -> FluentWorkflow:
    """Create a fluent workflow with deferred execution.

    Parameters
    ----------
    site : str
        Site name (e.g. ``"Rosalia"``).
    **kwargs
        Forwarded to :class:`FluentWorkflow`.

    Returns
    -------
    FluentWorkflow

    Examples
    --------
    >>> import canvodpy
    >>> result = (canvodpy.workflow("Rosalia")
    ...     .read("2025001")
    ...     .preprocess()
    ...     .grid()
    ...     .vod("canopy_01", "reference_01")
    ...     .result())
    """
    return FluentWorkflow(site, **kwargs)


# ============================================================================
# Level 3 API: Re-export subpackages for advanced users
# ============================================================================


# Lazy import subpackages on access to avoid circular dependencies
def __getattr__(name: str):
    """Lazy import subpackages when accessed."""
    _subpackages = {
        "auxiliary": "canvod.auxiliary",
        "grids": "canvod.grids",
        "readers": "canvod.readers",
        "store": "canvod.store",
        "viz": "canvod.viz",
        "vod": "canvod.vod",
    }

    if name in _subpackages:
        import importlib
        import sys

        module = importlib.import_module(_subpackages[name])
        # Cache the imported module (can't use globals() as it's shadowed by canvodpy.globals)
        setattr(sys.modules[__name__], name, module)
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================================
# Version
# ============================================================================

__version__ = "0.1.0"

# ============================================================================
# Public API
# ============================================================================

__all__ = [  # noqa: RUF022
    # Version
    "__version__",
    # High-level API (most users)
    "Site",
    "Pipeline",
    "process_date",
    "calculate_vod",
    "preview_processing",
    # New workflow API
    "VODWorkflow",
    # Fluent workflow API
    "FluentWorkflow",
    "workflow",
    # Functional API (notebooks & Airflow)
    "read_rinex",
    "read_rinex_to_file",
    "create_grid",
    "create_grid_to_file",
    "assign_grid_cells",
    "assign_grid_cells_to_file",
    "calculate_vod_to_file",
    # Logging
    "setup_logging",
    "get_logger",
    # Factories (community extensions)
    "ReaderFactory",
    "GridFactory",
    "VODFactory",
    "AugmentationFactory",
    # Subpackages (advanced users)
    "readers",
    "aux",
    "grids",
    "vod",
    "viz",
    "store",
]


# ============================================================================
# Auto-register built-in components
# ============================================================================


def _register_builtin_components() -> None:
    """
    Register built-in component implementations.

    Called automatically on package import. Registers:
    - Rnxv3Obs reader (rinex3)
    - EqualAreaGridBuilder (equal_area)
    - TauOmegaZerothOrder calculator (tau_omega)

    Notes
    -----
    Uses lazy imports to avoid loading heavy dependencies unless needed.
    """
    log = get_logger(__name__)

    # Set ABC classes for validation
    ReaderFactory._set_abc_class()
    GridFactory._set_abc_class()
    VODFactory._set_abc_class()
    AugmentationFactory._set_abc_class()

    try:
        from canvod.readers import Rnxv3Obs

        ReaderFactory.register("rinex3", Rnxv3Obs)
    except ImportError:
        log.debug("canvod-readers not available, skipping reader registration")

    try:
        from canvod.readers.rinex import Rnxv3StrippedObs

        ReaderFactory.register("rinex3_stripped", Rnxv3StrippedObs)
    except ImportError:
        log.debug("Rnxv3StrippedObs not available, skipping registration")

    try:
        from canvod.readers.sbf import SbfReader

        ReaderFactory.register("sbf", SbfReader)
    except ImportError:
        log.debug("SbfReader not available, skipping sbf reader registration")

    try:
        # register rinex2
        from canvod.readers.rinex import Rnxv2Obs

        ReaderFactory.register("rinex2", Rnxv2Obs)
    except ImportError:
        log.debug("Rnxv2Obs reader not available, skipping rinex2 reader registration")

    try:
        from canvod.readers.nmea import NmeaObs

        ReaderFactory.register("nmea", NmeaObs)
    except ImportError:
        log.debug("NmeaObs reader not available, skipping nmea reader registration")

    try:
        from canvod.grids import EqualAreaBuilder

        GridFactory.register("equal_area", EqualAreaBuilder)
    except ImportError:
        log.debug("canvod-grids not available, skipping grid registration")

    try:
        from canvod.vod.calculator import TauOmegaZerothOrder

        VODFactory.register("tau_omega", TauOmegaZerothOrder)
    except ImportError:
        log.debug("canvod-vod not available, skipping VOD registration")

    log.info("builtin_components_registered")


# Auto-register on import
_register_builtin_components()
