"""Logging utilities for canvodpy.

Uses structlog for LLM-friendly log output. Scientists can feed logs to
LLMs for debugging assistance.

Examples
--------
Get a logger:

    >>> from canvodpy.logging import get_logger
    >>> log = get_logger(__name__)
    >>> log.info("processing_started", site="ExampleSite", date="2025001")

Setup logging (optional, already configured by default):

    >>> from canvodpy.logging import setup_logging
    >>> setup_logging()
"""

import structlog

from canvodpy.logging.logging_config import configure_logging
from canvodpy.logging.run_context import get_run_id, reset_run_id, set_run_id
from canvodpy.logging.stage_timer import emit_run_summary, stage_timer, timed_stage

# Alias for API compatibility
setup_logging = configure_logging


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a logger instance for a module.

    Parameters
    ----------
    name : str
        Logger name, typically `__name__` of the module.

    Returns
    -------
    structlog.stdlib.BoundLogger
        Configured logger instance.

    Examples
    --------
    >>> log = get_logger(__name__)
    >>> log.info("event_name", key="value", count=42)
    """
    return structlog.get_logger(name)


__all__ = [
    "configure_logging",
    "emit_run_summary",
    "get_logger",
    "get_run_id",
    "reset_run_id",
    "set_run_id",
    "setup_logging",
    "stage_timer",
    "timed_stage",
]
