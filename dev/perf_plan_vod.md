# Performance Plan — VOD I/O Overhead

**Date:** 2026-07-05. Follow-up to `dev/performance-report.md` §"VOD store overhead"
(28-DOY run: pure RINEX 548 s → RINEX+VOD 842 s, **+294 s ≈ 10.5 s/day**, actual VOD
math 0.2 s/day).

**Planning only — no code was changed.** All file:line references verified against the
`explore/performance-review` worktree (`canvodpy-perf`).

Scope:
- **Task V1** — eliminate the store round-trip: feed VOD from in-memory data.
- **Task V2** — batch VOD Icechunk commits (every N days instead of daily).
- **Task V3** — de-serialize `_normalize_encodings` string-coord computes.

---

## 0. Traced call chain (verified)

```
run.py:332  pipeline.process_range(start, end)
  └─ orchestrator/pipeline.py:1072 process_by_date
     └─ :590 _process_multi_day_batches
        └─ streaming loop :841-937:
           :886  processor._append_to_icechunk(augmented, ...)    ← RINEX write; augmented still in scope
           :910  daily_ds = self.site.read_receiver_data(...)     ← RE-READ #1 (store round-trip)
           :935  date_datasets[date_key][receiver_name] = daily_ds ← lazy, Zarr-backed
        :973  yield (date_key, date_datasets[date_key], timings)
run.py:349  _compute_vod_for_day(datasets, vod_analyses, ...)
  :243  TauOmegaZerothOrder.from_datasets(canopy_ds, ref_ds, align=True)
        → calculator.py:142 xr.align(join="inner"); :179 calculate_vod() — LAZY graph
  :250  vod_ds.chunk({"epoch": 34560, "sid": -1})
  :257  research_site.store_vod_analysis(...)
        └─ manager.py:436 vod_store.write_or_append_group(...)
           :1463 _normalize_encodings(dataset)                   ← sequential per-coord computes (RE-READ #2a)
           :1466-1470 to_icechunk(append_dim="epoch")            ← lazy VOD graph EVALUATED (RE-READ #2b)
                       session.commit()                           ← 1 commit/day on ExFAT
  :263  n_valid = int((~vod_ds["VOD"].isnull()).sum())           ← RE-READ #3: 2nd evaluation of same lazy graph
```

### Key answers from call-chain trace

**Where does VOD path read the RINEX store?** Not in `VodComputer`. In the **orchestrator**:
`pipeline.py:910` → `manager.py:386-389` → `read_group_deduplicated(receiver_name, keep="last")`
(store.py:597). This opens the **full group history** (no time_slice forwarded), loads all
metadata rows, builds one boolean epoch mask per ingested file, then applies `ds.where(...,
drop=True)` for the day. Cost is **O(campaign length)** — the 10.5 s/day average hides a
linear ramp.

**Is `date_datasets` passed to VOD?** Yes (run.py:349), but those datasets **are the
store re-read** (pipeline.py:910) — lazy and Zarr-backed. The original in-memory per-file
datasets (`augmented`, pipeline.py:878) are dropped after the RINEX write.

**Three parallel VOD write paths exist:** `run.py:_compute_vod_for_day`, `VodComputer`,
`api.Pipeline.calculate_vod` (api.py:449-520) — consolidation opportunity noted in V1.

---

## Confirmed root causes

| # | Root cause | Evidence | Est. cost |
|---|---|---|---|
| R1 | Read-back after RINEX write opens **full group history** + per-file masks, day-filter | pipeline.py:902-921 → manager.py:386-398 → store.py:597-693 | ~4 s/day, grows with campaign |
| R2 | Lazy VOD graph evaluated **twice**: once in `to_icechunk`, once for `n_valid` | store.py:1467 + run.py:263; laziness by design calculator.py:182-184 | ~4 s/day |
| R3 | One `session.commit()` per analysis per day on ExFAT | store.py:1470/1479; called from manager.py:436 | ~2-4 s/day |
| R4 | `_normalize_encodings` computes each Dask-backed string coord **sequentially** (~7 coords, 7 scheduler passes) | store.py:247-259; called at :1463 and 6 other write methods | ~2 s/day |

---

## Task V1 — Feed VOD from in-memory data (primary, ~8 s/day)

### V1.1 Design

Replace the store read-back with an in-memory daily concat; fall back to store read
when the write skipped files (resume/overlap runs).

**1. `_append_to_icechunk` returns what it skipped** (`processor.py:1593`):
- Change return type `None` → `set[str]` (skipped file-hashes; empty = everything written)
- `existing_hashes` is already computed internally at :1638 — no new work
- Update callers: pipeline.py:886, `parsed_rinex_data_gen` / `parsed_rinex_data_gen_2_receivers`

**2. In-memory daily dataset in the streaming loop** (pipeline.py:902-935):
```python
skipped = processor._append_to_icechunk(augmented, receiver_name, rinex_files, ...)
if not skipped:
    parts = [ds for _, ds in augmented]
    daily_ds = xr.concat(parts, dim="epoch", join="exact")
    daily_ds = daily_ds.sortby("epoch").drop_duplicates("epoch", keep="last")
    daily_ds = daily_ds.sel(epoch=slice(day_start, day_end))  # parity with time_range filter
else:
    daily_ds = self.site.read_receiver_data(receiver_name, time_range)  # unchanged fallback
```
`join="exact"` is safe while reader-side padding produces identical sid axes (per
`perf_plan_phase1.md` Task B context; when B lands, reindex to group axis instead —
note the dependency in both plans).

**3. `run.py` benefits automatically:** with numpy-backed input, `calculate_vod` runs
eager, `n_valid` (run.py:263) is a cheap in-memory reduction (kills R2 for free), and
`_normalize_encodings` hits numeric/numpy fast paths (kills most of R4 on this path).
Move `n_valid` stat above the store write: stats never trigger I/O even in fallback mode.

**4. Rollback switch:** `ProcessingParams.vod_read_back: bool = False` or orchestrator
arg — one `if` at pipeline.py:902.

**5. Rider: `time_slice` pushdown** (cheap, recommended): forward the day slice into
`read_group(time_slice=...)` (store.py:636-638 already accepts it) to cap O(N) growth
for every remaining caller of `read_receiver_data` (fallback path and `compute_bulk`).

**6. (Optional later):** Collapse three VOD paths onto `VodComputer.compute_day` and
deprecate `api.Pipeline.calculate_vod`'s independent read path.

### V1.2 Parity risks and mitigations

| Risk | Mitigation |
|---|---|
| In-memory concat ≠ store content when files were skipped | Fallback to read-back when `skipped` non-empty |
| Store round-trip normalizes attrs/dtypes that in-memory data lacks | VOD math only touches SNR/theta/phi + alignment — attr differences are inert; `_normalize_encodings` still runs before the VOD write |
| Read-back as implicit write-verification | Keep cheap epoch-count assertion against metadata table instead of full read |
| Transient memory spike from `xr.concat` | Parts coexist in memory today; bounded by one receiver-day (~150 MB at 5 s × 277 SIDs × 4 vars) |

### V1.3 Tests

1. **Parity (load-bearing):** one day in fresh store → compare VOD from in-memory path
   vs store-read path; assert bit-identical `VOD`, `delta_snr`, `phi`, `theta`
   (audit-suite `compare_datasets` EXACT tier).
2. **Skip-fallback:** pre-ingest one file, rerun; assert `skipped` non-empty, fallback taken.
3. **Return contract:** `_append_to_icechunk` returns empty set on clean write, hashes on skip.
4. Existing suite: `uv run pytest packages/canvod-audit/tests/`

**Impact: ~8 s/day (~224 s / 28 d).** Removes R1 entirely and R2 as a side effect.
Also removes the O(N) campaign-length growth.

---

## Task V2 — Batch VOD commits (~2-3 s/day)

### V2.1 Design — driver-side accumulate-and-flush (recommended)

Keep `write_or_append_group` untouched. In `run.py`:

```python
pending_vod: dict[str, list[xr.Dataset]] = defaultdict(list)

# per day, instead of writing immediately:
pending_vod[analysis_name].append(vod_ds)          # in-memory after V1; eager

# flush every N days (configurable) and in finally:
if len(pending_vod[name]) >= vod_commit_every or end_of_run:
    flush = xr.concat(pending_vod[name], dim="epoch")
    research_site.store_vod_analysis(flush, name, commit_message=f"VOD {name} {first_doy}..{last_doy}")
    pending_vod[name].clear()
```

`--vod-commit-every N` flag, default 7 for backfill; cron passes 1.
28 days → 4 commits + 4 `group_exists` + 4 `_normalize_encodings` instead of 28 of each.

Rejected: single long-lived writable session with periodic commits — more invasive;
Icechunk sessions become read-only after commit (see store CLAUDE.md) anyway.

### V2.2 Risks

| Risk | Mitigation |
|---|---|
| Crash loses up to N days of VOD | Recompute via `VodComputer.compute_bulk(start=..., end=...)` — document recovery command; `finally:` handles normal termination |
| Stale VOD during run | Acceptable for batch; cron uses `--vod-commit-every 1` |
| Larger single append → bigger ExFAT transaction | Fewer, fuller chunks — actually helps on ExFAT (fewer small files per chunk boundary) |
| Partial-day duplication on retry | Wrap flush in try/except that does NOT clear buffer on failure |

**Impact: ~2-3 s/day (~56-84 s / 28 d).** 24 of 28 commits disappear.

---

## Task V3 — `_normalize_encodings` batch computes (~1-2 s/day)

### V3.1 Change (store.py:216-274)

Batch all Dask-backed string-coord computes into one scheduler call:

```python
candidates: dict = {}
lazy: dict = {}
for name in list(ds.coords):
    da = ds[name]
    if da.dtype.kind in _NUMERIC_KINDS:
        continue
    if da.chunks is None and da.dtype == object:
        continue
    (lazy if da.chunks is not None else candidates)[name] = da

if lazy:
    try:
        computed = dask.compute(*lazy.values())        # ONE scheduler pass for all coords
        candidates.update(zip(lazy.keys(), computed))
    except Exception:
        # fall back to per-coord loop on failure
        for name, da in lazy.items():
            try:
                candidates[name] = da.compute()
            except Exception:
                pass

# then existing np.array(raw, dtype=object) box-construction per candidate
```

Early exit: `if not candidates and not lazy: return ds` — common case after V1 (numpy inputs).

### V3.2 Tests

- Existing StringDType regression tests must pass unchanged.
- New: dataset with 3 Dask-backed string coords → exactly 1 `dask.compute` call (monkeypatch spy); all output dtypes `object`.

**Impact: ~1-2 s/day standalone; mostly subsumed by V1 on the VOD path. Still pays off
for SBF metadata writes and any other lazy-input caller of the 7 write methods.**

---

## Implementation order

| Step | Task | Why |
|---|---|---|
| 1 | **V3** | Smallest diff, zero behavioral risk, independently shippable |
| 2 | **V1** | The structural win; land with `vod_read_back` escape hatch |
| 3 | **V2** | Driver-side buffering; land after V1 (eager datasets make buffer sizing predictable) |
| 4 | Benchmark | Re-run 28-day run; expected: **842 s → ~575-600 s** (VOD overhead ~1 s/day) |
| 5 | (Optional) | Consolidate three VOD write paths onto `VodComputer` |

## Open questions

1. **V2 flush window default:** 1 (cron-safe) vs 7 (backfill-fast)? Suggest flag default 1;
   backfill invocations in `run.py` pass 7.
2. **V1 + Task B dependency:** when `perf_plan_phase1.md` Task B lands (`pad_global_sid=False`),
   the `join="exact"` concat site must reindex to the group axis instead — note in both plans.
3. **`time_slice` pushdown** (rider on V1): forward day slice into `read_group(time_slice=...)`
   at store.py:636-638 to cap O(N) growth for all `read_receiver_data` callers.
4. **`n_valid` stat location:** move above the write (free after V1; stats never trigger I/O).
