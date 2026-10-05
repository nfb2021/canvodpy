# canvod-ops

Optional preprocessing of observation datasets before they are stored:
temporal aggregation and grid assignment, configured in
`processing.preprocessing`.

## Where things live

| Path (under `src/canvod/ops/`) | What |
|---|---|
| `base.py` | `Op` ABC |
| `temporal.py` | `TemporalAggregate`: bins from 00:00, NaN/-1 skipped, integers rounded, `phi` averaged as an angle; output has the input's signature plus the `Temporal Aggregation` attribute; numpy blocks, no polars |
| `grid.py` | `GridAssignment`: calls canvod-grids' `add_cell_ids_to_ds_fast` |
| `pipeline.py`, `registry.py` | `Pipeline`; `build_default_pipeline` builds it from the settings (empty if unset) |
| `files.py` | `preprocess_files`: the one step every run calls per receiver-day; joins the files in preallocated arrays (no `xr.concat`) |

Background: `docs/packages/ops/overview.md`.

## Invariants

- **Never on by default.** Preprocessing runs only when the user set it,
  and then in every entry point (CLI, `Site.pipeline()`, Airflow) through
  `preprocess_files`. Don't present it as a recommended practice.
- Bins that span two files are merged before writing.
- A store group never mixes preprocessed and raw data; the store refuses
  it.

## Tests

```bash
just test-package canvod-ops
```
