# Cross-group fork/merge writes for `skip`/`unsafe_append` strategies

Status: **design only, no code written yet.** Continues `dev/todo_later.md`
§50 ("Parallel writes across receiver-groups — feasibility resolved"), which
established fork/merge as the safe alternative to `.rebase()`/`ConflictSolver`
but left the actual cross-group implementation as a proposed, unstarted task.
This document is that implementation plan.

## Context

canvodpy writes one Icechunk store per site, with one Zarr group per receiver
(canopy, reference, ...). Today, `RinexDataProcessor.parsed_rinex_data_gen`
(`canvodpy/src/canvodpy/orchestrator/processor.py`, PHASE 3, lines
~3583-3638) writes each receiver group's data **sequentially**: one
`writable_session()` + `commit()` cycle per group, one after another, via
`_append_to_icechunk` (lines 2184-2809).

This is the last real serialization point in an otherwise-parallel pipeline
(PHASE 1/2 already thread-parallelize file discovery and RINEX augmentation
across all receiver groups). It's serialized because `commit()` is a
ref-write, and canvodpy's only deployment backend (LocalFileSystem — local
SSD or CIFS/NFS, never S3/GCS/Azure) has **no real CAS/conditional-write
primitive**: two concurrent `commit()` calls on the same branch don't
conflict-error, they silently race and the loser's ref update is lost
(confirmed against Icechunk's Rust source, documented in
`.claude/skills/icechunk/SKILL.md` "Conflict Resolution", and in
`dev/todo_later.md` §50). So groups can't just commit in parallel.

The fix is Icechunk's fork/merge primitive: `Session.fork()` does an
anonymous flush-only commit (persists content-addressed data, never touches
the branch ref) and `Session.merge()` is pure in-memory changeset merging —
neither touches the racy ref-update path, so N groups can write into N
independent forks in parallel, then merge into one base session and issue
exactly **one** real `commit()`. This pattern is already proven in this
codebase (`DistributedRinexDataProcessor._cooperative_distributed_writing`,
lines 3851-3970) but only for *intra-group* file-level parallelism on a code
path that isn't wired into the live pipeline. This plan extends the same
primitive *across* receiver groups, on the live path.

Scope: only the `skip` and `unsafe_append` `gnss_store_strategy` values (plus
new-file-always-write, which is strategy-independent). `overwrite` is
excluded entirely — it uses a temp-branch-create + `reset_branch` sequence
with the same LocalFileSystem ref-write hazard, and redesigning that is
separate future work. Confirmed via `processor.py:872` that
`_gnss_store_strategy` is set once per processor run (whole site/day), not
per receiver group — so the split is "whole day is overwrite (untouched) or
whole day is skip/unsafe_append (new fork/merge path)," not a per-group
partition within one day.

## Design

### 1. Concurrency: `ThreadPoolExecutor`, one thread per receiver group

Not processes. PHASE 2 has already loaded all datasets into the parent
process's memory — a `ProcessPoolExecutor` would mean pickling large
`xr.Dataset`s and `ForkSession` objects across a process boundary for no
CPU-bound work left to parallelize (all the CPU-heavy augmentation already
happened in PHASE 2; PHASE 3 is I/O — Zarr chunk writes and blosc
compression, which release the GIL). Threads also keep `zarr_async_concurrency`
(a per-process cap, confirmed in `store.py`) at its configured value instead
of silently multiplying it by worker count against a CIFS/NFS mount — the
exact hazard that knob exists to manage. This resolves §50's open point 2/3
(the storage-backend-dependent worker-count question) for the write phase
specifically: threads sidestep the "N workers multiply concurrent I/O against
the mount" problem entirely, since there's still only one process.

Create one independent fork per group up front, in the parent thread —
`forks = {name: base_session.fork() for name in group_names}` — not one
shared fork passed to multiple workers (that only works in the existing
`_cooperative_distributed_writing` because each `ProcessPoolExecutor.submit()`
pickles an independent copy per process; with threads there's no such
serialization boundary, so concurrent mutation of one shared fork by multiple
threads would be unsafe).

### 2. Refactor `_append_to_icechunk` into three pieces

**a) `_prepare_group_write(...) -> GroupWritePlan`** — extract today's STEP 1
(lines 2220-2256) as-is: `_check_existing_with_temporal_overlap` runs
sequentially, per group, before any fork exists (already true today, no
positional change needed). This resolves §50's open point 1 (dedup-under-
fork/merge timing) for the cross-group case: the check is confirmed
`receiver_name`-scoped with zero cross-group reads (`load_metadata_for_dedup`,
`batch_check_existing`, `check_temporal_overlaps` all key off
`receiver_name`), so running it independently per group ahead of fork
dispatch is safe. Bundle its output (augmented_datasets, file_hash_map,
existing_hashes, aux_datasets, sid_issues, reader_format) into a small
dataclass.

**b) `_write_group_into_fork(fork_session, plan, groups_at_batch_start) -> GroupWriteResult`**
— runs inside the thread pool, one call per group. Today's STEP 2
(non-overwrite branch only) + STEP 3, with `session` replaced by the group's
own `fork_session` (the file already imports and uses `ForkSession` from
`icechunk.session` for the existing intra-group cooperative-write path, so
forks are a confirmed drop-in for every place `_append_to_icechunk` currently
only calls `.store`/`to_icechunk` on `session`). Drop the `(True,
"overwrite")` match arm — dead in this path. Includes the
`append_metadata_bulk(..., session=fork_session)` call — confirmed
per-group-disjoint (`{group_name}/metadata/table`, own `start_index` from its
own subtree length, no cross-group read). Returns actions/metadata_records/
timings so post-commit diagnostics can still be logged per group.

**c) New orchestrator `_write_receiver_batch_forked(base_session, group_plans) -> dict[str, GroupWriteResult]`**:
fork per group → dispatch each into the thread pool → `base_session.merge(*results)`
→ **one** `base_session.commit(agg_message, metadata=agg_metadata)`. All
existing per-group structured logging (`icechunk.file_append`,
`batch_write_complete` with its `timings`/`actions` dicts, keeper tags) still
fires once per group in a loop after the commit, anchored to the shared
`snapshot_id`. `dir_entry_counts()` is store-global (not group-scoped) —
call it once per batch instead of once per group (removes an existing
redundancy).

### 3. PHASE 3 restructure — branch on strategy, not per-group

```python
if self._gnss_store_strategy == "overwrite":
    # UNCHANGED: today's exact sequential loop, byte-for-byte.
    ...
else:  # "skip" or "unsafe_append"
    plans = [self._prepare_group_write(...) for name, ... in normalized_configs if name not in skipped]
    with self.site.gnss_store.writable_session("main") as base_session:
        results = self._write_receiver_batch_forked(base_session, plans)
    for name, rtype, data_dir, _pos, fmt in normalized_configs:   # preserves yield order
        if name in skipped: continue
        daily_dataset = self.site.read_receiver_data(receiver_name=name, time_range=time_range)
        yield name, daily_dataset, total_s
```

**Behavior change worth noting**: today, group 1's dataset can be yielded as
soon as group 1's own commit lands, before group 2 starts writing. Under
fork/merge, nothing is readable until the whole batch's single commit lands —
all groups finish writing before the first read-back. `pipeline.py`'s caller
just collects `datasets[receiver_name] = ds` per yield (doesn't consume
streaming-ness today), so downstream impact is effectively zero, but it's a
real, visible change in yield timing.

### 4. New-group (first-ever-write) edge case — resolved with a sequential pre-pass, not left to chance

Whether `Session.merge()` correctly reconciles two forks that each
independently create a brand-new sibling top-level Zarr group is *not*
something the skill doc's fork/merge semantics settle (verified for
"never touches the branch ref," not for "concurrent new-group creation
reconciles correctly at the node-graph level"). Rather than trust this
blind on a data-integrity-guardrail path: add a short **sequential pre-pass**
before forking — for every group where `receiver_name not in groups` at
batch start, do that group's one-time "initial" `to_icechunk(...)` call
(with `encoding=chunk_encoding_for(...)`, preserving today's
chunk-shape-at-creation behavior) directly on `base_session`, one at a time,
before any `.fork()` for this batch. After the pre-pass every group in the
batch already exists, so no fork ever races another fork to create a new
group. Cost: at most one extra tiny sequential write per receiver-group, once
in the entire lifetime of a site's store (the day it's first seen) —
effectively free amortized over the store's life, and it removes the
riskiest correctness unknown from the design without depending on an
experiment succeeding. Still run the throwaway-store experiment (§ Testing,
Case B) once, with the fallback temporarily disabled, purely to learn whether
it's strictly load-bearing or belt-and-suspenders — not as a ship-blocking
gate, since the fallback is adopted either way.

### 5. Commit message / metadata aggregation

Message: `f"[v{version}] {yyyydoy}: {len(results)} groups: " + ", ".join(f"{name}({summary})" for name, r in results.items())`,
kept terse (skill doc notes ~200-byte practical ceiling on commit messages).
Metadata: preserve today's per-group fields (`receiver`/`start`/`end`/
`rinex_hashes`/`canonical_names`) under a `group__{receiver_name}` key per
group (JSON-encoded sub-dict), plus batch-level `date`/`receivers`/
`total_files`. Confirm via the throwaway-store smoke test (§ Testing) whether
`Session.commit(metadata=...)` round-trips a natively-nested dict cleanly
through the Rust binding — if yes, use a cleaner nested `agg_metadata["groups"]`
shape instead of JSON-stringified sub-values; decide from the test, not a
guess. (`commit()` signature confirmed via direct introspection:
`commit(self, message: str, metadata: dict[str, Any] | None = None, *, rebase_with=None, rebase_tries=1000, allow_empty=False) -> str`.)

### 6. Error handling: fail-fast, no partial merge

If any group's `_write_group_into_fork` raises: do not `merge()`, do not
`commit()` — log which groups succeeded/failed/never-started, re-raise.
Today, groups before a failing one in the sequential loop have *already*
committed independently and stay committed on retry; under one shared batch
commit that property is structurally impossible, so fail-fast is the
necessary (not just safer) choice — a best-effort partial merge would create
a new, silent failure mode (a "successful" commit missing one group's data,
with nothing downstream to detect it, unlike the VOD store's
`vod-reconcile`). Slightly more redundant recomputation on retry is an
acceptable cost for a guardrail-area change.

### 7. STEP 5/5b — consolidate to once per batch

STEP 5 (`source_format` root attr) is already a no-op after the first-ever
call — move it to run once after the batch commit, pure simplification.

STEP 5b (rich store metadata) is **not** idempotent today: every group call
appends its own `history` entry and re-runs the full config-drift diff, so a
2-group day produces two history entries with slightly different timestamps
for one conceptual ingest event. Consolidate to run once per batch after the
shared commit, aggregating file counts across groups into a single history
entry. This is a real, intentional behavior change bundled into the refactor
— call it out explicitly in the PR description, not as a silent side effect.
Check `packages/canvod-store-metadata/tests/test_schema.py` and
`test_config_drift.py` for coupling to today's "one entry per group per day"
shape before changing it.

## Testing / verification

Required (CLAUDE.md "Store dedup logic" guardrail):
```bash
uv run pytest packages/canvod-audit/tests/
uv run pytest -m "not integration"
uv run pytest packages/canvod-store/tests/test_store_guardrails.py packages/canvod-store/tests/test_metadata_overlap.py packages/canvod-store/tests/test_write_concurrency_cap.py packages/canvod-store/tests/test_repo_info_rewrite_config.py packages/canvod-store/tests/test_store_regression.py
uv run pytest packages/canvod-store-metadata/tests/test_schema.py packages/canvod-store-metadata/tests/test_config_drift.py
```

New throwaway-store cases (extend `packages/canvod-store/tests/build_day0_store.py`'s
existing synthetic-dataset scaffolding — real test files, not a scratch script):
- **Case A (steady state)**: two pre-existing groups, write 1-2 new files to
  each concurrently via the new batch path. Assert both groups read back
  correctly (checksum against a sequential-path run on a second throwaway
  store), `len(list(repo.ancestry(branch="main")))` grew by exactly 1, and
  both groups' metadata tables have correct new rows.
- **Case B (new-group edge case)**: fresh store, two never-seen groups, run
  once with the §4 sequential pre-pass disabled (to learn if merge handles it
  alone) and once with it enabled (the shipped default). Assert `list_groups()`
  returns both and both read back correctly.
- **Case C (fail-fast)**: monkeypatch `to_icechunk` to raise for one group
  mid-batch. Assert the exception propagates, `ancestry()` shows no new
  snapshot, and neither group's data is visible afterward.
- **Case D (overwrite non-interference)**: run one unmodified
  overwrite-strategy flow, confirm byte-identical behavior to pre-change
  baseline.
- Smoke-test `session.commit(metadata={"groups": {...}})` on a throwaway
  store to settle the nested-vs-JSON-string metadata shape question (§5)
  before finalizing.

## Files

- `canvodpy/src/canvodpy/orchestrator/processor.py` — `_append_to_icechunk`
  (2184-2809, split per §2), PHASE 3 of `parsed_rinex_data_gen` (3583-3638,
  restructured per §3). `_cooperative_distributed_writing` (3851-3970) stays
  untouched, used only as the reference pattern.
- `packages/canvod-store/src/canvod/store/store.py` — `writable_session`,
  `append_metadata_bulk`, `dir_entry_counts`, `create_keeper_tag`,
  `list_groups` (no changes expected, just consumed by the new orchestrator).
- `packages/canvod-store/tests/build_day0_store.py` + sibling test files —
  extend with Cases A-D.
- `packages/canvod-store-metadata/tests/test_schema.py`, `test_config_drift.py`
  — check for coupling to per-group history-entry shape before §7's change.
