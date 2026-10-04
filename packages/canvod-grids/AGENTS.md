# canvod-grids

Hemisphere grids (cells of the sky seen from the receiver), assignment of
observations to cells, and analysis on gridded VOD.

## Where things live

| Path (under `src/canvod/grids/`) | What |
|---|---|
| `__init__.py` | `create_hemigrid`: build a grid by type and resolution |
| `core/` | `GridData`, `BaseGridBuilder` ABC, grid types |
| `grids_impl/` | One builder per grid type (equal-area is the default for GNSS-T) |
| `operations.py` | `add_cell_ids_to_ds_fast`: the one cell assignment |
| `aggregation.py`, `analysis/` | Per-cell aggregation and VOD analysis |

Background: `docs/packages/grids/overview.md`.

## Invariants

- **One cell assignment**: `add_cell_ids_to_ds_fast` (nearest cell center,
  KD-tree, float64). `GridAssignment` in canvod-ops calls it. Its other
  variants are deprecated; don't add a new one.
- Outlier filtering (Hampel and similar) was removed on purpose; it does
  not belong in canvodpy.

## Tests

```bash
just test-package canvod-grids
```

The HEALPix grid needs `healpy`, which is in this package's `optional`
dependency group (no Windows wheels); without it those cases skip.
