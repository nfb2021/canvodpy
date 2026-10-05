"""Entries of the store history (``summaries.history`` of the store metadata)."""

from __future__ import annotations

import importlib.metadata


def history_entry(now: str, event: str, preprocessing: dict[str, str]) -> str:
    """One history line: time, event, canVODpy version and preprocessing.

    Parameters
    ----------
    now : str
        ISO 8601 time of the write.
    event : str
        What was written, e.g. ``"Ingest 2025001: canopy_01(written=96)"``.
    preprocessing : dict[str, str]
        Per store group written, its preprocessing as text
        (``canvod.config.models.describe_preprocessing``).
    """
    version = importlib.metadata.version("canvodpy")
    applied = "; ".join(f"{group}: {text}" for group, text in preprocessing.items())
    return f"{now}: {event} (canvodpy {version}); preprocessing: {applied or 'none'}"
