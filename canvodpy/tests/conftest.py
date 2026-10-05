"""Pytest configuration for canvodpy tests."""

import os

import pytest

_CONFIG_ENV = ("CANVOD_CONFIG_DIR", "CANVOD_CONFIG_FILE")


@pytest.fixture(autouse=True)
def _restore_config_env():
    """Undo ``CANVOD_CONFIG_*`` changes made by CLI options during a test.

    ``--config-dir`` and ``--config`` set these variables in the process
    that runs the command, which for ``CliRunner`` is the test process.
    """
    saved = {name: os.environ.get(name) for name in _CONFIG_ENV}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
