---
title: Developing with Claude Code
description: How canVODpy uses AI-assisted development with Claude Code, skills, and persistent memory
---

# Developing with Claude Code

canVODpy is developed with [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
Anthropic's agentic coding CLI. This page documents the setup, the breadcrumb trail
Claude follows to understand the project, and how contributors can use it.

---

## Quick start

```bash
# Install Claude Code
npm install -g @anthropic-ai/claude-code

# Run in the project root — CLAUDE.md loads automatically
cd canvodpy
claude
```

Claude will automatically read `CLAUDE.md`, which provides scientific context,
architecture overview, conventions, and pointers to deeper documentation.

!!! tip "You don't need Claude Code to contribute"

    `CLAUDE.md` is a plain markdown file that also serves as a human-readable
    summary of project conventions. Everything documented there applies whether
    you use Claude Code or not.

---

## The breadcrumb trail

When Claude Code starts, it follows this chain to build understanding:

```
CLAUDE.md (auto-loaded)
├── Scientific context (GNSS-T, VOD, key domain concepts)
├── Architecture (12 packages, CLI + Site.pipeline() + functional API, data contracts)
├── Conventions (uv, ruff, ty, pytest, commitizen)
├── Skills table (15+ domain skills, auto-applied)
├── Guardrails (what NOT to change without running audits)
└── Key documentation pointers:
    ├── docs/guides/ai-development.md  ← you are here
    ├── docs/architecture.md           ← system design & data flow
    ├── docs/principles.md             ← design philosophy
    ├── docs/guides/api-levels.md      ← CLI, Site.pipeline(), functional API
    ├── docs/guides/contributor-setup.md ← contributor setup & first run
    ├── docs/findings/                 ← scientific comparison results
    └── docs/packages/*/overview.md    ← per-package deep dives
```

Additionally, Claude Code maintains **persistent memory** across sessions in
`.claude/projects/<hash>/memory/`, storing architectural decisions, known issues,
and project conventions discovered during development.

---

## Skills

Skills are domain-specific knowledge modules that Claude Code applies automatically
when their domain is relevant. They provide deep expertise without needing to
re-explain conventions each session.

### Installed skills

| Skill | What it provides | Install |
|---|---|---|
| `xarray` | Dims, coords, attrs, `.sel()`, `.where()`, Dask chunking | `npx skills add tondevrel/scientific-agent-skills@xarray -g -y` |
| `zarr-python` | Zarr v3 stores, encoding, compression, parallel I/O | `npx skills add davila7/claude-code-templates@zarr-python -g -y` |
| `icechunk` | Icechunk transactions, branching, time travel, xarray integration | `just install-skills` (bundled in repo at `.claude/skills/icechunk/`) |
| `pydantic` | BaseModel patterns, validators, `ConfigDict`, frozen models | `npx skills add bobmatnyc/claude-mpm-skills@pydantic -g -y` |
| `python-testing-patterns` | pytest fixtures, parametrize, mocking, assertion patterns | `npx skills add wshobson/agents@python-testing-patterns -g -y` |
| `uv-package-manager` | `uv run`, `uv add`, workspace management, `pyproject.toml` | `npx skills add wshobson/agents@uv-package-manager -g -y` |
| `marimo-notebook` | Marimo cell structure, reactive execution, `mo.ui` widgets | `npx skills add marimo-team/skills@marimo-notebook -g -y` |
| `beautiful-mermaid` | Render `.mmd` diagrams to SVG/PNG with themed output | `npx skills add intellectronica/agent-skills@beautiful-mermaid -g -y` |
| `mermaid-diagrams` | Architecture, flow, ERD, C4 diagrams in Mermaid syntax | `npx skills add softaworks/agent-toolkit@mermaid-diagrams -g -y` |
| `scientific-writing` | IMRAD manuscripts, citations, reporting guidelines | `npx skills add davila7/claude-code-templates@scientific-writing -g -y` |
| `airflow` | Airflow DAG operations, debugging, task logs, health checks | `npx skills add astronomer/agents@airflow -g -y` |
| `airflow-dag-patterns` | DAG design patterns, TaskFlow API, dynamic DAGs, testing | `npx skills add wshobson/agents@airflow-dag-patterns -g -y` |
| `docs-as-code` | Documentation pipeline automation, MkDocs, Zensical workflows | Custom (contact maintainer) |
| `context-mode` | Large output handling, log analysis, data processing | MCP plugin (auto-configured) |
| `notebooklm` | Generate podcasts, reports, quizzes from project sources | `pip install notebooklm-py && notebooklm skill install` |
| `find-skills` | Discover and install new skills from the ecosystem | `npx skills add vercel-labs/skills@find-skills -g -y` |
| `agent-browser` | Browser automation for testing and scraping | `npx skills add vercel-labs/agent-browser@agent-browser -g -y` |
| `simplify` | Review changed code for reuse, quality, efficiency | Built-in Claude Code skill |

### Installing all skills at once

```bash
# Core scientific stack
npx skills add tondevrel/scientific-agent-skills@xarray -g -y
npx skills add davila7/claude-code-templates@zarr-python -g -y
npx skills add bobmatnyc/claude-mpm-skills@pydantic -g -y

# Development workflow
npx skills add wshobson/agents@python-testing-patterns -g -y
npx skills add wshobson/agents@uv-package-manager -g -y
npx skills add marimo-team/skills@marimo-notebook -g -y

# Orchestration
npx skills add astronomer/agents@airflow -g -y
npx skills add wshobson/agents@airflow-dag-patterns -g -y

# Diagrams & documentation
npx skills add intellectronica/agent-skills@beautiful-mermaid -g -y
npx skills add softaworks/agent-toolkit@mermaid-diagrams -g -y
npx skills add davila7/claude-code-templates@scientific-writing -g -y

# Bundled (ships with this repo)
just install-skills

# Utilities
npx skills add vercel-labs/skills@find-skills -g -y
npx skills add vercel-labs/agent-browser@agent-browser -g -y
pip install notebooklm-py && notebooklm skill install
```

---

## Typical workflows

### Exploring the codebase

```
> Explain how SBF broadcast ephemeris differs from SP3 agency ephemeris

Claude will:
1. Read CLAUDE.md scientific context (auto-loaded)
2. Follow breadcrumb to docs/findings/ephemeris_source_architecture.md
3. Read the EphemerisProvider ABC and both implementations
4. Explain with domain-correct terminology
```

### Code generation

```
> Add a new reader for NMEA format following the GNSSDataReader ABC

Claude will:
1. Read GNSSDataReader base class
2. Study Rnxv3Obs and SbfReader for patterns
3. Generate the reader with proper Pydantic model, to_ds(), iter_epochs()
4. Write tests following existing patterns
5. Register in the factory
```

### Running the pipeline

```
> Process the last week of data for site ExampleSite

Claude will:
1. Recommend the CLI: canvodpy run --site ExampleSite --start ... --end ...
2. Suggest omitting --start on subsequent runs (auto-resumes from the store)
3. Only drop to Site(site).pipeline() in Python if the user needs scripted,
   multi-site, or notebook-embedded control
4. Not suggest FluentWorkflow, the flat process_date()/calculate_vod()
   functions, or VODWorkflow — all deprecated, see docs/guides/api-levels.md
```

### Running the audit suite

```
> Run the audit tests and explain any failures

Claude will:
1. Run: just test-audit
2. Parse test output (60+ tests across 4 tiers)
3. For failures: read the relevant comparison engine code
4. Explain what scientific property was violated
```

---

## Three-tier audit suite

The [canvod-audit](../packages/audit/overview.md) package provides scientifically
defensible verification across four tiers:

| Tier | What it verifies | CI |
|---|---|---|
| 0 | Reader self-consistency (read twice = identical) | test_platforms.yml |
| 1a | SBF vs RINEX structural consistency | audit.yml |
| 1b | Broadcast vs agency ephemeris angular agreement | audit.yml |
| 2 | Regression freeze/thaw round-trips | audit.yml |
| 3 | vs gnssvod (Humphrey et al.) — external validation | Manual |

The audit CI runs on every push that touches readers, store, auxiliary, or audit code.
It uses real GNSS test data from a git submodule.

---

## Guidelines for AI-assisted contributions

1. **Review all output.** AI-generated code must be reviewed by a human before merging.
   The contributor submitting the change is responsible for correctness.

2. **Run the test suite.** Always run `just test` after AI-assisted changes.

3. **Check scientific claims.** AI may hallucinate references, formulas, or values.
   Cross-check against primary sources (IGS documentation, Navipedia, literature).

4. **Commit attribution.** Commits with significant AI assistance include:
   ```
   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   ```

5. **No secrets.** Never paste API keys, credentials, or private data into an AI tool.
   Claude Code operates locally but sends prompts to Anthropic's API.

---

## Related pages

- [Architecture](../architecture.md) — system design and data flow
- [Contributor Setup](contributor-setup.md) — contributor setup and first run
- [API Levels](api-levels.md) — CLI, `Site.pipeline()`, and the functional API explained
- [Audit Overview](../packages/audit/overview.md) — three-tier verification suite
