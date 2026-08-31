"""Tests for FilenameMapper.detect_overlaps."""

from __future__ import annotations

from pathlib import Path

from canvod.preflight import CanVODFilename, FilenameMapper
from canvod.preflight.mapping import VirtualFile


def _vf(
    period: str = "01D",
    hour: int = 0,
    minute: int = 0,
    doy: int = 1,
    year: int = 2025,
) -> VirtualFile:
    """Create a VirtualFile with the given parameters."""
    cn = CanVODFilename(
        site="ROS",
        receiver_type="R",
        receiver_number=1,
        agency="TUW",
        year=year,
        doy=doy,
        hour=hour,
        minute=minute,
        period=period,
        sampling="05S",
        content="AA",
        file_type="rnx",
    )
    return VirtualFile(
        physical_path=Path(f"/data/{cn.name}"),
        conventional_name=cn,
    )


class TestOverlapDetection:
    """Test FilenameMapper.detect_overlaps."""

    def test_daily_vs_subdaily(self):
        """01D file with 15M files for same day -> overlaps."""
        vfs = [
            _vf(period="01D", hour=0, minute=0),
            _vf(period="15M", hour=0, minute=0),
            _vf(period="15M", hour=0, minute=15),
            _vf(period="15M", hour=0, minute=30),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        # Daily overlaps each 15M file: 3 pairs
        assert len(overlaps) == 3

    def test_non_overlapping_subdaily(self):
        """Non-overlapping 15M files -> clean."""
        vfs = [
            _vf(period="15M", hour=0, minute=0),
            _vf(period="15M", hour=0, minute=15),
            _vf(period="15M", hour=0, minute=30),
            _vf(period="15M", hour=0, minute=45),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0

    def test_different_days_no_overlap(self):
        """Files on different DOYs never overlap."""
        vfs = [
            _vf(period="01D", doy=1),
            _vf(period="01D", doy=2),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0

    def test_hourly_overlap_with_daily(self):
        """01H files overlap with 01D on same day."""
        vfs = [
            _vf(period="01D", hour=0),
            _vf(period="01H", hour=0),
            _vf(period="01H", hour=1),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 2  # daily overlaps both hourly

    def test_single_file_no_overlap(self):
        """Single file -> no overlaps."""
        vfs = [_vf()]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0

    def test_empty_list(self):
        """Empty list -> no overlaps."""
        assert FilenameMapper.detect_overlaps([]) == []

    def test_adjacent_hourly_files(self):
        """Adjacent 01H files don't overlap (00:00-01:00 and 01:00-02:00)."""
        vfs = [
            _vf(period="01H", hour=0),
            _vf(period="01H", hour=1),
        ]
        overlaps = FilenameMapper.detect_overlaps(vfs)
        assert len(overlaps) == 0
