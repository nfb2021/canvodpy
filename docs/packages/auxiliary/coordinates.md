# Coordinate Systems

## Overview

Three coordinate systems are used in GNSS positioning within canvod-auxiliary:

1. **ECEF** (Earth-Centered, Earth-Fixed): Cartesian coordinates (X, Y, Z) in meters
2. **Geodetic** (WGS84): Latitude, longitude (degrees), altitude (meters)
3. **Spherical**: Slant range, polar angle, azimuth (r, theta, phi) relative to the receiver

## ECEF Coordinates

Earth-Centered, Earth-Fixed Cartesian coordinates define positions relative to the Earth's center of mass.

```python
from canvod.auxiliary import ECEFPosition

ecef = ECEFPosition(x=4075539.8, y=931735.3, z=4801629.6)
ecef = ECEFPosition.from_ds_metadata(rinex_ds)

lat, lon, alt = ecef.to_geodetic()
```

## Geodetic Coordinates

WGS84 geodetic coordinates (latitude, longitude, altitude above ellipsoid).

```python
from canvod.auxiliary import GeodeticPosition

geo = GeodeticPosition(lat=48.2, lon=16.4, alt=200.0)
x, y, z = geo.to_ecef()
```

## Spherical Coordinates

Spherical coordinates relative to the receiver position, following the physics convention:

- **r**: Slant range from receiver to satellite (meters)
- **theta**: Polar angle from zenith [0, pi] radians (0 = zenith, pi/2 = horizon)
- **phi**: Azimuthal angle from East [0, 2*pi) radians

```python
from canvod.auxiliary import compute_spherical_coordinates

r, theta, phi = compute_spherical_coordinates(
    sat_x, sat_y, sat_z, receiver_position
)
```

These coordinates are essential for VOD calculation: theta determines the reflection zone geometry, phi maps to the hemispheric grid azimuth, and r is used in geometric corrections.

## Adding Coordinates to Datasets

```python
from canvod.auxiliary import add_spherical_coords_to_dataset

augmented_ds = add_spherical_coords_to_dataset(rinex_ds, r, theta, phi)
# Adds r, theta, phi as data variables
```
