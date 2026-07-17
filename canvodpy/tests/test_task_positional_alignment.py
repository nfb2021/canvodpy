"""Regression test: task-tuple values must land on the right parameter.

``prepare_batch_tasks`` builds flat positional tuples that ``pipeline.py``'s
``_submit_task`` splats straight into ``preprocess_with_hermite_aux`` /
``preprocess_reference_with_hermite_aux_fanout`` (after stripping the
trailing §47 fan-out marker). Nothing type-checks that a tuple element
lands on the *intended* parameter -- a silent off-by-one here (found during
§44 review: the pre-existing dormant broadcast_canopy_file/canopy_reader_fmt
misalignment silently ate the new ``aux_group`` slot too) fails loudly only
much later (wrong/missing aux data), not at the call site itself. This test
binds the exact tuple shapes ``prepare_batch_tasks`` constructs against the
real function signatures via ``inspect.signature().bind()`` so a future
field addition that breaks positional alignment fails here instead.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from canvodpy.orchestrator.processor import (
    preprocess_reference_with_hermite_aux_fanout,
    preprocess_with_hermite_aux,
)

from canvod.auxiliary.position.position import ECEFPosition

_POSITION = ECEFPosition(x=1.0, y=2.0, z=3.0)


def test_non_fanout_tuple_delivers_aux_group_to_its_own_parameter() -> None:
    """Mirrors prepare_batch_tasks's per-file (canopy/reference) tuple."""
    aux_group_value = "some-fingerprint/2025213"
    task_args = (
        Path("file.rnx"),  # rnx_file
        None,  # keep_vars
        Path("aux.zarr"),  # aux_zarr_path
        _POSITION,  # receiver_position
        "canopy_01",  # receiver_name
        None,  # keep_sids
        "rinex3",  # effective_reader
        False,  # use_sbf_geometry
        False,  # store_radial_distance
        None,  # broadcast_canopy_file
        None,  # canopy_reader_fmt
        None,  # broadcast_canopy_fmt (explicit filler)
        True,  # pad_global_sid (explicit filler)
        aux_group_value,  # aux_group
        False,  # is_reference_fanout marker -- stripped before the call
    )

    bound = inspect.signature(preprocess_with_hermite_aux).bind(*task_args[:-1])
    bound.apply_defaults()

    assert bound.arguments["aux_group"] == aux_group_value
    assert bound.arguments["rnx_file"] == Path("file.rnx")
    assert bound.arguments["receiver_position"] is _POSITION


def test_fanout_tuple_delivers_aux_group_to_its_own_parameter() -> None:
    """Mirrors prepare_batch_tasks's reference fan-out tuple (§47)."""
    aux_group_value = "some-fingerprint/2025213"
    canopy_positions = {"reference_01_canopy_01": _POSITION}
    task_args = (
        Path("ref.rnx"),  # rnx_file
        None,  # keep_vars
        Path("aux.zarr"),  # aux_zarr_path
        canopy_positions,  # canopy_positions
        "reference:ref_dir",  # reference_lane_key
        None,  # keep_sids
        "rinex3",  # effective_reader
        False,  # store_radial_distance
        True,  # store_sbf_raw_observables
        True,  # pad_global_sid
        aux_group_value,  # aux_group
        True,  # is_reference_fanout marker -- stripped before the call
    )

    bound = inspect.signature(preprocess_reference_with_hermite_aux_fanout).bind(
        *task_args[:-1]
    )
    bound.apply_defaults()

    assert bound.arguments["aux_group"] == aux_group_value
    assert bound.arguments["canopy_positions"] is canopy_positions
