#!/usr/bin/env python3
"""Parallelization strategy benchmark for canvodpy.

Compares three strategies for processing the same set of 24h RINEX files:

  S0 — Baseline: fresh ProcessPoolExecutor per receiver-day (current code)
  S1 — Warm pool, bounded 2N window, per-day submission
  S2 — Warm pool, bounded 2N window, flat LPT across all days × receivers

Usage
-----
    uv run python dev/benchmark_strategies.py [--workers N] [--days-dir PATH]

Options
-------
--workers N      Parallel workers (default: os.cpu_count())
--days-dir PATH  Root data directory (default: /Volumes/ExtremePro/Daily_data)
--dry-run        Process only 1 day, skip writes (completes in <2 min)

Dependencies
------------
psutil is required.  loky is optional (improves S1/S2 pool reuse; falls back
to a long-lived ProcessPoolExecutor if not installed):

    uv add --dev loky psutil       # add to project
    # or: uv pip install loky psutil
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import psutil
import xarray as xr
from canvodpy.orchestrator.processor import preprocess_with_hermite_aux
from icechunk.xarray import to_icechunk

from canvod.auxiliary.interpolation import (
    ClockConfig,
    ClockInterpolationStrategy,
    Sp3Config,
    Sp3InterpolationStrategy,
)
from canvod.auxiliary.pipeline import AuxDataPipeline
from canvod.auxiliary.position.position import ECEFPosition
from canvod.readers.matching import MatchedDirs
from canvod.store.store import MyIcechunkStore

# ── canvodpy / canvod imports ─────────────────────────────────────────────────
from canvod.utils.config import load_config
from canvod.utils.tools import YYYYDOY

# ── optional loky (S1 / S2) ──────────────────────────────────────────────────
try:
    from loky import get_reusable_executor as _loky_reusable

    HAS_LOKY = True
except ImportError:
    HAS_LOKY = False
    _loky_reusable = None  # type: ignore[assignment]

# ── constants ─────────────────────────────────────────────────────────────────
DEFAULT_DAYS_DIR = Path("/Volumes/ExtremePro/Daily_data")
DEFAULT_WORKERS = os.cpu_count() or 4
DOYS = [f"25{i:03d}" for i in range(1, 29)]  # 28 days: 25001–25028
RECEIVERS = [
    ("reference", "01_reference"),
    ("canopy", "02_canopy"),
]
READER_NAME = "rinex3"


# ── module-level sentinel for pool warm-up (must be picklable) ────────────────
def _noop(x: int) -> int:
    """Trivial picklable worker used to pre-fork pool processes."""
    return x


def _timed_preprocess(*args):
    """Worker wrapper: measures actual compute time inside the worker process.

    Returns the original 4-tuple from preprocess_with_hermite_aux plus a fifth
    element: the wall time spent executing (seconds, float).  Measured inside
    the worker so queue-wait time is excluded — this gives an accurate CPU-util
    denominator.
    """
    t0 = time.perf_counter()
    result = preprocess_with_hermite_aux(*args)
    return (*result, time.perf_counter() - t0)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def doy_to_yyyydoy(doy: str) -> str:
    """'25001' → '2025001' (YYDDD → YYYYDDD)."""
    return f"20{doy[:2]}{doy[2:]}"


def parse_sampling_s(fname: str) -> float:
    """Extract sampling interval in seconds from a filename part like '05S'.

    Falls back to 5.0 s (typical 24 h RINEX).
    """
    m = re.search(r"_(\d+)([SMHZ])_", fname)
    if m:
        val, unit = int(m.group(1)), m.group(2)
        return {
            "S": float(val),
            "M": float(val * 60),
            "H": float(val * 3600),
            "Z": 1.0 / val if val else 1.0,
        }.get(unit, 5.0)
    return 5.0


def discover_files(days_dir: Path, n_days: int) -> dict[str, dict[str, list[Path]]]:
    """Return ``{doy: {rx_name: [sorted .rnx files]}}``."""
    result: dict[str, dict[str, list[Path]]] = {}
    for doy in DOYS[:n_days]:
        result[doy] = {}
        for rx_name, subdir in RECEIVERS:
            d = days_dir / subdir / doy
            files = sorted(d.glob("*.rnx"))
            if not files:
                raise FileNotFoundError(f"No .rnx files in {d}")
            result[doy][rx_name] = files
            sizes = [f.stat().st_size // 1_048_576 for f in files]
            print(
                f"  {doy}/{rx_name}: {len(files)} file(s)  "
                f"[{min(sizes)}–{max(sizes)} MB]"
            )
    return result


def read_receiver_position(rnx_file: Path) -> ECEFPosition:
    """Extract ECEF position from a RINEX file's header attributes."""
    from canvodpy.factories import ReaderFactory

    reader = ReaderFactory.create(READER_NAME, fpath=rnx_file)
    ds = reader.to_ds(keep_data_vars=[], write_global_attrs=True)
    return ECEFPosition.from_ds_metadata(ds)


# ─────────────────────────────────────────────────────────────────────────────
# Aux-zarr builder
# ─────────────────────────────────────────────────────────────────────────────


def build_aux_zarr(
    doy: str,
    days_dir: Path,
    canopy_files: list[Path],
    out_dir: Path,
) -> Path:
    """Build a Hermite-interpolated aux zarr for one DOY.

    Mirrors ``_preprocess_aux_data_with_hermite`` but as a standalone function
    (no processor object needed). Results are written to *out_dir* and
    cached — calling twice for the same DOY is a no-op.

    Returns
    -------
    Path
        Path to the ``.zarr`` file.
    """
    out_path = out_dir / f"aux_{doy}.zarr"
    if out_path.exists():
        return out_path  # cached from a previous call

    yyyydoy_str = doy_to_yyyydoy(doy)  # e.g. "2025001"
    matched_dirs = MatchedDirs(
        canopy_data_dir=days_dir / "02_canopy" / doy,
        reference_data_dir=days_dir / "01_reference" / doy,
        yyyydoy=YYYYDOY.from_str(yyyydoy_str),
    )

    # Load SP3 + CLK via the standard pipeline (files already on disk, no download)
    pipeline = AuxDataPipeline.create_standard(
        matched_dirs=matched_dirs,
        aux_file_path=days_dir,
    )
    pipeline.load_all()

    # Build the full-day target epoch grid
    sampling_s = parse_sampling_s(canopy_files[0].name)
    doy_int = int(yyyydoy_str[4:])
    year_int = int(yyyydoy_str[:4])
    day0 = datetime.date(year_int, 1, 1) + datetime.timedelta(days=doy_int - 1)
    day_start = np.datetime64(day0, "D")
    n_epochs = int(24 * 3600 / sampling_s)
    target_epochs = day_start + np.arange(n_epochs) * np.timedelta64(
        int(sampling_s), "s"
    )

    ephem_ds = pipeline.get("ephemerides")
    clock_ds = pipeline.get("clock")

    ephem_interp = Sp3InterpolationStrategy(
        config=Sp3Config(use_velocities=True, fallback_method="linear")
    ).interpolate(ephem_ds, target_epochs)

    clock_interp = ClockInterpolationStrategy(
        config=ClockConfig(window_size=9, jump_threshold=1e-6)
    ).interpolate(clock_ds, target_epochs)

    aux_processed = xr.merge([ephem_interp, clock_interp])
    aux_processed.to_zarr(out_path, mode="w", consolidated=False)

    mb = sum(f.stat().st_size for f in out_path.rglob("*") if f.is_file()) // 1_048_576
    print(f"    aux zarr built: {out_path.name}  (~{mb} MB)")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Icechunk write helper (sequential — timing the write step in isolation)
# ─────────────────────────────────────────────────────────────────────────────


def write_day_to_store(
    datasets: list[tuple[Path, xr.Dataset]],
    rx_name: str,
    store_path: Path,
) -> float:
    """Write one receiver-day batch to a fresh temp Icechunk store.

    Returns wall-time of the write (open session → commit) in seconds.
    Does NOT include pool creation or data-processing time.
    """
    store = MyIcechunkStore(store_path, store_type="rinex_store")
    groups: list[str] = store.list_groups() or []

    t0 = time.perf_counter()
    with store.writable_session("main") as session:
        for idx, (_, ds) in enumerate(datasets):
            # Best-effort cleanse (private helpers; skip if API changed)
            try:
                ds = store._cleanse_dataset_attrs(ds)
                ds = store._normalize_encodings(ds)
            except AttributeError:
                pass

            if idx == 0 and rx_name not in groups:
                to_icechunk(ds, session, group=rx_name)
                groups.append(rx_name)
            else:
                to_icechunk(ds, session, group=rx_name, append_dim="epoch")

        session.commit(f"benchmark: {rx_name}")

    return time.perf_counter() - t0


# ─────────────────────────────────────────────────────────────────────────────
# System resource monitor (background thread, 0.5 s sampling)
# ─────────────────────────────────────────────────────────────────────────────


class SystemMonitor:
    """Sample system-wide CPU, RAM, swap and driver RSS every 0.5 s.

    Maintains a full time series (one dict per sample) so callers can track
    resource usage continuously over time, not just see peak snapshots.

    Usage::

        mon = SystemMonitor()
        mon.start()
        # ... run strategy ...
        peaks  = mon.stop()        # dict of peak / avg metrics
        series = mon.time_series() # list of per-sample dicts (after stop())
    """

    INTERVAL = 0.5  # seconds between samples

    def __init__(self) -> None:
        self._proc = psutil.Process()
        self._running = False
        self._thread: threading.Thread | None = None
        self._t_start: float = 0.0

        # Time series — one entry per sample tick
        self._timestamps: list[float] = []  # seconds since start()
        self._driver_rss: list[float] = []  # MB
        self._sys_ram_pct: list[float] = []  # %
        self._sys_ram_mb: list[float] = []  # MB used
        self._cpu_avg: list[float] = []  # system-wide average %
        self._cpu_cores: list[list[float]] = []  # per-core %
        self._swap_mb: list[float] = []  # MB used

    def start(self) -> None:
        # Prime cpu_percent — first call always returns 0.0 (no prior reference)
        psutil.cpu_percent(percpu=True)
        self._t_start = time.perf_counter()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        """Stop sampling and return a dict of peak and average metrics."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

        def _peak(seq):
            return max(seq) if seq else 0.0

        def _avg(seq):
            return sum(seq) / len(seq) if seq else 0.0

        n_cores = len(self._cpu_cores[0]) if self._cpu_cores else 0
        per_core_peak = (
            [max(s[c] for s in self._cpu_cores) for c in range(n_cores)]
            if n_cores
            else []
        )

        total_ram_mb = psutil.virtual_memory().total / 1024**2

        return {
            "n_samples": len(self._timestamps),
            "n_cores": n_cores,
            "total_ram_mb": total_ram_mb,
            "peak_driver_rss_mb": _peak(self._driver_rss),
            "avg_driver_rss_mb": _avg(self._driver_rss),
            "peak_sys_ram_pct": _peak(self._sys_ram_pct),
            "avg_sys_ram_pct": _avg(self._sys_ram_pct),
            "peak_sys_ram_mb": _peak(self._sys_ram_mb),
            "peak_cpu_pct": _peak(self._cpu_avg),
            "avg_cpu_pct": _avg(self._cpu_avg),
            "per_core_peak_pct": per_core_peak,
            "n_cores_gt50": sum(1 for p in per_core_peak if p > 50),
            "n_cores_gt90": sum(1 for p in per_core_peak if p > 90),
            "peak_swap_mb": _peak(self._swap_mb),
        }

    def time_series(self) -> list[dict]:
        """Return all samples as a list of dicts with relative timestamps.

        Call after ``stop()``.  Each dict has keys: ``t_s``, ``driver_rss_mb``,
        ``sys_ram_pct``, ``sys_ram_mb``, ``cpu_avg_pct``, ``swap_mb``,
        and ``core{N}_pct`` for each logical core.
        """
        rows = []
        for i, t in enumerate(self._timestamps):
            row: dict = {
                "t_s": round(t, 2),
                "driver_rss_mb": round(self._driver_rss[i], 1),
                "sys_ram_pct": round(self._sys_ram_pct[i], 1),
                "sys_ram_mb": round(self._sys_ram_mb[i], 1),
                "cpu_avg_pct": round(self._cpu_avg[i], 1),
                "swap_mb": round(self._swap_mb[i], 1),
            }
            if i < len(self._cpu_cores):
                for c, pct in enumerate(self._cpu_cores[i]):
                    row[f"core{c}_pct"] = round(pct, 1)
            rows.append(row)
        return rows

    def _run(self) -> None:
        while self._running:
            time.sleep(self.INTERVAL)
            t = time.perf_counter() - self._t_start
            try:
                driver_mb = self._proc.memory_info().rss / 1024**2
                vm = psutil.virtual_memory()
                per_core = psutil.cpu_percent(percpu=True)
                swap_mb = psutil.swap_memory().used / 1024**2

                self._timestamps.append(t)
                self._driver_rss.append(driver_mb)
                self._sys_ram_pct.append(vm.percent)
                self._sys_ram_mb.append((vm.total - vm.available) / 1024**2)
                self._cpu_cores.append(per_core)
                self._cpu_avg.append(sum(per_core) / len(per_core) if per_core else 0.0)
                self._swap_mb.append(swap_mb)

            except psutil.NoSuchProcess, psutil.AccessDenied:
                break


# ─────────────────────────────────────────────────────────────────────────────
# Bounded-window submission
# ─────────────────────────────────────────────────────────────────────────────


def bounded_submit(executor, fn, tasks, n_workers):
    """Submit tasks with a 2N in-flight window; yield ``(future, task)`` as each completes.

    Keeps at most ``2 × n_workers`` futures in-flight so the driver never
    accumulates all result datasets in memory at once.

    IMPORTANT: do NOT wrap as_completed in list() — that exhausts the entire
    iterator and blocks until ALL futures finish, defeating the window entirely.
    Use next() to drain exactly one future before re-filling.
    """
    window = n_workers * 2
    pending: dict = {}  # future → (task, t_submit)
    task_iter = iter(tasks)

    def _fill_one() -> None:
        task = next(task_iter, None)
        if task is not None:
            fut = executor.submit(fn, *task)
            pending[fut] = (task, time.perf_counter())

    for _ in range(window):
        _fill_one()

    while pending:
        # next(as_completed(...)) blocks until exactly ONE future is done —
        # do NOT use list(as_completed(...)) which waits for ALL.
        fut = next(as_completed(list(pending)))
        task, t_sub = pending.pop(fut)
        yield fut, task, time.perf_counter() - t_sub
        _fill_one()


# ─────────────────────────────────────────────────────────────────────────────
# Warm-pool factory
# ─────────────────────────────────────────────────────────────────────────────


def make_warm_pool(n_workers: int):
    """Return a warm process pool.

    Uses ``loky.get_reusable_executor`` if available (better health
    monitoring); otherwise falls back to a manually kept-alive
    ``ProcessPoolExecutor``.  In both cases the workers are pre-forked before
    returning, so the caller sees zero spawn latency on first submit.
    """
    t0 = time.perf_counter()
    if HAS_LOKY:
        executor = _loky_reusable(max_workers=n_workers, timeout=300)
    else:
        executor = ProcessPoolExecutor(max_workers=n_workers)

    # Pre-fork: submit one no-op per worker
    list(executor.map(_noop, range(n_workers)))
    elapsed = time.perf_counter() - t0
    pool_type = "loky" if HAS_LOKY else "ProcessPoolExecutor(reused)"
    print(f"  warm pool ready: {pool_type}, {n_workers} workers, spawn={elapsed:.2f}s")
    return executor, elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Worker task arguments builder
# ─────────────────────────────────────────────────────────────────────────────


def make_task(
    f: Path,
    aux_path: Path,
    pos: ECEFPosition,
    rx_name: str,
    keep_vars: list[str] | None = None,
    keep_sids: list[str] | None = None,
) -> tuple:
    """Pack positional args for ``preprocess_with_hermite_aux``."""
    return (
        f,
        keep_vars,
        aux_path,
        pos,
        rx_name,
        keep_sids,
        READER_NAME,
        False,  # use_sbf_geometry
        False,  # store_radial_distance
        False,  # store_sbf_raw_observables
    )


# ─────────────────────────────────────────────────────────────────────────────
# Strategy S0 — fresh pool per receiver-day (current baseline)
# ─────────────────────────────────────────────────────────────────────────────


def run_s0(
    file_map: dict,
    aux_zarrs: dict,
    positions: dict,
    n_workers: int,
    store_base: Path,
    dry_run: bool,
    keep_vars: list[str] | None = None,
    keep_sids: list[str] | None = None,
) -> dict:
    """S0: new ``ProcessPoolExecutor`` for every receiver-day."""
    mem = SystemMonitor()
    mem.start()

    m: dict = dict(
        name="S0 current",
        wall=0.0,
        pool_spawn=0.0,
        cpu_seconds=0.0,
        write_seconds=[],
        n_tasks=0,
        n_errors=0,
        per_day={},
        events=[],
    )
    t_wall = time.perf_counter()

    def _ev(kind: str, detail: str = "") -> None:
        m["events"].append((round(time.perf_counter() - t_wall, 3), kind, detail))

    for doy, rx_map in file_map.items():
        m["per_day"][doy] = {}
        aux_path = aux_zarrs[doy]

        for rx_name, files in rx_map.items():
            pos = positions[rx_name]
            store_path = store_base / f"s0_{doy}_{rx_name}"
            t_rx = time.perf_counter()
            results_rx: list[tuple[Path, xr.Dataset]] = []
            task_durs: list[float] = []
            spawn_s = 0.0
            first_done = False

            _ev("spawn_start", f"{rx_name}/{doy}")
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                t_spawn_start = time.perf_counter()
                futures = {
                    executor.submit(
                        _timed_preprocess,
                        *make_task(f, aux_path, pos, rx_name, keep_vars, keep_sids),
                    ): (f, time.perf_counter())
                    for f in files
                }
                _ev("tasks_submitted", f"{rx_name}/{doy} n={len(files)}")

                for fut in as_completed(futures):
                    t_done = time.perf_counter()
                    _f, t_sub = futures[fut]
                    if not first_done:
                        spawn_s = t_done - t_spawn_start
                        first_done = True
                        _ev("spawn_done", f"overhead={spawn_s:.2f}s")
                    try:
                        fname, ds, _, _, cpu_s = fut.result()
                        results_rx.append((fname, ds))
                        task_durs.append(cpu_s)
                        m["n_tasks"] += 1
                        _ev(
                            "task_done",
                            f"{rx_name}/{doy}/{fname.name} cpu={cpu_s:.2f}s",
                        )
                    except Exception as exc:
                        print(f"    [S0] worker error ({rx_name}/{doy}): {exc}")
                        m["n_errors"] += 1
                        _ev("task_error", f"{rx_name}/{doy}: {exc}")

            m["pool_spawn"] += spawn_s
            m["cpu_seconds"] += sum(task_durs)

            write_s = 0.0
            if not dry_run and results_rx:
                _ev("write_start", f"{rx_name}/{doy}")
                write_s = write_day_to_store(results_rx, rx_name, store_path)
                m["write_seconds"].append(write_s)
                _ev("write_done", f"{rx_name}/{doy} dur={write_s:.2f}s")

            rx_wall = time.perf_counter() - t_rx
            m["per_day"][doy][rx_name] = dict(
                wall=rx_wall, tasks=len(results_rx), write=write_s
            )
            print(
                f"    [S0] {doy}/{rx_name}: {rx_wall:.1f}s  "
                f"tasks={len(results_rx)}  write={write_s:.1f}s"
            )

    m["wall"] = time.perf_counter() - t_wall
    m["sys"] = mem.stop()
    m["timeseries"] = mem.time_series()
    return m


# ─────────────────────────────────────────────────────────────────────────────
# Strategy S1 — warm pool, bounded window, per receiver-day
# ─────────────────────────────────────────────────────────────────────────────


def run_s1(
    file_map: dict,
    aux_zarrs: dict,
    positions: dict,
    n_workers: int,
    store_base: Path,
    dry_run: bool,
    keep_vars: list[str] | None = None,
    keep_sids: list[str] | None = None,
) -> dict:
    """S1: one warm pool, bounded 2N window, submit one receiver-day at a time."""
    mem = SystemMonitor()
    mem.start()

    m: dict = dict(
        name="S1 loky/day",
        wall=0.0,
        pool_spawn=0.0,
        cpu_seconds=0.0,
        write_seconds=[],
        n_tasks=0,
        n_errors=0,
        per_day={},
        events=[],
    )
    t_wall = time.perf_counter()

    def _ev(kind: str, detail: str = "") -> None:
        m["events"].append((round(time.perf_counter() - t_wall, 3), kind, detail))

    _ev("spawn_start")
    executor, spawn_s = make_warm_pool(n_workers)
    m["pool_spawn"] = spawn_s
    _ev("spawn_done", f"overhead={spawn_s:.2f}s")

    try:
        for doy, rx_map in file_map.items():
            m["per_day"][doy] = {}
            aux_path = aux_zarrs[doy]

            for rx_name, files in rx_map.items():
                pos = positions[rx_name]
                store_path = store_base / f"s1_{doy}_{rx_name}"
                t_rx = time.perf_counter()
                results_rx: list[tuple[Path, xr.Dataset]] = []

                tasks = [
                    make_task(f, aux_path, pos, rx_name, keep_vars, keep_sids)
                    for f in files
                ]
                _ev("tasks_submitted", f"{rx_name}/{doy} n={len(tasks)}")
                for fut, _, _ in bounded_submit(
                    executor, _timed_preprocess, tasks, n_workers
                ):
                    try:
                        fname, ds, _, _, cpu_s = fut.result()
                        results_rx.append((fname, ds))
                        m["cpu_seconds"] += cpu_s
                        m["n_tasks"] += 1
                        _ev(
                            "task_done",
                            f"{rx_name}/{doy}/{fname.name} cpu={cpu_s:.2f}s",
                        )
                    except Exception as exc:
                        print(f"    [S1] worker error ({rx_name}/{doy}): {exc}")
                        m["n_errors"] += 1
                        _ev("task_error", f"{rx_name}/{doy}: {exc}")

                write_s = 0.0
                if not dry_run and results_rx:
                    _ev("write_start", f"{rx_name}/{doy}")
                    write_s = write_day_to_store(results_rx, rx_name, store_path)
                    m["write_seconds"].append(write_s)
                    _ev("write_done", f"{rx_name}/{doy} dur={write_s:.2f}s")

                rx_wall = time.perf_counter() - t_rx
                m["per_day"][doy][rx_name] = dict(
                    wall=rx_wall, tasks=len(results_rx), write=write_s
                )
                print(
                    f"    [S1] {doy}/{rx_name}: {rx_wall:.1f}s  "
                    f"tasks={len(results_rx)}  write={write_s:.1f}s"
                )
    finally:
        if not HAS_LOKY:
            executor.shutdown(wait=False)

    m["wall"] = time.perf_counter() - t_wall
    m["sys"] = mem.stop()
    m["timeseries"] = mem.time_series()
    return m


# ─────────────────────────────────────────────────────────────────────────────
# Strategy S2 — warm pool, flat LPT submission across all days × receivers
# ─────────────────────────────────────────────────────────────────────────────


def run_s2(
    file_map: dict,
    aux_zarrs: dict,
    positions: dict,
    n_workers: int,
    store_base: Path,
    dry_run: bool,
    keep_vars: list[str] | None = None,
    keep_sids: list[str] | None = None,
) -> dict:
    """S2: warm pool, flat LPT task list (all days × receivers), bounded 2N window.

    Results are accumulated by (doy, rx_name) and written per receiver-day once
    all tasks complete.  LPT (Longest Processing Time) ordering maximises
    throughput by ensuring the biggest files start first.
    """
    mem = SystemMonitor()
    mem.start()

    m: dict = dict(
        name="S2 loky/flat",
        wall=0.0,
        pool_spawn=0.0,
        cpu_seconds=0.0,
        write_seconds=[],
        n_tasks=0,
        n_errors=0,
        per_day={},
        events=[],
    )
    t_wall = time.perf_counter()

    def _ev(kind: str, detail: str = "") -> None:
        m["events"].append((round(time.perf_counter() - t_wall, 3), kind, detail))

    _ev("spawn_start")
    executor, spawn_s = make_warm_pool(n_workers)
    m["pool_spawn"] = spawn_s
    _ev("spawn_done", f"overhead={spawn_s:.2f}s")

    # ── Build flat task list (file_size DESC = LPT order) ────────────────────
    flat: list[tuple[int, tuple, str, str]] = []  # (size, args, doy, rx_name)
    for doy, rx_map in file_map.items():
        m["per_day"][doy] = {}
        for rx_name, files in rx_map.items():
            m["per_day"][doy][rx_name] = dict(wall=0.0, tasks=0, write=0.0)
            aux_path = aux_zarrs[doy]
            pos = positions[rx_name]
            for f in files:
                flat.append(
                    (
                        f.stat().st_size,
                        make_task(f, aux_path, pos, rx_name, keep_vars, keep_sids),
                        doy,
                        rx_name,
                    )
                )

    flat.sort(key=lambda x: x[0], reverse=True)  # LPT: largest first
    print(
        f"  flat task list: {len(flat)} files  "
        f"[{flat[-1][0] // 1_048_576}–{flat[0][0] // 1_048_576} MB]"
    )

    tasks_only = [t for _, t, _, _ in flat]
    doy_rx_list = [(doy, rx) for _, _, doy, rx in flat]

    # ── Expected tasks per (doy, rx_name) — needed to know when to write ────────
    expected_tasks: dict[tuple[str, str], int] = {
        (doy, rx_name): len(files)
        for doy, rx_map in file_map.items()
        for rx_name, files in rx_map.items()
    }

    # ── Submit with bounded window; write as each receiver-day completes ───────
    # collected holds in-progress partial results; entries are deleted after write
    # to free memory immediately rather than accumulating all 12 datasets at once.
    collected: dict[tuple[str, str], list[tuple[Path, xr.Dataset]]] = {
        (doy, rx): [] for _, _, doy, rx in flat
    }

    window = n_workers * 2
    pending: dict = {}  # future → (doy, rx_name, t_submit)
    idx_iter = iter(range(len(tasks_only)))

    def _fill_one() -> None:
        i = next(idx_iter, None)
        if i is None:
            return
        fut = executor.submit(_timed_preprocess, *tasks_only[i])
        pending[fut] = (*doy_rx_list[i], time.perf_counter())

    for _ in range(window):
        _fill_one()

    try:
        while pending:
            # next() drains exactly ONE completed future — do NOT use
            # list(as_completed(...)) which blocks until ALL finish.
            fut = next(as_completed(list(pending)))
            doy, rx_name, t_sub = pending.pop(fut)
            try:
                fname, ds, _, _, cpu_s = fut.result()
                collected[(doy, rx_name)].append((fname, ds))
                m["cpu_seconds"] += cpu_s
                m["n_tasks"] += 1
                _ev("task_done", f"{rx_name}/{doy}/{fname.name} cpu={cpu_s:.2f}s")

                # Write immediately when the last file for this receiver-day arrives.
                # Delete from collected right after to free dataset memory.
                if len(collected[(doy, rx_name)]) >= expected_tasks[(doy, rx_name)]:
                    datasets = collected.pop((doy, rx_name))
                    write_s = 0.0
                    if not dry_run:
                        store_path = store_base / f"s2_{doy}_{rx_name}"
                        _ev("write_start", f"{rx_name}/{doy}")
                        write_s = write_day_to_store(datasets, rx_name, store_path)
                        m["write_seconds"].append(write_s)
                        _ev("write_done", f"{rx_name}/{doy} dur={write_s:.2f}s")
                    m["per_day"][doy][rx_name]["tasks"] = len(datasets)
                    m["per_day"][doy][rx_name]["write"] = write_s
                    print(
                        f"    [S2] {doy}/{rx_name}: tasks={len(datasets)}  write={write_s:.1f}s"
                    )

            except Exception as exc:
                print(f"    [S2] worker error ({rx_name}/{doy}): {exc}")
                m["n_errors"] += 1
            _fill_one()
    finally:
        if not HAS_LOKY:
            executor.shutdown(wait=False)

    # Handle any receiver-days that never completed (e.g. all tasks errored)
    for (doy, rx_name), datasets in collected.items():
        if datasets:
            m["per_day"][doy][rx_name]["tasks"] = len(datasets)

    m["wall"] = time.perf_counter() - t_wall
    m["sys"] = mem.stop()
    m["timeseries"] = mem.time_series()
    return m


# ─────────────────────────────────────────────────────────────────────────────
# CSV export — time series + event log
# ─────────────────────────────────────────────────────────────────────────────


def save_results_csv(results: list[dict], out_dir: Path) -> None:
    """Write two CSV files per run:

    ``timeseries_<ts>.csv``  — one row per 0.5 s sample, all strategies
    ``events_<ts>.csv``      — one row per logged event, all strategies

    Both can be joined on ``strategy`` + ``t_s`` for cross-referencing resource
    usage against pipeline events.
    """
    import csv

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Time series ───────────────────────────────────────────────────────────
    ts_path = out_dir / f"timeseries_{ts}.csv"
    ts_rows: list[dict] = []
    for r in results:
        for row in r.get("timeseries", []):
            ts_rows.append({"strategy": r["name"], **row})

    if ts_rows:
        fields = list(ts_rows[0].keys())
        with open(ts_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(ts_rows)
        print(f"  time series → {ts_path}  ({len(ts_rows)} rows)")

    # ── Event log ─────────────────────────────────────────────────────────────
    ev_path = out_dir / f"events_{ts}.csv"
    ev_rows: list[dict] = []
    for r in results:
        for t_s, kind, detail in r.get("events", []):
            ev_rows.append(
                {"strategy": r["name"], "t_s": t_s, "event": kind, "detail": detail}
            )

    if ev_rows:
        with open(ev_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["strategy", "t_s", "event", "detail"])
            w.writeheader()
            w.writerows(ev_rows)
        print(f"  event log   → {ev_path}  ({len(ev_rows)} events)")


# ─────────────────────────────────────────────────────────────────────────────
# ASCII sparkline helper
# ─────────────────────────────────────────────────────────────────────────────

_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def sparkline(
    values: list[float], width: int = 64, vmin: float = 0.0, vmax: float = 100.0
) -> str:
    """Render a sequence of floats as a Unicode block sparkline of given width."""
    if not values:
        return "─" * width
    # Resample to exactly `width` points via nearest-neighbour
    n = len(values)
    indices = [int(i * n / width) for i in range(width)]
    sampled = [values[min(i, n - 1)] for i in indices]
    span = max(vmax - vmin, 1e-9)
    chars = []
    for v in sampled:
        idx = int((v - vmin) / span * (len(_SPARK_CHARS) - 1))
        chars.append(_SPARK_CHARS[max(0, min(len(_SPARK_CHARS) - 1, idx))])
    return "".join(chars)


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────


def print_report(results: list[dict], n_workers: int, dry_run: bool) -> None:
    W = 84
    print()
    print("=" * W)
    print(
        f"  BENCHMARK RESULTS  ({n_workers} workers"
        + ("  DRY-RUN — writes skipped" if dry_run else "")
        + ")"
    )
    print("=" * W)

    # ── Strategy comparison table ─────────────────────────────────────────────
    hdr = (
        f"{'Strategy':<16} {'Wall(s)':>8} {'Spawn(s)':>9} "
        f"{'wkr-CPU%':>9} {'DrvRSS(MB)':>11} "
        f"{'Write/day(s)':>13} {'Tasks/s':>8}"
    )
    print(hdr)
    print("-" * W)

    for r in results:
        wall = r["wall"]
        spawn = r.get("pool_spawn", 0.0)
        cpu_s = r.get("cpu_seconds", 0.0)
        cpu_util = 100.0 * cpu_s / (n_workers * wall) if wall > 0 else 0.0
        sys = r.get("sys", {})
        drv_mb = sys.get("peak_driver_rss_mb", 0.0)
        writes = r.get("write_seconds", [])
        avg_wr = sum(writes) / len(writes) if writes else 0.0
        tps = r["n_tasks"] / wall if wall > 0 else 0.0
        print(
            f"{r['name']:<16} {wall:>8.1f} {spawn:>9.2f} "
            f"{cpu_util:>8.1f}% {drv_mb:>11.0f} "
            f"{avg_wr:>13.1f} {tps:>8.2f}"
        )

    print("=" * W)

    # ── System resource peaks (per strategy) ─────────────────────────────────
    print()
    print("  System resource peaks  (sampled every 0.5 s)")
    print("-" * W)
    hdr2 = (
        f"{'Strategy':<16} {'SysRAM%':>8} {'SysRAM(GB)':>11} "
        f"{'SysCPU%':>8} {'Cores>50%':>10} {'Cores>90%':>10} "
        f"{'Swap(MB)':>9}"
    )
    print(hdr2)
    print("-" * W)

    for r in results:
        sys = r.get("sys", {})
        total = sys.get("total_ram_mb", 1.0)
        print(
            f"{r['name']:<16}"
            f" {sys.get('peak_sys_ram_pct', 0):>7.1f}%"
            f" {sys.get('peak_sys_ram_mb', 0) / 1024:>10.1f}"
            f" {sys.get('peak_cpu_pct', 0):>7.1f}%"
            f" {sys.get('n_cores_gt50', 0):>10}"
            f" {sys.get('n_cores_gt90', 0):>10}"
            f" {sys.get('peak_swap_mb', 0):>9.0f}"
        )

    print("=" * W)

    # ── Per-core peak bar chart (last strategy) ───────────────────────────────
    last_sys = results[-1].get("sys", {}) if results else {}
    per_core = last_sys.get("per_core_peak_pct", [])
    if per_core:
        print()
        print(
            f"  Per-core peak CPU% ({results[-1]['name']}, {len(per_core)} logical cores):"
        )
        for i, p in enumerate(per_core):
            filled = int(p / 5)
            print(f"  core{i:<2} {'█' * filled}{'░' * (20 - filled)} {p:5.1f}%")

    # ── Time-series sparklines ────────────────────────────────────────────────
    print()
    print(
        f"  Time-series sparklines  (each char ≈ {SystemMonitor.INTERVAL:.1f}s, "
        f"left = start, right = end)"
    )
    print(f"  {'Strategy':<16}  {'metric':>12}   [{'scale':^64}]")
    print("  " + "─" * 80)

    for r in results:
        ts = r.get("timeseries", [])
        if not ts:
            continue
        cpu = [s["cpu_avg_pct"] for s in ts]
        ram = [s["sys_ram_pct"] for s in ts]
        drv = [s["driver_rss_mb"] for s in ts]
        swap = [s["swap_mb"] for s in ts]
        name = r["name"]

        max_drv = max(drv) if drv else 1.0
        max_swap = max(swap) if swap else 1.0

        print(
            f"  {name:<16}  {'CPU avg%':>12}   [{sparkline(cpu, vmin=0, vmax=100)}]  0–100%"
        )
        print(
            f"  {'':<16}  {'SysRAM%':>12}   [{sparkline(ram, vmin=0, vmax=100)}]  0–100%"
        )
        print(
            f"  {'':<16}  {'DrvRSS MB':>12}   [{sparkline(drv, vmin=0, vmax=max_drv)}]  0–{max_drv:.0f} MB"
        )
        if max_swap > 10:
            print(
                f"  {'':<16}  {'Swap MB':>12}   [{sparkline(swap, vmin=0, vmax=max_swap)}]  0–{max_swap:.0f} MB"
            )
        print()

    # Per-day breakdown: S0 vs S2 wall time per receiver-day
    s0 = next((r for r in results if r["name"].startswith("S0")), None)
    s2 = next((r for r in results if r["name"].startswith("S2")), None)
    if s0 and s2 and s0.get("per_day"):
        print()
        print("Per-day wall time breakdown (S0 vs S2):")
        print(
            f"  {'DOY':<8} {'Receiver':<12} {'S0 wall(s)':>11} "
            f"{'S2 tasks':>9} {'S2 write(s)':>12}"
        )
        print("  " + "-" * 55)
        for doy in sorted(s0["per_day"]):
            for rx_name in sorted(s0["per_day"][doy]):
                s0_w = s0["per_day"][doy][rx_name].get("wall", 0.0)
                s2_rx = s2.get("per_day", {}).get(doy, {}).get(rx_name, {})
                s2_t = s2_rx.get("tasks", 0)
                s2_w = s2_rx.get("write", 0.0)
                print(f"  {doy:<8} {rx_name:<12} {s0_w:>11.1f} {s2_t:>9} {s2_w:>12.1f}")

    if not HAS_LOKY:
        print()
        print("NOTE: loky not installed — S1/S2 used a long-lived ProcessPoolExecutor.")
        print("      Install loky for reusable-executor semantics:")
        print("        uv add --dev loky")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--days-dir",
        type=Path,
        default=DEFAULT_DAYS_DIR,
        help=f"Root data directory (default: {DEFAULT_DAYS_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process only 1 day (2 files) and skip Icechunk writes",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Limit to first N days (default: all 28). --dry-run overrides to 1.",
    )
    args = parser.parse_args()

    n_workers = args.workers
    days_dir = args.days_dir
    dry_run = args.dry_run
    n_days = 1 if dry_run else (args.days if args.days is not None else len(DOYS))

    # ── Load config (keep_vars / keep_sids) ──────────────────────────────────
    cfg = load_config()
    keep_vars: list[str] | None = ["SNR"]
    keep_sids: list[str] | None = cfg.sids.custom_sids or None

    # ── Memory safety cap ─────────────────────────────────────────────────────
    # SNR-only + 277-SID curated config: ~0.67 GB peak per worker (tracemalloc).
    # macOS spawn adds ~3 GB one-time base per worker process; Linux fork shares
    # parent pages so incremental cost is data only.  Use 1.0 GB as conservative
    # estimate; revisit after lazy-padding reduces in-flight to ~100 observed SIDs.
    avail_gb = psutil.virtual_memory().available / 1024**3
    total_gb = psutil.virtual_memory().total / 1024**3
    n_sid_label = (
        f"{len(keep_sids)}-SID curated" if keep_sids else "all-SID global (3658)"
    )
    gb_per_worker = 1.0
    safe_workers = max(1, int(avail_gb * 0.70 / gb_per_worker))
    if n_workers > safe_workers:
        print(
            f"WARNING: {n_workers} workers requested but only {avail_gb:.0f} GB available."
        )
        print(
            f"  Estimated {gb_per_worker:.1f} GB per in-flight task (SNR-only, {n_sid_label})."
        )
        print(f"  Capping to {safe_workers} workers to stay under 70% RAM.")
        print(f"  Override: pass --workers {n_workers} after freeing memory.")
        n_workers = safe_workers

    print()
    print("canvodpy parallelization benchmark")
    print(f"  workers  : {n_workers}  (avail RAM: {avail_gb:.0f}/{total_gb:.0f} GB)")
    print(f"  window   : {n_workers * 2} tasks in-flight max")
    print(f"  days-dir : {days_dir}")
    print(f"  days     : {n_days}")
    print(f"  dry-run  : {dry_run}")
    print(
        f"  loky     : {'yes' if HAS_LOKY else 'no (using ProcessPoolExecutor fallback)'}"
    )
    print(f"  keep_vars: {keep_vars}")
    print(f"  keep_sids: {n_sid_label}")
    print()

    # ── Discover files ────────────────────────────────────────────────────────
    print("Discovering files...")
    file_map = discover_files(days_dir, n_days)
    total_files = sum(len(f) for rx in file_map.values() for f in rx.values())
    print(f"  total: {total_files} RINEX file(s)")

    # ── Receiver positions (read once from first file per receiver) ───────────
    print("\nReading receiver ECEF positions...")
    positions: dict[str, ECEFPosition] = {}
    first_doy = next(iter(file_map))
    for rx_name, files in file_map[first_doy].items():
        print(f"  {rx_name}: {files[0].name}")
        positions[rx_name] = read_receiver_position(files[0])
        lat, lon, alt = positions[rx_name].to_geodetic()
        print(f"    → lat={lat:.4f}°  lon={lon:.4f}°  alt={alt:.1f} m")

    # ── Build aux zarrs once (shared by all three strategies) ─────────────────
    aux_dir = Path(tempfile.mkdtemp(prefix="canvod_bench_aux_"))
    print(f"\nBuilding aux zarrs → {aux_dir}")
    aux_zarrs: dict[str, Path] = {}
    for doy, rx_map in file_map.items():
        canopy_files = rx_map.get("canopy", next(iter(rx_map.values())))
        print(f"  {doy} ...")
        aux_zarrs[doy] = build_aux_zarr(doy, days_dir, canopy_files, aux_dir)

    # ── Temp Icechunk store base ──────────────────────────────────────────────
    store_base = Path(tempfile.mkdtemp(prefix="canvod_bench_stores_"))
    print(f"\nTemp stores → {store_base}")

    all_results: list[dict] = []

    try:
        # ── S0: baseline ─────────────────────────────────────────────────────
        print("\n── S0 (fresh pool per receiver-day) ──")
        all_results.append(
            run_s0(
                file_map,
                aux_zarrs,
                positions,
                n_workers,
                store_base,
                dry_run,
                keep_vars=keep_vars,
                keep_sids=keep_sids,
            )
        )
        shutil.rmtree(store_base, ignore_errors=True)
        store_base.mkdir()

        # ── S1: warm pool, per-day ────────────────────────────────────────────
        print("\n── S1 (warm pool, bounded 2N window, per-day) ──")
        all_results.append(
            run_s1(
                file_map,
                aux_zarrs,
                positions,
                n_workers,
                store_base,
                dry_run,
                keep_vars=keep_vars,
                keep_sids=keep_sids,
            )
        )
        shutil.rmtree(store_base, ignore_errors=True)
        store_base.mkdir()

        # ── S2: warm pool, flat LPT ───────────────────────────────────────────
        print("\n── S2 (warm pool, bounded 2N window, flat LPT) ──")
        all_results.append(
            run_s2(
                file_map,
                aux_zarrs,
                positions,
                n_workers,
                store_base,
                dry_run,
                keep_vars=keep_vars,
                keep_sids=keep_sids,
            )
        )

    finally:
        print("\nCleaning up temp directories...")
        shutil.rmtree(aux_dir, ignore_errors=True)
        shutil.rmtree(store_base, ignore_errors=True)

    print_report(all_results, n_workers, dry_run)

    # ── Save time series + event log as CSV ──────────────────────────────────
    csv_dir = Path(__file__).parent / "benchmark_output"
    csv_dir.mkdir(exist_ok=True)
    print("\nSaving CSVs...")
    save_results_csv(all_results, csv_dir)


if __name__ == "__main__":
    main()
