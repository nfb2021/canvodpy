# canvod-ops

Generic preprocessing operations pipeline (composable, modular).

## Key modules

| Module | Purpose |
|---|---|
| `base.py` | `Op` ABC — all operations inherit this |
| `grid.py` | `GridAssignment(Op)` — assigns satellite observations to grid cells |
| `temporal.py` | `TemporalAggregate(Op)` — time bins from 00:00, NaN skipped, `phi` as an angle |
| `pipeline.py` | `Pipeline` — chains operations, `OpResult` / `PipelineResult` |
| `registry.py` | `build_default_pipeline` — the pipeline `processing.preprocessing` sets (empty if unset) |
| `files.py` | `preprocess_files` — the one step capi, papi and Airflow call per receiver-day before the GNSS store write |

## Pattern

```python
from canvod.ops import Pipeline, GridAssignment, TemporalAggregate

pipeline = Pipeline(
    [
        TemporalAggregate(freq="1min", method="median"),
        GridAssignment(grid_type="equal_area", angular_resolution=2.0),
    ]
)
ds_out, result = pipeline(ds)
```

## Testing

```bash
uv run pytest packages/canvod-ops/tests/
```
