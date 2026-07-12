"""Signal ID (SID) filtering configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationInfo, field_validator

from .base import _StrictModel


class SidsConfig(_StrictModel):
    """Signal ID configuration."""

    mode: Literal["all", "preset", "custom"] = Field(
        "all",
        description="SID selection mode",
    )
    preset: str | None = Field(
        None,
        description="Preset name when mode=preset",
    )
    custom_sids: list[str] = Field(
        default_factory=list,
        description="Custom SID list when mode=custom",
    )

    @field_validator("preset")
    @classmethod
    def validate_preset_when_mode_preset(
        cls,
        v: str | None,
        info: ValidationInfo,
    ) -> str | None:
        """Ensure preset is set when mode is preset.

        Parameters
        ----------
        v : str | None
            Preset name.
        info : ValidationInfo
            Pydantic validation info.

        Returns
        -------
        str | None
            Preset value if valid.
        """
        mode = info.data.get("mode")
        if mode == "preset" and not v:
            msg = "preset must be specified when mode is 'preset'"
            raise ValueError(msg)
        return v

    def get_sids(self) -> list[str] | None:
        """Get the effective SID list.

        Returns
        -------
        list[str] | None
            None if mode is "all" (keep all SIDs), otherwise a SID list.
        """
        if self.mode == "all":
            return None
        if self.mode == "preset":
            return self._get_preset_sids()
        # CUSTOM
        return self.custom_sids

    def _get_preset_sids(self) -> list[str]:
        if self.preset is None:
            msg = "preset must be set when mode is 'preset'"
            raise ValueError(msg)
        # presets/ lives at canvod/config/presets/, one level up from this
        # models/ subpackage.
        presets_dir = Path(__file__).parent.parent / "presets"
        preset_file = presets_dir / f"{self.preset}.yaml"
        if not preset_file.exists():
            known = sorted(p.stem for p in presets_dir.glob("*.yaml"))
            msg = f"Unknown SID preset '{self.preset}'. Available: {known}"
            raise ValueError(msg)
        with preset_file.open() as f:
            data = yaml.safe_load(f)
        return data.get("sids", [])
