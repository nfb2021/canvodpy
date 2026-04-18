# NOTE: Run from monorepo root with `uv run marimo edit` or `uv run marimo run`
# to pick up workspace packages (canvod-audit, canvod-store, etc.).
# Do NOT add a PEP 723 `# /// script` block.

import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # Broadcast vs Agency Ephemeris: Grid Cell Impact

        Both ephemeris sources place the satellite in roughly the same direction,
        but the SBF broadcast path quantises azimuth/elevation to 0.01° steps while
        the agency path (SP3 Hermite interpolation) computes at floating-point precision.

        **Key question:** Are the angular differences large enough to shift observations
        into different 2° equal-area hemigrid cells — and thus distort gridded VOD maps?
        """
    )
    return (mo,)


@app.cell
def _():
    import numpy as np
    import plotly.graph_objects as go
    import xarray as xr
    from scipy.spatial import cKDTree  # type: ignore[unresolved-import]

    return cKDTree, go, np, xr


@app.cell
def _():
    import os
    from pathlib import Path

    AUDIT_ROOT = Path(
        os.environ.get("CANVOD_AUDIT_OUTPUT", "/Volumes/ExtremePro/canvod_audit_output")
    )
    BROADCAST_STORE = (
        AUDIT_ROOT / "tier1_broadcast_vs_agency/Rosalia/canvodpy_SBF_broadcast_store"
    )
    AGENCY_STORE = AUDIT_ROOT / "tier1_sbf_vs_rinex/Rosalia/canvodpy_SBF_allvars_store"
    return AGENCY_STORE, AUDIT_ROOT, BROADCAST_STORE


@app.cell
def _(AGENCY_STORE, BROADCAST_STORE, np, xr):
    from canvod.audit.runners.common import open_store

    _s_b = open_store(BROADCAST_STORE)
    _s_a = open_store(AGENCY_STORE)
    ds_b = xr.open_zarr(
        store=_s_b.readonly_session().__enter__().store, group="canopy_01"
    )
    ds_a = xr.open_zarr(
        store=_s_a.readonly_session().__enter__().store, group="canopy_01"
    )

    shared_sids = sorted(set(ds_b.sid.values) & set(ds_a.sid.values))
    shared_epochs = np.intersect1d(ds_b.epoch.values, ds_a.epoch.values)

    phi_b = ds_b["phi"].sel(epoch=shared_epochs, sid=shared_sids).values
    phi_a = ds_a["phi"].sel(epoch=shared_epochs, sid=shared_sids).values
    theta_b = ds_b["theta"].sel(epoch=shared_epochs, sid=shared_sids).values
    theta_a = ds_a["theta"].sel(epoch=shared_epochs, sid=shared_sids).values

    valid = (
        ~np.isnan(phi_b) & ~np.isnan(phi_a) & ~np.isnan(theta_b) & ~np.isnan(theta_a)
    )
    phi_b_v = phi_b[valid]
    phi_a_v = phi_a[valid]
    theta_b_v = theta_b[valid]
    theta_a_v = theta_a[valid]

    # Angular separation (great-circle on unit sphere)
    _dphi = phi_b_v - phi_a_v
    _el_b = np.pi / 2 - theta_b_v
    _el_a = np.pi / 2 - theta_a_v
    _cos_sep = np.sin(_el_b) * np.sin(_el_a) + np.cos(_el_b) * np.cos(_el_a) * np.cos(
        _dphi
    )
    angular_sep_deg = np.degrees(np.arccos(np.clip(_cos_sep, -1, 1)))
    return angular_sep_deg, phi_a_v, phi_b_v, theta_a_v, theta_b_v


@app.cell
def _(angular_sep_deg, mo, np):
    mo.md(f"""
    ## Angular separation statistics

    | Metric | Value |
    |--------|-------|
    | Observations | {len(angular_sep_deg):,} |
    | Mean | {np.mean(angular_sep_deg):.4f}° |
    | Median | {np.median(angular_sep_deg):.4f}° |
    | p95 | {np.percentile(angular_sep_deg, 95):.4f}° |
    | p99 | {np.percentile(angular_sep_deg, 99):.4f}° |
    | Max | {np.max(angular_sep_deg):.4f}° |
    | > 1° | {int(np.sum(angular_sep_deg > 1.0)):,} ({100 * np.sum(angular_sep_deg > 1.0) / len(angular_sep_deg):.3f}%) |
    """)
    return


@app.cell
def _(cKDTree, np):
    from canvod.grids.grids_impl.equal_area_grid import EqualAreaBuilder

    grid = EqualAreaBuilder(angular_resolution=2.0).build()
    grid_coords = grid.coords  # (n_cells, 2): phi, theta
    _phi_g = grid_coords[:, 0]
    _theta_g = grid_coords[:, 1]
    _xyz_g = np.column_stack(
        [
            np.sin(_theta_g) * np.cos(_phi_g),
            np.sin(_theta_g) * np.sin(_phi_g),
            np.cos(_theta_g),
        ]
    )
    grid_tree = cKDTree(_xyz_g)
    return grid_coords, grid_tree


@app.cell
def _(grid_tree, np, phi_a_v, phi_b_v, theta_a_v, theta_b_v):
    def _assign(phi, theta):
        xyz = np.column_stack(
            [
                np.sin(theta) * np.cos(phi),
                np.sin(theta) * np.sin(phi),
                np.cos(theta),
            ]
        )
        _, idx = grid_tree.query(xyz)
        return idx

    cells_a = _assign(phi_a_v, theta_a_v)
    cells_b = _assign(phi_b_v, theta_b_v)
    mismatch = cells_a != cells_b
    return cells_a, mismatch


@app.cell
def _(angular_sep_deg, mismatch, mo, np, theta_a_v):
    _n_mm = int(np.sum(mismatch))
    _n_total = len(mismatch)
    _pct = 100 * _n_mm / _n_total

    _theta_deg = np.degrees(theta_a_v)
    _rows = []
    for _lo in range(0, 91, 10):
        _hi = min(_lo + 10, 91)
        _band = (_theta_deg >= _lo) & (_theta_deg < _hi)
        _n_band = int(np.sum(_band))
        if _n_band == 0:
            continue
        _n_mm_band = int(np.sum(mismatch & _band))
        _rows.append(
            f"| {_lo}--{_hi} deg | {_n_mm_band:,} / {_n_band:,} | {100 * _n_mm_band / _n_band:.1f}% |"
        )

    _sep_mm = angular_sep_deg[mismatch]

    mo.md(f"""
    ## Grid cell mismatch (2 deg equal-area hemigrid)

    **{_n_mm:,} / {_n_total:,} observations ({_pct:.1f}%) land in a different cell.**

    Mismatched observations have angular sep: mean {np.mean(_sep_mm):.3f} deg, min {np.min(_sep_mm):.4f} deg

    ### Mismatch rate by polar angle

    | Band | Mismatches | Rate |
    |------|-----------|------|
    {chr(10).join(_rows)}

    The rate is uniform across all polar angles (~6%), confirming this is a
    resolution artefact (0.01 deg SBF quantisation), not a geometry-dependent effect.
    """)
    return


@app.cell
def _(angular_sep_deg, go):
    """Histogram of angular separations."""
    _clipped = angular_sep_deg[angular_sep_deg < 1.0]

    _fig = go.Figure()
    _fig.add_trace(
        go.Histogram(
            x=_clipped,
            nbinsx=200,
            marker_color="#ABC8A4",
            opacity=0.85,
        )
    )
    _fig.add_vline(
        x=0.09,
        line_dash="dash",
        line_color="#375D3B",
        annotation_text="median 0.09 deg",
    )

    _fig.update_layout(
        title="Angular separation: broadcast vs agency (< 1 deg shown)",
        xaxis_title="Angular separation (deg)",
        yaxis_title="Count",
        height=400,
        template="plotly_dark",
        paper_bgcolor="#0d0d0d",
        plot_bgcolor="#1a1a1a",
        font=dict(family="Space Grotesk", color="#E1E6B9"),
    )
    _fig.update_xaxes(gridcolor="#333")
    _fig.update_yaxes(gridcolor="#333")
    _fig
    return


@app.cell
def _(angular_sep_deg, go, mismatch, np, phi_a_v, theta_a_v):
    """Polar plot: all observations colored by angular separation."""
    _n = len(phi_a_v)
    _step = max(1, _n // 5000)
    _idx = np.arange(0, _n, _step)

    _phi_deg = np.degrees(phi_a_v[_idx])
    _theta_deg = np.degrees(theta_a_v[_idx])
    _sep = angular_sep_deg[_idx]
    _mm = mismatch[_idx]

    _fig = go.Figure()

    _fig.add_trace(
        go.Scatterpolar(
            r=_theta_deg,
            theta=_phi_deg,
            mode="markers",
            marker=dict(
                size=3,
                color=_sep,
                colorscale=[
                    [0, "#1a1a1a"],
                    [0.05, "#375D3B"],
                    [0.2, "#ABC8A4"],
                    [1.0, "#E1E6B9"],
                ],
                cmin=0,
                cmax=0.3,
                colorbar=dict(title="sep (deg)", len=0.6),
                opacity=0.6,
            ),
            name="all obs",
            showlegend=False,
        )
    )

    # Overlay mismatched observations
    _mm_abs = np.where(_mm)[0]
    if len(_mm_abs) > 0:
        _mm_global = _idx[_mm_abs]
        _fig.add_trace(
            go.Scatterpolar(
                r=np.degrees(theta_a_v[_mm_global]),
                theta=np.degrees(phi_a_v[_mm_global]),
                mode="markers",
                marker=dict(size=6, color="#ff4444", opacity=0.7, symbol="x"),
                name="cell mismatch",
            )
        )

    _fig.update_layout(
        title="Hemisphere: angular offset (color) + cell mismatches (red x)",
        polar=dict(
            radialaxis=dict(
                range=[0, 90],
                tickvals=[0, 15, 30, 45, 60, 75, 90],
                ticktext=["0", "15", "30", "45", "60", "75", "90"],
                gridcolor="#333",
                color="#E1E6B9",
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                gridcolor="#333",
                color="#E1E6B9",
            ),
            bgcolor="#0d0d0d",
        ),
        height=700,
        template="plotly_dark",
        paper_bgcolor="#0d0d0d",
        font=dict(family="Space Grotesk", color="#E1E6B9"),
        showlegend=True,
        legend=dict(x=1.15, y=0.95),
    )
    _fig
    return


@app.cell
def _(cells_a, go, grid_coords, mismatch, np):
    """Hemigrid heatmap: mismatch rate per cell."""
    _unique_cells = np.unique(cells_a)
    _n_uc = len(_unique_cells)
    _cell_mm_rate = np.zeros(_n_uc)
    _cell_count = np.zeros(_n_uc)

    for _i in range(_n_uc):
        _c = _unique_cells[_i]
        _mask = cells_a == _c
        _cell_count[_i] = float(np.sum(_mask))
        if _cell_count[_i] > 0:
            _cell_mm_rate[_i] = float(np.sum(mismatch[_mask])) / _cell_count[_i]

    _phi_c = np.degrees(grid_coords[_unique_cells, 0])
    _theta_c = np.degrees(grid_coords[_unique_cells, 1])

    # Only show cells with at least 10 observations
    _show_idx = np.where(_cell_count >= 10)[0]

    _fig = go.Figure()
    _fig.add_trace(
        go.Scatterpolar(
            r=_theta_c[_show_idx],
            theta=_phi_c[_show_idx],
            mode="markers",
            marker=dict(
                size=np.clip(_cell_count[_show_idx] / 20.0, 4.0, 20.0),
                color=100.0 * _cell_mm_rate[_show_idx],
                colorscale=[
                    [0, "#1a1a1a"],
                    [0.3, "#375D3B"],
                    [0.6, "#ABC8A4"],
                    [1.0, "#E1E6B9"],
                ],
                cmin=0,
                cmax=15,
                colorbar=dict(title="Mismatch %", len=0.6),
                opacity=0.8,
            ),
            text=[
                f"cell {_unique_cells[_j]}: {100 * _cell_mm_rate[_j]:.1f}% ({int(_cell_count[_j])} obs)"
                for _j in _show_idx
            ],
            hoverinfo="text",
            showlegend=False,
        )
    )

    _fig.update_layout(
        title="Hemigrid: cell mismatch rate (%, size = obs count)",
        polar=dict(
            radialaxis=dict(
                range=[0, 90],
                tickvals=[0, 15, 30, 45, 60, 75, 90],
                ticktext=["0", "15", "30", "45", "60", "75", "90"],
                gridcolor="#333",
                color="#E1E6B9",
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                gridcolor="#333",
                color="#E1E6B9",
            ),
            bgcolor="#0d0d0d",
        ),
        height=700,
        template="plotly_dark",
        paper_bgcolor="#0d0d0d",
        font=dict(family="Space Grotesk", color="#E1E6B9"),
    )
    _fig
    return


@app.cell
def _(mo):
    mo.md("""
    ## Displacement vectors

    Each arrow shows the offset from the agency position (tail) to the broadcast
    position (head) for a subsample of observations. Vectors are **scaled up**
    (geodetic exaggeration) to make the sub-degree displacements visible on the
    hemisphere. Color encodes the magnitude.
    """)
    return


@app.cell
def _(mo):
    scale_slider = mo.ui.slider(
        start=10,
        stop=200,
        value=50,
        step=10,
        label="Vector scale factor",
    )
    min_diff_slider = mo.ui.slider(
        start=0.0,
        stop=1.0,
        value=0.0,
        step=0.01,
        label="Min angular difference (deg)",
    )
    mo.hstack([scale_slider, min_diff_slider])
    return min_diff_slider, scale_slider


@app.cell
def _(
    angular_sep_deg,
    go,
    min_diff_slider,
    mismatch,
    np,
    phi_a_v,
    phi_b_v,
    scale_slider,
    theta_a_v,
    theta_b_v,
):
    """Polar plot with scaled displacement vectors (geodetic exaggeration)."""
    _scale = scale_slider.value
    _min_diff = min_diff_slider.value

    # Filter by minimum angular difference, then subsample
    _above = np.where(angular_sep_deg >= _min_diff)[0]
    _step = max(1, len(_above) // 1500)
    _idx = _above[::_step]

    _phi_a = np.degrees(phi_a_v[_idx])
    _theta_a = np.degrees(theta_a_v[_idx])
    _phi_b = np.degrees(phi_b_v[_idx])
    _theta_b = np.degrees(theta_b_v[_idx])
    _sep = angular_sep_deg[_idx]
    _mm = mismatch[_idx]

    # Scaled displacement: agency + scale * (broadcast - agency)
    _dphi = _phi_b - _phi_a
    # Handle azimuth wrap-around
    _dphi = np.where(_dphi > 180, _dphi - 360, _dphi)
    _dphi = np.where(_dphi < -180, _dphi + 360, _dphi)
    _dtheta = _theta_b - _theta_a

    _phi_tip = _phi_a + _scale * _dphi
    _theta_tip = _theta_a + _scale * _dtheta

    _fig = go.Figure()

    # Draw vectors as lines from agency to scaled broadcast position
    _phi_lines = []
    _theta_lines = []
    _colors = []
    for _i in range(len(_idx)):
        _phi_lines.extend([_phi_a[_i], _phi_tip[_i], None])
        _theta_lines.extend([_theta_a[_i], _theta_tip[_i], None])

    _fig.add_trace(
        go.Scatterpolar(
            r=_theta_lines,
            theta=_phi_lines,
            mode="lines",
            line=dict(color="#ABC8A4", width=1),
            opacity=0.4,
            showlegend=False,
            hoverinfo="skip",
        )
    )

    # Arrow tips (broadcast, scaled)
    _fig.add_trace(
        go.Scatterpolar(
            r=_theta_tip,
            theta=_phi_tip,
            mode="markers",
            marker=dict(
                size=3,
                color=_sep,
                colorscale=[
                    [0, "#375D3B"],
                    [0.3, "#ABC8A4"],
                    [0.7, "#E1E6B9"],
                    [1.0, "#ff4444"],
                ],
                cmin=0,
                cmax=0.3,
                colorbar=dict(title="sep (deg)", len=0.5),
                opacity=0.8,
            ),
            name="broadcast (scaled)",
            showlegend=False,
        )
    )

    # Agency positions (tails)
    _fig.add_trace(
        go.Scatterpolar(
            r=_theta_a,
            theta=_phi_a,
            mode="markers",
            marker=dict(size=2, color="#666666", opacity=0.3),
            name="agency",
            showlegend=False,
        )
    )

    # Highlight mismatched vectors
    _mm_abs = np.where(_mm)[0]
    if len(_mm_abs) > 0:
        _fig.add_trace(
            go.Scatterpolar(
                r=_theta_tip[_mm_abs],
                theta=_phi_tip[_mm_abs],
                mode="markers",
                marker=dict(size=5, color="#ff4444", opacity=0.8, symbol="circle"),
                name="cell mismatch",
            )
        )

    _fig.update_layout(
        title=f"Displacement vectors (scale: {_scale}x, min diff: {_min_diff:.2f}°, n={len(_idx):,})",
        polar=dict(
            radialaxis=dict(
                range=[0, 90],
                tickvals=[0, 15, 30, 45, 60, 75, 90],
                ticktext=["0", "15", "30", "45", "60", "75", "90"],
                gridcolor="#333",
                color="#E1E6B9",
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                gridcolor="#333",
                color="#E1E6B9",
            ),
            bgcolor="#0d0d0d",
        ),
        height=750,
        template="plotly_dark",
        paper_bgcolor="#0d0d0d",
        font=dict(family="Space Grotesk", color="#E1E6B9"),
        showlegend=True,
        legend=dict(x=1.15, y=0.95),
    )
    _fig
    return


@app.cell
def _(mo):
    mo.md("""
    ## Conclusion

    **~6% of observations shift to a neighbouring grid cell** when using broadcast
    instead of agency ephemeris on a 2 deg equal-area hemigrid. The effect is uniform
    across all polar angles, driven by the 0.01 deg quantisation of the SBF
    azimuth/elevation fields.

    The displacement vector plot confirms the offsets are **randomly oriented** —
    there is no systematic directional bias. This means the effect is a spatial
    blurring (smoothing), not a systematic shift that would distort the VOD map
    in a particular direction.

    **Recommendation:** Use agency (final) products for production-quality gridded
    VOD maps. Broadcast ephemeris is acceptable for non-gridded analysis or coarser
    grids (5 deg+ resolution).
    """)
    return


if __name__ == "__main__":
    app.run()
