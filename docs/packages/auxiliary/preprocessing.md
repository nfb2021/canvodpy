# Preprocessing Pipeline

Before interpolation, auxiliary data must be restructured to match the `(epoch × sid)` layout of RINEX obs Datasets. This pipeline bridges the **sv** indexing of SP3/CLK files and the **sid** indexing of the obs Dataset.

---

## The Dimension Mismatch Problem

<div class="grid" markdown>

!!! info "SP3 / CLK files"
    Index by **satellite vehicle** (sv):

    ```python
    sp3_data.dims
    # {'epoch': 96, 'sv': 32}
    ```

    GPS G01 has one entry — one position per epoch.

!!! note "RINEX obs Dataset"
    Index by **signal ID** (sid):

    ```python
    rinex_data.dims
    # {'epoch': 2880, 'sid': 384}
    ```

    GPS G01 maps to ~20 Signal IDs (L1C, L2W, L5Q, …).

</div>

Satellite **position** is frequency-independent (all signals leave the same antenna), so the sv → sid mapping simply **replicates** each position across all signal IDs for that satellite.

---

## Pipeline Functions

| Function | Purpose | Input dims | Output dims |
|----------|---------|-----------|-------------|
| `preprocess_aux_for_interpolation()` | Minimal prep for interpolation | sv: 32 | sid: 896 |
| `prep_aux_ds()` | Full prep for Icechunk storage | sv: 32 | sid: ~4400 |
| `map_aux_sv_to_sid()` | Step 1: expand sv → sid | sv: 32 | sid: 896 |
| `pad_to_global_sid()` | Step 2: pad to all constellations | sid: 896 | sid: ~4400 |
| `normalize_sid_dtype()` | Step 3: convert to object dtype | — | dtype fixed |
| `strip_fillvalue()` | Step 4: remove `_FillValue` attrs | — | attrs cleaned |

---

## Step 1 — `map_aux_sv_to_sid()`

Each satellite position is **replicated** across all its signal IDs:

```python
from canvod.auxiliary.preprocessing import map_aux_sv_to_sid

sp3_sid = map_aux_sv_to_sid(sp3_data)

# G01 position is identical for every signal ID of G01
sp3_sid["X"].sel(sid="G01|L1|C")  # 12 345 678.9 m
sp3_sid["X"].sel(sid="G01|L2|W")  # 12 345 678.9 m  (same)
sp3_sid["X"].sel(sid="G01|L5|I")  # 12 345 678.9 m  (same)
```

Signal IDs generated for GPS G01 (28 total):

```
G01|L1|C  G01|L1|L  G01|L1|M  G01|L1|N  G01|L1|P  G01|L1|S  G01|L1|W
G01|L1|X  G01|L1|Y  G01|L1|p  G01|L1|u
G01|L2|C  G01|L2|D  G01|L2|L  G01|L2|M  G01|L2|N  G01|L2|P  G01|L2|S
G01|L2|W  G01|L2|X  G01|L2|Y  G01|L2|l  G01|L2|p  G01|L2|u
G01|L5|I  G01|L5|Q  G01|L5|X  G01|L5|u
```

Signal ID format: `"{SV}|{BAND}|{CODE}"` — e.g. `"G01|L1|C"`, `"E08|E5a|Q"`. Uppercase codes are RINEX 3 attributes; the lowercase codes are the [RINEX 2 tracking-code markers](../readers/rinex-v2-format.md#lowercase-tracking-code-markers) for signals whose code RINEX 2 does not record.

---

## Step 2 — `pad_to_global_sid()`

Pads the Dataset to include **all possible** Signal IDs across all supported constellations — every SV × band × code in the constellation `BAND_CODES` (4 429 at the time of writing). Signal IDs outside that set are dropped. Required for Icechunk storage, where sequentially appended datasets must share the same coordinate space.

```python
from canvod.auxiliary.preprocessing import pad_to_global_sid

sp3_global = pad_to_global_sid(sp3_sid)
sp3_global.sizes["sid"]   # 4429
```

Missing SIDs are filled with `NaN` — they carry no observations and are stripped during VOD computation.

---

## Step 3 — `normalize_sid_dtype()`

Converts the `sid` coordinate to `object` dtype for Zarr/Icechunk compatibility. Fixed-length Unicode string types (`<U12`, etc.) cause dtype conflicts when datasets from different files are concatenated and appended.

```python
from canvod.auxiliary.preprocessing import normalize_sid_dtype

ds = normalize_sid_dtype(ds)
ds["sid"].dtype   # dtype('O')
```

---

## Step 4 — `strip_fillvalue()`

Removes `_FillValue` attributes that conflict with Icechunk's internal missing-data handling. NaN is the standard missing-value marker throughout the pipeline.

```python
from canvod.auxiliary.preprocessing import strip_fillvalue

ds = strip_fillvalue(ds)
# No variable in ds.data_vars has a "_FillValue" encoding key
```

---

## Scientific Note

Replicating satellite positions across signal IDs is scientifically valid:

!!! success "Position is frequency-independent"
    All signals originate from the same satellite antenna phase centre.
    IGS SP3 final products have ~1 cm accuracy, with antenna offset
    corrections already applied. The replication introduces zero error.
