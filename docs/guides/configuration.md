# Configuration Guide

canVODpy is configured through a single `config/canvod.yaml` file.

```bash
canvod config init    # scaffold canvod.yaml from template (includes recipe files)
canvod config validate
```

If you have an existing three-file setup (`processing.yaml` / `sites.yaml` / `sids.yaml`),
migrate it with:

```bash
canvod config migrate   # merges the trio → canvod.yaml, then review & remove old files
```

---

## File layout

```
config/
├── canvod.yaml          # unified configuration (processing, sites, sids)
├── .env                 # secrets — gitignored, loaded automatically
└── recipes/
    ├── rosalia_reference.yaml
    └── rosalia_canopy.yaml
```

---

## Environment variable overrides

Any field can be overridden at runtime via environment variables or a `config/.env`
file (automatically loaded, gitignored).  Prefix `CANVOD__`, use `__` for nesting:

| Variable | Overrides |
|---|---|
| `CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR` | `processing.storage.stores_root_dir` |
| `CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL` | `processing.credentials.nasa_earthdata_acc_mail` |

**Precedence:** env var > `.env` file > `canvod.yaml` > package defaults

---

## processing:

Controls metadata, resource allocation, storage, and auxiliary data settings.

```yaml
processing:
  metadata:
    author: Your Name
    email: your.email@example.com
    institution: Your Institution

  credentials:
    nasa_earthdata_acc_mail: null  # prefer .env instead — see env-var table above

  aux_data:
    agency: COD          # SP3/CLK product source
    product_type: final

  params:
    keep_rnx_vars: [SNR]           # RINEX variables to retain
    store_radial_distance: false   # store satellite distance (r)
    receiver_position_mode: shared # or per_receiver
    file_pairing: complete         # or paired
    ephemeris_source: final        # or broadcast (SBF only)
    days_per_batch: 1              # calendar days per loky wave (1–30)

    # --- Resource management ---
    resource_mode: auto            # auto or manual
    # n_max_threads: 4             # required if manual
    # max_memory_gb: 16            # soft RAM limit (manual only)
    # cpu_affinity: [0, 1, 2, 3]  # pin to CPU cores (Linux)
    # nice_priority: 10            # 0=normal, 19=lowest priority

  preprocessing:
    temporal_aggregation:
      enabled: true
      freq: "1min"                 # target time resolution
      method: mean                 # mean or median
    grid_assignment:
      enabled: true
      grid_type: equal_area
      angular_resolution: 2.0     # degrees

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
    stores_root_dir: /path/to/stores  # prefer CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR
    rinex_store_strategy: skip        # skip, overwrite, or append
    vod_store_strategy: overwrite
```

### Key fields

| Field | Values | Description |
|-------|--------|-------------|
| `params.receiver_position_mode` | `shared`, `per_receiver` | `shared` uses canopy receiver position for all receivers (enables 1:1 SNR comparison). `per_receiver` uses each receiver's own position. |
| `params.file_pairing` | `complete`, `paired` | `complete` ingests all files per receiver independently. `paired` only processes dates where both receivers have data. |
| `params.ephemeris_source` | `final`, `broadcast` | `final` uses SP3/CLK agency products (~3 cm, 12-18 day latency). `broadcast` uses SBF SatVisibility (SBF only, faster but ~1-2 m). |
| `params.days_per_batch` | 1–30 | Calendar days pooled per loky processing wave. |
| `params.resource_mode` | `auto`, `manual` | `auto` lets Dask detect available resources. `manual` uses explicit limits. See [Dask & Resource Management](dask-resources.md). |
| `params.store_radial_distance` | `true`, `false` | Whether to store satellite radial distance in the output. |

---

## sites:

Defines research sites, receivers, and VOD analysis pairs.
Top-level keys under `sites:` are site names (no nested `sites:` wrapper).

```yaml
sites:
  rosalia:
    gnss_site_data_root: /data/rosalia
    description: Mixed forest GNSS-T research site
    country: AT
    latitude: 47.7
    longitude: 16.3
    altitude_m: 680.0

    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        recipe: rosalia_reference     # → config/recipes/rosalia_reference.yaml
        reader_format: auto           # rinex3, sbf, or auto
        scs_from: all                 # 'all' or list of canopy receiver names
      canopy_01:
        type: canopy
        directory: 02_canopy
        recipe: rosalia_canopy
        reader_format: auto

    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

### Receiver fields

| Field | Default | Description |
|-------|---------|-------------|
| `recipe` | -- | Name of a NamingRecipe file in `config/recipes/`. See [canvod-virtualiconvname](../packages/naming/overview.md). |
| `reader_format` | `auto` | Force a specific reader: `rinex3`, `sbf`, or `auto` (detect from file). |
| `scs_from` | `all` | Which canopy receivers this reference is paired with. `all` pairs with every canopy receiver. |

---

## sids:

Controls which signal IDs (SIDs) to retain during processing.

Three modes are available:

| Mode | Behaviour |
|---|---|
| `all` | Keep every SID observed in the file — no filtering |
| `preset` | Use a named built-in list (see below) |
| `custom` | Keep only the SIDs you list explicitly |

=== "Default preset"

    The package ships one built-in preset: `default` — a curated 277-SID
    multi-GNSS list (GPS + Galileo + BeiDou MEO + GLONASS).

    Hard exclusions: no GEO, no IGSO, no augmentation signals
    (SBAS/IRNSS/QZSS), no GPS L2W.

    ```yaml
    sids:
      mode: preset
      preset: default
    ```

    This is the **package default**. Use `mode: all` to opt out and keep every observed SID.

=== "All signals"

    ```yaml
    sids:
      mode: all
    ```

=== "Custom list"

    ```yaml
    sids:
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
They live in `config/recipes/` and are referenced from `sites:` receivers via
the `recipe` field.

See [NamingRecipe](../packages/naming/overview.md#namingrecipe) for the full YAML
format and field reference.

`canvod config init` copies recipe templates to `config/recipes/` alongside `canvod.yaml`.

---

## Legacy three-file layout

If your project still uses `processing.yaml` / `sites.yaml` / `sids.yaml`, the
loader accepts them with a `DeprecationWarning`.  Migrate with:

```bash
canvod config migrate   # reads legacy trio, writes canvod.yaml
canvod config validate  # confirm it loaded correctly
rm config/processing.yaml config/sites.yaml config/sids.yaml
```
