# Preprocessing Pipeline

## Overview

Preprocessing converts auxiliary data from satellite vehicle (sv) indexing to signal ID (sid) indexing, aligning it with the structure of RINEX observation data. This step is required before interpolation.

## Dimension Mismatch

SP3 and CLK files index data by satellite vehicle (sv), while RINEX files index by signal ID (sid). Each satellite transmits on multiple frequencies and codes, so GPS satellite G01 maps to approximately 20 signal IDs.

```python
sp3_data.dims   # {'epoch': 96, 'sv': 32}
rinex_data.dims # {'epoch': 2880, 'sid': 384}
```

## Pipeline Functions

| Function | Purpose | Transformation |
|----------|---------|----------------|
| `preprocess_aux_for_interpolation()` | Minimal preprocessing for interpolation | sv:32 -> sid:384 |
| `prep_aux_ds()` | Full preprocessing for Icechunk storage | sv:32 -> sid:~2000 |
| `map_aux_sv_to_sid()` | Step 1: sv to sid conversion | sv:32 -> sid:384 |
| `pad_to_global_sid()` | Step 2: pad to all constellations | sid:384 -> sid:~2000 |
| `normalize_sid_dtype()` | Step 3: convert to object dtype | dtype fix |
| `strip_fillvalue()` | Step 4: remove _FillValue attributes | attribute cleanup |

## Step 1: map_aux_sv_to_sid()

Each satellite position is replicated across all its signal IDs:

```python
from canvod.auxiliary.preprocessing import map_aux_sv_to_sid

sp3_sid = map_aux_sv_to_sid(sp3_data)

# G01 position replicated across all signal IDs
sp3_sid['X'].sel(sid='G01|L1|C')  # 12345678.9 m
sp3_sid['X'].sel(sid='G01|L2|W')  # 12345678.9 m (identical)
sp3_sid['X'].sel(sid='G01|L5|I')  # 12345678.9 m (identical)
```

Signal IDs generated for GPS G01:
```
['G01|L1|C', 'G01|L1|L', 'G01|L1|P', 'G01|L1|S', 'G01|L1|W', 'G01|L1|X', 'G01|L1|Y',
 'G01|L2|C', 'G01|L2|D', 'G01|L2|L', 'G01|L2|M', 'G01|L2|P', 'G01|L2|S', 'G01|L2|W',
 'G01|L2|X', 'G01|L2|Y', 'G01|L5|I', 'G01|L5|Q', 'G01|L5|X', 'G01|X1|X']
```

Signal ID format: `"{SV}|{BAND}|{CODE}"`
- SV: Satellite vehicle (G01, E02, R24)
- BAND: Frequency band (L1, L2, L5, E1, E5a, G1, G2)
- CODE: Tracking code (C, P, W, I, Q, X)

## Step 2: pad_to_global_sid()

Pads the dataset to include all possible signal IDs across all constellations (~1987 total). This ensures consistent dimensions for Icechunk storage, where appended datasets must share the same coordinate space.

## Step 3: normalize_sid_dtype()

Converts the sid coordinate to object dtype for Zarr/Icechunk compatibility. Fixed-length Unicode string types cause dtype conflicts during sequential appends.

## Step 4: strip_fillvalue()

Removes `_FillValue` attributes that conflict with Icechunk's internal missing-data handling. NaN serves as the standard missing value marker.

## Scientific Correctness of Data Replication

Replicating satellite positions across signal IDs is scientifically valid: satellite position is independent of signal frequency. All signals originate from the same antenna. Position accuracy of IGS final products is approximately 1 cm, and antenna offset corrections at the millimeter level are already applied in SP3 files.

