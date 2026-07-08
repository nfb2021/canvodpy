"""Shared deprecation-warning decorator for canvodpy's legacy API surfaces."""

from __future__ import annotations

import functools
import inspect
import warnings
from collections.abc import Callable
from typing import Any


def deprecated(message: str) -> Callable[[Any], Any]:
    """Emit a ``DeprecationWarning`` when the decorated object is used.

    Applied to a function, wraps the call. Applied to a class, wraps
    ``__init__`` so the warning fires on instantiation.
    """

    def decorator(obj: Any) -> Any:
        if inspect.isclass(obj):
            original_init = obj.__init__

            def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
                warnings.warn(message, DeprecationWarning, stacklevel=2)
                original_init(self, *args, **kwargs)

            obj.__init__ = functools.wraps(original_init)(new_init)
            return obj

        @functools.wraps(obj)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return obj(*args, **kwargs)

        return wrapper

    return decorator
