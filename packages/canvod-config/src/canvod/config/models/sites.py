"""Research site and receiver configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .base import _StrictModel


class ReceiverConfig(_StrictModel):
    """Receiver configuration."""

    type: Literal["reference", "canopy"] = Field(
        ...,
        description=(
            "Receiver role: 'canopy' = placed under the vegetation canopy; "
            "'reference' = open-sky baseline above or outside the canopy. "
            "Wizard prompt: 'Is this receiver under the canopy or in the open sky?'"
        ),
    )
    directory: str = Field(..., description="Subdirectory for receiver data")
    paired_canopies: str | list[str] | None = Field(
        None,
        description=(
            "Which canopy receiver(s) to pair with this reference. "
            "Required for reference receivers: 'all' or a list of canopy names. "
            "Must not be set for canopy receivers."
        ),
    )
    description: str | None = Field(
        None,
        description="Human-readable description",
    )
    naming: dict | None = Field(
        None,
        description="Naming configuration (validated by canvod-filemap package)",
    )
    metadata: dict[str, str | int | float | bool] | None = Field(
        None,
        description=(
            "Freeform receiver metadata written to dataset global attrs. "
            "Example keys: site_url, antenna_height, species."
        ),
    )
    reader_format: str = Field(
        "auto",
        description=(
            "GNSS data reader format: 'auto', 'rinex3', 'sbf'. "
            "When 'auto', detected from files at pipeline start."
        ),
    )
    recipe: str | None = Field(
        None,
        description=(
            "Name of a naming recipe (e.g. 'rosalia_reference'). "
            "Resolved from config/recipes/{recipe}.yaml. "
            "When set, replaces the 'naming' block for file discovery."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_scs_from(cls, data: object) -> object:
        if isinstance(data, dict) and "scs_from" in data:
            import warnings

            warnings.warn(
                "ReceiverConfig: 'scs_from' is deprecated; use 'paired_canopies' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            data = dict(data)
            data["paired_canopies"] = data.pop("scs_from")
        return data

    @model_validator(mode="after")
    def validate_paired_canopies(self) -> ReceiverConfig:
        """Validate paired_canopies is required for reference, forbidden for canopy."""
        if self.type == "reference" and self.paired_canopies is None:
            msg = "paired_canopies is required for reference receivers"
            raise ValueError(msg)
        if self.type == "canopy" and self.paired_canopies is not None:
            msg = "paired_canopies must not be set for canopy receivers"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_naming_recipe_exclusive(self) -> ReceiverConfig:
        """Reject a receiver configuring both recipe and naming.

        recipe's own description says it "replaces the naming block for
        file discovery" — but nothing enforced that until now, so both
        could be set with no indication of which one actually takes effect.
        """
        if self.recipe is not None and self.naming is not None:
            msg = (
                "recipe and naming are mutually exclusive on a receiver — "
                "recipe replaces the naming block for file discovery, so "
                "having both set is ambiguous. Remove one."
            )
            raise ValueError(msg)
        return self


class VodAnalysisConfig(_StrictModel):
    """VOD analysis pair configuration."""

    canopy_receiver: str = Field(..., description="Canopy receiver name")
    reference_receiver: str = Field(..., description="Reference receiver name")
    description: str | None = Field(None, description="Analysis description")


class SiteConfig(_StrictModel):
    """Research site configuration."""

    gnss_site_data_root: str = Field(
        ..., description="Root directory for site GNSS data"
    )
    description: str | None = Field(None, description="Site description")
    country: str | None = Field(None, description="Country code (ISO 3166-1)")
    latitude: float | None = Field(None, description="WGS84 latitude")
    longitude: float | None = Field(None, description="WGS84 longitude")
    altitude_m: float | None = Field(None, description="Altitude in meters")
    receivers: dict[str, ReceiverConfig] = Field(..., description="Site receivers")
    vod_analyses: dict[str, VodAnalysisConfig] | None = Field(
        None,
        description="VOD analysis pairs",
    )
    naming: dict | None = Field(
        None,
        description="Naming configuration (validated by canvod-filemap package)",
    )

    @model_validator(mode="after")
    def validate_paired_canopies_targets(self) -> SiteConfig:
        """Validate that paired_canopies entries reference existing canopy receivers."""
        canopy_names = self.get_canopy_receiver_names()
        for name, cfg in self.receivers.items():
            if cfg.type != "reference" or cfg.paired_canopies is None:
                continue
            if isinstance(cfg.paired_canopies, str) and cfg.paired_canopies == "all":
                continue
            targets = (
                cfg.paired_canopies
                if isinstance(cfg.paired_canopies, list)
                else [cfg.paired_canopies]
            )
            for target in targets:
                if target not in canopy_names:
                    msg = (
                        f"Receiver '{name}' paired_canopies references '{target}' "
                        f"which is not a canopy receiver. "
                        f"Available canopy receivers: {canopy_names}"
                    )
                    raise ValueError(msg)
        return self

    def get_base_path(self) -> Path:
        """Get gnss_site_data_root as a Path.

        Returns
        -------
        Path
            Site data root directory as a Path object.
        """
        return Path(self.gnss_site_data_root)

    def get_canopy_receiver_names(self) -> list[str]:
        """Get names of all canopy receivers.

        Returns
        -------
        list[str]
            Canopy receiver names.
        """
        return [name for name, cfg in self.receivers.items() if cfg.type == "canopy"]

    def resolve_paired_canopies(self, receiver_name: str) -> list[str]:
        """Resolve paired_canopies for a reference receiver to a list of canopy names.

        Parameters
        ----------
        receiver_name : str
            Name of the reference receiver.

        Returns
        -------
        list[str]
            List of canopy receiver names paired with this reference.
        """
        cfg = self.receivers[receiver_name]
        if cfg.type != "reference":
            msg = f"resolve_paired_canopies only applies to reference receivers, got '{cfg.type}'"
            raise ValueError(msg)
        if cfg.paired_canopies == "all":
            return self.get_canopy_receiver_names()
        if isinstance(cfg.paired_canopies, list):
            return cfg.paired_canopies
        # Single canopy name as string
        if cfg.paired_canopies is None:
            msg = f"Receiver '{receiver_name}' has no paired_canopies configured"
            raise ValueError(msg)
        return [cfg.paired_canopies]

    def resolve_scs_from(self, receiver_name: str) -> list[str]:
        """Deprecated: use resolve_paired_canopies instead."""
        import warnings

        warnings.warn(
            "SiteConfig.resolve_scs_from is deprecated; use resolve_paired_canopies instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.resolve_paired_canopies(receiver_name)

    @model_validator(mode="after")
    def _auto_derive_vod_analyses(self) -> SiteConfig:
        """Fill vod_analyses from paired_canopies when not explicitly set."""
        if self.vod_analyses is not None:
            return self
        pairs = self.get_reference_canopy_pairs()
        if not pairs:
            return self
        self.vod_analyses = {
            f"{canopy}_vs_{ref}": VodAnalysisConfig(
                canopy_receiver=canopy,
                reference_receiver=ref,
            )
            for ref, canopy in pairs
        }
        return self

    def get_reference_canopy_pairs(self) -> list[tuple[str, str]]:
        """Expand paired_canopies into (reference_name, canopy_name) pairs.

        Returns
        -------
        list[tuple[str, str]]
            List of (reference_name, canopy_name) pairs.
        """
        pairs = []
        for name, cfg in self.receivers.items():
            if cfg.type != "reference":
                continue
            for canopy_name in self.resolve_paired_canopies(name):
                pairs.append((name, canopy_name))
        return pairs


class SitesConfig(_StrictModel):
    """All research sites."""

    sites: dict[str, SiteConfig]

    @field_validator("sites")
    @classmethod
    def validate_at_least_one_site(
        cls,
        v: dict[str, SiteConfig],
    ) -> dict[str, SiteConfig]:
        """Warn if no sites are defined.

        Parameters
        ----------
        v : dict[str, SiteConfig]
            Sites dictionary to validate.

        Returns
        -------
        dict[str, SiteConfig]
            Validated sites dictionary.
        """
        if not v:
            import warnings

            warnings.warn(
                "No research sites defined in sites.yaml. Run: just config-init",
                UserWarning,
                stacklevel=2,
            )
        return v
