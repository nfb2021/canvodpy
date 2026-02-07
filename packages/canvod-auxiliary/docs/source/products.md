# Product Registry

37 validated GNSS products from 17 agencies.

## Overview

The product registry provides declarative configuration for SP3 and CLK file locations across multiple agencies.

## Available Products

**Primary Sources:**
- **CODE** (Center for Orbit Determination in Europe): Final, Rapid
- **GFZ** (GeoForschungsZentrum Potsdam): Final, Rapid
- **ESA** (European Space Agency): Final, Rapid, Ultra-rapid
- **JPL** (Jet Propulsion Laboratory): Final
- **IGS** (International GNSS Service): Final, Rapid, Ultra-rapid

**Total:** 37 products from 17 agencies

## Usage

```python
from canvod.auxiliary import PRODUCT_REGISTRY, ProductSpec, Sp3File

# List all products
products = list_available_products()  # Returns dict of all products

# List agencies
from canvod.auxiliary import list_agencies
agencies = list_agencies()  # ['CODE', 'GFZ', 'ESA', ...]

# Get specific product
spec = get_product_spec("CODE", "final")
print(spec.sp3_url_template)
print(spec.latency_hours)  # 336 hours (14 days)

# Use with file handlers
sp3 = Sp3File.from_url(date(2024, 1, 1), "CODE", "final")
```

## Product Types

### Final Products
- **Latency:** 14-21 days
- **Accuracy:** Highest (cm-level)
- **Use case:** Scientific research, reprocessing

### Rapid Products
- **Latency:** 17-24 hours
- **Accuracy:** Near-final (cm-level)
- **Use case:** Near-real-time processing

### Ultra-rapid Products
- **Latency:** 3-9 hours
- **Accuracy:** Good (few cm)
- **Use case:** Real-time applications

## Configuration

Products are defined in `products/registry.toml`:

```toml
[CODE.final]
sp3_url_template = "ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.EPH.Z"
clk_url_template = "ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.CLK.Z"
latency_hours = 336
ftp_server = "ftp.aiub.unibe.ch"
requires_auth = false
```

## Agency Details

See `products/` module for complete specifications.

## See Also

- API Reference for `ProductSpec` details
- Overview for product comparison table
