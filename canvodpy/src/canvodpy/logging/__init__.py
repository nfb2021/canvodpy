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


__all__ = ["configure_logging", "get_logger", "setup_logging"]
