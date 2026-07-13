"""
OpenTelemetry instrumentation utilities for canvodpy.

This module provides helpers for manual instrumentation of canvodpy operations
using OpenTelemetry traces and metrics. Use these utilities to track:
- Icechunk write performance
- RINEX processing duration
- VOD calculation timing
- Auxiliary data operations

The instrumentation is designed to work seamlessly with the auto-instrumentation
provided by OpenTelemetry, and integrates with the existing structlog logging.

Usage
-----
Wrap operations with trace context managers::

    from canvodpy.utils.telemetry import trace_icechunk_write

    with trace_icechunk_write(group_name="2025213", dataset_size_mb=45.2):
        dataset.to_zarr(store_path, group=group_name, mode="a")

Or use the generic tracer for custom operations::

    from canvodpy.utils.telemetry import trace_operation

    with trace_operation("custom_operation", attributes={"key": "value"}):
        # ... your code ...
        pass
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

try:
    from opentelemetry import metrics, trace  # type: ignore[unresolved-import]
    from opentelemetry.trace import (  # type: ignore[unresolved-import]
        Status,
        StatusCode,
    )

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


# Get tracer and meter (only if OpenTelemetry is available)
if OTEL_AVAILABLE:
    tracer = trace.get_tracer(__name__, "1.0.0")
    meter = metrics.get_meter(__name__, "1.0.0")

    # Define metrics for key operations
    icechunk_write_duration = meter.create_histogram(
        name="canvodpy.icechunk.write.duration",
        unit="s",
        description="Duration of icechunk write operations in seconds",
    )

    icechunk_write_size = meter.create_histogram(
        name="canvodpy.icechunk.write.size",
        unit="MB",
        description="Size of data written to icechunk in megabytes",
    )

    rinex_processing_duration = meter.create_histogram(
        name="canvodpy.rinex.processing.duration",
        unit="s",
        description="Duration of RINEX file processing in seconds",
    )

    aux_download_duration = meter.create_histogram(
        name="canvodpy.auxiliary.download.duration",
        unit="s",
        description="Duration of auxiliary file downloads in seconds",
    )

    aux_preprocessing_duration = meter.create_histogram(
        name="canvodpy.auxiliary.preprocessing.duration",
        unit="s",
        description="Duration of auxiliary data preprocessing in seconds",
    )

    vod_calculation_duration = meter.create_histogram(
        name="canvodpy.vod.calculation.duration",
        unit="s",
        description="Duration of VOD calculations in seconds",
    )
else:
    tracer = None
    meter = None


@contextmanager
def trace_operation(
    operation_name: str,
    attributes: dict[str, Any] | None = None,
    record_duration: bool = True,
) -> Generator[Any]:
    """
    Context manager for tracing operations with OpenTelemetry.

    Creates a span for the operation and optionally records its duration.
    If OpenTelemetry is not available, this becomes a no-op.

    Parameters
    ----------
    operation_name : str
        Name of the operation (becomes span name).
    attributes : dict, optional
        Attributes to attach to the span.
    record_duration : bool, default True
        Whether to record duration_seconds attribute.

    Yields
    ------
    span
        The OpenTelemetry span object (or None if OTel unavailable).

    Examples
    --------
    >>> with trace_operation("data_processing", attributes={"file": "test.dat"}):
    ...     process_data()
    """
    if not OTEL_AVAILABLE or tracer is None:
        # No-op if OpenTelemetry not available
        yield None
        return

    with tracer.start_as_current_span(operation_name) as span:
        # Add attributes to span
        if attributes:
            for key, value in attributes.items():
                # Convert to string if necessary for OTel compatibility
                if value is not None:
                    span.set_attribute(
                        str(key),
                        str(value)
                        if not isinstance(value, (int, float, bool))
                        else value,
                    )

        start = time.perf_counter()

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            if record_duration:
                duration = time.perf_counter() - start
                span.set_attribute("duration_seconds", round(duration, 3))


@contextmanager
def trace_icechunk_write(
    group_name: str,
    dataset_size_mb: float | None = None,
    num_variables: int | None = None,
) -> Generator[Any]:
    """
    Trace an icechunk write operation.

    Parameters
    ----------
    group_name : str
        Name of the zarr group being written.
    dataset_size_mb : float, optional
        Size of the dataset in megabytes.
    num_variables : int, optional
        Number of variables in the dataset.

    Yields
    ------
    span
        The OpenTelemetry span object.

    Examples
    --------
    >>> size_mb = dataset.nbytes / 1024 / 1024
    >>> with trace_icechunk_write("2025213", dataset_size_mb=size_mb):
    ...     dataset.to_zarr(store_path, group="2025213", mode="a")
    """
    attributes: dict[str, Any] = {"icechunk.group": group_name}
    if dataset_size_mb is not None:
        attributes["icechunk.size_mb"] = round(dataset_size_mb, 2)
    if num_variables is not None:
        attributes["icechunk.num_variables"] = num_variables

    with trace_operation("icechunk.write", attributes=attributes) as span:
        start = time.perf_counter()
        try:
            yield span
        finally:
            duration = time.perf_counter() - start

            # Record metrics if available
            if OTEL_AVAILABLE and icechunk_write_duration is not None:
                icechunk_write_duration.record(
                    duration,
                    attributes={"group": group_name},
                )

                if dataset_size_mb is not None and icechunk_write_size is not None:
                    icechunk_write_size.record(
                        dataset_size_mb,
                        attributes={"group": group_name},
                    )


@contextmanager
def trace_rinex_processing(
    file_name: str,
    site: str | None = None,
    date: str | None = None,
) -> Generator[Any]:
    """
    Trace RINEX file processing.

    Parameters
    ----------
    file_name : str
        Name of the RINEX file being processed.
    site : str, optional
        Site name.
    date : str, optional
        Date key (e.g., "2025213").

    Yields
    ------
    span
        The OpenTelemetry span object.

    Examples
    --------
    >>> with trace_rinex_processing("ract213a00.25o", site="ExampleSite"):
    ...     df = process_rinex_file(file_path)
    """
    attributes = {"rinex.file": file_name}
    if site is not None:
        attributes["site"] = site
    if date is not None:
        attributes["date"] = date

    with trace_operation("rinex.process_file", attributes=attributes) as span:
        start = time.perf_counter()
        try:
            yield span
        finally:
            duration = time.perf_counter() - start

            # Record metrics if available
            if OTEL_AVAILABLE and rinex_processing_duration is not None:
                metric_attrs = {}
                if site is not None:
                    metric_attrs["site"] = site
                rinex_processing_duration.record(duration, attributes=metric_attrs)


@contextmanager
def trace_aux_preprocessing(
    date: str,
    operation: str | None = None,
) -> Generator[Any]:
    """
    Trace auxiliary data preprocessing.

    Parameters
    ----------
    date : str
        Date key being preprocessed.
    operation : str, optional
        Specific operation (e.g., "hermite_interpolation").

    Yields
    ------
    span
        The OpenTelemetry span object.

    Examples
    --------
    >>> with trace_aux_preprocessing("2025213", operation="hermite"):
    ...     aux_data = preprocess_auxiliary(date)
    """
    attributes = {"aux.date": date}
    if operation is not None:
        attributes["aux.operation"] = operation

    with trace_operation("auxiliary.preprocessing", attributes=attributes) as span:
        start = time.perf_counter()
        try:
            yield span
        finally:
            duration = time.perf_counter() - start

            # Record metrics if available
            if OTEL_AVAILABLE and aux_preprocessing_duration is not None:
                aux_preprocessing_duration.record(duration, attributes={"date": date})


@contextmanager
def trace_vod_calculation(
    operation: str,
    site: str | None = None,
    date: str | None = None,
) -> Generator[Any]:
    """
    Trace VOD calculation.

    Parameters
    ----------
    operation : str
        Type of VOD operation (e.g., "tau_omega", "grid_interpolation").
    site : str, optional
        Site name.
    date : str, optional
        Date key.

    Yields
    ------
    span
        The OpenTelemetry span object.

    Examples
    --------
    >>> with trace_vod_calculation("tau_omega", site="ExampleSite"):
    ...     vod_result = calculate_vod(data)
    """
    attributes = {"vod.operation": operation}
    if site is not None:
        attributes["site"] = site
    if date is not None:
        attributes["date"] = date

    with trace_operation("vod.calculate", attributes=attributes) as span:
        start = time.perf_counter()
        try:
            yield span
        finally:
            duration = time.perf_counter() - start

            # Record metrics if available
            if OTEL_AVAILABLE and vod_calculation_duration is not None:
                metric_attrs = {"operation": operation}
                if site is not None:
                    metric_attrs["site"] = site
                vod_calculation_duration.record(duration, attributes=metric_attrs)


def is_tracing_enabled() -> bool:
    """
    Check if OpenTelemetry tracing is available and enabled.

    Returns
    -------
    bool
        True if tracing is available, False otherwise.
    """
    return OTEL_AVAILABLE and tracer is not None
