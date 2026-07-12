# canvod-config

## Purpose

The `canvod-config` package provides configuration management for the
canVODpy ecosystem — a YAML-based configuration system with Pydantic
validation, XDG-aware defaults, and bundled templates. It was split out of
`canvod-utils` so configuration has no dependency on the rest of the
processing stack.

---

## Configuration System

A single `canvod-settings.yaml` controls all aspects of a canVODpy deployment:

<div class="grid cards" markdown>

-   :fontawesome-solid-sliders: &nbsp; **`processing:`**

    ---

    Author metadata, NASA CDDIS credentials, auxiliary data agency,
    parallel processing limits, Icechunk compression, store strategies.

-   :fontawesome-solid-map-location-dot: &nbsp; **`sites:`**

    ---

    Research site definitions — data root paths, receiver types,
    directory layout, SCS expansion (`scs_from`), VOD analysis pairs.

-   :fontawesome-solid-broadcast-tower: &nbsp; **`sids:`**

    ---

    Signal ID (SID) filtering — `all`, a named `preset` (e.g. `default`),
    or a `custom` list of SIDs to retain.

</div>

User values override package defaults for any specified keys. Unset keys fall back to bundled defaults. Any field can also be overridden via environment variable or `config/.env` — see [Configuration Guide](../../guides/configuration.md).

---

## Where the settings file lives

`get_default_config_dir()` resolves the settings directory in this order:

1. A dev checkout — `{monorepo_root}/config`, if run from inside a canvodpy checkout
2. `$XDG_CONFIG_HOME/canvodpy` (or `~/.config/canvodpy` if unset) — everywhere else
3. Overridden explicitly via the `CANVOD_CONFIG_DIR` environment variable

`canvodpy doctor` reports which of these was used for the current run.

---

## Configuration File

```yaml
processing:
  metadata:
    author: Your Name
    email: your.email@example.com
    institution: Your Institution

  credentials:
    nasa_earthdata_acc_mail: null  # prefer config/.env instead

  aux_data:
    agency: COD
    product_type: final

  params:
    keep_rnx_vars: [SNR]
    store_radial_distance: false
    receiver_position_mode: shared     # or per_receiver
    file_pairing: complete             # or paired
    days_per_batch: 1
    resource_mode: auto
    # n_max_threads: 8       # manual mode only
    # max_memory_gb: 16      # manual mode only
    # cpu_affinity: [0, 1, 2, 3]
    # nice_priority: 10

  preprocessing:
    temporal_aggregation:
      enabled: true
      freq: "1min"
      method: mean
    grid_assignment:
      enabled: true
      grid_type: equal_area
      angular_resolution: 2.0

  compression:
    zlib: true
    complevel: 5

  icechunk:
    compression_level: 5
    compression_algorithm: zstd
    inline_threshold: 512
    get_concurrency: 1
    chunk_strategies:
      rinex_store: {epoch: 34560, sid: -1}
      vod_store:   {epoch: 34560, sid: -1}

  storage:
    stores_root_dir: /path/to/your/gnss/stores
    rinex_store_strategy: skip
    vod_store_strategy: overwrite

sites:
  rosalia:
    gnss_site_data_root: /path/to/rosalia
    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        recipe: rosalia_reference
        reader_format: auto
        scs_from: all
      canopy_01:
        type: canopy
        directory: 02_canopy
        recipe: rosalia_canopy
        reader_format: auto
    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01

sids:
  mode: preset
  preset: default
  # mode: all                 # keep every observed SID
  # mode: custom
  # custom_sids: ["G01|L1|C", "E01|E1|C"]
```

---

## Loading Configuration

```python
from canvod.config import load_config

config = load_config()

# Access any section
author  = config.processing.metadata.author
agency  = config.processing.aux_data.agency
n_cores = config.processing.params.n_max_threads
```

!!! tip "Validation at load time"

    All values are validated by Pydantic models. Invalid emails, non-existent paths,
    and out-of-range parameters produce structured error messages immediately
    — not at runtime hours into a long processing run.

---

## CLI Quick Reference

```bash
canvodpy config init                # Scaffold canvod-settings.yaml + recipe templates
canvodpy config init --interactive  # ...or answer a few questions instead of hand-editing YAML
canvodpy config validate            # Validate configuration
canvodpy config show                # Display resolved configuration
canvodpy config edit                # Open canvod-settings.yaml in $EDITOR
canvodpy doctor                     # Environment + config diagnostics (read-only)
```
