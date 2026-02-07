# canvodpy

**Umbrella Package for Unified GNSS VOD Analysis**

## What is canvodpy?

`canvodpy` is the unified entry point for the canVOD ecosystem - a modern
Python package for analyzing GNSS signals to estimate vegetation optical
depth (VOD). It provides three levels of API to match your needs:

- **Level 1:** One-line convenience functions (fastest path to results)
- **Level 2:** Object-oriented classes (structured workflows)
- **Level 3:** Low-level components (full control)

## Installation

```bash
# One command installs canvodpy + all 7 sub-packages
uv pip install canvodpy
```

## Quick Start

### Level 1: Simple (One-Liners)

```python
from canvodpy import process_date, calculate_vod

# Process one day of data
data = process_date("Rosalia", "2025001")

# Calculate VOD
vod = calculate_vod("Rosalia", "canopy_01", "reference_01", "2025001")
```

### Level 2: Object-Oriented (More Control)

```python
from canvodpy import Site, Pipeline

# Create site and pipeline
site = Site("Rosalia")
pipeline = site.pipeline(aux_agency="ESA", n_workers=8)

# Process data
data = pipeline.process_date("2025001")

# Or process multiple days
for date, datasets in pipeline.process_range("2025001", "2025007"):
    print(f"Processed {date}")
```

### Level 3: Low-Level (Full Control)

```python
from canvod.readers import Rnxv3Obs
from canvod.auxiliary import Sp3File, ClkFile
from canvod.store import GnssResearchSite
from canvodpy.orchestrator import PipelineOrchestrator

# Direct access to all internals
site = GnssResearchSite("Rosalia")
orchestrator = PipelineOrchestrator(site, n_max_workers=12)
# ... custom processing ...
```

## What's Included?

Installing canvodpy gives you access to all 7 packages:

- 📖 **canvod.readers** - RINEX file parsing (v3.04)
- 🛰️ **canvod.auxiliary** - Auxiliary data (SP3, CLK) handling
- 🌐 **canvod.grids** - Hemisphere grid structures
- 💾 **canvod.store** - Icechunk data storage
- 📊 **canvod.vod** - VOD calculation algorithms
- 🎨 **canvod.viz** - 2D/3D visualization
- 🔧 **canvod.utils** - Shared utilities

## Key Features

- ✅ Three-level API (simple → structured → advanced)
- ✅ Multi-receiver, multi-date orchestration
- ✅ Parallel processing (12+ workers default)
- ✅ Icechunk integration for efficient storage
- ✅ Multi-agency support (CODE, ESA, GFZ, JPL)
- ✅ Lazy imports (no circular dependencies)
- ✅ Comprehensive test suite with validated preprocessing

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux | ✅ Full support | Recommended |
| macOS | ✅ Full support | Fully tested |
| Windows | ⚠️ WSL only | Native not supported (reserved `aux` name) |

## Documentation

📚 **Full documentation:** [docs-site/packages/canvodpy/](../docs-site/packages/canvodpy/)

- [Overview](../docs-site/packages/canvodpy/overview.md) - Getting started
- [API Levels](../docs-site/packages/canvodpy/api-levels.md) - Understanding the 3 levels
- [Configuration](../docs-site/packages/canvodpy/configuration.md) - Sites & settings
- [Examples](../docs-site/packages/canvodpy/examples.md) - Real-world usage
- [Orchestrator](../docs-site/packages/canvodpy/orchestrator.md) - Internals

## Configuration

Create a `.env` file in repository root (optional for NASA products):

```bash
# NASA CDDIS credentials (optional)
CDDIS_MAIL=your.email@example.com

# Data root directory (required)
GNSS_ROOT_DIR=/path/to/your/data
```

Without `.env`, canvodpy works in **ESA-only mode** (COD, GFZ, ESA products).

## Development

See the [main repository README](../README.md) for workspace development setup.

## License

MIT License - see LICENSE file for details.
