"""Logging configuration for canvodpy with dual-output system.

This module configures structured logging with multiple outputs:
- Machine-readable JSON logs for analysis
- Human-readable text logs for debugging
- Component-specific logs for isolation
- Log rotation for manageable file sizes
"""

import logging
import multiprocessing
import os
import sys
from collections.abc import Callable
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from canvod.utils.config import load_config


def _process_log_suffix() -> str:
    """Return a filename suffix identifying the current OS process.

    Empty in the main process (unchanged filenames, backwards compatible).
    Non-empty in any other process (e.g. a loky/ProcessPoolExecutor worker),
    since ``RotatingFileHandler``/``TimedRotatingFileHandler`` are only safe
    within a single process — multiple processes rotating the same physical
    file race on ``os.rename()``. Giving each process its own file set
    removes the shared path entirely instead of trying to coordinate rotation
    across processes.
    """
    if multiprocessing.current_process().name == "MainProcess":
        return ""
    return f".{os.getpid()}"


def _setup_log_directories(base_dir: Path) -> dict[str, Path]:
    """Create organized log directory structure.

    Parameters
    ----------
    base_dir : Path
        Base logging directory (e.g., .logs/)

    Returns
    -------
    dict[str, Path]
        Dictionary of log directories by category.
    """
    dirs = {
        "machine": base_dir / "machine",
        "human": base_dir / "human",
        "component": base_dir / "component",
        "archive": base_dir / "archive",
    }

    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    return dirs


def _create_human_renderer() -> Callable[..., Any]:
    """Create human-readable formatter function.

    Returns
    -------
    Callable
        Processor function for human-readable logs.
    """

    def human_format(logger, name, event_dict):
        """Format log entry in traditional log format."""
        timestamp = event_dict.get("timestamp", "")
        level = event_dict.get("level", "INFO").upper()
        event = event_dict.get("event", "")

        # Extract context fields
        context_parts = []
        for key, value in sorted(event_dict.items()):
            # Skip internal/standard fields
            if key in ("timestamp", "level", "event", "logger", "exc_info"):
                continue
            if key.startswith("_"):
                continue
            context_parts.append(f"{key}={value}")

        context = f" [{', '.join(context_parts)}]" if context_parts else ""

        return f"{timestamp} {level:8s} {event}{context}"

    return human_format


def _create_error_renderer() -> Callable[..., Any]:
    """Create detailed error formatter with stack traces.

    Returns
    -------
    Callable
        Processor function for error logs with full context.
    """

    def error_format(logger, name, event_dict):
        """Format error log entry with full details."""
        timestamp = event_dict.get("timestamp", "")
        level = event_dict.get("level", "INFO").upper()
        event = event_dict.get("event", "")
        logger_name = event_dict.get("logger", "")

        # Build header
        lines = [
            f"{'=' * 80}",
            f"{timestamp} {level} [{logger_name}]",
            f"Event: {event}",
        ]

        # Add context fields
        context_items = []
        for key, value in sorted(event_dict.items()):
            if key in (
                "timestamp",
                "level",
                "event",
                "logger",
                "exc_info",
                "exception",
            ):
                continue
            if key.startswith("_"):
                continue
            context_items.append(f"  {key}: {value}")

        if context_items:
            lines.append("Context:")
            lines.extend(context_items)

        # Add exception if present
        exc_info = event_dict.get("exc_info")
        exception = event_dict.get("exception")
        if exception:
            lines.append("Exception:")
            lines.append(exception)
        elif exc_info:
            lines.append(f"Exception Info: {exc_info}")

        lines.append("")  # Blank line between errors
        return "\n".join(lines)

    return error_format


class ErrorFilter(logging.Filter):
    """Filter that only passes ERROR and CRITICAL level logs."""

    def filter(self, record):
        """Return True only for ERROR/CRITICAL levels."""
        return record.levelno >= logging.ERROR


class PerformanceFilter(logging.Filter):
    """Filter that only passes performance-related logs."""

    def filter(self, record):
        """Return True for logs with timing/performance data."""
        # Check if log has performance indicators
        if hasattr(record, "duration_sec") or hasattr(record, "duration"):
            return True
        if hasattr(record, "msg") and isinstance(record.msg, dict):
            msg = record.msg
            return any(
                key in msg
                for key in [
                    "duration_sec",
                    "duration_seconds",
                    "duration",
                    "elapsed_time",
                    "processing_time",
                    "size_mb",
                    "throughput",
                    "throughput_files_per_sec",
                ]
            )
        return False


class ComponentFilter(logging.Filter):
    """Filter that only passes logs from specific component."""

    def __init__(self, component_name: str):
        """Initialize filter for specific component.

        Parameters
        ----------
        component_name : str
            Name of component to filter (e.g., "processor", "auxiliary")
        """
        super().__init__()
        self.component_name = component_name

    def filter(self, record):
        """Return True only for logs from this component."""
        # Check logger name
        if self.component_name in record.name:
            return True

        # Check if log message dict has component field
        if (
            hasattr(record, "msg")
            and isinstance(record.msg, dict)
            and record.msg.get("component") == self.component_name
        ):
            return True

        # Check if record has component attribute (set by ProcessorFormatter)
        return hasattr(record, "component") and record.component == self.component_name


def configure_logging(logfile: Path | None = None) -> structlog.BoundLogger:
    """Configure structlog with dual-output system.

    Creates organized logging structure:
    - machine/full.json - Complete JSON logs for analysis
    - human/main.log - Traditional readable logs
    - Console output for warnings/errors

    All file handlers include log rotation.

    Parameters
    ----------
    logfile : Path, optional
        Legacy parameter for backwards compatibility. Now used to determine
        base log directory. Defaults to LOG_FILE.

    Returns
    -------
    structlog.BoundLogger
        Configured structlog logger.
    """
    if logfile is None:
        try:
            logfile = load_config().processing.logging.get_log_file()
        except Exception:
            # Fallback when config system isn't available (e.g. CI, tests)
            logfile = Path.cwd() / ".logs" / "canvodpy.log"

    # Set up directory structure
    base_dir = logfile.parent
    log_dirs = _setup_log_directories(base_dir)

    # Distinguishes worker-process log files from the main process's, so
    # concurrent processes never share a physical path (see _process_log_suffix).
    suffix = _process_log_suffix()

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors = [
        timestamper,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Renderers
    console_renderer = structlog.dev.ConsoleRenderer()
    json_renderer = structlog.processors.JSONRenderer()

    # Reset root logger
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)  # Ensure root accepts all levels

    # ========================================================================
    # HANDLER 1: Console (stdout) - Warnings and errors only
    # ========================================================================
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
    )
    console_handler.setFormatter(console_formatter)

    # ========================================================================
    # HANDLER 2: Machine JSON - Complete structured logs with rotation
    # ========================================================================
    machine_log = log_dirs["machine"] / f"full{suffix}.json"
    machine_handler = RotatingFileHandler(
        machine_log,
        maxBytes=100 * 1024 * 1024,  # 100MB max per file
        backupCount=10,  # Keep 10 rotated files
        encoding="utf-8",
    )
    machine_handler.setLevel(logging.DEBUG)  # Capture everything
    machine_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer,
        ],
    )
    machine_handler.setFormatter(machine_formatter)

    # ========================================================================
    # HANDLER 3: Human-readable - Traditional logs with rotation
    # ========================================================================
    human_log = log_dirs["human"] / f"main{suffix}.log"
    human_handler = TimedRotatingFileHandler(
        human_log,
        when="midnight",  # Rotate at midnight
        interval=1,  # Daily rotation
        backupCount=30,  # Keep 30 days
        encoding="utf-8",
    )
    human_handler.setLevel(logging.INFO)
    human_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _create_human_renderer(),
        ],
    )
    human_handler.setFormatter(human_formatter)

    # ========================================================================
    # HANDLER 4: Errors Only - Detailed error logs with stack traces
    # ========================================================================
    error_log = log_dirs["human"] / f"errors{suffix}.log"
    error_handler = RotatingFileHandler(
        error_log,
        maxBytes=50 * 1024 * 1024,  # 50MB max per file
        backupCount=5,  # Keep 5 rotated files
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(ErrorFilter())
    error_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _create_error_renderer(),
        ],
    )
    error_handler.setFormatter(error_formatter)

    # ========================================================================
    # HANDLER 5: Performance Metrics - Timing and throughput data
    # ========================================================================
    perf_log = log_dirs["machine"] / f"performance{suffix}.json"
    perf_handler = RotatingFileHandler(
        perf_log,
        maxBytes=50 * 1024 * 1024,  # 50MB max per file
        backupCount=10,  # Keep 10 rotated files
        encoding="utf-8",
    )
    perf_handler.setLevel(logging.DEBUG)
    perf_handler.addFilter(PerformanceFilter())
    perf_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer,
        ],
    )
    perf_handler.setFormatter(perf_formatter)

    # ========================================================================
    # HANDLER 6-8: Component-specific logs
    # ========================================================================
    component_handlers = []
    for component_name in ["processor", "auxiliary", "icechunk"]:
        comp_log = log_dirs["component"] / f"{component_name}{suffix}.log"
        comp_handler = TimedRotatingFileHandler(
            comp_log,
            when="midnight",
            interval=1,
            backupCount=7,  # Keep 1 week
            encoding="utf-8",
        )
        comp_handler.setLevel(logging.DEBUG)
        comp_handler.addFilter(ComponentFilter(component_name))
        comp_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _create_human_renderer(),
            ],
        )
        comp_handler.setFormatter(comp_formatter)
        component_handlers.append(comp_handler)

    # Register all handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(machine_handler)
    root_logger.addHandler(human_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(perf_handler)
    for handler in component_handlers:
        root_logger.addHandler(handler)

    # Structlog config
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger("gnssvodpy")
    # Ensure the underlying stdlib logger accepts all levels
    logging.getLogger("gnssvodpy").setLevel(logging.DEBUG)

    return logger


# Global base logger
LOGGER = configure_logging()


def get_file_logger(fname: Path) -> structlog.BoundLogger:
    """Return logger bound with parent/parent/file path.

    Parameters
    ----------
    fname : Path
        File path to include in the log context.

    """
    try:
        depth = load_config().processing.logging.log_path_depth
    except Exception:
        depth = 6
    rel_path = Path(*fname.parts[-depth:])
    return LOGGER.bind(file=str(rel_path))
