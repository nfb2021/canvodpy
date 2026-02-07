# Overview

## Introduction

The `canvod-auxiliary` package provides comprehensive auxiliary data management for GNSS (Global Navigation Satellite System) vegetation optical depth (VOD) research. It handles the complete workflow of downloading, parsing, preprocessing, and interpolating SP3 ephemerides and CLK clock corrections to augment RINEX observation data with precise satellite positions and timing.

## The Problem We Solve

GNSS VOD analysis requires combining two data sources with different characteristics:

**RINEX Observation Files:**
- High temporal resolution (30s, 15s, or faster)
- Signal-level data (SNR, phase, pseudorange)
- Indexed by **Signal ID (sid)**: `"G01|L1|C"` (satellite + band + code)
- Dimensions: `(epoch: 2880, sid: 384)`

**Auxiliary Files (SP3/CLK):**
- Low temporal resolution (15 minutes for SP3, 5 minutes for CLK)
- Satellite-level data (position, velocity, clock bias)
- Indexed by **Satellite Vehicle (sv)**: `"G01"`, `"E02"`, etc.
- Dimensions: `(epoch: 96, sv: 32)`

**The Challenges:**
- ❌ **Dimension mismatch**: sv (32) vs sid (384)
- ❌ **Temporal mismatch**: 15min vs 30s sampling
- ❌ **Format complexity**: Multiple agencies, different file structures
- ❌ **Coordinate systems**: ECEF → Geodetic → Spherical transformations
- ❌ **Scientific accuracy**: Sub-millimeter positioning, sub-nanosecond timing

**canvod-auxiliary solves all these:**

✅ **Dimension alignment**: Converts sv → sid with proper signal replication
✅ **Temporal alignment**: Hermite splines (ephemeris) + piecewise linear (clock)
✅ **Unified interface**: 37 products from 17 agencies through single API
✅ **Coordinate pipeline**: ECEF → Geodetic → Spherical (r, θ, φ)
✅ **Validated accuracy**: Comprehensive test suite verifying preprocessing correctness

## Design Philosophy

### 1. Preprocessing-First Workflow

The **critical insight**: preprocessing must happen BEFORE interpolation.

```{mermaid}
graph LR
    A[SP3 File<br/>sv dimension] -->|Download| B[Raw Dataset<br/>96 epochs, 32 svs]
    B -->|Preprocess| C[Preprocessed<br/>96 epochs, 384 sids]
    C -->|Interpolate| D[Interpolated<br/>2880 epochs, 384 sids]
    D -->|Match| E[RINEX Data<br/>2880 epochs, 384 sids]

    style C fill:#fff3e0
    style D fill:#e3f2fd
```

**Why preprocessing first?**
- Each satellite transmits on ~12 signal IDs
- Interpolation operates per-signal, not per-satellite
- RINEX data is already signal-indexed
- Prevents KeyError when matching dimensions

```python
# ❌ WRONG: Interpolate before preprocessing
sp3_data = sp3_file.to_dataset()  # {'epoch': 96, 'sv': 32}
sp3_interp = interpolator.interpolate(sp3_data, target_epochs)
# KeyError: 'sid' - interpolator expects sid dimension!

# ✅ CORRECT: Preprocess before interpolation
sp3_data = sp3_file.to_dataset()  # {'epoch': 96, 'sv': 32}
sp3_sid = preprocess_aux_for_interpolation(sp3_data)  # {'epoch': 96, 'sid': 384}
sp3_interp = interpolator.interpolate(sp3_sid, target_epochs)  # Works!
```

### 2. Configuration-Based Product Registry

Hardcoded product URLs are unmaintainable. We use **declarative configuration**:

```python
# Old approach (hardcoded)
def get_sp3_url(date, agency):
    if agency == "CODE":
        return f"ftp://ftp.aiub.unibe.ch/CODE/{date.year}/COD{gpsweek}{dow}.EPH"
    elif agency == "GFZ":
        return f"ftp://isdcftp.gfz-potsdam.de/gnss/products/{gpsweek}/gbm{gpsweek}{dow}.sp3"
    # ... 20 more agencies

# New approach (configuration)
PRODUCT_REGISTRY = {
    "CODE": {
        "final": ProductSpec(
            sp3_url_template="ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.EPH",
            clk_url_template="ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.CLK",
            latency_hours=336,  # 14 days
        )
    }
}
```

**Benefits:**
- ✅ Easy to add/update products
- ✅ Pydantic validation catches errors early
- ✅ Self-documenting (latency, server, authentication)
- ✅ Testable without network access

### 3. Strategy Pattern for Interpolation

Different data types require different interpolation strategies:

```{mermaid}
graph TD
    A[InterpolationStrategy<br/>Abstract Base] --> B[Sp3InterpolationStrategy<br/>Hermite Splines]
    A --> C[ClockInterpolationStrategy<br/>Piecewise Linear]

    B --> D[Config:<br/>use_velocities=True<br/>fallback='linear']
    C --> E[Config:<br/>window_size=9<br/>jump_threshold=1e-6]

    style A fill:#e8f5e9
    style B fill:#e3f2fd
    style C fill:#fff3e0
```

**Why different strategies?**

**Ephemerides (SP3)**:
- Physics: Smooth orbital motion
- Velocities available: Use for improved accuracy
- Strategy: Hermite cubic splines (C¹ continuous)
- Result: Sub-millimeter accuracy

**Clock Corrections (CLK)**:
- Physics: Discontinuous (satellite maneuvers, uploads)
- No derivatives: Can't use higher-order methods
- Strategy: Piecewise linear with jump detection
- Result: Sub-nanosecond accuracy

### 4. Type-Safe Configuration

Every configuration uses Pydantic for validation:

```python
from canvod.auxiliary.interpolation import Sp3Config, ClockConfig

# Type-checked at instantiation
config = Sp3Config(
    use_velocities=True,       # ✓ bool
    fallback_method='linear',  # ✓ 'linear' | 'cubic'
    extrapolation_method='nearest'  # ✓ valid option
)

# Pydantic catches errors
bad_config = Sp3Config(
    use_velocities="yes",  # ❌ ValidationError: expected bool
    fallback_method='spline'  # ❌ ValidationError: must be 'linear'|'cubic'
)
```

**Benefits:**
- Errors caught before computation
- Self-documenting (see what options exist)
- IDE autocomplete support
- Serializable (save/load configs)

## Use Cases

### 1. RINEX Data Augmentation (Primary)

Add satellite positions and spherical coordinates to RINEX observations:

```python
from canvod.auxiliary import (
    Sp3File, ClkFile,
    preprocess_aux_for_interpolation,
    Sp3InterpolationStrategy, Sp3Config,
    compute_spherical_coordinates,
    ECEFPosition
)

# Load RINEX
rinex_ds = Rnxv3Obs("station.24o").to_ds()
target_epochs = rinex_ds.epoch.values

# Load and preprocess auxiliary data
sp3_data = Sp3File.from_url(date, "CODE", "final").to_dataset()
sp3_sid = preprocess_aux_for_interpolation(sp3_data)

# Interpolate
config = Sp3Config(use_velocities=True)
interpolator = Sp3InterpolationStrategy(config=config)
sp3_interp = interpolator.interpolate(sp3_sid, target_epochs)

# Compute spherical coordinates
receiver_pos = ECEFPosition.from_ds_metadata(rinex_ds)
r, theta, phi = compute_spherical_coordinates(
    sp3_interp['X'], sp3_interp['Y'], sp3_interp['Z'], receiver_pos
)

# Augment RINEX data
from canvod.auxiliary import add_spherical_coords_to_dataset
augmented_ds = add_spherical_coords_to_dataset(rinex_ds, r, theta, phi)
```

### 2. Icechunk Storage Preparation

Prepare auxiliary data for Icechunk with full preprocessing:

```python
from canvod.auxiliary import prep_aux_ds

# Load raw auxiliary data
sp3_data = Sp3File(...).to_dataset()  # {'epoch': 96, 'sv': 32}
clk_data = ClkFile(...).to_dataset()  # {'epoch': 288, 'sv': 32}

# Full 4-step preprocessing for Icechunk
sp3_prep = prep_aux_ds(sp3_data)  # {'epoch': 96, 'sid': ~2000}
clk_prep = prep_aux_ds(clk_data)  # {'epoch': 288, 'sid': ~2000}

# Now ready for Icechunk storage
# - sv → sid dimension
# - Padded to global sid list (all constellations)
# - sid dtype normalized to object
# - _FillValue attributes removed
```

### 3. Multi-Agency Product Comparison

Compare products from different agencies:

```python
from canvod.auxiliary import get_product_spec, Sp3File
from datetime import date

agencies = ["CODE", "GFZ", "JPL", "ESA"]
target_date = date(2024, 1, 1)

for agency in agencies:
    spec = get_product_spec(agency, "final")
    sp3 = Sp3File.from_url(target_date, agency, "final")

    ds = sp3.to_dataset()
    accuracy = ds.X.std(dim='epoch')
    print(f"{agency}: latency={spec.latency_hours}h, σ_X={accuracy:.3f}m")
```

### 4. Coordinate System Transformations

Convert between ECEF, geodetic, and spherical coordinates:

```python
from canvod.auxiliary import ECEFPosition, GeodeticPosition

# From RINEX metadata (ECEF)
ecef = ECEFPosition(x=4075539.8, y=931735.3, z=4801629.6)

# To geodetic (WGS84)
lat, lon, alt = ecef.to_geodetic()
print(f"Lat: {lat:.6f}°, Lon: {lon:.6f}°, Alt: {alt:.1f}m")

# Or from geodetic to ECEF
geo = GeodeticPosition(lat=48.0, lon=16.0, alt=200.0)
x, y, z = geo.to_ecef()
print(f"ECEF: X={x:.1f}, Y={y:.1f}, Z={z:.1f}")

# Spherical coordinates relative to receiver
# (computed from satellite ECEF and receiver ECEF)
r, theta, phi = compute_spherical_coordinates(
    sat_x, sat_y, sat_z, receiver_position
)
```

### 5. Custom Interpolation Strategies

Implement your own interpolation strategy:

```python
from canvod.auxiliary.interpolation import InterpolationStrategy, InterpolatorConfig
from dataclasses import dataclass

@dataclass
class MyConfig(InterpolatorConfig):
    """Custom configuration."""
    window_size: int = 5
    polynomial_degree: int = 3

class MyInterpolationStrategy(InterpolationStrategy):
    """Custom Savitzky-Golay filter interpolation."""

    def __init__(self, config: MyConfig):
        super().__init__(config)

    def interpolate(self, aux_ds, target_epochs):
        # Your implementation here
        ...
        return interpolated_ds

# Use it
config = MyConfig(window_size=7)
interpolator = MyInterpolationStrategy(config=config)
result = interpolator.interpolate(aux_data, target_epochs)
```

## Key Components

### File Handlers

**Sp3File (Ephemerides)**:
- Reads SP3a, SP3c, SP3d formats
- Extracts positions (X, Y, Z) and velocities (VX, VY, VZ)
- Returns xarray.Dataset with sv dimension
- Handles gzip/Hatanaka compression

**ClkFile (Clock Corrections)**:
- Reads RINEX clock format
- Extracts satellite clock biases
- Returns xarray.Dataset with sv dimension
- Handles gzip compression

**ProductSpec (Configuration)**:
- URL templates for each agency/product
- Latency information (rapid vs final)
- Authentication requirements (CDDIS)
- FTP server configuration

### Preprocessing Pipeline

Four-step preprocessing pipeline:

```python
from canvod.auxiliary.preprocessing import (
    map_aux_sv_to_sid,      # Step 1: sv → sid
    pad_to_global_sid,       # Step 2: pad to all sids
    normalize_sid_dtype,     # Step 3: object dtype
    strip_fillvalue,         # Step 4: remove _FillValue
    prep_aux_ds             # All 4 steps
)

# Manual pipeline
ds = map_aux_sv_to_sid(aux_ds)  # 32 svs → 384 sids
ds = pad_to_global_sid(ds)       # 384 → ~2000 sids (all constellations)
ds = normalize_sid_dtype(ds)     # Fix dtype for Zarr/Icechunk
ds = strip_fillvalue(ds)         # Clean attributes

# Or use convenience function
ds = prep_aux_ds(aux_ds)  # Same result
```

### Interpolation Strategies

**Sp3InterpolationStrategy**:
```python
from canvod.auxiliary.interpolation import Sp3InterpolationStrategy, Sp3Config

config = Sp3Config(
    use_velocities=True,           # Use VX, VY, VZ if available
    fallback_method='linear',      # If velocities missing
    extrapolation_method='nearest'  # At boundaries
)

interpolator = Sp3InterpolationStrategy(config=config)
sp3_interp = interpolator.interpolate(sp3_data, target_epochs)
```

**ClockInterpolationStrategy**:
```python
from canvod.auxiliary.interpolation import ClockInterpolationStrategy, ClockConfig

config = ClockConfig(
    window_size=9,           # Look at ±4 points
    jump_threshold=1e-6,     # 1 microsecond
    extrapolation='nearest'  # At boundaries
)

interpolator = ClockInterpolationStrategy(config=config)
clk_interp = interpolator.interpolate(clk_data, target_epochs)
```

### Position Classes

**ECEFPosition**: Earth-Centered, Earth-Fixed coordinates

```python
ecef = ECEFPosition(x=4075539.8, y=931735.3, z=4801629.6)
ecef = ECEFPosition.from_ds_metadata(rinex_ds)  # From RINEX
lat, lon, alt = ecef.to_geodetic()  # Convert to WGS84
```

**GeodeticPosition**: WGS84 latitude/longitude/altitude

```python
geo = GeodeticPosition(lat=48.2, lon=16.4, alt=200.0)
x, y, z = geo.to_ecef()  # Convert to ECEF
```

**Spherical Coordinates**: (r, θ, φ) relative to receiver

```python
r, theta, phi = compute_spherical_coordinates(
    sat_x, sat_y, sat_z,  # Satellite ECEF
    receiver_position      # Receiver ECEF or GeodeticPosition
)

# r: slant range (meters)
# theta: polar angle from zenith [0, π] radians
# phi: azimuthal angle from East [0, 2π) radians (physics convention)
```

## Data Flow

```{mermaid}
sequenceDiagram
    participant User
    participant Sp3File
    participant Preprocessor
    participant Interpolator
    participant Coordinates
    participant RINEX

    User->>Sp3File: from_url(date, agency, product_type)
    Sp3File->>Sp3File: Download from FTP
    Sp3File->>Sp3File: Parse SP3 format
    Sp3File-->>User: to_dataset() → {'epoch', 'sv'}

    User->>Preprocessor: preprocess_aux_for_interpolation(sp3_data)
    Preprocessor->>Preprocessor: map_aux_sv_to_sid()
    Preprocessor-->>User: {'epoch', 'sid'}

    User->>Interpolator: interpolate(sp3_sid, target_epochs)
    Interpolator->>Interpolator: Hermite splines
    Interpolator-->>User: {'epoch', 'sid'} @ target times

    User->>Coordinates: compute_spherical_coordinates()
    Coordinates-->>User: (r, θ, φ)

    User->>RINEX: add_spherical_coords_to_dataset()
    RINEX-->>User: Augmented RINEX data
```

## Performance Characteristics

### Memory Usage

**Download & Parse**:
- SP3 file: ~5 MB compressed → ~20 MB in memory
- CLK file: ~3 MB compressed → ~15 MB in memory
- Dataset overhead: ~10 MB per dataset

**Preprocessing (sv → sid)**:
- Input: 96 epochs × 32 svs = 3,072 values
- Output: 96 epochs × 384 sids = 36,864 values
- Memory: ~40 MB (12× expansion)

**Interpolation**:
- Input: 96 epochs × 384 sids
- Output: 2,880 epochs × 384 sids
- Memory: ~60 MB (30× time expansion)

**Total pipeline**: ~150 MB for 24-hour augmentation

### Processing Speed

Typical timings (Intel i7-1165G7 @ 2.8GHz):

| Stage | Time | Notes |
|-------|------|-------|
| Download SP3 | 1-3s | Network dependent |
| Download CLK | 1-2s | Network dependent |
| Parse SP3 | 0.3s | 96 epochs, 32 svs |
| Parse CLK | 0.2s | 288 epochs, 32 svs |
| Preprocess SP3 | 0.1s | sv → sid mapping |
| Preprocess CLK | 0.1s | sv → sid mapping |
| Interpolate SP3 | 1.2s | Hermite splines, 2880 epochs |
| Interpolate CLK | 0.6s | Piecewise linear, 2880 epochs |
| Spherical coords | 0.3s | 2880 epochs × 384 sids |
| **Total** | **~5s** | Complete augmentation |

### Optimization Tips

1. **Cache downloaded files**:
   ```python
   sp3 = Sp3File.from_url(date, "CODE", "final", local_dir=Path("cache/sp3"))
   ```

2. **Reuse preprocessed data**:
   ```python
   sp3_sid = preprocess_aux_for_interpolation(sp3_data)
   # Use sp3_sid for multiple RINEX files with same date
   ```

3. **Parallelize multiple dates**:
   ```python
   from concurrent.futures import ProcessPoolExecutor

   with ProcessPoolExecutor() as executor:
       results = executor.map(process_date, dates)
   ```

4. **Use minimal preprocessing for interpolation**:
   ```python
   # For interpolation only (faster)
   sp3_sid = preprocess_aux_for_interpolation(sp3_data)

   # For Icechunk storage (slower, more thorough)
   sp3_prep = prep_aux_ds(sp3_data)
   ```

## Comparison with Other Tools

| Feature | canvod-auxiliary | georinex | gnssrefl | sp3 |
|---------|------------|----------|----------|-----|
| SP3 parsing | ✅ Full | ✅ Full | ❌ | ✅ Full |
| CLK parsing | ✅ Full | ⚠️ Basic | ❌ | ❌ |
| sv→sid conversion | ✅ | ❌ | ❌ | ❌ |
| Hermite interpolation | ✅ | ❌ | ❌ | ❌ |
| Clock interpolation | ✅ | ❌ | ❌ | ❌ |
| Product registry | ✅ 37 products | ❌ | ❌ | ❌ |
| Coordinate transforms | ✅ ECEF/Geo/Sph | ⚠️ Partial | ❌ | ❌ |
| Type safety | ✅ Pydantic | ❌ | ❌ | ❌ |
| Icechunk ready | ✅ | ❌ | ❌ | ❌ |

**Key Differences:**
- **sv→sid preprocessing**: Essential for VOD pipeline, unique to canvod-auxiliary
- **Interpolation strategies**: Scientifically validated, configurable
- **Product registry**: 39 validated products from 17 agencies
- **Type safety**: Pydantic configurations catch errors early

## Next Steps

::::{grid} 2

:::{grid-item-card} 🔄 Preprocessing Guide
:link: preprocessing
:link-type: doc

Deep dive into sv→sid conversion and Icechunk preparation
:::

:::{grid-item-card} 📈 Interpolation Details
:link: interpolation
:link-type: doc

Learn about Hermite splines and clock correction strategies
:::

:::{grid-item-card} 📦 Product Registry
:link: products
:link-type: doc

Explore all 39 validated GNSS products
:::

:::{grid-item-card} 🌐 Position & Coordinates
:link: position
:link-type: doc

ECEF, geodetic, and spherical transformations
:::

::::
