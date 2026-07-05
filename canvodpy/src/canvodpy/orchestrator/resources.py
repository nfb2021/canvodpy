"""Resource monitoring for pipeline processing."""

from __future__ import annotations

import psutil

from canvodpy.logging import get_logger

logger = get_logger(__name__)


class MemoryMonitor:
    """Monitor system memory and log advisory snapshots.

    Used by ``PipelineOrchestrator`` for batch-level memory logging.
    Enforcement is advisory only; worker processes are not memory-capped.

    Parameters
    ----------
    max_memory_gb : float | None
        Soft RAM limit in GB (informational only). None means no limit.

    """

    def __init__(self, max_memory_gb: float | None = None) -> None:
        self.max_memory_gb = max_memory_gb

    def available_gb(self) -> float:
        """Current available system memory in GB."""
        return psutil.virtual_memory().available / (1024**3)

    def used_percent(self) -> float:
        """Current system memory usage percentage."""
        return psutil.virtual_memory().percent

    def log_memory_stats(self, context: str = "") -> None:
        """Log current memory statistics.

        Parameters
        ----------
        context : str
            Description of when this snapshot was taken.

        """
        mem = psutil.virtual_memory()
        logger.info(
            "memory_stats",
            context=context,
            available_gb=round(mem.available / (1024**3), 2),
            used_percent=round(mem.percent, 1),
            total_gb=round(mem.total / (1024**3), 2),
        )
