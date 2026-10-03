"""``preprocess_files``: the configured operations on one receiver's day."""

import json

import numpy as np
import xarray as xr

from canvod.config.models import PreprocessingConfig
from canvod.ops import TemporalAggregate, preprocess_files

CONFIG = PreprocessingConfig.model_validate(
    {
        "temporal_aggregation": {"freq": "1min", "method": "median"},
        "grid_assignment": {"grid_type": "equal_area", "angular_resolution": 10.0},
    }
)


def _file(start: str, n: int, sids: list[str], file_hash: str, seed: int):
    rng = np.random.default_rng(seed)
    epochs = np.datetime64(start, "ns") + np.arange(n) * np.timedelta64(5, "s")
    shape = (n, len(sids))
    return xr.Dataset(
        {
            "SNR": (("epoch", "sid"), rng.uniform(20, 50, shape).astype("float32")),
            "phi": (("epoch", "sid"), rng.uniform(0, 2 * np.pi, shape)),
            "theta": (("epoch", "sid"), rng.uniform(0, 1.5, shape)),
        },
        coords={
            "epoch": epochs,
            "sid": sids,
            "band": ("sid", [s.split("|")[1] for s in sids]),
        },
        attrs={"File Hash": file_hash},
    )


# 00:00:00-00:01:25 and 00:01:30-00:02:55: the 00:01 bin spans both files.
FILE_A = _file("2025-01-01T00:00:00", 18, ["G01|L1", "G02|L1"], "A", 0)
FILE_B = _file("2025-01-01T00:01:30", 18, ["G01|L1", "G03|L2"], "B", 1)


def test_nothing_set_only_records_it():
    out = preprocess_files([("a", FILE_A)], None)
    assert out[0][0] == "a"
    xr.testing.assert_identical(out[0][1].drop_attrs(), FILE_A.drop_attrs())
    assert out[0][1].attrs == {"File Hash": "A", "Preprocessing": "{}"}


def test_bin_spanning_two_files_uses_both():
    out = preprocess_files([("b", FILE_B), ("a", FILE_A)], CONFIG)

    # Time order; the shared bin belongs to the file with its first observation.
    assert [key for key, _ in out] == ["a", "b"]
    np.testing.assert_array_equal(
        out[0][1]["epoch"].values,
        np.array(["2025-01-01T00:00", "2025-01-01T00:01"], dtype="datetime64[ns]"),
    )
    np.testing.assert_array_equal(
        out[1][1]["epoch"].values,
        np.array(["2025-01-01T00:02"], dtype="datetime64[ns]"),
    )

    # Same values as aggregating the joined day at once.
    joined = xr.concat(
        [FILE_A.drop_vars("band"), FILE_B.drop_vars("band")], "epoch", join="outer"
    )
    expected, _ = TemporalAggregate("1min", "median")(joined)
    got = xr.concat([ds for _, ds in out], "epoch")
    np.testing.assert_array_equal(
        got["SNR"].values, expected["SNR"].sel(sid=got["sid"]).values
    )


def test_each_file_keeps_its_attrs_and_records_the_operations():
    out = dict(preprocess_files([("a", FILE_A), ("b", FILE_B)], CONFIG))
    assert out["a"].attrs["File Hash"] == "A"
    assert out["b"].attrs["File Hash"] == "B"
    assert json.loads(out["a"].attrs["Preprocessing"]) == {
        "grid_assignment": {"angular_resolution": 10.0, "grid_type": "equal_area"},
        "temporal_aggregation": {"freq": "1min", "method": "median"},
    }
    assert "cell_id_equal_area_10.0deg" in out["b"].data_vars


def test_signals_of_all_files_keep_their_coordinates():
    out = dict(preprocess_files([("a", FILE_A), ("b", FILE_B)], CONFIG))
    for ds in out.values():
        assert list(ds["sid"].values) == ["G01|L1", "G02|L1", "G03|L2"]
        assert list(ds["band"].values) == ["L1", "L1", "L2"]


def test_file_inside_an_earlier_bin_is_left_out():
    short = _file("2025-01-01T00:00:30", 3, ["G01|L1", "G02|L1"], "S", 2)
    out = preprocess_files([("a", FILE_A), ("s", short)], CONFIG)
    assert [key for key, _ in out] == ["a"]
