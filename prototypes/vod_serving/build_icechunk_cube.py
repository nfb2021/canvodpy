"""Prototype: the UGRID/uxarray VOD cube inside an ICECHUNK store.

Demonstrates the concrete on-disk structure we'd commit to:
  * STATIC UGRID mesh (singularity-free Cartesian unit-vector nodes on S²)
  * TIME-VARYING additive metadata layers on (pair, time, n_face)
  * written to an icechunk repo, with an append-a-week commit, then read back.

Mesh stored with Cartesian node coords node_x/y/z (NOT lon/lat): the zenith is
just (0,0,1) and the 0/360 azimuth seam doesn't exist in xyz, so the pole/seam
pathology is gone at the storage level. Cells are spherical-polygon faces.

Run: cd canvodpy && uv run python ../grid_storage/build_icechunk_cube.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import icechunk
import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    PAIRS,
    assign_equal_area,
    equal_area_grid,
    load_fixture,
    moments,
)

STORE = Path(__file__).resolve().parent / "_out" / "vod_cube.icechunk"
RES = 2.0


def build_mesh(grid) -> xr.Dataset:
    """canvod equal-area cells -> UGRID mesh with Cartesian unit-vector nodes."""
    g = grid.grid
    phi_min = g["phi_min"].to_numpy()
    phi_max = g["phi_max"].to_numpy()
    th_min = g["theta_min"].to_numpy()
    th_max = g["theta_max"].to_numpy()
    ncells = grid.ncells

    def xyz(phi, theta):
        return np.stack(
            [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)],
            axis=-1,
        )

    # 4 corners per cell -> Cartesian; dedup (xyz merges seam AND pole automatically)
    cph = np.stack([phi_min, phi_max, phi_max, phi_min], axis=1).ravel()
    cth = np.stack([th_max, th_max, th_min, th_min], axis=1).ravel()
    corners = xyz(cph, cth)
    key = np.round(corners, 9)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    node_xyz = corners[first]
    face_node = inv.reshape(ncells, 4).astype(np.int64)

    fc = xyz(g["phi"].to_numpy(), g["theta"].to_numpy())  # face centres
    return xr.Dataset(
        data_vars={
            "mesh": (
                (),
                np.int32(0),
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "node_x node_y node_z",
                    "face_coordinates": "face_x face_y face_z",
                    "face_node_connectivity": "face_node_connectivity",
                    "face_dimension": "n_face",
                    "long_name": "canvod equal-area hemisphere mesh on the unit sphere",
                },
            ),
            "face_node_connectivity": (
                ("n_face", "n_max_face_nodes"),
                face_node,
                {
                    "cf_role": "face_node_connectivity",
                    "start_index": 0,
                    "_FillValue": -1,
                },
            ),
            "face_x": ("n_face", fc[:, 0]),
            "face_y": ("n_face", fc[:, 1]),
            "face_z": ("n_face", fc[:, 2]),
            "face_theta": (
                "n_face",
                g["theta"].to_numpy(),
                {"units": "rad", "long_name": "cell-centre zenith angle"},
            ),
            "face_phi": (
                "n_face",
                g["phi"].to_numpy(),
                {"units": "rad", "long_name": "cell-centre azimuth from north (cw)"},
            ),
            "face_solid_angle": ("n_face", grid.get_solid_angles(), {"units": "sr"}),
        },
        coords={
            "node_x": ("n_node", node_xyz[:, 0]),
            "node_y": ("n_node", node_xyz[:, 1]),
            "node_z": ("n_node", node_xyz[:, 2]),
        },
    )


def layers_for_times(grid, times: list[pd.Timestamp]) -> xr.Dataset:
    """Additive metadata layers (pair, time, n_face). Demo: same day repeated."""
    fx = load_fixture()
    ncells = grid.ncells
    npairs, nt = len(PAIRS), len(times)
    vsum = np.zeros((npairs, nt, ncells))
    vsq = np.zeros((npairs, nt, ncells))
    cnt = np.zeros((npairs, nt, ncells))
    for p, pair in enumerate(PAIRS):
        cid = assign_equal_area(grid, fx[f"{pair}__phi"], fx[f"{pair}__theta"])
        s, s2, c = moments(cid, fx[f"{pair}__vod"], ncells)
        for k in range(nt):
            vsum[p, k], vsq[p, k], cnt[p, k] = s, s2, c
    return xr.Dataset(
        {
            "vod_sum": (
                ("pair", "time", "n_face"),
                vsum,
                {"cell_methods": "time: sum"},
            ),
            "vod_sumsq": (("pair", "time", "n_face"), vsq),
            "count": (("pair", "time", "n_face"), cnt, {"long_name": "obs count"}),
        },
        coords={
            "pair": ("pair", np.array(PAIRS)),
            "time": ("time", pd.to_datetime(times)),
        },
    )


def main() -> None:
    grid = equal_area_grid(RES)
    mesh = build_mesh(grid)
    print(
        f"mesh: n_face={mesh.sizes['n_face']}, n_node={mesh.sizes['n_node']} "
        f"(lon/lat version had 12604 — xyz dedup merged seam+pole)",
        flush=True,
    )

    # initial cube: mesh (static) + first two weekly snapshots
    init = xr.merge(
        [
            mesh,
            layers_for_times(
                grid, [pd.Timestamp("2025-10-06"), pd.Timestamp("2025-10-13")]
            ),
        ]
    )
    init.attrs.update(
        {
            "title": "CARBONARA VOD hemisphere cube (UGRID on S²)",
            "Conventions": "UGRID-1.0",
            "grid_type": "equal_area",
            "angular_resolution_deg": RES,
            "coordinate_frame": "topocentric unit sphere S² (Cartesian node_x/y/z); NOT geographic",
            "stats_rule": "additive vod_sum/vod_sumsq/count; mean=sum/cnt, std=sqrt(sumsq/cnt-mean^2)",
            "source_store_branch": "main",
        }
    )

    shutil.rmtree(STORE, ignore_errors=True)
    repo = icechunk.Repository.create(icechunk.local_filesystem_storage(str(STORE)))

    # commit 1: init (chunk time=1 so appends/partial reads are cheap)
    sess = repo.writable_session("main")
    init.chunk({"time": 1}).to_zarr(
        sess.store, mode="w", consolidated=False, zarr_format=3
    )
    c1 = sess.commit("init VOD cube: mesh + 2 weekly snapshots")
    print(f"\ncommit 1 {c1[:12]} — mesh + time=2", flush=True)

    # commit 2: APPEND a new week (data vars only; mesh untouched)
    newweek = layers_for_times(grid, [pd.Timestamp("2025-10-20")])
    sess = repo.writable_session("main")
    newweek.chunk({"time": 1}).to_zarr(
        sess.store, append_dim="time", consolidated=False
    )
    c2 = sess.commit("append week 2025-10-20")
    print(f"commit 2 {c2[:12]} — appended time=3 (mesh NOT rewritten)", flush=True)

    _show_structure(repo)


def _show_structure(repo) -> None:
    sess = repo.readonly_session("main")
    ds = xr.open_zarr(sess.store, consolidated=False)
    print("\n" + "=" * 72)
    print("ICECHUNK STORE STRUCTURE (branch main, read-back)")
    print("=" * 72)
    print(ds)
    print("\n--- static mesh (no time dim) ---")
    for v in ["mesh", "face_node_connectivity", "face_solid_angle"]:
        print(f"  {v:24s} dims={ds[v].dims}")
    print("--- time-varying metadata layers ---")
    for v in ["vod_sum", "vod_sumsq", "count"]:
        print(f"  {v:24s} dims={ds[v].dims}  chunks={ds[v].encoding.get('chunks')}")
    print("--- derived on read (NOT stored) ---")
    den = ds["count"]
    mean = ds["vod_sum"] / den.where(den > 0)
    std = np.sqrt((ds["vod_sumsq"] / den.where(den > 0) - mean**2).clip(min=0))
    print(
        f"  mean base_up t0: {float(mean.isel(pair=0, time=0).mean()):.3f} (cell avg)"
    )
    print(f"  std  base_up t0: {float(std.isel(pair=0, time=0).mean()):.3f} (cell avg)")
    print(
        "\n--- icechunk history (each append = a commit; branch/rollback as usual) ---"
    )
    for s in repo.ancestry(branch="main"):
        print(f"  {s.id[:12]}  {s.message}")


if __name__ == "__main__":
    main()
