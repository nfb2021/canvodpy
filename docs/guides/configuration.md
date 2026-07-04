# Configuration Guide

canVODpy is configured through three YAML files in the `config/` directory.
Run `just config-init` to create them from templates (including recipe files).

---

## processing.yaml

Controls processing behaviour, resource allocation, and storage.

```yaml
metadata:
  author: Your Name
  email: your.email@example.com
  institution: Your Institution

credentials:
  nasa_earthdata_acc_mail: null  # required for NASA CDDIS FTP

aux_data:
  agency: COD          # SP3/CLK product source
  product_type: final

processing:
  keep_rnx_vars: [SNR]              # RINEX variables to retain
  aggregate_glonass_fdma: true       # merge GLONASS FDMA bands
  store_radial_distance: false       # store satellite distance (r)
  receiver_position_mode: shared     # or per_receiver
  file_pairing: complete             # or paired
  batch_hours: 24                    # hours per processing batch

  # --- Resource management ---
  resource_mode: auto                # auto or manual
  # n_max_threads: 4                 # required if manual
  # max_memory_gb: 16                # soft RAM limit (manual only)
  # threads_per_worker: 1            # threads per Dask worker
  # cpu_affinity: [0, 1, 2, 3]      # pin to CPU cores (Linux)
  # nice_priority: 10                # 0=normal, 19=lowest priority

preprocessing:
  temporal_aggregation:
    enabled: true
    freq: "1min"                     # target time resolution
    method: mean                     # mean or median
  grid_assignment:
    enabled: true
    grid_type: equal_area
    angular_resolution: 2.0          # degrees

compression:
  zlib: true
  complevel: 5

icechunk:
  compression_level: 5
  compression_algorithm: zstd
  inline_threshold: 512
  chunk_strategies:
    rinex_store:
      epoch: 34560
      sid: -1
    vod_store:
      epoch: 34560
      sid: -1

storage:
  stores_root_dir: /path/to/stores
  rinex_store_strategy: skip         # skip or overwrite
  vod_store_strategy: overwrite
```

### Key fields

| Field | Values | Description |
|-------|--------|-------------|
| `receiver_position_mode` | `shared`, `per_receiver` | `shared` uses canopy receiver position for all receivers (enables 1:1 SNR comparison). `per_receiver` uses each receiver's own position. |
| `file_pairing` | `complete`, `paired` | `complete` ingests all files per receiver independently. `paired` only processes dates where both receivers have data. |
| `resource_mode` | `auto`, `manual` | `auto` lets Dask detect available resources. `manual` uses explicit limits. See [Dask & Resource Management](dask-resources.md). |
| `store_radial_distance` | `true`, `false` | Whether to store satellite radial distance in the output. |

---

## sites.yaml

Defines research sites, receivers, and VOD analysis pairs.

```yaml
sites:
  rosalia:
    base_dir: /data/rosalia
    receivers:
      reference_01:
        type: reference
        directory: 01_reference/01_GNSS/01_raw
        recipe: rosalia_reference.yaml     # naming recipe
        reader_format: rinex3              # rinex3, sbf, or auto
      canopy_01:
        type: canopy
        directory: 02_canopy/01_GNSS/01_raw
        recipe: rosalia_canopy.yaml
        reader_format: auto
        scs_from: null                     # use own position
      canopy_02:
        type: canopy
        directory: 02_canopy/02_GNSS/01_raw
        scs_from: canopy_01               # share position with canopy_01
    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

### Receiver fields

| Field | Default | Description |
|-------|---------|-------------|
| `recipe` | -- | Path to a NamingRecipe YAML file. See [canvod-virtualiconvname](../packages/naming/overview.md). |
| `reader_format` | `auto` | Force a specific reader: `rinex3`, `sbf`, or `auto` (detect from file). |
| `scs_from` | `null` | Use another receiver's position for spherical coordinate computation. |

---

## sids.yaml

Controls which signal IDs (SIDs) to retain during processing.

Three modes are available:

| Mode | Behaviour |
|---|---|
| `all` | Keep every SID observed in the file — no filtering |
| `preset` | Use a named built-in list (see below) |
| `custom` | Keep only the SIDs you list explicitly |

=== "All signals"

    ```yaml
    mode: all
    ```

=== "Default preset"

    The package ships one built-in preset: `default` — a curated 277-SID
    multi-GNSS list (GPS + Galileo + BeiDou MEO + GLONASS).

    Hard exclusions: no GEO, no IGSO, no augmentation signals
    (SBAS/IRNSS/QZSS), no GPS L2W.

    ```yaml
    mode: preset
    preset: default
    ```

    This is the **package default** when no `config/sids.yaml` is present.
    Use `mode: all` to opt out and keep every observed SID.

=== "Custom list"

    ```yaml
    mode: custom
    custom_sids:
      - "G01|L1|C"
      - "E01|E1|C"
    ```

### Release maintenance

The `default` preset is a static file bundled with the package
(`canvod/utils/config/presets/default.yaml`).
**It must be reviewed and updated at every new software release** to reflect
constellation changes since the previous release:

- New satellites launched and declared operational
- Satellites decommissioned or moved to a different orbit type
- Orbit reclassifications (e.g. IGSO → MEO)
- New signal codes added to the RINEX 3 spec

The authoritative source is the [IGS satellite metadata SINEX file](https://files.igs.org/pub/station/general/igs_satellite_metadata.snx)
(updated every 2–4 weeks by DLR/IGS) and the bundled
`SatelliteCatalog` in `canvod-readers`.  Cross-check `active_prns(on_date)`
against the current preset and apply the same exclusion rules (no GEO, no
IGSO, no augmentation, no GPS L2W) when adding new entries.

---

## Recipe files

NamingRecipe files define how to parse physical filenames into canonical names.
They live alongside configuration files and are referenced from `sites.yaml` via
the `recipe` field.

See [NamingRecipe](../packages/naming/overview.md#namingrecipe) for the full YAML
format and field reference.

When you run `just config-init`, recipe templates are copied to `config/` along
with the YAML configuration files.
