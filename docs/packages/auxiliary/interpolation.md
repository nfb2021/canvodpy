# Interpolation Methods

SP3 orbits come every 5 or 15 minutes and CLK clocks every 30 s or 5
minutes; observations come every 1 to 30 s. canvod-auxiliary interpolates
one day of orbits and clocks onto a regular grid that starts at 00:00 and
has the sampling interval of the observations
(`canvod.auxiliary.interpolation.interpolate_aux_day`). Each observation
epoch then takes the nearest grid epoch. `canvodpy run`, the ephemeris
provider of the Python API and the Airflow tasks all use these functions.

<div class="grid cards" markdown>

-   :fontawesome-solid-wave-square: &nbsp; **Cubic Hermite spline**

    ---

    Used for **SP3 orbits** (satellite X, Y, Z).

    The spline matches the positions and the satellite velocities at
    every SP3 epoch.

-   :fontawesome-solid-chart-line: &nbsp; **Piecewise linear**

    ---

    Used for **CLK clock offsets**.

    Linear between neighbouring clock epochs, never across a detected
    clock jump.

</div>

---

## Cubic Hermite spline (orbits)

Orbital motion is smooth, so a cubic polynomial between two SP3 epochs
fits it well. A Hermite spline fixes each polynomial by the positions and
velocities at both ends of the interval
([`scipy.interpolate.CubicHermiteSpline`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.CubicHermiteSpline.html)).

SP3 files read by canVODpy provide positions only. The SP3 reader
(`Sp3File`, `add_velocities=True` by default) estimates the velocities
from the positions by central differences (forward and backward
differences at the first and last epoch).

```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

config = Sp3Config(
    use_velocities=True,       # Hermite spline with Vx, Vy, Vz
    fallback_method="linear",  # used when the dataset has no velocities
)

interpolator = Sp3InterpolationStrategy(config=config)
result = interpolator.interpolate(sp3_data, target_epochs)
```

| Parameter | Default | Effect |
|-----------|---------|--------|
| `use_velocities` | `True` | Hermite spline if `Vx`, `Vy`, `Vz` are in the dataset |
| `fallback_method` | `"linear"` | `xarray` interpolation method without velocities |

!!! warning "End of the day"
    A daily SP3 file usually ends one sampling interval before midnight
    (for example 23:55 for 5-minute orbits), and the next day's file is
    not loaded. Grid epochs after the last SP3 epoch are extrapolated
    from the last spline segment. Satellites without any finite position
    are NaN.

canVODpy has not measured the interpolation error against a reference
orbit; the docs give no accuracy figure for it.

---

## Piecewise linear (clocks)

Satellite clock offsets can jump. Linear interpolation between
neighbouring CLK epochs, split at each jump, avoids fitting across one.

```python
from canvod.auxiliary.interpolation import ClockConfig, ClockInterpolationStrategy

config = ClockConfig(
    window_size=9,          # epochs averaged on each side of a candidate jump
    jump_threshold=1e-6,    # jump detection threshold (seconds)
)

interpolator = ClockInterpolationStrategy(config=config)
result = interpolator.interpolate(clk_data, target_epochs)
```

!!! warning "Jump detection"
    For each gap between consecutive CLK epochs, the interpolator compares
    the mean of up to `window_size` epochs before the gap with the mean of
    up to `window_size` epochs after it. Where the difference exceeds
    `jump_threshold`, the gap is a jump (for a run of flagged gaps, only the
    one with the largest difference). The series is split at each jump and
    interpolated linearly within each segment, never across a jump. Target
    epochs inside a jump gap, outside the data, or in a segment of a single
    epoch are NaN. `window_size=1` compares the two neighbouring epochs only.

The strategy interpolates every data variable whose name contains
`clock`, `clk`, `Clock` or `CLK`, and raises `ValueError` if there is none.

---

## Recorded in the data

`interpolate_aux_day` writes the class and settings of each strategy to
the interpolated orbits and clocks (`attrs["interpolator_config"]`, from
`Interpolator.to_attrs()`), and
`create_interpolator_from_attrs()` rebuilds the interpolator from these
attributes.

---

## Custom strategies

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

!!! example "Try it"
    [05 — Ephemeris & Coordinates](../../notebooks/_build/05_ephemeris_coordinates.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/05_ephemeris_coordinates.py)
