---
title: canVODpy
description: GNSS Transmissometry analysis framework for Python
---

<div class="hero" markdown>

# canVODpy

**GNSS Transmissometry (GNSS-T) analysis framework for Python**

A modular ecosystem of eight packages for processing GNSS signal-to-noise ratio
data into vegetation optical depth (VOD) estimates.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18496234.svg)](https://doi.org/10.5281/zenodo.18496234)
[![PyPI](https://img.shields.io/pypi/v/canvodpy)](https://pypi.org/project/canvodpy/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[Get started](architecture.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/nfb2021/canvodpy){ .md-button }

</div>

---

## Pipeline

```mermaid
graph LR
    A[RINEX Files] --> B[canvod-readers]
    B --> C[canvod-auxiliary]
    C --> D[canvod-grids]
    D --> E[canvod-vod]
    E --> F[canvod-store]
    E --> G[canvod-viz]
```

## Packages

| Package | Description |
|---------|-------------|
| **canvod-readers** | RINEX v3.04 observation file parsing with validation |
| **canvod-auxiliary** | SP3 ephemeris and CLK clock correction processing |
| **canvod-grids** | Hemispheric grid implementations (HEALPix, equal-area) |
| **canvod-vod** | VOD estimation using the tau-omega model |
| **canvod-store** | Versioned storage via Icechunk |
| **canvod-viz** | 2D and 3D hemispheric visualization |
| **canvod-utils** | Configuration management and CLI |
| **canvodpy** | Umbrella package providing unified access |

## Quick Start

```bash
pip install canvodpy
```

```python
from canvod.readers import Rnxv3Obs
from canvod.grids import EqualAreaBuilder
from canvod.vod import VODCalculator
```

## Technology

| | |
|---|---|
| Python 3.13+ | uv + uv_build |
| xarray + NumPy | Icechunk / Zarr |
| ruff + ty | pytest |
| Zensical | just |

## Publications

Bader, N. F. (2026). *canVODpy: GNSS Transmissometry Analysis* (v0.2.0-beta.1).
Zenodo. [https://doi.org/10.5281/zenodo.18496234](https://doi.org/10.5281/zenodo.18496234)

## Affiliation

Climate and Environmental Remote Sensing Research Unit (CLIMERS),
Department of Geodesy and Geoinformation,
TU Wien (Vienna University of Technology).

[https://www.tuwien.at/en/mg/geo/climers](https://www.tuwien.at/en/mg/geo/climers)
