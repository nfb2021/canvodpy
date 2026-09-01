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
    """Publications, funding, and related-resource references."""

    software_repository: str | None = Field(
        None, description="URL of the software repository (e.g. GitHub)"
    )
    documentation: str | None = Field(None, description="URL of the documentation")
    access_url: str | None = Field(
        None,
        description="URL where the store data is actually accessible (FAIR A1)",
    )
    related_stores: list[str] = Field(
        default_factory=list, description="Identifiers/paths of related stores"
    )
    publications: list[PublicationRef] = Field(default_factory=list)
    funding: list[FundingRef] = Field(default_factory=list)
