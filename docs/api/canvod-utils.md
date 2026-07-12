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

::: canvod.utils.diagnostics
    options:
      members:
        - TaskMetrics
        - task_metrics
        - track_time
        - track_memory
        - BatchTracker
        - DatasetReport
        - retry
