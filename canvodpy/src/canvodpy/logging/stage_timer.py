"""Lightweight, always-on performance tracking.

Deliberately not full telemetry: no spans, no collectors, no exporters, no
extra dependency (see ``canvodpy/utils/telemetry.py``'s removal -- an
OpenTelemetry-based tracer that was dead weight because ``opentelemetry``
was never installed). ``stage_timer()`` replaces the previously ragged mix
of field names (``duration_seconds``, ``processing_time_min``,
``hampel_processing_time_s``, ...) scattered across the codebase with one
canonical event (``stage_timing``), and a small in-process accumulator
produces an end-of-run summary -- what a human skims first, and what an
agent uses to see how far a run got before it died (the crash-handling path
in ``cli/run.py`` calls ``emit_run_summary`` too, so a partial summary
exists even for a run that later failed).

Caveat: the accumulator is per-process. ``stage_timer`` calls made inside a
``ProcessPoolExecutor``/loky worker accumulate in that worker's own
interpreter, not the parent's -- they still reach the log (each worker
writes its own per-PID log file, see ``logging_config.py``'s
``_process_log_suffix``), but won't roll into the parent process's
``run_summary``. Solving that would require exactly the cross-process
collector machinery this module exists to avoid.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypeVar

import structlog

from canvodpy.logging.run_context import get_run_id

log = structlog.get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_lock = threading.Lock()
# {run_id: {stage: {"count": float, "total_seconds": float, "errors": float}}}
_run_stats: dict[str, dict[str, dict[str, float]]] = {}

_NO_RUN_ID = "_no_run_id"


@contextmanager
def stage_timer(stage: str, **context: Any) -> Generator[None]:
    """Time a block of code and emit one canonical ``stage_timing`` event.

    Emits on both success and failure (``status="error"`` on the latter)
    before any exception propagates, so a run summary can still be produced
    for a run that later crashes.

    Parameters
    ----------
    stage : str
        Canonical stage name (e.g. ``"rinex.process_file"``,
        ``"icechunk.write"``).
    **context
        Extra fields attached to the emitted event (e.g. ``file=...``,
        ``site=...``).
    """
    start = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.perf_counter() - start
        log.info(
            "stage_timing",
            stage=stage,
            duration_seconds=round(duration, 3),
            status=status,
            **context,
        )
        _record(stage, duration, status)


def timed_stage(stage: str, **context: Any) -> Callable[[_F], _F]:
    """Decorator form of :func:`stage_timer`."""

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with stage_timer(stage, **context):
                return func(*args, **kwargs)

        return wrapper  # ty: ignore[invalid-return-type]

    return decorator


def _record(stage: str, duration: float, status: str) -> None:
    run_id = get_run_id() or _NO_RUN_ID
    with _lock:
        stats = _run_stats.setdefault(run_id, {})
        entry = stats.setdefault(
            stage, {"count": 0.0, "total_seconds": 0.0, "errors": 0.0}
        )
        entry["count"] += 1
        entry["total_seconds"] += duration
        if status == "error":
            entry["errors"] += 1


def emit_run_summary(**context: Any) -> None:
    """Emit a ``run_summary`` event: per-stage breakdown for the current run.

    Called at the end of a successful run and also from the crash-handling
    path in ``cli/run.py``, so a partial summary exists even for a run that
    later failed -- showing how far it got before dying.
    """
    run_id = get_run_id() or _NO_RUN_ID
    with _lock:
        stages = {
            stage: dict(entry) for stage, entry in _run_stats.get(run_id, {}).items()
        }

    total_seconds = sum(entry["total_seconds"] for entry in stages.values())
    log.info(
        "run_summary",
        stages={
            stage: {
                "count": int(entry["count"]),
                "total_seconds": round(entry["total_seconds"], 3),
                "errors": int(entry["errors"]),
            }
            for stage, entry in stages.items()
        },
        total_seconds=round(total_seconds, 3),
        **context,
    )


def reset_run_stats(run_id: str | None = None) -> None:
    """Clear accumulated stage stats for ``run_id`` (or all, if None).

    Call after emitting a run's summary to avoid unbounded growth of the
    in-process accumulator across many runs in a long-lived interpreter
    (e.g. a scheduler that reuses the process across invocations).
    """
    with _lock:
        if run_id is None:
            _run_stats.clear()
        else:
            _run_stats.pop(run_id, None)
