# Interpolation Strategies

Temporal alignment of auxiliary data with RINEX observations.

## Overview

Interpolation increases temporal resolution from SP3/CLK sampling (15 min, 5 min) to RINEX sampling (30s, 15s, or faster).

## Strategies

### Hermite Cubic Splines (Ephemerides)

**Why Hermite?**
- Uses positions AND velocities
- C¹ continuous (smooth first derivative)
- Preserves physics of orbital motion
- Sub-millimeter accuracy

**Configuration:**
```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

config = Sp3Config(
    use_velocities=True,  # Use VX, VY, VZ
    fallback_method='linear',
    extrapolation_method='nearest'
)
interpolator = Sp3InterpolationStrategy(config=config)
```

### Piecewise Linear (Clock Corrections)

**Why Linear?**
- Handles discontinuities at maneuvers
- No derivatives available
- Simple, robust
- Sub-nanosecond accuracy

**Configuration:**
```python
from canvod.auxiliary.interpolation import ClockConfig, ClockInterpolationStrategy

config = ClockConfig(
    window_size=9,
    jump_threshold=1e-6,
    extrapolation='nearest'
)
interpolator = ClockInterpolationStrategy(config=config)
```

## See Also

- API Reference for complete configuration options
- Overview for performance characteristics
