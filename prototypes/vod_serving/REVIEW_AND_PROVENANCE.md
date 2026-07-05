# Review + provenance audit — rollup / plotting / grid+virtualization stack

> Date: 2026-07-04. Covers the cumulative rollup, the xpublish serving layer, the
> marimo viewer, the UGRID mesh, and the canvod grid primitives they lean on.
> Two parts: **(A)** a correctness review (what's sound, what to fix) and
> **(B)** a provenance/location audit answering *"is all the required logic
> inside the `canvodpy` repo, and on which branch?"* — the short answer is **no,
> most of it is not** (see §B).

---

## A. Correctness review

### Verdict — the pipeline is intact and works end-to-end

Re-ran the serving self-test against the **full** store
(`_out/vod_native_full.icechunk`, 906 MB) on 2026-07-04: it passes.

- mesh `6448 cells / 12558 nodes`
- rollup group intact: `249 daily edges × 6448 cells`, span `2025-09-25 → 2026-05-31`,
  vars `cum_sum / cum_sumsq / cum_count / cum_count_{G,E,C,R}`
- full-window `nobs = 5,906,333` (matches the build record)
- O(1) prefix-subtraction brushing verified (2-day sub-window → `nobs = 106,959`)

### What each piece does (and that it is sound)

| File | Role | Status |
|---|---|---|
| `build_rollup.py` | cumulative additive moments + per-cons counts, prepended zero edge so `cum[b]-cum[a]` = any window; vectorized `sid_code→letter` decode | ✅ correct |
| `serve_hemisphere.py` | xpublish router; loads mesh + 3 rollups once; windows by prefix subtraction (~6448 numbers/req) | ✅ validated |
| `view_vod_cube.py` | thin marimo client; brush → `GET /hemisphere`; persistent 3D `FigureWidget` recolored in place (camera survives); 2D flat-equidistant + over-zenith | ✅ sound |
| `build_native_full.py` | gridded-in-space / native-in-time full store; per-day index | ✅ |
| `build_icechunk_cube.build_mesh` | canvod equal-area cells → UGRID mesh, Cartesian `node_x/y/z` (xyz dedup kills pole singularity + azimuth seam) | ✅ |
| `_common.py` + `canvod.grids.operations._query_points` | KDTree nearest-cell-centre assignment | ✅ (see issue 1) |

### Issues worth addressing (ranked)

1. **Nearest-centre snapping has no rejection radius**
   (`canvod/grids/operations.py:_query_points`, used via `_common.assign_equal_area`
   in `build_native_full.py`). Any obs with θ beyond the outermost ring is snapped
   to a horizon cell rather than dropped; the full build applies **no θ cutoff**
   before assignment, only a finiteness mask. In practice θ∈[0,90°] so impact is
   small, but low-elevation obs would inflate horizon-ring counts. Fix: pass
   `distance_upper_bound` to the KDTree query → NaN beyond it. *(Only issue with
   scientific bite.)*

2. **`cons` param is unvalidated** (`serve_hemisphere.py`, `_aggregate`). A bad
   value hits `delta("cum_count_X")` → `KeyError` → HTTP 500. Guard:
   `if cons and cons not in "GECR": raise HTTPException(400, ...)`.

3. **Self-test window label is misleading on the daily store**
   (`serve_hemisphere.py`, `_selftest`). Prints `window 00:00-00:00` because the
   `[11:16]` time-slice is a leftover from the hourly prototype; the window itself
   is fine. Slice `[:10]` (date) instead.

4. **Population vs sample std.** `serve_hemisphere._aggregate` and
   `_common.mean_std` use √(E[x²]−E[x]²) (÷N), not ÷(N−1). Consistent everywhere,
   guarded by `cnt≥2`. Just be aware it's population std.

5. **Zenith cap cells** are degenerate quads under xyz dedup (already flagged in
   `SESSION_HANDOFF §8`). They still render (as a triangle; the second sub-triangle
   collapses) — cosmetic. Represent as a fan when finalizing the mesh.

None block anything today.

---

## B. Provenance / location audit — **the important part**

**Question:** is all the required logic inside the `canvodpy` repo, or is it
sitting in notebooks / side directories? **Answer: most of it is OUTSIDE canvodpy
and is not committed anywhere.**

### Repo topology

There are **two nested git repos**:

| Repo | Path | Branch | State |
|---|---|---|---|
| **outer** ("carbonara_plotter" scratch) | `…/GNSS/carbonara_plotter` | `master` | everything untracked |
| **canvodpy** (the real monorepo) | `…/carbonara_plotter/canvodpy` | **`main`** | dirty working tree, uncommitted edits |

`grid_storage/` lives in the **outer** repo, **outside** the `canvodpy` git repo
entirely (`git ls-files` from canvodpy: *"outside repository"*). And in the outer
repo it is **untracked** (`?? grid_storage/`) — i.e. **not committed anywhere, in
any repo.**

### What is where

**Inside `canvodpy` (branch `main`) — the reusable primitives only:**
- `canvod.grids.create_hemigrid` — the equal-area tessellation (6448 cells @ 2°)
- `canvod.grids.operations._build_kdtree` / `_query_points` — cell assignment
- `canvod.grids.operations.grid_to_dataset` / `store_grid` — the UGRID-lite serialize
- `canvod.grids.aggregation` — `aggregate_data_to_grid`, `compute_percell_timeseries`
- `canvod.vod.TauOmegaZerothOrder` — the guard-railed VOD formula
- `canvod.viz.HemisphereVisualizer` — the polar renderer

> ⚠️ Note these primitives are on `main` but the **working tree is dirty** — several
> `packages/**` and `src/canvodpy/**` files are modified and uncommitted. The
> primitives the prototypes import are stable, but nothing here is a clean commit.

**Outside `canvodpy` (untracked, in the outer repo) — ALL the new architecture:**

| Component | File(s) | Home |
|---|---|---|
| UGRID mesh builder (`build_mesh`) | `grid_storage/build_icechunk_cube.py` | outer, untracked |
| Native full store builder | `grid_storage/build_native_full.py` | outer, untracked |
| Native 24h prototype | `grid_storage/build_native_pointcloud.py` | outer, untracked |
| **Cumulative rollup** | `grid_storage/build_rollup.py` | outer, untracked |
| **xpublish serving layer** | `grid_storage/serve_hemisphere.py` | outer, untracked |
| **Marimo viewer** | `grid_storage/view_vod_cube.py` | outer, untracked |
| Shared helpers | `grid_storage/_common.py` | outer, untracked |
| Strategy prototypes | `grid_storage/strategy{1,2,3}_*/` | outer, untracked |
| **VOD-per-day source iterator** | `precompute_vod_summary.py` (`open_session`, `day_bounds`, `vod_for_day`, `PAIRS`, uses `TauOmegaZerothOrder`) | **outer repo root**, untracked |

`build_native_full.py` imports `PAIRS, day_bounds, open_session, vod_for_day` from
`precompute_vod_summary.py` at the **outer repo root** — so the full build has a
hard dependency on an untracked side script, not on canvodpy.

`canvodpy` itself contains **zero** of the rollup / serving / UGRID-mesh / viewer
logic (grep for `build_mesh|cum_sum|rollup|uxarray|UGRID|face_node_connectivity`
in `canvodpy/**` src → no hits).

### Consequence / risk

- The entire serving + rollup + viewer + native-store architecture is **prototype
  code in an untracked scratch directory**. One `git clean`/`rm` and it is gone;
  it is not versioned, not packaged, not importable from `canvod.*`.
- This is expected — `grid_storage/` was always the de-risking sandbox (per
  `SESSION_HANDOFF §6.7` and `MATURATION.md`). But nothing has been promoted yet.

### Migration TODO (to make "all logic in canvodpy")

1. **Commit/land the canvodpy working tree** on `main` (or a feature branch) so the
   primitives the prototypes depend on are a clean baseline.
2. **Promote the mesh builder** (`build_mesh`) into `canvod.grids` as a first-class
   UGRID emitter (`SESSION_HANDOFF §6.7`, the planned canvod-grids restructure).
3. **Move `precompute_vod_summary`'s source-day iterator** (`open_session`,
   `day_bounds`, `vod_for_day`) into a canvod package (candidate: `canvod.ops` or a
   new `canvod.store` reader helper) so builds don't import an outer-root script.
4. **Package the rollup + serving + viewer** as a canvod subpackage (candidate:
   `canvod.serve` / `canvod.viz`), replacing the `grid_storage/` scripts.
5. Until then: at minimum `git add` `grid_storage/` + the outer-root precompute
   scripts into the outer repo and commit, so the prototype is not one `rm` from
   deletion.

### One-line answer

**Branch:** the reusable grid/VOD/viz primitives are in **canvodpy on `main`**
(dirty tree). **Everything else** — rollup, xpublish serving, marimo viewer, UGRID
mesh, native store builders — lives in the **untracked `grid_storage/` side
directory of the outer `carbonara_plotter` repo (branch `master`)** and is **not in
canvodpy at all, and not committed in any repo.**
