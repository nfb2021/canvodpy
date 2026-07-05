"""Unit tests for MemoryMonitor."""

from __future__ import annotations

import unittest.mock

import pytest
from canvodpy.orchestrator.resources import MemoryMonitor


def _mock_vmem(
    available: int = 4 * 1024**3, percent: float = 42.5, total: int = 8 * 1024**3
):
    m = unittest.mock.MagicMock()
    m.available = available
    m.percent = percent
    m.total = total
    return m


class TestMemoryMonitor:
    def test_init_stores_max_memory_gb(self):
        mm = MemoryMonitor(max_memory_gb=16.0)
        assert mm.max_memory_gb == 16.0

    def test_init_none(self):
        mm = MemoryMonitor()
        assert mm.max_memory_gb is None

    def test_available_gb(self):
        with unittest.mock.patch(
            "psutil.virtual_memory", return_value=_mock_vmem(available=4 * 1024**3)
        ):
            mm = MemoryMonitor()
            assert abs(mm.available_gb() - 4.0) < 0.01

    def test_used_percent(self):
        with unittest.mock.patch(
            "psutil.virtual_memory", return_value=_mock_vmem(percent=55.0)
        ):
            mm = MemoryMonitor()
            assert mm.used_percent() == pytest.approx(55.0)

    def test_log_memory_stats_does_not_raise(self):
        with unittest.mock.patch("psutil.virtual_memory", return_value=_mock_vmem()):
            mm = MemoryMonitor()
            mm.log_memory_stats(context="test_context")  # should not raise
