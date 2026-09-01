# canvod-vod

VOD (Vegetation Optical Depth) retrieval algorithms.

## Key modules

| Module | Purpose |
|---|---|
| `calculator.py` | `VODCalculator` ABC, `TauOmegaZerothOrder` implementation |
| `_internal/` | Internal computation helpers |

## Algorithm

Zeroth-order-scattering Tau-Omega radiative transfer model (`TauOmegaZerothOrder`):
- Compares SNR through canopy vs open-sky reference (both in dB)
- `delta_snr = SNR_canopy - SNR_sky`; `transmissivity = 10 ** (delta_snr / 10)`
- `VOD = -ln(transmissivity) * cos(theta)`
- theta = polar angle of satellite signal path through canopy

## Input requirements

Each `canopy_ds`/`sky_ds` input must be an `xarray.Dataset` with an `SNR`
variable on `(epoch, sid)` dims (enforced by a pydantic `field_validator`)
and `theta`/`phi` from ephemeris augmentation.

## Testing

```bash
uv run pytest packages/canvod-vod/tests/
```

VOD is bit-identical between canvodpy and gnssvodpy (verified by canvod-audit Tier 0).
