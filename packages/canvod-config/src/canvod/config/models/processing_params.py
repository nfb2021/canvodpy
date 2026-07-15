"""Processing-run parameters (resource limits, batching, ephemeris source, etc.)."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field, model_validator

from .base import _StrictModel


class ProcessingParams(_StrictModel):
    """Processing parameters.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    resource_mode: Literal["auto", "manual"] = Field(
        "auto",
        description=(
            "'auto': Dask/OS auto-detects workers and memory (local machines). "
            "'manual': hard caps via n_max_threads, max_memory_gb, etc. (shared servers)."
        ),
    )
    n_max_threads: int | None = Field(
        None,
        ge=1,
        le=100,
        description=(
            "Max worker processes. Required when resource_mode='manual'. "
            "Ignored in 'auto'."
        ),
    )
    auto_uncapped: bool = Field(
        False,
        description=(
            "Remove the automatic CPU core cap in resource_mode='auto'. "
            "WARNING: enabling this on a shared machine can starve other users' "
            "processes. Only set True when the machine is exclusively yours."
        ),
    )
    keep_gnss_observables: list[str] = Field(
        default_factory=lambda: ["SNR"],
        description="GNSS observables to keep (SNR, Pseudorange, Phase, Doppler)",
    )
    aggregate_glonass_fdma: bool = Field(
        True,
        description=(
            "Aggregate GLONASS FDMA sub-bands into effective G1*/G2* bands. "
            "When False, each satellite keeps its precise frequency — increases "
            "SID count and changes the store SID axis. Do not change on an "
            "existing store without understanding append-compatibility implications."
        ),
    )
    store_radial_distance: bool = Field(
        False,
        description="Store radial distance (r) in the output store",
    )
    store_delta_snr: bool = Field(
        False,
        description=(
            "Store delta SNR (SNR_canopy − SNR_reference, dB) in the VOD store. "
            "Useful for diagnosing canopy attenuation without the angular correction."
        ),
    )
    store_radial_diff: bool = Field(
        False,
        description=(
            "Store radial distance difference (r_canopy − r_reference, m) in the "
            "VOD store. Requires store_radial_distance=true at ingest time so that "
            "r is available in both receiver datasets."
        ),
    )
    receiver_position_mode: Literal["shared", "per_receiver"] = Field(
        "shared",
        description=(
            "'shared': all receivers use the canopy receiver position for "
            "spherical coordinate computation (default, enables 1:1 SNR "
            "comparison). 'per_receiver': each receiver uses its own RINEX "
            "header position (physically correct geometry but breaks direct "
            "SNR comparability between receivers)."
        ),
    )
    file_pairing: Literal["complete", "paired"] = Field(
        "complete",
        description=(
            "'complete': discover files per-receiver independently (all data ingested). "
            "'paired': only process dates where both receivers in an analysis pair have data."
        ),
    )
    days_per_batch: int = Field(
        1,
        ge=1,
        le=30,
        description="Number of DOYs pooled per loky wave (1 = one day at a time)",
    )
    max_memory_gb: float | None = Field(
        None,
        gt=0,
        description="Soft RAM limit for processing (None = no limit)",
    )
    cpu_affinity: list[int] | None = Field(
        None,
        description="Pin workers to specific CPU core IDs (None = no restriction)",
    )
    nice_priority: int = Field(
        -5,
        ge=-20,
        le=19,
        description=(
            "Process nice value (-20=highest priority, 0=normal, 19=lowest). "
            "Negative values raise worker priority above normal but require "
            "root/CAP_SYS_NICE on Linux -- silently has no effect otherwise "
            "(canvod.utils.tools.worker._worker_init swallows PermissionError)."
        ),
    )
    # TODO: investigate whether threads_per_worker is still needed after the loky /
    # ProcessPoolExecutor parallelisation refactor replaced Dask. If neither loky nor
    # the custom process-pool uses it, remove this field and its callsites in api.py.
    threads_per_worker: int | None = Field(
        None,
        ge=1,
        le=8,
        description=(
            "Threads per worker process. None lets the scheduler decide. "
            "Values >1 help with numpy/xarray ops and I/O (GIL-releasing) but not "
            "pure-Python RINEX text parsing."
        ),
    )
    ephemeris_source: Literal["final", "broadcast"] = Field(
        "final",
        description=(
            "'final': compute satellite coordinates from agency final products "
            "(SP3/CLK). 'broadcast': use broadcast ephemerides from SBF "
            "SatVisibility blocks (SBF reader_format only, skips SP3/CLK "
            "download). Broadcast is faster but less accurate (~1-2 m orbit)."
        ),
    )
    store_sbf_raw_observables: bool = Field(
        True,
        description=(
            "When reading SBF files, include the pre-correction 'raw' observable "
            "variables in obs_ds: SNR_raw (before CN0HighRes), "
            "Pseudorange_unsmoothed (before Hatch filter), "
            "Pseudorange_raw (before Hatch + multipath filters), and "
            "Phase_raw (before carrier multipath correction). "
            "Set to False to reduce dataset size when raw quantities are not needed."
        ),
    )

    @model_validator(mode="after")
    def validate_resource_mode(self) -> ProcessingParams:
        """Validate resource_mode constraints.

        In 'manual' mode, ``n_max_threads`` must be set.
        In 'auto' mode, ``n_max_threads`` is ignored with a warning if set.
        """
        if self.resource_mode == "manual" and self.n_max_threads is None:
            msg = (
                "n_max_threads is required when resource_mode='manual'. "
                "Set n_max_threads to the number of worker processes you want."
            )
            raise ValueError(msg)
        if self.resource_mode == "auto" and self.n_max_threads is not None:
            import warnings

            warnings.warn(
                f"resource_mode='auto' ignores n_max_threads={self.n_max_threads}. "
                "Set resource_mode='manual' to enforce hard caps, "
                "or remove n_max_threads for auto mode.",
                UserWarning,
                stacklevel=2,
            )
        return self

    def resolve_resources(self) -> dict:
        """Resolve effective resource settings based on resource_mode.

        Returns
        -------
        dict
            Resolved resource values with keys: ``n_workers``,
            ``max_memory_gb``, ``cpu_affinity``, ``nice_priority``.
            In auto mode with ``auto_uncapped=False``, ``n_workers`` is
            ``max(1, cpu_count - 2)`` to leave headroom for the OS.
            With ``auto_uncapped=True``, ``n_workers`` is ``None`` (no cap).
        """
        if self.resource_mode == "auto":
            if self.auto_uncapped:
                n_workers = None
            else:
                n_workers = max(1, (os.cpu_count() or 2) - 2)
            return {
                "n_workers": n_workers,
                "max_memory_gb": None,
                "cpu_affinity": None,
                "nice_priority": -5,
                "threads_per_worker": self.threads_per_worker,
            }
        # manual mode
        return {
            "n_workers": self.n_max_threads,
            "max_memory_gb": self.max_memory_gb,
            "cpu_affinity": self.cpu_affinity,
            "nice_priority": self.nice_priority,
            "threads_per_worker": self.threads_per_worker,
        }
