"""Metadata definitions for RINEX datasets.

Defines CF-compliant metadata for xarray.Dataset coordinates, data variables,
and global attributes. Used by all readers to ensure consistent NetCDF output
compatible with downstream VOD calculations and storage operations.

Module Contents
---------------
OBSERVABLES_METADATA : dict
    Metadata for GNSS observables (Pseudorange, Phase, Doppler, etc.)
CN0_METADATA : dict
    Metadata for Carrier-to-Noise density ratio (C/N0) measurements.
SNR_METADATA : dict
    Metadata for Signal-to-Noise ratio (SNR) measurements.
COORDS_METADATA : dict
    Metadata for dataset coordinates (epoch, sid, sv, etc.)
DTYPES : dict
    Data types for coordinates and variables.
DATAVARS_TO_BE_FILLED : dict
    Metadata for auxiliary variables (r, theta, phi, v, a).

Notes
-----
All metadata follows CF (Climate and Forecast) conventions for NetCDF files
to ensure interoperability with standard tools and libraries.

See Also
--------
canvod.readers.base.validate_dataset : Validates dataset structure

"""

from typing import Any, Final

import numpy as np

from canvod.readers.gnss_specs.constants import FREQ_UNIT

# -------------------
# Observable metadata
# -------------------
OBSERVABLES_METADATA: Final[dict[str, dict[str, Any]]] = {
    "Pseudorange": {
        "standard_name": "pseudorange",
        "long_name": "GNSS Pseudorange",
        "units": "meters",
        "valid_min": 0,
        "description": (
            "The pseudorange is the raw distance measurement between the GNSS "
            "satellite and receiver, including any timing errors due to "
            "satellite and receiver clocks."
        ),
        "comment": (
            "Pseudorange values represent the apparent distance from the "
            "satellite to the receiver and include biases from satellite and "
            "receiver clock errors."
        ),
        "_FillValue": np.nan,
    },
    "Doppler": {
        "standard_name": "doppler_shift",
        "long_name": "GNSS Doppler Shift",
        "units": "Hz",
        "valid_min": -10_000,
        "description": (
            "The Doppler shift represents the rate of change in the phase of "
            "the GNSS signal due to the relative motion between the satellite "
            "and receiver."
        ),
        "comment": (
            "Doppler shift values are used to determine the relative velocity "
            "between the GNSS satellite and the receiver. Positive values "
            "indicate the satellite is moving toward the receiver, while "
            "negative values indicate it is moving away."
        ),
        "_FillValue": np.nan,
    },
    "Phase": {
        "standard_name": "carrier_phase",
        "long_name": "GNSS Carrier Phase",
        "units": "cycles",
        "description": (
            "The carrier phase is the accumulated phase change of the GNSS "
            "signal's carrier wave from the satellite to the receiver, "
            "representing precise distance measurements."
        ),
        "comment": (
            "Carrier phase measurements are relative to an arbitrary reference "
            "cycle and may include an unknown integer ambiguity. They provide "
            "high-precision data for positioning applications when combined "
            "with pseudorange measurements."
        ),
        "_FillValue": np.nan,
    },
    "LLI": {
        "standard_name": "loss_of_lock_indicator",
        "long_name": "Loss of Lock Indicator",
        "units": "1",
        "valid_range": [-1, 9],
        "description": (
            "Indicator representing the loss of lock status of the signal. "
            "-1 indicates no data, while values 0-9 indicate the indicator "
            "value."
        ),
        "_FillValue": -1,
    },
    "SSI": {
        "standard_name": "signal_strength_indicator",
        "long_name": "Signal Strength Indicator",
        "units": "1",
        "valid_range": [-1, 9],
        "description": (
            "Indicator representing the signal strength of the observation. "
            "-1 indicates no data, while values 0-9 indicate the measured "
            "signal strength."
        ),
        "_FillValue": -1,
    },
}

# -------------------
# SNR vs C/N0 metadata
# -------------------
CN0_METADATA: Final[dict[str, Any]] = {
    "standard_name": "carrier_to_noise_density_ratio",
    "long_name": "Carrier-to-Noise Density Ratio (C/N0)",
    "units": "dB-Hz",
    "valid_min": 0,
    "resolution": "0.25 dB-Hz (MeasEpoch); 0.03125 dB-Hz with MeasExtra CN0HighRes",
    "description": (
        "Carrier-to-noise density ratio (C/N0) represents the carrier signal "
        "strength relative to noise power density (per 1 Hz)."
    ),
    "comment": (
        "C/N0 is a standard quality indicator of GNSS tracking performance. "
        "Sourced from MeasEpoch.MeasEpochChannelType1.CN0 (u1, scale 0.25 dB-Hz/LSB, "
        "Do-Not-Use 255). Resolution is 0.25 dB-Hz by default. "
        "GPS L1P (sig 1, RINEX 1W) and GPS L2P (sig 2, RINEX 2W) use semi-codeless "
        "tracking: formula is C/N0 = raw * 0.25 (no +10 dB-Hz offset). "
        "All other signals: C/N0 = raw * 0.25 + 10. "
        "If MeasExtra (Block 4000) is also logged, add cn0_highres_correction "
        "(from MeasExtraChannelSub.Misc bits 0-2) to extend resolution to 0.03125 dB-Hz."
    ),
    "references": (
        "Septentrio AsteRx SB3 ProBase Firmware v4.14.0 Reference Guide, "
        "MeasEpoch block (Block 4027), MeasEpochChannelType1 sub-block, "
        "field CN0, p.264; signal type table Section 4.1.10, pp.255-256; "
        "MeasExtra block (Block 4000), MeasExtraChannelSub, field Misc (CN0HighRes), p.268."
    ),
    "_FillValue": np.nan,
}

SNR_METADATA: Final[dict[str, str | float | int]] = {
    "standard_name": "signal_to_noise_ratio",
    "long_name": "Signal-to-Noise Ratio (SNR)",
    "units": "dB",
    "valid_min": 0,
    "description": (
        "Signal-to-noise ratio (SNR) represents the received signal strength "
        "relative to the noise floor across the signal bandwidth."
    ),
    "comment": "SNR is expressed in decibels (dB). Higher values indicate better signal quality.",
    "_FillValue": np.nan,
}

# -------------------
# Coordinate metadata
# -------------------
COORDS_METADATA: Final[dict[str, dict[str, str]]] = {
    "epoch": {
        "standard_name": "time",
        "long_name": "GNSS Observation epoch",
        "short_name": "epoch",
        "description": (
            "The epoch indicates the precise time at which each GNSS "
            "observation was recorded."
        ),
    },
    "sv": {
        "standard_name": "space_vehicle_identifier",
        "long_name": "GNSS Space Vehicle Identifier",
        "description": (
            "The Space Vehicle (sv) identifier denotes the specific satellite "
            "from which the GNSS observation was received."
        ),
    },
    "sid": {
        "long_name": "Signal ID",
        "description": (
            "Unique signal identifier (sv|band|code). Used to map each "
            "observation unambiguously to its properties."
        ),
    },
    "band": {
        "description": "Signal band (L1, L2, E1, etc.)",
        "long_name": "Signal band",
    },
    "system": {
        "description": "GNSS system (G=GPS, E=Galileo, R=GLONASS, C=BeiDou)",
        "long_name": "GNSS System",
    },
    "code": {
        "description": "Observation code (C, P, Y, etc.)",
        "long_name": "Observation code",
    },
    "freq_center": {
        "description": "Center frequency of the signal band",
        "long_name": "Center Frequency",
        "standard_name": "center_frequency",
        "units": f"{FREQ_UNIT:~}",
    },
    "freq_min": {
        "description": "Minimum frequency of the signal band",
        "long_name": "Minimum Frequency",
        "standard_name": "minimum_frequency",
        "units": f"{FREQ_UNIT:~}",
    },
    "freq_max": {
        "description": "Maximum frequency of the signal band",
        "long_name": "Maximum Frequency",
        "standard_name": "maximum_frequency",
        "units": f"{FREQ_UNIT:~}",
    },
}

# -------------------
# Encoding definitions
# -------------------
DTYPES: Final[dict[str, np.dtype]] = {
    "SNR": np.dtype("float32"),
    "Pseudorange": np.dtype("float64"),
    "Phase": np.dtype("float64"),
    "Doppler": np.dtype("float32"),
    "LLI": np.dtype("int8"),
    "SSI": np.dtype("int8"),
    "freq_center": np.dtype("float32"),
    "freq_min": np.dtype("float32"),
    "freq_max": np.dtype("float32"),
}

# -------------------
# Global attributes
# -------------------


def get_global_attrs() -> dict[str, str]:
    """Build global attributes from the active configuration.

    Returns
    -------
    dict[str, str]
        Global attributes dict suitable for xarray Dataset attrs.
        Falls back to ``{"Software": "canVODpy"}`` when no config is
        available (e.g. standalone ``canvod-readers`` install without a
        ``canvod-settings.yaml``).
    """
    from canvod.utils.config import load_config

    try:
        cfg = load_config()
        meta = cfg.processing.metadata
    except Exception:
        return {"Software": "canVODpy"}

    attrs: dict[str, str] = {
        "Author": meta.author,
        "Email": meta.email,
        "Institution": meta.institution,
    }
    if meta.department:
        attrs["Department"] = meta.department
    rg_parts = [p for p in [meta.research_group, meta.website] if p]
    if rg_parts:
        attrs["Research Group"] = ", ".join(rg_parts)
    attrs["Software"] = "canVODpy"
    return attrs


# -------------------
# Additional data variables
# -------------------
DATAVARS_TO_BE_FILLED: Final[dict[str, dict[str, Any]]] = {
    "r": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "radial distance",
            "standard_name": "slant_range",
            "units": "meters",
            "description": "Slant distance from receiver to satellite in ECEF spherical coordinates",
        },
    },
    "theta": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "polar angle",
            "standard_name": "polar_angle",
            "units": "degrees",
            "description": "Angle from positive Z-axis (zenith)",
        },
    },
    "phi": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "azimuthal angle",
            "standard_name": "azimuth",
            "units": "degrees",
            "description": "Rotation angle from reference meridian in XY-plane",
        },
    },
    "v": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "satellite velocity",
            "standard_name": "platform_velocity",
            "units": "meters per second",
            "description": "Instantaneous satellite velocity relative to receiver",
        },
    },
    "a": {
        "fill_value": -9999.0,
        "dtype": np.float32,
        "attrs": {
            "long_name": "satellite acceleration",
            "standard_name": "platform_acceleration",
            "units": "meters per second squared",
            "description": "Instantaneous satellite acceleration relative to receiver",
        },
    },
}
