"""Tests for MyIcechunkStore's retention/maintenance capability.

dev/perf_degradation_findings_2026_07_15.md, Problem B: two bugs fixed
before shipping (expire_old_snapshots overriding safe upstream defaults to
True/True; maintenance() running garbage_collect() twice per call), plus
a new tag-based keeper scheme (create_keeper_tag). These are regression
locks against exactly those bugs, plus basic coverage of the new methods.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import zarr

from canvod.store import create_vod_store


class TestExpireOldSnapshotsDefaults:
    def test_delete_flags_default_to_false(self):
        """Regression lock: must match Icechunk's own safe defaults, not
        override them to True (the original bug)."""
        sig = inspect.signature(
            __import__(
                "canvod.store.store", fromlist=["MyIcechunkStore"]
            ).MyIcechunkStore.expire_old_snapshots
        )
        assert sig.parameters["delete_expired_branches"].default is False
        assert sig.parameters["delete_expired_tags"].default is False

    def test_default_days_is_90(self):
        """90 days (weeks-to-months cadence), not the aggressive old default."""
        store = Mock()
        store.repo = Mock()
        store.repo.expire_snapshots.return_value = set()
        store._logger = Mock()
        store.store_type = "gnss_store"

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.expire_old_snapshots(store, days=None)

        called_cutoff = store.repo.expire_snapshots.call_args.kwargs["older_than"]
        expected = datetime.now(called_cutoff.tzinfo) - timedelta(days=90)
        assert abs((called_cutoff - expected).total_seconds()) < 5

    def test_does_not_call_garbage_collect(self):
        """expire_old_snapshots must be expire-only; GC ownership moved to
        garbage_collect()/maintenance() so it runs exactly once per
        maintenance() call, not twice (the second bug)."""
        store = Mock()
        store.repo = Mock()
        store.repo.expire_snapshots.return_value = set()
        store._logger = Mock()
        store.store_type = "gnss_store"

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.expire_old_snapshots(store, days=30)

        store.repo.garbage_collect.assert_not_called()


class TestMaintenanceRunsGcExactlyOnce:
    def test_maintenance_defaults(self):
        sig = inspect.signature(
            __import__(
                "canvod.store.store", fromlist=["MyIcechunkStore"]
            ).MyIcechunkStore.maintenance
        )
        assert sig.parameters["expire_days"].default == 90

    def test_gc_called_exactly_once(self):
        store = Mock()
        store._logger = Mock()
        store.store_type = "gnss_store"
        store.expire_old_snapshots = Mock(return_value=set())
        store.cleanup_stale_branches = Mock(return_value=[])
        store.garbage_collect = Mock(
            return_value={
                "dry_run": False,
                "bytes_deleted": 0,
                "chunks_deleted": 0,
                "manifests_deleted": 0,
                "snapshots_deleted": 0,
                "attributes_deleted": 0,
                "transaction_logs_deleted": 0,
            }
        )

        from canvod.store.store import MyIcechunkStore

        results = MyIcechunkStore.maintenance(
            store, expire_days=30, cleanup_branches=False, run_gc=True
        )

        store.garbage_collect.assert_called_once()
        assert store.garbage_collect.call_args.kwargs["days"] == 30
        assert results["gc_summary"] is not None

    def test_dry_run_gc_passed_through(self):
        store = Mock()
        store._logger = Mock()
        store.store_type = "gnss_store"
        store.expire_old_snapshots = Mock(return_value=set())
        store.cleanup_stale_branches = Mock(return_value=[])
        store.garbage_collect = Mock(return_value={"dry_run": True})

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.maintenance(store, dry_run_gc=True)

        assert store.garbage_collect.call_args.kwargs["dry_run"] is True

    def test_expire_delete_flags_passed_through(self):
        store = Mock()
        store._logger = Mock()
        store.store_type = "gnss_store"
        store.expire_old_snapshots = Mock(return_value=set())
        store.cleanup_stale_branches = Mock(return_value=[])
        store.garbage_collect = Mock(return_value={})

        from canvod.store.store import MyIcechunkStore

        MyIcechunkStore.maintenance(
            store, delete_expired_branches=True, delete_expired_tags=False
        )

        kwargs = store.expire_old_snapshots.call_args.kwargs
        assert kwargs["delete_expired_branches"] is True
        assert kwargs["delete_expired_tags"] is False


class TestGarbageCollectWrapper:
    def test_dry_run_passed_to_repo(self):
        store = Mock()
        store._logger = Mock()
        store.repo = Mock()
        store.repo.garbage_collect.return_value = Mock(
            bytes_deleted=0,
            chunks_deleted=0,
            manifests_deleted=0,
            snapshots_deleted=0,
            attributes_deleted=0,
            transaction_logs_deleted=0,
        )

        from canvod.store.store import MyIcechunkStore

        result = MyIcechunkStore.garbage_collect(store, days=90, dry_run=True)

        assert store.repo.garbage_collect.call_args.kwargs["dry_run"] is True
        assert result["dry_run"] is True


class TestCreateKeeperTag:
    def test_creates_tag_on_real_store(self, tmp_path: Path) -> None:
        store_path = tmp_path / "test_site" / "vod_store"
        store = create_vod_store(store_path)

        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            group = root.create_group("canopy")
            group.create_array("data", shape=(3,), dtype="i4")
            group["data"][:] = [1, 2, 3]
            snapshot_id = session.commit("test commit")

        created = store.create_keeper_tag("canopy", "2025001", snapshot_id)

        assert created is True
        assert "keep/canopy/2025001" in store.list_tags()

    def test_duplicate_tag_returns_false_without_raising(self, tmp_path: Path) -> None:
        store_path = tmp_path / "test_site" / "vod_store"
        store = create_vod_store(store_path)

        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("canopy")
            snapshot_id = session.commit("test commit")

        first = store.create_keeper_tag("canopy", "2025001", snapshot_id)
        second = store.create_keeper_tag("canopy", "2025001", snapshot_id)

        assert first is True
        assert second is False


class TestKeeperTagsConfigDefault:
    def test_storage_config_keeper_tags_defaults_false(self):
        from canvod.config.models.storage import StorageConfig

        config = StorageConfig(stores_root_dir="/tmp/canvod-test-stores")
        assert config.keeper_tags is False
