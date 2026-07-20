"""Basic tests for canvod-store package."""


def test_import():
    """Test that package can be imported."""
    import canvod.store

    assert hasattr(canvod.store, "MyIcechunkStore")
    assert hasattr(canvod.store, "create_gnss_store")
    assert hasattr(canvod.store, "create_vod_store")
    assert hasattr(canvod.store, "GnssResearchSite")


def test_version():
    """Test that version is defined."""
    import canvod.store

    assert hasattr(canvod.store, "__version__")
    assert isinstance(canvod.store.__version__, str)
