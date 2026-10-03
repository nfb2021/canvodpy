# canvod-viz

2D/3D hemisphere visualization for GNSS-VOD data.

## Key modules

| Module | Purpose |
|---|---|
| `hemisphere_2d.py` | `HemisphereVisualizer2D` — polar plots (matplotlib) |
| `hemisphere_3d.py` | `HemisphereVisualizer3D` — 3D sphere (plotly) |
| `styles.py` | `PlotStyle`, `PolarPlotStyle` — Nordic theme integration |

## Usage

```python
from canvod.viz import HemisphereVisualizer

viz = HemisphereVisualizer(grid_data, style="nordic")
viz.plot_2d(variable="vod")
viz.plot_3d(variable="vod")
```

## Testing

```bash
uv run pytest packages/canvod-viz/tests/
```
