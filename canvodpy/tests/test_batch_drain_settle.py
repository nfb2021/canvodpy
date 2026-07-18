"""Tests for the batch-drain settle gap (VOD-write-crash investigation, 2026-07-18).

The first VOD write of a multi-day batch is the first thing to touch a
network-mounted store immediately after that batch's loky pool finishes a
sustained multi-process RINEX I/O burst -- confirmed by log evidence that no
worker process is still running at write time (``flat_loky_complete`` fires
before VOD write starts), so this isn't a concurrency problem, but OS/SMB
connection state from the just-finished burst may not have settled yet.
``_should_settle_after_batch_drain`` is the pure decision logic behind an
opt-in pause between drain and the first VOD write; it's tested in isolation
since ``_process_multi_day_batches`` itself has no lightweight test harness.
"""

from __future__ import annotations

from canvodpy.orchestrator.pipeline import _should_settle_after_batch_drain

from canvod.config.models import ProcessingParams


def test_default_config_does_not_settle() -> None:
    assert ProcessingParams.model_fields["batch_drain_settle_seconds"].default is None


def test_unconfigured_never_settles() -> None:
    assert _should_settle_after_batch_drain(None, tasks_succeeded=100) is False


def test_configured_settles_when_tasks_succeeded() -> None:
    assert _should_settle_after_batch_drain(15.0, tasks_succeeded=100) is True


def test_configured_but_zero_tasks_succeeded_does_not_settle() -> None:
    # A batch where everything failed never reaches a VOD write -- nothing
    # to settle before.
    assert _should_settle_after_batch_drain(15.0, tasks_succeeded=0) is False


def test_zero_seconds_configured_does_not_settle() -> None:
    assert _should_settle_after_batch_drain(0.0, tasks_succeeded=100) is False
