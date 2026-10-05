"""Tests for the shared ``deprecated`` decorator."""

import warnings

import pytest

from canvod.utils.tools import deprecated


def test_function_warns_and_returns_result():
    @deprecated("Use new_add instead.")
    def old_add(a, b):
        """Add two numbers."""
        return a + b

    with pytest.warns(FutureWarning, match="Use new_add instead."):
        assert old_add(1, 2) == 3
    assert old_add.__name__ == "old_add"
    assert old_add.__doc__ == "Add two numbers."


def test_class_warns_on_instantiation():
    @deprecated("Use NewThing instead.")
    class OldThing:
        def __init__(self, value):
            self.value = value

    with pytest.warns(FutureWarning, match="Use NewThing instead."):
        obj = OldThing(5)
    assert obj.value == 5
    assert isinstance(obj, OldThing)


def test_warning_points_at_caller():
    @deprecated("old")
    def old():
        return None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        old()
    assert caught[0].filename == __file__
