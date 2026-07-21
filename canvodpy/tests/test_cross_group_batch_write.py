"""Tests for RinexDataProcessor's cross-group fork/merge batch write path.

dev/cross_group_fork_merge_plan.md. Exercises `_prepare_group_write` /
`_write_group_into_fork` / `_write_receiver_batch_forked` directly against a
real throwaway Icechunk store, via a minimal `RinexDataProcessor` subclass
that skips the real (heavy, Config/Site-coupled) `__init__` and only sets
the handful of attributes the batch-write path actually touches. There's no
existing precedent for constructing a full `RinexDataProcessor` in tests
(nothing in this suite does), and the underlying fork/merge primitive itself
is already covered by `_cooperative_distributed_writing`'s existing
intra-group use -- these tests target the new orchestration logic on top of
it: pre-pass reconciliation for new groups, action/metadata bookkeeping, and
fail-fast merge/commit semantics.

"overwrite" strategy is untouched by this refactor (`_append_to_icechunk`
still handles it, unmodified) -- no dedicated test needed here.

Note on commit count: a batch that creates brand-new groups costs *two*
commits (a sequential pre-pass commit, then the fork/merge batch commit),
not one -- verified empirically that a session can't have its own pending
writes before `.fork()` is called on it (`session.merge(fork)` silently
drops the fork's data in that case), so the pre-pass must commit on its own
clean session before the fork/merge phase opens a fresh one. A batch with
only pre-existing groups still costs exactly one commit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from canvodpy.logging import get_logger
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.store import MyIcechunkStore

_SIDS = [f"G{i:02d}|L1|C" for i in range(1, 6)]


def _make_ds(
    file_id: str, slot: int, n_epochs: int = 10, day: str = "2025-03-28"
) -> xr.Dataset:
    """Small synthetic (epoch, sid) dataset with the required "File Hash" attr.

    ``slot`` offsets the epoch range so distinct files in a batch don't
    temporally overlap -- the dedup guardrail's temporal-overlap check
    (correctly) treats overlapping ranges as duplicates, same as
    `make_synthetic_dataset`'s ``slot`` param in
    ``packages/canvod-store/tests/_helpers.py``.
    """
    base = np.datetime64(f"{day}T00:00:00") + slot * n_epochs * np.timedelta64(5, "s")
    epochs = base + np.arange(n_epochs) * np.timedelta64(5, "s")
    rng = np.random.default_rng(
        int(hashlib.sha256(file_id.encode()).hexdigest()[:8], 16)
    )
    s1c = rng.uniform(30.0, 55.0, (n_epochs, len(_SIDS))).astype(np.float32)
    return xr.Dataset(
        {"S1C": xr.DataArray(s1c, dims=["epoch", "sid"])},
        coords={"epoch": epochs, "sid": _SIDS},
        attrs={
            "File Hash": hashlib.sha256(file_id.encode()).hexdigest()[:16],
            "canonical_name": file_id,
            "physical_path": file_id,
        },
    )


class _FakeSite:
    def __init__(self, store: MyIcechunkStore) -> None:
        self.gnss_store = store
        self.site_name = "testsite"


class _FakeYyyyDoy:
    def __str__(self) -> str:
        return "2025087"


class _FakeMatchedDataDirs:
    yyyydoy = _FakeYyyyDoy()


class _TestProcessor(RinexDataProcessor):
    """Minimal RinexDataProcessor stand-in for the batch-write path only."""

    def __init__(self, store: MyIcechunkStore, strategy: str = "skip") -> None:
        self.site = _FakeSite(store)
        self.matched_data_dirs = _FakeMatchedDataDirs()
        self._logger = get_logger(__name__)
        self._icechunk_log = get_logger(__name__)
        self._gnss_store_strategy = strategy
        self._keeper_tags_enabled = False
        self._config = None  # STEP 8 (rich metadata) no-ops via `except Exception`
        self._reader_name = "rinex3"


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "throwaway_store"
    store_path.mkdir()
    return MyIcechunkStore(store_path)


def _group_input(name: str, files: list[tuple[Path, xr.Dataset]]):
    return (name, files, [f for f, _ in files], None, None, "rinex3")


def _warm_up_source_format(proc: _TestProcessor) -> None:
    """Consume the store's one-time ``source_format`` root-attr commit.

    `MyIcechunkStore.set_root_attrs` (STEP 7, fired once per store on the
    first-ever write when ``source_format`` is still ``None``) does its own
    separate commit -- unrelated to the pre-pass/batch commits under test.
    Call this first in any test that asserts an exact commit count on a
    fresh store, on a throwaway group name, so the real assertions aren't
    coupled to this orthogonal one-time side effect.
    """
    proc._write_receiver_batch_forked(
        [_group_input("_warmup", [(Path("warmup.rnx"), _make_ds("warmup", slot=0))])]
    )


def test_case_a_steady_state_writes_to_two_pre_existing_groups(
    store: MyIcechunkStore,
) -> None:
    """Two pre-existing groups, write new files to each via the batch path."""
    proc = _TestProcessor(store)

    seed_ref = [(Path("ref_seed.rnx"), _make_ds("ref_seed", slot=0))]
    seed_can = [(Path("can_seed.rnx"), _make_ds("can_seed", slot=0))]
    proc._write_receiver_batch_forked(
        [
            _group_input("reference_01", seed_ref),
            _group_input("canopy_01", seed_can),
        ],
    )
    assert set(store.list_groups() or []) == {"reference_01", "canopy_01"}

    ref_files = [
        (Path("ref_2.rnx"), _make_ds("ref_2", slot=1)),
        (Path("ref_3.rnx"), _make_ds("ref_3", slot=2)),
    ]
    can_files = [(Path("can_2.rnx"), _make_ds("can_2", slot=1))]

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = proc._write_receiver_batch_forked(
        [
            _group_input("reference_01", ref_files),
            _group_input("canopy_01", can_files),
        ],
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 1, (
        "a batch with only pre-existing groups (no pre-pass) must be exactly "
        "one shared commit, not one per group"
    )
    assert results["reference_01"].actions["written"] == 2
    assert results["canopy_01"].actions["written"] == 1

    ref_ds = store.read_group("reference_01").compute()
    assert ref_ds.sizes["epoch"] == 30  # seed(10) + 2 new(10 each)
    can_ds = store.read_group("canopy_01").compute()
    assert can_ds.sizes["epoch"] == 20  # seed(10) + 1 new(10)

    assert store.metadata_row_count("reference_01") == 3
    assert store.metadata_row_count("canopy_01") == 2


def test_case_b_new_groups_pre_pass_creates_both_before_any_fork(
    store: MyIcechunkStore,
) -> None:
    """Two never-seen groups in one batch.

    The sequential pre-pass must create both groups (on its own committed
    session) before any fork runs, so `Session.merge()` never has to
    reconcile two forks that each independently create a sibling group --
    an unverified case per dev/cross_group_fork_merge_plan.md §4. Also
    verifies the pre-pass's consumed file isn't double-written or
    double-counted in the subsequent fork write (§4 reconciliation fix), and
    that this costs exactly two commits (pre-pass + batch), not one.
    """
    proc = _TestProcessor(store)
    _warm_up_source_format(proc)
    ref_files = [(Path(f"ref_{i}.rnx"), _make_ds(f"ref_{i}", slot=i)) for i in range(3)]
    can_files = [(Path(f"can_{i}.rnx"), _make_ds(f"can_{i}", slot=i)) for i in range(2)]

    assert set(store.list_groups() or []) == {"_warmup"}
    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = proc._write_receiver_batch_forked(
        [
            _group_input("reference_01", ref_files),
            _group_input("canopy_01", can_files),
        ],
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 2, (
        "a batch creating new groups must cost exactly two commits: the "
        "sequential pre-pass, then the fork/merge batch"
    )
    assert set(store.list_groups() or []) == {"_warmup", "reference_01", "canopy_01"}
    assert results["reference_01"].actions == {
        "initial": 1,
        "skipped": 0,
        "appended": 0,
        "written": 2,
    }
    assert results["canopy_01"].actions == {
        "initial": 1,
        "skipped": 0,
        "appended": 0,
        "written": 1,
    }

    ref_ds = store.read_group("reference_01").compute()
    assert ref_ds.sizes["epoch"] == 30  # 3 files x 10 epochs, none dropped/doubled
    can_ds = store.read_group("canopy_01").compute()
    assert can_ds.sizes["epoch"] == 20

    # The pre-pass-consumed file must appear exactly once in the metadata
    # table (not zero -- dropped -- and not two -- double-written).
    assert store.metadata_row_count("reference_01") == 3
    assert store.metadata_row_count("canopy_01") == 2


def test_case_b_single_file_new_group_needs_no_fork(store: MyIcechunkStore) -> None:
    """A brand-new group whose only file is fully consumed by the pre-pass
    still produces a correct result with no fork/thread involved -- the
    empty-plan-after-trim path (`plans = {... if aug}` filters it out), and
    costs exactly one commit (the pre-pass alone; the fork/merge phase never
    opens a session since `plans` is empty)."""
    proc = _TestProcessor(store)
    _warm_up_source_format(proc)
    ref_files = [(Path("ref_only.rnx"), _make_ds("ref_only", slot=0))]

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = proc._write_receiver_batch_forked(
        [_group_input("reference_01", ref_files)]
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 1
    assert results["reference_01"].actions["initial"] == 1
    assert results["reference_01"].fork is None
    assert results["reference_01"].snapshot_id is not None
    assert set(store.list_groups() or []) == {"_warmup", "reference_01"}
    ds = store.read_group("reference_01").compute()
    assert ds.sizes["epoch"] == 10
    assert store.metadata_row_count("reference_01") == 1


def test_case_c_fail_fast_no_partial_merge(
    store: MyIcechunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If one group's write raises, nothing merges or commits.

    Under one shared batch commit, "groups before the failure stay
    committed" (today's sequential-loop property) is structurally
    impossible -- so a failing group must prevent the *whole* batch commit
    from landing, not just itself (dev/cross_group_fork_merge_plan.md §6).
    """
    proc = _TestProcessor(store)

    # Seed two pre-existing groups so this batch only exercises fork writes
    # (not the pre-pass), isolating the fail-fast path under test.
    proc._write_receiver_batch_forked(
        [
            _group_input(
                "reference_01",
                [(Path("ref_seed.rnx"), _make_ds("ref_seed", slot=0))],
            ),
            _group_input(
                "canopy_01",
                [(Path("can_seed.rnx"), _make_ds("can_seed", slot=0))],
            ),
        ],
    )

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))

    real_write = RinexDataProcessor._write_group_into_fork

    def _boom(self: RinexDataProcessor, fork_session, plan):
        if plan.receiver_name == "canopy_01":
            raise RuntimeError("simulated mid-batch failure")
        return real_write(self, fork_session, plan)

    monkeypatch.setattr(RinexDataProcessor, "_write_group_into_fork", _boom)

    ref_files = [(Path("ref_2.rnx"), _make_ds("ref_2", slot=1))]
    can_files = [(Path("can_2.rnx"), _make_ds("can_2", slot=1))]

    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        proc._write_receiver_batch_forked(
            [
                _group_input("reference_01", ref_files),
                _group_input("canopy_01", can_files),
            ],
        )

    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))
    assert n_snapshots_after == n_snapshots_before, "no commit must land on failure"

    ref_ds = store.read_group("reference_01").compute()
    assert ref_ds.sizes["epoch"] == 10  # still just the seed -- ref_2 never landed
    can_ds = store.read_group("canopy_01").compute()
    assert can_ds.sizes["epoch"] == 10  # still just the seed -- can_2 never landed
