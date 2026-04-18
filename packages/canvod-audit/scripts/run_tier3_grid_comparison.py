"""Tier 3C: Grid cell assignment comparison — canvodpy vs gnssvod.

Maps both canvodpy and gnssvod observation outputs to:
  A. gnssvod's 2° equi-angular grid (hemibuild)
  B. canvodpy's 2° equal-area grid (create_hemigrid)

Then compares cell assignments to determine whether the ~0.002° angular
differences from different SP3 interpolation methods cause observations
to land in different grid cells.

Prerequisites
-------------
Tier 3 steps 1-3 must have completed (trimmed RINEX, gnssvod output,
canvodpy output all present).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

# ── Paths ─────────────────────────────────────────────────────────────────────

AUDIT_ROOT = Path(
    os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
)
TIER3_DIR = AUDIT_ROOT / "tier3_vs_gnssvod/Rosalia"

CANVODPY_STORE = TIER3_DIR / "canvodpy_trimmed_store"
GNSSVOD_CANOPY = TIER3_DIR / "gnssvod_canopy_output.parquet"
GNSSVOD_VOD = TIER3_DIR / "gnssvod_vod_output.parquet"

ANGULAR_RESOLUTION = 2.0  # degrees


# ── Data loading ──────────────────────────────────────────────────────────────


def load_canvodpy() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load canvodpy phi, theta arrays for L1|C SIDs.

    Returns (epoch, sid, phi_rad, theta_rad) — all aligned.
    phi and theta are 2D arrays (epoch, sid) in radians.
    """
    ds = xr.open_zarr(str(CANVODPY_STORE))

    # Select GPS L1|C SIDs (matching gnssvod's S1C)
    l1c_sids = [s for s in ds.sid.values if str(s).endswith("|L1|C")]
    ds_band = ds.sel(sid=l1c_sids)

    # Extract PRNs for alignment with gnssvod
    prns = np.array([str(s).split("|")[0] for s in l1c_sids])

    phi = ds_band["phi"].values  # (epoch, sid) radians
    theta = ds_band["theta"].values  # (epoch, sid) radians
    epochs = ds_band.epoch.values

    return epochs, prns, phi, theta


def load_gnssvod() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load gnssvod Azimuth, Elevation arrays.

    Returns (epoch, sid, azi_deg, ele_deg) — all 2D (epoch, sid).
    """
    df = pd.read_parquet(GNSSVOD_CANOPY)

    # Pivot to (epoch, sid) arrays
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()

    epochs = np.sort(df["Epoch"].unique())
    svs = np.sort(df["SV"].unique())

    # Build 2D arrays via pivot
    azi_pivot = df.pivot(index="Epoch", columns="SV", values="Azimuth")
    ele_pivot = df.pivot(index="Epoch", columns="SV", values="Elevation")

    # Reindex to sorted axes
    azi_pivot = azi_pivot.reindex(index=epochs, columns=svs)
    ele_pivot = ele_pivot.reindex(index=epochs, columns=svs)

    return epochs, svs, azi_pivot.values, ele_pivot.values


def align_datasets(
    cv_epochs,
    cv_prns,
    cv_phi,
    cv_theta,
    gv_epochs,
    gv_svs,
    gv_azi,
    gv_ele,
) -> dict:
    """Align canvodpy and gnssvod on shared (epoch, PRN) pairs.

    Returns dict with aligned 2D arrays for both tools.
    """
    shared_epochs = np.intersect1d(cv_epochs, gv_epochs)
    shared_prns = np.intersect1d(cv_prns, gv_svs)

    print(f"  Shared epochs: {len(shared_epochs)}, shared PRNs: {len(shared_prns)}")

    # Vectorized index alignment
    cv_ep_sel = np.searchsorted(cv_epochs, shared_epochs)
    cv_prn_sel = np.searchsorted(cv_prns, shared_prns)
    gv_ep_sel = np.searchsorted(gv_epochs, shared_epochs)
    gv_prn_sel = np.searchsorted(gv_svs, shared_prns)

    return {
        "epochs": shared_epochs,
        "prns": shared_prns,
        "cv_phi": cv_phi[np.ix_(cv_ep_sel, cv_prn_sel)],
        "cv_theta": cv_theta[np.ix_(cv_ep_sel, cv_prn_sel)],
        "gv_azi": gv_azi[np.ix_(gv_ep_sel, gv_prn_sel)],
        "gv_ele": gv_ele[np.ix_(gv_ep_sel, gv_prn_sel)],
    }


# ── Grid assignment ───────────────────────────────────────────────────────────


def assign_gnssvod_grid(azi_deg: np.ndarray, ele_deg: np.ndarray) -> np.ndarray:
    """Assign observations to gnssvod's equi-angular grid cells.

    Parameters: 2D arrays (epoch, sid) in degrees.
    Returns: 2D array of CellID (int), NaN where input is NaN.
    """
    from gnssvod.hemistats.hemistats import hemibuild

    hemi = hemibuild(ANGULAR_RESOLUTION)
    print(f"  gnssvod grid: {len(hemi.grid)} cells")

    # Flatten, create DataFrame, assign, reshape
    shape = azi_deg.shape
    flat_azi = azi_deg.ravel()
    flat_ele = ele_deg.ravel()

    valid = np.isfinite(flat_azi) & np.isfinite(flat_ele)
    cell_ids = np.full(len(flat_azi), np.nan)

    if valid.sum() > 0:
        valid_indices = np.where(valid)[0]
        df = pd.DataFrame(
            {
                "Azimuth": flat_azi[valid],
                "Elevation": flat_ele[valid],
            },
            index=valid_indices,
        )
        df = hemi.add_CellID(df, aziname="Azimuth", elename="Elevation")
        # add_CellID may drop rows (elevation cutoff), so use index
        cell_ids[df.index.values] = df["CellID"].values

    return cell_ids.reshape(shape)


def assign_canvodpy_grid(phi_rad: np.ndarray, theta_rad: np.ndarray) -> np.ndarray:
    """Assign observations to canvodpy's equal-area grid cells.

    Parameters: 2D arrays (epoch, sid) in radians.
    Returns: 2D array of cell_id (int), NaN where input is NaN.
    """
    from canvod.grids import create_hemigrid
    from canvod.grids.operations import _build_kdtree, _query_points

    grid = create_hemigrid("equal_area", angular_resolution=ANGULAR_RESOLUTION)
    print(f"  canvodpy equal-area grid: {len(grid.grid)} cells")

    shape = phi_rad.shape
    flat_phi = phi_rad.ravel()
    flat_theta = theta_rad.ravel()

    valid = np.isfinite(flat_phi) & np.isfinite(flat_theta)
    cell_ids = np.full(len(flat_phi), np.nan)

    if valid.sum() > 0:
        tree = _build_kdtree(grid)
        cell_id_col = grid.grid["cell_id"].to_numpy()
        ids = _query_points(tree, cell_id_col, flat_phi[valid], flat_theta[valid])
        cell_ids[valid] = ids

    return cell_ids.reshape(shape)


# ── Coordinate conversion ────────────────────────────────────────────────────


def canvodpy_to_deg(phi_rad, theta_rad):
    """Convert canvodpy (phi_rad, theta_rad) to (azi_deg, ele_deg)."""
    azi_deg = np.rad2deg(phi_rad)
    ele_deg = 90.0 - np.rad2deg(theta_rad)
    return azi_deg, ele_deg


def gnssvod_to_rad(azi_deg, ele_deg):
    """Convert gnssvod (azi_deg, ele_deg) to (phi_rad, theta_rad)."""
    phi_rad = np.deg2rad(azi_deg) % (2 * np.pi)  # normalize to [0, 2π)
    theta_rad = np.deg2rad(90.0 - ele_deg)
    return phi_rad, theta_rad


# ── Comparison ────────────────────────────────────────────────────────────────


def compare_cell_assignments(
    cells_a: np.ndarray,
    cells_b: np.ndarray,
    label: str,
) -> dict:
    """Compare two cell assignment arrays. Returns stats dict."""
    valid = np.isfinite(cells_a) & np.isfinite(cells_b)
    n_valid = valid.sum()

    if n_valid == 0:
        print(f"  {label}: no valid pairs")
        return {"label": label, "n_valid": 0}

    a = cells_a[valid].astype(int)
    b = cells_b[valid].astype(int)

    agree = a == b
    n_agree = agree.sum()
    n_disagree = n_valid - n_agree
    pct_agree = n_agree / n_valid * 100

    print(f"  {label}:")
    print(f"    Valid pairs: {n_valid:,}")
    print(f"    Same cell:   {n_agree:,} ({pct_agree:.4f}%)")
    print(f"    Diff cell:   {n_disagree:,} ({100 - pct_agree:.4f}%)")

    stats = {
        "label": label,
        "n_valid": int(n_valid),
        "n_agree": int(n_agree),
        "n_disagree": int(n_disagree),
        "pct_agree": float(pct_agree),
    }

    if n_disagree > 0:
        # Analyze disagreements: are they at cell boundaries?
        # For the disagreeing observations, check angular distance to cell edge
        print(f"    Analyzing {min(n_disagree, 10)} disagreements ...")

    return stats


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    print("=" * 70)
    print("Tier 3C: Grid cell assignment comparison")
    print(f"Angular resolution: {ANGULAR_RESOLUTION}°")
    print("=" * 70)

    # ── Load data ──
    print("\n── Loading canvodpy ──")
    cv_epochs, cv_prns, cv_phi, cv_theta = load_canvodpy()
    print(f"  Shape: ({len(cv_epochs)}, {len(cv_prns)})")
    print(f"  phi range: [{np.nanmin(cv_phi):.4f}, {np.nanmax(cv_phi):.4f}] rad")
    print(f"  theta range: [{np.nanmin(cv_theta):.4f}, {np.nanmax(cv_theta):.4f}] rad")

    print("\n── Loading gnssvod ──")
    gv_epochs, gv_svs, gv_azi, gv_ele = load_gnssvod()
    print(f"  Shape: ({len(gv_epochs)}, {len(gv_svs)})")
    print(f"  azi range: [{np.nanmin(gv_azi):.4f}, {np.nanmax(gv_azi):.4f}] deg")
    print(f"  ele range: [{np.nanmin(gv_ele):.4f}, {np.nanmax(gv_ele):.4f}] deg")

    # ── Align ──
    print("\n── Aligning on shared (epoch, PRN) ──")
    aligned = align_datasets(
        cv_epochs,
        cv_prns,
        cv_phi,
        cv_theta,
        gv_epochs,
        gv_svs,
        gv_azi,
        gv_ele,
    )

    # Also convert coordinates for cross-grid assignment
    cv_azi_deg, cv_ele_deg = canvodpy_to_deg(aligned["cv_phi"], aligned["cv_theta"])
    gv_phi_rad, gv_theta_rad = gnssvod_to_rad(aligned["gv_azi"], aligned["gv_ele"])

    # ── Part A: gnssvod 2° grid ──
    print("\n" + "=" * 70)
    print("Part A: Both datasets → gnssvod 2° equi-angular grid")
    print("=" * 70)

    print("\n  Assigning canvodpy angles to gnssvod grid ...")
    cv_on_gv_grid = assign_gnssvod_grid(cv_azi_deg, cv_ele_deg)

    print("  Assigning gnssvod angles to gnssvod grid ...")
    gv_on_gv_grid = assign_gnssvod_grid(aligned["gv_azi"], aligned["gv_ele"])

    print()
    stats_a = compare_cell_assignments(
        cv_on_gv_grid,
        gv_on_gv_grid,
        "canvodpy vs gnssvod → gnssvod grid",
    )

    # ── Part B: canvodpy 2° equal-area grid ──
    print("\n" + "=" * 70)
    print("Part B: Both datasets → canvodpy 2° equal-area grid")
    print("=" * 70)

    print("\n  Assigning canvodpy angles to canvodpy grid ...")
    cv_on_cv_grid = assign_canvodpy_grid(aligned["cv_phi"], aligned["cv_theta"])

    print("  Assigning gnssvod angles to canvodpy grid ...")
    gv_on_cv_grid = assign_canvodpy_grid(gv_phi_rad, gv_theta_rad)

    print()
    stats_b = compare_cell_assignments(
        cv_on_cv_grid,
        gv_on_cv_grid,
        "canvodpy vs gnssvod → canvodpy equal-area grid",
    )

    # ── Summary ──
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)

    for stats in [stats_a, stats_b]:
        if stats["n_valid"] > 0:
            print(
                f"  {stats['label']}: "
                f"{stats['pct_agree']:.4f}% same cell, "
                f"{stats['n_disagree']:,} differ "
                f"(of {stats['n_valid']:,} valid pairs)"
            )

    # ── Save ──
    results_df = pd.DataFrame([stats_a, stats_b])
    out_path = TIER3_DIR / "tier3c_grid_comparison.csv"
    results_df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
