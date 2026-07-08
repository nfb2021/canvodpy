# Multi-Site CLI + Per-Site/Receiver Progress — Plan

Written 2026-07-08, following the tmux/batching investigation on the remote
processing machine. Confirmed there: the "Overall" days-processed bar was
architecturally correct but blind to per-receiver detail, and the old
per-receiver bars (disabled to fix a dueling-`Live` bug) were the only
mechanism giving real-time feedback during a `days_per_batch`-sized batch.
Rather than just restoring those, the user wants a redesign: **`canvodpy run`
should accept multiple `--site` values in one invocation, and the progress
display should show one row per (site, receiver-group) — no aggregate
"Overall" bar at all.**

Confirmed via `AskUserQuestion`: multi-site is a real CLI capability to add
(not just a labeling change), and the per-receiver rows should **replace** the
aggregate bar entirely, not sit alongside it.

## Part A — `--site` accepts multiple values

**Current state** (`canvodpy/src/canvodpy/cli/run.py:_build_parser`):
```python
p.add_argument("--site", required=True, help="Site name as defined in sites.yaml (e.g. Rosalia)")
```
Single required string.

**Change:** `nargs="+"` so `--site Rosalia` (still works, list of one) and
`--site Rosalia OtherSite ThirdSite` both work.
```python
p.add_argument(
    "--site",
    required=True,
    nargs="+",
    metavar="SITE",
    help="One or more site names as defined in sites.yaml (e.g. Rosalia)",
)
```

**Orchestration in `main()`:** loop over sites **sequentially** — each site
gets its own `Site(name)`, its own `_resolve_date_range()` call (each site's
store may have a different last-processed date — this is genuinely per-site
state, can't share one `start`/`end` resolution), and its own
`site.pipeline(...)`/`process_range()` call. Sequential, not concurrent,
because:
- Each `PipelineOrchestrator` already owns a resource-mode-driven worker count
  (`n_max_workers`/`resolve_resources()`); running N sites' orchestrators
  concurrently would contend for the same CPU/memory budget in ways the
  current resource-mode logic doesn't account for.
- Concurrent sites writing to *different* Icechunk stores isn't inherently
  unsafe (different stores, no shared-write conflict), but the loky pool is a
  process-global singleton (`get_reusable_executor()` — see
  `parallelization_benchmark.md` memory) — two sites submitting to it
  concurrently would need careful worker-budget splitting that doesn't exist
  yet. Out of scope for this change; sequential is the safe default.
- `--dry-run` and `--no-vod` apply uniformly across all sites in the list (no
  per-site override needed for v1 — if a per-site override is wanted later,
  that's a separate, additive change).

`--config` (overlay YAML) applies once, globally, before the site loop starts
(unchanged from today).

## Part B — Per-(site, receiver-group) progress display, no aggregate bar

**Remove:** `RichReporter`'s single "Overall" `Progress` task
(`cli/dashboard.py:146-159, 193, 217-220`) entirely — no more aggregate bar,
per the user's explicit choice.

**Add:** one `Progress` row per `(site, receiver_group)` pair, known **upfront**
by enumerating each site's groups before any processing starts:
```python
canopy_names = [
    name for name, cfg in site.active_receivers.items() if cfg["type"] == "canopy"
]
pair_names = [
    f"{ref}_{canopy}"
    for ref, canopy in site._site.get_reference_canopy_pairs()
]
groups = canopy_names + pair_names
```
(`GnssResearchSite.active_receivers` — `packages/canvod-store/src/canvod/store/manager.py:110`;
`get_reference_canopy_pairs()` — same file, `:199`, delegates to
`SiteConfig.get_reference_canopy_pairs()` in
`packages/canvod-utils/src/canvod/utils/config/models.py:1031`.)

Each row's `total` = that site's resolved date-range length (from
`_resolve_date_range()`, per-site). Row label: `f"{site_name}/{group}"`.

**Wiring the advance callback.** The actual "a receiver-group-day finished
writing" event already exists — it's exactly where the old per-receiver bar
used to advance, `pipeline.py:933-935`:
```python
if receiver_name in receiver_tasks:
    progress.advance(receiver_tasks[receiver_name])
```
That `progress`/`receiver_tasks` pair is currently owned *inside*
`_process_multi_day_batches` (created fresh per `PipelineOrchestrator`
instance, i.e. per site). For a shared, CLI-owned, multi-site display, this
needs to become a callback the CLI injects, not a `Progress` object the
orchestrator constructs itself:

1. `PipelineOrchestrator.__init__` gains `on_group_written:
   Callable[[str, str], None] | None = None` (site name + receiver-group
   name), replacing `show_progress: bool` — a callback is more flexible than a
   bool (bool only supports "some generic bar, or none"; a callback lets the
   caller route the event anywhere, e.g. into a shared multi-site table row).
   `show_progress` added in the earlier fix gets removed/superseded here.
2. `_process_multi_day_batches`'s inner loop calls
   `self._on_group_written(self.site.site_name, receiver_name)` if set,
   instead of maintaining its own `_processing_progress()`/`receiver_tasks`
   dict. The internal per-receiver `Progress` construction
   (`pipeline.py:619-626`) goes away entirely — no orchestrator-owned display
   at all, just an event hook.
3. Thread `on_group_written` through `Pipeline.__init__` and
   `Site.pipeline()` the same way `show_progress` was threaded (same 3-layer
   pattern, same files: `api.py`, `orchestrator/pipeline.py`).
4. `cli/run.py`'s multi-site loop constructs ONE shared `Progress` + task-ID
   map (`{(site_name, group): TaskID}`) before the loop starts, wrapped in
   ONE `Live` (reusing `RichReporter`'s existing `Console`/`Live` ownership —
   `RichReporter` becomes the owner of this per-(site,receiver) `Progress`
   instead of the old single-task one). Passes a closure
   `lambda s, g: shared_progress.advance(task_ids[(s, g)])` as
   `on_group_written=...` into each site's `site.pipeline(...)` call.

**What stays:** the plain per-day console log lines (`on_datasets`,
`on_vod_result`, `on_timing`, the `─── {date_key}` markers) continue to print
via `console.print()` against the same shared console — Rich's `Live`
supports interleaved `console.print()` calls above the live region already
(this is how the current header-panel + progress combination already works
without conflict). These lines will need a `site=` prefix or similar since
output now spans multiple sites in one run.

**Row lifecycle:** rows for a finished site should stay visible (not
collapse/disappear) so the final tally for completed sites remains readable
while later sites are still running — matches "one persistent bar per
receiver spanning ALL dates" comment already in the current code
(`pipeline.py:618`), just extended across sites too.

## Testing / verification

- `uv run canvodpy run --site Rosalia --dry-run` — single-site form still
  works unchanged.
- `uv run canvodpy run --site SiteA SiteB --dry-run` — multi-site parses,
  both previews print.
- Live run against real/fixture data with 2 sites × mixed receiver counts —
  confirm rows appear for every (site, group) pair upfront, advance
  independently and correctly as each group's days complete, no dueling
  `Live` (only one `Live` instance for the whole run, same as the earlier
  fix), no flashing under `tmux` specifically (the environment where this was
  originally noticed).
- `uv run ty check` on all touched files; `uv run pytest -m "not integration"
  -q --no-cov` matches baseline.

## Open questions before implementing

1. Should there still be a "current site" text indicator (e.g. a header
   line), given there's no more aggregate bar to attach that context to? Or
   is the per-row `site/group` label sufficient on its own?
2. VOD analysis names also vary per site (`site.vod_analyses`) — do
   `on_vod_result`/`on_vod_failed` log lines need a site prefix too, or is
   the preceding `─── {date_key}` marker (which could also gain a site
   prefix) enough context?
3. Any cap on total rows for very large multi-site runs (many sites × many
   receivers)? Rich `Progress` can scroll, but a huge row count may need a
   "collapse finished sites to a single summary line" behavior later — not
   needed for v1, flagging so it isn't forgotten.
