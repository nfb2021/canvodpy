"""Shared helpers for the three grid-storage strategy prototypes.

Everything geometric comes from canvod (`create_hemigrid`, the KDTree
assignment, the viz renderer) — these helpers only orchestrate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "_fixture" / "obs_24h.npz"

PAIRS = ["base_up_vs_sky_up", "nadir_in_vs_sky_up", "nadir_out_vs_sky_up"]


def load_fixture() -> dict:
    """Return {date, pairs, <pair>__phi/theta/vod}."""
    z = np.load(FIXTURE, allow_pickle=True)
    out = {"date": str(z["date"]), "pairs": [str(p) for p in z["pairs"]]}
    for p in out["pairs"]:
        out[f"{p}__phi"] = z[f"{p}__phi"]
        out[f"{p}__theta"] = z[f"{p}__theta"]
        out[f"{p}__vod"] = z[f"{p}__vod"]
    return out


def equal_area_grid(resolution: float = 2.0):
    """canvod equal-area hemigrid (the scientifically-validated tessellation)."""
    from canvod.grids import create_hemigrid

    return create_hemigrid("equal_area", angular_resolution=resolution)


def assign_equal_area(grid, phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Assign obs to canvod equal-area cells via canvod's own KDTree path."""
    from canvod.grids.operations import _build_kdtree, _query_points

    tree = _build_kdtree(grid)
    cid_col = grid.grid["cell_id"].to_numpy()
    return _query_points(tree, cid_col, phi, theta).astype(np.int64)


def moments(cell_ids: np.ndarray, vod: np.ndarray, ncells: int):
    """Per-cell additive moments: (sum, sumsq, count), each length ncells."""
    s = np.zeros(ncells)
    s2 = np.zeros(ncells)
    c = np.zeros(ncells)
    np.add.at(s, cell_ids, vod)
    np.add.at(s2, cell_ids, vod**2)
    np.add.at(c, cell_ids, 1.0)
    return s, s2, c


def mean_std(s, s2, c):
    """Derive (mean, std) from additive moments; NaN where unsupported."""
    mean = np.where(c > 0, s / np.where(c > 0, c, 1), np.nan)
    var = np.where(c > 0, s2 / np.where(c > 0, c, 1) - mean**2, np.nan)
    var = np.clip(var, 0.0, None)
    std = np.where(c >= 2, np.sqrt(var), np.nan)
    return mean, std


def dir_size_mb(path: Path) -> float:
    """Total size of a file or directory tree, in MB."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size / 1e6
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6
