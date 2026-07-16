"""Shared retry-with-backoff wrapper for Icechunk store I/O.

``icechunk.IcechunkError`` wraps object-store errors -- including transient
network drops on shared/mounted storage (os error 103 ECONNABORTED, seen in
production against an NFS-style share; dev/perf_degradation_findings_2026_
07_15.md) -- but is not a subclass of OSError/RuntimeError/ValueError, so it
escapes a plain ``except (OSError, RuntimeError, ValueError)`` uncaught.
Used by both the RINEX ingest path (``orchestrator/pipeline.py``) and the
VOD store write path (``cli/run.py``) -- both hit the same store, over the
same network mount, so both need the same retry treatment.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable

import icechunk

STORE_ERROR_TYPES = (OSError, RuntimeError, ValueError, icechunk.IcechunkError)
STORE_RETRY_BACKOFF_SECONDS = (2.0, 8.0, 30.0)


def call_with_store_retries[T](fn: Callable[[], T], *, logger, **log_ctx: object) -> T:
    """Retry a store read/write with backoff before giving up.

    The final attempt is unguarded -- its exception propagates to the
    caller's own ``except``/``log.exception`` so existing log event names
    and give-up behavior are unchanged; this only adds retries in front of
    that.
    """
    for attempt, backoff in enumerate(STORE_RETRY_BACKOFF_SECONDS):
        try:
            return fn()
        except STORE_ERROR_TYPES as exc:
            logger.warning(
                "store_op_retry",
                attempt=attempt + 1,
                backoff_seconds=backoff,
                error=str(exc),
                **log_ctx,
            )
            _time.sleep(backoff)
    return fn()
