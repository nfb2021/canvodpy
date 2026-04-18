# canvodpy — Claude Code Instructions

## Skills — auto-apply when relevant

Apply all skills automatically whenever their domain is relevant — do not
wait to be asked.

### Core skills (installed)

| Skill | Apply when | Install |
|---|---|---|
| `xarray` | Working with `xarray.Dataset` / `DataArray`, coordinates, dims, attrs | `npx skills add tondevrel/scientific-agent-skills@xarray -g -y` |
| `zarr-python` | Working with Zarr stores, chunking, encoding | `npx skills add davila7/claude-code-templates@zarr-python -g -y` |
| `icechunk` | Working with Icechunk stores, versioned storage, branching | `just install-skills` (bundled at `.claude/skills/icechunk/`) |
| `pydantic` | Working with Pydantic models, validators, `BaseModel` | `npx skills add bobmatnyc/claude-mpm-skills@pydantic -g -y` |
| `python-testing-patterns` | Writing or reviewing `pytest` tests | `npx skills add wshobson/agents@python-testing-patterns -g -y` |
| `uv-package-manager` | Running `uv`, editing `pyproject.toml`, managing deps | `npx skills add wshobson/agents@uv-package-manager -g -y` |
| `marimo-notebook` | Writing/editing marimo notebooks (`.py` marimo files) | `npx skills add marimo-team/skills@marimo-notebook -g -y` |
| `beautiful-mermaid` | Rendering Mermaid diagrams to SVG/PNG from `.mmd` sources | `npx skills add intellectronica/agent-skills@beautiful-mermaid -g -y` |
| `mermaid-diagrams` | Creating software diagrams (architecture, flows, ERDs) | `npx skills add softaworks/agent-toolkit@mermaid-diagrams -g -y` |
| `scientific-writing` | Writing scientific manuscripts (IMRAD structure, citations) | `npx skills add davila7/claude-code-templates@scientific-writing -g -y` |
| `docs-as-code` | Documentation pipeline automation, MkDocs/Zensical workflows | Custom (contact maintainer) |
| `context-mode` | Large command outputs, log analysis, data processing | MCP plugin (see context-mode docs) |
| `notebooklm` | Generating podcasts, reports, quizzes from project sources | `pip install notebooklm-py && notebooklm skill install` |
| `simplify` | Reviewing changed code for reuse, quality, and efficiency | Built-in Claude Code skill |
| `find-skills` | Discovering and installing new skills | `npx skills add vercel-labs/skills@find-skills -g -y` |
| `agent-browser` | Browser automation for testing and scraping | `npx skills add vercel-labs/agent-browser@agent-browser -g -y` |
| `airflow` | Airflow best practices, operators, patterns (Astronomer) | `npx skills add astronomer/agents@airflow -g -y` |
| `airflow-dag-patterns` | DAG design patterns, TaskFlow API, dynamic DAGs, testing | `npx skills add wshobson/agents@airflow-dag-patterns -g -y` |

## Scientific context — GNSS-T and Vegetation Optical Depth

> This section provides the domain knowledge needed to work on this codebase.
> Read it before making changes to scientific logic.

### What is GNSS Transmissometry (GNSS-T)?

GNSS-T is a remote sensing technique that uses existing GNSS satellite signals
(L-band microwaves) to estimate vegetation properties. As signals travel from
a satellite to a ground-based receiver, they are scattered and absorbed by the
vegetation canopy.

The experimental setup uses **two receivers**:
- **Reference receiver** — placed in the open or above the canopy (unobstructed)
- **Canopy receiver** — placed underneath the vegetation

By comparing the **Signal-to-Noise Ratio (SNR)** at both locations for the same
satellite, the system calculates **transmittance (T)** — the ratio of signal
power reaching the below-canopy receiver vs. the unobstructed reference.

### What is VOD?

**Vegetation Optical Depth (VOD)** quantifies canopy signal attenuation using
the Tau-Omega Radiative Transfer Model:

    VOD = -ln(T) · cos(θ)

where T is transmittance and θ is the polar angle. VOD is a proxy for
**vegetation biomass and fuel moisture content**. Unlike optical sensors (NDVI),
L-band signals penetrate the entire canopy — invaluable for monitoring forest
health, carbon stocks, and drought stress.

### Key domain concepts for developers

| Concept | What it means | In the code |
|---|---|---|
| **SNR** | Signal-to-Noise Ratio (dB-Hz), the primary observable | SBF: 0.25 dB quantization; RINEX: ~0.001 dB |
| **SID** | Signal ID: `SV\|Band\|Code` (e.g. `G01\|L1\|C`) | Unique key identifying satellite + frequency + tracking code |
| **PRN** | Satellite identifier (e.g. `G01`) | Used by external tools; canvodpy uses SID internally |
| **Polar angle (θ)** | Angle from vertical to satellite (0°=overhead, 90°=horizon) | Used in VOD formula; internally prefer polar angle over elevation |
| **Azimuth (φ)** | Compass direction to satellite (0°=N, 90°=E) | Used for hemispheric gridding |
| **Ephemeris** | Satellite orbital data for position computation | Agency final (SP3/CLK, ~3 cm, 12-18 day latency) or broadcast (~1-2 m, real-time) |
| **Constellations** | GPS (G), Galileo (E), GLONASS (R), BeiDou (C) | System prefix in SID string |
| **Fresnel zone** | Elliptical signal footprint on canopy/ground | Determines spatial sensitivity of each observation |
| **Epoch** | Timestamp of a GNSS observation | GPS Time → UTC conversion with leap-second offset |
| **ECEF** | Earth-Centered Earth-Fixed coordinates | Satellite positions before conversion to receiver-relative spherical |

### Processing pipeline

```
RINEX/SBF files → Reader → xarray.Dataset(epoch, sid)
    → Ephemeris augmentation (SP3/CLK or broadcast)
    → Coordinate transform (ECEF → spherical: r, θ, φ)
    → Hemispheric gridding (EqualArea grid cells)
    → VOD retrieval (align canopy & reference by epoch+SID)
    → Icechunk/Zarr store (versioned, cloud-native)
```

## Project architecture

### Monorepo packages

| Package | Namespace | Role |
|---|---|---|
| `canvod-readers` | `canvod.readers` | RINEX v2/v3 and SBF binary readers → `xarray.Dataset` |
| `canvod-store` | `canvod.store` | Icechunk/Zarr storage layer (`MyIcechunkStore`) |
| `canvod-store-metadata` | `canvod.store_metadata` | Rich DataCite/ACDD/STAC metadata (11 sections, ~90 fields) |
| `canvod-vod` | `canvod.vod` | VOD retrieval algorithms |
| `canvod-grids` | `canvod.grids` | Spatial grid operations (EqualArea hemigrid) |
| `canvod-auxiliary` | `canvod.auxiliary` | Ephemeris, troposphere, auxiliary data pipeline |
| `canvod-utils` | `canvod.utils` | Config models (Pydantic), shared utilities |
| `canvod-viz` | `canvod.viz` | Visualization and store viewer |
| `canvod-ops` | `canvod.ops` | Operational pipeline (streaming, monitoring) |
| `canvod-virtualiconvname` | `canvod.virtualiconvname` | GNSS filename convention parsing and validation |
| `canvod-audit` | `canvod.audit` | Three-tier verification suite (internal consistency, regression, vs gnssvod) |
| `canvodpy` | `canvodpy` | Orchestrator, API levels (L1-L4), VodComputer |

### API levels

| Level | Style | Entry point | Use case |
|---|---|---|---|
| L1 | Convenience | `canvodpy.read()`, `canvodpy.vod()` | Quick exploration, notebooks |
| L2 | Fluent | `FluentWorkflow().read().augment().grid().vod()` | Scripted workflows |
| L3 | Site pipeline | `site.process()`, `site.vod` | Full site processing with config |
| L4 | Functional | `canvodpy.functional.*` | Custom pipelines, testing |

### Data contracts

- **All datasets**: dimensions `(epoch, sid)`, attribute `"File Hash"` required
- **SID format**: `SV|Band|Code` (e.g. `G01|L1|C`)
- **Naming convention**: `{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}`
- **Store guardrails**: three-layer dedup (hash match, temporal overlap, intra-batch overlap)

## Tooling

| Tool | Command | Purpose |
|---|---|---|
| `uv` | `uv sync`, `uv run` | Package manager, workspace orchestration, virtual env |
| `ruff` | `uv run ruff check`, `uv run ruff format` | Linting and formatting (replaces flake8/black/isort) |
| `ty` | `uv run ty check` | Type checking (Astral's type checker) |
| `pytest` | `uv run pytest` | Test runner; `-m "not integration"` for fast suite |
| `beautiful-mermaid` | `npx beautiful-mermaid render ...` | Render `.mmd` diagrams to SVG/PNG |
| `gfzrnx` | `/usr/local/bin/gfzrnx` | IGS RINEX toolkit (obs type filtering, splicing) — used by `RinexTrimmer` |
| `Zensical` | `uv run zensical build` | Rust+Python MkDocs Material wrapper for docs |
| `commitizen` | pre-commit hook | Enforces conventional commit messages |
| `pre-commit` | auto on `git commit` | Runs ruff, trim whitespace, large file check, private key detection |

### Common commands

```bash
# Quality & testing
uv sync                                  # Install all workspace deps
just check                               # Lint + format (all packages) — fast, always passes
just check-types                         # Type check with ty (informational, allowed to fail)
just test                                # Run all tests
just test-audit                          # Run audit suite (unit + integration)
just test-all-packages                   # Run tests per package (avoids namespace collisions)
just test-package canvod-readers         # Test a single package
uv run pytest -m "not integration"       # Skip integration tests (fast)

# Documentation & notebooks
just docs                                # Preview documentation locally
just notebooks                           # List available marimo notebooks
just open-notebook grids_overview.py     # Edit a notebook interactively

# Store metadata
just metadata-show <store_path>          # Full metadata report for a store
just metadata-validate <store_path>      # Validate against FAIR/DataCite/ACDD/STAC

# Configuration
just config-validate                     # Validate sites.yaml
just config-check-data <site>            # Pre-flight naming convention check

# Dependencies
just deps-all                            # Generate all dependency graphs
just deps-cross                          # Cross-package dependency graph
```

## Conventions

- Monorepo managed with `uv` workspaces — all packages share one `.venv` at root
- Pydantic models use `frozen=False` with `@cached_property` for lazy computation
- Config: Pydantic models in `canvod.utils.config.models` (centralized, ~900 lines)
- Commits: conventional commits enforced by commitizen (`feat:`, `fix:`, `chore:`, etc.)
- Generated files: do NOT commit `*.png`, `*.svg` (except `docs/assets/logo.svg`),
  `*.lcov`, `*.db`, `node_modules/`, `package.json`, `package-lock.json`

## Code quality philosophy

**Goal:** Catch bugs without annoying scientists.

### What's enforced (blocks commits & PRs)
- **Linting** (ruff) — undefined names, unused imports, actual bugs
- **Formatting** (ruff) — auto-fixes, no cognitive load
- **Security** — no private keys, no large files in Git
- **Commit messages** — conventional commits for automated changelog

### What's informational (tracks progress, doesn't block)
- **Type checking** (ty) — runs in CI with `continue-on-error: true`
- Type hints are being added progressively
- Run `just check-types` to track full diagnostics manually
- Focus on correctness tests (audit suite) over type bureaucracy

### ty rollout phases (active)
- **Phase 2 (noise reduction):** file-level ignore on the two worst files while refactors are pending
- **Phase 3 (enforcement):** `just check-types-budget` is enforced in CI via `TY_MAX_DIAGNOSTICS`
- Ratchet policy: lower the budget by ~10 diagnostics per PR until target is reached, then remove file ignores

### Test code exemptions
Tests can use `assert`, magic numbers, and intentionally weird patterns
to test edge cases (see `pyproject.toml:90` for ruff exemptions).

## Guardrails — what NOT to change without understanding

> These areas involve scientific correctness or data integrity. Do not modify
> them without understanding the underlying science and running the audit suite.

- **VOD formula** (`canvod-vod`) — Tau-Omega radiative transfer model
- **Coordinate transforms** (`canvod-auxiliary`) — ECEF ↔ spherical, deg/rad conversions
- **Store dedup logic** (`canvod-store`) — hash + temporal overlap + intra-batch guards
- **Naming convention parser** (`canvod-virtualiconvname`) — IGS/RINEX standard
- **Ephemeris interpolation** (`canvod-auxiliary`) — Hermite spline on SP3 data
- **SID construction** (`canvod-readers`) — must match across readers and store

After changes to any of the above, run:
```bash
uv run pytest packages/canvod-audit/tests/  # Audit suite (60 tests, includes real data)
uv run pytest -m "not integration"          # Fast unit tests across all packages
```

## Diagram rendering

Use **[lukilabs/beautiful-mermaid](https://github.com/lukilabs/beautiful-mermaid)** for
rendering Mermaid diagrams to SVG/PNG. Source files live in `docs/diagrams/` (`.mmd`).
Do not commit generated images (`*.png`, `*.svg` except `docs/assets/logo.svg`),
`node_modules/`, or `package*.json`.

## Key documentation — breadcrumb trail

When you need deeper context than this file provides, read these docs **in order**.
Each document cross-references the next, building from high-level architecture down
to package-specific details.

1. `docs/guides/ai-development.md` — **start here**: Claude Code setup, skills, audit suite, workflows
2. `docs/architecture.md` — system architecture and data flow
3. `docs/principles.md` — design principles and philosophy
4. `docs/guides/api-levels.md` — the four API levels explained
5. `docs/guides/getting-started.md` — setup and first run
6. `docs/packages/audit/overview.md` — three-tier verification suite
7. `docs/findings/` — scientific comparison results and findings
8. `docs/packages/*/overview.md` — per-package deep dives

**Onboarding rule:** If a user asks you to explain the project, walk them through
this trail. If you encounter an unfamiliar package or concept, follow the trail
to the relevant `overview.md` before answering.

## AI-assisted development

This project uses **Claude Code** as a development and maintenance tool.
The AI agent is configured with:

- **`CLAUDE.md`** (this file) — project-specific instructions, architecture context,
  and scientific domain knowledge loaded into every conversation
- **15+ Claude Code skills** — domain-specific knowledge packs for xarray, Zarr,
  Pydantic, pytest, uv, marimo, Mermaid, and scientific writing (see skills table above)
- **Persistent memory** — cross-session recall of project decisions, conventions,
  and known issues (stored in `.claude/` directory)
- **Three-tier audit suite** — scientifically defensible verification that runs as CI
  and catches regressions when any pipeline component changes

New contributors: Claude Code can explain any part of the codebase, run the test
suite, generate diagrams, and help navigate the monorepo. Start with
`claude` in the repo root — it will automatically load this context.

### Session discipline

- **Always `cd` into the repo root before launching** — Claude Code reads the
  current directory for context; launching from home means no project awareness.
- **Prefer short, focused sessions** over marathon ones. When switching to an
  unrelated task, start fresh with `/clear`.
- **Watch for context window degradation**: signs are Claude re-reading files it
  already examined, or suggesting changes you already rejected. Use `/compact`
  to summarise conversation history and reclaim context space.
