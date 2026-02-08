# canvod-viz

## Purpose

The `canvod-viz` package provides visualization utilities for GNSS vegetation optical depth analysis. It generates 2D and 3D hemispheric plots of SNR data, grid cells, and VOD results.

## Capabilities

- Hemispheric projection plots (polar and 3D)
- Grid cell visualization with color-mapped values
- Satellite track overlays
- Time series plots of VOD estimates
- Publication-quality figure export

## Usage

```python
from canvod.viz import HemisphereVisualizer

viz = HemisphereVisualizer(grid, dataset)
fig = viz.plot_hemisphere(variable="SNR", projection="polar")
```

## Dependencies

canvod-viz depends on canvod-grids for grid geometry. Visualization is built on matplotlib.
