# Write-side performance degradation — findings & fix plan (2026-07-15)

Companion to `dev/todo_later.md` §34 (investigation history, Tier 0
instrumentation) and §37 (dashboard log-visibility bug, fixed same day).
This file is the detailed writeup behind §34's "Action" pointer — Tier 2
design work, not yet implemented.

## How this was produced

1. Analyzed real logs from a 15.1h overnight backfill (`rosalia`, 4
   receivers, `days_per_batch=14`) at `~/Downloads/canvod-logs/`, merging
   `performance.json` with the rotated `performance.json.1` backup.
2. A Fable-model agent independently vetted the initial findings —
   corrected two of them (see "Corrections" below).
3. Web research (Icechunk docs, GitHub issues, an Earthmover blog post)
   plus reading the actual installed Icechunk 2.1.1 Python source
   (`.venv/.../icechunk/repository.py` — the core is a compiled Rust
   extension, but the Python binding layer's docstrings are more complete
   than the public docs) filled gaps neither the docs nor the vetting pass
   could answer alone.
4. A second Fable-model agent planned concrete fixes for the two
   surviving root causes, reading the actual current code to ground every
   recommendation in real line numbers.

## Corrections from the vetting pass (important — don't re-litigate these)

- **"Periodic spikes = network contention"** — **wrong**, walked back
  twice. First pass blamed a coincidental `disk_read_mb` sample. Second
  pass (after ruling out downloads and aux/ephemeris compute directly)
  called it "genuinely unexplained." Both wrong: the real mechanism is
  writes racing a still-draining worker pool (Problem A below), found by
  reading `pipeline.py` directly.
- **"RSS growth might be `stage_timer.py`'s `_run_stats` accumulator"** —
  refuted directly: that dict holds 3 floats per stage name, kilobytes
  not gigabytes, and `reset_run_stats()` is already called
  (`cli/run.py:552`). Real candidate found instead (Problem C below).
- **`process_data` growth is real but the mechanism was under-specified.**
  Checked `process_data_per_file.first` vs `.last` directly: no
  within-batch sawtooth (ratio ~0.7-1.0 across every decile of the run).
  Growth is a uniform, cross-run cost affecting every file regardless of
  position in its batch — global store-history growth, not "each append
  rewrites a bigger same-day manifest."

## Problem A — writes race a still-draining worker pool

**Location**: `canvodpy/src/canvodpy/orchestrator/pipeline.py`,
`_process_multi_day_batches` (~line 606).

**Mechanism**: `_loky_reusable` (line 24: `from loky import
get_reusable_executor as _loky_reusable`) is a genuinely warm/reusable
pool across the whole run — it does *not* respawn per batch. But at line
796-812, **all** tasks for a full `days_per_batch=14` batch (14 days × 4
receivers × 96 files ≈ 5,376 tasks) get `.submit()`-ed into that pool's
queue in one loop, before any results are consumed. Then `as_completed`
(line 813) streams results back; the moment a `(date, receiver)` group's
files are all accounted for (line 878), `processor._append_to_icechunk()`
fires immediately (line 900) — **inside** that same loop, while the pool
is still working through the rest of the batch's backlog for other
receiver-days.

**Evidence**: `resource_sample` shows `children_rss_gb` jumping
0.035GB → ~5.2GB and holding for several minutes exactly when writes spike
to 79-106s (vs ~19.5s median), recurring every ~14.5 days (matching
`days_per_batch=14` — worst right after a batch's pool is freshly loaded).
A 64MB disk-read burst coincides with the RSS jump. The write slowdown is
uniform across all ~96 files in the affected batch, consistent with
CPU/IO contention rather than a slow write path.

**Design constraint**: the interleaving is intentional (comment at line
815, "Streaming collection: write as groups complete") — avoids waiting
for the whole 14-day batch before writing anything. Any fix must preserve
that, not just serialize everything.

**Recommended fix**: windowed task submission with top-up. Seed the pool
with `~2×n_wrk` tasks instead of the full batch; in the completion loop,
submit one new task from the remaining backlog each time a task
completes. Requires replacing the `as_completed(future_to_meta)` pattern
(which can't grow its input set) with a manual `wait(FIRST_COMPLETED)`
loop. Preserves streaming-write behavior exactly (writes still fire the
moment a group completes) while bounding how many workers can be
concurrently active during any given write. Cheap complement: drop
`max_workers` to `n_wrk - 1`, or raise worker `nice_priority` (already a
resource-mode knob via `resolve_resources()`,
`canvod-config/.../processing_params.py:174`) so the write path always
has scheduling headroom.

## Problem B — unbounded store growth needs a retention strategy

**Location**: `packages/canvod-store/src/canvod/store/store.py` —
`dir_entry_counts()` (new, added 2026-07-15) shows `manifests` growing
linearly and unbounded (22 → 37,680 over 15.1h, no plateau).
`expire_old_snapshots()` already exists in the same file but has never
been invoked mid-backfill in production.

**Owner's framing (exact quote, must not be conflated)**: "there are two
temporal dimensions: a) write time, eg delete snapshots written older
than 2 weeks ago and b) the time associated with the data itself, eg.
delete snapshots of when the underlying data was from before June 25,
2026. we should not mix them up. i think it is sufficient to keep one
snapshot every day, week or even month per receiver."

**Verified against real Icechunk 2.1.1 docstrings** (`repository.py`,
not guessed):
- `expire_snapshots(older_than: datetime, delete_expired_branches=False,
  delete_expired_tags=False)` operates **only on `written_at`**
  (write-time). No native data-content-time expiry exists — that needs
  custom snapshot selection.
- Expiring removes a snapshot from `ancestry()` (no more time travel)
  unless a surviving tag points to it. `garbage_collect(delete_object_
  older_than=...)` is the separate step that reclaims disk space for
  objects nothing points to anymore.
- **Good news, found by reading `processor.py`**: `_append_to_icechunk`'s
  `session.commit(commit_msg, metadata=...)` (line ~2144) already
  attaches structured metadata (`receiver`, `date`/yyyydoy, `start`,
  `end`, `rinex_hashes`) to every commit. Data-time selection needs no
  commit-message parsing — just read snapshot metadata via `ancestry()`.
- `repo.create_tag()` is already wrapped (`store.py:2939`).
- **New, unused capability**: `repo.rewrite_manifests(message, *,
  branch, metadata=None, commit_method="new_commit")` consolidates all
  of an array's fragmented manifests back into the current splitting
  config in one operation. `commit_method="amend"` (spec v2 repos) can do
  this without even adding a new commit to history. Not used anywhere in
  canvodpy today. This directly targets the manifest-fragmentation
  mechanism behind Problem A's `process_data` growth cost model
  ("appending a small amount of data to a large array requires
  downloading and rewriting the entire manifest" — Icechunk's own
  performance guide) — a smaller, more surgical candidate than either
  batched writes or the pool-scheduling fix. **Not verified**: whether
  it's safe to run concurrently with an active write session. Needs a
  throwaway-store experiment before trusting it in production.

**Operational guidance found (Earthmover blog, not in the reference
docs)**: expire/GC is **not safe to run during active concurrent
writes without a large safety margin** — the cutoff timestamp must
predate the start of *any* concurrently-running write session. Hard
constraint: no more than one GC/expiration operation running at once.
Recommended cadence: expire every 1-2 months, GC every 15-30 days —
"running more frequently yields marginal storage savings and increases
operational risk." This means retention/GC should be a **separately
scheduled maintenance job**, not triggered automatically inside the
pipeline's own per-batch loop (a first plan draft suggested "every ~14
days processed," which is too frequent given this guidance, and unsafe
if multiple sites' pipelines ever run concurrently against a shared
maintenance scheduler).

**Bug found before this scheme could ship — worse than first described**:
upstream Icechunk's `expire_snapshots()` defaults are
`delete_expired_branches=False, delete_expired_tags=False` (safe) —
`store.py`'s `expire_old_snapshots()` (~line 2536-2537) actively
**overrides** these to `True, True`. Not a wrong default, an active
override of a safe upstream default. Sole caller is `maintenance()`
(store.py:3117), which just passes those defaults through.

**A second bug, found in the same review pass**: `expire_old_snapshots()`
already calls `garbage_collect()` internally (store.py:2583), and
`maintenance(run_gc=True)` calls `garbage_collect()` **again**
(store.py:3130) — GC runs twice per `maintenance()` call. Also,
`maintenance()`'s default `expire_days=7` is far below the weeks-to-months
cadence the Earthmover operational guidance recommends (see below) — as
shipped, calling `maintenance()` with its defaults would expire relatively
fresh data on a 7-day cutoff, delete the very tags a keeper scheme needs,
and run GC twice. None of this is used by the pipeline today (`maintenance()`
isn't called anywhere in the write path), but it must not ship as-is once
the retention scheme starts calling it.

**Recommended design**:
1. After each `(receiver, date)` commit, tag it
   `keep/{receiver}/{yyyydoy}` (daily granularity; a config knob could
   widen this to weekly/monthly by only tagging the last commit of a
   period).
2. **Axis (a), write-time**, run as a separate scheduled job (not inside
   the pipeline): `expire_snapshots(older_than=now - N_days,
   delete_expired_tags=False)` then `garbage_collect(delete_object_
   older_than=same_cutoff)`. Cadence per the Earthmover guidance above
   (weeks-to-months), with N_days generously larger than any realistic
   run duration.
3. **Axis (b), data-time**, a fully separate, explicit, human-triggered
   operation: enumerate `keep/*` tags via `ancestry()` metadata, delete
   tags whose `date` is before the desired data cutoff, then run (a)'s
   expire+GC. Never automatic.
4. Fix the `delete_expired_tags` default bug first — it currently
   defeats step 1 entirely.

## Problem C — RSS growth (0.3GB → ~15GB over the run, no drops)

**Confirmed mechanism**: `_process_multi_day_batches` is a generator;
`process_by_date` does `yield from self._process_multi_day_batches(...)`
(pipeline.py:1071), consumed by `Pipeline.process_range` (api.py:457).
This means **one generator frame spans the entire multi-batch run** —
every local variable survives every `yield`, for the run's full
duration, not just one batch.

Within that frame, `future_to_meta[fut] = (date_key, receiver_name)`
(line 793-804) is written but **never popped**. `concurrent.futures.
Future` objects retain their `.result()` — the full `(fname, ds, aux,
_sids)` tuple, i.e. the actual parsed dataset — after completion. So
every one of a batch's ~5,376 parsed datasets stays reachable via
`future_to_meta` for the rest of that batch's duration, even after
already being copied into `pending_results` and written to the store.
The dict *is* rebound fresh at the start of each new batch (so this
isn't an infinite multi-batch leak by itself), but it does inflate peak
per-batch memory substantially, and — since the whole generator frame
lives for the entire run — anything about pool/executor internals that
also retains completed-future state (loky's own internal bookkeeping,
not confirmed) remains an open, unverified residual candidate.

**Fix**: `future_to_meta.pop(fut)` immediately after `fut.result()` is
consumed (in the loop at line 846+), releasing the Future's reference to
its now-redundant result. Also explicitly `.clear()`
`pending_results`/`pending_aux`/`date_datasets`/`doy_contexts` at batch
end as a belt-and-suspenders measure, even though they should already be
empty by then via the existing `.pop()` calls.

**The owner's own empirical finding**: "just invoking python garbage
collector from time to time tended to make long runs more stable... costs
nothing to put and invoke." Validated as a reasonable complement, not a
substitute for the fix above: xarray/Dask objects are known to form
reference cycles that Python's refcounting alone cannot collect — only
the cycle-detecting `gc` module can, and CPython's automatic scheduling
can lag behind large-buffer workloads. Recommendation: add one
`gc.collect()` call at the end of each batch iteration (after the
`batch_complete` log line, ~line 1015) as a near-zero-cost, near-zero-risk
mitigation. It does not by itself explain the full 0.3→15GB climb — the
`pop()` fix is the substantive change; `gc.collect()` is a cheap
insurance policy on top.

## Update 2026-07-15 (later same day): answers from the actual Icechunk source

The owner checked out Icechunk's real source (Rust + Python + design docs,
not just public docs/compiled bindings) to `~/Downloads/icechunk/`. Read
directly (`design-docs/005-manifest-split.md`, `007-basic-expiration.md`,
`010-notes-towards-an-IC-2.md`, `011-ref-and-ancestry-entry-point.md`,
`011-IC2-gc-and-expiration-consistency.md`, `015-extra-data-in-manifests-
and-snapshots.md`, `016-expired-transaction-logs.md`,
`006-tag-delete.md`) — this resolves several open questions below with
actual design intent, not inference, and adds a new, more precise
candidate mechanism for the `process_data` growth in Problem A.

**New candidate for the "global, cross-run, uniform-per-file" `process_data`
cost** (refines, doesn't replace, the manifest-fragmentation story):
Icechunk 2.x ("IC2") introduced a **single `$ROOT/repo` object** holding
*all* refs (tags, branches) and *all* snapshots' metadata (id, parent
offset, timestamp, message, metadata items) in one flatbuffer, fetched
once at repository open and kept in memory
(`design-docs/011-ref-and-ancestry-entry-point.md`). Per the design doc's
own numbers: each `SnapshotInfo` costs ~256 bytes (200 of which is the
commit message), so 10k snapshots ≈ 2.5MB in memory. Explicitly stated as
a cost: **"Need to write this larger object on every commit... Overhead
on commit to write the repo object."** `MyIcechunkStore` opens exactly one
`Repository` per process (`store.py`: `self._repo =
icechunk.Repository.open(...)`, done once, reused for the run's
lifetime) — confirmed by reading `store.py` directly, not assumed — so
this isn't a per-session-open cost in our case, but the **write** cost on
every `session.commit()` scales with total accumulated snapshot count
regardless. This was **built specifically to fix** a documented IC1
problem (`010-notes-towards-an-IC-2.md`, "Slow `ancestry`" section):
"On repos with many versions, this could take minutes, because it's very
sequential" — i.e., the old architecture had exactly the O(n),
ancestry-walk-scales-with-history problem we're seeing symptoms of; IC2's
fix targets read-side ancestry speed specifically, not write-side commit
cost, which the same doc's trade-offs section still flags as a new
overhead ("Overhead on commit to write the `repo` object... more storage
overhead"). Not yet isolated from the per-append-manifest-flush cost
(doc 005) in our own telemetry — our `timings.commit` sub-metric was
small in the spike example (1.9-3.5s) and didn't show the same growth
`process_data` did, so this is unlikely to be the *dominant* driver
within a single 15h run, but is a real, confirmed, and *compounding*
cost as total snapshot count grows across a store's full multi-year
lifetime — exactly the "100+ sites, years of data" scale target.

**Correction, found in the final Fable review pass**: this "unbounded
growth" framing needs tempering. The shipped 2.1.1 `RepositoryConfig` has
`num_updates_per_repo_info_file` (default **1,000**, confirmed against
the installed package's type stubs, not just design-doc intent) — the
repo-info object is sharded into a new file every 1,000 updates, not
literally one ever-growing object for the store's entire lifetime. Lower
values shrink each write's payload at the cost of more object fetches to
reconstruct full history. This is a real, concrete, already-shipped lever
worth an experiment (tune down, re-run the same backfill, compare
`timings.commit` growth) rather than something to build — it already
exists. `RepositoryConfig.repo_update_retries` (default 100 tries, 50ms
initial backoff, 30s max) governs contention retries on this same object.

**Resolved from the original 8 open questions:**

1. **Answered.** Doc 007: tags/branches protect only what they directly
   point to (plus that snapshot's own remaining ancestry). "Update A in
   place" re-parents the oldest surviving snapshot on a ref's path
   directly to the branch root — anything not reachable from a surviving
   ref becomes unreachable. Caveat from doc 016 (a *very* recent fix,
   worth confirming it's in our installed 2.1.1): the edited snapshot's
   own transaction log becomes stale relative to its new parent unless
   `pruned_ancestor_tx_logs` support is present — affects `diff`/`rebase`/
   `amend`/`inspect` on an edited snapshot, not plain reads.
2. **Answered.** Doc 007, explicit: "During history edits... no objects
   are deleted." `expire_snapshots()` is a metadata-only "soft delete" —
   it rewrites the `repo` object (ref/ancestry metadata) but touches no
   `manifests/`/`snapshots/`/`transactions/` files. Those only shrink at
   `garbage_collect()` time.
3. **Partially answered, not fully reconciled.** Doc 011-IC2-gc-and-
   expiration-consistency.md describes a real self-protection mechanism
   the Earthmover blog didn't mention: GC computes its deletable-object
   list first, then does a conditional update; if new refs/snapshots
   appear pointing at about-to-be-deleted objects during that window, GC
   **restarts** (bounded retries) rather than corrupting anything. This
   is safer than "unsafe without a large margin" suggests — but the doc
   still assumes "some level of protection... not passing a recent
   timestamp," i.e. the generous-cutoff-margin guidance from the
   Earthmover blog remains the right operational practice, just with a
   real safety net underneath rather than pure operator discipline.
   Local-FS-specific locking behavior still unconfirmed.
4. **Resolved, cheaply.** `garbage_collect(dry_run=True)` exists and does
   exactly this — reports what would be deleted without deleting anything.
   No need to build a separate cost-model experiment; run this directly
   against the real store (still worth doing before ever running it for
   real, but the tool to answer the question already exists).
5. **Answered.** Doc 005, current (pre-split) behavior: "each commit
   needs to rewrite the full manifest" — this is the state manifest
   *splitting* fixes. Post-split, rewrite cost is scoped to the *closure*
   of the modified arrays' manifest set (all arrays sharing any manifest
   with a touched array, not literally every array in the store) — see
   the doc's closure/bin-packing algorithm. Confirms our `ChunkStrategy`
   config (`rinex_store`/`vod_store`, `epoch=17280`) is exercising a real,
   documented feature, but whether canvodpy's manifest-*set* assignment
   (which variables get packed together — `obs`, `snr`, `theta`, `phi`,
   etc.) is tuned well for our access pattern is unconfirmed and worth a
   dedicated look: if unrelated variables share a manifest set, writing
   one forces a rewrite touching all of them.
6. **Answered, risk downgraded.** The installed 2.1.1 docstring
   (`repository.py:1819`) says `rewrite_manifests()` "starts a new writable
   session on the specified branch, rewrite[s] manifests for all arrays,
   and then commits" — it's an **ordinary commit** under the hood, subject
   to ordinary conflict semantics (retry-on-conflict), not a specially
   unsafe operation. Still worth a throwaway-store timing/memory test
   before relying on it, but the risk shape is "commit conflict to
   handle," not "might corrupt something."
7. **Answered, see the new mechanism above** — yes, by design, confirmed
   via `011-ref-and-ancestry-entry-point.md`, not just local-FS
   speculation.
8. **Not resolved** — no numbers found on `create_tag()` cost at scale;
   tag deletion is logical (`006-tag-delete.md`: writes a `.deleted`
   marker, the name can never be reused) which matters for our `keep/*`
   naming scheme (don't expect to reuse a deleted keeper tag's name).

## Status

**Update 2026-07-15, later same day — Problems A, B, C implemented,
verified, vetted, fixes applied. Not committed.** Fable planned
(execution-ready, function-level), Sonnet built, a final Fable vetting
pass reviewed the actual diffs against the installed Icechunk/loky
packages (not just the plan) and found one real regression, one
telemetry nit, and confirmed everything else correct:

- **Real regression, fixed**: `_windowed_completions`'s lazy, mid-stream
  submission meant a `submit()` call could hit an *already-broken* worker
  pool directly (a worker OOM-killed mid-batch) — `loky.process_executor.
  TerminatedWorkerError` (confirmed a `BrokenProcessPool` subclass) would
  propagate straight out of the generator and crash the whole multi-batch
  run, where the old submit-all-upfront design never hit this path (all
  submission happened before any worker could have died, so failures only
  ever surfaced later via a future's `.result()`, which was already
  caught). Fixed: `_windowed_completions` now catches `BrokenProcessPool`
  around its own `submit()` calls, stops attempting further submissions
  once the pool is confirmed broken, and synthesizes an already-failed
  `Future` for every remaining task instead — so the caller's existing
  per-task `except BrokenProcessPool` handling in
  `_process_multi_day_batches` still sees exactly the shape of exception
  it already expects, one per task, not one uncaught exception that kills
  the generator. New test:
  `test_pool_broken_mid_stream_does_not_crash_the_generator` (verifies
  every task still yielded, pre-broken tasks fail cleanly via
  `fut.result()`, and `submit()` is not called again after the pool is
  known broken).
- **Telemetry nit, fixed**: the `phase2_loky_submitted` log event
  reported `tasks_submitted`/`submit_seconds` as if submission were still
  synchronous and upfront — misleading once submission is lazy and spread
  across the batch. Renamed to `phase2_windowed_scheduling_started` with
  `tasks_to_submit`/`setup_seconds`, and a comment explaining why. No
  other code depends on the old event/field names (checked).
- **Minor UX nit, fixed**: `canvodpy store maintain`'s dry-run path
  showed the garbage-collect report even when `--no-gc` was passed.
  Gated behind the flag now.
- **Confirmed correct by the vetting pass** (not just re-asserted, each
  spot-checked against real code/behavior): windowing preserves
  write-on-group-complete semantics exactly; the `_pool` closure-capture
  fix is correct across batch iterations; `gc.collect()` fires once per
  batch end, not mid-yield; `expire_old_snapshots()` genuinely no longer
  calls GC internally and `maintenance()` genuinely calls it exactly
  once (traced, not assumed); `create_keeper_tag()`'s
  `except icechunk.IcechunkError` is verified correct for both
  duplicate-tag and reuse-after-deletion cases (tested live against the
  installed package); the mocked `test_store_maintenance.py` assertions
  are meaningful, not mock-shape false positives; `StorageConfig` is
  `extra="forbid"` but `keeper_tags` has a default so old YAML still
  loads; every SKILL.md claim spot-checked matches installed 2.1.1.
- **Noted, not fixed (pre-existing, unrelated)**: the `demo` submodule
  has local modifications and `dev/quick_view.py` is an untracked scratch
  script — neither was touched by or is related to this work.

Re-verified after the fix: `ruff`/`ty` clean, fast suite 1808/1808 (was
1807, +1 for the new broken-pool test), audit suite 60/60.

- **Problem A (windowed pool submission)**: `pipeline.py` — new
  `_windowed_completions()` generator (seeds `2×n_wrk` tasks, tops up one
  per completion via `concurrent.futures.wait(FIRST_COMPLETED)`, replaces
  the submit-all-then-`as_completed()` pattern). Streaming-write behavior
  unchanged. New tests: `canvodpy/tests/test_pipeline_windowed.py` (5
  tests, concurrency-bounding + exception passthrough + edge cases).
- **Problem C (RSS fix)**: satisfied structurally by A's rewrite — the
  `future_to_meta` dict that retained completed futures no longer exists;
  `_windowed_completions` pops each future before yielding it. Added
  belt-and-suspenders `.clear()` on all per-batch accumulator dicts plus
  `gc.collect()` at both the normal and early-exit end of each batch.
- **Problem B (retention capability + 2 bug fixes)**: `store.py` —
  `expire_old_snapshots()` no longer overrides Icechunk's safe
  `False`/`False` defaults to `True`/`True`, no longer runs GC internally
  (was double-GC bug source), default `days` 30→90. New
  `garbage_collect()` wrapper (thin, with `dry_run` support).
  `maintenance()` now runs GC exactly once, default `expire_days` 7→90,
  passes through `dry_run_gc`/delete-flag params. New `create_keeper_tag()`
  (tags `keep/{receiver}/{yyyydoy}`, swallows name collisions, never fails
  a write). New `StorageConfig.keeper_tags` field (default `False`).
  Orchestrator hook in `processor.py::_append_to_icechunk` (additive,
  inert unless `keeper_tags=True`). New CLI command `canvodpy store
  maintain <site>` — **defaults to dry-run** (garbage-collect report +
  stale-ancestry count, deletes nothing), `--execute` requires interactive
  confirmation. New tests: `packages/canvod-store/tests/
  test_store_maintenance.py` (11 tests — regression locks on both bugs'
  exact defaults/call-counts) + 3 new cases in `canvodpy/tests/
  test_cli_store.py` (dry-run-deletes-nothing, execute-abort,
  execute-confirm).
- **Explicitly not built**: no automatic/scheduled invocation of
  expiration/GC/`maintain` anywhere — `keeper_tags` ships off by default,
  `maintain` ships dry-run-by-default. `rewrite_manifests()` remains
  unused (out of scope per the plan — unverified concurrency safety).

**Verified**: `ruff check` clean on every touched file; `ty check`
(whole project) clean; fast suite 1807/1807 passed (was 1788, +19 new
tests); audit suite 60/60 passed; `just test-package canvod-store`
122/122; `just test-package canvod-config` 81/81 (+8 skipped,
pre-existing/unrelated). Nothing committed — left in the working tree.

`dev/todo_later.md` §34 points here; its Action line reflects this
update. The two earlier-shipped fixes from the same investigation (dedup
single-load + vectorized overlap join, dashboard glob + backupCount
bumps) are described in §34 and §37 respectively, not repeated here.

**Separately shipped today**: `.claude/skills/icechunk/SKILL.md` was
rewritten using everything learned in this investigation — added a full
"Maintenance: Expiration & Garbage Collection" section, `rewrite_manifests()`
documentation, a "Write Cost Model" section (both mechanisms described
above, in skill form), and fixed 6 factual errors the previous version had
against the actual installed 2.1.1 API (`set_max_concurrent_requests`
doesn't exist as a module function, `unsafe_overwrite_refs` was removed,
`CachingConfig` field names and defaults were wrong — caching is mostly
**on** by default, not off, compression level default is 3 not 5,
`StorageConcurrency` should be `StorageConcurrencySettings`, `azure_storage`
needs `account=`). Every added claim was verified against the installed
package's type stubs or live introspection, not taken from the design
docs' stated intent alone (intent and shipped behavior sometimes differ,
e.g. `num_updates_per_repo_info_file` above).

Remaining unresolved before Problem B's retention scheme is safe to build:
open question 8 (`create_tag()` cost at ~1,460 tags/year/site scale) and
an empirical `garbage_collect(dry_run=True)` run against the real store
(the tool exists, per question 4 above — it just hasn't been run).
