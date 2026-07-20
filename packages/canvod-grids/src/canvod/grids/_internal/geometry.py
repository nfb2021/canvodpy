"""Shared geometric helpers for grid builders."""

import numpy as np


def phi_bbox(phi_values: np.ndarray) -> tuple[float, float]:
    """Angular bounding box of a cluster of phi values in [0, 2*pi).

    Naive ``(min(phi), max(phi))`` reports a near-full-circle span for a
    cell whose vertices straddle the 0/2*pi seam (e.g. vertices at 0.01 and
    6.27 rad give ``[0.01, 6.27]`` instead of the true ~0.02 rad width).
    Assumes ``phi_values`` are a single angularly-localized cluster (true
    for one cell's own vertices) -- computes the bbox both as-is and in a
    frame shifted by pi, and keeps whichever framing gives the narrower
    span.

    Parameters
    ----------
    phi_values : np.ndarray
        Azimuthal angles of a cell's vertices, radians (any range; wrapped
        into [0, 2*pi) internally).

    Returns
    -------
    phi_min, phi_max : float
        ``phi_min`` is in [0, 2*pi). ``phi_max`` may exceed 2*pi when the
        cell wraps the seam -- callers should use ``phi_max - phi_min``
        directly for angular width rather than assuming both bounds lie in
        [0, 2*pi); polar axes wrap angles > 2*pi visually.

    """
    phi_values = np.asarray(phi_values, dtype=np.float64) % (2 * np.pi)
    lo, hi = float(phi_values.min()), float(phi_values.max())
    span = hi - lo

    shifted = (phi_values + np.pi) % (2 * np.pi)
    lo_s, hi_s = float(shifted.min()), float(shifted.max())
    span_s = hi_s - lo_s

    if span_s < span:
        lo, hi = lo_s - np.pi, hi_s - np.pi
        if lo < 0:
            lo += 2 * np.pi
            hi += 2 * np.pi

    return lo, hi
