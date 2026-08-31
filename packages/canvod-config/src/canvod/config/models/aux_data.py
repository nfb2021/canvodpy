"""Auxiliary data source configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import _StrictModel


class AuxDataConfig(_StrictModel):
    """Auxiliary data source configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    agency: str = Field("COD", description="Analysis center code")
    product_type: Literal["final", "rapid", "ultra-rapid"] = Field(
        "final",
        description="Product type",
    )
    ftp_timeout_s: int = Field(
        30, ge=1, description="FTP connection timeout in seconds"
    )
    fetch_clock: bool = Field(
        True,
        description=(
            "Download and interpolate CLK clock-correction files alongside "
            "SP3 ephemerides. canvod-vod's VOD formula only needs "
            "transmittance and polar angle — clock is not consumed "
            "downstream. Set to False to skip the extra downloads, "
            "parsing, and interpolation."
        ),
    )
    zarr_async_concurrency: int | None = Field(
        None,
        ge=1,
        description=(
            "Cap on zarr's own async chunk write/read burst for aux cache "
            "writes; None (default) = zarr's own default (10) applies, no "
            "cost for local/fast storage. Set on network-mounted "
            "(CIFS/NFS) shared_aux_cache_dir deployments hitting "
            "connection-abort errors — separate from "
            "IcechunkConfig.zarr_async_concurrency since this is a "
            "different store with its own write-frequency profile."
        ),
    )

    def get_ftp_servers(
        self,
        cddis_mail: str | None,
    ) -> list[tuple[str, str | None]]:
        """Get FTP servers in priority order.

        If cddis_mail is set: NASA first (with auth), ESA fallback (no auth).
        If cddis_mail is None: ESA only (no auth).

        Parameters
        ----------
        cddis_mail : str | None
            Optional CDDIS email for NASA authentication.

        Returns
        -------
        list[tuple[str, str | None]]
            Server URL and optional auth email pairs in priority order.
        """
        if cddis_mail:
            # NASA first (requires auth), ESA fallback (no auth)
            return [
                ("ftp://gdc.cddis.eosdis.nasa.gov", cddis_mail),
                ("ftp://gssc.esa.int", None),
            ]
        # ESA only (no auth required)
        return [("ftp://gssc.esa.int", None)]
