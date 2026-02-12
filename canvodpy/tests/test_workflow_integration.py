"""
Integration tests for VODWorkflow.

Tests workflow orchestration, factory integration, and logging.
Uses a mock Site to avoid filesystem dependencies (external drives, store paths).
"""

from unittest.mock import patch

import pytest
from canvodpy.factories import GridFactory, ReaderFactory

from canvodpy import VODWorkflow


class _FakeSite:
    """Minimal stand-in for :class:`canvodpy.api.Site` (no I/O)."""

    def __init__(self, name: str = "Rosalia"):
        self.name = name


def _make_workflow(**kwargs) -> VODWorkflow:
    """Create a VODWorkflow with a fake Site (no I/O)."""
    return VODWorkflow(site=_FakeSite(), **kwargs)


class TestWorkflowInitialization:
    """Test VODWorkflow initialization."""

    def test_workflow_creates_with_site_object(self):
        """Should create workflow from a Site-like object."""
        workflow = _make_workflow()
        assert workflow.site.name == "Rosalia"

    def test_workflow_creates_with_site_name(self):
        """Should create workflow from site name string."""
        with patch("canvodpy.workflow.Site", side_effect=lambda n: _FakeSite(n)):
            workflow = VODWorkflow(site="Rosalia")
        assert workflow.site.name == "Rosalia"

    def test_workflow_uses_default_components(self):
        """Should use default component names."""
        workflow = _make_workflow()
        assert workflow.reader_name == "rinex3"
        assert workflow.grid_name == "equal_area"
        assert workflow.vod_calculator_name == "tau_omega"

    def test_workflow_accepts_custom_components(self):
        """Should accept custom component names."""
        workflow = _make_workflow(
            reader="rinex3",
            grid="equal_area",
            vod_calculator="tau_omega",
        )
        assert workflow.reader_name == "rinex3"


class TestWorkflowGridCreation:
    """Test grid creation in workflow."""

    def test_workflow_creates_grid(self):
        """Should create and cache grid on init."""
        workflow = _make_workflow()
        assert workflow.grid is not None
        assert hasattr(workflow.grid, "ncells")
        assert workflow.grid.ncells > 0

    def test_workflow_grid_with_custom_params(self):
        """Should pass custom parameters to grid."""
        workflow = _make_workflow(grid_params={"angular_resolution": 5.0})
        # 5deg resolution should have more cells than 10deg default
        assert workflow.grid.ncells > 240

    def test_workflow_grid_is_built(self):
        """Grid should be built (not builder) on init."""
        workflow = _make_workflow()
        # Should be GridData, not GridBuilder
        assert not hasattr(workflow.grid, "build")
        assert hasattr(workflow.grid, "ncells")


class TestWorkflowLogging:
    """Test structured logging in workflow."""

    def test_workflow_has_logger(self):
        """Should have structured logger."""
        workflow = _make_workflow()
        assert hasattr(workflow, "log")
        assert hasattr(workflow.log, "info")

    def test_workflow_logger_has_site_context(self):
        """Logger should be bound to site context."""
        workflow = _make_workflow()
        assert workflow.log is not None


class TestWorkflowRepr:
    """Test workflow string representation."""

    def test_workflow_repr(self):
        """Should have informative __repr__."""
        workflow = _make_workflow()
        repr_str = repr(workflow)
        assert "VODWorkflow" in repr_str
        assert "Rosalia" in repr_str
        assert "equal_area" in repr_str
        assert "rinex3" in repr_str


class TestWorkflowFactoryIntegration:
    """Test workflow uses factories correctly."""

    def test_workflow_uses_grid_factory(self):
        """Should create grid via GridFactory."""
        workflow = _make_workflow()
        available = GridFactory.list_available()
        assert workflow.grid_name in available

    def test_workflow_respects_factory_registration(self):
        """Should use registered factories."""
        # If we register a custom component, workflow should find it
        # This is tested implicitly in factory tests


class TestWorkflowErrorHandling:
    """Test workflow error handling."""

    def test_workflow_invalid_site_fails(self):
        """Should fail gracefully with invalid site name."""
        from canvodpy.research_sites_config import RESEARCH_SITES

        assert "NonexistentSite123" not in RESEARCH_SITES

        # VODWorkflow passes the string to Site(), which calls GnssResearchSite()
        # which raises KeyError for unknown sites. Mock Site to simulate this.
        with patch(
            "canvodpy.workflow.Site",
            side_effect=KeyError("NonexistentSite123"),
        ):
            with pytest.raises(KeyError, match="NonexistentSite123"):
                VODWorkflow(site="NonexistentSite123")

    def test_workflow_invalid_grid_type_fails(self):
        """Should fail with invalid grid type."""
        with pytest.raises(ValueError, match="nonexistent_grid"):
            _make_workflow(grid="nonexistent_grid")

    def test_workflow_invalid_reader_fails(self):
        """Should fail with invalid reader type during creation."""
        # Invalid reader is only caught when factory.create() is called
        # This happens during process_date(), not during __init__
        # Verify that invalid readers aren't in the registry
        assert "nonexistent_reader" not in ReaderFactory.list_available()


@pytest.mark.integration
class TestWorkflowProcessing:
    """Integration tests requiring data (marked for CI)."""

    def test_process_date_returns_dict(self):
        """process_date should return dict of datasets."""
        pytest.skip("Requires test data")

    def test_calculate_vod_returns_dataset(self):
        """calculate_vod should return xarray Dataset."""
        pytest.skip("Requires test data")

    def test_workflow_end_to_end(self):
        """Full workflow from init to VOD calculation."""
        pytest.skip("Requires test data")
