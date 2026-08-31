# canvod-grids

Hemisphere grid discretization and spatiotemporal VOD analysis.

## Key modules

| Module | Purpose |
|---|---|
| `core/` | `GridData` structure, `BaseGridBuilder` ABC, `GridType` enum |
| `grids_impl/` | 7 grid builders: `EqualAreaBuilder`, `EqualAngleBuilder`, `EquirectangularBuilder`, `HTMBuilder`, `GeodesicBuilder`, `HEALPixBuilder`, `FibonacciBuilder` |
| `analysis/` | `TemporalAnalysis`, `VODSpatialAnalyzer`, `PerCellVODAnalyzer`, diurnal/spatial patterns |
| `aggregation.py` | `CellAggregator`, `WeightCalculator`, `SolarPositionCalculator` |
| `workflows/` | `AdaptedVODWorkflow` (store integration) |

## Grid types

The primary grid for GNSS-T is **equal-area hemisphere** (2° cells viewed from
receiver position looking up). Each satellite signal path intersects one cell
based on its (theta, phi) angles.

## Filtering

- `Filter` ABC + `ZScoreFilter`, `IQRFilter`, `RangeFilter`, `PercentileFilter`, `CustomFilter`
- `PerCellFilter` variants for per-grid-cell outlier removal
- Hampel filter and sigma clipping available

## Factory

```python
from canvod.grids import create_hemigrid
grid = create_hemigrid(grid_type=GridType.EQUAL_AREA, resolution=2.0)
```

## Testing

```bash
uv run pytest packages/canvod-grids/tests/
```

`HEALPixBuilder` requires `healpy`, which is **not** installed by
`uv sync --dev` — it lives in this package's own `optional` dependency
group (no Windows wheels on PyPI, which is why it isn't a hard
dependency). Install it with `uv sync --dev --group optional` to run the
HEALPix-dependent cases in `test_grid_correctness_all_types.py`; without
it they skip cleanly (this is also what CI's Windows leg does — Linux/macOS
CI installs the `optional` group, Windows doesn't).
