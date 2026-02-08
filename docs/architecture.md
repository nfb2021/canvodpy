---
title: Monorepo Structure
description: Architecture of the canVODpy monorepo and its package organization
---

# Monorepo Structure

## Overview

canVODpy is organized as a monorepo containing eight Python packages for GNSS vegetation optical depth analysis. All packages reside in a single repository while maintaining technical independence: each can be developed, tested, and published separately.

## Package Organization

```
canVODpy Monorepo
  canvod-readers    RINEX v3.04 observation file readers
  canvod-auxiliary   SP3 ephemeris and CLK clock correction processing
  canvod-grids      Hemispheric grid implementations
  canvod-vod        VOD estimation algorithms
  canvod-store      Icechunk/Zarr storage backends
  canvod-viz        Visualization utilities
  canvod-utils      Configuration and CLI tools
  canvodpy          Umbrella package (re-exports all subpackages)
```

## Key Design Decisions

### Namespace Packages

All packages share the `canvod.*` namespace, providing a unified import API:

```python
from canvod.readers import Rnxv3Obs
from canvod.grids import EqualAreaBuilder
from canvod.vod import VODCalculator
```

Each import originates from a different installable package, but the shared namespace presents a coherent interface. See [Namespace Packages](namespace-packages.md) for implementation details.

### Workspace Architecture

All packages share a single virtual environment and lockfile:

- One `uv sync` installs all packages in editable mode
- Dependencies are resolved together, preventing version conflicts
- Each package maintains its own `pyproject.toml` for independent publishing

### Package Independence

Each package can be installed independently:

```bash
pip install canvod-readers          # Just the readers
pip install canvod-grids canvod-vod # Grids and VOD only
pip install canvodpy                # Everything
```

## Directory Structure

```
canvodpy/                           # Repository root
  packages/                         # Independent packages
    canvod-readers/
      src/
        canvod/                     # Namespace (no __init__.py)
          readers/                  # Package code
            __init__.py
      tests/
      pyproject.toml
      README.md
    canvod-auxiliary/                # Same structure
      ...
  canvodpy/                         # Umbrella package
    src/
      canvodpy/
        __init__.py                 # Re-exports all subpackages
  docs/                             # Centralized documentation
  pyproject.toml                    # Workspace configuration
  uv.lock                          # Shared lockfile
  Justfile                          # Task runner commands
```

## Dependency Flow

```
canvod-readers    (no inter-package dependencies)
canvod-grids      (no inter-package dependencies)
canvod-vod        (no inter-package dependencies)
canvod-utils      (no inter-package dependencies)
canvod-auxiliary   depends on canvod-readers
canvod-store      depends on canvod-grids
canvod-viz        depends on canvod-grids
canvodpy          depends on all packages
```

The dependency graph is intentionally flat: four foundation packages have zero inter-package dependencies, and three consumer packages each depend on exactly one foundation package. Maximum dependency depth is 1.

## Trade-offs

**Advantages:**
- Clear separation of concerns between packages
- Users install only the components they need
- Independent testing and development per package
- Smaller dependency trees for individual packages

**Costs:**
- Additional configuration files per package
- Developers must understand the namespace package mechanism
- Coordinated releases required for version consistency
