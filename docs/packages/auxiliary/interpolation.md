# Interpolation Methods

SP3 and CLK products sample at 15-minute or 5-minute intervals. RINEX observations arrive at 1–30 s. Interpolation bridges the gap — producing per-epoch satellite positions and clock corrections at the exact observation timestamps.

<div class="grid cards" markdown>

-   :fontawesome-solid-wave-square: &nbsp; **Hermite Cubic Splines**

    ---

    Used for **SP3 ephemerides** (satellite XYZ positions).

    SP3 files include both positions *and* velocities, enabling Hermite
    interpolation — C¹ continuous, sub-millimetre accuracy for IGS final products.

-   :fontawesome-solid-chart-line: &nbsp; **Piecewise Linear**

    ---

    Used for **CLK clock corrections**.

    Clock files provide no derivative information and exhibit discontinuities
    at manoeuvre events. Linear segments between knot points give
    sub-nanosecond accuracy without over-fitting.

</div>

---

## Hermite Cubic Splines (Ephemerides)

Physical motivation: orbital motion is smooth — well-suited to polynomial interpolation. Positions and velocities from SP3 files determine the Hermite polynomial coefficients uniquely over each 15-minute interval.

```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

config = Sp3Config(
    use_velocities=True,          # use velocity columns from SP3 (recommended)
    fallback_method="linear",     # fall back if velocity missing
    extrapolation_method="nearest",
)

interpolator = Sp3InterpolationStrategy(config=config)
result = interpolator.interpolate(sp3_data, target_epochs)
```

| Parameter | Default | Effect |
|-----------|---------|--------|
| `use_velocities` | `True` | Enables Hermite mode (higher accuracy) |
| `fallback_method` | `"linear"` | Used when velocity columns absent |
| `extrapolation_method` | `"nearest"` | Behaviour outside the SP3 time span |

!!! success "Accuracy"
    Hermite splines achieve **< 1 mm** position error at 30 s cadence
    for IGS final products. Rapid products are typically < 5 mm.

---

## Piecewise Linear Interpolation (Clock Corrections)

Clock corrections are **not** smooth — receiver and satellite clock models are periodically updated, causing step discontinuities. Linear interpolation between adjacent CLK knots avoids fitting across those jumps.

```python
from canvod.auxiliary.interpolation import ClockConfig, ClockInterpolationStrategy

config = ClockConfig(
    window_size=9,          # samples averaged on each side of a candidate jump
    jump_threshold=1e-6,    # discontinuity detection threshold (seconds)
)

interpolator = ClockInterpolationStrategy(config=config)
result = interpolator.interpolate(clk_data, target_epochs)
```

!!! warning "Jump detection"
    For each gap between consecutive CLK knots, the interpolator compares
    the mean of up to `window_size` knots before the gap with the mean of
    up to `window_size` knots after it. Where the difference exceeds
    `jump_threshold`, the gap is a jump (for a run of flagged gaps, only the
    one with the largest difference). The series is split at each jump and
    interpolated linearly within each segment, never across a jump. Target
    epochs inside a jump gap, outside the data, or in a segment of a single
    knot are NaN. `window_size=1` compares the two neighbouring knots only.

---

## Custom Strategies

Subclass `Interpolator` to write your own interpolation:

```python
import numpy as np
import xarray as xr
from canvod.auxiliary.interpolation import Interpolator

class CustomStrategy(Interpolator):
    """Example: Lagrange polynomial interpolation."""

    def interpolate(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        # Your implementation here
        return interpolated_ds
```

`canvodpy run` always uses `Sp3InterpolationStrategy` and
`ClockInterpolationStrategy`; a custom strategy is for your own scripts.

---

## Accuracy Summary

| Data | Method | Expected accuracy | Notes |
|------|--------|------------------|-------|
| SP3 final (IGS) | Hermite | < 1 mm | Requires velocity columns |
| SP3 rapid (IGS) | Hermite | < 5 mm | Typically available within 17 h |
| SP3 ultra-rapid | Hermite | few cm | Predicted half |
| CLK final | Linear | < 0.1 ns | Sub-centimetre equivalent |
| CLK rapid | Linear | ~0.5 ns | Typically available within 17 h |

---

!!! example "Try it"
    [05 — Ephemeris & Coordinates](../../notebooks/_build/05_ephemeris_coordinates.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/05_ephemeris_coordinates.py)
