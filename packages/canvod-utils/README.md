# canvod-utils

Shared utilities and diagnostics for canvodpy.

## Features

- **Date/time tools**: `YYYYDOY`/`YYDOY` GNSS date handling, GPS week helpers
- **Validation and hashing**: `isfloat`, `file_hash`
- **Diagnostics**: timing, memory, dataset, and Airflow task-metric tracking
- **Retry**: `tenacity`-based retry wrapper

## Installation

```bash
uv pip install -e packages/canvod-utils
```

## Quick Start

```python
from canvod.utils.tools import YYYYDOY, get_version_from_pyproject, file_hash

date = YYYYDOY.from_str("2025024")
print(date.to_datetime())

from canvod.utils.diagnostics import track_time, track_memory, task_metrics

@track_time("rinex.read")
def read_rinex(path):
    ...

with track_memory("vod.compute") as m:
    compute(ds)
print(f"Peak: {m.peak_mb:.1f} MB")
```

## Documentation

[Full documentation](https://nfb2021.github.io/canvodpy/packages/utils/overview/)

## Development

```bash
# From repo root
uv sync
uv run pytest packages/canvod-utils/tests
just check
```
