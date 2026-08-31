"""Unified hemisphere visualization API combining 2D and 3D capabilities.

Provides a single interface for both matplotlib (publication) and plotly
(interactive) plots.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import plotly.graph_objects as go

from canvod.viz.hemisphere_2d import HemisphereVisualizer2D
from canvod.viz.hemisphere_3d import HemisphereVisualizer3D
from canvod.viz.styles import (
    PlotStyle,
    PolarPlotStyle,
    create_interactive_style,
    create_publication_style,
)

if TYPE_CHECKING:
    import numpy as np
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

    from canvod.grids import HemiGrid


class HemisphereVisualizer:
    """Unified hemisphere visualizer combining 2D and 3D capabilities.

    Provides consistent API for both publication-quality matplotlib plots
    and interactive plotly visualizations. Handles styling coordination
    between different rendering backends.

    Parameters
    ----------
    grid : HemiGrid
        Hemisphere grid to visualize

    Examples
    --------
    Create both 2D and 3D visualizations::

        from canvod.grids import create_hemigrid
        from canvod.viz import HemisphereVisualizer

        grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
        viz = HemisphereVisualizer(grid)

        # Publication-quality 2D plot
        fig_2d, ax_2d = viz.plot_2d(
            data=vod_data,
            title="VOD Distribution",
            save_path="publication.png"
        )

        # Interactive 3D plot
        fig_3d = viz.plot_3d(
            data=vod_data,
            title="Interactive VOD Explorer"
        )
        fig_3d.show()

    Switch styles easily::

        # Publication style
        pub_style = create_publication_style()
        viz.set_style(pub_style)
        fig, ax = viz.plot_2d(data=vod_data)

        # Interactive style
        int_style = create_interactive_style(dark_mode=True)
        viz.set_style(int_style)
        fig = viz.plot_3d(data=vod_data)

    """

    def __init__(self, grid: HemiGrid) -> None:
        """Initialize unified visualizer.

        Parameters
        ----------
        grid : HemiGrid
            Hemisphere grid to visualize

        """
        self.grid = grid

        # Initialize specialized visualizers
        self.viz_2d = HemisphereVisualizer2D(grid)
        self.viz_3d = HemisphereVisualizer3D(grid)

        # Default styling
        self.style = PlotStyle()

    def set_style(self, style: PlotStyle) -> None:
        """Set unified styling for both 2D and 3D plots.

        Parameters
        ----------
        style : PlotStyle
            Styling configuration

        Examples
        --------
        >>> pub_style = create_publication_style()
        >>> viz.set_style(pub_style)
        >>> fig, ax = viz.plot_2d(data=vod_data)

        """
        self.style = style

    def plot_2d(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        ax: Axes | None = None,
        save_path: Path | str | None = None,
        style: PolarPlotStyle | None = None,
        **kwargs: Any,
    ) -> tuple[Figure, Axes]:
        """Create 2D publication-quality plot.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        ax : matplotlib.axes.Axes, optional
            Existing axes to plot on
        save_path : Path or str, optional
            Save figure to this path
        style : PolarPlotStyle, optional
            Override default 2D style
        **kwargs
            Additional styling parameters

        Returns
        -------
        fig : matplotlib.figure.Figure
            Figure object
        ax : matplotlib.axes.Axes
            Polar axes with plot

        Examples
        --------
        >>> fig, ax = viz.plot_2d(
        ...     data=vod_data,
        ...     title="VOD Distribution",
        ...     cmap='plasma',
        ...     save_path="output.png",
        ...     dpi=300
        ... )

        """
        if style is None:
            style = self.style.to_polar_style()

        if title:
            style.title = title

        return self.viz_2d.plot_grid_patches(
            data=data, style=style, ax=ax, save_path=save_path, **kwargs
        )

    def plot_3d(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        style: PlotStyle | None = None,
        **kwargs: Any,
    ) -> go.Figure:
        """Create 3D interactive plot.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        style : PlotStyle, optional
            Override default 3D style
        **kwargs
            Additional plotly parameters

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive 3D figure

        Examples
        --------
        >>> fig = viz.plot_3d(
        ...     data=vod_data,
        ...     title="Interactive VOD",
        ...     opacity=0.9,
        ...     width=1000,
        ...     height=800
        ... )
        >>> fig.show()
        >>> fig.write_html("interactive.html")

        """
        if style is None:
            style = self.style

        return self.viz_3d.plot_hemisphere_surface(
            data=data, style=style, title=title, **kwargs
        )

    def plot_3d_mesh(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        **kwargs: Any,
    ) -> go.Figure:
        """Create 3D mesh plot showing cell boundaries.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        **kwargs
            Additional plotly parameters

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive mesh figure

        Examples
        --------
        >>> fig = viz.plot_3d_mesh(
        ...     data=vod_data,
        ...     title="VOD Mesh View",
        ...     opacity=0.7
        ... )

        """
        return self.viz_3d.plot_cell_mesh(data=data, title=title, **kwargs)

    def create_comparison_plot(
        self,
        data: np.ndarray | None = None,
        title_2d: str = "2D Polar View",
        title_3d: str = "3D Hemisphere View",
        save_2d: Path | str | None = None,
        save_3d: Path | str | None = None,
    ) -> tuple[tuple[Figure, Axes], go.Figure]:
        """Create both 2D and 3D plots for comparison.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title_2d : str, default "2D Polar View"
            Title for 2D plot
        title_3d : str, default "3D Hemisphere View"
            Title for 3D plot
        save_2d : Path or str, optional
            Save 2D figure to this path
        save_3d : Path or str, optional
            Save 3D figure to this path (HTML)

        Returns
        -------
        plot_2d : tuple of Figure and Axes
            2D matplotlib plot
        plot_3d : plotly.graph_objects.Figure
            3D plotly plot

        Examples
        --------
        >>> (fig_2d, ax_2d), fig_3d = viz.create_comparison_plot(
        ...     data=vod_data,
        ...     save_2d="comparison_2d.png",
        ...     save_3d="comparison_3d.html"
        ... )
        >>> plt.show()  # Show 2D
        >>> fig_3d.show()  # Show 3D

        """
        # Create 2D plot
        fig_2d, ax_2d = self.plot_2d(data=data, title=title_2d, save_path=save_2d)

        # Create 3D plot
        fig_3d = self.plot_3d(data=data, title=title_3d)

        # Save 3D if requested
        if save_3d:
            save_3d = Path(save_3d)
            save_3d.parent.mkdir(parents=True, exist_ok=True)
            fig_3d.write_html(str(save_3d))

        return (fig_2d, ax_2d), fig_3d

    def create_publication_figure(
        self,
        data: np.ndarray | None = None,
        title: str = "Hemispherical Data Distribution",
        save_path: Path | str | None = None,
        dpi: int = 300,
        **kwargs: Any,
    ) -> tuple[Figure, Axes]:
        """Create publication-ready figure with optimal styling.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, default "Hemispherical Data Distribution"
            Plot title
        save_path : Path or str, optional
            Save figure to this path
        dpi : int, default 300
            Resolution in dots per inch
        **kwargs
            Additional styling parameters

        Returns
        -------
        fig : matplotlib.figure.Figure
            Publication-ready figure
        ax : matplotlib.axes.Axes
            Styled polar axes

        Examples
        --------
        >>> fig, ax = viz.create_publication_figure(
        ...     data=vod_data,
        ...     title="VOD Distribution Over ExampleSite Site",
        ...     save_path="paper_figure_3.png",
        ...     dpi=600
        ... )

        """
        # Use publication style and convert to PolarPlotStyle
        pub_plot_style = create_publication_style()
        polar_style = pub_plot_style.to_polar_style()
        polar_style.title = title
        polar_style.dpi = dpi

        # Override with kwargs
        for key, value in kwargs.items():
            if hasattr(polar_style, key):
                setattr(polar_style, key, value)

        return self.plot_2d(data=data, style=polar_style, save_path=save_path)

    def create_interactive_explorer(
        self,
        data: np.ndarray | None = None,
        title: str = "Interactive Data Explorer",
        dark_mode: bool = True,
        save_html: Path | str | None = None,
    ) -> go.Figure:
        """Create interactive explorer with optimal settings.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, default "Interactive Data Explorer"
            Plot title
        dark_mode : bool, default True
            Use dark theme
        save_html : Path or str, optional
            Save HTML to this path

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive explorer figure

        Examples
        --------
        >>> fig = viz.create_interactive_explorer(
        ...     data=vod_data,
        ...     title="VOD Explorer",
        ...     dark_mode=True,
        ...     save_html="explorer.html"
        ... )
        >>> fig.show()

        """
        # Use interactive style
        int_style = create_interactive_style(dark_mode=dark_mode)

        fig = self.plot_3d(data=data, title=title, style=int_style)

        # Save if requested
        if save_html:
            save_html = Path(save_html)
            save_html.parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(str(save_html))

        return fig
