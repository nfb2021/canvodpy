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
| 28-DOY benchmark not yet run | 6-DOY with SNR-only + 277-SID now measured; 28-DOY would confirm at scale |
| Production server RAM/cores unknown | Determines whether S2 suffices or S3 is needed |
| 1s resolution not yet benchmarked | 30 GB footprint is extrapolated, not measured |
| Icechunk write contention not profiled | Could cap S3's real gain below projections |
| AIUB not in products.toml | Ephemeris download fails without NASA credentials |
| Worker process overhead not profiled | macOS spawn adds ~2–3 GB base per worker; Linux fork does not |

---

## Recommendation

**Immediate:** Adopt S2 in the production orchestrator (structural win, no downside).
Set `keep_rnx_vars: ["SNR"]` in `config/processing.yaml` (already supported) and re-run
the 28-DOY benchmark — this alone is projected to allow 3–4 workers on the development
machine and more on Linux where fork reduces per-worker overhead.
**Next:** Implement lazy padding (defer `pad_to_global_sid` to write boundary via
`reindex(sid=store_axis)`) to bring in-flight footprint to ~100–150 MB, then S3 if 1s
resolution files are confirmed as a production requirement.
