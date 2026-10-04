# canvod-auxiliary

Satellite geometry for the observations: orbits and clocks (agency SP3/CLK
products or the receiver's broadcast data), interpolation onto the
observation epochs, receiver position, and θ/φ per epoch and SID.

## Where things live

| Path (under `src/canvod/auxiliary/`) | What |
|---|---|
| `ephemeris/provider.py` | `EphemerisProvider` ABC; `AgencyEphemerisProvider` (SP3/CLK), `SbfBroadcastProvider` (SBF navigation blocks) |
| `interpolation/` | The one interpolation module: Hermite for orbits, clock interpolation, and the day grid (`interpolation/day_grid.py`) |
| `position/` | `ECEFPosition`, geodetic position, spherical coordinates (θ, φ) |
| `products/` | Product registry: which agency products exist, where to fetch them |
| `augmentation.py`, `pipeline.py` | Adding the auxiliary data to an observation dataset |
| `cache_fingerprint.py` | Fingerprint of the interpolated-product cache (`AUX_CACHE_FORMAT_VERSION`) |

Background: `docs/packages/auxiliary/overview.md`,
`docs/packages/auxiliary/interpolation.md`,
`docs/packages/auxiliary/coordinates.md`,
`docs/packages/auxiliary/products.md`,
`docs/packages/readers/ephemeris-sources.md`.

## Invariants

- **Epoch grid**: 00:00 of the day plus multiples of the observations'
  sampling interval, the same rule for `canvodpy run`, the Python API and
  Airflow. Products are interpolated once per day onto it.
- **Receiver position** comes from the data (`ECEFPosition.from_ds_metadata`),
  not from the settings.
- **Broadcast geometry** goes through `SbfBroadcastProvider` only. θ/φ the
  receiver derived from the almanac are masked; the source of each value
  is recorded.
- CLK clock bias is read in seconds. When a change alters cached
  interpolation results, raise `AUX_CACHE_FORMAT_VERSION`.
- Angles are radians in datasets; polar angle, not elevation.

## Tests

```bash
just test-package canvod-auxiliary
```

Downloading products needs network access and credentials; those tests are
marked `integration`.
