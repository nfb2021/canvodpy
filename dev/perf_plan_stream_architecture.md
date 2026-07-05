# Performance Plan — Stream Architecture for Mixed File Sizes

**Date:** 2026-07-03 (revised). Companion to `dev/perf_plan_phase2_framework.md` (loky
pool, `ParallelismConfig`), `dev/perf_audit.md` (§7 deep-dive), `dev/perf_strategy.md`,
and `dev/perf_web_research_streams.md` (web research this revision incorporates — see §8).
**Planning + measurement only — no code changed.** New measurements in §2.2 were
taken on this machine (macOS arm64, Python 3.14) with a scratch script against real
test files; everything else cites the audit or verified code.

**Question answered here:** given that a 24 h SBF file occupies one worker for
minutes while 96 × 15-min RINEX files flow through in seconds each, how many
"streams" (differently-tuned submission/processing configurations) should the
pipeline expose, and how does a file find its stream?

**Answer in one line:** **one physical stream** (one pool, one bounded window, one
sequential writer) with **auto-detected task-shaping profiles** per
(format × duration class), plus **exactly one user-overridable `custom` profile
block** — streams are task shapes, not scheduling entities. Details in §4–5.

**Revision summary (2026-07-03):** default chunk count for split files is now
**K = 2N** (not K = N), exposed as `split_chunks_multiplier: int = 2` on
`StreamProfile`; the web research's ephemeris-per-chunk concern was **verified
against the code and rejected** (the per-day aux Zarr already sidesteps it, §8.2);
the LPT sort key for chunk tasks is specified as `file_size_bytes / K`; §7 Q2 and
Q6 are reframed per the research. Full change log in §8.

**Second revision (2026-07-03, maintainer constraints locked):**
(1) **no file splitting in the default stream** — every file is touched exactly
once; gfzrnx is a user-facing docs recommendation only, never a canvodpy
dependency or pre-pass; (2) **24 h is the prescribed default data unit**, and
within a site all receivers must deliver the same temporal extent — a
prerequisite, not something canvodpy accommodates silently; (3) **15-min cadence
is served by the custom stream only** — the default stream makes no promises
about it; (4) **backlog = multi-day step** (all files across the full date range
submitted into one pool at once), **daily = single-day step**; (5) **SBF-specific
parallelization work is blocked on the SBF decoder fix** (see §10). §5 and §7 are
updated accordingly; new §9 records the daily-vs-backlog analysis and §10 the
RINEX-vs-SBF resolution. The splitting machinery (K = 2N, index pass, chunk sort
key) is *retained* in this document as the specification of the **opt-in
custom-profile feature** — it is no longer part of any default.

---

## 1. Data characterization (real holdings, measured 2026-07-03)

### 1.1 `canvodpy-perf/packages/canvod-readers/tests/test_data` (worktree)

**Empty.** The directory exists but the git subrepo is uninitialized in the perf
worktree (`total 0`). The initialized copy lives in the main checkout at
`/Users/work/Developer/GNSS/canvodpy/packages/canvod-readers/tests/test_data`
(2.9 GB) and is characterized below — any perf benchmark run from the worktree
must either init the subrepo or point at the main checkout.

| Subdir (`valid/`) | Files | Format | Size range | PERIOD | Notes |
|---|---|---|---|---|---|
| `rinex_v3_04/01_Rosalia` | 192 | RINEX v3.04 obs | 1.41–2.45 MB | `15M` @ `05S` | 96 canopy (~1.4 MB) + 96 reference (~2.2–2.3 MB), day 25001 |
| `sbf/01_Rosalia` | 192 | SBF binary | 11.29–13.71 MB | `15M` @ `05S` | Same day/receivers as above; canopy ~11.3 MB, ref ~13.6 MB |
| `rinex_v2_11/02_Moflux` | 48 | RINEX v2.11 obs | 0.46–0.81 MB | `01H` @ `15S` | Hourly files, 2 days |
| `rinex_v3_05_stripped` | 2 | RINEX v3.05 obs | 29–44 KB | `10S` | Tiny fixtures |
| `rinex_v3_04_nav_data` | 192 | RINEX nav | 9–51 KB | 15M | Broadcast ephemeris companions |
| `nmea/01_Rosalia` | 96 | NMEA text | ~0.52 MB | `15M` | |
| `aux_data` | 2 + zarr | SP3 (2.2 MB), CLK (36.9 MB), aux Zarr | | `01D` | |
| `invalid/` | 36 | corrupted `.25o` fixtures | tiny | | corruption suite |

```
Location: main-checkout test_data (worktree copy EMPTY)
Files found: ~760 GNSS data files (excl. zarr chunks / stores)
Format breakdown: RINEX3 194, RINEX2 48, SBF 192, NMEA 96, nav 192, SP3/CLK 2
Size range: 0.03–13.7 MB
Temporal extent range: 10S / 15M / 01H (no 24 h obs files in test_data)
Typical files-per-day: 96 per receiver (15-min cadence)
```

### 1.2 `/Volumes/ExtremePro/Daily_data` — the 24 h RINEX case

Clean canonical-name layout (`01_reference/`, `02_canopy/`, per-DOY subdirs
25001–25006, plus `01_SP3/`, `02_CLK/`).

| File class | Count | Size | PERIOD/SAMPLING |
|---|---|---|---|
| `ROSR…_01D_05S_AA.rnx` (reference) | 6 | **216.9–220.6 MB** | 24 h @ 5 s, RINEX v3 |
| `ROSA…_01D_05S_AA.rnx` (canopy) | 6 | **141.4–154.2 MB** | 24 h @ 5 s, RINEX v3 |
| `COD0MGXFIN…_ORB.SP3` | 6 | 2.16 MB | 1/day |
| `COD0MGXFIN…_CLK.CLK` | 6 | 36.9–37.3 MB | 1/day |

```
Location: /Volumes/ExtremePro/Daily_data
Files found: 24 data files (+2 helper scripts, 1 stray temp file)
Format breakdown: RINEX3 only (obs), SP3/CLK aux
Size range: 141–221 MB per obs file
Temporal extent: 01D (24 h), 5 s sampling
Typical files-per-day: 1 per receiver per day  → 2 obs tasks/day for the site
```

**No 24 h SBF exists in any surveyed location.** Extrapolating the measured 15-min
SBF (~11.3–13.7 MB @ 5 s with this station's block mix), a 24 h SBF file would be
**~1.1–1.3 GB**, an order of magnitude above the "~100+ MB" working assumption
(the RefGuide's "104 MB/day" figure is MeasEpoch-only at 1 Hz; these files carry
SatVisibility/PVT/DOP blocks too). At 1 Hz the same extrapolation reaches **~6 GB**
(web research, §8). If 24 h SBF becomes real, it is a *gigabyte* problem, not a
100 MB problem — this strengthens, not weakens, the intra-file split conclusion
(§3.4), and at 1 Hz it makes splitting mandatory (§7 Q2).

### 1.3 `/Volumes/ExtremePro/Sample_data` — the 15-min mixed-format case

Same site, days 25001–25007, **legacy RINEX-2-style filenames**
(`ract006l30.25o` = canopy, DOY 006, hour letter `l`, minute 30) but the payloads
are modern. Header inspection:

| Ext | Actual format | Count | Size range | Per receiver-day |
|---|---|---|---|---|
| `.25o` | **RINEX v3.04 obs** | 2 690 | canopy 1.15–1.79 MB (median 1.56); ref 2.02–2.53 MB | 96 |
| `.25_` | **raw SBF binary** | 1 344 | 11.08–12.02 MB | 96 |
| `.251` | NMEA text | 1 344 | ~0.5 MB | 96 |
| `.25p` | RINEX nav (mixed) | 1 344 | 6–42 KB | 96 |
| SP3/CLK | aux | 7+7 | 2.2 / ~37 MB | 1 |

Plus one **stray 24 h file** `02_canopy/25001/ract0010_daily.25o` (151.1 MB) sitting
among the 15-min files — a real-world example of the mixed-duration directory the
stream design must survive (and today's discovery would feed it into the same pool
as the 96 sub-files; dedup Layer 3 is what protects the store, audit §7.11).

```
Location: /Volumes/ExtremePro/Sample_data
Files found: 6 739
Format breakdown: RINEX3 obs 2 690 (+1 daily), SBF 1 344, NMEA 1 344, nav 1 344, SP3 7, CLK 7
Size range: 6 KB – 12 MB (one 151 MB outlier)
Temporal extent: 15M @ 05S (one 01D outlier)
Typical files-per-day: 96 obs + 96 SBF per receiver per day
```

### 1.4 The three workload shapes the architecture must serve

| Workload | Tasks/receiver-day | Single-task wall (measured/extrapolated, §2.2) | Day's parallelizable work |
|---|---|---|---|
| 15-min RINEX | 96 × 0.4 s | 0.39 s measured | ~37 s CPU → seconds wall on 8 cores |
| 15-min SBF | 96 × 3.7 s | 3.69 s measured | ~6 min CPU → ~45 s wall on 8 cores |
| 24 h RINEX | **1** × ~25–40 s | extrapolated (linear in epochs, §2.2) | 1 task — pool of N>2 mostly idle |
| 24 h SBF (hypothetical) | **1** × ~6 min | extrapolated | 1 task — worst straggler |

The polar opposition is **duration class**, not format: 96-task days want inter-file
parallelism and backpressure; 1-task days want intra-file parallelism (or a decode
that is fast enough not to need it).

---

## 2. Reader differences and scaling (Step 2)

### 2.1 Where the CPU goes (verified code, audit §7.3/7.8/7.9)

- **RINEX v3** (`packages/canvod-readers/src/canvod/readers/rinex/v3_04.py`):
  pure-Python string slicing. Hot loop = `iter_epochs` (:1128) →
  `process_satellite_data` (:1065, 16-char slice walk per satellite line) →
  `parse_observation_slice` (:968, three fallback parse methods, `list()`/`pop()`
  char manipulation per observation) → one Pydantic `Observation` per value
  (:1106–1112). ~100 % GIL-held. **CPU-bound Python, not I/O-bound** — threads
  would serialize it; processes required (audit §7.3 verdict stands).
- **SBF** (`packages/canvod-readers/src/canvod/readers/sbf/reader.py`): Cython
  `sbf-parser` builds nested Python dicts per block; canvod decode re-walks them —
  `_decode_epoch` (:2286–2299) → `_decode_type1`/`_decode_type2` with per-observation
  pint Quantities and a Pydantic `SbfSignalObs` instantiation each (~10–30 µs per
  signal-observation, audit §7.9). Plus a second full parse (`_freq_nr_cache`
  pre-scan) and a full-file read for `file_hash`. >90 % GIL-held.
- Both readers **pad to the global 3 658-SID universe** before returning
  (audit §7.2) — the returned dataset size is dominated by padding, not data,
  until Phase-1 Task B (ragged SIDs) lands.

### 2.2 Measured single-file timings (new, this session)

Scratch run against the real Rosalia test files (warm imports, single process):

| Measurement | Value |
|---|---|
| `import canvod.readers` | 1.11 s (subset of the 3.05 s full worker import, audit §7.4) |
| 15-min RINEX v3, 2.34 MB, 180 epochs @ 5 s | **0.39 s** `to_ds_and_auxiliary` → returned ds 16.0 MB (padded) |
| 15-min SBF, 13.66 MB, 180 epochs @ 5 s | **3.69 s** → returned ds 39.7 MB + aux (sbf_obs) 27.2 MB |

Derived:

- **Per-epoch cost** (same 180 epochs, same site): RINEX ≈ **2.2 ms/epoch**,
  SBF ≈ **20.5 ms/epoch** — a **~9.5× constant factor**, same shape. Both scale
  linearly in epochs (per-epoch loops, no super-linear structures; RINEX
  additionally linear in declared obs-types × satellites, SBF in tracked signals).
  Bytes are a proxy for epochs×signals within one station, so "linear in bytes"
  holds per (station, format) with different constants; across formats bytes are
  not comparable (SBF ~3.7 MB/s vs RINEX ~6 MB/s effective parse rate here).
- **Memory expansion ratio** (input file → returned padded datasets):
  RINEX 2.34 → 16.0 MB (**6.8×**); SBF 13.66 → 66.9 MB incl. sbf_obs (**4.9×**).
  Ratio is roughly constant per format across durations *because both numerator and
  denominator are linear in epochs* — a 24 h RINEX reference file would return
  ~16 MB × 96 ≈ **1.5 GB** padded (consistent with the audit §7.2 table; 155 MB
  unpadded after Task B).
- **Extrapolated 24 h single-task wall**: RINEX ref ≈ 0.39 s × 96 ≈ **~37 s**
  (canopy ~25 s); SBF ≈ 3.69 s × 96 ≈ **~6 min**. These are the straggler sizes
  the 1-task-per-day workload pins on one worker.
- Note the sample SBF is **5 s sampling** (180 epochs/15 min), not the 1 Hz the
  audit's size table assumed — the audit's "900 epochs / 82 MB per 15-min SBF" row
  is a 1 Hz upper bound, not what this station produces. Production sampling rate
  is an open question (§7 Q1).

### 2.3 Intra-file parallelism feasibility

| Format | Splittable? | What it takes |
|---|---|---|
| RINEX v3 | Yes, moderately. File is read into a line list; epoch records are `>`-delimited batches (`get_epoch_record_batches`). Split = parse header once, partition epoch-record line ranges across workers, each builds a partial array block. No library dependency. The web research confirms this is the well-trodden FASTA chunking pattern (byte offset → scan forward to next `>` line; workers stateless after alignment) — low complexity. | New reader surface (`epoch_range=` / line-range variant), driver-side reassembly. Not currently exposed. *(Superseded 2026-07-03: gfzrnx pre-splitting was considered as a Phase-1 stopgap but is rejected as canvodpy machinery — it survives only as a user-facing docs recommendation; splitting itself is custom-profile-only, §5/§7 Q6.)* |
| SBF | Yes, by design of the container: stream self-synchronizes on `$@` + CRC-16 from any byte offset (parser.pyx:183; graphify-confirmed "NOT randomly seekable **without** a pre-scan"). Correctness trap: mid-file workers need carried stream state (last `DeltaLS`, SVID→FreqNr) → index pass mandatory. | Audit §7.6: index pass + `byte_range=`/`initial_state=` params, **150–300 LOC in canvod-readers, zero sbf-parser changes**; the index pass can *replace* the existing `_freq_nr_cache` full second parse (net win even unsplit). |

**When it pays:** only for the 1-task-per-day class. For 15-min files (≤4 s tasks,
96/day) inter-file parallelism already saturates any realistic pool and split
overhead (index pass + N× aux-Zarr opens + reassembly) would exceed the win.

### 2.4 The 96×15-min vs 1×24 h equivalence (Step 2, Q4)

Same data, very different execution profile:

| Aspect | 96 × 15-min | 1 × 24 h |
|---|---|---|
| Submission overhead | 96 × ~0.2 ms dispatch + 96 result pickles | 1 × each |
| Worker utilization (N=8) | ~100 % until the tail; wall ≈ total/8 | 1/N busy; wall = full parse |
| Per-file fixed costs (aux Zarr open+load, `file_hash`, header parse, reader-object setup) | paid 96× | paid once |
| Result granularity | 96 × 16 MB pickles (RINEX, padded) | 1 × ~1.5 GB pickle (blocker pre-Task-B) |
| Failure blast radius | one 15-min file | the whole day |

Measured/estimated per-file overhead for a warm pool (dispatch 0.2 ms + 16 MB
result pickle ~30 ms round trip + aux open/slice, order 10²ms total) is **≤ ~10 %**
of even the cheapest real task (0.39 s RINEX). So 96 small files are *not*
meaningfully penalized versus one big file on a warm pool — the per-file overhead
story only becomes dominant with the **cold per-receiver-day pool** (3–6 s spawn,
audit §7.7), which Phase 2 already eliminates. Conclusion: **the 15-min workload
needs no special stream; it needs the warm pool + bounded window that Phase 2 already
prescribes.** The 24 h workload is the one the current design cannot serve.

**Ephemeris note (verified for this revision, §8.2):** neither profile pays for
ephemeris *computation* — workers never interpolate SP3. The driver builds the
per-day aux Zarr once (`_ensure_aux_data_preprocessed`, processor.py:1137, invoked
from `prepare_batch_tasks` at :2435 before any task descriptor exists); each worker
opens it by path and loads only its epoch slice (processor.py:242–249). The
"aux Zarr open + slice" line in the tables above is a *read*, not an interpolation.

---

## 3. Overhead breakdown per class (Step 3)

Numbers: measured (M) from §2.2/audit §7.4, estimated (E) otherwise.

| Cost | 15-min RINEX | 15-min SBF | 24 h RINEX | 24 h SBF (hyp.) |
|---|---|---|---|---|
| Pool dispatch (warm) | 0.2 ms (M) | 0.2 ms (M) | 0.2 ms | 0.2 ms |
| Worker cold import (amortized, long-lived pool) | ~0 | ~0 | ~0 | ~0 |
| File open + header/prescan | ~10 ms (E) | ~2 full extra passes exist today (freq-cache + hash) — part of the 3.69 s (M) | ~1 s (E) | minutes (the double-parse scales too) |
| Per-epoch decode | 0.39 s total (M) | 3.69 s total (M) | ~25–37 s (E) | ~6 min (E) |
| Aux Zarr open + slice load | ~50–150 ms (E) | ~50–150 ms (E) | larger slice, ~1 s (E) | ~1 s (E) |
| Result pickle (padded, pre-Task-B) | 16 MB ≈ 30 ms (M rate 1.1 GB/s) | 67 MB ≈ 120 ms | ~1.5 GB ≈ 3 s + 3× RSS | ~6 GB — **blocker** |
| **Per-file overhead / total** | **≲ 10 %** | **≲ 3 %** | ≲ 5 % | ≲ 2 % |

**Crossover:** per-epoch work dominates per-file overhead for *every* real file in
the surveyed holdings once the pool is warm — even the smallest (0.46 MB hourly
RINEX v2). There is no file class where per-file overhead justifies batching
multiple files into one task, and no file class where splitting is needed for
*overhead* reasons. Splitting is justified purely by the **utilization ceiling**
(1 task/day) and, pre-Task-B, by **result size** (temp-Zarr return path).
For 15-min files specifically: intra-file parallelism is strictly worse than
inter-file parallelism (96 independent tasks already exist; splitting adds fixed
costs and reassembly for zero utilization gain).

**Chunked-task overhead (for the split case, K = 2N):** each chunk repeats the
aux Zarr open + its slice load and produces its own result pickle. Aggregate extra
cost of K=16 chunks vs one whole-file task ≈ (K−1) × Zarr open (~50–150 ms each)
≈ **1–2 s total** — against a 37 s (24 h RINEX) or ~6 min (24 h SBF) task. The
slice *bytes* read are the same in total (K disjoint slices = one full-day slice).
Well above the ~10–50 ms task floor the research confirms (§8.1); no "chunks too
small" risk at K=16, N=8.

---

## 4. Stream architecture options (Step 4)

Evaluation criteria fixed by the task: mixed-site handling, misconfiguration
behaviour, interaction with the single sequential Icechunk writer, compatibility
with the Phase-2 bounded window (`perf_plan_phase2_framework.md` §4.4).

### Option A — two streams: default (24 h) + custom (15-min)

- Mixed site (15-min canopy + 24 h reference — a plausible real deployment):
  both streams active simultaneously against **one** worker budget and **one**
  writer. Either the streams are separate pools (fragments capacity; loky's
  reusable executor is a process-global singleton, so two differently-parameterized
  pools would tear each other down on alternation — Phase-2 §4.2) or they share a
  pool, in which case "stream" degenerates to "per-file settings" and the
  two-stream framing adds nothing.
- Misconfiguration: the custom stream owns real scheduling knobs; a user who sets
  concurrency high on 15-min SBF days can OOM the shared machine. Wrong tuning =
  slow *or* dead.
- Duration is the wrong axis to make the *user-facing* boundary: the user's own
  data (§1.3) mixes durations in one directory (the stray daily file).
- Verdict: **rejected** — the boundary is real but does not need to be a stream.

### Option B — 2×2: {default,custom} × {RINEX,SBF}

- The format axis buys nothing at the pool level: both formats are >80–90 %
  GIL-held CPU-bound Python (audit §7.3), both need process workers, both scale
  linearly in epochs with only a ~9.5× constant between them. The earlier
  "RINEX could use threads" idea is dead. What differs per format is
  *task shaping* (SBF: index-pass/split, sbf_obs aux payload; RINEX: nothing
  special) — not executor tuning.
- Four config surfaces to misconfigure; the mixed site now spans up to all four
  streams in one day against one writer.
- Verdict: **rejected** — format is a per-task property (`reader_format` already
  travels with each task, processor.py:157), not a stream.

### Option C — one auto-tuned default stream + one fully custom stream

- Closest to right. Auto-detection by size/duration for the common case, one
  escape hatch. Two flaws as stated: (1) if the custom stream is a genuinely
  *separate* stream, all Option-A objections about capacity fragmentation and the
  loky singleton apply; (2) "user sets all parameters" re-opens the pool-level
  misconfiguration hole.
- Verdict: **adopt the shape, fix the semantics** → Option D.

### Option D (recommended) — one physical stream, profile-shaped tasks

**There is exactly one stream** in the scheduling sense: one long-lived loky pool
(Phase-2 §4.2/4.3), one bounded submission window (§4.4), one sequential
writer/session per receiver-day (audit §7.10). What varies per file class is the
**task shape**, resolved per file at `prepare_batch_tasks` time
(processor.py:2376) from a small set of **profiles**:

- a profile decides: split or not (and chunk granularity, default K = 2 ×
  resolved workers — §5.3), result return path (pickle vs temp-Zarr), submission
  priority;
- profiles are keyed by (format, duration class) — both already known *before
  parsing* from the naming convention PERIOD field and the reader format the
  receiver config declares; file size is the fallback for non-canonical names
  (Sample_data's legacy names carry duration in the hour-letter scheme, and size
  discriminates unambiguously: 15-min ≤ ~15 MB, daily ≥ ~100 MB);
- **defaults ship in code** for the four (format × {sub-daily, daily}) cells —
  this is the "prescribed, optimized for the common case" stream;
- **one `custom` profile block in config** overrides matched files — this is the
  user-tweakable stream, but constrained to *shaping* parameters. Pool-level
  facts (worker count, memory fraction, mode) remain global on
  `ParallelismConfig` and are never per-stream.

Evaluation against the criteria:

- **Mixed site**: trivially handled — one task list, per-file profiles. A day of
  96 canopy 15-min + 1 reference 24 h becomes 96 small tasks + 1 daily task
  (or, *only under a custom profile with splitting enabled*, K chunk tasks,
  K = 16 at N=8), sorted size-descending into one window;
  wall ≈ max(daily_chunks, small_total/N) instead of being pinned to the unsplit
  daily parse. The stray daily file in a 15-min directory (§1.3) gets the daily
  profile automatically by size even under legacy naming.
- **Misconfiguration**: bounded blast radius by construction. The worst a bad
  `custom` block can do is split too finely (more fixed cost per chunk) or force
  pickling of a large result (slow, pre-Task-B memory-heavy) — degraded, not
  wrong, and never a second pool or an unbounded window. Validators clamp
  (`split_threshold_mb > 0`, `chunk_target_epochs >= 900`,
  `split_chunks_multiplier >= 1`, etc.).
- **Single sequential writer**: unchanged and unthreatened — profiles change the
  *task list*, never the write side. Chunked results of one file are epoch-disjoint
  by construction and append through the same session; the filename-ordered release
  buffer planned for streaming (audit §7.10) needs only a sub-key
  (filename, chunk_index).
- **Bounded window (Phase 2)**: profiles compose with it — the window counts
  in-flight *tasks*; a split daily file simply contributes K entries. Size-descending
  submission (Phase-2 change 4) already orders chunks first.

---

## 5. Recommendation (Step 5)

**Option D. One stream. Profiles, not streams, absorb the heterogeneity.**

1. **How many streams?** One physical stream: one loky pool + one bounded window +
   one sequential writer. Two *logical* tiers: built-in default profiles
   (prescribed) and a single optional `custom` profile (user-tuned). No
   per-format streams, no per-duration streams.

2. **What routes a file?** Auto-detection, in precedence order:
   (a) `custom` profile match (explicit glob / receiver / format / period matcher
   in config); (b) naming-convention PERIOD field (`15M`/`01H` → sub-daily,
   `01D` → daily) — computable without parsing, same source the discovery-time
   Layer-3 dedup will use (audit §7.11), so the two features share one
   filename-interval pass; (c) file-size fallback for non-canonical names
   (threshold ~50 MB, coinciding with `large_file_threshold_mb`). Format comes
   from the receiver's declared `reader_format` as today.

   **Prescription (2026-07-03):** the default stream *prescribes* `01D` — within
   a site, all receivers must deliver the same temporal extent (24 h). This is a
   documented prerequisite enforced at pre-flight (naming-convention check), not
   something the router accommodates silently. Sub-daily cadences (15-min, hourly)
   are the domain of the `custom` profile: users operating there tune it
   themselves and the default stream makes no promises about it. The routing
   machinery above still exists — it feeds discovery-time dedup and the custom
   matcher — but in the default stream its job is *validation* (flag the stray
   sub-daily file), not accommodation.

3. **Tunable per profile** (shaping only). **Splitting is not part of the
   default stream** (constraint locked 2026-07-03): every file is touched
   exactly once by default. All **four built-in profile cells ship
   `split_threshold_mb = None`** — the split machinery below is reachable
   only through the `custom` profile, opt-in, by users who understand their
   cadence (e.g. 15-min operators):
   - `split_threshold_mb: float | None` — `None` = never split. **Default
     `None` for all built-in cells (daily and sub-daily, both formats).**
     Only a `custom` profile may set a value; the daily-SBF straggler is
     addressed by the decoder fix (§10), not by default-stream splitting.
   - `chunk_target_epochs: int | None` — **explicit** split granularity. If set,
     it wins over the multiplier below (explicit granularity beats relative).
   - `split_chunks_multiplier: int = 2` — **relative** split granularity:
     `K = split_chunks_multiplier × resolved_max_workers`, computed by the
     profile resolver at `prepare_batch_tasks` time (that is the first moment
     both the profile and the resolved global worker count are in hand).
     Default 2 per the K = 2N finding (§8.1): K = N leaves one worker idle behind
     any chunk that runs long (one 20 %-slower chunk = tail straggler); K = 2N
     lets loky's queue-level stealing backfill finished workers. At N=8 → K=16:
     24 h RINEX ≈ **2.3 s/chunk**, 24 h SBF ≈ **22 s/chunk** — both far above the
     ~50 ms task-overhead floor the research confirms. K = 4N remains a
     reasonable custom value for files with non-uniform epoch density.
   - `return_path: Literal["pickle", "temp-zarr", "auto"]` — `auto` = temp-Zarr
     above `large_file_threshold_mb` (Phase-3 mechanism, perf_strategy.md)
   - `priority: int` — submission ordering weight (default: size-descending
     already covers it; the knob exists for "reference first" style needs)
   Global-only (NOT per profile): `max_workers`, `mode`, `memory_fraction`,
   `worker_idle_timeout_s`, executor selection.

   **Chunk-count resolution logic** (normative): if `chunk_target_epochs` is set
   → K = ceil(file_epochs / chunk_target_epochs); else K =
   `split_chunks_multiplier × resolved_max_workers`; K is clamped to ≥ 1, and a
   file is only split at all when its size exceeds `split_threshold_mb`.

4. **Mapping to the existing pool design**: `_parallel_process_rinex_pool`
   (processor.py:1409) is untouched at the pool level — it receives a task list
   and drains it (post-Phase-2: through the bounded window §4.4). Profile
   resolution lives entirely in `prepare_batch_tasks` (processor.py:2376): resolve
   profile per file → emit 1 task (whole file) or K tasks (byte-range/epoch-range
   chunks + shared `initial_state` from the index pass) → sort size-descending.
   The worker function grows optional `byte_range=`/`initial_state=` passthrough
   args to the reader (audit §7.6 surface); `preprocess_with_hermite_aux`
   (processor.py:80) otherwise unchanged. Chunk reassembly = none needed on the
   driver: chunks are epoch-disjoint appends, same as files.

   **LPT sort key** (normative — today `prepare_batch_tasks` emits descriptors in
   discovery order with *no* sort; the sort is Phase-2 change 4 and is specified
   here precisely): the sort key is **estimated size in bytes**, available
   pre-parse from the filesystem (`Path.stat().st_size`) — never epochs, which
   are unknown without parsing. Whole-file task → `st_size`; chunk task from a
   split file → **`st_size / K`** (chunks are epoch-uniform partitions, and both
   readers are linear in epochs ∝ bytes within one file, §2.2). Sort the *entire*
   mixed task list descending on this one key. Worked example (mixed day at N=8,
   *assuming a custom profile with splitting enabled* — in the default stream
   the daily file is one 217 MB task, which sorts first by the same key):
   a 217 MB daily RINEX splits into K=16 chunks of estimated 13.6 MB each — these
   sort ahead of all 96 × 1.4–2.4 MB 15-min RINEX files, filling all workers
   first, exactly the LPT-desired order. Caveat (accepted): bytes are a
   *per-format* duration proxy (SBF ~3.7 MB/s vs RINEX ~6 MB/s, §2.2), so a
   15-min SBF file (13.7 MB, 3.69 s) sorts adjacent to a daily-RINEX chunk
   (13.6 MB, ~2.3 s); by duration the SBF file should indeed go first, and byte
   order happens to place them together — within LPT's heuristic tolerance
   (≤ 4/3 − 1/(3m) × OPT, tightening toward ~1.22× as K = 2N shrinks task-size
   variance, §8.3). A per-format byte-rate weight is a possible later refinement,
   not required now.

   **Ephemeris and chunks** (verified, §8.2): all K chunk tasks receive the *same*
   `aux_zarr_path` the whole-file task would receive — the per-day aux Zarr is
   already built by the driver before any task descriptor exists
   (`_ensure_aux_data_preprocessed`, processor.py:1137, called from
   `prepare_batch_tasks` at :2435). Each chunk loads only its epoch slice
   (processor.py:242–249). **No `ephemeris_ref` field, Manager dict, or initarg
   is needed** — the path *is* the shared read-only reference. One SBF footnote:
   in broadcast-geometry mode (`use_sbf_geometry`) chunk tasks derive theta/phi
   from SatVisibility blocks in their own byte range, so the index pass's
   `initial_state` must carry the last-seen SatVisibility context along with
   `DeltaLS`/FreqNr (§2.3) — an index-pass detail, not a profile field.

5. **`ParallelismConfig` shape change** (extends Phase-2 §3.2 model):

   ```python
   class StreamProfile(BaseModel):
       """Task-shaping for one (format × duration) class. Never pool-level knobs.

       Split fields (split_threshold_mb / chunk_target_epochs /
       split_chunks_multiplier) are consumed ONLY via the custom profile:
       all four built-in cells ship split_threshold_mb=None — no splitting
       in the default stream (2026-07-03 constraint).
       """
       match_format: Literal["rinex2", "rinex3", "sbf", "*"] = "*"
       match_period: Literal["sub-daily", "daily", "*"] = "*"
       match_glob: str | None = None          # custom-profile targeting
       split_threshold_mb: float | None = None
       chunk_target_epochs: int | None = None  # explicit granularity — wins if set
       split_chunks_multiplier: int = 2        # K = this × resolved_max_workers
       return_path: Literal["pickle", "temp-zarr", "auto"] = "auto"
       priority: int = 0

   class ParallelismConfig(BaseModel):
       ...  # Phase-2 fields unchanged: mode, max_workers, memory_fraction,
            # large_file_threshold_mb, worker_idle_timeout_s, executor, ...
       custom_profile: StreamProfile | None = None   # THE user stream

       def profile_for(self, fmt: str, period_class: str, size_mb: float) -> StreamProfile:
           # custom (if matches) > built-in (fmt, period) cell > catch-all default
           ...
   ```

   Built-in defaults live in code (a 4-entry table), not YAML — users see one
   optional `parallelism.custom_profile:` block, which is the entire "Stream 2"
   config surface. `large_file_threshold_mb` stays on the top level and doubles
   as the size-fallback router and the `return_path="auto"` threshold, so the
   Phase-2 field is not churned.

**Sequencing / cost-benefit honesty:** the audit's #1 lever is still the SBF
decode fix (10–50×, §7.13-1) and #2 is ragged SIDs — and the decode fix is now
a **hard prerequisite for SBF backlog processing** (§10.2), not merely the
bigger lever. With splitting removed from the default stream, the sequencing
simplifies: the profile table + PERIOD routing land in Phase 2.5 (small,
enables discovery-time dedup too); the split machinery (SBF index pass, RINEX
epoch-range API, K = 2N chunking as specified in §2.3/§5.3/§8.1) is built
**only if and when a custom-profile user needs it**, sequenced after the
decode and ragged-SID wins — it is a documented opt-in feature spec, not a
roadmap item. `gfzrnx` is a **user-facing documentation recommendation only**
(operators who want pre-split daily RINEX can run it themselves before
pointing canvodpy at the output); it is never a canvodpy dependency, pre-pass,
or invoked tool.

---

## 6. Impact on the Phase 2 plan (`dev/perf_plan_phase2_framework.md`)

Confirmations (no change): one global pool (§4.2) — this document's Option
analysis independently re-derives it, and the web research independently confirms
it (§8.3); bounded window (§4.4) unchanged and confirmed as the standard
semaphore idiom; size-descending sort (change 4) unchanged, becomes the default
`priority` implementation, and is now theoretically grounded (LPT, §8.3); loky
decision unaffected (its queue-level work-stealing is exactly what makes K = 2N
chunks backfill idle workers, §8.1).

Changes/additions:

1. **§3.2 `ParallelismConfig`**: add `custom_profile: StreamProfile | None = None`
   and the `StreamProfile` model + `profile_for()` resolver to
   `parallelism.py` (~40 extra lines). **`StreamProfile` now carries
   `split_chunks_multiplier: int = 2`** (K = 2 × resolved workers by default;
   `chunk_target_epochs` wins when both are set — resolution logic in §5.3).
   Keep it inert in Phase 2 (only the `priority`/sort path consumes it); document
   that `large_file_threshold_mb` is consumed by `return_path="auto"` in Phase 3.
   This avoids a second config migration when splitting lands.
2. **Change 4 (bounded window)**: task list may contain chunk tasks later —
   phrase the window in "tasks", not "files" (already true in the sketch; make
   it explicit in tests).
3. **Change 4 (sort key, normative)**: the LPT sort key is bytes from
   `Path.stat().st_size`; **chunk tasks from a split file carry estimated size
   `st_size / K`** and sort on the same key as whole files (§5.4). Today
   `prepare_batch_tasks` performs no sort at all — the sort is new Phase-2 code,
   and it must be written against the (path, estimated_size_bytes) pair so chunk
   tasks slot in without a second code path.
4. **`prepare_batch_tasks` (processor.py:2376)** becomes the single profile
   resolution point — note this in change 4's HOW so the Phase-3 split lands as
   a task-list transform, not a new dispatch path.
5. **Ephemeris: no new mechanism.** The web research proposed pre-computing
   ephemeris and sharing it via a Manager dict / initarg before chunk submission;
   verification against the code shows canvodpy already does the equivalent —
   per-day aux Zarr built once in the driver, workers load epoch slices by path
   (§8.2). **Rejected as a StreamProfile field; nothing to add to Phase 2.**
   Record the rationale in `guides/parallelism.md` so it is not re-proposed.
6. **§7 open questions**: add Q9–Q12 below.
7. **Docs follow-up (change 7)**: the future `guides/parallelism.md` should
   document the one-stream + custom-profile model, explicitly *not* a
   two-pool story — including the K = 2N default and the aux-Zarr-slice pattern.
8. **Benchmark fixture gap**: the perf worktree cannot run reader benchmarks —
   `packages/canvod-readers/tests/test_data` is uninitialized there (§1.1).
   Phase-2 integration tests that need real files must init the subrepo in the
   worktree or parameterize the data root.

---

## 7. Former open questions — resolution status (2026-07-03, maintainer constraints locked)

All six questions from the previous revision are now resolved by maintainer
decision or prescription. Recorded here so they are not re-asked.

1. **Production SBF sampling rate — RESOLVED: 1 Hz confirmed.** A 24 h
   production SBF file is ~6 GB and ~30 min of decode at today's reader. The
   consequence is *not* "splitting stops being optional" (splitting is out of
   the default stream entirely) — it is that **the SBF decode fix is a hard
   prerequisite for SBF backlog processing** (§10.2).
2. **Do 24 h SBF files loom? — RESOLVED by prescription.** 24 h is now the
   *prescribed default data unit* for all receivers in a site (§5.2), so the
   24 h SBF case is the expected production shape, not a hypothetical. The
   answer to it is the decode fix (§10), not default-stream splitting; the
   SBF index-pass/split work (§2.3) survives only as the opt-in custom-profile
   feature spec and is sequenced after the decode fix, if ever.
3. **Mixed temporal extents within a site — RESOLVED: not accommodated.**
   Within a site, all receivers must deliver the same temporal extent (24 h in
   the default stream). This is a documented prerequisite enforced at
   pre-flight; a 15-min canopy + 24 h reference site is a configuration error
   in the default stream, and a custom-stream concern otherwise. `match_glob`
   stays on `StreamProfile` for custom targeting.
4. **The stray `ract0010_daily.25o` — RESOLVED in treatment.** Whatever its
   origin, the default stream's response is *validation*, not accommodation:
   the pre-flight naming/extent check flags it, and discovery-time Layer-3
   dedup (audit §7.11) protects the store regardless.
5. **Custom-profile scope — RESOLVED: shaping-only stands.** Worker counts,
   mode, and memory settings remain global on `ParallelismConfig`; the custom
   profile carries only task-shaping fields. 15-min operators tune the custom
   profile themselves; the default stream makes no promises at that cadence.
6. **RINEX intra-file split — RESOLVED: not in the default stream, not a
   canvodpy pre-pass.** The epoch-range reader API remains a *possible* future
   custom-profile implementation detail (feasibility confirmed, §2.3/§8.3) but
   is not scheduled; the ~37 s daily-RINEX straggler is accepted (latency is
   irrelevant in daily mode, §9.2, and in backlog the writer is the ceiling
   anyway, §9.4). **gfzrnx is a user-facing docs recommendation only** —
   operators may pre-split their own files with it before ingest, but canvodpy
   never depends on it, invokes it, or special-cases its output.

---

## 8. Web research integration (what changed vs the original, and why)

This revision incorporates `dev/perf_web_research_streams.md` (Sonnet, 2026-07-03),
which surveyed straggler handling, file-splitting patterns, LPT scheduling, and
chunk-granularity guidance. The research proposed **two changes** to the original
plan; one is accepted, one was verified against the codebase and rejected. Nothing
in the research challenges the core one-stream + profiles architecture.

### 8.1 Accepted: K = 2N default chunk count (`split_chunks_multiplier`)

The original plan left chunk count implicit (chunk granularity via
`chunk_target_epochs` ≈ 1 h, which for a 24 h file happens to yield K ≈ 24 — fine —
but the natural fallback instinct of "one chunk per worker", K = N, was never ruled
out). The research rules it out explicitly: with K = N, one chunk running 20 %
slower than the median leaves one worker idle at the tail with nothing to steal;
the empirical optimum across Dask/Spark partition-sizing guidance is **K = 2N to
4N**, because loky's queue-level work-stealing (pending-task stealing, not
preemption — a running 6-min parse cannot be rescued) then backfills workers that
finish early.

Concretely at N = 8, K = 16: 24 h RINEX → ~2.3 s/chunk, 24 h SBF → ~22 s/chunk —
both comfortably above the ~10–50 ms floor below which IPC/pickle overhead makes
process pools counterproductive. Even at N = 32 (K = 64), RINEX chunks are ~0.6 s,
still an order of magnitude above the floor.

**Change made:** `split_chunks_multiplier: int = 2` added to `StreamProfile` (§5.3,
§5.5); resolver computes `K = multiplier × resolved_max_workers` at
`prepare_batch_tasks` time; `chunk_target_epochs`, when set, wins (explicit beats
relative). Validator clamps multiplier ≥ 1.

### 8.2 Rejected after verification: per-chunk ephemeris pre-computation

The research flagged that if each of K chunks "independently triggers SP3
interpolation, K = 16 chunks means 16× the interpolation cost", and proposed an
`ephemeris_ref` profile field plus a Manager-dict/initarg sharing mechanism. That
concern assumes an architecture canvodpy does not have. Verified against the code
(graphify's graph covers canvod-readers only, so the orchestrator was checked by
direct line inspection):

- **Interpolation runs once per day, in the driver, before any task exists.**
  `prepare_batch_tasks` (processor.py:2376) calls
  `_ensure_aux_data_preprocessed` (:2435 → definition :1137) as its STEP-1, which
  runs the Hermite interpolation over SP3/CLK and writes `aux_{date}.zarr` to
  disk (rebuilt fresh each run — cheap by design, per the in-code comment). Only
  *after* that does the task-descriptor loop start; every descriptor carries the
  same `aux_zarr_path` (a `Path`, :2535). The sequential pipeline path does the
  same (:2644).
- **Workers never interpolate — they slice-read.** `preprocess_with_hermite_aux`
  (processor.py:80) opens the store by path and selects only its epochs
  (:242–249): `xr.open_zarr(aux_zarr_path, …)` →
  `.sel(epoch=ds.epoch, method="nearest")` → `.load()`. A chunk task with 1/K of
  the epochs loads 1/K of the slice. There is no per-worker SP3 parse, no
  full-store load, no interpolation call anywhere in the worker path.
- **Cost accounting:** K chunks vs 1 whole-file task changes the aux cost by
  (K−1) extra Zarr opens (~50–150 ms each, §3) while total slice bytes stay
  constant — ≈ 1–2 s aggregate at K = 16 against a 37 s / ~6 min task (§3).
  Immaterial.

**Conclusion: the aux Zarr *is* the "pre-computed ephemeris shared by reference"
the research asked for** — a path to a read-only on-disk store, which is strictly
better than a Manager dict (no proxy round-trips, no pickling, OS page cache
shared across workers). No `ephemeris_ref` field, no `ephemeris_pre_compute`
flag, no initarg mechanism is added. This paragraph exists to prevent the concern
from being re-raised: any future reviewer who worries about K× interpolation
should read processor.py:1137/:2435 (driver-side, once per day) and :242–249
(worker-side slice load) first. Two genuine residuals, both already tracked
elsewhere: (a) in broadcast-geometry SBF mode the aux Zarr is skipped and chunk
tasks take geometry from SatVisibility blocks in their own byte range — the SBF
index pass must therefore carry SatVisibility context in `initial_state` (§2.3,
§5.4 footnote); (b) the always-rebuild of the aux Zarr is a per-*day* cost
unrelated to chunking (it does not multiply with K) and stays on the general perf
backlog.

### 8.3 Confirmed by the research (no change needed)

- **One pool, not multiple** (research Q4): multiple pools are justified only when
  pipeline *stages* differ in parallelism archetype; all canvodpy tasks are
  GIL-held CPU-bound Python feeding one sequential writer. Independently
  re-derives §4's Option-A/B rejections.
- **Bounded semaphore window** (research Q1): confirmed as the standard idiom
  (`bounded_pool_executor`, `futureproof`); it prevents queue bloat but does not
  fix stragglers — pre-splitting does. Matches Phase-2 §4.4 exactly.
- **LPT size-descending submission** (research Q3): Graham's bound
  makespan ≤ (4/3 − 1/(3m)) × OPT (≈ 1.29× at m = 8), and with K = 2N chunks the
  effective bound improves toward ~1.22× because chunking shrinks task-size
  variance. Python pools have no native priority queue, so submission *order* is
  the priority mechanism — which is what the plan already prescribed. This
  revision makes the sort key normative (§5.4): bytes from `st_size`; chunk tasks
  = `st_size / K`; one key, one sorted mixed list. (Verified: no sort exists in
  `prepare_batch_tasks` today — the sort is new Phase-2 code, not a modification.)
- **Pre-submission splitting mirrors Spark AQE** (research Q4): split decisions at
  the stage boundary, never mid-task — architecturally identical to profiles
  resolving at `prepare_batch_tasks` time.
- **Speculative execution rejected** (research synthesis): incompatible with the
  sequential Icechunk writer; pre-splitting strictly superior here. No change —
  the plan never proposed it; recorded so it isn't proposed later.
- **RINEX split feasibility** (research Q2): the FASTA byte-offset pattern
  confirms §2.3's assessment and upgrades §7 Q6's recommendation from "defer"
  to "worth building, sequenced after the decode/ragged-SID wins", with
  **gfzrnx as a zero-code Phase-1 pre-splitting alternative**.
- **SBF split feasibility** (research Q2): index pre-scan over `$@`/CRC boundaries
  confirms audit §7.6's design; scan cost (<~5 s est. for 24 h) is acceptable and
  the pass replaces the existing `_freq_nr_cache` second parse (net win).

### 8.4 What the research got wrong about canvodpy (for the record)

Two research statements needed correction against the actual code, both benign:

1. "If the ephemeris is pre-computed and serialized… the overhead per chunk is a
   dict lookup" — canvodpy pre-computes to a *Zarr store*, not an in-memory
   object; the per-chunk overhead is a store open + slice read, and the sharing
   mechanism (a path) already exists (§8.2).
2. Research Q1 computed chunk sizes assuming K = N = 8 ("if split into K=8, each
   chunk ≈ 3–4.6 s") before its own Q5 corrected the default to K = 2N; this
   document uses the corrected K = 2N numbers throughout (2.3 s RINEX / 22 s SBF
   chunks at N = 8).

---

## 9. Daily vs backlog treatment (Question A, resolved 2026-07-03)

Scenario definitions (locked constraints): **daily** = single-day step —
1–2 files per receiver per day; even a live 100-antenna network yields only
~200 tasks/day, arriving together once a day; latency is irrelevant because
the next data physically cannot arrive until tomorrow. **backlog** =
multi-day step — all files across the full requested date range submitted
into the one pool at once (e.g. 3 y × 4 stations × 2 receivers ≈ 8 760
files); maximum throughput; typically a dedicated machine or off-hours.

### 9.1 Is max_workers resolution the only difference? (Q-A.1)

Almost — and deliberately so. The two modes share every architectural
element: one loky pool, one bounded window (2N tasks), one sequential
writer, LPT byte-descending sort, the same profile table. Exactly two things
differ, both driver-side policy, neither a mechanism:

1. **Worker-count resolution**: `backlog` = all cores; `daily` =
   `max(1, cores // 2)` (headroom on shared machines). A constant, not a
   code path.
2. **Step extent**: `daily` prepares and submits one day's task list per
   invocation; `backlog` prepares task descriptors across the *whole* date
   range and flat-submits them into the same pool (the shape the flat
   multi-day Dask path already proves, pipeline.py:825–830). The only
   per-day serial work remaining in backlog is the driver-side aux-Zarr
   build (one Hermite interpolation per date, §8.2) — a cheap pre-step
   pipelined ahead of submission, not a scheduling entity. No per-day
   batching, no file splitting (constraints 1 and 4).

Nothing else forks: no daily-specific scheduling, no backlog-specific pool
type, no second code path beyond "how many dates does `prepare_batch_tasks`
cover".

### 9.2 Daily mode, 200 tasks, N = 8 (Q-A.2)

Already optimal — boringly so. 200 × ~37 s (24 h RINEX) ≈ 2 h CPU → ~15–16
min wall at N = 8 plus the serial write tail; a 2-antenna site is seconds of
scheduling around two ~37 s tasks. The bounded window provides the memory
cap; the LPT sort is near-inert (tasks are near-uniform in size) and
harmless. Because daily mode has **no latency target to miss**, no
daily-specific optimization can ever pay for itself; the only meaningful
knob is the worker cap, which is precisely what `mode` sets. Anything beyond
that is over-engineering. Answer: yes, N = 8 with the 2N window is already
optimal for the 200-task day.

### 9.3 Backlog bounded-window size — 2N stands (Q-A.3)

2N remains correct at 8 760 tasks. The window's job is to bound **driver
memory** (in-flight submitted-but-uncollected results), not to feed the
pool: any window ≥ N + refill-latency keeps all workers busy, and refill
latency (~0.2 ms dispatch against multi-second tasks) is negligible. A
larger window (4N, 100, …) adds *zero* throughput and linearly more
driver-resident result datasets — post-Task-B up to ~155 MB each, so 16 in
flight is already ~2.5 GB worst-case. The memory argument for keeping the
window small is in fact **stronger** in backlog, where the task iterator
never runs dry and the window is pinned full for hours. If the window is
ever tuned, it should be tuned *downward* for memory-heavy profiles, never
upward for "throughput".

### 9.4 The sequential writer is the backlog asymptote (Q-A.4)

Yes — the writer becomes a bottleneck in backlog in a way daily never
notices. Writes are strictly serial (one Icechunk session/commit per
receiver-day, audit §7.10); parsing scales with N. The writer binds when
per-receiver-day parse work divided by N drops below per-receiver-day write
cost. At N = 8 with 24 h RINEX (~37 s parse), parsing contributes only
~4.6 s per receiver-day — if a commit + append + metadata-table write costs
more than that on local FS (plausible), **backlog RINEX wall time is
dominated by the 730-commit write chain, not the pool**, and the "≈56 min"
figure in §10.2 is a parse-only lower bound. Pre-decode-fix SBF never
notices (a ~30 min parse swamps any write); post-fix SBF (~3 min → ~22 s of
parse per receiver-day at N = 8) re-enters the same regime as RINEX.
Consequences: (a) measure per-receiver-day write cost early in Phase-2
benchmarking; (b) the Phase-3 streaming writer (overlap day *d*'s write with
day *d+1*'s parses — already planned, audit §7.10) is a
**backlog-throughput feature**, not just a memory feature; (c) no pool-level
change follows — one sequential writer stays (constraint 6); the remedy is
overlap, never write parallelism. Daily mode is indifferent: two commits per
day, latency irrelevant.

### 9.5 Recommendation: optimize for backlog; daily is the capped default (Q-A.5)

Yes — deprioritize `daily` architecturally. Every piece of default-stream
machinery (warm pool, bounded window, LPT sort, profiles, and later the
streaming writer) is designed against the **backlog** workload, the only one
with a real throughput requirement. `daily` is the same machinery applied to
a small task list with a politer worker cap — it cannot be architecturally
"wrong" because it has no latency target. Therefore `mode` means **step
extent** (single-day vs multi-day submission) with the `max_workers`
resolution as a *consequence* of that intent — not two tuning universes.
Mirrored in the Phase-2 plan §3.2 (revised semantics).

---

## 10. RINEX vs SBF resolution (Question B, resolved 2026-07-03)

### 10.1 SBF is a decoder problem, not a parallelization problem (Q-B.1)

Confirmed. At the scheduling level the pool treats RINEX and SBF
identically (constraint 7): both are >80–90 % GIL-held CPU-bound Python
process tasks (§4 Option-B rejection, audit §7.3); what differs is the
duration constant (~9.5× per epoch, §2.2 — at the confirmed 1 Hz production
rate, ~30 min per 24 h file). The audit's #1 lever (§7.9: vectorized decode
— drop the per-observation Pydantic `SbfSignalObs` + 2–4 pint Quantities,
accumulate raw integer columns per epoch, apply scaling once with numpy;
10–50×) turns a 24 h 1 Hz SBF task from ~30 min into ~0.5–3 min — the same
order as a 24 h RINEX task (~37 s). **After the fix, the parallelization
architecture needs zero SBF-specific accommodation**: same pool, same
window, same LPT byte sort, same profile machinery, no default-stream
splitting (removed anyway, §5). The SBF-specific items that remain live
*inside the reader*, not in the scheduler: the sbf_obs aux payload size, and
the `file_hash` full read / `_freq_nr_cache` second parse (both of which the
decode-fix work should eliminate, audit §7.6/§7.9).

### 10.2 Wall-time arithmetic — confirmed — and the hard-prerequisite verdict (Q-B.2)

One year, one station, 2 receivers = 730 daily files, N = 8:

| Workload | Per-file wall | Backlog wall (parse only) |
|---|---|---|
| SBF 1 Hz, no decode fix | ~30 min | 730 ÷ 8 × 30 min ≈ **45–46 h** ✓ |
| SBF 1 Hz, with decode fix (÷10) | ~3 min | ≈ **4.5 h** ✓ |
| 24 h RINEX | ~37 s | ≈ **56 min** ✓ — parse-only; the serial write chain may dominate (§9.4) |

At the 3 y × 4-station scale (8 760 files), no-fix SBF is ≈ **23 days** of
wall time. No worker count or scheduling refinement touches a 10–50×
constant. Two pre-fix aggravations compound it: (a) per-worker transient RSS
on a 24 h SBF decode is multi-GB (audit §7.5: >10 GB pre-Task-B), so 8
concurrent decodes likely **OOM before wall time even matters**; (b) LPT
front-loads exactly those N worst tasks simultaneously at t = 0 (§10.3).
**Verdict: the SBF decode fix is a hard prerequisite for SBF backlog
processing.** Further SBF-specific parallelization planning (index pass,
splitting, per-format tuning) is deferred until the decoder lands; user
documentation must state plainly that pre-fix SBF backlog runs are
unsupported/inadvisable.

### 10.3 Mixed-format backlog scheduling — LPT handles it; the residual is memory, not makespan (Q-B.3)

Size-descending submission puts every SBF file ahead of every RINEX file
(GB-scale vs ~150–220 MB — the per-format byte-rate skew noted in §5.4 is
irrelevant at this size gap). That is exactly the LPT-desired order: long
tasks cannot land at the tail, the tail backfills with ~37 s RINEX tasks,
and the makespan excess is bounded by Graham's 4/3 and in practice by
fractions of one RINEX task. The one genuine residual is **memory
co-scheduling**: LPT starts the N largest decodes simultaneously at t = 0,
so peak aggregate RSS lands at the front of the run (pre-fix/pre-Task-B:
N × multi-GB → OOM risk, §10.2). The guard is the memory-based worker cap
(`resolved_max_workers(est_worker_peak_gb=…)`, Phase-2 §3.2) — **not** the
sort order; do not "fix" it by interleaving formats, which would only
reintroduce tail stragglers. Post-decode-fix and post-Task-B this residual
fades to irrelevance.

### 10.4 15-min SBF (custom stream) — confirmed, no concern (Q-B.4)

96 × 3.69 s ≈ 5.9 min CPU per receiver-day → ~44 s wall at N = 8. Inter-file
parallelism saturates the pool (§2.4); nothing further needed. The custom
stream owns this cadence; the default stream makes no promises about it.

### 10.5 Order of work: framework first, then decoder — with one honest caveat (Q-B.5)

The recommended order stands: **(1) ship the Phase-2 parallelization
framework** (warm pool, bounded window, LPT sort) — it benefits RINEX
immediately and is entirely decoder-agnostic; **(2) fix the SBF decoder** —
SBF then benefits automatically through the same framework with zero
framework rework (§10.1). The steelman against this order: for an
SBF-dominant operator the decoder is a 10–50× lever versus the framework's
≤ N× (≤ 8× here), so decoder-first maximizes total compute saved; and a
pre-fix SBF backlog attempt on the new framework will disappoint (45 h) or
OOM. Counters: the two changes are independent workstreams in different
packages (canvodpy orchestrator vs canvod-readers) and can proceed in
parallel; the framework is the smaller, lower-risk change and unblocks
Phase 3; and the pre-fix failure mode is prevented by documentation (the
§10.2 verdict), not by sequencing. The caveat to carry into release notes:
**do not present Phase 2 as "SBF is now fast"** — SBF throughput is gated on
the decoder fix, full stop (mirrored in Phase-2 plan §1).
