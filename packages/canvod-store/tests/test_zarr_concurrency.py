"""Tests for the shared zarr async-concurrency scoping helper.

Extracted from MyIcechunkStore's icechunk-only throttle so the aux
(SP3/CLK Hermite) cache's plain-Zarr write path can share the exact same
mechanism (dev/todo_later.md §44). MyIcechunkStore's own behavior is
covered by test_write_concurrency_cap.py and is unaffected by this
extraction (verified there, unmodified).
"""

from __future__ import annotations

import zarr

from canvod.store.zarr_concurrency import scoped_zarr_concurrency


def test_none_is_a_no_op() -> None:
    before = zarr.config.get("async.concurrency")
    with scoped_zarr_concurrency(None):
        assert zarr.config.get("async.concurrency") == before


def test_scopes_concurrency_for_the_block() -> None:
    with scoped_zarr_concurrency(2):
        assert zarr.config.get("async.concurrency") == 2


def test_reverts_after_the_block() -> None:
    before = zarr.config.get("async.concurrency")
    with scoped_zarr_concurrency(3):
        pass
    assert zarr.config.get("async.concurrency") == before


def test_preserves_sibling_async_config_keys() -> None:
    # The regression this module exists to prevent from recurring:
    # zarr.config.set({"async": {"concurrency": N}}) replaces the whole
    # "async" subdict rather than merging, silently dropping sibling keys
    # (e.g. "timeout") for the scope of the block.
    before_async_cfg = dict(zarr.config.get("async"))
    assert "timeout" in before_async_cfg
    with scoped_zarr_concurrency(2):
        during = dict(zarr.config.get("async"))
        assert during["concurrency"] == 2
        assert during["timeout"] == before_async_cfg["timeout"]


def test_nested_scoping_reverts_to_the_outer_value() -> None:
    with scoped_zarr_concurrency(4):
        with scoped_zarr_concurrency(2):
            assert zarr.config.get("async.concurrency") == 2
        assert zarr.config.get("async.concurrency") == 4
