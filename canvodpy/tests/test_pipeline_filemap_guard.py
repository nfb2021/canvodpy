"""Tests for the recipe/canvod-filemap fail-fast guard in PipelineOrchestrator."""

from __future__ import annotations

import pytest
from canvodpy.orchestrator.pipeline import _check_recipe_receivers_have_filemap


class TestRecipeFilemapGuard:
    def test_no_recipes_configured_is_a_no_op(self):
        _check_recipe_receivers_have_filemap(
            {"canopy_01": {"type": "canopy", "directory": "02_canopy"}}
        )

    def test_recipe_without_filemap_installed_raises(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "canvod.filemap" or name.startswith("canvod.filemap"):
                raise ImportError("No module named 'canvod.filemap'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        with pytest.raises(ImportError) as exc_info:
            _check_recipe_receivers_have_filemap(
                {
                    "canopy_01": {
                        "type": "canopy",
                        "directory": "02_canopy",
                        "recipe": "rosalia_canopy",
                    },
                    "reference_01": {"type": "reference", "directory": "01_reference"},
                }
            )

        assert "canopy_01" in str(exc_info.value)
        assert "reference_01" not in str(exc_info.value)
        assert "uv sync --extra filemap" in str(exc_info.value)

    def test_recipe_with_filemap_installed_does_not_raise(self, monkeypatch):
        import builtins
        import sys
        import types

        fake_module = types.ModuleType("canvod.filemap")
        monkeypatch.setitem(sys.modules, "canvod.filemap", fake_module)

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "canvod.filemap":
                return fake_module
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        _check_recipe_receivers_have_filemap(
            {
                "canopy_01": {
                    "type": "canopy",
                    "directory": "02_canopy",
                    "recipe": "rosalia_canopy",
                },
            }
        )
