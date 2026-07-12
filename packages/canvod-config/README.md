# canvod-config

Configuration models and YAML loading for canvodpy.

## Features

- **Type-safe configuration**: Pydantic models with validation
- **YAML-based config**: Human-readable configuration files
- **CLI tools**: Easy configuration management
- **API-ready**: Same models work for files and APIs

## Installation

```bash
uv pip install -e packages/canvod-config
```

## Quick Start

### 1. Initialize Configuration

```bash
just config-init
```

This creates:
- `config/processing.yaml` - Processing parameters and credentials
- `config/sites.yaml` - Research site definitions
- `config/sids.yaml` - Signal ID selection

### 2. Edit Configuration

```bash
# Edit in your preferred editor
just config-edit processing
just config-edit sites
just config-edit sids
```

Or edit files directly:
- Set `nasa_earthdata_acc_mail` (optional) in `config/processing.yaml` for NASA CDDIS access
- Set `gnss_site_data_root` per site in `config/sites.yaml`
- Define your research sites in `config/sites.yaml`

### 3. Validate Configuration

```bash
just config-validate
```

### 4. Use in Code

```python
from canvod.config import load_config

# Load configuration
config = load_config()

# Access values
print(config.nasa_earthdata_acc_mail)
print(config.processing.aux_data.agency)

# FTP server selection (auto-detect based on nasa_earthdata_acc_mail)
servers = config.processing.aux_data.get_ftp_servers(config.nasa_earthdata_acc_mail)
for server_url, auth_email in servers:
    print(f"Server: {server_url}, Auth: {auth_email}")
```

## Configuration Structure

### processing.yaml

```yaml
credentials:
  nasa_earthdata_acc_mail: your.email@example.com  # Optional

aux_data:
  agency: COD
  product_type: final

processing:
  resource_mode: auto
  keep_rnx_vars: [SNR]
  aggregate_glonass_fdma: true
```

### sites.yaml

```yaml
sites:
  rosalia:
    gnss_site_data_root: /path/to/rosalia
    receivers:
      reference_01:
        type: reference
        directory: 01_reference/01_GNSS/01_raw
      canopy_01:
        type: canopy
        directory: 02_canopy/01_GNSS/01_raw
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
just config-init

# Validate configuration
just config-validate

# Show current configuration
just config-show
uv run canvodpy config show --section processing  # filtered view

# Edit configuration
just config-edit processing
just config-edit sites
just config-edit sids
```

## FTP Server Selection

- **If `nasa_earthdata_acc_mail` is set**: NASA CDDIS (primary) → ESA (fallback)
- **If `nasa_earthdata_acc_mail` is null**: ESA only (no authentication)
- ESA server is always available as fallback

## Configuration Priority

1. Package defaults (lowest priority)
2. User configuration files (highest priority)

## Resolving the settings file location

Outside a canvodpy monorepo checkout (e.g. a standalone `pip install
canvod-config`), there's no `.git` to find, so `load_config()` falls back to
XDG: `$XDG_CONFIG_HOME/canvodpy`, or `~/.config/canvodpy` if that isn't set.
Two environment variables override this:

- `CANVOD_CONFIG_DIR` — directory containing `canvod-settings.yaml`
- `CANVOD_CONFIG_FILE` — an overlay YAML file merged on top

`canvodpy doctor` reports which of these was actually used for a given run.

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

[Full documentation](https://nfb2021.github.io/canvodpy/packages/config/overview/)

## Development

```bash
# From repo root
uv sync
uv run pytest packages/canvod-config/tests
just check
```
