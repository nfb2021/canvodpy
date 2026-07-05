# Performance Plan — Phase 1 (Implementation Plan)

**Date:** 2026-07-02. Follow-up to `docs/findings/ragged_sid_feasibility.md` (Phase 0,
W7 + W9) and `docs/findings/perf_audit.md` §7. **Planning only — no code was changed.**
All file:line references verified against the `explore/performance-review` worktree
(`canvodpy-perf`).

Scope:

- **Task A** — make `SidsConfig.mode: all` authoritative (~321 data-backed SIDs
  instead of 3,658 theoretical ones); drop `mode: preset`.
- **Task B** — stop padding in readers; pad once at the write boundary
  ("ragged in pipeline, fixed axis in store").
- **Task C** — review of `canvod-virtualiconvname` (findings only).
- **Task D** — review of the CLI/config approach (findings only).

---

## Task A — Make `SidsConfig.mode: all` authoritative

### A.0 Current state (verified)

| What | Where |
|---|---|
| `SidsConfig` model | `packages/canvod-utils/src/canvod/utils/config/models.py:901-969` |
| `mode: Literal["all", "preset", "custom"]`, default `"all"` | `models.py:904-907` |
| `preset` field + `validate_preset_when_mode_preset` validator | `models.py:908-942` |
| `get_sids()` — returns `None` for `all`, `_get_preset_sids()` for `preset`, `custom_sids` for `custom` | `models.py:944-957` |
| `_get_preset_sids()` — TODO stub returning `[]` (silent no-op) | `models.py:959-969` |
| Only caller of `_get_preset_sids` is `get_sids()` (verified via grep) | — |
| `get_sids()` call sites | `canvodpy/src/canvodpy/orchestrator/processor.py:613`; `canvodpy/src/canvodpy/workflows/tasks.py:683, 829, 1000` |
| Shipped default `mode: all` | `packages/canvod-utils/src/canvod/utils/config/defaults/sids.yaml`; `config/sids.yaml.example` |
| Config loader for sids | `packages/canvod-utils/src/canvod/utils/config/loader.py:153-162` (`_load_sids`, deep-merge defaults + user file) |
| CLI display of sids config | `packages/canvod-utils/src/canvod/utils/config/cli.py:616` (`_show_sids`) |

### A.1 Canonical source of "valid Band×Code per constellation"

The SID universe is generated today inside `pad_to_global_sid`
(`packages/canvod-auxiliary/src/canvod/auxiliary/preprocessing.py:199-218`) from
two structures that both live in **canvod-readers**:

- `SignalIDMapper.SYSTEM_BANDS` — `packages/canvod-readers/src/canvod/readers/gnss_specs/signals.py:54`,
  populated from the `Bands` registry
  (`packages/canvod-readers/src/canvod/readers/gnss_specs/bands.py:53-80`), which in turn
  combines the per-constellation `BANDS` class attributes.
- Per-constellation `BAND_CODES: ClassVar[dict[str, list[str]]]` in
  `packages/canvod-readers/src/canvod/readers/gnss_specs/constellations.py`:
  `ConstellationBase` declares it at line 48 (`SYSTEM_PREFIX` at line 52);
  concrete tables at GALILEO:132, GPS:198, BEIDOU:272, GLONASS:365 (+
  `AGGR_BAND_CODES` at 394, merged into `BAND_CODES` in `__init__` at 429-450 when
  `aggregate_fdma=True`), SBAS/QZSS/IRNSS in the same file.
- Static PRN lists come from each constellation's `static_svs` (e.g. GPS
  `G01-G32` at constellations.py:221, GALILEO `E01-E36` at 171, BEIDOU `C01-C63`
  at 319, GLONASS `R01-R24` at 423).
- The cross-product formula (preprocessing.py:211-217):
  for each system letter in `SYSTEM_BANDS`, for each band, for each SV in
  `systems[sys].svs`, for each code in `BAND_CODES.get(band, ["X"])` → `"SV|Band|Code"`.

**These constellation tables are RINEX v3.04 spec-derived and are the canonical
source.** No new table is needed.

### A.2 `SatelliteCatalog.active_prns` (verified)

- `packages/canvod-readers/src/canvod/readers/gnss_specs/satellite_catalog.py:508-532`:
  `active_prns(self, constellation: str, on_date: date) -> list[str]` — single-letter
  prefix (`"G"`, `"R"`, `"E"`, `"C"`, `"J"`, `"I"`, `"S"`), returns sorted active PRN
  codes from the SINEX PRN-assignment blocks.
- `SatelliteCatalog.load()` (satellite_catalog.py:251) has a discovery chain ending in
  a bundled SINEX fallback — never fails offline.
- **Already wired to constellations**: `ConstellationBase.update_svs_from_catalog(on_date)`
  (constellations.py:65-96) replaces `self.svs` with `catalog.active_prns(SYSTEM_PREFIX, on_date)`.
  This is the mechanism the new builder should use — no new plumbing into
  constellation classes is required.

### A.3 Layering constraint (critical)

`canvod-readers` **depends on** `canvod-utils`
(`packages/canvod-readers/pyproject.toml:33`); `canvod-utils` has no dependency on
canvod-readers (verified: `packages/canvod-utils/pyproject.toml:12-20`). Therefore
`SidsConfig` (in canvod-utils) **cannot import** `SatelliteCatalog` or the
constellation tables without creating a cycle.

**Recommended design:**

1. **New builder in canvod-readers**, e.g.
   `packages/canvod-readers/src/canvod/readers/gnss_specs/sid_universe.py` with one
   public function, `build_active_sid_universe(on_date, aggregate_glonass_fdma=True) -> list[str]`:
   - Instantiate the seven constellation objects exactly as `pad_to_global_sid`
     does (preprocessing.py:200-208).
   - Call `update_svs_from_catalog(on_date)` on each (constellations.py:65).
   - Run the existing cross-product (preprocessing.py:211-218 logic), sorted.
   - Keep the `BAND_CODES.get(band, ["X"])` fallback for behavioural parity.
2. **Refactor `pad_to_global_sid`** (preprocessing.py:199-218) to import the
   static-universe variant of the same generator from the new module so the
   cross-product exists in exactly one place (a second function or a
   `use_catalog: bool` parameter — static SVs vs catalog SVs).
3. **Resolution point moves to the callers of `get_sids()`** (all in canvodpy,
   which may import canvod-readers freely). Add a small helper in canvodpy —
   suggested location `canvodpy/src/canvodpy/orchestrator/` or `canvodpy/utils/` —
   `resolve_keep_sids(sids_config, on_date) -> list[str]`:
   - `mode == "custom"` → `custom_sids` as-is.
   - `mode == "all"` → `build_active_sid_universe(on_date)`.
   - Replace the four call sites: `processor.py:613`, `tasks.py:683, 829, 1000`.
4. **`SidsConfig.get_sids()` contract change**: after this, `get_sids()` returning
   `None` no longer means "no filter" in the orchestrator path — it means "resolve
   dynamically". Update the docstring at models.py:944-957 accordingly. (Alternative
   considered and rejected: lazy `from canvod.readers ...` import inside
   `get_sids()` — a layering violation that makes canvod-utils silently depend on
   canvod-readers being installed.)

### A.4 The `on_date` question (must be decided before implementation)

Options:

- **(a) Processing date per batch** — the orchestrator knows it
  (`self.matched_data_dirs.yyyydoy`, e.g. processor.py:1814). Scientifically most
  correct (PRN reassignments respected per day). **Danger:** the active-PRN set
  changes over time, so `keep_sids` differs between days → the padded sid axis
  differs between days. With today's reader-side padding this produces
  different-size (or worse, same-size-different-SIDs) appends — exactly the silent
  misalignment failure from Phase 0. **Option (a) is only safe after Task B's
  write-boundary reindex is in place.**
- **(b) Fixed date pinned in config** — new optional field on `SidsConfig`
  (e.g. `catalog_date: date | None`); when unset, fall back to (c). Stable axis,
  reproducible, but slightly stale for long campaigns.
- **(c) `datetime.now(UTC).date()`** — simplest; axis drifts silently across
  reprocessing runs months apart. Not reproducible. Not recommended as the
  primary mechanism.

**Recommendation:** implement `resolve_keep_sids(config, on_date)` with an explicit
`on_date` parameter; the orchestrator passes the processing date (option a);
**sequence Task A after (or together with) Task B**. If A must ship alone, use (b)
with a documented default and a warning when unset.

### A.5 Dropping `mode: preset` (migration)

- `models.py:904`: `Literal["all", "preset", "custom"]` → `Literal["all", "custom"]`.
- Delete the `preset` field (models.py:908-911), the validator (models.py:917-942),
  and `_get_preset_sids` (models.py:959-969).
- Add a `model_validator(mode="before")` that maps incoming `mode: "preset"` to
  `"all"`, drops a stray `preset:` key, and emits a `DeprecationWarning`
  ("mode 'preset' was never implemented; falling back to 'all'"). This keeps old
  YAML configs loading (the loader passes raw dicts at loader.py:162).
- Update `_show_sids` in `cli.py:616` (it renders the preset branch).
- Update `packages/canvod-utils/src/canvod/utils/config/defaults/sids.yaml` and
  `config/sids.yaml.example` comments to document the new `all` semantics
  ("SINEX-active PRNs × RINEX-valid Band/Code, resolved per processing date").

### A.6 Tests

Existing coverage (verified):
`packages/canvod-utils/tests/test_config_models.py:293-323` (`TestSidsConfig`) — four
tests touch `preset` and **will break**; rewrite as: preset-mode input warns and
coerces to `all`; `mode="all"` still returns `None` from `get_sids()` (contract:
resolution happens upstream). `test_config_loader.py:100-185` uses `mode: all`
fixtures — unaffected. `test_config.py` imports `SidsConfig` — check compile only.

New tests:

1. canvod-readers `tests/test_sid_universe.py`: builder returns sorted unique SIDs;
   every SID's prefix letter maps to the right constellation's codes; GLONASS
   aggregate vs non-aggregate toggles universe size; two dates spanning a known
   PRN reassignment (SINEX fixture) give different PRN sets; offline path (bundled
   SINEX) works; size sanity — order 300-400, strictly less than the 3,658 static
   universe.
2. Parity test: static-universe generator refactored out of `pad_to_global_sid`
   produces exactly the same 3,658-SID list as before the refactor (regression
   guard for the extraction).
3. canvodpy: `resolve_keep_sids` returns custom list untouched; `all` mode
   delegates to the builder (monkeypatch the builder, assert `on_date` forwarded).

### A.7 Change list and order

| # | File | Change |
|---|---|---|
| 1 | `canvod-readers .../gnss_specs/sid_universe.py` (new) | builder + static-universe function |
| 2 | `canvod-auxiliary .../preprocessing.py:199-218` | delegate universe generation to #1 |
| 3 | `canvod-utils .../config/models.py:901-969` | drop preset, add before-validator + warning, docstring |
| 4 | `canvodpy` helper `resolve_keep_sids` (new, small) | resolution logic |
| 5 | `processor.py:613`, `tasks.py:683,829,1000` | call #4 with processing date |
| 6 | `cli.py:616`, `defaults/sids.yaml`, `config/sids.yaml.example` | docs/display |
| 7 | tests per A.6 | — |

Order: 1 → 2 (with parity test) → 3 → 4 → 5 → 6/7. Steps 1-2 are independently
shippable and zero-risk.

**Estimated size:** ~150-250 lines changed/added (excluding tests), tests ~150-200.

### A.8 Open questions (Task A)

1. `on_date` policy (A.4) — needs maintainer decision; recommendation: processing
   date, sequenced after Task B.
2. Should `mode: all` also apply to the aux-pipeline padding
   (`prep_aux_ds` → `pad_to_global_sid`, `canvod-auxiliary/pipeline.py:158`)? The
   aux zarr is intersected away at processor.py:252-272 anyway, but a smaller aux
   axis saves interpolation work. Suggest yes, same resolved list.
3. QZSS ("J") is in the `systems` dict at preprocessing.py:207 but the 321-SID
   reference list (config/sids.yaml.bak) contains no J entries — confirm whether
   the SINEX catalog carries QZSS PRNs and whether that's desired.

---

## Task B — Ragged-in-pipeline: pad at the write boundary

### B.0 Design summary

Readers keep `pad_global_sid=True` as their default (L1/L2/L4 unchanged). The
orchestrator opts out (`pad_global_sid=False`), so workers carry ~155 MB instead of
~7.9 GB per 24 h SBF file. Every Zarr/Icechunk **append** then reindexes the ragged
dataset to the target group's existing sid axis; every **group creation** establishes
that axis from the resolved `keep_sids` universe (Task A), guaranteeing the axis is a
superset of anything observed later.

**Load-bearing invariant to preserve** (Phase 0 §1): xarray/Zarr epoch-appends do
not validate non-append-dim coordinate *values* — same-size-different-SIDs corrupts
silently. Therefore the reindex must be structurally unskippable: enforced inside
the write helpers, not left to call-site discipline.

### B.1 Reader call sites (orchestrator path)

Verified call sites that must pass `pad_global_sid=False`:

- `processor.py:158-163` — `rnx.to_ds_and_auxiliary(...)` in
  `preprocess_with_hermite_aux` (the single funnel for **all** worker paths:
  `worker_task` :443, `worker_task_append_only` :483, `worker_task_with_region_auto`
  :518, cooperative pre-scan :3064 and :3077, and the batch path).
- `processor.py:177-181` — canopy-file read in the SBF shared-position branch.
- Probe reads `processor.py:810, 1110, 2278, 3247` (`to_ds(keep_data_vars=[], ...)`)
  — used for structure/attrs discovery; also pass `False` (pure win, no contract
  change; the skeleton construction changes in B.3 anyway).
- Reader signatures already accept it: `rinex/v3_04.py:1810` (kwargs.pop, default
  True), `sbf/reader.py:1026, 1226, 1617` (explicit kwarg, default True),
  `rinex/v2_11.py:1315,1332`, `v3_05_stripped.py:226,240`. **No reader changes.**
- Note: with padding off, `_fill_sid_coords_from_sid_strings`
  (`canvod-auxiliary/preprocessing.py:247`) no longer runs in the reader path; the
  sid-level coord backfill (sv/band/code/system/freq_*) must instead happen at the
  write boundary after reindex (see B.2), otherwise newly padded rows have NaN
  coords — this function is importable and reusable as-is.

### B.2 Write-boundary reindex (batch append path)

**New helper** (suggested: `MyIcechunkStore._reindex_to_group_sid_axis(ds, session, group)`
in `packages/canvod-store/src/canvod/store/store.py`, plus a thin wrapper usable
from processor.py):

- Read the group's existing `sid` coordinate once per batch from the open session
  (zarr group access via `session.store`; cache per `(group, session)` in the batch
  loop — do not re-read per file).
- If the dataset's SIDs ⊆ store axis: `ds.reindex(sid=store_axis, fill_value=np.nan)`
  then `_fill_sid_coords_from_sid_strings`.
- If the dataset has SIDs **not in** the store axis: log a structured warning with
  the dropped SIDs (they are lost — the axis cannot grow; see B.9 Q2) and reindex
  anyway. Never raise mid-batch by default (matches current "log and continue"
  batch semantics at processor.py:1980-1981).

**First write vs append:**

- First write (group creation): build the axis from the **resolved `keep_sids`
  universe** (Task A output), *not* from the first file's observed SIDs. This makes
  the axis a stable superset from day one and eliminates the "first file was
  GPS-only" trap. Insertion point: the `case (False, _) if receiver_name not in groups`
  branch at `processor.py:1927-1932` — reindex `ds_clean` to the universe before the
  initial `to_icechunk`.
- Appends: reindex to the group's stored axis before `to_icechunk(..., append_dim="epoch")`
  at `processor.py:1941-1946, 1952-1957, 1963-1968`.

**Store-level guardrail** (defence in depth, protects non-orchestrator callers):

- `append_to_group` — `store.py`, `to_icechunk` at :1337. Callers found:
  `canvod-store/reader.py:418, 428`, tests, and a docstring example in
  `canvod-auxiliary/augmentation.py:690`.
- `write_or_append_group` — `store.py:1368-1455`, `to_icechunk` append at :1439,
  create at :1448. Callers: `manager.py:348` (rinex store), `manager.py:436` (vod store).
- Both methods: when the group exists and `append_dim` is used, reindex to the
  group axis inside the method. On group creation, use the incoming dataset's axis
  (these public APIs don't know the config universe; callers that do — the
  orchestrator — create groups with the universe axis themselves).
- `append_metadata_datasets` (sbf_obs parts) — `store.py:1124`: same mechanism
  applies; sbf_obs parts are already ragged today and merged via `xr.concat` in the
  orchestrator (processor.py:2744). Reindex-before-append here too, or leave
  per-part groups as-is if that path writes whole replacements (verify `mode="w"`
  semantics at implementation time).

### B.3 Region="auto" path (cooperative distributed writing)

`DistributedRinexDataProcessor._cooperative_distributed_writing`
(`processor.py:3042-3093+`):

- Pre-scan loop at :3061-3074 already calls `preprocess_with_hermite_aux` per file
  and collects `all_epochs`. Extend it to also accumulate
  `union_sids |= set(ds.sid.values)`.
- Skeleton at :3089-3092 (`first_ds.isel(epoch=[]).expand_dims(...)`): after
  building from `first_ds`, reindex the skeleton to
  `sorted(union_sids)` — or better, to the resolved universe (consistent with B.2's
  first-write rule) — before `to_icechunk(empty_ds, ..., mode="w")` at :3092.
- Workers (`worker_task_with_region_auto`, :505-538): reindex `ds_clean` to the
  skeleton axis before `to_zarr(..., region="auto")` at :530-536. The axis must be
  passed to the worker (new parameter) or read from the store inside the worker;
  passing it is cheaper and deterministic. `region="auto"` cannot express scattered
  row subsets, so full-axis reindex per worker is mandatory here.
- Note (pre-existing, out of scope but worth recording): the pre-scan **fully
  processes every file twice** (once for epochs at :3063, once again in workers).
  Adding SID collection does not worsen this; a cheap header-only scan is a
  separate optimization.

### B.4 VOD store writes

Write paths (verified):

- `GnssResearchSite.store_vod` — `manager.py:623-680`: **direct** `to_icechunk`
  inside its own session (`mode="w"` if group missing, else `append_dim="epoch"`,
  manager.py:651-660). It does *not* route through `write_or_append_group`.
- `manager.py:436` — `vod_store.write_or_append_group(...)` (second VOD write path).

Under ragged inputs, `calculate_vod`'s `xr.align(join="inner")` (manager.py:578-580;
`canvod-vod/calculator.py:141-145`) yields a **variable SID axis per day** — today
this is masked because both inputs arrive identically padded.

**Store-axis decision for VOD groups:** create each VOD analysis group with the
**same resolved universe axis as the SNR stores** (option chosen for consistency
and simplicity; a canopy∩reference subset would save little and add a second axis
convention). Then:

- `store_vod` (manager.py:651-660): on group creation, reindex `vod_ds` to the
  universe; on append, reindex to the group's existing axis (same helper as B.2).
- `write_or_append_group` gets the internal guardrail from B.2 anyway.
- VOD reads are unaffected: consumers mask NaN (Phase 0 §4-5), and
  `VodComputer`'s chunk spec `{"epoch": 34560, "sid": -1}`
  (`canvodpy/vod_computer.py:73`) is size-agnostic.
- Semantics note: a SID observed by only one receiver produces a NaN row after
  reindex — identical to today's padded behaviour, so no scientific change.

### B.5 Aggregation guards

`packages/canvod-grids/src/canvod/grids/aggregation.py`:

- :81-83 — `vod.sel(sid=sid)` / `cell_ids.sel(sid=sid)`: guard with an intersection
  (filter the requested list to `ds.sid.values` membership; log requested-but-absent
  SIDs; raise only if the intersection is empty).
- :236-238 — `data_ds.sel(sid=selected_sids)`: same guard.
- (These datasets come from the store, which keeps a fixed axis under this design,
  so the guard is belt-and-braces — but it also fixes the latent KeyError for
  user-supplied SID lists that were never valid.)

### B.6 L1/L2/L4 API behaviour

- **L1** `canvodpy.read_rinex` (`canvodpy/functional.py:51-98`, exported at
  `__init__.py:206`) calls `reader_obj.to_ds(write_global_attrs=True)` — reader
  default `pad_global_sid=True` applies. **Unchanged** (backward compat).
- **L2** `FluentWorkflow.read` (`canvodpy/fluent.py:189`) — same, unchanged. If a
  fluent chain later writes to a store, the store-level guardrail (B.2) reindexes
  as needed, so padded L2 output stays valid.
- **L4** `functional.read_rinex` accepts `**reader_kwargs`, so power users can
  already pass `pad_global_sid=False` today; document this.
- **Distinguishing mechanism:** none needed beyond explicit kwargs — the
  orchestrator path is the only place that changes, at the two call sites in
  `preprocess_with_hermite_aux` (B.1). No global flag, no config knob required
  (optionally a `ProcessingParams` escape hatch `pad_in_readers: bool = False`
  for rollback; see B.9 Q4).

### B.7 Dedup guardrail — confirmed SID-agnostic

`_check_existing_with_temporal_overlap` (`processor.py:1662-1743`): layer 1 is
`batch_check_existing` on hashes (:1679-1682); layers 2-3 build `(start, end)`
epoch intervals (:1685-1692 ff.). No SID-shape or sid-coordinate access anywhere in
the dedup logic. `should_skip_file` (used by `write_or_append_group` dedup,
store.py:1415-1433) is likewise hash+time only. **No changes required.**

### B.8 Tests

Likely to break / need review:

- Orchestrator/integration tests that assert `ds.sizes["sid"] == <universe>` after
  processing (search `canvodpy/tests/` for sid-size assertions; `test_dask_serialization.py:31`
  uses explicit `keep_sids` lists and `keep_sids=None` — semantics of the *reader
  output* change to ragged in the orchestrator path).
- canvod-readers tests are safe (reader defaults untouched).
- Store tests (`test_store_guardrails.py`, `test_store_regression.py`,
  `test_metadata_overlap.py`) pass identical-axis datasets today; they should keep
  passing, then be **extended** per below.

New tests (store-level, `packages/canvod-store/tests/`):

1. **Different-SID append correctness**: create group from file A (SIDs {G01,G02}
   axis fixed to a 4-SID universe), append file B observing {G02,G03}; read back
   and assert each SID's values landed on the right row and G04 is all-NaN — the
   anti-silent-misalignment test. Include the nasty case: |A-SIDs| == |B-SIDs| but
   different sets.
2. **First-write axis**: group creation uses the provided universe axis, not the
   first file's observed SIDs.
3. **Superset violation**: appending a dataset containing a SID outside the axis
   logs a warning and drops only that SID's rows.
4. **Region path**: cooperative write with two files of different observed SIDs;
   skeleton axis = union/universe; read-back equals the batch-path result.
5. **VOD variable-axis**: two days with different inner-join SID sets appended to
   one VOD group; read back and verify per-day values by label.
6. **sid coord backfill**: after write-boundary reindex, sv/band/code/system coords
   are populated for padded SIDs (parity with `_fill_sid_coords_from_sid_strings`).

Mandatory gates after implementation (project guardrail policy):
`uv run pytest packages/canvod-audit/tests/` and `uv run pytest -m "not integration"`.
Tier-2 regression checkpoints must be bit-identical (padding at write time must
reproduce the current on-disk layout exactly when `keep_sids` resolves to the same
list).

### B.9 Dependency order, estimate, open questions

**Order within Task B:**

1. Store helper + guardrails in `store.py` (B.2 store-level) + tests 1-3 — safe,
   inert while inputs are still padded.
2. `_append_to_icechunk` first-write/append reindex (B.2 orchestrator) — still
   inert with padded inputs (reindex to identical axis is a no-op).
3. VOD path (B.4) + test 5.
4. Aggregation guards (B.5).
5. Flip the two `pad_global_sid=False` call sites (B.1) — the actual memory win;
   everything before this is a no-op-safe scaffold.
6. Region path (B.3) + test 4.
7. Audit suite + Tier-2 regression run.

**Interaction with Task A:** the first-write axis (B.2) consumes Task A's resolved
universe. Recommended land order: **B steps 1-4 → A → B steps 5-7**, or A and B in
one PR with B's scaffold first. Do **not** ship A's per-processing-date `on_date`
(option A.4a) before B step 2 is merged.

**Estimated size:** ~300-450 lines changed/added across `store.py`, `processor.py`,
`manager.py`, `aggregation.py` (excluding tests); tests ~300-400.

**Open questions (Task B):**

1. Axis for public `append_to_group`/`write_or_append_group` group creation when the
   caller has no config universe — first dataset's SIDs (proposed) or require an
   explicit axis argument?
2. Axis growth: if a genuinely new SID appears (new satellite launched mid-campaign
   and Task A resolves a newer date), the store axis cannot grow via appends.
   Options: warn+drop (proposed), or a maintenance operation that rewrites the
   group with a wider axis (Icechunk makes this a versioned commit). Decide policy.
3. `overwrite_file_in_group` (store.py:963) and `worker_task`/`worker_task_append_only`
   fallback paths (processor.py:429-502) — same reindex treatment; confirm these
   are still live code paths or candidates for deletion first.
4. Do we want a `ProcessingParams.pad_in_readers` rollback flag for one release, or
   is the audit suite sufficient confidence to go without?
5. The known-broken overwrite strategy (`_prepare_store_for_overwrite` Dask
   `.load()` TypeError, see memory/known issues) intersects the overwrite match arm
   at processor.py:1961-1968 — fix separately, but don't let B's changes mask it.

---

## Task C — Review: `canvod-virtualiconvname` (findings only)

**What it is** (~1,765 LOC + 9 test modules): filename-convention layer that maps
arbitrary receiver file names to the canonical
`{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}` name.

Modules: `convention.py:108-217` (`CanVODFilename`, frozen pydantic dataclass +
regex parser), `patterns.py:163-181` (`BUILTIN_PATTERNS` registry, 5 patterns +
auto-order), `mapping.py:104-378` (`FilenameMapper`, `VirtualFile`, overlap
detection), `validator.py:43-132` (`DataDirectoryValidator`, the pre-pipeline hard
gate), `config_models.py` (naming config models), `recipe.py:106-367`
(`NamingRecipe`, width-based field extraction from YAML), `catalog.py:79-301`
(`FilenameCatalog`, DuckDB-backed mapping cache).

Consumers (verified): `canvodpy` orchestrator/pipeline/tasks/fluent,
`canvod-readers` (`matching/dir_matcher.py` — deprecated — and
`gnss_specs/constants.py`), `canvod-utils` config models (opaque dict pass-through).

### Findings

**Complexity / scoping**

- C1. **Three overlapping mapping mechanisms**: builtin `SourcePattern` regexes,
  `NamingRecipe` width-walks, and per-receiver naming config defaults. The core
  (convention + patterns + mapper + validator, ~1,000 LOC) is well-scoped and
  justified. `NamingRecipe` (367 LOC) is used in exactly one place
  (`canvodpy/workflows/tasks.py:355-365`, a validation task); it duplicates what a
  custom `SourcePattern` could express. Two extension mechanisms for the same
  problem is one too many.
- C2. **`FilenameCatalog` is dead code**: zero consumers outside its own tests
  (verified repo-wide grep). It pulls in the `duckdb` dependency, and duplicates the
  role of the Icechunk metadata table (canonical_name/physical_path are already
  persisted per write, store.py:1490-1491). Candidate for removal or explicit
  "experimental" quarantine.

**Correctness edge cases**

- C3. **Silent skips in discovery**: `discover_all`/`discover_for_date` swallow
  `ValueError`/`KeyError` per file with `continue` and **no logging**
  (mapping.py:145, 178). The validator reports unmatched files, but the L2 path
  (`fluent.py:226` uses `FilenameMapper` directly) and any caller that skips the
  validator can silently omit data files. At minimum these skips should be logged;
  ideally discovery returns a report like the validator does.
- C4. **Cross-midnight overlaps missed**: `detect_overlaps` groups by `(year, doy)`
  and compares minute intervals within the day (mapping.py:308-333); `end_min` can
  exceed 1440 but files starting on the *next* day are in a different group, so a
  23:45 15M file vs the next day's 01D file can't be flagged. Low likelihood, but
  the dedup guardrails downstream would catch the data-level consequence — worth a
  comment or fix.
- C5. **Period inference heuristics**: `hour_letter == "0"` ⇒ `period = "01D"`
  (mapping.py:257-262) and recipe's "no hour field ⇒ daily" (recipe.py:296-301)
  encode conventions that are usually right but silently mis-tag e.g. an hourly
  file named with `0`. Wrong period → wrong overlap detection (C4 interacts).
  Config-declared `period` is the tiebreaker but defaults can lie.
- C6. **`NamingRecipe.matches` requires exact filename length** (recipe.py:331-339)
  and has no compression-extension handling — `foo.25o.gz` never matches a recipe
  written for `foo.25o`. `_detect_file_type` in mapping.py handles compression;
  recipe.py does not. Inconsistent.
- C7. **Two hash notions**: catalog's `_compute_file_hash` is SHA-256 of the first
  64 KiB truncated to 16 hex chars (catalog.py:56-64) — deliberately partial, but
  it shares the column name pattern (`file_hash`) with the pipeline's full-file
  "File Hash" used by dedup. If catalog data ever met store metadata, they would
  disagree. (Moot if C2 removal happens.)
- C8. **PEP 758 syntax** (`except ValueError, KeyError:` without parentheses,
  mapping.py:145,178; validator.py:103) — valid only on Python ≥3.14; the package
  correctly pins `requires-python = ">=3.14"`, so this is fine, but it silently
  hard-blocks any future attempt to relax the monorepo's floor.

**Performance**

- C9. **Not on a hot path.** Discovery is per-day directory globbing + regex per
  file; overlap detection is O(n²) per day with n < 100. Negligible next to
  reading/padding. `FilenameCatalog.record_batch` is a per-row SELECT+INSERT loop
  without a transaction (catalog.py:183-186) — would be slow at 10⁵ rows, but it
  has no callers (C2).

**Coupling**

- C10. Naming config lives in `sites.yaml` but is stored as **opaque dicts** in
  canvod-utils and validated only when a `FilenameMapper` is constructed
  (config_models.py docstring, lines 1-6). Config errors surface at pipeline
  runtime rather than at `just config-validate` time — unless the validator task
  runs first. Consider validating the `naming:` sections during `SitesConfig`
  construction via a late import or a plugin-style validator registration.
- C11. `canvod-readers` depends on the package for the deprecated
  `DataDirMatcher`/`PairDataDirMatcher` path (`matching/dir_matcher.py`) — once
  those are removed, the readers→virtualiconvname edge can likely be dropped,
  simplifying the dependency graph.

**Open questions (C):** Should `NamingRecipe` be folded into `SourcePattern`
(user-defined patterns) or kept as the "no-regex-required" UX? Is `FilenameCatalog`
part of a planned feature (n8n/automate?) or removable? Should discovery-time skips
be a hard error under `file_pairing: complete`?

---

## Task D — Review: CLI and configuration approach (findings only)

### Current surfaces (verified)

- **Console script** `canvodpy` → `canvod.utils.config.cli:main`
  (`packages/canvod-utils/pyproject.toml:23-24`; typer app, 835 lines): `init`,
  `validate`, `show`, `edit`, `stats-*` (cli.py:91, 202, 331, 376, 654, 707, 781).
  This is **config management only** — it cannot run the pipeline.
- **Pipeline runner** `canvodpy/src/canvodpy/cli/run.py` (argparse, 366 lines,
  `main` at :285): `--site`, `--start/--end` (YYYYDOY, auto-resume from store
  metadata via `_last_processed_date` :88), `--no-vod`, `--dry-run`, `--workers`,
  `--batch-hours`. **Not registered** as a console script in `canvodpy/pyproject.toml`
  (verified — no `[project.scripts]`), so it runs via `python -m canvodpy.cli.run`,
  yet its argparse `prog` is also `"canvodpy"` (run.py:37). Two different CLIs
  claim the same name; the installed one is the config tool.
- **Config flow**: `load_config()` (`canvod-utils/config/loader.py:233-262`) →
  `ConfigLoader` finds the monorepo root by walking up to a `.git` **directory**
  (loader.py:20-55), reads `{root}/config/{processing,sites,sids}.yaml`,
  deep-merges over package defaults (loader.py:122-162), validates into
  `CanvodConfig(processing, sites, sids)` (models.py:977-988). Override hook:
  `CANVOD_CONFIG_DIR` env var (loader.py:257-260).
- **Into the pipeline**: `Site(name)` (L3, `canvodpy/api.py`) wraps
  `GnssResearchSite`; the orchestrator constructor reads
  `config.sids.get_sids()` (processor.py:613) and `ProcessingParams` fields;
  CLI `--workers`/`--batch-hours` are passed into `site.pipeline(n_workers=...,
  batch_hours=...)` (run.py:303-331) as ad-hoc overrides.

### Findings

- D1. **Repo-anchored config discovery**: `.git`-walk root finding breaks for any
  pip-installed / containerized deployment (falls back to `Path.cwd()/config`).
  `CANVOD_CONFIG_DIR` is the only escape and is not surfaced by either CLI's
  `--help`. No `--config-dir` flag on the runner. For the ops/n8n direction this
  is the first wall users will hit.
- D2. **Hidden global config loads inside library code**: e.g.
  `GnssResearchSite.calculate_vod` calls `load_config()` mid-function to read
  `store_delta_snr`/`store_radial_diff` (`manager.py`, verified in the
  calculate_vod body). This re-reads YAML from disk at compute time — config can
  drift between the orchestrator's snapshot and the store layer's, complicates
  testing, and couples canvod-store to the config-file layout. Config should flow
  in as data (constructor/params), not be re-loaded ambiently.
- D3. **Library code exits the process**: `ConfigLoader.load()` calls
  `sys.exit(1)` on validation error (loader.py:116-118) and `print`s warnings
  (loader.py:133, 146) instead of raising/structlog. Fine for a CLI, wrong for
  `load_config()` as a library entry point (L2/L4 users get a dead interpreter).
- D4. **"What" vs "how" separation is half-done.** Good: `sites.yaml` = what
  (sites/receivers/analyses), `processing.yaml` = how, `sids.yaml` = filter.
  Blurred: `ProcessingParams` (models.py:134-327) mixes scientific semantics
  (`file_pairing`, `store_radial_distance`, `store_sbf_raw_observables`) with
  machine-resource knobs (`resource_mode`, `n_max_threads`, `threads_per_worker`,
  `parallelization_strategy`); VOD analysis definitions live per-site in
  `sites.yaml` while VOD output toggles (`store_delta_snr`) live globally in
  `processing.yaml`. Reproducibility-relevant settings and machine-local settings
  should not share a section — a run's science config should be portable between
  machines without dragging worker counts along.
- D5. **Override precedence is ad hoc**: `--workers`/`--batch-hours` bypass the
  config model entirely (plain constructor args); there is no general
  CLI > env > user-yaml > defaults story, and no way to override any *other*
  config field from the runner (e.g. strategy, sids mode) without editing YAML.
- D6. **`ParallelismConfig` fit** (per `perf_plan.md` §A): embedding it in
  `ProcessingConfig` alongside `ProcessingParams` is consistent with the existing
  hierarchy, and it directly resolves half of D4 by giving resource knobs their own
  model. It **must** subsume, not join, the four existing resource fields
  (perf_plan Q1): recommend `ParallelismConfig` as the single source, the old
  `ProcessingParams` fields deprecated with warnings, and `resolve_resources()`
  delegating. CLI `--workers` should become an explicit override of
  `ParallelismConfig.max_workers` (addresses D5 for the one field that matters
  most), and `mode: backlog|daily` maps cleanly onto the runner's two real usage
  patterns (historical backfill vs cron ingest).
- D7. **Duplication/monolith**: 24 model classes in one 990-line `models.py`
  (verified class list) — the perf_plan's "separate file per concern" approach
  (parallelism.py) is the right direction generally. Naming config as opaque dicts
  (see C10) is part of the same "validation lives elsewhere" pattern.
- D8. **Two CLIs, one name** (see surfaces above): either register the runner as
  the `canvodpy` script and move config commands under it (`canvodpy config
  validate`, `canvodpy run --site ...`), or rename one. Current state means
  `canvodpy --site X` fails for every new user who followed the docs to install
  the workspace.

**Open questions (D):**

1. Is the intended long-term entry point the L3 `Site` API with `run.py` as thin
   sugar, or should the runner become the primary operational interface (n8n/
   Airflow call it)? This decides how much CLI investment is warranted.
2. Where should per-run overrides live once `ParallelismConfig` exists — CLI flags,
   env vars (`CANVOD_*` family), or a `--set key=value` passthrough?
3. Should `CanvodConfig` snapshots be persisted into store metadata per run (the
   store-metadata package already has a `config` section) so that D2-style drift is
   at least auditable?
4. Config validation timing: move naming-section validation (C10) and
   `sites.yaml` data-dir pre-flight into `canvodpy validate` so all gates run
   before any pipeline start?

---

## Combined sequencing recommendation

1. **B scaffold** (store-level reindex guardrails + tests) — inert, safe.
2. **A** (universe builder + config change), with `on_date` = processing date.
3. **B flip** (`pad_global_sid=False` in orchestrator) + region path.
4. Audit suite + Tier-2 regression (bit-identical stores expected when the resolved
   universe equals the previous padded axis; otherwise freeze new checkpoints
   deliberately).
5. C/D items are review-only; C3 (silent discovery skips) and D3 (`sys.exit` in
   loader) are small, high-value fixes that could ride along with any PR.
