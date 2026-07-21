"""Quick local chunk-size sweep -- validates the load_config() cache fix
(2026-07-21, packages/canvod-config/src/canvod/config/loader.py) end-to-end
through the real Site()/GnssResearchSite()/MyIcechunkStore() resolution path,
and gives a first (non-confounded) directional write-cost signal across
chunk sizes, without needing the external SSD or the remote CIFS share.

Each candidate epoch runs as its own subprocess (`uv run python -c ...`),
mirroring dev/rechunk_sweep_remote.sh's real "one `canvodpy run` process per
chunk size" shape -- including triggering `canvodpy.logging`'s module-level
`LOGGER = configure_logging()` import-time bare `load_config()` call, which
is exactly the call that used to poison the cache before the fix. If the fix
is broken, this script will show every leg resolving to the SAME store path.

Synthetic data (matches dev/bench_rechunk_sweep.py's shape: N_SID=277,
96 x 15-min files/day), not real RINEX -- this is a config/write-cost
sanity check, not a scientific-correctness test. One receiver group only
(not the real site's 4) to keep it quick; the real gfzrnx-based 28-day
remote sweep (dev/rechunk_sweep_remote.sh) is the one that matters for the
actual chunk-size decision.

Run: uv run python dev/local_chunk_sweep.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

CANDIDATES = [90, 180, 17280]
N_DAYS = 28
N_FILES_PER_DAY = 96  # 24h of 15-min files
EPOCHS_PER_FILE = 180  # 15 min @ 5s sampling
N_SID = 277
SITE_NAME = "LocalSweepSite"
RECEIVER = "canopy_01"

_LEG_SCRIPT = textwrap.dedent("""
    import json, os, sys, time
    import numpy as np
    import pandas as pd
    import xarray as xr

    scratch = sys.argv[1]
    epoch_chunk = int(sys.argv[2])

    config_dir = f"{{scratch}}/config_{{epoch_chunk}}"
    stores_root = f"{{scratch}}/stores_{{epoch_chunk}}"
    os.environ["CANVOD_CONFIG_DIR"] = config_dir

    # Import canvodpy.logging BEFORE touching config -- this is what fires
    # the module-level `LOGGER = configure_logging()` bare load_config()
    # call that poisoned the cache pre-fix.
    import canvodpy.logging  # noqa: F401

    from canvod.config import load_config
    early = load_config()
    early_store_root = str(early.processing.storage.stores_root_dir)

    from canvodpy.api import Site
    site = Site("{site_name}")
    store = site.gnss_store
    resolved_path = str(store.store_path)
    resolved_epoch = store.chunk_strategy.get("epoch")

    n_sid = {n_sid}
    epochs_per_file = {epochs_per_file}
    rng = np.random.default_rng(42)
    sid_values = np.array([f"S{{i:03d}}|L1|C" for i in range(n_sid)], dtype=object)
    code_values = np.array(["C"] * n_sid, dtype=object)
    band_values = np.array(["L1"] * n_sid, dtype=object)
    sv_values = np.array([f"S{{i:03d}}" for i in range(n_sid)], dtype=object)
    system_values = np.array(["G"] * n_sid, dtype=object)
    freq = np.full(n_sid, 1575.42e6, dtype=np.float32)

    def make_file(day, idx):
        start = (
            pd.Timestamp("2025-01-01")
            + pd.Timedelta(days=day)
            + pd.Timedelta(seconds=idx * epochs_per_file * 5)
        )
        epoch = pd.date_range(start, periods=epochs_per_file, freq="5s")
        snr = rng.uniform(20, 55, size=(epochs_per_file, n_sid)).astype(np.float32)
        phi = rng.uniform(0, 360, size=(epochs_per_file, n_sid)).astype(np.float64)
        theta = rng.uniform(0, 90, size=(epochs_per_file, n_sid)).astype(np.float64)
        return xr.Dataset(
            data_vars={{
                "SNR": (("epoch", "sid"), snr),
                "phi": (("epoch", "sid"), phi),
                "theta": (("epoch", "sid"), theta),
            }},
            coords={{
                "epoch": epoch,
                "sid": sid_values,
                "code": ("sid", code_values),
                "band": ("sid", band_values),
                "sv": ("sid", sv_values),
                "system": ("sid", system_values),
                "freq_min": ("sid", freq),
                "freq_center": ("sid", freq),
                "freq_max": ("sid", freq),
            }},
            attrs={{"File Hash": f"local-sweep-{{day}}-{{idx}}"}},
        )

    timings = []
    n_days = {n_days}
    n_files_per_day = {n_files_per_day}
    for day in range(n_days):
        for idx in range(n_files_per_day):
            ds = make_file(day, idx)
            t0 = time.perf_counter()
            store.write_or_append_group(
                ds, "{receiver}", commit_message=f"day={{day}} file={{idx}}"
            )
            timings.append(time.perf_counter() - t0)

    result = {{
        "epoch_chunk": epoch_chunk,
        "early_bare_stores_root": early_store_root,
        "resolved_store_path": resolved_path,
        "resolved_chunk_epoch": resolved_epoch,
        "n_writes": len(timings),
        "write_total_s": sum(timings),
        "write_mean_s": sum(timings) / len(timings) if timings else None,
        "write_first_s": timings[0] if timings else None,
        "write_last_s": timings[-1] if timings else None,
    }}
    with open(f"{{scratch}}/result_{{epoch_chunk}}.json", "w") as f:
        json.dump(result, f)
    print(json.dumps(result, indent=2))
""")


def _write_config(config_dir: Path, stores_root: Path, epoch_chunk: int) -> None:
    import yaml

    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": {
                        "author": "Local Sweep",
                        "email": "sweep@example.com",
                        "institution": "canvodpy",
                    },
                    "storage": {"stores_root_dir": str(stores_root)},
                    "icechunk": {
                        "chunk_strategies": {
                            "gnss_store": {"epoch": epoch_chunk, "sid": -1}
                        }
                    },
                },
                "sites": {
                    SITE_NAME: {
                        "gnss_site_data_root": str(stores_root / "raw"),
                        "receivers": {
                            RECEIVER: {"type": "canopy", "directory": "02_canopy"}
                        },
                    }
                },
            }
        )
    )


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="canvod_local_sweep_"))
    print(f"Scratch dir: {scratch}")
    print(
        f"Candidates: {CANDIDATES}, N_DAYS={N_DAYS}, N_FILES_PER_DAY={N_FILES_PER_DAY}\n"
    )

    leg_script_path = scratch / "leg.py"

    results = []
    try:
        for epoch_chunk in CANDIDATES:
            config_dir = scratch / f"config_{epoch_chunk}"
            stores_root = scratch / f"stores_{epoch_chunk}"
            _write_config(config_dir, stores_root, epoch_chunk)

            leg_script_path.write_text(
                _LEG_SCRIPT.format(
                    site_name=SITE_NAME,
                    receiver=RECEIVER,
                    n_sid=N_SID,
                    epochs_per_file=EPOCHS_PER_FILE,
                    n_days=N_DAYS,
                    n_files_per_day=N_FILES_PER_DAY,
                )
            )

            print(f"=== leg epoch={epoch_chunk}: spawning subprocess ===")
            proc = subprocess.run(
                [sys.executable, str(leg_script_path), str(scratch), str(epoch_chunk)],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                print(proc.stdout[-4000:])
                print(proc.stderr[-4000:])
                raise RuntimeError(f"leg epoch={epoch_chunk} failed (see above)")

            with open(scratch / f"result_{epoch_chunk}.json") as f:
                results.append(json.load(f))

        # ── Regression check: the actual bug this script exists to catch ──
        store_paths = {r["resolved_store_path"] for r in results}
        chunk_epochs = {r["epoch_chunk"]: r["resolved_chunk_epoch"] for r in results}
        print("\n=== config-resolution regression check ===")
        print(
            f"distinct resolved store paths across {len(CANDIDATES)} legs: {len(store_paths)}"
        )
        for r in results:
            print(
                f"  epoch={r['epoch_chunk']:>6}: store_path={r['resolved_store_path']}"
            )
        print(f"resolved chunk_strategy.epoch per leg: {chunk_epochs}")
        if len(store_paths) != len(CANDIDATES):
            print(
                "\n!!! REGRESSION: legs collapsed onto fewer store paths than "
                "candidates -- the load_config() cache-poisoning bug is back. !!!"
            )
        elif any(chunk_epochs[c] != c for c in CANDIDATES):
            print(
                "\n!!! REGRESSION: a leg's resolved chunk epoch doesn't match "
                "its intended candidate -- chunk_strategies overlay not applying. !!!"
            )
        else:
            print(
                "OK: every leg resolved a distinct store path and the correct "
                "chunk epoch. Bug fix holds under the real Site()/"
                "GnssResearchSite()/MyIcechunkStore() resolution path."
            )

        # ── Write-cost summary ──
        print("\n=== write-cost summary ===")
        header = f"{'epoch':>7} | {'n_writes':>8} | {'mean_s':>8} | {'total_s':>9} | {'first_s':>8} | {'last_s':>8}"
        print(header)
        print("-" * len(header))
        for r in results:
            print(
                f"{r['epoch_chunk']:>7} | {r['n_writes']:>8} | "
                f"{r['write_mean_s']:>8.4f} | {r['write_total_s']:>9.1f} | "
                f"{r['write_first_s']:>8.4f} | {r['write_last_s']:>8.4f}"
            )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
