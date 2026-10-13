"""Store retries: only errors that can be transient are retried."""

import icechunk
import pytest
import structlog
from canvodpy.orchestrator import store_retry


class _Failing:
    """Raises ``exc`` on the first ``n`` calls, then returns ``"ok"``."""

    def __init__(self, exc: Exception, n: int) -> None:
        self.exc, self.n, self.calls = exc, n, 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.n:
            raise self.exc
        return "ok"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(store_retry._time, "sleep", lambda _s: None)


@pytest.mark.parametrize(
    "exc", [OSError("os error 103"), icechunk.IcechunkError("connection dropped")]
)
def test_transient_errors_are_retried(exc):
    fn = _Failing(exc, 2)
    log = structlog.get_logger()
    assert store_retry.call_with_store_retries(fn, logger=log) == "ok"
    assert fn.calls == 3


@pytest.mark.parametrize("exc", [ValueError("validation failed"), RuntimeError("x")])
def test_other_errors_propagate_at_once(exc):
    fn = _Failing(exc, 1)
    with pytest.raises(type(exc)):
        store_retry.call_with_store_retries(fn, logger=structlog.get_logger())
    assert fn.calls == 1
