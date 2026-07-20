"""Test inventory/scan_stores on temp directories."""

import icechunk
import zarr

from canvod.store_metadata.inventory import scan_stores, scan_stores_as_stac
from canvod.store_metadata.io import write_metadata
from canvod.store_metadata.schema import (
    Creator,
    SiteInfo,
    SpatialExtent,
    StoreIdentity,
    StoreMetadata,
    TemporalExtent,
)


def _create_store_with_metadata(path, store_id="test/store"):
    storage = icechunk.local_filesystem_storage(str(path))
    repo = icechunk.Repository.create(storage=storage)
    session = repo.writable_session("main")
    zarr.open_group(session.store, mode="w")
    session.commit("init")

    meta = StoreMetadata(
        identity=StoreIdentity(
            id=store_id,
            title=f"Store {store_id}",
            store_type="gnss_store",
            source_format="rinex3",
        ),
        creator=Creator(name="Test", email="t@e.com", institution="U"),
        temporal=TemporalExtent(
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        ),
        spatial=SpatialExtent(site=SiteInfo(name="Test")),
    )
    write_metadata(path, meta)
    return path


class TestInventory:
    def test_scan_empty_dir(self, tmp_path):
        df = scan_stores(tmp_path)
        assert len(df) == 0
        assert "id" in df.columns

    def test_scan_finds_store(self, tmp_path):
        _create_store_with_metadata(tmp_path / "site1" / "rinex", "site1/rinex")
        df = scan_stores(tmp_path)
        assert len(df) == 1
        assert df["id"][0] == "site1/rinex"

    def test_scan_multiple_stores(self, tmp_path):
        _create_store_with_metadata(tmp_path / "s1" / "rinex", "s1/rinex")
        _create_store_with_metadata(tmp_path / "s2" / "rinex", "s2/rinex")
        df = scan_stores(tmp_path)
        assert len(df) == 2

    def test_scan_as_stac(self, tmp_path):
        _create_store_with_metadata(tmp_path / "site" / "store", "site/store")
        catalog = scan_stores_as_stac(tmp_path)
        assert catalog["type"] == "Catalog"
        assert len(catalog["collections"]) == 1
        assert catalog["collections"][0]["id"] == "site/store"

    def test_scan_nonexistent_dir(self, tmp_path):
        df = scan_stores(tmp_path / "nope")
        assert len(df) == 0
