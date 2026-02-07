# canVODpy Dependency Graphs

**Generated with [pydeps](https://github.com/thebjorn/pydeps)**
**Date:** 2026-01-25

---

## Overview

This directory contains automatically generated dependency graphs for the canVODpy package ecosystem. The graphs visualize import relationships between packages and modules, focusing exclusively on canvodpy and canvod.* packages (external Python libraries are excluded).

---

## Graph Files

### 1. Complete Overview

**`canvodpy_overview.svg` / `canvodpy_overview.png`** (27KB)
- **Scope:** Full canvodpy umbrella package
- **Shows:** All import relationships across all modules
- **Clustering:** Enabled (groups modules by package)
- **Depth:** 3 levels (--max-bacon 3)
- **Best for:** Understanding overall architecture

![canvodpy Overview](canvodpy_overview.png)

---

### 2. Full Detail (Original)

**`canvodpy_full.svg`** (17KB)
- **Scope:** Complete canvodpy with strict filtering
- **Filter:** `--only canvodpy canvod` (shows only these namespaces)
- **Clustering:** Enabled
- **Depth:** 2 levels
- **Best for:** Focusing only on internal packages

---

### 3. Simplified View

**`canvodpy_simple.svg`** (7.8KB)
- **Scope:** Canvodpy without clustering
- **Shows:** Direct module-to-module dependencies
- **Clustering:** Disabled (flatter view)
- **Depth:** 2 levels, max module depth 2
- **Best for:** Seeing direct import chains

---

### 4. Individual Package Graphs

#### canvod.auxiliary
**`canvod_aux.svg`** (992B)
- Dependencies on: canvod.readers, canvod.utils, canvodpy.settings, canvodpy.globals
- Key exports: AuxDataPipeline, Sp3File, ClkFile

#### canvod.readers
**`canvod_readers.svg`** (611B)
- Dependencies on: canvod.utils
- Key exports: Rnxv3Obs, DataDirMatcher, MatchedDirs

#### canvod.store
**`canvod_store.svg`** (992B)
- Dependencies on: canvod.grids, canvod.readers, canvod.utils, canvod.auxiliary
- Key exports: GnssResearchSite, IcechunkDataReader

#### Orchestrator
**`orchestrator.svg`** (987B)
- Shows: High-level orchestration layer
- Dependencies on: All canvod.* packages
- Key modules: processor, pipeline, matcher

---

## How to View

### SVG Files (Vector Graphics)
- **GitHub:** Renders automatically in browser
- **VSCode:** Built-in SVG preview
- **Web browsers:** Open directly
- **Inkscape/Illustrator:** For editing

### PNG Files
- **Any image viewer**
- **Better for:** Quick viewing, presentations, documentation

---

## Interpreting the Graphs

### Node Types
- **Boxes:** Modules/packages
- **Clusters:** Package groupings (when clustering enabled)
- **Colors:** Different colors indicate different package namespaces

### Edge Types
- **Solid arrows:** Direct imports
- **Arrow direction:** Points from importer to imported module

### Reading Tips
1. **Follow arrows:** Start from umbrella package, follow dependencies downward
2. **Identify layers:** Core packages (no deps) at bottom, orchestration at top
3. **Spot circular deps:** Look for cycles in arrows
4. **Check clustering:** Grouped boxes show package boundaries

---

## Package Dependency Summary

Based on the generated graphs:

```
canvodpy (Umbrella)
├── orchestrator/ → ALL packages
├── settings.py → .env, processing.yaml
└── globals.py → Default constants

canvod.auxiliary
├── → canvod.readers
├── → canvod.utils
├── → canvod.store (optional)
├── → canvodpy.settings
└── → canvodpy.globals

canvod.store
├── → canvod.grids
├── → canvod.readers
├── → canvod.utils
├── → canvod.auxiliary (optional)
├── → canvod.vod
└── → canvodpy.* (globals, logging, research_sites_config)

canvod.readers
└── → canvod.utils

canvod.viz
└── → canvod.grids

canvod.vod
└── → canvod.store

canvod.utils
└── (no dependencies)

canvod.grids
└── (no dependencies)
```

---

## Key Findings

### 1. Circular Dependencies
**Identified:** `canvod.auxiliary` ↔ `canvod.store`

**Visible in:** canvodpy_overview graph (look for cycle between aux and store clusters)

**Resolution:** Optional/lazy imports (imports only when needed, not at module level)

### 2. Dependency Layers

**Layer 0 (Core):**
- canvod.utils
- canvod.grids

**Layer 1 (Base):**
- canvod.readers → utils

**Layer 2 (Mid-tier):**
- canvod.auxiliary → readers, utils, store
- canvod.store → grids, readers, utils, aux
- canvod.viz → grids

**Layer 3 (Processing):**
- canvod.vod → store

**Layer 4 (Orchestration):**
- canvodpy → ALL packages

### 3. Configuration Flow

**Visible in:** orchestrator.svg

```
.env + processing.yaml
        ↓
    settings.py
        ↓
    globals.py
        ↓
    Packages (aux, store, orchestrator)
```

### 4. Most Connected Packages

**canvod.store:**
- Highest number of dependencies
- Central hub connecting aux, readers, utils, grids, vod
- Uses canvodpy infrastructure (globals, logging, research_sites_config)

**canvodpy.orchestrator:**
- Integrates ALL namespace packages
- Provides high-level workflow coordination

---

## Regenerating Graphs

### Prerequisites
```bash
# Install pydeps
uv pip install pydeps

# Requires graphviz for rendering
brew install graphviz  # macOS
apt install graphviz   # Linux
```

### Generate Complete Overview
```bash
cd /Users/work/Developer/GNSS/canvodpy

# SVG version
uv run pydeps canvodpy/src/canvodpy \
    -x numpy pandas xarray pathlib os sys re datetime collections typing pydantic \
    -T svg \
    -o docs/dependency_graphs/canvodpy_overview.svg \
    --noshow \
    --cluster \
    --max-bacon 3 \
    --rmprefix canvod. canvodpy.

# PNG version
uv run pydeps canvodpy/src/canvodpy \
    -x numpy pandas xarray pathlib os sys re datetime collections typing pydantic \
    -T png \
    -o docs/dependency_graphs/canvodpy_overview.png \
    --noshow \
    --cluster \
    --max-bacon 3 \
    --rmprefix canvod. canvodpy.
```

### Generate Individual Package Graph
```bash
# Example: canvod.auxiliary
uv run pydeps packages/canvod-auxiliary/src/canvod/aux \
    --only canvodpy canvod \
    -T svg \
    -o docs/dependency_graphs/canvod_aux.svg \
    --noshow \
    --cluster \
    --max-bacon 2
```

### Key Flags Explained

- `-x MODULE`: Exclude specific modules (e.g., `-x numpy pandas`)
- `--only PREFIX`: Include only modules matching prefix
- `-T FORMAT`: Output format (svg, png)
- `-o FILE`: Output file path
- `--noshow`: Don't display graph automatically
- `--cluster`: Group modules by package
- `--max-bacon N`: Limit dependency depth (N levels)
- `--rmprefix PREFIX`: Remove prefix from node names for clarity
- `-v`: Verbose output

---

## pydeps Configuration

For automated generation, create `.pydeps` in project root:

```ini
[pydeps]
# Exclude common external libraries
exclude = numpy pandas xarray pathlib os sys re datetime collections typing pydantic pytest

# Visual settings
cluster = True
max_bacon = 3
rankdir = TB

# Output
T = svg
noshow = True

# Filtering
rmprefix = canvod. canvodpy.
```

Then run simply:
```bash
pydeps canvodpy/src/canvodpy -o docs/dependency_graphs/output.svg
```

---

## Troubleshooting

### Empty/Small Graph Files
**Issue:** Graph shows no or few connections
**Cause:** Too restrictive filtering with `--only`
**Solution:** Use `-x` to exclude externals instead

### Cluttered Graph
**Issue:** Too many nodes, hard to read
**Solutions:**
- Increase `--max-bacon` to limit depth
- Use `--max-module-depth` to limit module nesting
- Enable `--cluster` to group by package
- Use `-x` to exclude more external libraries

### Circular Dependency Warnings
**Issue:** pydeps reports circular imports
**Expected:** canvod.auxiliary ↔ canvod.store (by design, using lazy imports)
**Action:** Document in graph README, verify lazy import pattern

---

## Related Documentation

- **CANVODPY_DEPENDENCY_GRAPH.md** - Comprehensive text documentation
- **DEPENDENCY_GRAPH.mmd** - Mermaid diagram source
- **DEPENDENCY_TREE.txt** - Quick text reference
- **REPO_STRUCTURE_STATUS.md** - Repository structure verification

---

## Graph Generation History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-25 | 1.0 | Initial generation with pydeps |

---

**Note:** These graphs are automatically generated and may need updates when:
- New packages are added
- Module structure changes
- Import relationships change
- Dependency refactoring occurs

Regenerate graphs after significant structural changes to keep documentation current.
