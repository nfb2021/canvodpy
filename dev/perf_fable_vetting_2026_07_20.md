# Fable vetting pass — write-serialization + concurrent-write architecture (2026-07-20)

Companion to `dev/perf_degradation_findings_2026_07_15.md` (Problems A/B/C,
shipped 2026-07-15) and `dev/todo_later.md` §34/§42/§44/§47. This pass
independently re-derives the write-serialization numbers from
`run_id=rosalia-20260719-094240` (do not trust the prior Sonnet pass's
numbers without re-checking — that is the point of this document), then
uses the actual Icechunk Rust source at `~/Downloads/icechunk/` (not just
docs) to answer the open architectural questions about concurrent writes
and the unresolved `915c5844` stall.

## Part A — independent verification of the prior pass's numbers

Re-parsed `.logs/component/icechunk.log` from scratch with a fresh script
(not reusing the prior pass's parsing), filtered to
`run_id=rosalia-20260719-094240`.

### A.1(a) — 80.5% of wall-clock in serialized writes: **CONFIRMED, exact**

- 168 `batch_write_session_started` / 168 `batch_write_complete` pairs.
- First start `09:43:15.886`, last end `10:54:59.564` → wall-clock
  **4303.7s**.
- Sum of all 168 `duration_seconds` → **3464.8s**.
- **3464.8 / 4303.7 = 80.51%** — matches the prior pass's figure to two
  decimal places.

### A.1(b) — zero concurrent write sessions: **CONFIRMED, exact**

Built a chronological START(+1)/END(-1) timeline over all 336 events and
tracked the running `active` count programmatically (not sampled): max
concurrent active sessions across the entire run = **1**. Zero timestamps
with `active > 1`. Gap between one write's END and the next write's START:
median **0.171s**, mean 5.02s (inflated by 42 gaps >1s, max 69.8s) —
confirms the parallel loky pool is keeping pace; the single write slot,
not pool starvation, is the ceiling.

### A.1(c) — flat ~20-22s per-write duration, no growth trend: **CONFIRMED at the batch level, but this masks a large and entirely real intra-day cost pattern the prior pass's own "corrections" section got wrong**

Batch-level (`batch_write_complete.duration_seconds`, one value per
receiver-day, 168 total): linear regression slope over chronological
index = **+0.0084 s/write**, predicting **1.4s** of drift over the whole
168-write run against a mean of 20.6s — genuinely flat, confirmed.

**But** the prior pass's "Corrections from the vetting pass" section in
`perf_degradation_findings_2026_07_15.md` states: *"`process_data` growth
is real but the mechanism was under-specified... no within-batch sawtooth
(ratio ~0.7-1.0 across every decile of the run)."* Independently
re-checking this at the **individual `icechunk.file_append` event**
level (not the aggregate `batch_write_complete` level that claim was
based on) shows the opposite: **every single one of the 168
(receiver, date) groups in this run shows a strong, structural,
near-linear growth in per-file append cost from `file_index=0` to
`file_index=95`,** with remarkably consistent shape across all 168
groups:

```
pos=  0 canopy_01/2025090:               first=0.205 last=0.329 slope=+0.0022
pos=  2 reference_01_canopy_01/2025090:  first=0.082 last=0.335 slope=+0.0027
pos= 10 reference_01_canopy_02/2025092:  first=0.050 last=0.338 slope=+0.0027
pos= 40 canopy_01/2025100:               first=0.052 last=0.330 slope=+0.0026
pos= 48 canopy_02/2025102:               first=0.437 last=0.318 slope=+0.0016
```

The **last-file duration converges to ~0.32-0.34s in every single one of
the 168 groups**, throughout the entire 71-minute run — not just the
first day (ruling out "cold cache at run start" as the explanation). The
slope is consistently **+0.0023 to +0.0028 s per file_index** across
every group. This is not noise; it is a clean, reproducible, per-day
structural cost curve that resets every day (which is exactly why it
doesn't show up in the batch-level flatness check — 96 files' worth of a
0.05→0.33s ramp still sums to ~20s whether or not the ramp exists, so the
prior pass's day-total check was blind to it, and its `.first`/`.last`
decile check on `process_data_per_file` was almost certainly binned
across receivers/dates in a way that washed the signal out rather than
isolating one day's 96-file sequence).

**Root cause, confirmed by directly inspecting the live store's array
chunk shapes** (not inferred — opened the actual store read-only):

```
$ .venv/bin/python3 -c "... zarr.open_group(store=session.store)['canopy_01']['SNR'] ..."
SNR shape=(724795, 277) chunks=(17280, 277) dims=('epoch','sid')
```

`chunk_strategies.rinex_store.epoch: 17280` (`packages/canvod-config/src/canvod/config/defaults/processing.yaml:47`)
is not just the Icechunk *manifest-split* range — it is the **physical
Zarr chunk size**, and 17280 epochs = exactly one full day at this
site's 5s sampling (96 files × 180 epochs/file). `sid: -1` means the
entire 277-SID dimension is one chunk too. So **every array has exactly
one physical chunk per day**, and every one of the 96 fifteen-minute
file-appends within that day writes into the *same* chunk. Zarr's zstd
compression is applied per-whole-chunk (`compression_algorithm: zstd`,
`processing.yaml:39`) — there is no in-place patch of a compressed
chunk; each append must read the chunk as currently populated, merge in
180 new epochs, recompress, and rewrite the whole thing. Cost scales with
how much of the day's chunk is already filled, which is exactly the
observed near-linear growth from file 1 (a nearly-empty chunk, cheap) to
file 96 (a nearly-full day's chunk, ~0.33s).

**This is a genuinely new, independently-confirmed finding this pass
adds to the record — not a re-statement of Problem A/C from the
2026-07-15 doc**, which was about cross-*batch*/cross-*day* drift, not
this within-day pattern. It does **not** contradict the 2026-07-15 doc's
Problems A/B/C (those remain correctly diagnosed and fixed), but it does
mean that specific "no sawtooth" correction in that doc was itself
wrong, or at least measured the wrong axis. Practical impact: **the
day-chunk-growth pattern likely accounts for roughly half of the total
per-file append cost by the end of each day** — first-file costs cluster
around 0.05-0.3s, last-file costs cluster tightly around 0.32-0.34s
regardless of receiver or date. See Part C recommendation #1.

### A.1 — resource_sample cross-check (CPU/RSS): CONFIRMED, minor numeric nuance

144 `resource_sample` events for this run_id. `cpu_percent`: min 0.0
(first sample only, pool still warming up), max **73.6%** (prior pass
said "27-67%" — actual max is a bit higher, but the qualitative claim
"not saturated" holds), mean 41.5%. `children_rss_gb`: range
0.169-2.313GB, linear-regression slope **-0.0057 GB/sample** (net
**-0.82GB** drift over the run) — confirms "no runaway growth, trending
down" as claimed.

### A.1 — store state at rest: CONFIRMED, exact

Counted directly with `find <dir> -type f | wc -l`:

| | RINEX_both_receivers | VOD_both_receivers |
|---|---|---|
| snapshots | 338 | 211 |
| manifests | 3696 | 2436 |
| transactions | 338 | 211 |
| chunks | 65785 | 420 |

Matches the prior pass exactly.

### A.1 — errors.log: CONFIRMED, exact, with one added detail

4 total errors in `.logs/human/errors.log` for this run: 3×
`prepare_batch_failed` (dates 2025087/2025088/2025089, all within a
6ms window at `09:42:42.26-.28`) referencing a missing
`.../shared_cache/aux_cache.zarr/<fingerprint>/.DS_Store`, and 1×
`task_failed` for `rref112q30.25o` — verified this is genuinely
`pydantic_core.ValidationError: ... could not find first valid header
line`, i.e. a corrupt/truncated RINEX file, not a pipeline bug, exactly
as claimed.

## Part A.2 — the `.DS_Store` aux-cache bug: real, but mischaracterized

The prior pass's framing — "the shared aux cache's directory-listing
code... is not filtering `.DS_Store`" — **does not match the actual
code**. Read the real implicated files directly:

- `packages/canvod-auxiliary/src/canvod/auxiliary/cache_fingerprint.py`
  (`compute_aux_cache_fingerprint`) never lists a directory at all — it
  only `.stat()`s file paths it's explicitly handed. Not the source of
  the bug.
- `packages/canvod-utils/src/canvod/utils/tools/sanitize.py`
  (`sanitize_directory`, used by `_ensure_shared_aux_cache`,
  `canvodpy/src/canvodpy/orchestrator/processor.py:1699` and `:1733`)
  **is** `.DS_Store`-aware and already race-safe on its own delete —
  its docstring explicitly anticipates concurrent sweeps and its
  `.unlink()` call catches `FileNotFoundError` for exactly that case
  (`sanitize.py:43-47`, comment: *"A concurrent sweep... already
  removed it — the desired end state already holds"*).

The actual mechanism: `pipeline.py:839-840` runs Phase-1 date-prep for
**up to 4 dates concurrently** in a `ThreadPoolExecutor`
(`phase1_workers = min(len(batch), 4)`). Each thread independently calls
`_ensure_shared_aux_cache` (`processor.py:1655`) for its own date but the
**same fingerprint** (agency/product/ephemeris config is shared across
nearby dates). All three failed dates in this run hit the same two
fingerprints and failed within a 6ms window — consistent with a genuine
race between one thread's `sanitize_directory(cache_root)` sweep
(`processor.py:1699` on hit, `:1733` after populate) unlinking a stray
`.DS_Store` at the exact moment another concurrently-running thread's
`aux_processed.to_zarr(output_path, group=tmp_group, mode="w",
consolidated=False)` (`processor.py:1206`) is inside Zarr's own internal
group-open/listing logic for the shared `cache_root/<fingerprint>/`
directory and trips over the file disappearing mid-listing. `sanitize_directory`'s own delete is guarded against this; Zarr's internal
listing (third-party code, not something canvodpy's own guard reaches)
is not.

This bug is real, but it's a **cross-thread race in Zarr's own internal
listing path during concurrent Phase-1 prep**, not "unfiltered
enumeration in canvodpy's own cache code" (no such enumeration exists).
Severity: low — self-healing next run (the `sanitize_directory` sweep
that caused the collision also fixes the underlying litter), and this
run only lost 3 dates from *this run's* Phase-1 prep (`pipeline.py:866`
does `continue`, silently dropping the date from this run — worth
flagging against the project's own "never silently skip-and-continue
past a real failure, only retry known transient faults" rule, since
today's `except (OSError, ValueError)` doesn't distinguish "this file
race will resolve on retry" from a genuine failure; see Part C).

## Part B — Icechunk source-grounded architecture questions

Used the real Icechunk source at `~/Downloads/icechunk/` (Rust core +
Python bindings + design docs), not public docs. Citations are file:line
against that checkout unless noted.

### B.1 — why does a single `to_icechunk()` call cost ~0.1-0.3s, and is it bounded by manifest splitting or tied to total store history?

**Two separate cost mechanisms found, of very different scale — and the
per-file 0.1-0.3s cost is dominated by neither of the mechanisms the
2026-07-15 doc focused on:**

1. **Dominant, newly confirmed this pass (see A.1(c) above): whole-chunk
   read/recompress/rewrite cost**, because `chunk_strategies.epoch=17280`
   makes the physical Zarr chunk span a full day, and every 15-min
   append partially fills the *same* chunk. This is **not** manifest
   work at all — it happens inside `to_icechunk()` per file, which only
   mutates the in-memory `ChangeSet` and writes chunk bytes
   (`asset_manager.rs:906`, `write_chunk`) — `do_flush`'s manifest
   rewrite (see below) only runs **once**, at the final
   `session.commit()`, not per file. This cost is bounded by *one day's*
   data (resets every day, confirmed in A.1(c): last-file duration is
   ~0.32-0.34s throughout the whole 56-day run with no cross-day
   growth), **not** tied to total store history.

2. **Manifest-rewrite cost, confirmed bounded by `manifest_splitting`,
   not total history** — but this only fires once per commit (once per
   ~96-file batch), not once per `to_icechunk()` call. Read
   `do_flush`/`flush_existing_node` directly
   (`icechunk/src/session.rs:2875-3010`, `:2600-2690`): for an array
   with no changes in this session's `ChangeSet`, `flush_existing_node`
   returns immediately (`session.rs:2617-2619`, `if rewrite_manifests ||
   change_set.is_updated_array(...) || change_set.has_chunk_changes(...)`
   — false for untouched arrays, no manifest work). For a touched array,
   the rewrite is explicitly designed and commented to be **"proportional
   to the size of the split, not... the total size of the array"**
   (`session.rs:2644-2645`) — with `manifest_splitting_epoch_range=17280`
   matching exactly one day, this bounds manifest-rewrite cost to the
   *current day's* data, confirmed by source, not the store's 338
   accumulated snapshots. One caveat found: `do_flush` still calls
   `old_snapshot.iter()` over **all** array nodes in the store
   (`session.rs:2918-2921`) to decide which ones changed — an
   O(total-array-count-across-all-4-receiver-groups) enumeration on
   every single commit, but this is a cheap in-memory dict lookup per
   node, not the dominant cost (`timings.commit` sub-metric was already
   observed small, 1.9-3.5s, in the 2026-07-15 doc's own telemetry).

3. **Repo_info write cost, confirmed real but small at this store's
   current size**: `do_commit_v2`/`update_repo_info_internal`
   (`asset_manager.rs:815-903`, `:945-1010`) writes a single
   `$ROOT/repo` flatbuffer containing all snapshot metadata on every
   commit. `num_updates_per_repo_info_file` (default 1000, confirmed
   against installed 2.1.1) shards this, so cost scales with
   `min(total_snapshots, 1000)` within the current shard — at 338
   snapshots this is small (~87KB of `SnapshotInfo` at ~256B each), but
   grows toward the 1000-shard boundary. This happens once per commit
   (once per ~96-file batch), consistent with the flat batch-level
   totals in A.1(c).

**Bottom line for B.1**: manifest splitting does genuinely bound the
manifest-rewrite cost to "this day's data," confirmed by source — but
that's not actually where most of the observed 0.1-0.3s per-file cost
comes from. The dominant driver is the whole-day-chunk rewrite pattern
in A.1(c), which is a *chunking* choice (`chunk_strategies.epoch`), not
a manifest-splitting one.

### B.2 — can the 4 receiver-groups' `_append_to_icechunk` calls run concurrently against non-overlapping Zarr groups in the same repo/branch?

**No — confirmed directly from source, not inferred.** Read
`do_commit_v2` (`icechunk/src/session.rs`, the actual function body):

```rust
let actual_parent = repo_info.resolve_branch(branch_name).inject()?;
if &actual_parent != parent_snapshot_id {
    return Err(RepositoryError::capture(RepositoryErrorKind::Conflict {
        expected_parent: Some(parent_snapshot_id.clone()),
        actual_parent: Some(actual_parent),
    }));
}
```

This check fires on **every** commit attempt, comparing the branch's
*current* tip against what the session expected when it was opened —
**at the branch level, with no per-array/per-group scoping whatsoever.**
It doesn't matter that two concurrent commits touch disjoint Zarr
groups; if either has already advanced `main`'s tip since the other's
session opened, the second one gets `RepositoryErrorKind::Conflict`
(surfaced to Python as `SessionErrorKind::Conflict`) — a hard, immediate
failure, not a silent merge. This is **not** absorbed by the
retry-with-backoff loop found in `update_repo_info_internal` — that loop
only retries on the narrower `RepoInfoUpdated` (a storage-object CAS
race on the repo_info file itself), and explicitly returns any other
error (including `Conflict`) immediately
(`asset_manager.rs:898-900`, `err @ Err(_) => return err`).

Icechunk *does* have a real, documented mechanism for exactly canvodpy's
scenario — the `Session::rebase()` docstring literally says: *"useful,
for example when different 'jobs' modify different arrays... 'merging'
the two changes is pretty trivial"* (`session.rs`, docstring above
`pub async fn rebase`), with a working example using
`BasicConflictSolver`. But this requires explicit adoption
(`.commit(...).rebase(solver, attempts)` instead of plain
`session.commit()`), and each conflict/rebase attempt **redoes the full
`do_flush`** (`do_commit_rebasing`, `session.rs:1725-1775`, calls
`commit_inner` fresh each attempt) — real, bounded, but non-trivial
overhead under contention, not a free lunch.

**So: naive dispatch of the 4 receiver-groups' writes to separate worker
processes, each calling plain `session.commit()` against the same
branch, is a non-starter as-is** — it would just produce
`SessionErrorKind::Conflict` failures on whichever writer loses the
race, not silent corruption and not automatic serialization. A redesign
using `.rebase()` + a conflict solver, or a single dedicated
writer merging a queue of pending per-group changesets, are the two
real options; see Part C.

### B.3 — the `915c5844` 8+-minute near-zero-CPU stall: mechanism found in source but not conclusively matched to the historical incident

**Confirmed, first-party, load-bearing**: Icechunk's own source
explicitly documents that local-filesystem storage is not safe for this
exact scenario. `new_local_filesystem`
(`icechunk-arrow-object-store/src/lib.rs:317-329`):

```rust
/// This implementation should not be used in production code.
pub async fn new_local_filesystem(prefix: &StdPath) -> Result<ObjectStorage, StorageError> {
    tracing::warn!(
        "The LocalFileSystem storage is not safe for concurrent commits. \
         If more than one thread/process will attempt to commit at the \
         same time, prefer using object stores."
    );
    ...
```

This warning fires on **every** `Repository.open()` against this store
(reproduced live: opening `RINEX_both_receivers` read-only for this
investigation printed it immediately). This is Icechunk's own
maintainers stating, unambiguously, that the exact configuration
canvodpy runs in production (local SSD, `IcechunkStores/rosalia/...`)
is explicitly unsupported for concurrent commits — independent
confirmation that rules 228c6844/915c5844 were investigating a real,
acknowledged-by-upstream risk class, not a canvodpy-specific bug.

**What the source does *not* support**: a literal OS-level lock
(`flock`, advisory lock file, spin-poll). Checked both layers:

- Icechunk's local-FS backend routes through `object_store`'s
  `LocalFileSystem` (confirmed exact pinned version, `Cargo.lock:3297`,
  `object_store = 0.14.0`; inspected the closest locally-cached source,
  0.12.5, same conditional-write architecture). `put_opts` explicitly
  returns `Err(NotImplemented)` for `PutMode::Update`
  (`object_store-0.12.5/src/local.rs:327-328`) — local FS cannot do a
  true conditional update. `PutMode::Create` uses `std::fs::hard_link`
  (`local.rs:357-368`) — atomic, **non-blocking**; on conflict it
  returns `AlreadyExists` immediately, it does not spin or wait.
- Icechunk's own `LocalFileSystemObjectStoreBackend::default_settings()`
  (`icechunk-arrow-object-store/src/lib.rs:958-975`) explicitly sets
  `unsafe_use_conditional_update: Some(false)` for this backend (it
  can't rely on the object-store's conditional-update semantics locally)
  and — separate, easy to conflate — sets the *object-store I/O* retry
  settings to `max_tries=1, backoff=0` (fast-fail on transient I/O, not
  related to repo_info CAS retries).

So there is **no filesystem-level lock a second process could get stuck
spinning on** in either layer. The only mechanism found capable of a
multi-minute, near-zero-CPU wait is Icechunk's own **application-level**
sleep-based backoff in `update_repo_info_internal`
(`asset_manager.rs:815-903`, separate from the object-store I/O retry
settings above — this one is `RepositoryConfig.repo_update_retries`,
confirmed default `max_tries=100, initial_backoff_ms=50,
max_backoff_ms=30_000`, `config.rs:487-489`, unaffected by the local-FS
backend override). This loop only fires on `RepoInfoUpdated` (a
storage-object write race), **not** on `Conflict` (branch-tip mismatch,
which fails fast per B.2). The arithmetic fits well: 5 immediate
zero-delay retries, then exponential ramp 50ms→30s (~10 steps, ~51s
cumulative), then successive ~30s-capped retries — **reaching 8 minutes
takes roughly 14-15 retries at the cap**, well inside the 100-try budget.

**What this pass could not close**: reading the actual diff of
`228c6844` (the reverted commit) shows `Site.__init__` eagerly opens
*both* `rinex_store` and `vod_store` in *every* process (main process
and the dedicated VOD-writer subprocess alike), but after that change
**only the subprocess ever commits to `vod_store`** — the main
process's `vod_store` `Repository` handle sits idle. `RINEX_both_receivers`
and `VOD_both_receivers` are separate storage roots (confirmed: distinct
top-level directories, distinct `repo_info` objects) — so a genuine
`RepoInfoUpdated` collision on `vod_store`'s repo_info object requires a
*second* concurrent writer to that same store, and this pass could not
identify one in the code as it stood at that commit. The revert
commit's literal "lock contention... on the same local store" framing is
therefore **not supported as stated** by anything found in the source
(no lock exists to contend on) — but a **sleep-based CAS-retry stall of
the right order of magnitude is a real, confirmed capability of the
code**, just not proven to be the exact mechanism that fired, absent the
original incident's own stack trace/thread dump. **Recommendation if
this is retried**: enable Icechunk's Rust `tracing` output
(`RUST_LOG=icechunk=debug`) so retry-loop activity is visible in logs
instead of looking like a silent stall, and capture a `py-spy dump` (or
equivalent native thread dump) during any recurrence — this pass's
source reading narrows the search space substantially but cannot
substitute for that direct evidence.

## Part C — prioritized recommendations

All grounded in file:line citations above or already-verified store
state (132GB/338 snapshots/3696 manifests RINEX; 211/2436/420 VOD;
`store.maintenance()` confirmed never run, per
`canvodpy/src/canvodpy/orchestrator/processor.py:2585-2589`'s own
comment and `cli/store.py:300`'s interactive-confirm gate).

### 1. Re-chunk `rinex_store`/`vod_store` epoch chunking away from one-chunk-per-day (highest expected impact, low-to-medium risk)

**Grounds**: A.1(c) + B.1 — confirmed live that `chunks=(17280, 277)`
means every 15-min append rewrites an increasingly full whole-day chunk,
contributing roughly half the per-file write cost by the end of each
day (first-file ~0.05-0.3s → last-file ~0.32-0.34s, consistent across
all 168 groups in the run). This is a **separate** mechanism from
`manifest_splitting_epoch_range` (which is already correctly bounding
manifest-rewrite cost to one day, confirmed by source in B.1) — the two
config knobs happen to share the value `17280` in
`processing.yaml:47/57` but govern different things (physical chunk
size vs. manifest-file granularity).

**Expected impact**: if per-file costs were flat near the *first-file*
end of the observed range instead of ramping to ~0.33s, a rough
back-of-envelope from the observed slope suggests roughly 30-50% of the
per-day file-append total (currently ~15-20s of the ~20-22s daily write
total) could be recovered — a meaningful fraction of the 80.5%
wall-clock currently spent serialized.

**Risk / what could go wrong**: this is exactly the kind of "obvious"
fix this project has a track record of getting subtly wrong (915c5844).
Smaller epoch chunks means **many more chunk files** (currently 65785
for RINEX at one-chunk/array/day; shrinking chunk size multiplies this),
which (a) increases inode/filesystem overhead — this store already sits
on a real SSD but at 132GB/338 snapshots, more chunk churn is not free —
and (b) is the exact scenario memory §35 already flagged from the
*read* side (`xr.open_zarr` chunk-mismatch `UserWarning`, physical
chunks ≠ declared config) as "read-efficiency only, not data-integrity."
This pass's finding suggests that assumption should be revisited —
it may also be a **write**-efficiency issue, not read-only as
previously assumed. **Needs a throwaway-store experiment first**:
re-chunk to something between "one chunk per file" (180 epochs — likely
too fine-grained, chunk-count explosion) and "one chunk per day"
(current, confirmed expensive) — e.g. one chunk per few hours — measure
actual per-file append cost and total chunk-file count before touching
production config. Does **not** touch guarded scientific-correctness
code (chunking is a storage-layout choice, not the VOD formula/coordinate
transforms/dedup logic) but does touch `canvod-store` write paths — run
the audit suite after any change (`uv run pytest
packages/canvod-audit/tests/`).

### 2. Do not attempt naive parallel dispatch of the 4 receiver-groups' writes to separate processes (this investigation's answer to a specific idea, not a new recommendation — closing the loop from Part B)

**Grounds**: B.2 (branch-level `Conflict` check, no per-group scoping,
confirmed by source) + B.3 (Icechunk's own maintainers: "LocalFileSystem
storage is not safe for concurrent commits," confirmed firing live
against this exact store). Given the store already sits on local SSD
(confirmed fast, not the bottleneck), and given a real, still-unresolved
8+-minute-stall incident (915c5844) in this exact problem space, this
pass's conclusion is: **don't pursue parallel per-group commits without
first building and testing the `.rebase()` + `ConflictSolver` redesign
in isolation against a throwaway store**, and even then, expect real
retry overhead under contention (each conflict redoes the full
`do_flush`, confirmed by source in B.2) that may erode the parallelism
gain. If throughput is the goal, recommendation #1 (cheaper individual
writes) is lower-risk than recommendation #2 (concurrent writes) for
the same underlying 80.5%-serialized-write problem.

### 3. Fix the Phase-1 `.DS_Store` race to retry instead of silently dropping the date (low impact, low risk, quick)

**Grounds**: Part A.2. `pipeline.py:860-866`'s `except (OSError,
ValueError): ... continue` currently treats this transient,
self-healing race (confirmed: `sanitize_directory` already anticipates
and safely handles concurrent deletion of the same file on *its own*
path; the actual failure is in an *unguarded* Zarr-internal listing call
racing against it) the same as a genuine, permanent failure — dropping
the date from the run with no retry. This is a direct instance of the
project's own stated rule (`feedback_no_masking_fixes.md`): retry known
transient faults, never silently skip-and-continue past a real one. A
narrow fix — catch this specific `FileNotFoundError` pattern (message
containing `.DS_Store`) and retry the date's Phase-1 prep once — would
recover the 3 dates lost in this run without broadening the except
clause's blast radius. Low risk: touches only the exception-handling
path in `pipeline.py`, not scientific logic; a single retry with no
backoff is sufficient since the race window is milliseconds (confirmed:
all 3 failures landed within a 6ms window). No audit-suite dependency
(not touching VOD/dedup/coordinate code).

### Not re-recommended (already handled)

- §42 (task/date ordering defeating cross-receiver interleaving) —
  confirmed shipped (`6e98d002`, `_interleave_by_receiver` present and
  active in `pipeline.py:136-198`; the observed write order in this
  run's log — canopy_01/canopy_02/reference_* interleaved rather than
  block-contiguous — is consistent with it being live).
- Store `maintenance()`/GC — confirmed still correctly **not**
  auto-invoked (per the `processor.py:2585-2589` comment about O(n)→O(n²)
  cost, and `cli/store.py`'s interactive-confirm gate); at 338/211
  snapshots this store is not yet at a size where deferring this is
  costing meaningfully. No change recommended this pass — the
  2026-07-15 doc's retention design (tags + separately-scheduled
  expire/GC) remains the right shape whenever it's picked back up;
  nothing in this pass's findings changes that plan.
