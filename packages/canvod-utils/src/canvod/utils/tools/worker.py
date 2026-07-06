"""Worker initializer for ProcessPoolExecutor and loky pools."""

from __future__ import annotations


def _worker_init(nice: int, affinity: list[int] | None) -> None:
    """Initialize a worker process with nice priority and optional CPU affinity.

    Called as the ``initializer`` argument of ``ProcessPoolExecutor`` or loky.
    Silently ignores OS errors so pool creation never fails due to missing
    permissions (e.g. nice clamping on macOS, affinity unavailable on BSD).
    """
    import os

    if nice > 0:
        try:
            os.nice(nice)
        except AttributeError, PermissionError:
            pass
    if affinity is not None:
        try:
            import psutil

            proc = psutil.Process()
            if hasattr(proc, "cpu_affinity"):
                proc.cpu_affinity(affinity)
        except Exception:
            pass
