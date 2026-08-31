"""Publication and funding reference models."""

from __future__ import annotations

from pydantic import Field

from .base import _StrictModel


class PublicationRef(_StrictModel):
    """A publication reference."""

    doi: str
    citation: str | None = None


class FundingRef(_StrictModel):
    """A funding reference."""

    funder: str
    funder_ror: str | None = None
    grant_number: str | None = None
    award_title: str | None = None


class ReferencesConfig(_StrictModel):
    """Publications and funding references."""

    publications: list[PublicationRef] = Field(default_factory=list)
    funding: list[FundingRef] = Field(default_factory=list)
