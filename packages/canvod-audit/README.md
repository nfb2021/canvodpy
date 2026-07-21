# canvod-audit

Four-tier verification and regression suite for canVODpy pipelines.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

`canvod-audit` provides scientifically defensible verification that the canVODpy
pipeline produces correct results. It runs as CI and catches regressions whenever
any pipeline component changes.

## Audit tiers

| Tier | What it checks |
|---|---|
| **0** | All four API levels (L1–L4) produce identical output |
| **1a** | SBF and RINEX readers produce internally consistent datasets |
| **1b** | Broadcast and agency (SP3/CLK) ephemeris sources agree within tolerance |
| **2** | Regression: current output matches a frozen checkpoint |
| **3** | External validation vs. gnssvod (Humphrey et al.) reference implementation |

## Installation

```bash
# Development only — not intended for end users
uv pip install canvod-audit
```

## Quick Start

```bash
# Run all audit tiers
uv run pytest packages/canvod-audit/tests/

# Run a specific tier
uv run pytest packages/canvod-audit/tests/ -k "tier1"

# Freeze a regression checkpoint
python -m canvod.audit.runners.regression freeze --store /path/to/store
```

## Documentation

[Full documentation](https://nfb2021.github.io/canvodpy/packages/audit/overview/)

## License

Apache License 2.0
