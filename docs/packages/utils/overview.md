# canvod-utils

## Purpose

The `canvod-utils` package provides configuration management and command-line tools for the canVODpy ecosystem. It implements a YAML-based configuration system with Pydantic validation and a CLI for managing settings.

## Configuration System

### File Structure

```
canvodpy/
  config/                              # User configuration (gitignored)
    processing.yaml                    # Processing parameters
    sites.yaml                         # Research site definitions
    sids.yaml                          # Signal ID selection
    processing.yaml.example            # Template
  packages/canvod-utils/
    src/canvod/utils/config/
      defaults/                        # Package defaults
        processing.yaml
        sites.yaml
        sids.yaml
```

User configuration overrides package defaults for any specified values.

### Processing Configuration

```yaml
# config/processing.yaml
metadata:
  author: Nicolas Francois Bader
  email: nicolas.bader@tuwien.ac.at
  institution: TU Wien

credentials:
  cddis_mail: your.email@example.com
  gnss_root_dir: /path/to/gnss/data

aux_data:
  agency: COD
  product_type: final

processing:
  time_aggregation_seconds: 15
  n_max_threads: 20
  keep_rnx_vars: [SNR]

icechunk:
  compression_level: 5
  compression_algorithm: zstd
  chunk_strategies:
    rinex_store:
      epoch: 34560
      sid: -1

storage:
  stores_root_dir: /path/to/stores
  rinex_store_strategy: skip
  vod_store_strategy: overwrite
```

### Sites Configuration

```yaml
# config/sites.yaml
sites:
  rosalia:
    base_dir: /path/to/rosalia
    receivers:
      reference_01:
        type: reference
        directory: 01_reference
      canopy_01:
        type: canopy
        directory: 02_canopy
    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

### Loading Configuration

```python
from canvod.utils.config import load_config

config = load_config()
author = config.processing.metadata.author
agency = config.processing.aux_data.agency
```

### Validation

All configuration values are validated by Pydantic models at load time. Invalid emails, nonexistent paths, and out-of-range parameters produce structured error messages.

```python
from canvod.utils.config.models import ProcessingParams

params = ProcessingParams(
    time_aggregation_seconds=15,  # Valid: 1-300
    n_max_threads=20,             # Valid: 1-100
)
```

## CLI Tools

The `canvodpy` command-line interface manages configuration files.

### Commands

```bash
canvodpy config init       # Copy templates to config/
canvodpy config validate   # Validate all configuration files
canvodpy config show       # Display current settings
canvodpy config edit processing  # Open in $EDITOR
```

### Initial Setup Workflow

```bash
canvodpy config init
canvodpy config edit processing   # Set metadata, paths, agency
canvodpy config edit sites        # Define research sites
canvodpy config validate          # Check for errors
```
