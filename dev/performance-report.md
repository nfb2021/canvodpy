# Performance Investigation: canvodpy Processing Pipeline

**Branch:** `explore/performance-review`
**Date:** 2026-07-04
**Scope:** RINEX daily-file processing, 6-DOY benchmark, shared-machine constraints

---

## What we know

The per-receiver-day workload is now well characterized. Compute is ~23s CPU (dominated
by RINEX parsing, ephemeris augmentation, and gridding), the aux zarr build is ~15s wall
time and constant regardless of file size, and the Icechunk write is ~2s. The write is a
hard serialization point: Icechunk on local FS cannot handle concurrent writers, so writes
must remain sequential no matter how the compute is parallelized.

The dominant resource constraint is memory, not CPU. A 200 MB daily RINEX at 5s resolution
expands to **1.66 GB in memory** as an xarray Dataset (peak 2.39 GB during allocation),
measured via `tracemalloc` on a real 24h reference file. The runtime safety cap —
`safe_workers = max(1, int(available_ram_gb × 0.70 / gb_per_worker))` — is doing its job,
but on the development machine (avg ~10.7 GB available, min 7.4 GB, volatile) it clamped
the entire benchmark to a single worker. Every parallelism strategy therefore ran
sequentially; the benchmark measured structural overhead, not concurrency.

The ~8× on-disk-to-memory expansion factor is the primary lever for improving the pipeline.
Reducing it unlocks more workers within any given memory budget. See section below.

One incidental finding: `products.toml` only listed NASA CDDIS (auth required) for
CODE MGEX final ephemeris; the AIUB FTP source (no auth, identical files) was used via
direct curl for this benchmark and should be added to `products.toml` properly.

---

## Benchmark results

### Run 1 — baseline (all vars, global SID pad, 1 worker)

Six DOYs × 2 receivers = 12 tasks. Config: all variables, 3,658-SID global pad.
Memory cap forced 1 worker throughout.

| Strategy | Wall time | Per-task avg | Effective workers |
|---|---|---|---|
| S0 — current (pool re-spawned per day) | 408s | ~34s | 1 |
| S1 — persistent loky pool, sequential submit | 383s | ~32s | 1 |
| S2 — persistent pool, all tasks submitted upfront | 365s | ~30s | 1 |

S2 was only 11% faster than S0 because all three strategies were forced to 1 worker —
the memory cap left no room for concurrency.

### Run 2 — SNR-only + 277-SID curated config (6 workers)

Same 6 DOYs × 2 receivers = 12 tasks. Config: `keep_rnx_vars: [SNR]` + `sids.yaml`
277-SID curated list. Memory cap allowed 6 workers (10 GB available ÷ 1 GB/worker × 0.70).

| Strategy | Wall(s) | Spawn(s) | wkr-CPU% | Driver RSS | Swap | vs old S0 |
|---|---|---|---|---|---|---|
| S0 current | 182s | **173s** | 13% | 5,095 MB | 520 MB | 2.2× faster |
| S1 loky/day | 190s | 0.2s | 14% | 816 MB | 512 MB | 2.1× faster |
| **S2 loky/flat** | **138.6s** | 0.01s | **94%** | 867 MB | 2,358 MB | **2.9× faster** |

Key measurements:
- Per-task time dropped from ~34s → ~15s (reference) / ~13s (canopy) — **config change alone**
- S0 spawn overhead: 173s out of 182s total (95% waste — 6 workers spawned per task, 1 used)
- S2 pool creation once: 0.01s; workers stay warm across all 12 tasks
- S2 wkr-CPU%: 94% — workers are productive nearly the entire run
- S2 write/day: 0.8s avg (higher than S0's 0.1s because tasks complete out-of-order
  and writes cluster; Icechunk serialization point is visible here)
- **S2 swap: 2,358 MB** — macOS spawn creates a fresh Python process (~3 GB module
  imports) per worker × 6 workers = significant pressure on a 16 GB machine.
  On Linux fork, workers share the parent's read-only pages → ~0 MB incremental swap.

**S2 is 24% faster than S0 on the same data with real parallelism.** The 2.9× gain over
the old baseline combines: (a) 2.2× from config-driven memory reduction enabling 6 workers,
and (b) 1.3× from S2's flat LPT scheduling that overlaps reference+canopy tasks across DOYs.

**Why not 6× faster?** Per-task CPU time rises under contention (6 workers × numpy
multithreading saturates all 8 cores). The parallelism gain is real but bounded by
CPU/memory bandwidth saturation on macOS. On Linux, COW semantics eliminate the module
import overhead and would allow more workers within the same RAM budget.

### Run 3 — lazy padding (S2 only, 6 workers, 14 DOYs)

S2 with `pad_global_sid=False` + driver-side `reindex(sid=store_sids)` before commit.

| Strategy | Wall(s) | wkr-CPU% | DrvRSS | Swap | s/DOY |
|---|---|---|---|---|---|
| S2 lazy pad | 351.9s | 88.4% | 5,453 MB | 4,268 MB | 25.1s |
| S2 Run 2 (baseline) | *(138.6s / 6 DOYs)* | 94% | 867 MB | 2,358 MB | **23.1s** |

Lazy padding is **~9% slower** on macOS. Driver RSS ballooned to 5,453 MB (vs 867 MB)
and swap rose to 4,268 MB despite identical worker count. The reindex in the driver
accumulates expanded datasets faster than the sequential Icechunk write can drain them.

> **⚠️ ASSUMPTION:** The macOS result does not rule out a benefit on Linux.
> On Linux fork, per-worker cost is data-only (~0.25 GB lazy vs ~0.67 GB padded),
> potentially allowing ~2.7× more workers. This was **not measured** — production
> runs on Linux; benchmark there before drawing conclusions.

---

## In-memory expansion — measured

Profiled with `tracemalloc` on `ROSR01TUW_R_20250010000_01D_05S_AA.rnx` (207 MB on disk),
three configurations measured:

| Configuration | Current | Peak | sid dim |
|---|---|---|---|
| All vars, global SID pad (baseline) | 1,662 MB | 2,390 MB | 3,658 |
| SNR-only, global SID pad | 496 MB | 922 MB | 3,658 |
| SNR-only + 277-SID curated list | **273 MB** | **672 MB** | 277 |

**The 6× reduction is entirely config-driven — no code changes needed:**
- `keep_rnx_vars: [SNR]` in `processing.yaml` (drops Pseudorange, Phase, Doppler)
- `sids.yaml` with `mode: custom` and the 277 curated science-grade SIDs

Both files already exist in the codebase (`config/sids.yaml.bak` has 277 SIDs,
`processing.yaml.example` has SNR-only as the commented default).

**Why the peak (672 MB) is higher than current (273 MB):**
`_create_dataset_single_pass` in the reader allocates all four variable arrays
unconditionally at `(17280, n_observed_sids)` before `to_ds()` drops the unwanted ones.
Moving the variable filter into the allocation step would bring the peak down to match
current — a one-function code change.

**Lazy padding** (deferred `pad_to_global_sid`): the 277-SID config already avoids the
3,658-SID global pad. The remaining improvement is to defer padding to the write boundary
(`reindex(sid=store_axis)` just before Icechunk commit) so the in-flight dataset carries
only the actually-observed SIDs (~100 in practice). This is the prerequisite for S3.

**Measured on macOS: lazy padding provides no speedup (slightly slower, ~9%).**
Run 3 (lazy pad, 6 workers, 14 DOYs): S2 = 25.1s/DOY vs Run 2 (277-SID, 6 workers): 23.1s/DOY.
Driver RSS jumped to 5,453 MB (vs 867 MB) and swap rose to 4,268 MB (vs 2,358 MB), offsetting
the smaller per-task footprint.

> **⚠️ ASSUMPTION — not yet measured on Linux:** The expected benefit of lazy padding on Linux
> relies on fork/COW semantics: workers share the parent's read-only pages (module imports cost
> nothing incrementally) so the data footprint is the only incremental RAM per worker.
> Under that model, ~100 observed SIDs (~0.25 GB/worker) vs 277 SIDs (~0.67 GB/worker) would
> unlock ~2.7× more workers within the same RAM budget. This has **not been benchmarked** —
> the macOS numbers cannot confirm or refute it. Production runs on Linux; verify there.

**Worker count projection on 10 GB machine (peak as the binding constraint):**

| OS | Workers (loky spawn/fork) | Reasoning |
|---|---|---|
| macOS (spawn) | 6 | ~3 GB module imports dominate; data size irrelevant |
| Linux (fork/COW) — no lazy pad | ~14 | Imports shared; 0.67 GB data per worker |
| Linux (fork/COW) — lazy pad | ~28 | Imports shared; 0.25 GB data per worker |

> These Linux projections are **extrapolated from macOS measurements + OS fork semantics**,
> not directly benchmarked. Validate on the actual production server.

**Reducing in-memory footprint is the highest-leverage single improvement available.**
The config change is immediate; fixing the allocation order and implementing lazy padding
are medium-effort code changes that unlock S3 and pay off most on Linux.

### Run 4 — Production format benchmarks (S2 only, SNR-only + 277-SID)

Three formats run head-to-head on the same loky/flat S2 strategy with the curated SNR-only
config. Machine: MacBook 8-core/16 GB. Workers RAM-capped to available headroom.

| Format | DOYs | Workers | Wall(s) | s/DOY | Tasks total | Tasks/s | wkr-CPU% | SysRAM peak | Swap | Write/day |
|---|---|---|---|---|---|---|---|---|---|---|
| **rinex3** (24h .rnx) | 14 | 5 | 216.5s | **15.5s** | 28 | 0.13 | 89.3% | 82.9% (13.3 GB) | 778 MB | 0.5s |
| **rinex3_15min** (15-min .25o) | 7 | 7 | 306.3s | **43.8s** | 1,344 | 4.39 | 87.2% | 66.0% (10.6 GB) | 714 MB | 3.4s |
| **sbf** (15-min .25_) | 7 | 7 | 1,932.3s | **276.0s** | 1,344 | 0.70 | 99.3% | 59.6% (9.5 GB) | 706 MB | 7.0s |

Notes on coverage: `Sample_data` only has SP3/CLK cached for DOYs 1–7; `Daily_data` has
DOYs 1–14. RINEX 3 15-min and SBF both ran 7 DOYs. 24h RINEX ran all 14 from `Daily_data`.
Workers were capped below the requested 8 by the `gb_per_worker` safety formula.

**Key findings:**

**1. SBF is 6.3× slower per DOY than 15-min RINEX (276s vs 44s).**
Both formats have the same task count (1,344), the same 7 workers, and similar file sizes
(10–11 MB SBF vs 1–2 MB RINEX 3). The gap is pure CPU cost per task: SBF binary decode +
SatVisibility processing + the known `sbf_obs` concat bottleneck (noted in memory:
`processor.py:2744` — `xr.concat(sbf_parts, dim="epoch")` across all 96 parts before write).
The SBF CPU sparkline is perfectly flat (▇▇▇▇▇▇ throughout) at 99.3% — CPU-saturated
for the entire 32-minute run, meaning there is no headroom left.

**2. 24h RINEX is the most memory-hungry format — capped to 5 workers.**
A single 24h file expands to ~1.6 GB in memory (per earlier tracemalloc measurement),
peaking at 5,002 MB driver RSS and 13.3 GB system RAM at 5 workers. Only 5 workers fit
within the 70% RAM budget. At 7 workers it would hit 16 GB + swap. 15-min files (~1–2 MB)
produce much smaller per-task footprints, allowing 7 workers at lower total RAM.

**3. 24h RINEX is the most efficient format per DOY (15.5s), even with fewer workers.**
Normalised to 7 workers: 24h RINEX ≈ 11s/DOY, vs 44s/DOY for 15-min RINEX. The overhead
that multiplies with file fragmentation — one aux zarr build per DOY (constant regardless of
file count), Icechunk commit overhead (0.5s vs 3.4s/DOY for 96 commits), Python task
dispatch per file — costs ~3× more for 15-min files.

**4. Write overhead scales with fragmentation:**
0.5s/DOY (1 file) → 3.4s/DOY (96 RINEX files) → 7.0s/DOY (96 SBF files). SBF writes are
2× slower than RINEX 15-min despite the same commit count — the `sbf_obs` concat-then-write
adds a costly driver-side step after every commit.

**5. SBF fix is high priority.**
The sbf_obs bottleneck is fully identified. Fix: write each `sbf_obs` part directly to
Icechunk as an incremental dataset instead of accumulating all 96 parts in the driver and
concatenating. This would drop SBF from 276s/DOY to an expected ~50–80s/DOY (matching
15-min RINEX) and remove the CPU saturation. See `memory/performance_investigation.md`
for the exact code location.

---

## Architectural direction: S3 (split + shared aux zarr)

Once the memory footprint is under control, S3 addresses the remaining bottleneck for
large files (1s resolution: ~1 GB on disk, ~30 GB+ in memory at current encoding).

S3 splits the daily RINEX into N time-range chunks in memory — pure-Python epoch-boundary
scan, no gfzrnx, no disk I/O — builds the aux zarr once in the driver, and fans chunks
out to N parallel workers. Per-task memory scales as footprint / N.

For 5s files with SNR-only + lazy padding (~150 MB footprint), S2 with 8 workers likely
suffices without any splitting. For 1s files (5× larger: ~750 MB with same optimizations,
or ~8 GB without), N=4 splits → ~200 MB per task → comfortably 8 workers on a 10 GB
machine. S3 is the only architecture that survives the 1s-resolution future if memory
optimizations alone prove insufficient.

The quality-check step (epoch count, time span, gap detection via header scan, <1s) slots
naturally before the aux zarr build, validating the day before any expensive compute.

**Sequencing:**
1. Fix in-memory expansion first (SNR-only loading, float32, lazy padding)
2. Re-run the 28-DOY benchmark to measure real parallelism on the development machine
3. Establish production server specs (RAM, cores)
4. Profile the Icechunk write path under concurrency (2s/write × 8 workers = potential
   bottleneck if workers produce faster than the driver can commit)
5. Implement S3 if 1s files are confirmed as a production requirement

---

## What remains open

| Item | Why it matters |
|---|---|
| **SBF sbf_obs concat fix** | Highest-ROI single fix: 6.3× slowdown, CPU-saturated, code location known (`processor.py:2744`) |
| Production server RAM/cores unknown | Determines whether S2 suffices or S3 is needed |
| 1s resolution not yet benchmarked | 30 GB footprint is extrapolated, not measured |
| Icechunk write contention not profiled | Could cap S3's real gain below projections |
| SP3/CLK only cached for 7 DOYs in Sample_data | Limits SBF/15-min benchmarks; expand cache or add `--sp3-dir` override |
| Worker process overhead not profiled | macOS spawn adds ~2–3 GB base per worker; Linux fork does not |
| Linux benchmark not run | macOS projections rely on fork/COW assumptions — validate on production server |

---

## Recommendation

**Priority 1 — Fix SBF sbf_obs concat** (high impact, code location known):
In `processor.py:2744`, replace the accumulate-all-parts-then-concat pattern with
incremental per-part writes to Icechunk. Expected to drop SBF from 276s/DOY to ~50-80s/DOY.

**Priority 2 — S2 in production + SNR-only config** (structural, no downside):
S2 loky/flat is already implemented on `explore/performance-review`. Merge it and set
`keep_rnx_vars: [SNR]` + 277-SID curated list in production `processing.yaml`. This
unlocks more workers within the RAM budget and eliminates the 95% spawn-overhead waste
from the current S0 strategy.

**Priority 3 — Linux benchmark** (validate extrapolations):
All macOS projections about fork/COW and lazy padding rely on OS-level assumptions not
measurable here. Run S2 on the actual production server to get real numbers before
committing to S3 architecture.

---

## VOD store overhead (2026-07-05, 28-DOY run)

**Measured:** pure RINEX pipeline 548s → RINEX + VOD 842s → **+294s for 28 days (~10.5s/day)**.
Actual VOD computation is 0.2s/day. The ~10s/day overhead comes from I/O:

| Step | Estimated cost | Root cause |
|---|---|---|
| `read_receiver_data` from RINEX Icechunk store × 2 receivers | ~4s/day | Data already in memory (`date_datasets`) — redundant re-read |
| VOD Icechunk `write_or_append_group` + `session.commit()` | ~4s/day | 28 × commit overhead on ExFAT external drive |
| `_normalize_encodings` eager string coord cast | ~2s/day | New from StringDType fix; computes all string coords before write |

**Primary fix — eliminate the re-read (highest ROI):**
`pipeline.py` stores `date_datasets[date_key][receiver_name]` after the RINEX write. The
VOD computer currently calls `read_receiver_data` to re-open the same data from Icechunk.
Instead, pass `date_datasets` directly to the VOD computation path, skipping the store
read entirely. Expected saving: ~8s/day (4s × 2 receivers) → ~224s total.

**Secondary fix — batch VOD commits:**
Instead of one Icechunk commit per day (28 commits), accumulate VOD data across days and
commit every N days or at run end. Trades crash-recovery granularity for throughput.
Expected saving: ~2-3s/day depending on drive speed.

**Tertiary fix — lazy `_normalize_encodings` for string coords:**
The StringDType fix forces eager `.compute().values` for all non-numeric coords. For a 277-SID
dataset these arrays are tiny (<100 KB), but the overhead is still measurable. Consider
only casting when `dtype.kind not in ('O',)` and skipping already-numpy-object coords
(the fast path already does this for `da.chunks is None and da.dtype == object`).

**Action:** profile the exact per-step breakdown before implementing — use
`time.perf_counter()` around each sub-step in `vod_computer._write_to_store()` and
`pipeline._run_vod_for_day()` (or equivalent entry point).
