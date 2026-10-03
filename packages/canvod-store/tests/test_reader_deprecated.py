"""``IcechunkDataReader`` is deprecated (left over from development).

The warnings fire before any work is done, so neither a site nor data is
needed to check them.
"""

import re

import pytest

from canvod.store import reader
from canvod.store.reader import IcechunkDataReader

LEFT_OVER = "left over from development"
REPLACEMENT = r"canvodpy\.Site\(<site>\)\.pipeline\(\)\.process_date\(<date>\)"


class _StopInitError(Exception):
    """Raised instead of loading the configuration."""


def _stop_init():
    raise _StopInitError


def test_instantiation_is_deprecated(monkeypatch):
    monkeypatch.setattr(reader, "load_config", _stop_init)
    with (
        pytest.warns(FutureWarning, match=f"IcechunkDataReader.*{LEFT_OVER}"),
        pytest.raises(_StopInitError),
    ):
        IcechunkDataReader(matched_dirs=None)


@pytest.mark.parametrize(
    ("method", "extra"),
    [
        ("parsed_rinex_data_gen", ""),
        ("parsed_rinex_data_gen_v2", "does not run"),
    ],
)
def test_generators_are_deprecated(method, extra):
    # Calling the generator function warns; the body only runs on iteration.
    with pytest.warns(FutureWarning, match=f"{method}.*{LEFT_OVER}") as record:
        getattr(IcechunkDataReader, method)(object())
    message = str(record[0].message)
    assert extra in message
    assert re.search(REPLACEMENT, message)
