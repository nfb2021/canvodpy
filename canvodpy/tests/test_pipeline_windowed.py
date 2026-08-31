"""Tests for _windowed_completions, the bounded-concurrency task scheduler.

dev/perf_degradation_findings_2026_07_15.md, Problem A: submitting a whole
batch's tasks upfront let the write path race a still-fully-loaded worker
pool. These tests exercise the scheduler directly (no loky/store needed).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import pytest
from canvodpy.orchestrator.pipeline import _windowed_completions


class TestWindowedCompletions:
    def test_bounds_concurrency_to_window(self):
        pool = ThreadPoolExecutor(max_workers=8)
        lock = threading.Lock()
        active = 0
        max_active = 0

        def work(task: int) -> int:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return task

        def submit(task: int):
            return pool.submit(work, task)

        tasks = list(range(10))
        results = list(_windowed_completions(submit, tasks, window=3))
        pool.shutdown()

        assert max_active <= 3
        assert sorted(task for task, _ in results) == tasks
        assert sorted(fut.result() for _, fut in results) == tasks
        assert len(results) == len(tasks)

    def test_exception_in_one_task_does_not_block_others(self):
        pool = ThreadPoolExecutor(max_workers=4)

        def work(task: int) -> int:
            if task == 3:
                raise ValueError("boom")
            return task

        def submit(task: int):
            return pool.submit(work, task)

        tasks = list(range(6))
        results = list(_windowed_completions(submit, tasks, window=2))
        pool.shutdown()

        assert sorted(task for task, _ in results) == tasks
        failing = [fut for task, fut in results if task == 3]
        assert len(failing) == 1
        with pytest.raises(ValueError, match="boom"):
            failing[0].result()
        # every other task still completed successfully
        for task, fut in results:
            if task != 3:
                assert fut.result() == task

    def test_empty_task_list_yields_nothing(self):
        pool = ThreadPoolExecutor(max_workers=2)
        results = list(
            _windowed_completions(lambda t: pool.submit(lambda: t), [], window=4)
        )
        pool.shutdown()
        assert results == []

    def test_window_larger_than_task_count(self):
        pool = ThreadPoolExecutor(max_workers=4)
        tasks = [1, 2, 3]
        results = list(
            _windowed_completions(lambda t: pool.submit(lambda: t), tasks, window=100)
        )
        pool.shutdown()
        assert sorted(task for task, _ in results) == tasks

    def test_window_one_never_submits_more_than_one_ahead(self):
        pool = ThreadPoolExecutor(max_workers=4)
        submitted: list[int] = []
        submit_lock = threading.Lock()

        def submit(task: int):
            with submit_lock:
                submitted.append(task)
            return pool.submit(lambda: task)

        tasks = list(range(5))
        results = list(_windowed_completions(submit, tasks, window=1))
        pool.shutdown()

        assert submitted == tasks  # strictly sequential submission order
        assert sorted(task for task, _ in results) == tasks

    def test_pool_broken_mid_stream_does_not_crash_the_generator(self):
        """A worker dying (loky raises BrokenProcessPool from submit() on an
        already-broken pool) used to only ever surface via a pre-submitted
        future's .result() -- everything was submitted upfront before any
        worker had a chance to die. Windowed submission means submit() can
        now itself hit an already-broken pool mid-batch; the generator must
        not let that exception escape uncaught (it would kill the whole
        multi-batch run) -- every remaining task must still be yielded, with
        a future whose .result() raises the same error the caller's
        existing per-task except BrokenProcessPool handling already expects.
        """
        pool = ThreadPoolExecutor(max_workers=4)
        submit_calls = 0
        break_after = 3  # tasks 0,1,2 submit fine; pool "breaks" on task 3

        def submit(task: int):
            nonlocal submit_calls
            submit_calls += 1
            if task >= break_after:
                raise BrokenProcessPool("worker died")
            return pool.submit(lambda: task)

        tasks = list(range(6))
        results = list(_windowed_completions(submit, tasks, window=2))
        pool.shutdown()

        # every task is still yielded exactly once, none silently dropped
        assert sorted(task for task, _ in results) == tasks

        ok_tasks = {task for task, fut in results if task < break_after}
        failed_tasks = {task for task, fut in results if task >= break_after}
        assert ok_tasks == {0, 1, 2}
        assert failed_tasks == {3, 4, 5}

        for task, fut in results:
            if task < break_after:
                assert fut.result() == task
            else:
                with pytest.raises(BrokenProcessPool):
                    fut.result()

        # submit() is called once for tasks 0-3 (3 breaks it), then never
        # again for 4/5 -- no point hammering a known-broken pool.
        assert submit_calls == break_after + 1
