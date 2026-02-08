# canvod-vod

## Purpose

The `canvod-vod` package implements vegetation optical depth (VOD) estimation from GNSS signal-to-noise ratio (SNR) data. It provides the core scientific algorithms for the canVODpy analysis pipeline.

## Theoretical Background

The package implements the zeroth-order tau-omega radiative transfer model for GNSS-transmissometry, following Humphrey and Frankenberg (2022). In this model, the attenuation of GNSS signals passing through a vegetation canopy is related to the optical depth (tau) of the canopy layer.

The zeroth-order model assumes:
- Single-scattering approximation (no multiple scattering between canopy elements)
- Plane-parallel canopy layer
- Signal attenuation proportional to the path length through the canopy

## Usage

```python
from canvod.vod import VODCalculator

calculator = VODCalculator(canopy_ds, reference_ds)
vod_result = calculator.compute()
```

The calculator requires:
- **Canopy dataset**: RINEX observations from a receiver beneath vegetation
- **Reference dataset**: RINEX observations from a nearby open-sky receiver
- Both datasets must be augmented with spherical coordinates (from canvod-auxiliary) and assigned to grid cells (from canvod-grids)

## References

Humphrey, V. and Frankenberg, C. (2022). GNSS-transmissometry: A new approach for vegetation optical depth estimation. *Remote Sensing of Environment*.
