---
title: canVODpy Documentation
description: Complete guide to understanding and developing canVODpy
---

# canVODpy Documentation

Welcome to the complete technical documentation for canVODpy, a modern monorepo for GNSS vegetation optical depth analysis.

## What is canVODpy?

canVODpy is a **modular Python package ecosystem** for analyzing GNSS (Global Navigation Satellite System) signals to estimate vegetation optical depth (VOD). The project uses a **monorepo architecture** with **namespace packages** to provide both modularity and a unified API.

## Who Should Read This?

This documentation is for:

- **New developers** joining the project
- **Contributors** wanting to understand the architecture
- **Users** interested in how the package works
- **Anyone** curious about modern Python monorepo development

**No prior knowledge assumed!** We explain everything from the ground up.

## What You'll Learn

### 1. Architecture Overview
[**Read: Architecture →**](architecture.md)

Understand the big picture:
- Why a monorepo instead of separate repos?
- How are the seven packages organized?
- What is the dependency flow?
- Why this architecture?

**Start here if:** You want to understand the overall project structure.

### 2. Development Tooling
[**Read: Tooling →**](tooling.md)

Master the modern Python toolchain:
- **uv** - Fast package manager
- **uv_build** - Build backend for packages
- **ruff** - Linter and formatter
- **ty** - Type checker
- **Just** - Task runner
- **pytest** - Testing framework
- **MyST** - Documentation system

**Start here if:** You're new to modern Python development or want to know why we chose these tools.

### 3. Namespace Packages Deep Dive
[**Read: Namespace Packages →**](namespace-packages.md)

Understand the `canvod.*` namespace:
- What are namespace packages?
- How do they work in Python?
- Why use them vs. regular packages?
- How does `canvod.readers` differ from `canvod_readers`?
- The role of implicit namespace packages

**Start here if:** You're confused about namespace packages or the project structure.

### 4. Development Workflow
[**Read: Development Workflow →**](development-workflow.md)

Learn day-to-day development:
- Setting up your environment
- Working on a package
- Running tests and quality checks
- Adding dependencies
- Building and publishing
- Common tasks and troubleshooting

**Start here if:** You're ready to contribute code.

### 5. Build System
[**Read: Build System →**](build-system.md)

Understand package building and distribution:
- What is "building" a package?
- Source distributions vs. wheels
- How uv_build works
- Publishing to PyPI
- Version management
- Build configuration

**Start here if:** You want to understand how packages are built and published.

## Quick Start Guide

### For New Developers

1. **Understand the architecture** → [Architecture](architecture.md)
2. **Learn the tools** → [Tooling](tooling.md)
3. **Set up your environment** → [Development Workflow](development-workflow.md)
4. **Start coding!**

### For Contributors

1. **Read:** [Development Workflow](development-workflow.md)
2. **Clone the repo:** `git clone https://github.com/nfb2021/canvodpy.git`
3. **Setup:** `cd canvodpy && uv sync && just hooks`
4. **Make changes:** Follow the workflow guide
5. **Submit PR:** `git push` and create pull request

### For Package Users

1. **Install:** `pip install canvodpy`
2. **Import:** `from canvod.readers import Rnxv3Obs`
3. **Use:** See package-specific documentation

## Key Concepts

### Monorepo

**One repository** containing **multiple packages**:

```
canvodpy/                    # Single repository
├── packages/
│   ├── canvod-readers/      # Package 1
│   ├── canvod-auxiliary/          # Package 2
│   ├── canvod-grids/        # Package 3
│   └── ...                  # Packages 4-6
└── canvodpy/                # Package 7 (umbrella)
```

**Benefits:**
- Easier to coordinate changes
- Shared tooling and configuration
- Single CI/CD setup
- Better for monolithic-to-modular migration

### Namespace Packages

**Multiple packages** sharing **one namespace**:

```python
# All from different PyPI packages, same namespace:
from canvod.readers import Rnxv3Obs        # canvod-readers
from canvod.grids import EqualAreaBuilder  # canvod-grids
from canvod.vod import VODCalculator       # canvod-vod
```

**Benefits:**
- Professional, unified API
- Clear package relationships
- Users install only what they need
- Extensible by third parties

### Workspace

**Shared development environment** for all packages:

```
canvodpy/
├── .venv/           # Shared virtual environment
├── uv.lock          # Shared lockfile
└── packages/        # All packages here
```

**Benefits:**
- One `uv sync` installs everything
- Packages immediately see each other's changes
- Guaranteed compatible versions
- Fast iteration

## The Eight Packages

```
canvod-readers    → Read GNSS data (RINEX v3.04)
canvod-auxiliary   → Auxiliary data (SP3 ephemeris, CLK clock corrections)
canvod-grids      → Spatial grids (HEALPix, HTM, equal-area, etc.)
canvod-vod        → Calculate vegetation optical depth (tau-omega)
canvod-store      → Store data (Icechunk, Zarr)
canvod-viz        → Visualize results (2D/3D hemisphere plots)
canvod-utils      → Configuration, CLI tools, shared utilities
canvodpy          → Umbrella (imports everything)
```

**Declared inter-package dependencies:**
```
readers ←── auxiliary
grids ←── store
grids ←── viz
canvodpy depends on all packages
```
`readers`, `grids`, `vod`, and `utils` have no inter-package dependencies.

## Technology Stack

### Core Technologies
- **Language:** Python 3.13+
- **Package Manager:** uv (Astral)
- **Build Backend:** uv_build (Astral)
- **Namespace:** Python 3.3+ implicit namespace packages

### Development Tools
- **Linter/Formatter:** ruff (Astral)
- **Type Checker:** ty (Astral)
- **Testing:** pytest
- **Task Runner:** Just
- **Pre-commit:** pre-commit hooks
- **CI/CD:** GitHub Actions

### Data Technologies
- **Spatial Grids:** HEALPix
- **Storage:** Icechunk, Zarr
- **Data Processing:** NumPy, Pandas, Xarray
- **Formats:** RINEX, NetCDF, Zarr

## Project Philosophy

### 1. Modern Over Legacy

We use **modern tools** (uv, ruff, ty) over legacy equivalents (pip, flake8, mypy) for:
- Speed (10-100x faster)
- Better integration
- Simpler configuration
- Active development

### 2. Modularity Over Monolith

**Small, focused packages** instead of one large package:
- Clear responsibilities
- Independent development
- Flexible dependencies
- Easier testing

### 3. Standards Compliance

Following **TU Wien GEO** standards:
- uv-based workflow
- Comprehensive testing
- Quality checks (ruff with curated rule set)
- Proper documentation

### 4. Documentation First

**Explain everything:**
- Why decisions were made
- How things work
- What alternatives exist
- Assume no prior knowledge

## Getting Help

### Documentation
- Read the guides (you are here!)
- Check package-specific READMEs
- See code examples in docs/

### Community
- GitHub Issues: Report bugs, request features
- Pull Requests: Contribute code
- Discussions: Ask questions

### Resources
- [GitHub Repository](https://github.com/nfb2021/canvodpy)
- [Contributing Guide](../CONTRIBUTING.md)
- [TU Wien GEO](https://www.tuwien.at/mg/geo)

## Document Structure

This documentation consists of five interconnected guides:

```
index.md (you are here)
    ├── architecture.md        - Overall structure
    ├── tooling.md            - Tools explained
    ├── namespace-packages.md  - Namespace deep dive
    ├── development-workflow.md - Daily development
    └── build-system.md        - Building & publishing
```

**Suggested reading order:**

1. Start: index.md (overview)
2. Architecture → tooling → namespace-packages → development-workflow → build-system

**Or jump directly to what you need!**

## Next Steps

**Ready to dive in?**

- 🏗️ [Architecture Overview →](architecture.md) - Understand the big picture
- 🛠️ [Development Tooling →](tooling.md) - Master the tools
- 📦 [Namespace Packages →](namespace-packages.md) - Learn namespace packages
- 💻 [Development Workflow →](development-workflow.md) - Start coding
- 🔨 [Build System →](build-system.md) - Package building

**Or:**

- Clone the repo: `git clone https://github.com/nfb2021/canvodpy.git`
- Set up: `cd canvodpy && uv sync`
- Explore: Look around and start coding!

---

*This documentation was written for people who have never worked with monorepos, namespace packages, or modern Python tooling. If anything is unclear, please open an issue!*
