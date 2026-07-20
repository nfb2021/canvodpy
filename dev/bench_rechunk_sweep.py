"""Re-chunk sweep: write cost, read cost, and on-disk chunk-file count across
a wide range of candidate epoch chunk sizes, on throwaway stores only.

Follow-up to dev/rechunk_benchmark_2026_07_20.md, which only tested 4
candidates and only measured write cost. This sweeps every divisor of 17280
that gives a whole number of files per chunk, and adds the two caveats that
benchmark flagged as unmeasured: read cost and physical chunk-file count.

Run: uv run python dev/bench_rechunk_sweep.py
Writes nothing outside a self-cleaning tempfile.mkdtemp() directory --
production store/config untouched.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from icechunk.xarray import to_icechunk

from canvod.store.store import MyIcechunkStore

N_FILES = 96  # 1 day of 15-min files
EPOCHS_PER_FILE = 180  # 15 min at 5s sampling
N_SID = 277  # matches live rosalia store's SID universe
DAY_EPOCHS = N_FILES * EPOCHS_PER_FILE  # 17280
# Every divisor of 17280 giving a whole files-per-chunk count.
CANDIDATES = [180, 360, 720, 1440, 2160, 2880, 4320, 5760, 8640, 17280]

rng = np.random.default_rng(42)

sid_values = np.array([f"S{i:03d}|L1|C" for i in range(N_SID)], dtype=object)
code_values = np.array(["C"] * N_SID, dtype=object)
band_values = np.array(["L1"] * N_SID, dtype=object)
sv_values = np.array([f"S{i:03d}" for i in range(N_SID)], dtype=object)
system_values = np.array(["G"] * N_SID, dtype=object)
freq = np.full(N_SID, 1575.42e6, dtype=np.float32)


def make_file(idx: int, day_start: pd.Timestamp) -> xr.Dataset:
    start = day_start + pd.Timedelta(seconds=idx * EPOCHS_PER_FILE * 5)
    epoch = pd.date_range(start, periods=EPOCHS_PER_FILE, freq="5s")
    snr = rng.uniform(20, 55, size=(EPOCHS_PER_FILE, N_SID)).astype(np.float32)
    phi = rng.uniform(0, 360, size=(EPOCHS_PER_FILE, N_SID)).astype(np.float64)
    theta = rng.uniform(0, 90, size=(EPOCHS_PER_FILE, N_SID)).astype(np.float64)
    return xr.Dataset(
        data_vars={
            "SNR": (("epoch", "sid"), snr),
            "phi": (("epoch", "sid"), phi),
            "theta": (("epoch", "sid"), theta),
        },
        coords={
            "epoch": epoch,
            "sid": sid_values,
            "code": ("sid", code_values),
            "band": ("sid", band_values),
            "sv": ("sid", sv_values),
            "system": ("sid", system_values),
            "freq_min": ("sid", freq),
            "freq_center": ("sid", freq),
            "freq_max": ("sid", freq),
        },
        attrs={"File Hash": f"bench-{idx}"},
    )


def count_chunk_files(store_dir: Path) -> tuple[int, float]:
    """Count files and total MB under the store's chunk storage."""
    n_files = 0
    n_bytes = 0
    for p in store_dir.rglob("*"):
        if p.is_file():
            n_files += 1
            n_bytes += p.stat().st_size
    return n_files, n_bytes / 1e6


def run_candidate(bench_root: Path, epoch_chunk: int) -> dict:
    store_dir = bench_root / f"epoch_{epoch_chunk}"
    store_dir.mkdir(parents=True)

    store = MyIcechunkStore(store_dir, store_type="gnss_store")
    store.chunk_strategy = {"epoch": epoch_chunk, "sid": -1}

    timings: list[float] = []
    day_start = pd.Timestamp("2025-01-01")
    group_name = "bench_receiver"

    with store.writable_session("main") as session:
        for idx in range(N_FILES):
            ds = make_file(idx, day_start)
            t0 = time.perf_counter()
            if idx == 0:
                to_icechunk(
                    ds,
                    session,
                    group=group_name,
                    encoding=store.chunk_encoding_for(ds),
                )
            else:
                to_icechunk(ds, session, group=group_name, append_dim="epoch")
            timings.append(time.perf_counter() - t0)
        session.commit(f"benchmark epoch_chunk={epoch_chunk}")

    # Read cost: fresh readonly session (new process would be more realistic
    # but this still avoids any write-path warm caches).
    t_open0 = time.perf_counter()
    ro_session = store.repo.readonly_session("main")
    ds_read = xr.open_zarr(ro_session.store, group=group_name, consolidated=False)
    t_open = time.perf_counter() - t_open0

    t_load0 = time.perf_counter()
    ds_read["SNR"].load()
    t_load = time.perf_counter() - t_load0

    n_files_disk, mb_disk = count_chunk_files(store_dir)

    return {
        "write_total_s": sum(timings),
        "write_first_s": timings[0],
        "write_last_s": timings[-1],
        "read_open_s": t_open,
        "read_load_s": t_load,
        "n_files_disk": n_files_disk,
        "mb_disk": mb_disk,
    }


def main() -> None:
    bench_root = Path(tempfile.mkdtemp(prefix="canvod_rechunk_sweep_"))
    print(f"Scratch dir: {bench_root}\n")
    header = (
        f"{'epoch':>7} | {'files/chk':>9} | {'write_s':>8} | {'ramp':>6} | "
        f"{'open_s':>7} | {'load_s':>7} | {'disk_files':>10} | {'disk_MB':>8}"
    )
    print(header)
    print("-" * len(header))

    try:
        for candidate in CANDIDATES:
            r = run_candidate(bench_root, candidate)
            files_per_chunk = candidate // EPOCHS_PER_FILE
            ramp = (
                r["write_last_s"] / r["write_first_s"]
                if r["write_first_s"]
                else float("nan")
            )
            print(
                f"{candidate:>7} | {files_per_chunk:>9} | {r['write_total_s']:>8.2f} | "
                f"{ramp:>5.1f}x | {r['read_open_s']:>7.3f} | {r['read_load_s']:>7.3f} | "
                f"{r['n_files_disk']:>10} | {r['mb_disk']:>8.1f}"
            )
    finally:
        shutil.rmtree(bench_root, ignore_errors=True)


if __name__ == "__main__":
    main()
