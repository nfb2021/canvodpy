# canvod-grids

Equal-area hemisphere grid operations for GNSS-Transmissometry.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

`canvod-grids` provides the spatial discretization layer for GNSS-T. Satellite
signal paths are assigned to equal-area grid cells on the hemisphere above the
receiver based on their polar angle (θ) and azimuth (φ). The primary grid type
for GNSS-T is the **equal-area** grid, where each 2° band is divided into cells
of equal solid angle.

Six grid types are available: `equal_area`, `equal_angle`, `equirectangular`,
`htm`, `geodesic`, and `fibonacci`. Of these, `equal_area` and `equal_angle`
are verified correct; the rest are implemented but not yet verified.

## Installation

```bash
uv pip install canvod-grids
```

## Quick Start

```python
from canvod.grids import create_hemigrid, GridType

# Create a 2° equal-area hemisphere grid
grid = create_hemigrid(grid_type=GridType.EQUAL_AREA, resolution=2.0)
print(grid.ncells)  # number of grid cells

# Assign satellite observations to cells
from canvod.grids import CellAggregator
agg = CellAggregator(grid)
per_cell = agg.aggregate(ds, variable="vod", method="median")
```

## Documentation

[Full documentation](https://nfb2021.github.io/canvodpy/packages/grids/overview/)

## Development

See the [main repository](https://github.com/nfb2021/canvodpy) for workspace development setup.

## License

Apache License 2.0

## Author & Affiliation

**Nicolas François Bader**
Climate and Environmental Remote Sensing Research Unit (CLIMERS)
Department of Geodesy and Geoinformation
TU Wien (Vienna University of Technology)
Email: nicolas.bader@geo.tuwien.ac.at
[https://www.tuwien.at/en/mg/geo/climers](https://www.tuwien.at/en/mg/geo/climers)
