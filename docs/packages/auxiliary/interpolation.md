# Interpolation Methods

## Overview

Interpolation increases the temporal resolution of auxiliary data from SP3/CLK sampling rates (15 min, 5 min) to RINEX observation rates (typically 30s or 15s).

## Hermite Cubic Splines (Ephemerides)

Hermite cubic splines are used for SP3 ephemeris interpolation because:

- Orbital motion is physically smooth, well-suited to polynomial interpolation
- SP3 files provide both positions and velocities, enabling Hermite (not just Lagrange) interpolation
- The resulting interpolant is C1 continuous (continuous first derivative)
- Sub-millimeter interpolation accuracy is achieved for IGS final products

Configuration:

```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

config = Sp3Config(
    use_velocities=True,
    fallback_method='linear',
    extrapolation_method='nearest'
)
interpolator = Sp3InterpolationStrategy(config=config)
result = interpolator.interpolate(sp3_data, target_epochs)
```

## Piecewise Linear Interpolation (Clock Corrections)

Clock corrections are interpolated using piecewise linear segments because:

- Satellite clock behavior exhibits discontinuities at maneuvers and clock parameter uploads
- No derivative information is available in CLK files
- Linear interpolation provides sub-nanosecond accuracy between knot points
- Jump detection prevents interpolation across discontinuities

Configuration:

```python
from canvod.auxiliary.interpolation import ClockConfig, ClockInterpolationStrategy

config = ClockConfig(
    window_size=9,
    jump_threshold=1e-6,
    extrapolation='nearest'
)
interpolator = ClockInterpolationStrategy(config=config)
result = interpolator.interpolate(clk_data, target_epochs)
```

## Custom Strategies

Custom interpolation strategies can be implemented by subclassing `InterpolationStrategy`:

```python
from canvod.auxiliary.interpolation import InterpolationStrategy

class CustomStrategy(InterpolationStrategy):
    def interpolate(self, aux_ds, target_epochs):
        # Implementation
        return interpolated_ds
```
