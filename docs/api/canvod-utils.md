# canvod.utils API Reference

Shared date/time utilities and processing diagnostics. Configuration
management lives in [canvod.config](canvod-config.md) instead.

## Tools

::: canvod.utils.tools
    options:
      members:
        - YYYYDOY
        - YYDOY
        - file_hash
        - get_gps_week_from_filename
        - gpsweekday
        - isfloat
        - get_version_from_pyproject

## Diagnostics

Processing diagnostics and performance tracking now live in
`canvodpy.logging` (see [canvodpy API Reference](canvodpy.md#configuration)
and the [Diagnostics & Performance Monitoring guide](../guides/diagnostics.md))
rather than in `canvod-utils` — `canvod.utils.diagnostics` was removed.
