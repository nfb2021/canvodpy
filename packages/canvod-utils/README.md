# canvod-utils

Utility functions and configuration management for canvodpy.

## Features

- **Type-safe configuration**: Pydantic models with validation
- **YAML-based config**: Human-readable configuration files
- **CLI tools**: Easy configuration management
- **API-ready**: Same models work for files and APIs

## Installation

```bash
uv pip install -e packages/canvod-utils
```

## Quick Start

### 1. Initialize Configuration

```bash
canvodpy config init
```

This creates:
- `config/processing.yaml` - Processing parameters and credentials
- `config/sites.yaml` - Research site definitions
- `config/sids.yaml` - Signal ID selection

### 2. Edit Configuration

```bash
# Edit in your preferred editor
canvodpy config edit processing
canvodpy config edit sites
canvodpy config edit sids
```

Or edit files directly:
- Set `gnss_root_dir` in `config/processing.yaml`
- Set `cddis_mail` (optional) for NASA CDDIS access
- Define your research sites in `config/sites.yaml`

### 3. Validate Configuration

```bash
canvodpy config validate
```

### 4. Use in Code

```python
from canvod.utils.config import load_config

# Load configuration
config = load_config()

# Access values
print(config.gnss_root_dir)
print(config.cddis_mail)
print(config.processing.aux_data.agency)

# FTP server selection (auto-detect based on cddis_mail)
servers = config.processing.aux_data.get_ftp_servers(config.cddis_mail)
for server_url, auth_email in servers:
    print(f"Server: {server_url}, Auth: {auth_email}")
```

## Configuration Structure

### processing.yaml

```yaml
credentials:
  cddis_mail: your.email@example.com  # Optional
  gnss_root_dir: /path/to/gnss/data

aux_data:
  agency: COD
  product_type: final

processing:
  time_aggregation_seconds: 15
  n_max_threads: 20
  keep_rnx_vars: [SNR]
  aggregate_glonass_fdma: true
```

### sites.yaml

```yaml
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

### sids.yaml

```yaml
mode: all  # all, preset, custom
# preset: gps_galileo
# custom_sids: [G01|L1|C, G01|L2|W, ...]
```

## CLI Commands

```bash
# Initialize configuration
canvodpy config init

# Validate configuration
canvodpy config validate

# Show current configuration
canvodpy config show
canvodpy config show --section processing

# Edit configuration
canvodpy config edit processing
canvodpy config edit sites
canvodpy config edit sids
```

## FTP Server Selection

- **If `cddis_mail` is set**: NASA CDDIS (primary) → ESA (fallback)
- **If `cddis_mail` is null**: ESA only (no authentication)
- ESA server is always available as fallback

## Configuration Priority

1. Package defaults (lowest priority)
2. User configuration files (highest priority)

## API-Ready Design

Same Pydantic models work for both local files and future API:

```python
# Local development (YAML files)
config = load_config()

# Future API usage (same models!)
@app.post("/process")
def process(config: CanvodConfig):
    return processor.run(config)
```

## Documentation

[Centralized documentation](../../docs/packages/utils/overview.md)

## Development

```bash
# Install dev dependencies
uv pip install -e "packages/canvod-utils[dev]"

# Run tests
pytest packages/canvod-utils/tests

# Lint and format
ruff check packages/canvod-utils
ruff format packages/canvod-utils
```
