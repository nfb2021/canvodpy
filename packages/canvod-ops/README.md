# canvod-ops

Composable preprocessing operations pipeline for GNSS-Transmissometry.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

`canvod-ops` provides a modular `Op`-based pipeline for applying preprocessing
steps to GNSS datasets. Operations are composable and chainable via `Pipeline`.

## Key components

| Component | Purpose |
|---|---|
| `Op` | Abstract base class for all operations |
| `GridAssignment` | Assigns satellite observations to equal-area grid cells |
| `Pipeline` | Chains operations and returns `PipelineResult` |

## Installation

```bash
uv pip install canvod-ops
```

`canvodpy run`, the Python API and Airflow do not apply these operations;
apply them yourself to datasets read from a store.

## Configuration (deprecated)

The `processing.preprocessing` settings section, which
`build_default_pipeline()` reads when called without a config, is left over
from development and will be removed with the next major version. Build the
pipeline explicitly instead (see Quick Start).

## Quick Start

```python
from canvod.ops import GridAssignment, Pipeline, TemporalAggregate

pipeline = Pipeline(
    [
        TemporalAggregate(freq="1min", method="mean"),
        GridAssignment(grid_type="equal_area", angular_resolution=2.0),
    ]
)
ds_out, result = pipeline(ds)
```

## Documentation

[Full documentation](https://nfb2021.github.io/canvodpy/packages/ops/overview/)

## License

Apache License 2.0
