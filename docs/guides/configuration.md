# Configuration Guide

canVODpy is configured through a single `config/canvod-settings.yaml` file.

Under the hood, configuration is handled by
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) —
a Python library that automatically reads configuration from YAML files **and**
environment variables using the same validated model, so you never have to parse
config files manually. Every field is type-checked when loaded: a typo in a field
name or a string where a number belongs is reported immediately, with the exact
location, instead of failing halfway through a processing run.

!!! tip "Why one file?"
    Everything lives in one `canvod-settings.yaml`: one place to look, one file to
    version-control, and edits that belong together (a new site plus its
    receivers) happen in a single atomic change. Earlier versions used three
    separate files — see [Legacy three-file layout](#legacy-three-file-layout)
    if you are migrating.

```bash
uv run canvodpy config init      # scaffold canvod-settings.yaml from template (includes recipe files)
uv run canvodpy config validate  # check the config against the Pydantic models
uv run canvodpy config show      # print the fully resolved configuration
```

Shortcuts: `just config-init`, `just config-validate`, `just config-show`.

If you have an existing three-file setup (`processing.yaml` / `sites.yaml` / `sids.yaml`),
migrate it with:

```bash
uv run canvodpy config migrate   # merges the trio → canvod-settings.yaml, then review & remove old files
```

---

## File layout

```
config/
├── canvod-settings.yaml          # unified configuration (processing, sites, sids)
└── recipes/                      # optional — only needed with canvod-filemap
    ├── my_site_reference.yaml
    └── my_site_canopy.yaml
```

**Precedence:** environment variable > `canvod-settings.yaml` > package defaults.

You only need to write the fields you want to change — anything you omit falls
back to the package defaults. Unknown field names are rejected
(`extra="forbid"`), so typos are caught at load time instead of being silently
ignored.

Two loader-level environment variables control *where* configuration is read from:

| Variable | Effect |
|---|---|
| `CANVOD_CONFIG_DIR` | Use a different config directory (default: `{repo_root}/config`) |
| `CANVOD_CONFIG_FILE` | Apply an overlay YAML on top of the main config (also available as `--config` on the CLI) |

---

## Environment variable overrides

To override any config value **without editing the file**, set an environment
variable with the `CANVOD__` prefix, using double underscores (`__`) to separate
nesting levels. This is especially useful on HPC clusters or shared servers,
where you want to change resource limits per job without touching a
version-controlled file:

```bash
CANVOD__PROCESSING__PARAMS__N_MAX_THREADS=4 uv run canvodpy run ...
CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7 uv run canvodpy run ...
```

| Variable | Overrides |
|---|---|
| `CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR` | `processing.storage.stores_root_dir` |
| `CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL` | `processing.credentials.nasa_earthdata_acc_mail` |
| `CANVOD__PROCESSING__PARAMS__N_MAX_THREADS` | `processing.params.n_max_threads` |

Environment variables always take priority over values in `canvod-settings.yaml`.

---

## Minimal working example

A complete, valid `canvod-settings.yaml` needs only the required fields — everything
else uses package defaults:

```yaml
processing:
  metadata:
    author: Jane Scientist
    email: jane.scientist@example.edu
    institution: Example University

  storage:
    stores_root_dir: /data/stores

sites:
  mysite:
    gnss_site_data_root: /data/mysite

    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        paired_canopies: all
      canopy_01:
        type: canopy
        directory: 02_canopy

    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

---

## processing:

Controls metadata, resource allocation, storage, and auxiliary data settings.

```yaml
processing:
  metadata:
    author: Your Name
    email: your.email@example.com
    institution: Your Institution
    # optional: orcid, institution_ror, department, research_group,
    # website, license, publisher, publisher_url, naming_authority

  credentials:
    nasa_earthdata_acc_mail: null  # prefer the env var — see table above

  aux_data:
    agency: COD          # SP3/CLK analysis center code
    product_type: final  # final, rapid, or ultra-rapid

  params:
    keep_gnss_observables: [SNR]   # observables to keep (SNR, Pseudorange, Phase, Doppler)
    store_radial_distance: false   # store satellite distance (r)
    receiver_position_mode: shared # or per_receiver
    file_pairing: complete         # or paired
    ephemeris_source: final        # or broadcast (SBF only)
    days_per_batch: 1              # calendar days per processing wave (1–30)

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

  netcdf_compression:              # NetCDF output from RINEX readers
    zlib: true
    complevel: 5

  icechunk:
    compression_level: 3
    compression_algorithm: zstd
    inline_chunk_threshold_bytes: 512
    chunk_strategies:
      gnss_store:
        epoch: 34560
        sid: -1
      vod_store:
        epoch: 34560
        sid: -1

  storage:
    stores_root_dir: /path/to/stores  # prefer CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR
    gnss_store_strategy: skip         # skip, overwrite, or append
    vod_store_strategy: overwrite
```

### Key fields

| Field | Values | Description |
|-------|--------|-------------|
| `params.keep_gnss_observables` | list | GNSS observables to retain (default `[SNR]`). |
| `params.receiver_position_mode` | `shared`, `per_receiver` | `shared` uses canopy receiver position for all receivers (enables 1:1 SNR comparison). `per_receiver` uses each receiver's own position. |
| `params.file_pairing` | `complete`, `paired` | `complete` ingests all files per receiver independently. `paired` only processes dates where both receivers have data. |
| `params.ephemeris_source` | `final`, `broadcast` | `final` computes satellite positions from agency SP3/CLK products. `broadcast` uses ephemerides from SBF SatVisibility blocks (SBF only, no SP3/CLK download, faster but less accurate). |
| `params.days_per_batch` | 1–30 | Calendar days pooled per parallel processing wave. |
| `params.resource_mode` | `auto`, `manual` | `auto` detects available CPU cores and leaves two free for the operating system. `manual` enforces explicit limits (`n_max_threads` is then required) — use this on shared servers. |
| `params.store_radial_distance` | `true`, `false` | Whether to store satellite radial distance in the output. |

### Ephemeris data sources

Agency SP3/CLK products are downloaded from **ESA GSSC** by default — no
account or credentials required. If you set
`credentials.nasa_earthdata_acc_mail` (a registered NASA Earthdata email),
**NASA CDDIS** is tried first, with ESA GSSC as fallback.

---

## sites:

Defines research sites, receivers, and VOD analysis pairs.
Top-level keys under `sites:` are site names (no nested `sites:` wrapper).

```yaml
sites:
  my_site:
    gnss_site_data_root: /data/my_site
    description: null        # optional free-text description
    country: null            # ISO 3166-1 alpha-2, e.g. AT
    latitude: null           # WGS84 decimal degrees
    longitude: null
    altitude_m: null         # metres above WGS84 ellipsoid

    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        reader_format: auto           # rinex3, sbf, or auto
        paired_canopies: all          # 'all' or list of canopy receiver names
        # recipe: my_site_reference   # optional — requires canvod-filemap
      canopy_01:
        type: canopy
        directory: 02_canopy
        reader_format: auto
        # recipe: my_site_canopy

    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

### Receiver fields

| Field | Default | Description |
|-------|---------|-------------|
| `type` | -- | `reference` or `canopy`. |
| `directory` | -- | Subdirectory under `gnss_site_data_root` holding this receiver's files. |
| `recipe` | -- | Name of a NamingRecipe file in `config/recipes/`. Maps non-canonical physical filenames to canVOD canonical names. Requires [`canvod-filemap`](https://github.com/nfb2021/canvodpy-extensions) (optional external package). Omit if your files already follow the canVOD naming convention. |
| `reader_format` | `auto` | Force a specific reader: `rinex3`, `sbf`, or `auto` (detect from file). |
| `paired_canopies` | -- | Which canopy receivers this reference is paired with: `all` or a list of canopy receiver names. Required for reference receivers, must not be set for canopy receivers. (The old name `scs_from` is deprecated and still accepted with a warning.) |

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

!!! note "Optional — requires `canvod-filemap`"
    Recipe files are only needed if your GNSS data files use non-canonical
    filenames (e.g. RINEX v2 short names, custom directory layouts).
    If your files already follow the canVOD naming convention, skip this section.
    Install from [canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions).

NamingRecipe files define how to parse physical filenames into canonical names.
They live in `config/recipes/` and are referenced from `sites:` receivers via
the `recipe` field. When `canvod-filemap` is installed, the pipeline
picks up the recipe at runtime — no other code change needed.

---

## Validating configuration and data

Two separate validation steps exist — one for the config file, one for the
data directories it points to:

**Config validation** runs your `canvod-settings.yaml` through the Pydantic models and
reports any field errors (wrong types, missing required fields, unknown keys),
then checks that each receiver directory exists and contains data files:

```bash
just config-validate           # = uv run canvodpy config validate
```

**Data directory validation** checks the *file names* inside a receiver
directory against the canVOD naming convention — before any processing starts:

```bash
canvod-preflight validate /data/rosalia/02_canopy \
    --site ROS --agency TUW --receiver 1 --role canopy
```

Shortcut for a configured site: `just config-check-data <site>`.

---

## Legacy three-file layout

If your project still uses `processing.yaml` / `sites.yaml` / `sids.yaml`, the
loader **no longer accepts them** — it requires `canvod-settings.yaml` and will
raise an error if that file is absent. Use the migrate command to consolidate:

```bash
uv run canvodpy config migrate   # reads legacy trio, writes canvod-settings.yaml
uv run canvodpy config validate  # confirm it loaded correctly
rm config/processing.yaml config/sites.yaml config/sids.yaml
```
