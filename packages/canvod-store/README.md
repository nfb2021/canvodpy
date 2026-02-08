# canvod-store

Icechunk storage for GNSS VOD data.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

This package provides versioned storage for GNSS data using Icechunk, managing:

- **RINEX Store (Level 1)**: Augmented observations per receiver
- **VOD Store (Level 2)**: Analysis products comparing receiver pairs

## Installation

```bash
pip install canvod-store
```

## Quick Start

```python
from canvod.store import create_rinex_store, GnssResearchSite
from pathlib import Path

# Create stores
rinex_store = create_rinex_store(Path("./rinex_store"))

# Or use site manager
site = GnssResearchSite(site_name="Rosalia")
```

## Features

- Automatic repository creation/connection
- Group management with validation
- Session management with context managers
- Integrated logging and metadata tracking
- Configurable compression and chunking
- Deduplication support

## Documentation

[Centralized documentation](../../docs/packages/store/overview.md)

## License

Apache License 2.0 - see LICENSE file
