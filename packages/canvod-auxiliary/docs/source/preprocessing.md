# Preprocessing Guide: sv → sid Conversion

Complete guide to auxiliary data preprocessing for GNSS VOD analysis.

## Overview

Preprocessing converts auxiliary data from satellite vehicle (sv) indexing to signal ID (sid) indexing, matching the structure of RINEX observation files. This is **critical** and must happen **before** interpolation.

## The Problem

**Dimension Mismatch:**

```python
# SP3/CLK files: indexed by satellite (sv)
sp3_data.dims  # {'epoch': 96, 'sv': 32}
sp3_data.sv.values  # ['G01', 'G02', ..., 'R24']

# RINEX files: indexed by signal (sid)
rinex_data.dims  # {'epoch': 2880, 'sid': 384}
rinex_data.sid.values  # ['G01|L1|C', 'G01|L2|W', ..., 'R24|G2|P']

# Interpolation expects sid dimension!
interpolator.interpolate(sp3_data, target_epochs)  # ❌ KeyError: 'sid'
```

**Root Cause:**
- Each satellite transmits on multiple frequencies and codes
- GPS G01 has ~20 signal IDs: L1 C/A, L1 P(Y), L2 C/A, L2 P(Y), L5 I, L5 Q, etc.
- SP3 has position for satellite G01, not for each signal
- Solution: Replicate G01 position across all 20 of its signal IDs

## Complete Workflow

```{mermaid}
graph LR
    A[SP3 File<br/>sv: 32] -->|Download| B[Raw Dataset]
    B -->|preprocess_aux_for<br/>_interpolation| C[sid: 384]
    C -->|interpolate| D[target epochs]
    D -->|match| E[RINEX<br/>sid: 384]

    style C fill:#fff3e0
```

**Step-by-step:**

```python
from canvod.auxiliary import Sp3File, preprocess_aux_for_interpolation
from canvod.auxiliary.interpolation import Sp3InterpolationStrategy, Sp3Config

# 1. Load raw SP3 data (sv dimension)
sp3_file = Sp3File.from_url(date, "CODE", "final")
sp3_data = sp3_file.to_dataset()
print(sp3_data.dims)  # {'epoch': 96, 'sv': 32}

# 2. ✅ CRITICAL: Preprocess BEFORE interpolation
sp3_sid = preprocess_aux_for_interpolation(sp3_data)
print(sp3_sid.dims)  # {'epoch': 96, 'sid': 384}

# 3. Now interpolation works
config = Sp3Config(use_velocities=True)
interpolator = Sp3InterpolationStrategy(config=config)
sp3_interp = interpolator.interpolate(sp3_sid, target_epochs)  # ✅ Works!
```

## Preprocessing Functions

### Quick Reference

| Function | Purpose | Input → Output |
|----------|---------|----------------|
| `preprocess_aux_for_interpolation()` | Minimal preprocessing | sv:32 → sid:384 |
| `prep_aux_ds()` | Full preprocessing | sv:32 → sid:~2000 |
| `map_aux_sv_to_sid()` | Step 1: sv→sid | sv:32 → sid:384 |
| `pad_to_global_sid()` | Step 2: pad | sid:384 → sid:~2000 |
| `normalize_sid_dtype()` | Step 3: dtype | dtype fix |
| `strip_fillvalue()` | Step 4: attrs | remove _FillValue |

### preprocess_aux_for_interpolation()

**Purpose:** Minimal preprocessing for interpolation workflows.

**What it does:**
- Converts sv → sid dimension only
- Replicates satellite data across all its signal IDs
- Fast, memory-efficient

**When to use:**
- Before interpolation
- When you don't need Icechunk storage
- Production pipelines

**Example:**
```python
from canvod.auxiliary import preprocess_aux_for_interpolation

sp3_data = sp3_file.to_dataset()  # {'epoch': 96, 'sv': 32}
sp3_sid = preprocess_aux_for_interpolation(sp3_data)  # {'epoch': 96, 'sid': 384}

# Ready for interpolation!
sp3_interp = interpolator.interpolate(sp3_sid, target_epochs)
```

### prep_aux_ds()

**Purpose:** Full 4-step preprocessing pipeline.

**What it does:**
1. Convert sv → sid
2. Pad to global sid list (all constellations)
3. Normalize sid dtype to object
4. Strip _FillValue attributes

**When to use:**
- Before Icechunk storage
- When you need global sid alignment
- When matching the standard preprocessing pipeline

**Example:**
```python
from canvod.auxiliary import prep_aux_ds

sp3_data = sp3_file.to_dataset()  # {'epoch': 96, 'sv': 32}
sp3_prep = prep_aux_ds(sp3_data)  # {'epoch': 96, 'sid': ~2000}

# Ready for Icechunk with proper padding and dtype
```

**Comparison:**
```python
# Minimal (for interpolation)
sp3_sid = preprocess_aux_for_interpolation(sp3_data)
sp3_sid.dims  # {'epoch': 96, 'sid': 384}

# Full (for Icechunk)
sp3_prep = prep_aux_ds(sp3_data)
sp3_prep.dims  # {'epoch': 96, 'sid': 1987}  # All possible sids
```

## The 4-Step Pipeline

### Step 1: map_aux_sv_to_sid()

**Expand each satellite to all its signal IDs.**

```python
from canvod.auxiliary.preprocessing import map_aux_sv_to_sid

# Input: One position per satellite
sp3_data['X'].sel(sv='G01')  # Single X value: 12345678.9 m

# Output: Same position replicated across all signal IDs
sp3_sid = map_aux_sv_to_sid(sp3_data)

sp3_sid['X'].sel(sid='G01|L1|C')  # 12345678.9 m
sp3_sid['X'].sel(sid='G01|L2|W')  # 12345678.9 m (same!)
sp3_sid['X'].sel(sid='G01|L5|I')  # 12345678.9 m (same!)
```

**GPS G01 signal IDs generated:**
```
['G01|L1|C', 'G01|L1|L', 'G01|L1|P', 'G01|L1|S', 'G01|L1|W', 'G01|L1|X', 'G01|L1|Y',
 'G01|L2|C', 'G01|L2|D', 'G01|L2|L', 'G01|L2|M', 'G01|L2|P', 'G01|L2|S', 'G01|L2|W',
 'G01|L2|X', 'G01|L2|Y', 'G01|L5|I', 'G01|L5|Q', 'G01|L5|X', 'G01|X1|X']
```

**Signal ID format:** `"{SV}|{BAND}|{CODE}"`
- SV: Satellite vehicle (G01, E02, R24)
- BAND: Frequency band (L1, L2, L5, E1, E5a, G1, G2)
- CODE: Tracking code (C, P, W, I, Q, X)

### Step 2: pad_to_global_sid()

**Pad to include all possible signal IDs across all constellations.**

```python
from canvod.auxiliary.preprocessing import pad_to_global_sid

# Before: Only sids present in SP3 file
sp3_sid.dims  # {'epoch': 96, 'sid': 384}  (32 svs × ~12 sids each)

# After: All possible sids (GPS + GLONASS + Galileo + BeiDou + ...)
sp3_padded = pad_to_global_sid(sp3_sid)
sp3_padded.dims  # {'epoch': 96, 'sid': 1987}

# New sids filled with NaN
sp3_padded['X'].sel(sid='C42|B1|I')  # NaN (BeiDou not in file)
```

**Why pad?**
- Ensures consistent dimension size for Icechunk appending
- Different RINEX files may have different constellations
- Icechunk requires matching dimensions across appends

**Global sid list includes:**
- GPS: G01-G32 × (L1, L2, L5) × (C, P, W, L, ...)
- GLONASS: R01-R24 × (G1, G2) × (C, P)
- Galileo: E01-E36 × (E1, E5a, E5b, E6) × (C, X, ...)
- BeiDou: C01-C63 × (B1, B2, B3) × (I, Q, X, ...)
- QZSS, IRNSS, SBAS: ...

**Total:** ~1987 signal IDs (actual number varies by KEEP_SIDS config)

### Step 3: normalize_sid_dtype()

**Convert sid coordinate to object dtype for Zarr/Icechunk compatibility.**

```python
from canvod.auxiliary.preprocessing import normalize_sid_dtype

# Before: Fixed-length Unicode string
sp3_padded.sid.dtype  # dtype('<U9')  (Unicode, 9 chars)

# After: Object array
sp3_normalized = normalize_sid_dtype(sp3_padded)
sp3_normalized.sid.dtype  # dtype('O')  (Object)
```

**Why object dtype?**
- Zarr struggles with fixed-length string types (`<U9`)
- Object arrays handle variable-length strings better
- Prevents dtype conflicts when appending to Icechunk
- Ensures consistent preprocessing across the pipeline

### Step 4: strip_fillvalue()

**Remove `_FillValue` attributes that conflict with Icechunk.**

```python
from canvod.auxiliary.preprocessing import strip_fillvalue

# Before: _FillValue attributes present
sp3_normalized['X'].attrs  # {'_FillValue': -999.0, ...}
sp3_normalized['X'].encoding  # {'_FillValue': -999.0, ...}

# After: _FillValue removed
sp3_clean = strip_fillvalue(sp3_normalized)
sp3_clean['X'].attrs  # {} (no _FillValue)
sp3_clean['X'].encoding  # {} (no _FillValue)
```

**Why remove _FillValue?**
- Icechunk handles missing data internally
- Conflicting _FillValue definitions cause errors
- NaN is the standard missing value marker
- Ensures consistent preprocessing across the pipeline

## Scientific Accuracy

### Data Replication

**Question:** Does replicating satellite positions across signal IDs introduce errors?

**Answer:** No, it's scientifically correct!

**Reasoning:**
- Satellite position is independent of signal frequency
- All signals from a satellite originate from the same antenna
- Position accuracy: ~1 cm (IGS final products)
- Antenna offset correction: ~mm (already applied in SP3)
- Signal-specific effects (ionosphere, multipath) are in RINEX, not SP3

**Verification:**
```python
# All sids for GPS G01 should have identical positions
sids_g01 = [sid for sid in sp3_sid.sid.values if sid.startswith('G01|')]

positions = [sp3_sid['X'].sel(sid=sid, epoch=epoch).values for sid in sids_g01]
assert all(pos == positions[0] for pos in positions)  # ✅ All identical
```

## Performance

**Timing breakdown (32 satellites → 384 sids):**

| Step | Time | Memory |
|------|------|--------|
| map_aux_sv_to_sid() | 0.08s | +20 MB |
| pad_to_global_sid() | 0.02s | +10 MB |
| normalize_sid_dtype() | 0.01s | +2 MB |
| strip_fillvalue() | 0.01s | 0 MB |
| **Total (prep_aux_ds)** | **0.12s** | **+32 MB** |

**Scaling:**
- Linear with number of epochs
- Independent of number of satellites (fixed sid expansion)
- Memory grows with (epochs × sids)

**Optimization tips:**
```python
# For interpolation only (faster)
sp3_sid = preprocess_aux_for_interpolation(sp3_data)  # 0.08s, +20 MB

# For Icechunk (slower, but required)
sp3_prep = prep_aux_ds(sp3_data)  # 0.12s, +32 MB
```

## Common Issues

### Issue 1: KeyError: 'sid' during interpolation

**Symptom:**
```python
sp3_interp = interpolator.interpolate(sp3_data, target_epochs)
# KeyError: 'sid'
```

**Cause:** Forgot to preprocess before interpolation.

**Solution:**
```python
sp3_sid = preprocess_aux_for_interpolation(sp3_data)  # ✅ Add this!
sp3_interp = interpolator.interpolate(sp3_sid, target_epochs)
```

### Issue 2: Dimension mismatch when matching

**Symptom:**
```python
matched = matcher.match(rinex_ds, sp3_interp)
# ValueError: dimensions don't align
```

**Cause:** RINEX has different sids than preprocessed SP3.

**Solution:**
```python
# Both must have same sids
assert set(rinex_ds.sid.values) <= set(sp3_sid.sid.values)  # Subset check
```

### Issue 3: Memory issues with large files

**Symptom:**
```python
sp3_prep = prep_aux_ds(large_sp3_data)
# MemoryError
```

**Cause:** Global sid padding creates ~2000 sids.

**Solution:**
```python
# For interpolation, use minimal preprocessing
sp3_sid = preprocess_aux_for_interpolation(sp3_data)  # Only 384 sids

# Or filter to specific systems
sp3_data = sp3_data.where(sp3_data.sv.str.startswith('G'), drop=True)  # GPS only
sp3_prep = prep_aux_ds(sp3_data)
```

## API Reference

See `api_reference.md` for complete function signatures and parameters.

**Main functions:**
- `preprocess_aux_for_interpolation(aux_ds, fill_value=np.nan, full_preprocessing=False)`
- `prep_aux_ds(aux_ds, fill_value=np.nan)`
- `map_aux_sv_to_sid(aux_ds, fill_value=np.nan)`
- `pad_to_global_sid(ds, keep_sids=None)`
- `normalize_sid_dtype(ds)`
- `strip_fillvalue(ds)`

## Next Steps

::::{grid} 2

:::{grid-item-card} 📈 Interpolation
:link: interpolation
:link-type: doc

Learn about Hermite splines after preprocessing
:::

:::{grid-item-card} 📦 Products
:link: products
:link-type: doc

Explore available SP3/CLK products
:::

::::
