"""Tests for _interleave_by_receiver and _build_ordered_tasks.

dev/todo_later.md §42: on a multi-day batch, the flat task list handed to
_windowed_completions was built receiver-major/file-minor within a date
(one receiver's whole daily file count before the next receiver's), and
dates were inserted in Phase 1 *completion* order (as_completed()) rather
than chronological order. Both defeated the point of windowed pooling --
groups completed in near-strict submission order instead of interleaved,
and the dashboard/progress display showed dates out of sequence. These
tests exercise the two reordering functions directly (no loky/store
needed), plus their composition with _windowed_completions to model what
on_group_written/reporter.advance() would actually observe.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from canvodpy.orchestrator.pipeline import (
    _build_ordered_tasks,
    _interleave_by_receiver,
    _windowed_completions,
)


def _task(receiver: str, n: int) -> tuple:
    """Build a minimal task-descriptor tuple with receiver at index 4."""
    return (n, None, None, None, receiver, None, None, None, None, None, None)


class TestInterleaveByReceiver:
    def test_equal_size_groups_round_robin(self):
        tasks = [_task("A", i) for i in range(3)] + [_task("B", i) for i in range(3)]
        result = _interleave_by_receiver(tasks)
        receivers = [t[4] for t in result]
        assert receivers == ["A", "B", "A", "B", "A", "B"]
        assert len(result) == len(tasks)

    def test_uneven_groups_preserve_all_tasks_no_gaps(self):
        tasks = [_task("A", i) for i in range(5)] + [_task("B", i) for i in range(2)]
        result = _interleave_by_receiver(tasks)
        assert len(result) == len(tasks)
        assert sorted((t[4], t[0]) for t in result) == sorted(
            (t[4], t[0]) for t in tasks
        )
        # first two rounds interleave, then A's tail flows through alone
        receivers = [t[4] for t in result]
        assert receivers[:4] == ["A", "B", "A", "B"]
        assert receivers[4:] == ["A", "A", "A"]

    def test_single_item_groups_no_crash(self):
        # §45: the recommended 1-file/day case -- each receiver contributes
        # exactly one task for the date.
        tasks = [_task("A", 0), _task("B", 0), _task("C", 0)]
        result = _interleave_by_receiver(tasks)
        assert len(result) == 3
        assert {t[4] for t in result} == {"A", "B", "C"}

    def test_empty_input(self):
        assert _interleave_by_receiver([]) == []

    def test_single_receiver_is_a_no_op_reorder(self):
        tasks = [_task("A", i) for i in range(4)]
        result = _interleave_by_receiver(tasks)
        assert [t[0] for t in result] == [0, 1, 2, 3]


class TestBuildOrderedTasks:
    def test_follows_ordered_date_keys_not_dict_insertion_order(self):
        # simulate Phase 1 completing d2 before d1 (as_completed() race) --
        # task_descriptors_by_date is populated d2-then-d1, but the batch's
        # chronological order is d1, d2, d3.
        task_descriptors_by_date = {
            "d2": [_task("A", 0)],
            "d1": [_task("A", 0)],
            "d3": [_task("A", 0)],
        }
        result = _build_ordered_tasks(["d1", "d2", "d3"], task_descriptors_by_date)
        assert [date_key for date_key, _ in result] == ["d1", "d2", "d3"]

    def test_receivers_interleave_within_each_date(self):
        task_descriptors_by_date = {
            "d1": [_task("A", i) for i in range(3)] + [_task("B", i) for i in range(3)],
        }
        result = _build_ordered_tasks(["d1"], task_descriptors_by_date)
        receivers = [task_args[4] for _date_key, task_args in result]
        assert receivers == ["A", "B", "A", "B", "A", "B"]

    def test_date_missing_from_task_descriptors_is_skipped(self):
        # models a date whose Phase 1 prep failed/was skipped
        task_descriptors_by_date = {"d1": [_task("A", 0)]}
        result = _build_ordered_tasks(["d1", "d2"], task_descriptors_by_date)
        assert [date_key for date_key, _ in result] == ["d1"]

    def test_empty_batch(self):
        assert _build_ordered_tasks([], {}) == []


class TestCompositionWithWindowedCompletions:
    def test_ordered_tasks_stay_interleaved_once_fed_through_windowing(self):
        """_build_ordered_tasks/_interleave_by_receiver already produce an
        A,B,A,B,... interleaved sequence before windowing ever runs -- this
        is a regression lock on *that* (revert either function back to
        contiguous per-group blocks and this fails), not a test of
        _windowed_completions's own concurrency bounding (see
        test_pipeline_windowed.py for that -- even window=1, fully
        sequential, would pass this specific assertion). Models what
        on_group_written/reporter.advance() would observe end-to-end:
        two dates, two receivers each with more tasks than the window.
        """
        task_descriptors_by_date = {
            "d1": [_task("A", i) for i in range(6)] + [_task("B", i) for i in range(6)],
            "d2": [_task("A", i) for i in range(6)] + [_task("B", i) for i in range(6)],
        }
        all_tasks = _build_ordered_tasks(["d1", "d2"], task_descriptors_by_date)

        pool = ThreadPoolExecutor(max_workers=4)

        def submit(task):
            date_key, task_args = task
            return pool.submit(lambda: (date_key, task_args[4]))

        completion_order = [
            fut.result()
            for _task, fut in _windowed_completions(submit, all_tasks, window=4)
        ]
        pool.shutdown()

        assert len(completion_order) == len(all_tasks)

        # group_key = (date, receiver); record the index of each group's
        # first and last completion -- if groups drained one at a time
        # (the pre-fix bug), a group's span would be a contiguous block
        # with no other group's tasks interleaved inside it.
        first_seen: dict[tuple[str, str], int] = {}
        last_seen: dict[tuple[str, str], int] = {}
        for i, group_key in enumerate(completion_order):
            first_seen.setdefault(group_key, i)
            last_seen[group_key] = i

        other_group_inside_span = False
        for group_key, start in first_seen.items():
            end = last_seen[group_key]
            for i in range(start, end + 1):
                if completion_order[i] != group_key:
                    other_group_inside_span = True
                    break
        assert other_group_inside_span, (
            "expected at least one group's completion span to contain "
            "another group's task, i.e. real interleaving -- got strictly "
            f"contiguous blocks: {completion_order}"
        )
