import marimo

__generated_with = "0.19.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # canvod-aux Demo

    Simple demonstration of downloading and reading GNSS auxiliary data files.
    """)
    return


@app.cell
def _():
    import datetime
    import tempfile
    from pathlib import Path

    from canvod.auxiliary.clock.reader import ClkFile
    from canvod.auxiliary.ephemeris.reader import Sp3File

    return ClkFile, Path, Sp3File, datetime, tempfile


@app.cell
def _(mo):
    mo.md("""
    ## 1. Download SP3 File Using from_datetime_date()
    """)
    return


@app.cell
def _(Path, Sp3File, datetime):
    _sp3_file = Sp3File.from_datetime_date(
        date=datetime.date(2023, 9, 11),
        agency="GFZ",
        product_type="rapid",
        ftp_server="ftp://gssc.esa.int",
        local_dir=Path("/tmp/tmpfiles"),
    )
    # sp3_file = Sp3File.from_datetime_date(
    #     date=datetime.date(2023, 9, 12),
    #     agency="GFZ",
    #     product_type="rapid",
    #     ftp_server="ftp://gssc.esa.int/gnss",
    #     local_dir=Path("/tmp/tmpfiles"),
    # )

    # sp3_file = Sp3File.from_datetime_date(
    #     date=datetime.date(2023, 9, 11),
    #     agency="COD",
    #     product_type="final",
    #     ftp_server="ftp://gssc.esa.int/gnss",
    #     local_dir=Path("/tmp/tmpfiles"),
    # )
    # sp3_file = Sp3File.from_datetime_date(
    #     date=datetime.date(2023, 9, 12),
    #     agency="COD",
    #     product_type="rapid",
    #     ftp_server="ftp://gssc.esa.int/gnss",
    #     local_dir=Path("/tmp/tmpfiles"),
    # )

    _sp3_file.data
    # dsout = sp3_file.data.resample(epoch='1min').interpolate('linear')
    # dsout.to_netcdf('/tmp/tmpfiles/orbit.nc')

    # sp3_path = Path(
    #     '/path/to/aux_files/01_SP3/COD0MGXFIN_20250010000_01D_05M_ORB.SP3'
    # )

    # sp31 = Sp3File.from_file(sp3_path)
    # sp32 = Sp3File.from_file(sp3_path,
    #                          dimensionless=False,
    #                          add_velocities=True)
    # sp33 = Sp3File.from_file(sp3_path, add_velocities=True)
    return


@app.cell
def _(Path, Sp3File, datetime, tempfile):
    # Download SP3 ephemeris file
    sp3_file = Sp3File.from_datetime_date(
        date=datetime.date(2023, 9, 11),
        agency="COD",
        product_type="final",
        ftp_server="ftp://gssc.esa.int",
        local_dir=Path(tempfile.gettempdir()) / "canvod_demo",
    )

    print(f"Downloaded: {sp3_file.fpath}")
    print(f"Agency: {sp3_file.agency}")
    print(f"Product: {sp3_file.product_type}")
    return (sp3_file,)


@app.cell
def _(mo):
    mo.md("""
    ## 2. Read SP3 Dataset
    """)
    return


@app.cell
def _(sp3_file):
    # Read dataset using .data property (lazy loading)
    sp3_dataset = sp3_file.data

    print(f"Dimensions: {dict(sp3_dataset.sizes)}")
    print(f"Variables: {list(sp3_dataset.data_vars)}")
    print(f"Coordinates: {list(sp3_dataset.coords)}")
    print(
        f"\nTime range: {sp3_dataset.epoch.values[0]} to {sp3_dataset.epoch.values[-1]}"
    )
    print(f"Satellites: {len(sp3_dataset.sv)}")

    sp3_dataset
    return (sp3_dataset,)


@app.cell
def _(mo, sp3_dataset):
    import numpy as np

    # Extract sv labels as strings
    sv_labels = [str(s) for s in sp3_dataset.sv.values]

    # Define "system" as first char (e.g., "G01" -> "G")
    systems = sorted({s[0] for s in sv_labels if len(s) > 0})

    system_dropdown = mo.ui.dropdown(
        options=systems,
        value=systems[0] if systems else None,
        label="System",
    )

    def sv_options_for_system(sys):
        return sorted([s for s in sv_labels if s.startswith(sys)]) if sys else []

    return np, sv_options_for_system, system_dropdown


@app.cell
def _(mo, sv_options_for_system, system_dropdown):
    sv_dropdown = mo.ui.dropdown(
        options=sv_options_for_system(system_dropdown.value),
        value=(
            sv_options_for_system(system_dropdown.value)[0]
            if sv_options_for_system(system_dropdown.value)
            else None
        ),
        label="SV",
    )
    return


@app.cell
def _(mo, system_dropdown):
    mo.hstack([system_dropdown])
    return


@app.cell
def _(mo, sp3_dataset, system_dropdown):
    import plotly.graph_objects as go

    # Filter SVs by system (e.g. "G", "E", "R")
    svs = [
        str(s)
        for s in sp3_dataset.sv.values
        if str(s).startswith(system_dropdown.value)
    ]

    if not svs:
        mo.md("No SV available for this system.")
    else:
        fig = go.Figure()

        for sat in svs:
            ds = sp3_dataset.sel(sv=sat)

            step = 1  # increase to 2/5/10 if heavy
            x = ds.X.values[::step]
            y = ds.Y.values[::step]
            z = ds.Z.values[::step]

            fig.add_trace(
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                    name=sat,
                    showlegend=False,  # set True if you want legend spam
                )
            )

        fig.update_layout(
            title=f"SP3 Orbits (ECEF) — System {system_dropdown.value}",
            scene=dict(
                xaxis_title="X",
                yaxis_title="Y",
                zaxis_title="Z",
                aspectmode="manual",
                aspectratio=dict(x=1, y=1, z=1),
            ),
            width=600,
            height=500,
            margin=dict(l=0, r=0, t=40, b=0),
        )

    fig.update_layout(template="plotly_dark")
    fig
    return (go,)


@app.cell
def _(mo):
    mo.md("""
    ## 4. Download CLK File
    """)
    return


@app.cell
def _(ClkFile, Path, datetime, tempfile):
    # Download CLK clock file
    clk_file = ClkFile.from_datetime_date(
        date=datetime.date(2023, 9, 11),
        agency="COD",
        product_type="final",
        ftp_server="ftp://gssc.esa.int",
        local_dir=Path(tempfile.gettempdir()) / "canvod_demo",
    )

    print(f"Downloaded: {clk_file.fpath}")
    return (clk_file,)


@app.cell
def _(mo):
    mo.md("""
    ## 5. Read CLK Dataset
    """)
    return


@app.cell
def _(clk_file):
    # Read clock dataset
    clk_dataset = clk_file.data

    print(f"Dimensions: {dict(clk_dataset.sizes)}")
    print(f"Variables: {list(clk_dataset.data_vars)}")
    print(
        f"Clock offset range: {float(clk_dataset.clock_offset.min()):.6e} to {float(clk_dataset.clock_offset.max()):.6e} seconds"
    )

    clk_dataset
    return


@app.cell
def _(sp3_dataset):
    df = sp3_dataset.to_dataframe().reset_index()
    print(df)
    return (df,)


@app.cell
def _(df, mo):
    table = mo.ui.table(df)
    table
    return (table,)


@app.cell
def _(table):
    table.value
    return


@app.cell
def _(df, mo):
    mo.ui.data_explorer(df)

    return


@app.cell
def _(go, np, table):
    # Sort once
    d = table.value.sort_values(["sv", "epoch"]).copy()

    # Speed magnitude
    d["speed"] = np.sqrt(d["Vx"] ** 2 + d["Vy"] ** 2 + d["Vz"] ** 2)

    _fig = go.Figure()

    # Optional: decimate for performance
    _step = 1  # try 5 or 10 if it gets slow

    for sv in d["sv"].unique():
        s = d[d["sv"] == sv].iloc[::_step]

        _fig.add_trace(
            go.Scatter3d(
                x=s["X"],
                y=s["Y"],
                z=s["Z"],
                mode="lines",
                line=dict(
                    width=3,
                    color=s["speed"],
                    colorscale="Turbo",
                ),
                name=str(sv),
                showlegend=False,  # set True if you really want it
            )
        )

    _fig.update_layout(
        title=f"3D Trajectories of {d['sv'].unique()} colored by speed",
        scene=dict(
            xaxis_title="X",
            yaxis_title="Y",
            zaxis_title="Z",
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=1),
        ),
        width=700,
        height=550,
        margin=dict(l=0, r=0, t=40, b=0),
    )

    _fig.show()
    return


@app.cell
def _(mo):
    mo.md("""
    ---

    ## Summary

    **Two ways to load files:**

    1. **`from_datetime_date()`** - Download from FTP server
       ```python
       file = Sp3File.from_datetime_date(
           date=datetime.date(2023, 9, 11),
           agency="COD",
           product_type="final",
           ftp_server="ftp://gssc.esa.int/gnss",
           local_dir=Path("/path/to/dir"),
       )
       ```

    2. **`from_file()`** - Read existing local file
       ```python
       file = Sp3File.from_file(
           filepath,
           add_velocities=True,  # SP3 only
           dimensionless=True,
       )
       ```

    **Access data:**
    ```python
    dataset = file.data  # Lazy-loads xarray.Dataset
    ```

    **Key attributes:**
    - `file.fpath` - Path to file
    - `file.agency` - Analysis center code
    - `file.product_type` - Product type (final/rapid)
    - `file.data` - xarray.Dataset (lazy-loaded)
    """)
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
