# CLI Integration: VOD Rollup (canvod-streamviz) + Statistics (canvod-streamstats)

!!! note "Status: prerequisites done, architecture mostly decided, one open question, CLI work not started"
    Investigation and design complete. All prerequisite fixes (bugs, the
    `canvod.ops.statistics` packaging gap, `bootstrap_site_store()`,
    `rollup_store_name` config field) are done — see "Prerequisite fixes"
    below. Rollup store architecture points 1-3 (separate store,
    aggregates-only, dual-store serving) are decided; point 4 (temporal
    resolution: 1min×2° as the retained-forever download baseline, hourly
    as a derived visualization view) is decided in shape but has **one open
    question blocking implementation**: whether the per-signal-group
    breakdown is kept at full 1min resolution forever (~1-3 TB/year/pair/site)
    or only at coarser day/week levels — see "Rollup store architecture" §4
    for the numbers. Nothing here is implemented yet: this is all still
    design — the `--rollup`/`--stats` CLI flags (§5), the rework of
    `run_pipeline_for_pair`'s rebuild paths, and wiring grid assignment into
    the live orchestrator are all future work, gated on the open question
    above and the other open questions below.

## Goal

Run `uv run python -m canvodpy.cli.run --site X ...` (the canvodpy public
CLI, `canvodpy/src/canvodpy/cli/run.py`) with new flags that, after VOD is
computed for each day, also (a) roll up VOD into the spatial hemigrid
aggregates that back the canvod-streamviz visualization server, and
(b) feed observations into the canvod-streamstats streaming statistics /
climatology / anomaly / changepoint accumulators.

Three repos are involved:

- `canvodpy` (public monorepo) — the CLI itself.
- `canvod-streamviz` (private, standalone, `canvod.streamviz`) — spatial
  hemigrid VOD rollups (day/week/hour, Welford moments per
  constellation\|band\|code triplet) backing a FastAPI/xpublish viz server.
- `canvod-streamstats` (private, standalone, `canvod.streamstats` +
  an `integration/` folder) — streaming accumulators (Welford, GK-sketch,
  histograms, EWMA, BOCPD, climatology grids, anomaly z-scores) plus a
  full parallel Airflow DAG (`dags/gnss_daily_processing.py`) that already
  wires `update_statistics → update_climatology → {detect_anomalies,
  detect_changepoints} → snapshot_statistics` — but has **zero** references
  to streamviz or rollup. The spatial rollup pipeline is not wired into
  anything today.

---

## 1. canvod-streamviz TODO list — verified against current code

The 4-day-old memory list traces to `canvod-streamviz/TODO.md`. Status:

| TODO | Status | Evidence |
|---|---|---|
| `zarr_plugin.py` route dispatch | **Still open, likely broken** | `serve/zarr_plugin.py:56-87` has two real routes but both call `store.get(path)` synchronously on an icechunk session store — zarr-v3/icechunk `.get()` is async, so this returns a coroutine, not bytes. Explicitly disabled in tests (`tests/test_serve.py:33`, `enable_zarr_plugin=False`). |
| Synthetic CI fixture needs mock grid | **Resolved, TODO.md stale** | `tests/conftest.py:1-11,63` builds the UGRID mesh from scratch with lazy GNSS-package imports and a numpy Welford stub. |
| Hour-level rollup not wired | **Resolved, TODO.md stale** | `pipeline.py:256-264` and `:333-341` both call `append_hour_bins`; `serve/router.py:60-68,107-112` reads the hour level. Residual: constellation filtering unsupported at hour level (`router.py:126-128`). |
| WebGL renderer | **Open** (Phase 3) | No frontend code; notebook still Plotly-based. |
| Multi-site catalog UI | **Open** (Phase 2) | `serve/` has API only, no UI; S3/GCS catalog backends still `NotImplementedError` (`catalog.py:215-224`). |

**Newly found issues relevant to this integration:**

- **Latent crash bug**: `ingest.py:164` reads `vod_flat["vod"]` but
  `TauOmegaZerothOrder.calculate_vod()` names the variable `"VOD"`
  (uppercase) — `packages/canvod-vod/src/canvod/vod/calculator.py:231-239`.
  Outside the try/except at `ingest.py:155-160`, so `extract_pair_obs`
  would raise `KeyError: 'vod'` on first real use. This path has
  apparently never run against the current canvod-vod API.
- **`import canvod.streamviz` hard-requires FastAPI**: `__init__.py`
  unconditionally does `from canvod.streamviz.serve.app import make_app`,
  which imports `fastapi` at module level. Even a bare
  `from canvod.streamviz.ingest import extract_pair_obs` fails unless the
  `serve` extra is installed.
- `extract_pair_obs` is not re-exported from `canvod.streamviz.__init__`.
- streamviz's `pyproject.toml` declares no canvod-* dependencies — grids,
  store, vod, streamstats are all expected as manual editable installs.

---

## 2. The redundant-computation problem — avoidable

The canvodpy CLI already computes `vod_ds` in memory in
`_compute_vod_for_day` (`cli/run.py:243-247`) with `VOD`, `delta_snr`,
`phi`, `theta` all present (`calculator.py:231-239`) — exactly what
`_assign_cells_safe` (`ingest.py:39-74`) needs for grid-cell assignment.

But `streamviz.ingest.extract_pair_obs` independently re-opens both obs
groups from icechunk readonly sessions and **recomputes VOD from
scratch** — a full duplicate of work the CLI already did.

`cell_id` assignment itself is genuinely new work either way — nothing in
the canvodpy CLI path computes it today (zero `GridAssignment`/`cell_id`
references in `orchestrator/processor.py` or `orchestrator/pipeline.py`).
Only the VOD recomputation and store re-reads are redundant, not the grid
assignment.

**Recommendation**: add a new streamviz function,
`extract_pair_obs_from_vod(vod_ds, pair_id, grid, *, theta_max_deg=90.0,
vod_min=-50.0, vod_max=50.0)` — literally the flatten/filter/assign tail
of `extract_pair_obs` (`ingest.py:162-214`) minus the store-read and
VOD-recompute head. This also fixes the `"vod"`/`"VOD"` bug by writing the
correct key once, in the new function.

Two caveats:
- The CLI's `vod_ds` may still be a lazy dask graph at this point
  (`process_range` yields Zarr-backed datasets, `cli/run.py:345-347`);
  using it directly means the rollup path re-triggers that day's cheap
  compute. Alternative: read the day back from the **VOD store** instead
  (already committed with `VOD`/`phi`/`theta` via `store_vod_analysis` →
  `write_or_append_group`, `canvod-store/.../manager.py:404-440`) for a
  zero-recompute single-group read. Negligible either way for one day of
  data — in-memory is architecturally simpler (no post-commit dependency).
- `_assign_cells_safe` builds a fresh KDTree per call (`ingest.py:69`).
  Build the hemigrid + KDTree once before the day loop, not per day.

Idempotency in `run_pipeline_for_pair` keys on the rollup store's own
commits (`pipeline.py:156-182`), not canvodpy store commits, so feeding
in-memory obs is safe.

**Grid consistency**: the assignment grid must match the catalog's
`grid_res_deg`/`ncells` (`catalog.py:58-59`) and the mesh in the rollup
store's `grid` group (read back at `pipeline.py:199-205`). canvodpy's
`GridAssignmentConfig.angular_resolution` defaults to 2.0
(`canvod-utils/config/models.py:574-581`), matching `SiteEntry.grid_res_deg
= 2.0` — should be asserted at runtime, not assumed.

---

## 3. Public/private package boundary

canvodpy is public; canvod-streamviz and canvod-streamstats are private,
local-install-only. A public CLI file cannot hard-import them.

**Existing precedent for optional imports in canvodpy:**
- Factory auto-registration wraps every component import in
  `try/except ImportError` (`canvodpy/__init__.py:250-305`).
- `FluentWorkflow` lazily imports `canvod.virtualiconvname` with an
  `except ImportError` fallback (`fluent.py:220,304`).
- `orchestrator/resources.py:186` raises a clear `ImportError` with an
  install hint when an optional feature is actually requested — the right
  model to copy.
- streamviz itself already treats canvod-streamstats as optional with a
  numpy fallback (`rollup.py:52-64`).

**Proposed pattern**: no top-level imports in `cli/run.py`; each flag
(`--rollup`, `--stats`) triggers a lazy import in a small setup helper,
validated immediately after `parser.parse_args()` (before the (possibly
hours-long) day loop starts) with a clear install-hint error and exit
code 2 on failure.

**Two blockers pure lazy-importing cannot solve:**

1. ✅ **Resolved** — `canvod.ops.statistics` did not exist as an
   installable module (only the never-installed
   `integration/canvod-ops-statistics/` folder). Fixed by option (b):
   `op/profile/query/store` now live at `src/canvod/streamstats/ops/` in
   canvod-streamstats, a real importable subpackage requiring only the
   public `canvod.ops.base.Op`. `import canvod.streamstats` alone still
   needs no canvod-ops; `import canvod.streamstats.ops` does (documented
   in canvod-streamstats' `pyproject.toml`). See "Prerequisite fixes"
   below for details.
2. **Still open** — `integration.workflows.tasks` is not an installed
   package; the Airflow DAG assumes the streamstats repo root is on
   `sys.path` (`dags/gnss_daily_processing.py:36`). The CLI must not
   import it directly. Now that blocker 1 is resolved, the task-5–9
   sequence (~100 lines of orchestration around importable primitives,
   now cleanly available via `canvod.streamstats.ops`) should be thinly
   reimplemented in canvodpy rather than imported — this is CLI
   implementation work, not a prerequisite bug fix.
3. (From §1) `import canvod.streamviz` requires fastapi — fix by making
   `make_app` a lazy attribute or moving the import into a function.

---

## 4. Config / bootstrapping requirements

**streamstats — config already fully exists in the public repo:**
- `StatisticsConfig` (`enabled` default `False`, `variables`,
  `gk_epsilon`, `quantile_probs`, `custom_histogram_bins`) —
  `canvod-utils/config/models.py:592-622`, wired as
  `PreprocessingConfig.statistics` (`:634-636`).
- `StorageConfig.get_statistics_store_path(site)` —
  `models.py:480-493`, already used by `canvod-utils/config/cli.py`.
- Store bootstrap is trivial (`zarr.open_group(path, mode="a")`
  auto-creates); every stage is independently idempotent via
  `stats_store.is_*_range_processed(...)`.

**streamviz — canvodpy config gets most of the way there, but not all:**
- `SiteEntry` needs `site_id`, `name`, `location`, `store_uri`,
  `grid_res_deg`, `ncells`, `pairs[...]` (`catalog.py:52-62`). Derivable
  from `SiteConfig.{latitude,longitude,altitude_m,description,country,
  receivers,vod_analyses}` (`models.py:763-771`); `pair_id` =
  `vod_analyses` key; `can_group`/`sky_group` match the CLI's own group
  naming convention (`cli/run.py:219`).
- **Missing config field**: no rollup-store path exists anywhere in
  canvodpy config. Add a symmetric `StorageConfig.rollup_store_name` +
  `get_rollup_store_path(site)`, mirroring the existing
  `get_statistics_store_path`.
- **The catalog must persist, not just be synthesized** —
  `run_pipeline_for_pair` mutates `pair_entry.t_start/t_end/n_obs/
  last_obs_commit/last_rollup_commit` (`pipeline.py:346-354`); the caller
  must `backend.save(doc)` (`:430-431`), and idempotency checks read these
  back (`:156-182`). Auto-bootstrap `catalog.json` at a deterministic path
  (e.g. `{stores_root}/{site}/streamviz/catalog.json`) on first `--rollup`
  run, synthesizing the `SiteEntry` from `SiteConfig` (shape shown in
  `_cli_add_site`, `catalog.py:266-309`), with an optional
  `--rollup-catalog PATH` override for pre-provisioned setups.
- **The rollup store must be pre-initialized, and nothing currently
  builds it.** `_append_obs_to_store` raises `ValueError` if a pair group
  doesn't exist yet (`pipeline.py:102-107`); the docstring's suggested
  fix (`build_rollups_for_site` first) doesn't actually create obs pair
  groups either — it only reads them (`rollup.py:607-614`). The only
  existing template for full init is the test fixture
  (`tests/conftest.py:270-327`). **A `bootstrap_site_store(repo, grid_ds,
  pairs)` helper is required new code in streamviz.**

---

## 5. Concrete design proposal

**Two flags, not one** — different private packages, different failure
modes, different data sources (rollup consumes VOD; stats consumes raw
receiver SNR and can run even with `--no-vod`):

- `--rollup` — streamviz spatial rollup ingest.
- `--stats` — streamstats statistics/climatology/anomaly chain.
- `--rollup-catalog PATH` (optional, override auto-bootstrapped catalog)
- `--rollup-retention-days N` (optional, passthrough to `append_hour_bins`,
  default 30)
- Reject `--rollup` + `--no-vod` at parse time (rollup needs VOD results).

**Startup** (after `_print_header`, before the day loop):
1. If `--rollup`: lazy-import streamviz; load/bootstrap catalog +
   `SiteEntry`; `open_site_repo(site_entry)`, bootstrapping the store
   (grid + pair groups) if absent; build the hemigrid + KDTree once.
2. If `--stats`: lazy-import `canvod.ops.statistics` + `canvod.streamstats`;
   check `config.processing.preprocessing.statistics.enabled`.
3. Any `ImportError` → clear install-hint message, exit 2.

**Per-day placement**, immediately after `vod_results = _compute_vod_for_day(...)`
(`cli/run.py:349-352`):

```python
if rollup_ctx and vod_results:
    for analysis_name, vod_ds in vod_results.items():
        new_obs = extract_pair_obs_from_vod(
            vod_ds, pair_id=analysis_name, grid=rollup_ctx.grid,
        )
        run_pipeline_for_pair(
            rollup_ctx.repo, rollup_ctx.site_entry, analysis_name, new_obs,
            retention_days=args.rollup_retention_days,
        )
    rollup_ctx.catalog.save(rollup_ctx.doc)

if stats_ctx:
    _run_stats_chain(args.site, date_key)  # thin glue reimplementing tasks 5-9
```

Wrap each in try/except (mirroring `_compute_vod_for_day`'s per-analysis
error handling, `cli/run.py:273-280`) so a rollup/stats failure never
aborts ingestion; count failures in the final summary line.

**Stats chain granularity**: run the full 5-stage chain
(`update_statistics → update_climatology → {detect_anomalies,
detect_changepoints} → snapshot_statistics`) under the single `--stats`
flag, sequentially. Every stage is independently idempotent, each is
cheap relative to ingest, and `snapshot_statistics` exists precisely to
verify the whole set ran. The DAG's anomaly/changepoint parallelism is an
Airflow scheduling nicety, not a data dependency — splitting into
per-stage CLI flags buys nothing and multiplies UX surface.

**Note on stats redundant reads**: `update_statistics` reads the day back
via `research_site.read_receiver_data()` + `build_default_pipeline()` for
`cell_id_*` coords (`tasks.py:1484-1520`) — a redundant store read since
the CLI just wrote this data. Refactoring it to accept the in-memory
`datasets` dict would change its idempotency bookkeeping; recommend
deferring that optimization to a later pass.

---

## Prerequisite fixes (in the private repos, before CLI work starts)

**canvod-streamviz:**
1. ✅ **Fixed** `"vod"` → `"VOD"` in `ingest.py:164` — was reading the
   wrong (never-existed) key, would `KeyError` on first real use.
2. ✅ **Fixed** the `zarr_plugin.py` async/sync bug — routes now
   `async def`, `store.get()` is awaited with a required `prototype=`
   arg, and `Buffer.to_bytes()` replaces the invalid `bytes(buffer)` call.
   Also fixed the exception type: icechunk raises `icechunk.IcechunkError`
   for malformed/missing keys, not `KeyError` — the old `except KeyError`
   never caught it, so a bad path leaked a 500 instead of returning 404.
   Verified end-to-end with a real icechunk store + FastAPI TestClient
   (zarr.json, array metadata, chunk bytes, and 404-on-missing-key all
   confirmed working).
3. ✅ **Fixed** the `fastapi`/`make_app` import — `__init__.py` now uses
   a PEP 562 module `__getattr__` to import `serve.app.make_app` lazily,
   so `import canvod.streamviz` (and `extract_pair_obs`) no longer
   requires fastapi/xpublish installed. Verified: bare import succeeds
   without the `[serve]` extra; `make_app` still resolves correctly (and
   fails with a clear `ModuleNotFoundError` if fastapi is genuinely
   missing) when actually accessed.
4. ✅ **Done as part of #3** — `extract_pair_obs` now exported from
   `__init__.py`.
5. ✅ **Done** — `bootstrap_site_store(site, grid, initial_obs, levels=...)`
   added to `pipeline.py`. Writes the `grid` mesh group and one obs group
   per `site.pairs` (real data, or an empty placeholder with an explicit
   `<U16` sid dtype + ns-since-epoch `epoch` encoding for pairs with no
   history yet) in one commit, then builds day/week rollups for whichever
   pairs had data. Exposed from `__init__.py`. Building it surfaced two
   pre-existing bugs in the self-heal path it depends on, both fixed:
   `zarr.open_group()` defaults to `mode="a"`, which silently
   auto-creates a missing group instead of raising — so the
   existence-check guards in `_check_temporal_overlap`,
   `_append_obs_to_store`, and `append_rollup_slice` never actually fired.
   Fixed by checking with `mode="r"` (paired with a second default-mode
   open for the actual write, since read-only handles reject appends).
   Verified end-to-end: a pair with data gets working rollups
   immediately; a pair with no data gets a placeholder and self-heals
   into a working rollup on its first real append. Full suite still
   38/41 (same 3 pre-existing unrelated failures).
   **Note**: every write in this function uses `to_zarr(mode="w")`, safe
   only because `Repository.create()` guarantees a clean prefix — do not
   reuse this pattern to add a pair to an *already-bootstrapped* site.

**canvod-streamstats:**
6. ✅ **Resolved** the `canvod.ops.statistics` packaging gap (§3, blocker 1).
   Given canvod-streamstats stays private/no-PyPI (confirmed), the fix was
   to relocate `op.py`, `profile.py`, `query.py`, `store.py` from the
   never-installable `integration/canvod-ops-statistics/` folder into a
   real subpackage, `src/canvod/streamstats/ops/`, with a proper
   `__init__.py`. Internal cross-imports rewritten from
   `canvod.ops.statistics.X` → `canvod.streamstats.ops.X`; `op.py`'s only
   remaining external dependency is the public `canvod.ops.base.Op`
   (unchanged). Updated all 5 import sites in
   `integration/workflows/tasks.py` accordingly. Moved the matching tests
   from the uncollected `integration/canvod-ops-tests/` into the package's
   real `tests/` dir (`test_ops_*.py`) so they actually run under
   `uv run pytest`; fixed one test that literally asserted the old
   (never-working) `from canvod.ops import ...` path. `canvod.streamstats`
   (plain accumulators) still imports with zero canvod-ops dependency;
   `canvod.streamstats.ops` requires `canvod-ops` installed (documented in
   `pyproject.toml`, matching the streamviz optional-dependency pattern).
   Verified cross-repo: both import paths resolve correctly, and 484/489
   tests pass (the 5 failures are pre-existing, unrelated — a missing
   optional `EMD-signal` extra).

**canvodpy (small, low-risk, can go first):**
7. ✅ **Done** — Added `StorageConfig.rollup_store_name` (default
   `"rollup"`) + `get_rollup_store_path(site_name)` to `canvod-config`,
   mirroring `vod_store_name`/`get_vod_store_path`. Test added
   (`TestStorageConfig.test_store_paths`); 5/5 pass.

---

## Rollup store architecture (decided 2026-07-10)

Two questions, entangled: where does the rollup store live relative to the
VOD store, and does it hold a persistent copy of raw per-obs data or only
derived aggregates? Both decided; see §2 for the redundant-VOD-computation
context these connect to.

**1. Separate icechunk repo, not a branch inside the VOD store.** Icechunk
branches represent alternate versions of *the same* dataset (dev vs. main),
not two different derived products with different lifecycles. The rollup
store is small, public-facing, and cheap to query; the VOD store is the
large scientific record. Separate repos let each be tuned independently
(chunking, compression, retention, eventual access policy) without coupling
their lifecycles. Cross-store provenance is already solved —
`built_from_commit`/`last_obs_commit` (`pipeline.py`, `rollup.py`) pin a
rollup to a specific VOD-store commit, the same idea as a git submodule pin.

**2. The rollup store should hold only derived aggregates (mesh + rollup
groups), not a persistent copy of raw per-obs VOD data.** Today's
`bootstrap_site_store`/`_append_obs_to_store` write a full per-pair obs copy
(`vod`, `epoch`, `cell_id`, `sid`) into the rollup store, because
`run_pipeline_for_pair`'s rebuild paths (late data, force-rebuild, the
always-rebuilt week level) currently re-read *that copy*, not the VOD store.
Combined with §2's finding that `streamviz.ingest.extract_pair_obs`
independently recomputes VOD from the raw canopy/reference stores instead of
reading the already-computed VOD store, this means there are currently two
independent VOD computations and two copies of the data. Target design:
rebuild paths re-read historical VOD directly from the VOD store instead of
a redundant rollup-store copy; per-day ingest uses the CLI's already-computed
in-memory `vod_ds` (§2's `extract_pair_obs_from_vod` proposal) instead of
recomputing. Once `grid_assignment.angular_resolution` is wired into the
live VOD-ingest path (see the TODO comment now in
`config/canvod-settings.yaml[.example]` — currently unwired, confirmed via
grep) and `cell_id` is written as a VOD-store coordinate at VOD-computation
time, the rollup ingest step can drop its own KDTree re-derivation too: one
VOD computation, one grid assignment, upstream, done once. **Not yet
implemented** — this is a rework of `run_pipeline_for_pair`'s rebuild
branches plus (later, separately) wiring grid assignment into the live
orchestrator, which touches a guardrail-adjacent area (coordinate
transforms) and needs the audit suite run after.

**3. Serving/download: both stores, for different products, not
either/or.** Icechunk's snapshot isolation means reading a frequently-written
store is never a correctness problem — `readonly_session()` always sees a
consistent snapshot regardless of concurrent writers (already the pattern in
`zarr_plugin.py`'s `_open_store()`). The real cost of hitting the VOD store
directly is query size (full-resolution per-obs reads), not contention. So:
dashboard/summary downloads (time series at a cell, climatology, anomalies)
→ rollup store, cheap, already what `zarr_plugin.py` serves at
`/zarr/{station}/rollup/...`. Full-fidelity/reprocessing downloads (raw VOD
observations for a site/date range) → VOD store directly, read-only, via a
second xpublish mount (e.g. `/zarr/{station}/raw/...`) — not yet built.

**4. Temporal resolution: 1min×2° is the retained download baseline;
hourly is a derived visualization view, not its own retention tier
(clarified 2026-07-10, corrects an earlier misreading of this as a
retention-window question).** Initial framing in this doc treated finer-
than-day temporal resolution as a bounded, rolling-window cache (mirroring
`append_hour_bins`'s existing 30-day-retention design) — wrong shape. The
actual requirement: the finest level (driven by
`PreprocessingConfig.preprocessing.temporal_aggregation.freq`, default
`"1min"`) is the thing users download, and it must be kept **forever**,
never trimmed. Hourly (what the dashboard currently renders) doesn't need
its own persisted, retention-managed tier at all — it's a coarser slice
over the same cumulative data.

Mechanism implication: `append_hour_bins`'s rolling-window/non-cumulative
design (raw per-bin sums, explicitly built to be trimmed) is the wrong
shape for a "keep forever" level. The finest level should use the *same*
cumulative-prefix-sum pattern `rollup_for_pair` already uses for day/week
(`cum_count`/`cum_sum`/`cum_sumsq` + grouped variants), just parameterized
by `temporal_aggregation.freq` instead of a hardcoded `"1D"`/`"7D"`. Once
that exists, "hourly for the dashboard" is just a query-time slice of the
1min prefix sums at hour-aligned edges — no separate storage required
unless kept as a pure query-speed cache (itself then also unbounded/kept
forever, since it's cheap relative to the 1min baseline).

**Open, unresolved — storage cost of the *grouped* breakdown at 1min,
kept forever:** the existing schema stores a per-`constellation|band|code`
breakdown (`cum_*_grouped`, ~30-40 groups) alongside the ungrouped total.
Back-of-envelope at 2° (6448 cells), 1min bins, float64, per pair, per
site: the **ungrouped total** (`cum_count`/`cum_sum`/`cum_sumsq`) is
roughly **~80 GB/year** — a real but tractable "download baseline" cost.
The **grouped** variant multiplies that by the group count (~30-40x) →
roughly **1-3 TB/year, per pair, per site** — before compression, and
before considering multiple pairs/sites. Zstd will claw back maybe 3-5x,
not enough to change the order of magnitude.

**Decision needed from the user before implementation:** keep the
per-signal-group breakdown at full 1min resolution forever too (accept the
multi-TB/year/site growth), or only retain it at coarser levels (day/week)
— with the 1min level stored ungrouped-only? Question posed, not yet
answered as of this note; pick up here.

---

## Open questions (product decisions, not resolvable from code)

1. ✅ **Resolved** — separate store, aggregates-only (see "Rollup store
   architecture" above). Config field also done (§4, prerequisite fix #7).
2. `--stats` flag vs `statistics.enabled` config — should the flag
   force-enable, or respect `enabled: false` and skip (current
   `tasks.py:1410-1423` behavior)? Two switches for one feature is a
   footgun either way — pick one as the source of truth.
3. `pair_id` naming: canvodpy `analysis_name` (matches `vod_analyses` keys,
   recommended) vs streamviz's `"CAN_vs_SKY"` convention parsed by
   `_cli_add_site` (`catalog.py:285-289`)? Affects serve-layer URLs and any
   existing prototype stores.
4. ✅ **Resolved (directionally)** — in-memory `vod_ds` for per-day ingest
   (simpler, avoids a post-commit dependency); historical rebuild paths read
   from the VOD store instead of a redundant rollup-store copy (see "Rollup
   store architecture" above). Not yet implemented.
5. Late-data semantics: `run_pipeline_for_pair` force-rebuilds all rollups
   when epochs arrive before `t_end` (`pipeline.py:184-192`). The CLI's
   resume logic can reprocess the last stored day (`cli/run.py:158`),
   which would look like "late data" and trigger a full rollup rebuild
   every run — but the temporal-overlap guard (`pipeline.py:215-217`)
   should skip the duplicate obs append first. Needs an explicit test;
   possibly the CLI should skip rollup for days whose obs were skipped as
   duplicates.
6. Should `--stats` be allowed with `--no-vod`? (Technically yes — it
   operates on SNR, not VOD.)
7. Sequencing/ownership for the three prerequisite fixes above, across
   two private repos this session doesn't directly control.
8. **Blocking, unresolved as of 2026-07-10** — grouped (per
   constellation\|band\|code) breakdown at the 1min baseline level: kept
   forever too (~1-3 TB/year/pair/site), or only at coarser day/week levels
   (1min stored ungrouped-only)? See "Rollup store architecture" §4 for the
   numbers this is based on. Nothing in the temporal-resolution rework
   (§4) should be implemented until this is answered.
