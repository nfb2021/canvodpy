"""Resource monitoring for pipeline processing."""

from __future__ import annotations

import threading
import time

import psutil

from canvodpy.logging import get_logger
from canvodpy.logging.run_context import get_run_id, set_run_id

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


class ResourceSampler:
    """Periodic background sampler for memory/CPU/disk I/O.

    ``MemoryMonitor.log_memory_stats`` only snapshots once per batch. This
    runs as a daemon thread emitting one ``resource_sample`` event every
    ``interval_seconds`` for the whole run (including time spent outside
    batch boundaries, e.g. aux data fetch/interpolation), so a wall-clock
    slowdown seen in stage_timing events can be correlated against actual
    resource pressure instead of assumed (dev/todo_later.md
    perf-degradation investigation, 2026-07-14).

    Parameters
    ----------
    interval_seconds : float
        Seconds between samples.
    """

    def __init__(self, interval_seconds: float = 30.0) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_id = get_run_id()

    def start(self) -> None:
        """Start sampling in a daemon thread. Safe to call once per run."""
        self._run_id = get_run_id()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="resource-sampler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the sampler thread to stop and wait for it to exit."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run_loop(self) -> None:
        # Contextvars don't cross thread boundaries automatically -- carry
        # run_id in explicitly, matching _worker_init_with_run_id's pattern
        # for loky workers (pipeline.py).
        if self._run_id:
            set_run_id(self._run_id)

        proc = psutil.Process()
        try:
            prev_io = psutil.disk_io_counters()
        except Exception:
            prev_io = None
        sample_index = 0

        while not self._stop.wait(self.interval_seconds):
            sample_index += 1
            t0 = time.perf_counter()
            try:
                mem = psutil.virtual_memory()
                main_rss_gb = proc.memory_info().rss / (1024**3)

                children_rss_gb = 0.0
                try:
                    for child in proc.children(recursive=True):
                        try:
                            children_rss_gb += child.memory_info().rss / (1024**3)
                        except psutil.NoSuchProcess, psutil.AccessDenied:
                            continue
                except Exception:
                    pass

                read_mb = write_mb = None
                try:
                    io = psutil.disk_io_counters()
                    if io is not None and prev_io is not None:
                        read_mb = (io.read_bytes - prev_io.read_bytes) / (1024**2)
                        write_mb = (io.write_bytes - prev_io.write_bytes) / (1024**2)
                    prev_io = io
                except Exception:
                    pass

                logger.info(
                    "resource_sample",
                    duration_seconds=round(time.perf_counter() - t0, 4),
                    sample_index=sample_index,
                    available_gb=round(mem.available / (1024**3), 2),
                    used_percent=round(mem.percent, 1),
                    main_rss_gb=round(main_rss_gb, 3),
                    children_rss_gb=round(children_rss_gb, 3),
                    cpu_percent=psutil.cpu_percent(interval=None),
                    disk_read_mb=round(read_mb, 2) if read_mb is not None else None,
                    disk_write_mb=round(write_mb, 2) if write_mb is not None else None,
                )
            except Exception:
                logger.debug("resource_sample_failed", exc_info=True)
