# canvod-grids

## Purpose

The `canvod-grids` package provides spatial grid implementations for hemispheric GNSS signal analysis. It supports multiple grid types for discretizing the hemisphere visible from a ground-based receiver, which is required for spatially resolved VOD estimation.

## Grid Types

- **Equal-area grid**: Hemispheric grid with cells of approximately equal solid angle, constructed using an azimuth-elevation partitioning scheme
- **HEALPix grid**: Hierarchical Equal Area isoLatitude Pixelization adapted for hemispheric projections

## Usage

```python
from canvod.grids import EqualAreaBuilder

builder = EqualAreaBuilder()
grid = builder.build(resolution=5.0)  # 5-degree resolution
```

Grid objects provide:
- Cell geometry (boundaries, centers, solid angles)
- Point-to-cell assignment for satellite positions
- Neighbor lookup for spatial smoothing
- Visualization support via canvod-viz

## Role in the VOD Pipeline

Grids discretize the hemisphere above the receiver into cells. Each GNSS satellite observation is assigned to a grid cell based on its elevation and azimuth angles (computed by canvod-auxiliary). VOD is then estimated per cell or aggregated across the hemisphere.
