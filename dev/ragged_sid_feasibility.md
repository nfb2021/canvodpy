# Ragged SID Axis Feasibility — W7 & W9 Investigation

**Phase 0 investigation, 2026-07-02.** Follow-up to `docs/findings/perf_audit.md` §7
(SID padding: ~7.9 GB padded vs ~155 MB unpadded for a 24 h SBF file, ~40×).
Code review only — no changes implemented. All paths relative to the repo root
(`canvodpy-perf` worktree) unless noted.

---

## W7 — Is `keep_sids` always set in production configs?

**Answer: No. The out-of-the-box default is "no filter", and two of the three
config modes silently resolve to "no filter". The 40× padding is real in default
deployments.**

### Default value

- `SidsConfig` (`packages/canvod-utils/src/canvod/utils/config/models.py:901-957`):
  `mode: Literal["all", "preset", "custom"] = "all"`. `get_sids()` returns
  **`None` when `mode == "all"`** → no filter → full 3,658-SID universe.
- The shipped default config sets `mode: all`
  (`packages/canvod-utils/src/canvod/utils/config/defaults/sids.yaml:6`), and the
  user-facing template does too (`config/sids.yaml.example:26`).
- **`mode: preset` is a silent no-op.** `_get_preset_sids()` is a TODO returning
  `[]` (`models.py:959-969`), and `pad_to_global_sid` treats an empty list as
  no-filter (`packages/canvod-auxiliary/src/canvod/auxiliary/preprocessing.py:230`:
  `if keep_sids is not None and len(keep_sids) > 0`). So `preset` ≡ `all` today.
- Only `mode: custom` with a non-empty `custom_sids` list actually filters.

### Plumbing

- `RinexDataProcessor.__init__` reads `self.keep_sids = config.sids.get_sids()`
  (`canvodpy/src/canvodpy/orchestrator/processor.py:613`) and passes it into
  `preprocess_with_hermite_aux` (`processor.py:86, 161, 443-449, 518-525`).
- Airflow-style tasks do the same: `keep_sids = config.sids.get_sids()`
  (`canvodpy/src/canvodpy/workflows/tasks.py:683, 829, 1000`).
- There is **no fallback logic** that sets a default filter anywhere; `None`
  flows straight to `pad_to_global_sid`.
- The L1 convenience API (`canvodpy.read()`) does not plumb `keep_sids` at all —
  readers pad to the full universe unconditionally there.

### Where the filter is applied (important nuance)

The filter is applied **inside** `pad_to_global_sid` *before* the `reindex`
(`preprocessing.py:229-243`): the universe list is intersected with `keep_sids`
first, then `ds.reindex(sid=sids)` materializes directly at the filtered size.
So when `keep_sids` **is** set, the 7.9 GB array is **never created** — the
multiplier is `len(keep_sids)/n_observed`, not 3,658/n_observed.

### Realistic values

- No active `config/sids.yaml` exists in either checkout (only `.example` /
  `.bak`). The main repo has `config/sids.yaml.bak` with `mode: custom` and a
  **321-SID list** (93 BeiDou, 90 GPS, 87 Galileo, 44 GLONASS, 4 SBAS, 3 IRNSS) —
  matching the "321-SID universe" used throughout the audit work.
- With that config the multiplier for a file observing ~87 SIDs is ~3.7×
  (321/87) instead of ~42× (3,658/87).
- Test fixtures (`canvodpy/tests/test_dask_serialization.py:31`) use small lists
  (`["G01", "G02", "G03"]`) but also explicitly test `keep_sids=None` as a
  supported production case.

### Practical implication

The padding concern is **not moot**:

1. The default (`all`) and the broken `preset` mode both produce the full
   3,658-SID universe.
2. Even the realistic custom config (321 SIDs) keeps a ~3.7× memory multiplier
   and stores mostly-NaN rows for never-co-observed SIDs.
3. The cheapest mitigation available **today** with zero code changes is a
   proper `mode: custom` list — this removes ~91% of the padded axis before any
   array is materialized. Implementing the `preset` TODO would make this the
   easy path for all users.

---

## W9 — Ragged SID axis: layer-by-layer audit

Hypothesis: readers return observed SIDs only; VOD aligns canopy/reference with
`xr.align(join="inner")`.

### 0. Where padding happens today

- `pad_to_global_sid` lives in
  `packages/canvod-auxiliary/src/canvod/auxiliary/preprocessing.py:177-244`.
  Universe = Σ over constellations of `SYSTEM_BANDS[sys] × svs × BAND_CODES[band]`
  (lines 199-218). Its docstring states the load-bearing purpose: *"Ensures
  consistent sid dimension for appending to Icechunk."*
- `aggregate_glonass_fdma=True` (default everywhere) collapses GLONASS FDMA
  per-frequency-channel bands into aggregate G1/G2 bands via
  `GLONASS(aggregate_fdma=...)` and the `SignalIDMapper` — it **reduces** the
  universe to the 3,658 figure; `False` would enlarge it.
- Callers:
  - Readers (all behind a **`pad_global_sid=True` kwarg that already exists**):
    `rinex/v3_04.py:1811,1831`, `rinex/v2_11.py:1315,1332`,
    `rinex/v3_05_stripped.py:226,240`, `sbf/reader.py:1210,1605,1891`
    (in `packages/canvod-readers/src/canvod/readers/`).
  - Aux pipeline: `prep_aux_ds` (`preprocessing.py:472`) pads the interpolated
    SP3/CLK zarr the same way (`packages/canvod-auxiliary/src/canvod/auxiliary/pipeline.py:158`).

So a ragged mode already has an off-switch at the reader level; the question is
what downstream breaks.

### 1. SNR store writes (`canvod-store`) — **BREAKS**

This is the one genuinely load-bearing layer.

- All append paths use `to_icechunk(ds, session, group=..., append_dim="epoch")`:
  - `MyIcechunkStore.append_to_group` — `packages/canvod-store/src/canvod/store/store.py:1337`
  - `write_or_append_group` — `store.py:1439`
  - `overwrite_file_in_group` — `store.py:963`
  - `append_metadata_datasets` (sbf_obs parts) — `store.py:1124`
  - Orchestrator batch path `_append_to_icechunk` — `processor.py:1941-1968`
    (the default production path, called at `processor.py:2347, 2783`)
  - Fallback worker `worker_task_append_only` — `processor.py:494-500`
- Zarr/xarray append along `epoch` requires all non-append dims to have
  **identical size**. (epoch=900, sid=87) then (epoch=900, sid=94) → hard error.
- Worse: when sizes happen to be **equal but the SID sets differ**, xarray does
  **not** validate coordinate values on non-append dims — data is placed
  positionally → **silent row misalignment**. The global padded universe (fixed
  sorted list) is precisely what makes appends safe today. Ragged appends
  without a reindex step are not just unsupported, they are silently corrupting.

**Region write path** (`worker_task_with_region_auto`, `processor.py:505-538`,
and `append_rinex_ds_to_store`, `processor.py:411-426`):

- `DistributedRinexDataProcessor._cooperative_distributed_writing`
  (`processor.py:3042-3093`) pre-allocates a skeleton: it collects **all epochs
  from all files** in a first pass (3061-3074), then builds `empty_ds` from the
  *first file's* structure expanded to the full epoch axis (3089-3092) and
  commits it. Workers then write with `region="auto"`.
- Under padding, "first file's sid axis" == global universe, so every worker's
  sid axis matches the skeleton exactly and `region="auto"` resolves sid to the
  full dim. Under ragged SIDs: (a) the skeleton would carry only the first
  file's SIDs, and (b) each worker's observed SIDs form a **non-contiguous
  subset** of any union axis — `region="auto"` cannot express scattered rows.
  Verdict: breaks; fix is to compute the **union of SIDs** in the existing
  pre-scan pass and have each worker `reindex` its output to that union before
  the region write (cheap: reindex to a few hundred SIDs, not 3,658).

### 2. SNR store reads (`canvod-store`) — **compatible**

- `read_group` (`store.py:510-567`) opens the group with
  `chunks = {"epoch": 34560, "sid": -1}` — a chunking spec, not a shape
  assumption; `sid: -1` works for any size.
- `read_group_deduplicated` (`store.py:569-665`) filters only along `epoch`
  using the metadata table (hash + time ranges; SID-agnostic).
- The store returns the **single fixed sid axis established at group creation**
  (Zarr has one coordinate array; epoch-appends never change it). There is no
  "union of SIDs ever written" semantics and no per-epoch-range narrowing — nor
  could there be with one Zarr group. A ragged design therefore has to decide
  the axis **per group** (see go/no-go).
- No positional SID indexing anywhere: `grep -rn "isel(sid"` over `packages/`
  and `canvodpy/src/` → zero hits. No hardcoded 3658 anywhere.
- `reader.py` (`parsed_rinex_data_gen*`) has no `sel(sid=...)`/`isel(sid=...)`
  either.

### 3. SNR-based analysis — **compatible, one minor guard needed**

- `manager.py`: no positional SID access; `prepare_vod_input_data`
  (`manager.py:484-534`) just reads both receiver groups and returns them.
- `packages/canvod-grids/src/canvod/grids/aggregation.py:81-87, 236-238` selects
  SIDs by **label**: `vod.sel(sid=sid)`. Under padding, any configured SID
  always exists (as NaN); under ragged, a configured-but-unobserved SID raises
  `KeyError`. Needs an intersection guard or `reindex` (one-line change, two
  sites).
- No `ds.sid.values` length or fixed-entry comparisons found outside tests.

### 4. VOD computation (`canvod-vod`) — **already ragged-native**

- `VODCalculator.from_datasets` calls
  `xr.align(canopy_ds, sky_ds, join="inner")`
  (`packages/canvod-vod/src/canvod/vod/calculator.py:141-145`) — literally the
  hypothesized mechanism, already in place.
- `GnssResearchSite.calculate_vod` does the same alignment
  (`packages/canvod-store/src/canvod/store/manager.py:578-580`) before passing
  `align=False`.
- `get_delta_snr` (`calculator.py:154-162`) is a plain xarray subtraction —
  xarray's default arithmetic join is `inner`, so even unaligned inputs reduce
  to co-observed SIDs.
- **No `pad_to_global_sid` call in the VOD layer, no `.fillna`** anywhere in
  `calculator.py`. SIDs seen by only one receiver are today NaN rows that
  produce NaN VOD; under ragged with `join="inner"` they are simply absent.
  Semantically equivalent: every downstream consumer found (gridding,
  sigma-clip, temporal analysis) masks with `isnull()`/`np.isfinite` and never
  counts the sid axis.
- **But**: `store_vod` → `write_or_append_group(append_dim="epoch")`
  (`manager.py:623` → `store.py:1439`) — the **VOD store has the same fixed-sid
  append constraint** as the RINEX store. Inner-join SID sets vary day to day,
  so ragged VOD appends break identically to layer 1.
- `VodComputer` (`canvodpy/src/canvodpy/vod_computer.py:73`) only carries the
  `{"epoch": 34560, "sid": -1}` rechunk spec — size-agnostic.

### 5. Hemispheric gridding (`canvod-grids`) — **compatible**

- Cell assignment writes `cell_id_<grid>(epoch, sid)` from theta/phi arrays with
  whatever shape arrives (`operations.py:164, 228, 323`) — fewer SIDs just means
  fewer points.
- Analysis code derives sid counts from data shape and NaN-guards everything:
  `temporal.py:369, 502, 639` (`sizes.get("sid", 1)` + flatten + `valid` mask),
  `sigma_clip_filter.py:167-199` (`vod_chunk.shape`, `np.isfinite` masks).
- No fixed SID count or list anywhere in `core/`, `analysis/`, `workflows/`.

### 6. Pipeline interior (augmentation) — **already ragged-tolerant**

Notable: the ephemeris augmentation step in `preprocess_with_hermite_aux`
already performs a **label-based inner join** between observations and aux data
(`processor.py:252-272`): `common_sids = rinex_sids ∩ aux_sids`, then
`ds.sel(sid=common_sids)` / `aux_slice.sel(sid=common_sids)` on both, with
scattered `rinex_only` SIDs logged and dropped. `_compute_spherical_coords_fast`
(`processor.py:333-358`) operates positionally only *after* this alignment. A
ragged dataset flows through this stage unchanged — the padding applied by the
reader moments earlier is immediately re-intersected anyway. Evidence from the
SBF side agrees: `sbf_obs` metadata parts already have ragged sid axes and are
merged with `xr.concat` (the known `join='outer'` FutureWarning at
`processor.py:2744`).

---

## Summary table

| Layer | Verdict | Change required for ragged |
|---|---|---|
| Readers (`pad_to_global_sid` call) | trivial | `pad_global_sid=False` kwarg **already exists** at every call site |
| Augmentation (aux join, coords) | compatible | none — already label-based inner join (`processor.py:252-272`) |
| SNR store writes (append paths) | **breaks** | reindex each dataset to a stable per-group SID axis before `to_icechunk(append_dim="epoch")`; silent-corruption risk if skipped |
| SNR store writes (region="auto" path) | **breaks** | build union-SID skeleton in existing pre-scan (`processor.py:3055-3093`); workers reindex to it |
| SNR store reads | compatible | none (fixed axis per group is inherent to Zarr; chunk spec `sid: -1` size-agnostic) |
| SNR analysis (`manager`, grids aggregation) | needs 1 guard | intersection guard on `.sel(sid=list)` (`aggregation.py:82-83, 237`) |
| VOD computation | compatible | none — `xr.align(join="inner")` already used; no fillna |
| VOD store writes | **breaks** | same reindex-before-append as SNR store |
| Gridding + per-cell analysis | compatible | none — shape-agnostic, NaN-guarded |
| sbf_obs metadata appends (`store.py:1080-1124`) | breaks (same mechanism) | same reindex, or per-part groups |

---

## Overall verdict: **GO — feasible, moderate refactor, one concentrated choke point**

The pipeline is far more ragged-ready than expected. Compute layers (augmentation,
VOD, gridding, analysis) are already label-based, inner-joining, and NaN-guarded;
readers already have the off-switch. **Exactly one assumption is load-bearing:
"every dataset appended to a Zarr group has the identical fixed sid axis"** — and
it appears in three places that all funnel through the same two functions
(`to_icechunk(append_dim="epoch")` call sites and the region-write skeleton).

The key design realization: **"ragged in the pipeline" and "fixed axis in the
store" are separable.** The 40× cost is paid at *read/process time* (per file,
per worker, ~96 files × 2 receivers a day); the store axis only matters at
*write time* (once per batch). Padding can move from the reader to the write
boundary.

### Minimum change set (recommended shape)

1. **Readers**: default `pad_global_sid=False` in the orchestrator path (kwarg
   exists; zero new code in `canvod-readers`).
2. **Write boundary**: in `_append_to_icechunk` (and `store.append_to_group` /
   `write_or_append_group` as the guardrail), `ds.reindex(sid=store_axis,
   fill_value=np.nan)` immediately before `to_icechunk`. `store_axis` = the
   group's existing sid coordinate (read once per batch), created on first
   write from config (`keep_sids` / implemented preset) or the first batch's
   union. This is ~20 lines and preserves on-disk layout, dedup guardrails, and
   all read paths bit-identically.
3. **Region path**: compute union of SIDs during the existing epoch pre-scan
   (`processor.py:3061-3074`), build the skeleton from it, reindex worker output
   to the union before the region write.
4. **VOD store**: same reindex-before-append (or per-day groups if a truly
   variable axis is ever wanted).
5. **Guards**: intersection guard on `.sel(sid=...)` in
   `grids/aggregation.py:82-83, 237`; same for sbf_obs part appends.
6. **W7 hygiene** (independent, immediate win): implement `_get_preset_sids`
   (currently a silent no-op) and ship a realistic preset so `keep_sids` is
   effectively always set — this alone collapses the multiplier from ~42× to
   ~3.7× with today's code.

### What a *fully* ragged store (no fixed axis at all) would additionally cost

Per-file/per-day groups or Icechunk sid-axis resizing with backfill, plus union
semantics on read — a genuinely large refactor touching store layout, dedup
metadata, and every consumer's read pattern. **Not recommended**; the
pad-at-write design above captures essentially all of the memory win (workers
hold ~155 MB instead of ~7.9 GB) without touching the storage contract.
