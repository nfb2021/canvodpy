# Quickstart — Retrieve VOD

Install canVODpy like any other Python package:

```bash
uv add canvodpy    # or: pip install canvodpy
```

Then follow the two steps below — configure the project and run your first pipeline day.

---

## 1. Configure the project

canVODpy is configured through a **single YAML file** — `config/canvod-settings.yaml`, located in the project root's `config/` directory — with three sections:

| Section       | Purpose                                                                                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sites:`      | Research sites: data root paths, receiver definitions (name, type, directory), and VOD analysis pairs. Each receiver's `directory` is relative to the site's `gnss_site_data_root`.   |
| `processing:` | Processing parameters: metadata, credentials (NASA Earthdata), auxiliary data settings (agency, product type), time aggregation, compression, Icechunk storage, and store strategies. |
| `sids:`       | Signal ID (SID) filtering: choose `all`, a named `preset` (e.g. `default`), or list `custom` SIDs to keep.                                                                            |

To initialize from the template:

```bash
just config-init          # runs: uv run canvodpy config init
```

After editing, validate your configuration:

```bash
just config-validate      # runs: uv run canvodpy config validate
```

To view the resolved configuration:

```bash
just config-show          # runs: uv run canvodpy config show
```

!!! note "Overriding config without editing files"

    Every setting in `canvod-settings.yaml` can also be overridden by an environment
    variable with the `CANVOD__` prefix (note the **double** underscores, which
    separate nesting levels). This is useful on HPC clusters or in CI, where
    editing a config file per job is impractical. For example:

    ```bash
    export CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7
    export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL="you@example.com"
    ```

    Environment variables take priority over values in the YAML file.
    See the [Configuration Guide](configuration.md) for the full reference.

---

## 2. Process your first day of data

Once your `canvod-settings.yaml` points to a site with GNSS data, you can run the pipeline.

### Check your data first (pre-flight)

Before processing, validate that your data files match the expected
[naming convention](configuration.md) with the standalone `canvod-preflight` tool:

```bash
canvod-preflight validate <path/to/your/data-dir>
```

This checks every file in the directory against the GNSS file naming convention
(`{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}`)
and reports mismatches **before** they cause cryptic errors mid-pipeline.

### Dates: the `YYYYDDD` format

canVODpy identifies days by **year + Day of Year (DOY)**: a 7-digit string
`YYYYDDD`, where `DDD` counts days from 001. For example, `"2025001"` is
1 January 2025 and `"2025032"` is 1 February 2025. This is the standard
date convention in GNSS data products.

### Run it

The simplest entry point (API level L1):

```python
from canvodpy import process_date

data = process_date("Rosalia", "2025001")   # site name from canvod-settings.yaml, 1 Jan 2025
```

For more control, create a `Site` and configure the pipeline explicitly:

```python
from canvodpy import Site

site = Site("Rosalia")
pipeline = site.pipeline()          # options like n_workers default to config values
data = pipeline.process_date("2025001")
```

This reads the raw files, augments them with satellite positions (ephemeris),
and writes the results to the site's Icechunk store. If you prefer a
step-by-step chain (API level L2):

```python
import canvodpy

result = (
    canvodpy.workflow("Rosalia")
    .read("2025001")
    .augment()
    .grid()
    .vod("canopy_01", "reference_01")
    .result()
)
```

!!! info "Ephemeris downloads"

    Satellite orbit products (SP3/CLK) are downloaded automatically from
    **ESA GSSC** (no account needed). If you configure NASA Earthdata (CDDIS)
    credentials in `canvod-settings.yaml`, NASA is tried first with ESA as fallback.

---

**Next steps:** [Configuration Guide](configuration.md) · [API Levels](api-levels.md)
