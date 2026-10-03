"""Temporal aggregation operation."""

import time
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
import structlog
import xarray as xr

from canvod.ops.base import Op, OpResult

logger = structlog.get_logger(__name__)


def _bin_starts(epochs: np.ndarray, freq_ns: int) -> np.ndarray:
    """Start of the bin of each epoch; bins are aligned to 1970-01-01 00:00."""
    ns = np.asarray(epochs, dtype="datetime64[ns]").astype(np.int64)
    return (ns - ns % freq_ns).astype("datetime64[ns]")


def _wrap_pi(x: pl.Expr) -> pl.Expr:
    """Wrap an angle in radians to [-pi, pi)."""
    return (x + np.pi) % (2 * np.pi) - np.pi


class TemporalAggregate(Op):
    """Aggregate an ``(epoch, sid)`` dataset to regular time bins.

    Each bin starts at a multiple of ``freq`` counted from 00:00 of the day
    and is labeled with its start. Missing values (NaN) are ignored; a bin
    without any value stays NaN. The azimuth ``phi`` (radians) is aggregated
    as an angle, so a satellite crossing north (0 rad) does not average to
    south: each value is taken relative to the first value of its bin.

    Parameters
    ----------
    freq : str
        Bin length as a pandas offset alias (e.g. ``"1min"``, ``"30s"``).
    method : str
        Aggregation method: ``"mean"`` or ``"median"``.
    """

    def __init__(self, freq: str = "1min", method: str = "mean") -> None:
        if method not in ("mean", "median"):
            msg = f"Unsupported aggregation method: {method!r}"
            raise ValueError(msg)
        self._freq = freq
        self._method = method

    @property
    def name(self) -> str:
        return "temporal_aggregate"

    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]:
        t0 = time.perf_counter()
        params: dict[str, Any] = {"freq": self._freq, "method": self._method}
        input_shape = {str(k): int(v) for k, v in dict(ds.sizes).items()}

        freq_ns = int(pd.tseries.frequencies.to_offset(self._freq).nanos)
        epoch_vals = np.asarray(ds.epoch.values, dtype="datetime64[ns]")
        bins = _bin_starts(epoch_vals, freq_ns)

        # --- Nothing to do if every epoch already is the start of its own bin ---
        if np.array_equal(bins, epoch_vals) and len(np.unique(bins)) == len(bins):
            logger.info("temporal_aggregation_skipped", requested=self._freq)
            result = OpResult(
                op_name=self.name,
                parameters=params,
                input_shape=input_shape,
                output_shape=input_shape,
                duration_seconds=time.perf_counter() - t0,
                notes=f"no-op: every epoch is already the start of a {self._freq} bin",
            )
            return ds, result

        # --- Identify coordinate roles ---
        sid_only_coords: list[str] = []
        epoch_sid_coords: list[str] = []
        for cname, coord in ds.coords.items():
            if cname in ("epoch", "sid"):
                continue
            dims = coord.dims
            if dims == ("sid",):
                sid_only_coords.append(str(cname))
            elif set(dims) == {"epoch", "sid"}:
                epoch_sid_coords.append(str(cname))

        data_var_names: list[str] = [str(v) for v in ds.data_vars]
        agg_columns: list[str] = data_var_names + epoch_sid_coords

        # --- Long-form Polars DataFrame; NaN becomes null so it is skipped ---
        n_epoch, n_sid = len(epoch_vals), ds.sizes["sid"]
        columns: dict[str, Any] = {
            "time_bin": pl.Series(np.repeat(bins, n_sid)),
            "sid_idx": np.tile(np.arange(n_sid), n_epoch),
        }
        for col in agg_columns:
            arr = ds[col].transpose("epoch", "sid").values.astype(np.float64)
            columns[col] = pl.Series(col, arr.ravel(), nan_to_null=True)
        df = pl.DataFrame(columns)

        keys = ["time_bin", "sid_idx"]
        agg_exprs = []
        for col in agg_columns:
            value = pl.col(col)
            if col == "phi":
                ref = value.drop_nulls().first()
                value = _wrap_pi(value - ref)
                agg = value.mean() if self._method == "mean" else value.median()
                agg = (agg + ref) % (2 * np.pi)
            else:
                agg = value.mean() if self._method == "mean" else value.median()
            agg_exprs.append(agg.alias(col))
        grouped = df.group_by(keys).agg(agg_exprs)

        # --- Pivot back to (epoch, sid) ---
        new_epochs = np.unique(bins)
        ei = np.searchsorted(new_epochs, grouped["time_bin"].to_numpy())
        si = grouped["sid_idx"].to_numpy()
        var_arrays: dict[str, np.ndarray] = {}
        for col in agg_columns:
            arr = np.full((len(new_epochs), n_sid), np.nan, dtype=np.float64)
            arr[ei, si] = grouped[col].fill_null(np.nan).to_numpy()
            dtype = ds[col].dtype
            var_arrays[col] = arr.astype(dtype) if dtype.kind == "f" else arr

        # --- Rebuild xarray Dataset ---
        new_coords: dict[str, Any] = {
            "epoch": ("epoch", new_epochs, ds["epoch"].attrs),
            "sid": ds["sid"],
        }
        for cname in sid_only_coords:
            new_coords[cname] = ds.coords[cname]
        for cname in epoch_sid_coords:
            new_coords[cname] = (
                ("epoch", "sid"),
                var_arrays.pop(cname),
                ds.coords[cname].attrs,
            )

        new_data_vars: dict[str, Any] = {
            vname: (("epoch", "sid"), var_arrays[vname], ds[vname].attrs)
            for vname in data_var_names
        }

        out = xr.Dataset(new_data_vars, coords=new_coords, attrs=ds.attrs.copy())

        duration = time.perf_counter() - t0
        output_shape = {str(k): int(v) for k, v in dict(out.sizes).items()}

        logger.info(
            "temporal_aggregation_complete",
            input_shape=input_shape,
            output_shape=output_shape,
            duration_s=round(duration, 2),
        )
        result = OpResult(
            op_name=self.name,
            parameters=params,
            input_shape=input_shape,
            output_shape=output_shape,
            duration_seconds=duration,
        )
        return out, result


def temporal_aggregate(
    ds: xr.Dataset,
    freq: str = "1min",
    method: str = "mean",
) -> xr.Dataset:
    """Convenience function: temporally aggregate a dataset.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset with ``(epoch, sid)`` dimensions.
    freq : str
        Target frequency.
    method : str
        ``"mean"`` or ``"median"``.

    Returns
    -------
    xr.Dataset
        Aggregated dataset.
    """
    op = TemporalAggregate(freq=freq, method=method)
    out, _ = op(ds)
    return out
