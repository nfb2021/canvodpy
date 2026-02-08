# Product Registry

## Overview

The product registry provides declarative configuration for 37 SP3 and CLK products from 17 analysis centers. Products are defined in TOML configuration rather than hardcoded URLs.

## Available Agencies

Primary sources:
- **CODE** (Center for Orbit Determination in Europe): Final, Rapid
- **GFZ** (GeoForschungsZentrum Potsdam): Final, Rapid
- **ESA** (European Space Agency): Final, Rapid, Ultra-rapid
- **JPL** (Jet Propulsion Laboratory): Final
- **IGS** (International GNSS Service): Final, Rapid, Ultra-rapid

## Product Types

| Type | Latency | Accuracy | Use Case |
|------|---------|----------|----------|
| Final | 14-21 days | Highest (cm-level) | Scientific research, reprocessing |
| Rapid | 17-24 hours | Near-final (cm-level) | Near-real-time processing |
| Ultra-rapid | 3-9 hours | Good (few cm) | Real-time applications |

## Usage

```python
from canvod.auxiliary import get_product_spec, Sp3File
from datetime import date

spec = get_product_spec("CODE", "final")
print(spec.latency_hours)  # 336 (14 days)

sp3 = Sp3File.from_url(date(2024, 1, 1), "CODE", "final")
ds = sp3.to_dataset()
```

## Configuration Format

Products are defined in `products/registry.toml`:

```toml
[CODE.final]
sp3_url_template = "ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.EPH.Z"
clk_url_template = "ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.CLK.Z"
latency_hours = 336
ftp_server = "ftp.aiub.unibe.ch"
requires_auth = false
```
