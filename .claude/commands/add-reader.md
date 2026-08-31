Guide adding a new GNSS data format reader to canvod-readers. Follow this template:

## Steps

1. **Create reader module** in `packages/canvod-readers/src/canvod/readers/{format}/`

2. **Inherit from `GNSSDataReader`** (in `base.py`):
   ```python
   from canvod.readers.base import GNSSDataReader

   class MyFormatReader(GNSSDataReader):
       @property
       def source_format(self) -> str:
           return "my_format"

       def to_ds(self) -> xr.Dataset:
           # Must return dataset with (epoch, sid) dims
           ...

       def to_ds_and_auxiliary(self) -> tuple[xr.Dataset, dict[str, xr.Dataset]]:
           # Optional: return main dataset + auxiliary datasets
           ...
   ```

3. **Data contract — the dataset MUST have:**
   - Dims: `(epoch, sid)`
   - Coords: `epoch` (datetime64), `sid` (str in `"{const}{prn}|{band}|{attr}"` format)
   - SID-level coords: `constellation`, `prn`, `band`, `attr`, `frequency_hz`
   - Attrs: `"File Hash"` (required)
   - Variables: `obs`, `snr`

4. **Register in factory** (`canvodpy/src/canvodpy/factories.py`):
   ```python
   ReaderFactory.register("my_format", MyFormatReader)
   ```

5. **Add glob patterns** to `BUILTIN_PATTERNS` in `canvod.filemap.patterns`

6. **Add format label** to `_FORMAT_LABELS` in `canvod-store/viewer.py`

7. **Write tests** in `packages/canvod-readers/tests/` — use canonical filenames, mark integration tests with `@pytest.mark.integration`

8. **Update store viewer** — `_get_display_type()` in viewer.py reads `source_format` root attr

## Existing readers for reference

- `rinex/rnxv3_obs.py` — RINEX v3.04 (text-based, header + obs blocks)
- `sbf/sbf_reader.py` — Septentrio SBF (binary, block-based with CRC)
