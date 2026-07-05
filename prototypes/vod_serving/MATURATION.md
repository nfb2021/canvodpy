# Maturation roadmap — from prototype to a network-scale VOD data viewer

> **Decision context (2026-06-13).** Target is **a network of many sites**
> (dozens+, ongoing), served to **a small team now with limited public access,
> trending to full public** long term. First foci chosen: **scale-out storage &
> serving** and **rollup completeness**. This doc is the agreed plan *before* code.
>
> Reads on top of: `SESSION_HANDOFF.md` (current state), `VIEWER_EXPLAINED.md`
> (how today's prototype works), and the memories
> `project-vod-store-viz-architecture`, `feedback-hemisphere-viz-principles`.

---

## 0. What we are building (one paragraph)

A Pangeo-native service that stores per-site VOD on the prescribed equal-area
hemisphere grid (gridded in space, native in time), and serves **instant windowed
hemisphere aggregates** for *any* site/antenna/time-range over a stable HTTP API,
to multiple clients (an internal marimo explorer now; a public WebGL dashboard
later). The data is huge and never moves; only date ranges go out and ~6448-number
per-cell arrays come back.

---

## 1. Guiding principles (the rules every phase obeys)

1. **API-first.** The HTTP contract is the product. Frontends (marimo, WebGL) are
   replaceable clients on top of it. Version it; never couple storage to a UI.
2. **Serve from source, no second copy.** Aggregates live as groups *inside* the
   same per-site store as the raw obs (Earthmover pattern). One thing to update,
   nothing to re-sync.
3. **The grid is sacred.** canvod's equal-area tessellation is never re-gridded.
   Geometry stays on S² as Cartesian unit vectors (no pole/seam). VOD always comes
   from canvod's `TauOmegaZerothOrder`.
4. **Additivity is the engine.** Everything fast (mean/std/count, per-constellation)
   reduces to add/subtract of cumulative moments → O(1) windows. Anything that
   isn't additive (n_sats) is explicitly special-cased, never faked.
5. **Bounded memory at every scale.** The whole database never fits in RAM. The
   server holds a catalog + an LRU of recently-touched rollups, nothing more.
6. **Provenance & reproducibility.** Every rollup slice records the obs commit it
   was built from. Served numbers are golden-tested against a raw scan.
7. **Single writer per site.** Each site store has exactly one writer (the 24 h
   job); many concurrent readers. This is what makes object-store icechunk safe.

---

## 2. Target architecture

```
                        ┌─────────────────────────────────────────┐
                        │  CATALOG  (small, global index)          │
                        │  sites, antennas, pairs, store URIs,     │
                        │  time ranges, grid res, levels, commits  │
                        └───────────────┬─────────────────────────┘
                                        │  (one repo per site, object storage)
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                                ▼
  site:tapajos.icechunk          site:siteB.icechunk            site:siteC.icechunk
   ├ grid   (UGRID mesh)          ├ grid                          ├ grid
   ├ meta   (sid lookup)          ├ meta                          ├ meta
   ├ <pair> (native obs)          ├ <pair>                        ├ <pair>
   └ rollup/<pair>/<level>        └ rollup/<pair>/<level>         └ rollup/<pair>/<level>
        hour* · day · week             (level pyramid in TIME)
                                        │
                       ┌────────────────┴───────────────────┐
                       │   SERVER  (xpublish/FastAPI, /v1)   │
                       │  catalog in RAM · rollups via LRU   │
                       │  prefix-subtraction · CORS · cache  │
                       └────────────────┬───────────────────┘
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                           ▼
       marimo explorer            WebGL dashboard            scripts / notebooks
        (team, now)               (public, later)             (analysis)
```

*Per-site stores* isolate the single-writer 24 h commit, bound blast-radius and
manifest size, and allow lazy per-site loading + independent backfill. The
*catalog* gives the global "what exists" view. The *server* is the only thing both
clients talk to.

---

## 3. Concrete schemas (the contracts to build against)

### 3a. Rollup schema **v2** (`rollup/<pair>/<level>`, `level ∈ {hour, day, week}`)

```
dims:  (edge, cell)                       cell = n_face (6448 at 2°)
coord: edge_time(edge)   datetime64       bin boundaries; cum[0] = 0

# total (always present) — gives "All-constellation" mean/std/count
cum_count   (edge, cell)
cum_sum     (edge, cell)
cum_sumsq   (edge, cell)

# per-constellation, for each letter present in meta (G,E,C,R,J,S,…)
cum_count_<C> (edge, cell)
cum_sum_<C>   (edge, cell)                 ← NEW vs v1 (v1 had counts only)
cum_sumsq_<C> (edge, cell)                 ← NEW

attrs:
  schema_version = 2
  level          = "day"
  freq           = "1D"
  n_bins         = <int>
  constellations = ["G","E","C","R", …]
  built_from_commit = "<obs commit id>"    ← provenance
  grid_res_deg   = 2.0
```

Any window `[a,b]`, any constellation `X` (or total): `delta = cum_*[b] − cum_*[a]`
→ `count = Δcount`, `mean = Δsum/Δcount`, `std = sqrt(Δsumsq/Δcount − mean²)`.
This makes **cons-filtered mean/std O(1)** (the gap in v1). Size at daily res ≈
`(3 + 3·n_cons) × n_edges × 6448 × 8 B`; with 5 constellations ≈ ~230 MB/pair —
fine for `day`, which is why `hour` is a **rolling recent window**, not full
history (hourly-over-years would be GBs).

### 3b. `n_sats` (distinct satellites per cell per window) — special-cased

Distinct-count is **not** additive, so prefix subtraction is invalid. Plan:
- **Interim:** computed on demand from raw obs for the window (slow path, honest).
- **Target:** mergeable **HyperLogLog** sketch per (bin, cell) at a coarse level
  (e.g. `week`); a window's estimate = union (register-max) over its bins. ~2 %
  error, bounded memory. Built as a separate `rollup/<pair>/<level>_nsat` group.

### 3c. Catalog schema (`/v1/catalog`)

```json
{ "schema_version": 1,
  "sites": [{
    "site_id": "tapajos",
    "name": "Tapajós GNSS-T",
    "location": {"lon": -54.95, "lat": -2.86, "alt_m": 120},
    "store_uri": "s3://carbonara/sites/tapajos.icechunk",
    "grid_res_deg": 2.0, "ncells": 6448,
    "constellations": ["G","E","C","R"],
    "levels": ["day", "week"],
    "pairs": [{
      "pair_id": "nadir_in_vs_sky_up",
      "can_group": "...", "sky_group": "...",
      "t_start": "2025-09-25", "t_end": "2026-05-31",
      "n_obs": 113850651,
      "last_obs_commit": "MXD8EHYKZ5Y7",
      "last_rollup_commit": "0GJPK2BXFB1C"
    }]
  }]
}
```

### 3d. API **v1** (versioned, CORS-enabled, cacheable where static)

| endpoint | purpose | cache |
|---|---|---|
| `GET /v1/catalog` | global index (sites/pairs/ranges) | ETag, short TTL |
| `GET /v1/healthz` | liveness/readiness | no |
| `GET /v1/sites/{site}/mesh` | static cell geometry | ETag, long TTL |
| `GET /v1/sites/{site}/pairs` | pairs + time ranges for a site | ETag |
| `GET /v1/sites/{site}/hemisphere/{pair}` | windowed per-cell array; params `t0,t1,layer,cons,level` | optional |

Server picks the coarsest `level` that satisfies the window (or honours an explicit
`level`); `hour` requests outside the rolling retention fall back to `day` with a
header note.

---

## 4. Phased roadmap

> Front-loaded on the two chosen foci (Phases 1–3). Each phase ends with a
> **Definition of Done (DoD)** — objective, testable.

### Phase 1 — Rollup completeness + a correctness harness  *(chosen focus)*
**Why first:** self-contained, makes every viewer control work fully, and forces
the **rollup schema v2 + provenance** that scale-out depends on. Correctness
tooling built here protects everything after.
- Rewrite `build_rollup.py` to emit schema v2 (per-cons sum/sumsq + total +
  provenance attrs); keep env overrides; multi-level capable (`day` now).
- **Golden test:** for random windows/pairs/constellations, assert
  `served_aggregate == raw_groupby(obs)` within float tolerance; assert prefix
  invariants (`cum` monotone in count, `cum[0]==0`).
- Wire cons-filtered `mean`/`std` through `serve_hemisphere.py`; expose in viewer.
- `n_sats` interim raw-obs path behind the existing layer.
- **DoD:** v2 rollup built on tapajos; golden tests green in CI; viewer's
  constellation filter changes mean/std (not just count); schema_version + commit
  provenance present and checked at server startup.

### Phase 2 — Scale-out storage: catalog + per-site layout + object storage  *(chosen focus)*
- Write `STORE_LAYOUT.md` (the spec in §2/§3) and a `catalog.py` (build/read).
- Storage abstraction: `local` (dev) and `s3`/`gcs` (prod) via icechunk storage
  configs; a single `open_site_store(site_id)` helper reads the catalog.
- Migrate tapajos into the per-site layout under a chosen object-store bucket
  (or MinIO locally first); generate the catalog entry.
- Backfill tooling: build a *new* site store + rollups from a source rinex store,
  end-to-end, parameterised by site.
- **DoD:** catalog lists ≥1 site; `open_site_store("tapajos")` works against object
  storage; a second (synthetic or real) site can be added by running one command;
  no hardcoded paths remain in builders/server.

### Phase 3 — Scale-out serving: multi-tenant, lazy, multi-resolution, API v1  *(chosen focus)*
- Refactor `serve_hemisphere.py` → catalog-driven, `/v1` routes, per-(site,pair,
  level) **LRU rollup cache** bounded by MB (evict least-recently-used site).
- Add `week` level (overview) + `hour` rolling-window level; level-selection logic.
- CORS, ETag on `/mesh` & `/catalog`, `/healthz`, structured request logging.
- Load test: concurrent readers across multiple sites stay within the memory bound.
- **DoD:** one server process serves N sites without loading all rollups; p95
  `/hemisphere` latency < ~50 ms warm; memory bounded under a mixed multi-site load;
  API documented (OpenAPI from FastAPI).

### Phase 4 — Self-updating pipeline (the 24 h job)
- One idempotent job per site: append a day's obs **and** its cumulative rollup
  slice(s) in a **single commit**; update the catalog entry (ranges, commits).
- Late/duplicate-day handling; hourly-window compaction/retention; rollup rebuild
  guarded by `built_from_commit`.
- Schedule (cron/Prefect/`/schedule`); alert on failure/drift.
- **DoD:** running the job appends exactly one consistent day; re-running is a
  no-op; a deliberately corrupted/stale rollup is detected and rebuilt; catalog
  stays accurate.

### Phase 5 — Frontends on the stable API
- Harden the marimo explorer: site picker (from `/catalog`), level-aware brush,
  all controls functional, graceful server-down UX. (Team use.)
- Spec + scaffold the **public WebGL client**: fetch `/mesh` once + `/hemisphere`
  per brush; render cell polygons (flat + ortho 2-D, 3-D sphere); no Python in the
  browser. (Public path.)
- **DoD:** marimo explorer drives any catalog site; WebGL prototype renders one
  site from the live API with persistent camera and instant brushing.

### Phase 6 — Productionization (team → public)
- Containerize server + job; deploy to object storage + a host; CDN/cache for
  `/mesh`, `/catalog`.
- AuthN/Z + rate-limiting for the limited-public stage; tighten for full public.
- Observability (metrics, tracing, dashboards); backups/versioning policy; CI/CD.
- **DoD:** a colleague hits a stable URL behind auth; metrics + alerts live; a new
  site goes from raw → visible via the scheduled pipeline with no manual steps.

---

## 5. Architecture Decision Records (what we're committing to, and why)

| # | Decision | Chosen | Rejected (why) |
|---|---|---|---|
| ADR-1 | Store granularity | **One icechunk repo per site** + global catalog | One mega-store (writer contention, manifest bloat, blast radius); per-pair stores (mesh duplication, too granular) |
| ADR-2 | Backend | **Object storage (S3/GCS/MinIO)**; local FS dev-only | Local FS in prod (unsafe concurrent commits, no cloud/public serving) |
| ADR-3 | Time resolution | **Pyramid: `day` base (full history) + rolling `hour` + `week` overview** | Single daily (no fine brush); on-the-fly (re-scans 1e8 obs); hourly-full-history (GB-scale) |
| ADR-4 | Constellation stats | **Per-cons full moments (count+sum+sumsq) + total** | Counts-only (no cons mean/std); on-the-fly filter (slow at scale) |
| ADR-5 | `n_sats` | **Mergeable HLL at coarse level + raw fallback** | Exact stored (too big, non-additive); omit (a real control) |
| ADR-6 | Client coupling | **API-first, versioned `/v1` HTTP contract** | UI-coupled serving (frontend churn breaks data layer) |
| ADR-7 | Integrity | **Provenance tag per rollup + golden tests** | Untracked rollups (silent drift, irreproducible) |

---

## 6. Risks & mitigations

- **Rollup/obs drift** (partial job failure) → single commit appends both;
  `built_from_commit` guard; startup consistency check; rebuild path.
- **Memory blow-up at N sites** → catalog-only resident; MB-bounded LRU of rollups;
  never open obs in the server.
- **Hourly retention growth** → rolling window + compaction job; weekly for
  overviews.
- **`n_sats` accuracy/size** → defer to HLL; raw fallback meanwhile; document error.
- **Single-writer violation** → orchestrate exactly one writer per site store;
  readers are sessionless/readonly.
- **Source (canvod) schema changes** → version guard + adapter (build_rollup
  already tolerates the two sid encodings); pin canvod.
- **Public exposure** (egress cost, abuse) → CDN/cache static endpoints; auth +
  rate-limit before public; tile-friendly responses.
- **icechunk/zarr v3 churn** → pin versions; the `UnstableSpecificationWarning` is
  handled by int-encoding (already done for sid).

---

## 7. Decisions still needed from you (small, blocking specifics)

1. **Object store**: AWS S3, GCS, or self-hosted MinIO to start? (Sets ADR-2 config
   and the deploy story.)
2. **Existing catalog?** Roll our own `catalog.json`/parquet, or use Arraylake/
   Earthmover (you've been tracking their patterns)?
3. **Sizing**: rough obs/site/day and target site count, so I size the LRU + hourly
   retention sensibly.
4. **Hourly retention window** (e.g. last 30 / 90 days)?
5. **n_sats accuracy** you can live with (HLL ~2 %)? Or keep it exact-but-slow only?
6. **Limited-public auth**: simple shared token / Cloudflare Access / real accounts?

(None block Phase 1, which is pure rollup-v2 + tests. They start to matter at
Phase 2.)
```
