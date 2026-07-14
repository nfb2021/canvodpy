import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import xarray as xr

    return Path, xr


@app.cell
def _(Path):
    nc_dir = Path("/Users/work/Downloads/tmp")
    return (nc_dir,)


@app.cell
def _(nc_dir, xr):
    ds_u = xr.load_dataset(nc_dir / "VOD_upper_antenna_2deg_median.nc")
    ds_u
    return


@app.cell
def _(nc_dir, xr):
    ds_l = xr.load_dataset(nc_dir / "VOD_lower_antenna_2deg_median.nc")
    ds_l
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
