# The VOD hemisphere viewer, explained from the ground up

> You drag a box over a timeline; a coloured dome of the sky updates instantly.
> This document explains *every* concept underneath that, in order, starting from
> "what is the grid" and ending at "what does each word in the launch command do".
> No prior knowledge of the storage stack assumed.
>
> Companion files: `SESSION_HANDOFF.md` (project state & decisions),
> `serve_hemisphere.py` (the server), `view_vod_cube.py` (the viewer),
> `build_native_full.py` / `build_rollup.py` (the builders).

---

## 0. What you are actually looking at

CARBONARA measures **VOD** (Vegetation Optical Depth) — roughly, *how much the
forest canopy attenuates a GNSS satellite signal on its way down to the antenna*.
A thick wet canopy attenuates more (higher VOD); bare sky attenuates nothing.

Every GNSS satellite sits somewhere in the sky, described by two angles:

- **θ (zenith angle)** — 0° straight up (zenith), 90° at the horizon.
- **φ (azimuth)** — compass bearing, 0° = North, increasing clockwise.

So each VOD measurement is "at this instant, looking in direction (θ, φ), the
canopy attenuation was *this much*." Over months, satellites sweep across the
whole sky, so you accumulate millions of (θ, φ, VOD) samples covering the dome
above the antenna. **The viewer's job is to let you pick a time window and see
the average canopy state in every direction of the sky** — a map painted on the
inside of a dome.

That is the destination. Now the concepts, bottom-up.

---

## 1. The sky is a sphere, not a rectangle

The naive way to store "a value per (θ, φ)" is a 2-D rectangle: φ along the
x-axis (0–360°), θ along the y-axis (0–90°). **Don't.** That rectangle lies about
the geometry in two places:

- **The zenith pole.** Straight up is a single point, but in the φ×θ rectangle the
  entire top row (θ ≈ 0) is stretched into a long line. One physical spot becomes
  hundreds of cells — a *singularity*.
- **The 0/360 seam.** φ = 359° and φ = 1° are neighbours in the sky but land at
  opposite edges of the rectangle. A satellite arc crossing North gets torn in
  half.

Both pathologies are artifacts of *flattening a sphere*, exactly like why every
flat world map distorts Greenland. The cure is to **never flatten**: keep the data
on the **unit sphere S²** and describe each point by its 3-D Cartesian unit vector

```
x = sin θ cos φ,   y = sin θ sin φ,   z = cos θ
```

In (x, y, z) the zenith is simply the point `(0, 0, 1)` — no stretched row — and
φ = 359° and φ = 1° are genuinely adjacent — no seam. **Everything geometric in
this system is stored as xyz unit vectors for this reason.** (This was a hard-won
design decision; see memory `feedback-hemisphere-viz-principles`.)

---

## 2. The grid: pixels on the dome

We can't store a value for *every* direction (there are infinitely many). We
divide the dome into a finite set of **cells** — think pixels, but on a sphere.

CARBONARA uses canvod's **equal-area hemisphere grid** (`create_hemigrid(
"equal_area", angular_resolution=2°)`). Two things matter about it:

1. **Equal-area.** Every cell covers the same solid angle (the same amount of
   sky). Near the horizon cells are squat and wide; near the zenith they are
   narrow — their *shapes* differ so their *areas* stay equal. This is what makes
   a "mean over a cell" fair: no direction is over- or under-counted. At 2°
   resolution this yields **6448 cells**.

2. **It is prescribed and fixed.** The science depends on this exact
   tessellation. We are *not* allowed to re-grid the data onto some other scheme
   (e.g. HEALPix) for convenience — that would change the numbers. So the storage
   format had to represent *these* cells exactly.

### How the grid is represented: a UGRID mesh

A cell is a little spherical quadrilateral bounded by `[φ_min, φ_max] ×
[θ_min, θ_max]`. We store the grid as an **unstructured mesh** in the **UGRID**
convention (the standard for unstructured geoscience meshes), which has three
pieces:

- **nodes** — the cell *corners*, each an xyz unit vector. (`node_x/y/z`,
  ~12 558 of them.)
- **faces** — the cells. Each face lists the 4 node indices of its corners
  (`face_node_connectivity`, shape 6448 × 4).
- **face metadata** — each cell's centre direction (`face_x/y/z`,
  `face_theta/phi`) and its solid angle (`face_solid_angle`).

When we convert each cell's 4 corners to xyz and then **deduplicate** identical
points, two nice things happen automatically: corners on the 0/360 seam merge
(same xyz), and all the cells meeting at the zenith share the one pole node. The
seam and pole simply *cannot* exist in this representation. (One honest wart: the
single cap cell at the very zenith is a degenerate quad — noted for later.)

> **Why "UGRID / unstructured" and not a plain array?** A plain 2-D array implies
> the rectangle-with-a-seam. An unstructured mesh says "here are cells of whatever
> shape, here is how they connect" — which is literally what an equal-area sphere
> tessellation is. It is the honest container for this grid.

---

## 3. "Gridded in space, native in time"

This is the core data-model decision, and it has two halves.

**Gridded in space.** Each raw observation is a continuous direction (θ, φ). We
snap it to the nearest grid cell using canvod's KDTree (`assign_equal_area` →
`_query_points`), which stamps every observation with a `cell_id` (0–6447). After
this step a measurement no longer says "θ = 41.3°, φ = 218.7°"; it says "cell
#5012". The continuous sky has been *quantised* into 6448 bins — that is the
"gridded" part.

**Native in time.** We do **not** do the same to time. We could have pre-summarised
into "daily snapshots" or "weekly averages", but that throws away resolution and
locks you into one binning forever. Instead every observation keeps its **exact
epoch** (timestamp). The store holds the raw point cloud:

```
one observation = (epoch, cell_id, vod, sid_code)
```

where `sid_code` identifies the satellite (an integer index into a lookup table of
satellite IDs like `G07`, `E12`, …; `G`=GPS, `E`=Galileo, `C`=BeiDou,
`R`=GLONASS). For the full deployment this is **~204 million observations** across
three antenna pairs.

> **The payoff:** because time stays native, *any* time aggregation — an hour, a
> day, a season, a custom dragged window — is computable later. Nothing is baked
> in. The grid quantises space (cheap, scientifically fixed); time stays free.

---

## 4. Where it all lives: one icechunk store

Everything sits in a single **icechunk** repository
(`_out/vod_native_full.icechunk`). icechunk is "git for array data": it stores
chunked, compressed N-D arrays (Zarr v3) on disk/cloud with **transactions,
commits, and versioning**. One store, committed every 24 h — chosen deliberately
so there is never a *second* store to keep in sync (a second copy would drift).

Inside, the data is organised into **groups** (like folders):

| group | what it holds |
|---|---|
| `grid` | the static UGRID mesh from §2 (nodes, faces, face metadata) |
| `meta` | the satellite-ID lookup table (decode `sid_code` → `G07` etc.) |
| `<pair>` | the native point cloud for one antenna pair: `epoch`, `cell_id`, `vod`, `sid_code`, plus a tiny per-day index (`day_date`, `day_count`, `day_mean_vod`) |
| `rollup/<pair>` | the cumulative summary that makes brushing instant — see §5 |

The three `<pair>` groups are `base_up_vs_sky_up`, `nadir_in_vs_sky_up`,
`nadir_out_vs_sky_up` (the up-looking and two nadir-looking antenna combinations).

---

## 5. The Earthmover-inspired rollup — the trick that makes it instant

Here is the problem. You drag a window covering, say, 40 days of the nadir_in
pair. That is tens of millions of observations. Re-scanning them on every drag —
filtering by time, then summing per cell — would take seconds and feel awful.

The fix is a classic idea (Earthmover, who build this storage stack
commercially, advocate "serve aggregates straight from the source store"): **pre-
compute a cumulative summary so any window is a subtraction.**

### 5a. Additive moments

You don't need the raw values to get a mean or std — you need three **additive**
quantities per cell:

```
count  = how many observations
sum    = Σ vod
sumsq  = Σ vod²
```

From those: `mean = sum/count`, and `std = sqrt(sumsq/count − mean²)`. The magic
word is **additive**: the count/sum/sumsq of "Monday + Tuesday" is just
"Monday's" plus "Tuesday's". You can add and subtract them freely.

### 5b. Cumulative (prefix) sums

Now bin time into days (249 daily edges over the deployment) and store, per cell,
the **running total from the start**:

```
cum[0] = 0
cum[k] = total of days 0 .. k-1     (a prefix sum)
```

Think of a bank balance. To know how much you spent between two dates you don't
re-add every transaction — you take `balance(end) − balance(start)`. Same here:

```
window [day a, day b)  →  cum[b] − cum[a]
```

One subtraction of two small arrays returns the per-cell `count`/`sum`/`sumsq`
for *any* window — **O(1)**, independent of how many millions of observations the
window actually contains. We store cumulative `count`, `sum`, `sumsq`, plus
per-constellation `count_G/E/C/R` (also additive, so the same subtraction gives a
GPS-only or Galileo-only count). Each `rollup/<pair>` is ~90 MB — tiny next to the
hundreds of millions of raw obs it summarises.

> **In one line:** the rollup turns "scan 100 million rows" into "subtract two
> 6448-number arrays." That is the whole reason brushing feels instant.

The 24 h pipeline appends one new day of observations **and** one new cumulative
slice in the *same* commit, so the rollup never drifts from the obs.

---

## 6. The server: `serve_hemisphere.py`

A thin web server (built on **xpublish**, which wraps **FastAPI**) that reads the
rollup from the store and answers windowed questions. It loads the mesh and the
three ~90 MB rollups into memory once at startup, then serves three endpoints:

- `GET /pairs` — the available pairs and their native time ranges.
- `GET /mesh` — the static cell geometry (nodes + faces), fetched once.
- `GET /hemisphere/{pair}?t0=&t1=&layer=&cons=` — **the workhorse.** It maps your
  window `[t0, t1]` to two daily edge indices `a, b`, does `cum[b] − cum[a]`,
  derives the requested `layer` (`mean`, `std`, or `count`), optionally filtered
  to one constellation (`cons=G/E/C/R`), and returns **one number per cell**
  (6448 values, with `null` where a cell had no data in that window) plus summary
  stats (`nobs`, `filled_cells`, `vmax`).

Per request it moves ~6448 numbers — not the raw observations. So it is
I/O-light, pure NumPy, no GPU needed. This is the "serve aggregates from the
source" pattern: the data is huge but **never moved**; only the tiny answer is.

> **Honest limits of the current rollup:** it stores per-constellation *counts*
> but not per-constellation sum/sumsq, so a constellation filter only applies to
> the `count` layer (not cons-filtered `mean`/`std`). And `n_sats` (distinct
> satellites per cell) isn't in the rollup. Both are noted as future polish
> (per-cons moments; an HLL sketch for n_sats).

---

## 7. The viewer: `view_vod_cube.py` (a marimo notebook)

**marimo** is a reactive Python notebook: cells form a dependency graph, and when
a value changes, every cell that depends on it re-runs automatically. The viewer
is now a **thin client** — it does *no* aggregation itself; it asks the server.

The pieces, in dependency order:

1. **Open the store locally** — but only for two cheap things: the **mesh**
   (to draw cell polygons) and the **daily timeline** (`day_date`, `day_count`,
   `day_mean_vod` — a few hundred numbers per pair). It deliberately does **not**
   read the 200-million-row obs; that work belongs to the server.

2. **Controls** — dropdowns for `pair`, `layer` (mean/std/count), `constellation`,
   and a radio for the 2-D projection.

3. **The timeline + brush** — a small Matplotlib plot of daily-mean VOD, wrapped
   in a **wigglystuff `ChartSelect`** widget so you can drag a box ("brush") to
   select a date range. Dragging changes the widget's value → marimo re-runs the
   downstream cells.

4. **Brush → query** — the brushed box is resolved to first/last day indices, then
   to ISO timestamps `t0`, `t1` (with `t1` pushed one day forward because the
   rollup window is half-open).

5. **The fetch** — `GET /hemisphere/{pair}?t0=&t1=&layer=&cons=` via **httpx**.
   The response's `values` become a 6448-long array `val`. This is the only
   expensive-looking step, and it's ~milliseconds because the server just
   subtracts two arrays. The status line shows obs count, filled cells, and the
   server round-trip time.

6. **Render** — the per-cell `val` array is turned into face colours (a colormap,
   grey where a cell is empty) and drawn as **filled cell polygons** (never
   markers — another viz principle) in two plots:
   - **3-D** on the actual unit sphere (the dome as it really is).
   - **2-D** radial sky-plot, with two selectable projections:
     - **flat / azimuthal-equidistant** (`ρ = θ/90°`) — the standard GNSS sky-plot;
       radius is linear in zenith angle, so the horizon isn't crushed.
     - **over-zenith / orthographic** (`ρ = sin θ`) — a camera looking straight
       down; visually intuitive but compresses the horizon.

### 7a. The camera-persistence trick (why the 3-D plot used to reset)

Originally each brush built a **brand-new** Plotly figure. marimo then mounted a
fresh plot element, so your hand-set 3-D camera angle snapped back to default
every drag — annoying.

Plotly has a `uirevision` flag that preserves the camera *when the plot updates in
place*, but it does nothing when the whole element is rebuilt and re-mounted —
which is what marimo was doing. So the real fix changes *how* the plot updates:

- The 3-D plot is created **once** as a Plotly **`FigureWidget`**, depending only
  on the static mesh. Since the mesh never changes, marimo never re-mounts it.
- On each brush, a separate cell **mutates that same widget in place** —
  `fig3d.data[0].facecolor = new_colours` inside a `batch_update()` — changing
  *only* the cell colours. The widget object (and therefore the camera) is never
  replaced, so your orbit/zoom survives every update.

This is why the launch command needs `--with ipywidgets`: a Plotly `FigureWidget`
is an ipywidget, and that in-place mutation is what carries the new colours to the
already-mounted plot. (The 2-D plot is a fixed top-down view, so it doesn't need
this.)

---

## 8. End-to-end: what happens on one drag

```
you drag a box on the timeline
        │
        ▼
wigglystuff ChartSelect value changes
        │  (marimo re-runs downstream cells)
        ▼
brush box → first/last day → t0, t1 (ISO timestamps)
        │
        ▼
httpx:  GET /hemisphere/nadir_in_vs_sky_up?t0=…&t1=…&layer=mean
        │
        ▼  (server)
map t0,t1 → daily edge indices a,b
agg = cum[b] − cum[a]                       ← O(1) prefix subtraction
mean = agg.sum / agg.count                  ← from additive moments
return 6448 per-cell values  (+ nobs, vmax)
        │
        ▼  (viewer)
val → colormap → face colours
fig3d.data[0].facecolor = colours           ← in-place, camera preserved
2-D sky-plot recoloured too
        │
        ▼
the dome repaints — in milliseconds
```

The huge dataset never moved. You only ever shipped a date range out and ~6448
numbers back.

---

## 9. The two commands, every element explained

You need **two terminals**, both run from the `canvodpy/` directory (that is where
`uv` finds the project's virtual-env, which has `canvod` and `icechunk`
installed, and from where the `../grid_storage/...` paths resolve).

### Terminal 1 — the server

```bash
cd /home/nbader/Developer/GNSS/carbonara_plotter/canvodpy && \
SERVE_STORE=/home/nbader/Developer/GNSS/carbonara_plotter/grid_storage/_out/vod_native_full.icechunk \
RUST_LOG=error \
uv run --with xpublish --with fastapi --with uvicorn \
  python ../grid_storage/serve_hemisphere.py
```

| element | what it does |
|---|---|
| `cd …/canvodpy &&` | run from the project dir so `uv` uses the right venv and relative paths resolve |
| `SERVE_STORE=…/vod_native_full.icechunk` | **env var** read by the script telling it which store to serve (defaults to the small 24 h prototype store if unset; this points it at the full deployment) |
| `RUST_LOG=error` | icechunk's engine is written in Rust and is chatty; this silences everything below error level |
| `uv run` | run the following command inside the project's `uv`-managed virtual environment |
| `--with xpublish --with fastapi --with uvicorn` | add three **ephemeral** dependencies *for this run only*, without editing `pyproject.toml`: the serving framework, its web framework, and the web server that actually listens on the port |
| `python ../grid_storage/serve_hemisphere.py` | the server script itself; it starts listening on `http://127.0.0.1:8000` |

Wait until it prints `Uvicorn running on http://127.0.0.1:8000`. Leave it running.
Stop it later with `Ctrl-C`.

### Terminal 2 — the viewer

```bash
cd /home/nbader/Developer/GNSS/carbonara_plotter/canvodpy && \
RUST_LOG=error \
uv run --with marimo --with plotly --with wigglystuff --with httpx --with ipywidgets \
  marimo edit ../grid_storage/view_vod_cube.py --no-token --watch
```

| element | what it does |
|---|---|
| `cd …/canvodpy &&` | same reason — correct venv + relative paths |
| `RUST_LOG=error` | quiet icechunk (the viewer opens the store for the mesh + timeline) |
| `uv run` | run inside the project venv |
| `--with marimo` | the reactive-notebook runtime |
| `--with plotly` | the 3-D / 2-D plotting library |
| `--with wigglystuff` | provides the draggable `ChartSelect` timeline-brush widget |
| `--with httpx` | the HTTP client used to call the server's `/hemisphere` endpoint |
| `--with ipywidgets` | **required** so the 3-D Plotly `FigureWidget` mounts and updates in place (the camera-persistence fix in §7a) |
| `marimo edit …/view_vod_cube.py` | open the notebook in editable, reactive mode in your browser |
| `--no-token` | skip marimo's URL auth token (convenience for a local session) |
| `--watch` | reload the notebook when the `.py` file changes on disk |

> **Optional:** prefix Terminal 2 with `HEMI_ENDPOINT=http://host:port` to point the
> viewer at a server somewhere other than the default `http://127.0.0.1:8000`.

The viewer's top banner turns **green** ("🛰️ aggregating on …") when it can reach
the server, and **yellow** with start-up instructions if it can't — so if the dome
is blank, check that Terminal 1 is up and serving the same store.

---

## 10. One-line glossary

- **VOD** — vegetation optical depth; canopy signal attenuation (the value we map).
- **θ / φ** — zenith angle / azimuth: a direction in the sky.
- **S²** — the unit sphere; we keep everything on it as xyz unit vectors to kill
  the pole singularity and the 0/360 seam.
- **equal-area grid** — 6448 same-solid-angle cells tiling the dome; fixed by the
  science.
- **UGRID mesh** — nodes (corners) + faces (cells) + connectivity: the honest
  container for an unstructured sphere grid.
- **cell_id** — which of the 6448 cells an observation falls in ("gridded in
  space").
- **native in time** — every obs keeps its exact epoch; no pre-binning.
- **icechunk** — versioned, transactional chunked-array store (git for arrays);
  one store, committed every 24 h.
- **additive moments** — count, sum, sumsq; combine by +/−; give mean & std.
- **rollup / prefix sum** — per-cell cumulative moments over daily bins; any window
  = `cum[b] − cum[a]`, O(1).
- **xpublish** — serves aggregates straight from the store over HTTP.
- **thin client** — the viewer ships a date range out and gets ~6448 numbers back;
  it never holds the raw obs.
- **FigureWidget** — the in-place-updatable Plotly object that lets the 3-D camera
  survive a brush.
```
