"""Test metadata I/O with temp Icechunk stores."""

import icechunk
import pytest
import zarr

from canvod.store_metadata.io import (
    metadata_exists,
    read_metadata,
    update_metadata,
    write_metadata,
)
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)


def _make_metadata() -> StoreMetadata:
    return StoreMetadata(
        identity=StoreIdentity(
            id="test/gnss_store",
            title="Test Store",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(
            name="Test",
            email="test@example.com",
            institution="TestU",
        ),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        ),
        spatial=SpatialExtent(
            site=SiteInfo(name="TestSite"),
        ),
    )


def _create_store(path):
    """Create a minimal Icechunk store."""
    storage = icechunk.local_filesystem_storage(str(path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")
    return path


class TestIO:
    def test_write_and_read_roundtrip(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        meta = _make_metadata()

        write_metadata(store_path, meta)
        restored = read_metadata(store_path)
        assert restored == meta

    def test_metadata_exists_false(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        assert not metadata_exists(store_path)

    def test_metadata_exists_true(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        write_metadata(store_path, _make_metadata())
        assert metadata_exists(store_path)

    def test_metadata_exists_no_store(self, tmp_path):
        assert not metadata_exists(tmp_path / "nonexistent")

    def test_update_metadata(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        meta = _make_metadata()
        write_metadata(store_path, meta)

        update_metadata(store_path, {"temporal.updated": "2026-06-01T00:00:00Z"})
        updated = read_metadata(store_path)
        assert updated.temporal.updated == "2026-06-01T00:00:00Z"
        assert updated.temporal.created == "2026-01-01T00:00:00Z"

    def test_read_missing_raises(self, tmp_path):
        store_path = _create_store(tmp_path / "store")
        with pytest.raises(KeyError):
            read_metadata(store_path)
