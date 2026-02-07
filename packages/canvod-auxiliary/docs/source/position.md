# Position & Coordinates

Three coordinate systems for GNSS positioning.

## Overview

canvod-auxiliary supports three coordinate systems:
1. **ECEF** (Earth-Centered, Earth-Fixed): Cartesian (X, Y, Z)
2. **Geodetic** (WGS84): Latitude, Longitude, Altitude
3. **Spherical** (Physics convention): (r, θ, φ) relative to receiver

## ECEF Position

Earth-Centered, Earth-Fixed Cartesian coordinates.

```python
from canvod.auxiliary import ECEFPosition

# Create from coordinates
ecef = ECEFPosition(x=4075539.8, y=931735.3, z=4801629.6)

# Or from RINEX metadata
ecef = ECEFPosition.from_ds_metadata(rinex_ds)

# Convert to geodetic
lat, lon, alt = ecef.to_geodetic()
```

## Geodetic Position

WGS84 latitude, longitude, altitude.

```python
from canvod.auxiliary import GeodeticPosition

# Create
geo = GeodeticPosition(lat=48.2, lon=16.4, alt=200.0)

# Convert to ECEF
x, y, z = geo.to_ecef()
```

## Spherical Coordinates

Physics convention: (r, θ, φ) relative to receiver position.

```python
from canvod.auxiliary import compute_spherical_coordinates

# Compute from satellite and receiver positions
r, theta, phi = compute_spherical_coordinates(
    sat_x,  # Satellite ECEF X
    sat_y,  # Satellite ECEF Y
    sat_z,  # Satellite ECEF Z
    receiver_position  # ECEFPosition or GeodeticPosition
)
```

**Coordinate definitions:**
- **r**: Slant range from receiver to satellite (meters)
- **θ (theta)**: Polar angle from zenith [0, π] radians (0 = zenith, π/2 = horizon)
- **φ (phi)**: Azimuthal angle from East [0, 2π) radians (physics convention)

## Add to Dataset

```python
from canvod.auxiliary import add_spherical_coords_to_dataset

# Augment RINEX dataset with spherical coordinates
augmented_ds = add_spherical_coords_to_dataset(
    rinex_ds,
    r, theta, phi
)

# Now available
augmented_ds['r']      # Slant range
augmented_ds['theta']  # Polar angle
augmented_ds['phi']    # Azimuthal angle
```

## Use in VOD Analysis

Spherical coordinates are essential for VOD calculation:
- **θ (theta)**: Determines reflection zone size
- **φ (phi)**: Maps to hemisphere grid azimuth
- **r**: Used in geometric corrections

## See Also

- API Reference for function signatures
- Overview for complete workflow example
