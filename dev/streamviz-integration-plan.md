# canvod-streamviz Integration Plan

**Date:** 2026-07-08
**Branch:** explore/performance-review (plan only; implementation on a dedicated branch)

---

## Current state

`/Users/work/Developer/GNSS/canvod-streamviz/` — standalone private repo, ~4 400 LOC.

| Component | State |
|---|---|
| `ingest.py` — `extract_pair_obs()` | ✅ Done. Reads RINEX stores, recomputes VOD via `TauOmegaZerothOrder`, filters, assigns cells. θ_max=80° implemented. NaN guard done. |
| `mesh.py` — `build_mesh()` | ✅ Done. S² Cartesian unit vectors, UGRID output. |
| `rollup.py` — schema v3 | ✅ Done. Welford moments (count, mean, M2, M3, M4, min, max, n_nan). float64. Per-constellation bin_moments. `built_from_commit` idempotency. |
| `pipeline.py` — `run_pipeline_for_pair()` | ✅ Done. Manual trigger only. |
| `serve/` — FastAPI + xpublish | ⚠️ Skeleton. `zarr_plugin.py` placeholder; hemisphere router wired but xpublish route dispatch not complete. |
| `tests/` — 920 lines | ⚠️ Partial. conftest uses real `canvod-grids` — fails in CI without local install. |
| `canvod-streamstats` package | ❌ Missing. Referenced in `_constants.py:62` (`STATE_SIZE = 8`) but package doesn't exist. Welford math currently lives in `rollup.py`. |
| Pipeline trigger (orchestrator hook) | ❌ Missing. Must run `pipeline.py` manually. |

## Open questions resolved

**Q: Does `preprocessing.grid_assignment` (canvod-ops) conflict with canvod-streamviz's `cell_id`?**
**A: No conflict.** `GridAssignment` in `canvod-ops` tags obs before the RINEX store commit (used by `TemporalAggregate`). `extract_pair_obs()` ignores any stored `cell_id` and derives fresh assignments from `phi`/`theta` at ingest time. They are independent.

**Q: Where does the rollup hook go — RINEX store commit or VOD store commit?**
**A: RINEX store commit.** `extract_pair_obs()` reads raw SNR + ephemeris from canopy/reference RINEX stores and recomputes VOD inline via `TauOmegaZerothOrder`. No separate VOD Icechunk store is required. The hook belongs immediately after `session.commit()` in `_append_to_icechunk()` — one commit per receiver, but rollup only triggers when both canopy+reference are available for the day.

**Q: Same Icechunk repo as RINEX store or separate?**
**A: Separate.** The RINEX store uses `(epoch, sid)` dims and has three-layer dedup guardrails that assume that shape. The rollup store uses `(edge, cell)` dims and a completely different layout. They must be separate repos.

---

## Phase 1 — `canvod-streamstats` package (~2 days)

The Welford accumulator math is currently embedded in `rollup.py`. It should be a standalone package so it can be tested without a store and reused by `StatisticsConfig` later.

### 1a. Create `packages/canvod-streamstats/`

```
packages/canvod-streamstats/
  pyproject.toml       # namespace: canvod.streamstats; deps: numpy
  src/canvod/streamstats/
    __init__.py        # export: WelfordAccumulator, merge_welford
    accumulators/
      __init__.py
      moments.py       # WelfordAccumulator(n, dtype=float64)
                       # .update(x: np.ndarray, cell_id: np.ndarray)
                       # .merge(other: WelfordAccumulator) → WelfordAccumulator
                       # .to_zarr_arrays() → dict[str, np.ndarray]
                       # .from_zarr_arrays(d) → WelfordAccumulator
    tests/
      test_moments.py  # golden tests (see §tests below)
```

`STATE_SIZE = 8` in `_constants.py` must match the layout: `count, mean, M2, M3, M4, min, max, n_nan`.

### 1b. Golden tests for Welford accumulator

These tests are pure math — no stores, no grids.

| Test | What it checks |
|---|---|
| `test_single_cell_matches_numpy` | `WelfordAccumulator.mean` == `np.mean(x)` for N=1000 obs in one cell |
| `test_merge_order_independence` | `merge(A, B)` == `merge(B, A)` == `update(A+B)` |
| `test_nan_rejection` | NaN inputs increment `n_nan`, not `count`; `mean` unaffected |
| `test_float64_dtype` | `.to_zarr_arrays()` always returns float64 arrays |
| `test_count_invariant` | `count.sum() == len(valid_obs)` after N appends |
| `test_empty_accumulator` | Update with zero obs → all-zero state, no division by zero |
| `test_window_prefix_subtraction` | `window(a,b) = cum[b] - cum[a]` matches brute-force recompute |

### 1c. Update canvod-streamviz to import from canvod-streamstats

Replace the inline Welford implementation in `rollup.py` with `from canvod.streamstats.accumulators.moments import WelfordAccumulator`. Update `_constants.py:62` (`STATE_SIZE`) to import from the package.

---

## Phase 2 — CI-safe test fixture (~1 day)

`tests/conftest.py` imports `canvod.grids` — fails in CI without local canvod-grids install.

### Fix

Create a `MockGrid` in `conftest.py` that implements the `GridData` interface (`grid` attribute with `cell_id` column, `n_cells` property) using a fixed 5-cell grid. The `_assign_cells_safe()` function already takes a `GridData` — mock it directly without touching the KDTree path.

```python
@pytest.fixture
def mock_grid():
    """Minimal GridData that returns fixed cell assignments without canvod-grids."""
    import pandas as pd
    class _MockGrid:
        n_cells = 5
        grid = pd.DataFrame({"cell_id": range(5), ...})  # minimal UGRID-compatible
    return _MockGrid()
```

Mark tests that require real `canvod-grids` as `@pytest.mark.integration`.

---

## Phase 3 — Pipeline trigger (~2 days)

### Decision: post-RINEX-commit hook via `RollupConfig`

Add `RollupConfig` to `canvod-utils/models.py` (next to `StatisticsConfig` at line 592):

```python
class RollupConfig(_StrictModel):
    enabled: bool = False
    pairs: list[str] | Literal["auto"] = "auto"   # auto = all vod_analyses keys
    theta_max_deg: float = 90.0
    vod_min: float = -50.0
    vod_max: float = 50.0
    min_count: int = 2                              # mask threshold for serve layer
    streamviz_store_root: Path | None = None        # where to write rollup repos
```

Add `rollup: RollupConfig = RollupConfig()` to `ProcessingConfig`.

### Hook in orchestrator (`processor.py`)

After `session.commit()` in `_append_to_icechunk()`, check if:
1. `config.processing.rollup.enabled` is True
2. Both canopy and reference have been committed for this date

If both conditions hold, call `run_pipeline_for_pair()` from `canvod.streamviz.pipeline`. The rollup is idempotent (`built_from_commit` guard) — safe to call multiple times.

```python
# STEP 6 — rollup (optional)
if rollup_cfg.enabled and _both_receivers_committed(date_key):
    from canvod.streamviz.pipeline import run_pipeline_for_pair
    run_pipeline_for_pair(
        canopy_store=self._get_store(canopy_name),
        reference_store=self._get_store(reference_name),
        pair_id=analysis_name,
        rollup_root=rollup_cfg.streamviz_store_root,
        theta_max_deg=rollup_cfg.theta_max_deg,
    )
```

**Note:** `canvod-streamviz` is a private local dep. Add it to `canvodpy/pyproject.toml` under `[project.optional-dependencies]` as `[streamviz] = ["canvod-streamviz"]` — not a hard dep. The hook import is guarded by the `try/except ImportError` pattern already used elsewhere.

### CLI trigger (alternative / backfill)

Add `canvodpy streamviz update --site <name> [--pair <id>] [--start] [--end]` to the existing CLI. This allows manual backfill without re-ingesting.

---

## Phase 4 — Complete xpublish serving (~1.5 days)

`serve/zarr_plugin.py` is currently a skeleton. Complete it:

1. Implement `make_router()` — dispatch Zarr HTTP API v3 requests to the Icechunk repo for the active site.
2. Wire into `make_app()`: mount xpublish at `/zarr`, hemisphere router at `/api`.
3. Add `serve/config.py`: `ServingConfig` (Pydantic) — `host`, `port`, `sites: dict[str, Path]`, `cache_ttl_s`.
4. Test with `pytest tests/test_serve.py` — the serve tests already exist.

Deploy command: `uvicorn "canvod.streamviz.serve.app:make_app()" --host 0.0.0.0 --port 8765`

---

## Phase 5 — Deferred (no timeline)

| Item | Blocks |
|---|---|
| Hour-level rollup (rolling 24h) | Skeleton in `rollup.py`; needs Phase 3 hook first |
| WebGL renderer (replace Plotly) | Phase 4 serve layer must be stable |
| Multi-site catalog UI (station selector, date range, download) | Needs multi-site deployment |
| Object storage backend (S3, MinIO) | Single-site works on local FS indefinitely |
| `canvod-automate` / Airflow integration | Replaces Phase 3 hook with a scheduled DAG |

---

## Implementation order

```
Phase 1  canvod-streamstats package + golden tests         ~2 days
Phase 2  CI-safe fixture (MockGrid)                        ~0.5 days
Phase 3  RollupConfig + orchestrator hook + backfill CLI   ~2 days
Phase 4  Complete xpublish serving                         ~1.5 days
─────────────────────────────────────────────────────────────────────
Total                                                       ~6 days
```

Phase 1 + 2 are independent of the monorepo orchestrator and can be done entirely in the `canvod-streamviz` and `canvod-streamstats` repos. Phase 3 touches `canvodpy` and `canvod-utils`.

---

## Files to create / modify

| File | Action |
|---|---|
| `packages/canvod-streamstats/` | Create (new package) |
| `packages/canvod-utils/src/canvod/utils/config/models.py` | Add `RollupConfig` near `StatisticsConfig` |
| `canvodpy/src/canvodpy/orchestrator/processor.py` | Add STEP 6 rollup hook |
| `canvodpy/pyproject.toml` | Add `[streamviz]` optional dep |
| `canvodpy/src/canvodpy/cli/run.py` | Add `streamviz update` subcommand |
| `/Users/work/Developer/GNSS/canvod-streamviz/tests/conftest.py` | MockGrid fixture |
| `/Users/work/Developer/GNSS/canvod-streamviz/src/canvod/streamviz/rollup.py` | Import from canvod-streamstats |
| `/Users/work/Developer/GNSS/canvod-streamviz/src/canvod/streamviz/serve/zarr_plugin.py` | Complete xpublish router |
