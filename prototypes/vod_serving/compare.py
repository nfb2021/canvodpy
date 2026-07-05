"""Measure the three grid-storage strategies: sizes, load times, cell counts.

Prints a scorecard table consumed by COMPARISON.md. Run AFTER the three
build.py scripts have produced _out/*.

Run: cd canvodpy && uv run --with healpy --with xdggs --with uxarray \
        python ../grid_storage/compare.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import dir_size_mb

OUT = Path(__file__).resolve().parent / "_out"

CASES = [
    (
        "S1 custom equal-area",
        "strategy1_equal_area.zarr",
        "strategy1_equal_area.nc",
        "cell",
    ),
    ("S2 HEALPix + xdggs", "strategy2_healpix.zarr", None, "cell"),
    ("S3 uxarray UGRID", "strategy3_ugrid.zarr", "strategy3_ugrid.nc", "n_face"),
]


def time_open(path: Path, n: int = 5) -> float:
    """Median wall time to open + load the cube (ms)."""
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        ds = xr.open_zarr(path, consolidated=True)
        ds.load()
        ts.append((time.perf_counter() - t0) * 1e3)
    return float(np.median(ts))


def main() -> None:
    rows = []
    for name, zname, ncname, celldim in CASES:
        z = OUT / zname
        zmb = dir_size_mb(z)
        ncmb = dir_size_mb(OUT / ncname) if ncname else None
        ds = xr.open_zarr(z, consolidated=True)
        ncells = ds.sizes[celldim]
        t_ms = time_open(z)
        rows.append((name, ncells, zmb, ncmb, t_ms))

    w = max(len(r[0]) for r in rows)
    print(
        f"\n{'strategy':<{w}}  {'cells':>6}  {'zarr MB':>8}  {'nc MB':>7}  {'open ms':>8}"
    )
    print("-" * (w + 36))
    for name, ncells, zmb, ncmb, t_ms in rows:
        nc = f"{ncmb:.2f}" if ncmb is not None else "  —"
        print(f"{name:<{w}}  {ncells:>6}  {zmb:>8.2f}  {nc:>7}  {t_ms:>8.1f}")
    print()


if __name__ == "__main__":
    main()
