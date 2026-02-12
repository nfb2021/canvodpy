"""3D hemisphere visualization using plotly for interactive exploration.

Provides interactive 3D sphere surface plots with zoom, pan, and rotation capabilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import plotly.graph_objects as go
from canvod.viz.styles import PlotStyle
from plotly.colors import sample_colorscale

if TYPE_CHECKING:
    from canvod.grids import HemiGrid


class HemisphereVisualizer3D:
    """3D hemisphere visualization using plotly.

    Creates interactive 3D plots with rotation, zoom, and hover capabilities.
    Designed for exploratory data analysis and presentations.

    Parameters
    ----------
    grid : HemiGrid
        Hemisphere grid to visualize

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.viz import HemisphereVisualizer3D
    >>>
    >>> grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    >>> viz = HemisphereVisualizer3D(grid)
    >>> fig = viz.plot_hemisphere_surface(data=vod_data, title="Interactive VOD")
    >>> fig.show()

    """

    def __init__(self, grid: HemiGrid) -> None:
        """Initialize 3D hemisphere visualizer.

        Parameters
        ----------
        grid : HemiGrid
            Hemisphere grid to visualize

        """
        self.grid = grid

    def plot_hemisphere_surface(
        self,
        data: np.ndarray | None = None,
        style: PlotStyle | None = None,
        title: str | None = None,
        colorscale: str = "Viridis",
        opacity: float = 0.8,
        show_wireframe: bool = True,
        show_colorbar: bool = True,
        width: int = 800,
        height: int = 600,
        **kwargs: Any,
    ) -> go.Figure:
        """Create 3D surface plot on hemisphere with actual cell patches.

        Renders grid cells as colored 3D patches (not just points).

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell. If None, shows grid structure.
        style : PlotStyle, optional
            Styling configuration. If None, uses defaults.
        title : str, optional
            Plot title
        colorscale : str, default 'Viridis'
            Plotly colorscale name
        opacity : float, default 0.8
            Surface opacity (0=transparent, 1=opaque)
        show_wireframe : bool, default True
            Show grid lines on surface
        show_colorbar : bool, default True
            Display colorbar
        width : int, default 800
            Figure width in pixels
        height : int, default 600
            Figure height in pixels
        **kwargs
            Additional plotly trace parameters

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive 3D figure with cell patches

        Examples
        --------
        >>> fig = viz.plot_hemisphere_surface(
        ...     data=vod_data,
        ...     title="VOD Distribution 3D",
        ...     colorscale='Plasma',
        ...     opacity=0.9
        ... )
        >>> fig.write_html("vod_3d.html")

        """
        # Initialize style
        if style is None:
            style = PlotStyle()
            colorscale = colorscale  # Use parameter
        else:
            colorscale = style.colorscale

        # Render grid based on type
        grid_type = self.grid.grid_type.lower()

        if grid_type in ["equal_area", "equal_angle", "equirectangular"]:
            trace = self._render_rectangular_cells(
                data,
                colorscale,
                opacity,
                show_colorbar,
            )
        elif grid_type == "htm":
            trace = self._render_htm_cells(data, colorscale, opacity, show_colorbar)
        elif grid_type == "geodesic":
            trace = self._render_geodesic_cells(
                data, colorscale, opacity, show_colorbar
            )
        elif grid_type == "healpix":
            trace = self._render_healpix_cells(data, colorscale, opacity, show_colorbar)
        elif grid_type == "fibonacci":
            trace = self._render_fibonacci_cells(
                data, colorscale, opacity, show_colorbar
            )
        else:
            # Fallback to scatter for unknown types
            trace = self._render_scatter_fallback(
                data,
                colorscale,
                opacity,
                show_colorbar,
            )

        fig = go.Figure(data=[trace])

        # Apply layout
        layout_config = style.to_plotly_layout() if style else {}
        layout_config.update(
            {
                "title": title or "Hemisphere 3D",
                "scene": dict(
                    aspectmode="data",
                    xaxis=dict(title="East", showbackground=False),
                    yaxis=dict(title="North", showbackground=False),
                    zaxis=dict(title="Up", showbackground=False),
                    bgcolor=layout_config.get("plot_bgcolor", "white"),
                ),
                "width": width,
                "height": height,
                "margin": dict(l=0, r=0, b=0, t=40),
            }
        )

        fig.update_layout(**layout_config)

        return fig

    def _render_rectangular_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render rectangular grid cells as 3D mesh patches."""
        grid_df = self.grid.grid

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []

        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                phi_min, phi_max = row["phi_min"], row["phi_max"]
                theta_min, theta_max = row["theta_min"], row["theta_max"]

                # Skip if beyond hemisphere
                if theta_min > np.pi / 2:
                    continue

                # Create 4 corners of rectangular cell
                phi_corners = [phi_min, phi_max, phi_max, phi_min]
                theta_corners = [theta_min, theta_min, theta_max, theta_max]

                patch_x, patch_y, patch_z = [], [], []
                for phi, theta in zip(phi_corners, theta_corners):
                    # Convert to 3D Cartesian
                    x = np.sin(theta) * np.cos(phi)
                    y = np.sin(theta) * np.sin(phi)
                    z = np.cos(theta)
                    patch_x.append(x)
                    patch_y.append(y)
                    patch_z.append(z)

                all_x.extend(patch_x)
                all_y.extend(patch_y)
                all_z.extend(patch_z)

                # Color value for this cell
                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * 4)

                # Two triangles per rectangle
                all_i.extend([vertex_count, vertex_count])
                all_j.extend([vertex_count + 1, vertex_count + 2])
                all_k.extend([vertex_count + 2, vertex_count + 3])

                vertex_count += 4

            except (KeyError, IndexError):
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name=f"{self.grid.grid_type.title()} Grid",
        )

    def _render_htm_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render HTM triangular cells as 3D mesh."""
        grid_df = self.grid.grid

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []

        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                v0 = np.array(row["htm_vertex_0"], dtype=float)
                v1 = np.array(row["htm_vertex_1"], dtype=float)
                v2 = np.array(row["htm_vertex_2"], dtype=float)

                # Skip if beyond hemisphere
                if np.all([v[2] < 0 for v in [v0, v1, v2]]):
                    continue

                all_x.extend([v0[0], v1[0], v2[0]])
                all_y.extend([v0[1], v1[1], v2[1]])
                all_z.extend([v0[2], v1[2], v2[2]])

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * 3)

                # One triangle per cell
                all_i.append(vertex_count)
                all_j.append(vertex_count + 1)
                all_k.append(vertex_count + 2)

                vertex_count += 3

            except (KeyError, TypeError, ValueError):
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name=f"{self.grid.grid_type.title()} Grid",
        )

    def _render_geodesic_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render geodesic triangular cells as 3D mesh.

        Reads ``geodesic_vertices`` (3 vertex indices per cell) and looks up
        3D Cartesian coordinates from the shared ``grid.vertices`` array.
        """
        grid_df = self.grid.grid
        shared_vertices = self.grid.vertices

        if shared_vertices is None or "geodesic_vertices" not in grid_df.columns:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []
        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                v_indices = np.array(row["geodesic_vertices"], dtype=int)
                if len(v_indices) < 3:
                    continue

                verts = shared_vertices[v_indices]  # (3, 3)

                if np.all(verts[:, 2] < 0):
                    continue

                all_x.extend(verts[:, 0].tolist())
                all_y.extend(verts[:, 1].tolist())
                all_z.extend(verts[:, 2].tolist())

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * 3)

                all_i.append(vertex_count)
                all_j.append(vertex_count + 1)
                all_k.append(vertex_count + 2)
                vertex_count += 3

            except (KeyError, IndexError, TypeError, ValueError):
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name="Geodesic Grid",
        )

    def _render_healpix_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render HEALPix curvilinear cells as 3D mesh.

        Uses ``healpy.boundaries()`` to obtain true pixel boundaries,
        then fan-triangulates each quadrilateral pixel.
        """
        try:
            import healpy as hp
        except ImportError:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        grid_df = self.grid.grid
        if "healpix_ipix" not in grid_df.columns:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        nside = int(grid_df["healpix_nside"][0])
        step = 4  # 4 sub-points per edge → 16 boundary vertices

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []
        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                ipix = int(row["healpix_ipix"])
                boundary = hp.boundaries(nside, ipix, step=step)
                x, y, z = boundary[0], boundary[1], boundary[2]

                if np.all(z < -0.01):
                    continue

                n_verts = len(x)
                all_x.extend(x.tolist())
                all_y.extend(y.tolist())
                all_z.extend(z.tolist())

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * n_verts)

                # Fan triangulation from first vertex
                for j in range(1, n_verts - 1):
                    all_i.append(vertex_count)
                    all_j.append(vertex_count + j)
                    all_k.append(vertex_count + j + 1)

                vertex_count += n_verts

            except (KeyError, IndexError, TypeError, ValueError):
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name="HEALPix Grid",
        )

    def _render_fibonacci_cells(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Mesh3d:
        """Render Fibonacci Voronoi cells as 3D mesh.

        Reads ``voronoi_region`` (variable-length vertex index list) and
        looks up 3D coordinates from ``grid.voronoi.vertices``.  The
        vertex indices are already in correct polygon winding order
        (``SphericalVoronoi.sort_vertices_of_regions()`` was called
        during grid construction), so no re-sorting is needed.
        Fan-triangulates each polygon for ``go.Mesh3d``.
        """
        grid_df = self.grid.grid
        voronoi = self.grid.voronoi

        if voronoi is None or "voronoi_region" not in grid_df.columns:
            return self._render_scatter_fallback(
                data, colorscale, opacity, show_colorbar
            )

        all_x, all_y, all_z = [], [], []
        all_i, all_j, all_k = [], [], []
        all_colors = []
        vertex_count = 0

        for i, row in enumerate(grid_df.iter_rows(named=True)):
            try:
                region_indices = row["voronoi_region"]
                if region_indices is None or len(region_indices) < 3:
                    continue

                verts = voronoi.vertices[region_indices]

                if np.all(verts[:, 2] < -0.01):
                    continue

                # Vertices are already in polygon winding order from
                # sort_vertices_of_regions() — use directly.
                n_verts = len(verts)

                all_x.extend(verts[:, 0].tolist())
                all_y.extend(verts[:, 1].tolist())
                all_z.extend(verts[:, 2].tolist())

                color_val = data[i] if data is not None else 0.5
                all_colors.extend([color_val] * n_verts)

                # Fan triangulation from first vertex
                for j in range(1, n_verts - 1):
                    all_i.append(vertex_count)
                    all_j.append(vertex_count + j)
                    all_k.append(vertex_count + j + 1)

                vertex_count += n_verts

            except (KeyError, IndexError, TypeError, ValueError):
                continue

        return go.Mesh3d(
            x=all_x,
            y=all_y,
            z=all_z,
            i=all_i,
            j=all_j,
            k=all_k,
            intensity=all_colors,
            colorscale=colorscale,
            showscale=show_colorbar,
            colorbar=dict(title="Value") if show_colorbar else None,
            opacity=opacity,
            flatshading=True,
            name="Fibonacci Grid",
        )

    def _render_scatter_fallback(
        self,
        data: np.ndarray | None,
        colorscale: str,
        opacity: float,
        show_colorbar: bool,
    ) -> go.Scatter3d:
        """Fallback scatter plot for unsupported grid types."""
        grid_df = self.grid.grid
        theta = grid_df["theta"].to_numpy()
        phi = grid_df["phi"].to_numpy()

        # Convert to 3D Cartesian coordinates
        x = np.sin(theta) * np.cos(phi)
        y = np.sin(theta) * np.sin(phi)
        z = np.cos(theta)

        # Prepare data values
        if data is None:
            values = np.ones(self.grid.ncells) * 0.5
        else:
            values = data

        # Filter hemisphere only
        hemisphere_mask = theta <= np.pi / 2
        x = x[hemisphere_mask]
        y = y[hemisphere_mask]
        z = z[hemisphere_mask]
        values = values[hemisphere_mask]

        return go.Scatter3d(
            x=x,
            y=y,
            z=z,
            mode="markers",
            marker=dict(
                size=6,
                color=values,
                colorscale=colorscale,
                opacity=opacity,
                colorbar=dict(title="Value") if show_colorbar else None,
                cmin=np.nanmin(values),
                cmax=np.nanmax(values),
            ),
            text=[f"Cell {i}<br>Value: {v:.3f}" for i, v in enumerate(values)],
            hoverinfo="text",
        )

    def plot_hemisphere_scatter(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        colorscale: str = "Viridis",
        marker_size: int | np.ndarray = 6,
        opacity: float = 0.8,
        width: int = 800,
        height: int = 600,
    ) -> go.Figure:
        """Create 3D scatter plot of cell centers.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        colorscale : str, default 'Viridis'
            Plotly colorscale name
        marker_size : int or np.ndarray, default 6
            Marker size (constant or per-point array)
        opacity : float, default 0.8
            Marker opacity
        width : int, default 800
            Figure width
        height : int, default 600
            Figure height

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive scatter plot

        """
        # Note: Now renders as mesh, not scatter points
        # Marker size parameter is ignored
        fig = self.plot_hemisphere_surface(
            data=data,
            title=title,
            colorscale=colorscale,
            opacity=opacity,
            width=width,
            height=height,
        )

        return fig

    def plot_cell_mesh(
        self,
        data: np.ndarray | None = None,
        title: str | None = None,
        colorscale: str = "Viridis",
        opacity: float = 0.7,
        show_edges: bool = True,
        width: int = 800,
        height: int = 600,
    ) -> go.Figure:
        """Create 3D mesh plot showing cell boundaries.

        Parameters
        ----------
        data : np.ndarray, optional
            Data values per cell
        title : str, optional
            Plot title
        colorscale : str, default 'Viridis'
            Plotly colorscale name
        opacity : float, default 0.7
            Mesh opacity
        show_edges : bool, default True
            Show cell edges
        width : int, default 800
            Figure width
        height : int, default 600
            Figure height

        Returns
        -------
        plotly.graph_objects.Figure
            Interactive mesh plot

        Notes
        -----
        This method requires grid cells with vertex information.
        Currently supports HTM and geodesic grids.

        """
        traces = []

        # Prepare data
        if data is None:
            values = np.ones(self.grid.ncells) * 0.5
        else:
            values = data

        grid_df = self.grid.grid
        grid_type = self.grid.grid_type.lower()

        # Check if grid supports mesh rendering
        if grid_type == "htm" and "htm_vertex_0" in grid_df.columns:
            # HTM triangular mesh
            for idx, row in enumerate(grid_df.iter_rows(named=True)):
                try:
                    v0 = np.array(row["htm_vertex_0"], dtype=float)
                    v1 = np.array(row["htm_vertex_1"], dtype=float)
                    v2 = np.array(row["htm_vertex_2"], dtype=float)

                    vertices = np.array([v0, v1, v2])

                    # Check hemisphere
                    z_coords = vertices[:, 2]
                    if np.all(z_coords < 0):
                        continue

                    # Normalize color value
                    color_val = (values[idx] - np.nanmin(values)) / (
                        np.nanmax(values) - np.nanmin(values)
                    )
                    color_rgb = sample_colorscale(colorscale, [color_val])[0]

                    # Create triangle mesh
                    trace = go.Mesh3d(
                        x=vertices[:, 0],
                        y=vertices[:, 1],
                        z=vertices[:, 2],
                        i=[0],
                        j=[1],
                        k=[2],
                        color=color_rgb,
                        opacity=opacity,
                        flatshading=True,
                        showscale=False,
                        hoverinfo="skip",
                    )
                    traces.append(trace)
                except (KeyError, TypeError, ValueError):
                    continue
        else:
            # Not supported for this grid type
            raise NotImplementedError(
                f"Cell mesh rendering not implemented for {grid_type} grids"
            )

        # Sample colorscale (no longer needed above, but kept for compatibility)

        # Add colorbar trace
        if values is not None and len(traces) > 0:
            dummy_trace = go.Scatter3d(
                x=[None],
                y=[None],
                z=[None],
                mode="markers",
                marker=dict(
                    size=0.1,
                    color=[np.nanmin(values), np.nanmax(values)],
                    colorscale=colorscale,
                    colorbar=dict(title="Value"),
                ),
                showlegend=False,
                hoverinfo="skip",
            )
            traces.append(dummy_trace)

        fig = go.Figure(data=traces)

        # Update layout
        fig.update_layout(
            title=title or "Hemisphere Mesh 3D",
            scene=dict(
                aspectmode="data",
                xaxis=dict(title="East", showbackground=False),
                yaxis=dict(title="North", showbackground=False),
                zaxis=dict(title="Up", showbackground=False),
            ),
            width=width,
            height=height,
            margin=dict(l=0, r=0, b=0, t=40),
        )

        return fig

    def add_spherical_overlays(
        self,
        fig: go.Figure,
        elevation_rings: list[int] | None = None,
        meridians_deg: list[int] | None = None,
        overlay_color: str = "lightgray",
        line_width: float = 1,
    ) -> go.Figure:
        """Add elevation rings and meridians to 3D plot.

        Parameters
        ----------
        fig : plotly.graph_objects.Figure
            Existing 3D figure to add overlays to
        elevation_rings : list of int, optional
            Elevation angles in degrees. Default: [15, 30, 45, 60, 75, 90]
        meridians_deg : list of int, optional
            Meridian angles in degrees. Default: [0, 45, 90, 135, 180, 225, 270, 315]
        overlay_color : str, default 'lightgray'
            Color for overlay lines
        line_width : float, default 1
            Width of overlay lines

        Returns
        -------
        fig : plotly.graph_objects.Figure
            Modified figure with overlays

        """
        if elevation_rings is None:
            elevation_rings = [15, 30, 45, 60, 75, 90]
        if meridians_deg is None:
            meridians_deg = list(range(0, 360, 45))

        # Elevation rings
        for theta_deg in elevation_rings:
            theta = np.radians(theta_deg)
            phi = np.linspace(0, 2 * np.pi, 200)
            x = np.sin(theta) * np.cos(phi)
            y = np.sin(theta) * np.sin(phi)
            z = np.full_like(phi, np.cos(theta))
            fig.add_trace(
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                    line=dict(color=overlay_color, width=line_width),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        # Meridians
        for phi_deg in meridians_deg:
            phi = np.radians(phi_deg)
            theta = np.linspace(0, np.pi / 2, 100)
            x = np.sin(theta) * np.cos(phi)
            y = np.sin(theta) * np.sin(phi)
            z = np.cos(theta)
            fig.add_trace(
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                    line=dict(color=overlay_color, width=line_width),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        return fig

    def add_custom_axes(
        self,
        fig: go.Figure,
        axis_length: float = 1.2,
        axis_color: str = "black",
        show_labels: bool = True,
    ) -> go.Figure:
        """Add custom coordinate axes with labels.

        Parameters
        ----------
        fig : plotly.graph_objects.Figure
            Existing 3D figure
        axis_length : float, default 1.2
            Length of axis lines
        axis_color : str, default 'black'
            Color for axes
        show_labels : bool, default True
            Show axis labels (E, N, Z)

        Returns
        -------
        fig : plotly.graph_objects.Figure
            Modified figure with custom axes

        """
        # Axis lines
        axes_lines = [
            dict(x=[0, axis_length], y=[0, 0], z=[0, 0]),  # East
            dict(x=[0, 0], y=[0, axis_length], z=[0, 0]),  # North
            dict(x=[0, 0], y=[0, 0], z=[0, axis_length]),  # Up
        ]

        for axis in axes_lines:
            fig.add_trace(
                go.Scatter3d(
                    x=axis["x"],
                    y=axis["y"],
                    z=axis["z"],
                    mode="lines",
                    line=dict(color=axis_color, width=6),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        # Arrowheads
        arrow_tip = axis_length + 0.05
        arrow_size = 0.1
        for pos, direction in zip(
            [[arrow_tip, 0, 0], [0, arrow_tip, 0], [0, 0, arrow_tip]],
            [[arrow_size, 0, 0], [0, arrow_size, 0], [0, 0, arrow_size]],
        ):
            fig.add_trace(
                go.Cone(
                    x=[pos[0]],
                    y=[pos[1]],
                    z=[pos[2]],
                    u=[direction[0]],
                    v=[direction[1]],
                    w=[direction[2]],
                    sizemode="absolute",
                    sizeref=arrow_size,
                    anchor="tip",
                    showscale=False,
                    colorscale=[[0, axis_color], [1, axis_color]],
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

        # Labels
        if show_labels:
            label_offset = axis_length + 0.15
            for label in [
                dict(x=label_offset, y=0, z=0, text="E"),
                dict(x=0, y=label_offset, z=0, text="N"),
                dict(x=0, y=0, z=label_offset, text="Z"),
            ]:
                fig.add_trace(
                    go.Scatter3d(
                        x=[label["x"]],
                        y=[label["y"]],
                        z=[label["z"]],
                        mode="text",
                        text=[label["text"]],
                        textfont=dict(size=16, color=axis_color),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

        return fig


# =============================================================================
# Convenience Functions
# =============================================================================


def visualize_grid_3d(
    grid: HemiGrid,
    data: np.ndarray | None = None,
    title: str | None = None,
    colorscale: str = "Viridis",
    add_overlays: bool = False,
    add_axes: bool = False,
    **kwargs: Any,
) -> go.Figure:
    """Visualize hemispherical grid in 3D interactive plot.

    Convenience function providing simple interface to 3D visualization.

    Parameters
    ----------
    grid : HemiGrid
        Grid to visualize
    data : np.ndarray, optional
        Data values per cell
    title : str, optional
        Plot title
    colorscale : str, default 'Viridis'
        Plotly colorscale name
    add_overlays : bool, default False
        Add elevation rings and meridians
    add_axes : bool, default False
        Add custom coordinate axes
    **kwargs
        Additional parameters passed to plot_hemisphere_surface

    Returns
    -------
    fig : plotly.graph_objects.Figure
        Interactive 3D figure

    Examples
    --------
    >>> from canvod.grids import create_hemigrid
    >>> from canvod.viz import visualize_grid_3d
    >>>
    >>> grid = create_hemigrid(grid_type='equal_area', angular_resolution=10.0)
    >>> fig = visualize_grid_3d(
    ...     grid,
    ...     data=vod_data,
    ...     title="VOD 3D",
    ...     add_overlays=True
    ... )
    >>> fig.show()

    """
    viz = HemisphereVisualizer3D(grid)
    fig = viz.plot_hemisphere_surface(
        data=data, title=title, colorscale=colorscale, **kwargs
    )

    if add_overlays:
        viz.add_spherical_overlays(fig)

    if add_axes:
        viz.add_custom_axes(fig)

    return fig
