"""Shared base class for all canvodpy config models."""

from pydantic import BaseModel, ConfigDict


class _StrictModel(BaseModel):
    """Base for all config models — forbids unknown keys so YAML typos are caught."""

    model_config = ConfigDict(extra="forbid")
