# canvod-utils

## Purpose

The `canvod-utils` package provides date/time utilities and processing
diagnostics shared across the canVODpy ecosystem. Configuration management
moved to a dedicated package — see
[canvod-config](../config/overview.md) — so `canvod-utils` has no
Pydantic/YAML dependency and no CLI code of its own.

---

## Tools

```python
from canvod.utils.tools import YYYYDOY, file_hash

YYYYDOY.from_str("2025032").date   # datetime.date(2025, 2, 1)
file_hash(path)                    # SHA-256 of a file, used by store dedup guardrails
```

| Function | Purpose |
|---|---|
| `YYYYDOY` / `YYDOY` | Year + Day-of-Year date parsing/formatting (the GNSS-standard date convention) |
| `get_gps_week_from_filename` | Extract GPS week from a standard product filename |
| `gpsweekday` | GPS week/day-of-week conversion |
| `file_hash` | SHA-256 hashing used by the store's dedup guardrails |
| `isfloat` | Safe float-parsing check |
| `get_version_from_pyproject` | Read a package version directly from `pyproject.toml` |

---

## Diagnostics

Processing diagnostics and performance tracking (`stage_timer`, `run_id`
correlation, structured logging) live in `canvodpy.logging`, not in
`canvod-utils` — see the [Diagnostics & Performance Monitoring
guide](../../guides/diagnostics.md) for the current implementation.

---

## CLI Quick Reference

canVODpy's CLI lives entirely in the `canvodpy` package (see
[canvod-config](../config/overview.md) for `config`/`doctor`, and
[canvod-store](../store/overview.md) for `store`) — collected here for a
one-stop reference:

=== "Setup"

    ```bash
    canvodpy config init                # Scaffold canvod-settings.yaml + recipe templates
    canvodpy config init --interactive  # ...or answer a few questions instead of hand-editing YAML
    canvodpy config validate            # Validate configuration
    canvodpy config show                # Display resolved configuration
    canvodpy config edit                # Open canvod-settings.yaml in $EDITOR
    canvodpy doctor                     # Environment + config diagnostics (read-only)
    ```

=== "Development"

    ```bash
    just test             # Run full test suite
    just check            # Lint + format + type-check
    just hooks            # Install pre-commit hooks
    just docs             # Serve documentation locally
    just test-coverage    # Tests with coverage report
    just clean            # Remove build artifacts
    ```

=== "Processing"

    ```bash
    just process          # Run full pipeline
    just process-date YYYYDOY     # Process single day
    just process-range START END  # Process date range
    ```

=== "Store inspection"

    ```bash
    canvodpy store list                    # Every site's gnss/vod store paths + status
    canvodpy store info <site>             # Tree of branches/groups + compression stats
    canvodpy store info <site> --group X   # Full dataset + metadata table for one group
    canvodpy store log <site>              # Commit graph
    canvodpy store log <site> --ops        # Ops audit trail
    ```
