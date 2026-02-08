# canvodpy

Umbrella package for unified GNSS VOD analysis.

## Overview

`canvodpy` is the unified entry point for the canVOD ecosystem. It provides
three levels of API:

- **Level 1:** One-line convenience functions (fastest path to results)
- **Level 2:** Object-oriented classes (structured workflows)
- **Level 3:** Low-level components (full control)

## Installation

```bash
# Installs canvodpy + all 7 sub-packages
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

## Included Packages

Installing canvodpy provides access to all 7 packages:

- **canvod.readers** -- RINEX file parsing (v3.04)
- **canvod.auxiliary** -- Auxiliary data (SP3, CLK) handling
- **canvod.grids** -- Hemisphere grid structures
- **canvod.store** -- Icechunk data storage
- **canvod.vod** -- VOD calculation algorithms
- **canvod.viz** -- 2D/3D visualization
- **canvod.utils** -- Shared utilities

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux | Full support | Recommended |
| macOS | Full support | Fully tested |
| Windows | WSL only | Native not supported (reserved `aux` name) |

## Configuration

Create a `.env` file in repository root (optional for NASA products):

```bash
# NASA CDDIS credentials (optional)
CDDIS_MAIL=your.email@example.com

# Data root directory (required)
GNSS_ROOT_DIR=/path/to/your/data
```

Without `.env`, canvodpy operates in ESA-only mode (COD, GFZ, ESA products).

## Documentation

[Centralized documentation](../docs/index.md)

## Development

See the [main repository README](../README.md) for workspace development setup.

## License

Apache License 2.0
