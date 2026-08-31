# canvod-readers

GNSS data format readers producing `xarray.Dataset` with `(epoch, sid)` dims.

## Key modules

| Module | Purpose |
|---|---|
| `base.py` | `GNSSDataReader` ABC — all readers inherit this |
| `builder.py` | Dataset builder (assembles coords, obs, attrs) |
| `rinex/` | RINEX v2/v3.04 observation reader (`Rnxv3Obs`) |
| `sbf/` | Septentrio SBF binary reader (`SbfReader`) |
| `matching/` | `DataDirMatcher`, `PairDataDirMatcher` (deprecated — use `canvod-filemap`) |
| `gnss_specs/` | Constellation definitions, `SatelliteCatalog`, signal tables |

## Data contract

Every reader must produce a dataset with:
- **Dims:** `(epoch, sid)` where sid = `"{constellation}{prn}|{band}|{attr}"` (e.g. `"G01|L1|C"`)
- **Coords:** `epoch` (datetime64), `sid` (str), plus sid-level coords (`constellation`, `prn`, `band`, `attr`, `frequency_hz`)
- **Attrs:** `"File Hash"` (required), header metadata, `source_format` property
- **Variables:** `obs` (observations), `snr` (signal-to-noise ratio in dB-Hz)

## Constellation system

- `ConstellationBase` ABC + 7 subclasses: `GPS`, `GALILEO`, `GLONASS`, `BEIDOU`, `SBAS`, `IRNSS`, `QZSS`
- Each defines `SYSTEM_PREFIX`, frequency tables, valid PRN ranges
- `SatelliteCatalog` (from IGS SINEX) provides SVN↔PRN mapping, TX power, mass, orbital plane
- Catalog loads from: search dirs → `~/.cache/canvod/` → IGS download → bundled fallback

## SID vs PRN

SID (Signal ID) = `"{const}{prn}|{band}|{attribute}"` — uniquely identifies one observable.
PRN (Pseudo-Random Noise) = satellite identifier within a constellation.
One PRN produces multiple SIDs (one per frequency band × attribute type).

## Testing

```bash
uv run pytest packages/canvod-readers/tests/
```

- Test data uses canonical filenames (e.g. `ROSA01TUW_R_20250010000_15M_05S_AA.rnx`)
- `test_data/` is a git submodule
- `@pytest.mark.integration` for tests requiring real GNSS files
