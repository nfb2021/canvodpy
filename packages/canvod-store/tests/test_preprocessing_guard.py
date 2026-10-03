"""A store group never mixes data preprocessed in different ways."""

import json

import pytest
from _helpers import GROUP, make_synthetic_dataset

AGGREGATED = json.dumps(
    {"temporal_aggregation": {"freq": "1min", "method": "median"}}, sort_keys=True
)


def _with_record(slot: int, record: str | None):
    ds = make_synthetic_dataset(slot=slot)
    if record is not None:
        ds.attrs["Preprocessing"] = record
    return ds


def test_new_group_accepts_any(tmp_store):
    tmp_store.check_preprocessing_matches(GROUP, _with_record(0, AGGREGATED))


def test_same_preprocessing_appends(tmp_store):
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    tmp_store.write_or_append_group(_with_record(1, AGGREGATED), group_name=GROUP)


def test_unrecorded_group_counts_as_not_preprocessed(tmp_store):
    """Groups written before the record existed hold unprocessed data."""
    tmp_store.write_or_append_group(_with_record(0, None), group_name=GROUP)
    tmp_store.check_preprocessing_matches(GROUP, _with_record(1, "{}"))
    with pytest.raises(ValueError, match="must not\\s+mix"):
        tmp_store.write_or_append_group(_with_record(1, AGGREGATED), group_name=GROUP)


def test_different_preprocessing_is_refused(tmp_store):
    tmp_store.write_or_append_group(_with_record(0, AGGREGATED), group_name=GROUP)
    with pytest.raises(ValueError, match="processing.preprocessing"):
        tmp_store.write_or_append_group(_with_record(1, "{}"), group_name=GROUP)
