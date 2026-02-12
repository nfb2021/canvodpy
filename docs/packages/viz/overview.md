# canvod-viz

## Purpose

The `canvod-viz` package provides 2D and 3D hemispheric visualization for GNSS-T grids, SNR data, and VOD results. It wraps matplotlib (publication-quality 2D polar plots) and plotly (interactive 3D hemispheres) behind a unified API.

## Components

| Class / Function | Purpose |
|------------------|---------|
| `HemisphereVisualizer` | Unified API combining 2D and 3D |
| `HemisphereVisualizer2D` | Matplotlib polar projection plots |
| `HemisphereVisualizer3D` | Plotly interactive 3D hemispheres |
| `visualize_grid` | One-call 2D grid plot |
| `visualize_grid_3d` | One-call 3D grid plot |
| `add_tissot_indicatrix` | Overlay angular distortion circles |
| `PlotStyle` / `PolarPlotStyle` | Styling configuration |
| `create_publication_style` | Pre-configured publication settings |
| `create_interactive_style` | Pre-configured interactive settings |

## Usage

### Unified API (recommended)

```python
from canvod.grids import create_hemigrid
from canvod.viz import HemisphereVisualizer

grid = create_hemigrid("equal_area", angular_resolution=10.0)
viz = HemisphereVisualizer(grid)

# 2D publication plot
fig_2d, ax_2d = viz.plot_2d(data=vod_data, title="VOD Distribution")

# 3D interactive plot
fig_3d = viz.plot_3d(data=vod_data, title="Interactive VOD")
fig_3d.show()
```

### Convenience functions

```python
from canvod.viz import visualize_grid, visualize_grid_3d, add_tissot_indicatrix

fig, ax = visualize_grid(grid, data=vod_data, cmap="viridis")
add_tissot_indicatrix(ax, grid, n_sample=5)

fig_3d = visualize_grid_3d(grid, data=vod_data)
```

### Specialized visualizers

```python
from canvod.viz import HemisphereVisualizer2D, HemisphereVisualizer3D

viz2d = HemisphereVisualizer2D(grid)
fig, ax = viz2d.plot_grid_patches(data=vod_data, title="VOD")

viz3d = HemisphereVisualizer3D(grid)
fig = viz3d.plot_hemisphere_surface(data=vod_data, title="Interactive VOD")
```

### Styling

```python
from canvod.viz import HemisphereVisualizer, create_publication_style, create_interactive_style

viz = HemisphereVisualizer(grid)

# Publication quality
viz.set_style(create_publication_style())
fig, ax = viz.plot_2d(data=vod_data)

# Interactive dark mode
viz.set_style(create_interactive_style(dark_mode=True))
fig = viz.plot_3d(data=vod_data)
```

### Comparison and export

```python
viz = HemisphereVisualizer(grid)

# Side-by-side 2D + 3D
(fig_2d, ax_2d), fig_3d = viz.create_comparison_plot(data=vod_data)

# Publication figure with custom DPI
fig, ax = viz.create_publication_figure(
    data=vod_data,
    title="VOD Distribution",
    save_path="figure_3.png",
    dpi=600,
)

# Interactive HTML export
fig = viz.create_interactive_explorer(
    data=vod_data,
    dark_mode=True,
    save_html="explorer.html",
)
```

## Dependencies

canvod-viz depends on canvod-grids for grid geometry. 2D plots use matplotlib; 3D plots use plotly.
