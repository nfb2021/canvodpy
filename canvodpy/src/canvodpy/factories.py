"""
Component factories for extensible VOD workflow.

Factories enforce ABC compliance and provide Pydantic validation for
community-contributed readers, grids, and calculators.

Examples
--------
Register and create a reader:

    >>> from canvodpy.factories import ReaderFactory
    >>> from canvod.readers import Rnxv3Obs
    >>>
    >>> ReaderFactory.register("rinex3", Rnxv3Obs)
    >>> reader = ReaderFactory.create("rinex3", path="data.rnx")

Create a grid:

    >>> from canvodpy.factories import GridFactory
    >>> grid = GridFactory.create(
    ...     "equal_area",
    ...     angular_resolution=5.0,
    ...     cutoff_theta=75.0,
    ... )

Community extension:

    >>> from canvodpy.factories import VODFactory
    >>> from my_package import MLVODCalculator
    >>>
    >>> VODFactory.register("ml_vod", MLVODCalculator)
    >>> calc = VODFactory.create("ml_vod", model_path="model.pt")
"""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Generic, TypeVar

from canvodpy.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=ABC)


class ComponentFactory(Generic[T]):
    """
    Generic factory for creating validated components.

    Enforces ABC compliance and validates kwargs at creation time.

    Type Parameters
    ---------------
    T : type, bound=ABC
        The abstract base class that all components must inherit from.

    Notes
    -----
    This is a generic factory base class. Use specialized subclasses:
    ReaderFactory, GridFactory, VODFactory, AugmentationFactory.
    """

    _registry: ClassVar[dict[str, type[T]]] = {}
    _abc_class: ClassVar[type[ABC] | None] = None

    @classmethod
    def register(cls, name: str, component_class: type[T]) -> None:
        """
        Register a component implementation.

        Parameters
        ----------
        name : str
            Unique identifier for this component (e.g., "rinex3").
        component_class : type[T]
            Component class that inherits from the required ABC.

        Raises
        ------
        TypeError
            If component_class doesn't inherit from the required ABC.

        Examples
        --------
        >>> ReaderFactory.register("rinex3", Rnxv3Obs)
        """
        if cls._abc_class and not issubclass(component_class, cls._abc_class):
            msg = (
                f"{component_class.__name__} must inherit from "
                f"{cls._abc_class.__name__}"
            )
            raise TypeError(msg)

        cls._registry[name] = component_class
        log.info(
            "component_registered",
            factory=cls.__name__,
            name=name,
            component=component_class.__name__,
        )

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> T:
        """
        Create a component instance.

        Parameters
        ----------
        name : str
            Registered component name.
        **kwargs : Any
            Component initialization parameters (validated by Pydantic).

        Returns
        -------
        T
            Component instance.

        Raises
        ------
        ValueError
            If component name not registered.
        ValidationError
            If kwargs don't match component requirements (Pydantic).

        Examples
        --------
        >>> reader = ReaderFactory.create("rinex3", path="data.rnx")
        >>> grid = GridFactory.create(
        ...     "equal_area", angular_resolution=5.0
        ... )
        """
        if name not in cls._registry:
            available = list(cls._registry.keys())
            msg = (
                f"Component '{name}' not registered in {cls.__name__}. "
                f"Available: {available}"
            )
            raise ValueError(msg)

        component_class = cls._registry[name]
        log.debug(
            "component_creating",
            factory=cls.__name__,
            name=name,
            component=component_class.__name__,
        )

        # Pydantic validation happens here
        return component_class(**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        """
        List all registered component names.

        Returns
        -------
        list[str]
            Registered component identifiers.

        Examples
        --------
        >>> ReaderFactory.list_available()
        ['rinex3', 'rinex2', 'custom_reader']
        """
        return list(cls._registry.keys())


class ReaderFactory(ComponentFactory):
    """
    Factory for GNSS data readers.

    All registered readers must inherit from `GNSSDataReader` ABC.

    Examples
    --------
    >>> from canvod.readers import Rnxv3Obs
    >>> ReaderFactory.register("rinex3", Rnxv3Obs)
    >>> reader = ReaderFactory.create("rinex3", path="data.rnx")
    >>> data = reader.read()
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.readers.base import GNSSDataReader

            cls._abc_class = GNSSDataReader


class GridFactory(ComponentFactory):
    """
    Factory for grid builders.

    All registered builders must inherit from `BaseGridBuilder` ABC.

    Examples
    --------
    >>> from canvod.grids import EqualAreaBuilder
    >>> GridFactory.register("equal_area", EqualAreaBuilder)
    >>> grid = GridFactory.create(
    ...     "equal_area",
    ...     angular_resolution=5.0,
    ...     cutoff_theta=75.0,
    ... )
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.grids.core.grid_builder import BaseGridBuilder

            cls._abc_class = BaseGridBuilder


class VODFactory(ComponentFactory):
    """
    Factory for VOD calculators.

    All registered calculators must inherit from `VODCalculator` ABC.

    Examples
    --------
    >>> from canvod.vod import TauOmegaZerothOrder
    >>> VODFactory.register("tau_omega", TauOmegaZerothOrder)
    >>> calc = VODFactory.create(
    ...     "tau_omega",
    ...     canopy_ds=canopy,
    ...     sky_ds=sky,
    ... )
    >>> vod = calc.calculate_vod()
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.vod.calculator import VODCalculator

            cls._abc_class = VODCalculator


class AugmentationFactory(ComponentFactory):
    """
    Factory for data augmentation steps.

    All registered steps must inherit from `AugmentationStep` ABC.

    Examples
    --------
    >>> from canvod.auxiliary.augmentation import HampelFilter
    >>> AugmentationFactory.register("hampel", HampelFilter)
    >>> step = AugmentationFactory.create(
    ...     "hampel",
    ...     window_size=5,
    ...     n_sigma=3.0,
    ... )
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.auxiliary.augmentation import AugmentationStep

            cls._abc_class = AugmentationStep
