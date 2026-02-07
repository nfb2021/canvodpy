---
title: Architecture Overview
description: Understanding the canVODpy monorepo structure and design decisions
---

# Architecture Overview

## What is canVODpy?

canVODpy is a **monorepo** containing multiple Python packages for GNSS (Global Navigation Satellite System) vegetation optical depth (VOD) analysis. Instead of having seven separate repositories, we keep all related packages in one place while maintaining their independence.

## The Problem We're Solving

Previously, the GNSS VOD analysis code existed as a single monolithic package. This created several problems:

1. **Tight coupling**: All features were interdependent
2. **Large dependencies**: Installing one feature meant installing all dependencies
3. **Difficult testing**: Hard to test components in isolation
4. **Unclear boundaries**: Code organization was unclear

## Our Solution: Modular Monorepo

We split the functionality into **eight independent packages** that work together:

```
canVODpy Monorepo
├── canvod-readers    → Read GNSS data formats (RINEX v3.04)
├── canvod-auxiliary   → Auxiliary data (SP3 ephemeris, CLK clock corrections)
├── canvod-grids      → Spatial grids (HEALPix, HTM, equal-area, etc.)
├── canvod-vod        → Calculate vegetation optical depth (tau-omega)
├── canvod-store      → Store data (Icechunk, Zarr)
├── canvod-viz        → Visualize results (2D/3D hemisphere plots)
├── canvod-utils      → Configuration, CLI tools, shared utilities
└── canvodpy          → Umbrella package (imports everything)
```

## Key Architectural Decisions

### 1. Namespace Packages

Instead of seven separate top-level packages, we use **namespace packages** so all packages share the `canvod.*` namespace:

```python
# All packages share the "canvod" namespace
from canvod.readers import Rnxv3Obs
from canvod.grids import EqualAreaBuilder
from canvod.vod import VODCalculator
```

**Why?** This creates a unified, professional API while keeping packages technically independent.

### 2. Monorepo Structure

All packages live in one repository but can be:
- Developed independently
- Tested in isolation
- Published separately to PyPI
- Versioned individually (if needed)

**Why?** Easier to coordinate changes across packages while maintaining modularity.

### 3. Workspace Architecture

We use a **workspace** structure where:
- All packages share one virtual environment (`.venv`)
- All packages share one lockfile (`uv.lock`)
- Dependencies are resolved together
- But each package maintains its own `pyproject.toml`

**Why?** Ensures all packages work together with compatible versions.

## Directory Structure Explained

```
canvodpy/                           # Repository root
│
├── packages/                       # Independent packages
│   ├── canvod-readers/
│   │   ├── src/
│   │   │   └── canvod/            # Namespace (NO __init__.py)
│   │   │       └── readers/       # Actual package
│   │   │           └── __init__.py
│   │   ├── tests/
│   │   ├── docs/
│   │   ├── pyproject.toml         # Package config
│   │   ├── Justfile               # Package commands
│   │   └── README.md
│   │
│   └── canvod-auxiliary/                 # Same structure
│       └── ...
│
├── canvodpy/                       # Umbrella package
│   └── src/
│       └── canvodpy/               # Regular package
│           └── __init__.py         # Re-exports all subpackages
│
├── .github/                        # CI/CD
│   ├── actions/setup/              # Reusable setup action
│   └── workflows/                  # CI workflows
│
├── docs/                           # Documentation (you are here!)
├── pyproject.toml                  # Workspace configuration
├── uv.lock                         # Shared lockfile
├── Justfile                        # Root commands
└── README.md                       # Project overview
```

## Package Independence

Each package can be:

**Installed independently:**
```bash
pip install canvod-readers          # Just the readers
pip install canvod-grids canvod-vod # Just grids + VOD
pip install canvodpy                # Everything
```

**Developed independently:**
```bash
cd packages/canvod-readers
just test                           # Test only this package
just build                          # Build only this package
```

**Published independently:**
Each package gets its own PyPI page:
- `pypi.org/project/canvod-readers/`
- `pypi.org/project/canvod-auxiliary/`
- etc.

## Dependency Flow

Packages declare explicit inter-package dependencies:

```
canvod-readers    (no inter-package dependencies)
canvod-grids      (no inter-package dependencies)
canvod-vod        (no inter-package dependencies)
canvod-utils      (no inter-package dependencies)
canvod-auxiliary   → depends on canvod-readers
canvod-store      → depends on canvod-grids
canvod-viz        → depends on canvod-grids
canvodpy          → depends on all packages
```

The dependency graph is intentionally flat — most packages are independent, with only three declared inter-package edges.

**During development:** All packages are installed in "editable mode" so changes to one package immediately affect packages that depend on it.

**After publishing:** Users can install only what they need.

## Why This Architecture?

### Advantages

1. **Modularity**: Clear separation of concerns
2. **Flexibility**: Use only what you need
3. **Maintainability**: Easier to understand and modify
4. **Testing**: Test components in isolation
5. **Collaboration**: Different people can own different packages
6. **Dependency management**: Smaller dependency trees per package

### Trade-offs

1. **Complexity**: More configuration files to manage
2. **Build time**: Need to build multiple packages
3. **Learning curve**: Developers need to understand the structure

We believe the advantages far outweigh the trade-offs for a project of this size and complexity.

## Real-World Example

```python
# Clear, explicit imports from separate packages
from canvod.readers import Rnxv3Obs
from canvod.grids import EqualAreaBuilder
from canvod.vod import VODCalculator

# Or use the umbrella package
import canvodpy
reader = canvodpy.readers.Rnxv3Obs(fpath="data.rnx")
```

## Next Steps

- [Understanding the Tooling](tooling.md) - Learn about uv, ruff, ty, etc.
- [Namespace Packages Deep Dive](namespace-packages.md) - How the `canvod.*` namespace works
- [Development Workflow](development-workflow.md) - How to work in this monorepo
- [Build System](build-system.md) - How packages are built and published
