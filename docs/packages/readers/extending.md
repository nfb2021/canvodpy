# Extending Readers

This guide describes how to add support for new GNSS data formats by implementing the `GNSSDataReader` abstract base class.

## Implementation Summary

Adding a new reader requires the following steps:

1. Create a class inheriting from `GNSSDataReader` and `BaseModel`.
2. Implement all abstract methods.
3. Ensure output passes `DatasetStructureValidator`.
4. Write tests.
5. Register with `ReaderFactory` (optional).

## Step-by-Step Implementation

### Step 1: Create the Reader Class

```python
from pathlib import Path
from datetime import datetime
from typing import Generator
import xarray as xr
from pydantic import BaseModel, ConfigDict

from canvod.readers.base import GNSSDataReader

class MyFormatReader(BaseModel, GNSSDataReader):
    """Reader for My Custom Format.

    Implements GNSSDataReader ABC for custom GNSS data format.
    """

    model_config = ConfigDict(
        frozen=True,  # Immutable
        arbitrary_types_allowed=True,  # Allow Path, etc.
    )

    # Required fields
    fpath: Path

    # Optional: Format-specific fields
    # my_custom_header: MyCustomHeader | None = None
```

### Step 2: Implement File Hash

```python
from canvod.readers.gnss_specs.utils import rinex_file_hash

class MyFormatReader(BaseModel, GNSSDataReader):
    # ... previous code ...

    @property
    def file_hash(self) -> str:
        """Compute file hash for deduplication.

        Returns
        -------
        str
            16-character SHA256 hash of file content.
        """
        return rinex_file_hash(self.fpath)
```

### Step 3: Implement Metadata Properties

```python
from datetime import datetime

class MyFormatReader(BaseModel, GNSSDataReader):
    # ... previous code ...

    @property
    def start_time(self) -> datetime:
        """Return start time of observations."""
        return self._parse_start_time()

    @property
    def end_time(self) -> datetime:
        """Return end time of observations."""
        return self._parse_end_time()

    @property
    def systems(self) -> list[str]:
        """Return list of GNSS systems in file."""
        return self._parse_systems()

    @property
    def num_epochs(self) -> int:
        """Return number of epochs."""
        return self._count_epochs()

    @property
    def num_satellites(self) -> int:
        """Return number of unique satellites."""
        return self._count_satellites()
```

### Step 4: Implement Epoch Iteration

```python
class MyFormatReader(BaseModel, GNSSDataReader):
    # ... previous code ...

    def iter_epochs(self) -> Generator:
        """Iterate over epochs in file.

        Yields
        ------
        EpochData
            Format-specific epoch representation containing
            timestamp and observations.
        """
        with open(self.fpath, 'r') as f:
            # Skip header if needed
            self._skip_header(f)

            # Parse data section
            for line in f:
                epoch_data = self._parse_epoch(line)
                if epoch_data:
                    yield epoch_data
```

### Step 5: Implement Dataset Conversion

This is the core method, converting the custom format to an xarray.Dataset:

```python
import numpy as np
from canvod.readers.gnss_specs.signals import SignalIDMapper
from canvod.readers.gnss_specs.metadata import (
    SNR_METADATA,
    COORDS_METADATA,
    GLOBAL_ATTRS_TEMPLATE,
)

class MyFormatReader(BaseModel, GNSSDataReader):
    # ... previous code ...

    def to_ds(
        self,
        keep_rnx_data_vars: list[str] | None = None,
        **kwargs
    ) -> xr.Dataset:
        """Convert to xarray.Dataset.

        Parameters
        ----------
        keep_rnx_data_vars : list of str, optional
            Variables to include. If None, includes all available.
        **kwargs
            Format-specific parameters.

        Returns
        -------
        xr.Dataset
            Validated dataset with standardized structure.
        """
        # 1. Collect all observations
        all_epochs = list(self.iter_epochs())

        # 2. Build Signal ID index
        mapper = SignalIDMapper()
        all_sids = set()

        for epoch in all_epochs:
            for obs in epoch.observations:
                sid = mapper.create_signal_id(obs.sv, obs.code)
                all_sids.add(sid)

        sids = sorted(all_sids)

        # 3. Create coordinate arrays
        epochs = [e.timestamp for e in all_epochs]

        # Extract metadata from Signal IDs
        sv_arr = np.array([sid.split('|')[0] for sid in sids])
        band_arr = np.array([sid.split('|')[1] for sid in sids])
        code_arr = np.array([sid.split('|')[2] for sid in sids])
        system_arr = np.array([sid[0] for sid in sids])

        # Get frequencies
        freq_center = np.array([
            mapper.get_band_frequency(sid.split('|')[1])
            for sid in sids
        ], dtype=np.float64)

        bandwidth = np.array([
            mapper.get_band_bandwidth(sid.split('|')[1])
            for sid in sids
        ], dtype=np.float64)

        freq_min = freq_center - (bandwidth / 2.0)
        freq_max = freq_center + (bandwidth / 2.0)

        # 4. Build data arrays
        data_vars = {}

        if keep_rnx_data_vars is None or "SNR" in keep_rnx_data_vars:
            snr_data = np.full(
                (len(epochs), len(sids)),
                np.nan,
                dtype=np.float32
            )

            # Fill with observations
            sid_to_idx = {sid: i for i, sid in enumerate(sids)}
            for epoch_idx, epoch in enumerate(all_epochs):
                for obs in epoch.observations:
                    sid = mapper.create_signal_id(obs.sv, obs.code)
                    sid_idx = sid_to_idx[sid]
                    snr_data[epoch_idx, sid_idx] = obs.snr

            data_vars["SNR"] = (
                ("epoch", "sid"),
                snr_data,
                SNR_METADATA
            )

        # Similar for other variables (Phase, Pseudorange, Doppler)

        # 5. Create Dataset
        ds = xr.Dataset(
            data_vars=data_vars,
            coords={
                "epoch": ("epoch", epochs, COORDS_METADATA["epoch"]),
                "sid": ("sid", sids, COORDS_METADATA["sid"]),
                "sv": ("sid", sv_arr, COORDS_METADATA["sv"]),
                "system": ("sid", system_arr, COORDS_METADATA["system"]),
                "band": ("sid", band_arr, COORDS_METADATA["band"]),
                "code": ("sid", code_arr, COORDS_METADATA["code"]),
                "freq_center": ("sid", freq_center, COORDS_METADATA["freq_center"]),
                "freq_min": ("sid", freq_min, COORDS_METADATA["freq_min"]),
                "freq_max": ("sid", freq_max, COORDS_METADATA["freq_max"]),
            },
            attrs={
                **GLOBAL_ATTRS_TEMPLATE,
                "Created": datetime.now().isoformat(),
                "RINEX File Hash": self.file_hash,
                "Source Format": "My Custom Format",
            }
        )

        # 6. CRITICAL: Validate before returning
        self.validate_output(ds, required_vars=keep_rnx_data_vars)

        return ds
```

## Complete Example: RINEX v2 Reader Stub

The following skeleton illustrates a RINEX v2 reader implementation:

```python
from pathlib import Path
from datetime import datetime
from typing import Generator
import xarray as xr
import numpy as np
from pydantic import BaseModel, ConfigDict, model_validator

from canvod.readers.base import GNSSDataReader
from canvod.readers.gnss_specs.utils import rinex_file_hash
from canvod.readers.gnss_specs.signals import SignalIDMapper

class Rnxv2ObsHeader(BaseModel):
    """RINEX v2 header parser."""

    rinex_version: float
    rinex_type: str
    obs_types: list[str]
    interval: float | None = None
    first_obs: datetime | None = None

    @classmethod
    def from_lines(cls, lines: list[str]) -> 'Rnxv2ObsHeader':
        """Parse header from lines."""
        data = {}

        for line in lines:
            label = line[60:80].strip()

            if label == "RINEX VERSION / TYPE":
                data['rinex_version'] = float(line[0:9])
                data['rinex_type'] = line[20]

            elif label == "# / TYPES OF OBSERV":
                num_obs = int(line[0:6])
                obs_types = line[10:60].split()
                data['obs_types'] = obs_types

            # ... parse other fields

        return cls(**data)


class Rnxv2ObsEpoch:
    """RINEX v2 epoch data."""

    def __init__(self, timestamp: datetime, satellites: list):
        self.timestamp = timestamp
        self.satellites = satellites


class Rnxv2Obs(BaseModel, GNSSDataReader):
    """RINEX v2 observation file reader.

    Implements GNSSDataReader ABC for RINEX v2.xx format.

    Examples
    --------
    >>> reader = Rnxv2Obs(fpath=Path("station.10o"))
    >>> ds = reader.to_ds(keep_rnx_data_vars=["SNR"])
    >>> print(ds)
    """

    model_config = ConfigDict(
        frozen=True,
        arbitrary_types_allowed=True,
    )

    fpath: Path
    header: Rnxv2ObsHeader | None = None

    @model_validator(mode='after')
    def parse_header(self):
        """Parse header on initialization."""
        with open(self.fpath, 'r') as f:
            header_lines = []
            for line in f:
                header_lines.append(line)
                if "END OF HEADER" in line:
                    break

        self.header = Rnxv2ObsHeader.from_lines(header_lines)
        return self

    @property
    def file_hash(self) -> str:
        """Compute file hash."""
        return rinex_file_hash(self.fpath)

    @property
    def start_time(self) -> datetime:
        """Return start time."""
        return self.header.first_obs

    @property
    def end_time(self) -> datetime:
        """Return end time."""
        # Would need to parse or compute
        raise NotImplementedError("End time parsing not yet implemented")

    @property
    def systems(self) -> list[str]:
        """Return GNSS systems."""
        # RINEX v2 typically only has GPS
        return ['G']

    @property
    def num_epochs(self) -> int:
        """Return number of epochs."""
        count = 0
        for _ in self.iter_epochs():
            count += 1
        return count

    @property
    def num_satellites(self) -> int:
        """Return number of unique satellites."""
        sats = set()
        for epoch in self.iter_epochs():
            for sat in epoch.satellites:
                sats.add(sat.sv)
        return len(sats)

    def iter_epochs(self) -> Generator[Rnxv2ObsEpoch, None, None]:
        """Iterate over epochs."""
        with open(self.fpath, 'r') as f:
            # Skip to data section
            for line in f:
                if "END OF HEADER" in line:
                    break

            # Parse epoch records
            current_epoch = None
            for line in f:
                # RINEX v2 epoch line format differs from v3
                if len(line) >= 29 and line[0] != ' ':
                    # New epoch
                    if current_epoch:
                        yield current_epoch

                    # Parse epoch line
                    timestamp = self._parse_epoch_line(line)
                    current_epoch = Rnxv2ObsEpoch(timestamp, [])
                else:
                    # Observation line
                    self._parse_observation_line(line, current_epoch)

            if current_epoch:
                yield current_epoch

    def to_ds(
        self,
        keep_rnx_data_vars: list[str] | None = None,
        **kwargs
    ) -> xr.Dataset:
        """Convert to Dataset."""
        # Implementation following the pattern shown above
        # ... (similar to RINEX v3)

        # MUST call validation
        self.validate_output(ds, required_vars=keep_rnx_data_vars)

        return ds

    def _parse_epoch_line(self, line: str) -> datetime:
        """Parse RINEX v2 epoch line."""
        # RINEX v2 format: YY MM DD HH MM SS.SSSSSSS
        year = int(line[1:3]) + 2000  # Y2K handling
        month = int(line[4:6])
        day = int(line[7:9])
        hour = int(line[10:12])
        minute = int(line[13:15])
        second = float(line[16:26])

        return datetime(
            year, month, day, hour, minute,
            int(second), int((second % 1) * 1e6)
        )

    def _parse_observation_line(self, line: str, epoch: Rnxv2ObsEpoch):
        """Parse observation line."""
        # Implementation based on RINEX v2 specification
        pass
```

## Validation Requirements

### Required Dimensions

```python
# The Dataset must have these dimensions
assert "epoch" in ds.dims
assert "sid" in ds.dims
```

### Required Coordinates

```python
# The Dataset must have these coordinates with correct dtypes
required_coords = {
    "epoch": "datetime64[ns]",
    "sid": "object",           # string
    "sv": "object",
    "system": "object",
    "band": "object",
    "code": "object",
    "freq_center": "float64",  # NOT float32
    "freq_min": "float64",
    "freq_max": "float64",
}
```

### Required Attributes

```python
# The Dataset must have these global attributes
required_attrs = {
    "Created",
    "Software",
    "Institution",
    "RINEX File Hash",  # For storage deduplication
}
```

### Data Variables

```python
# At minimum, SNR and Phase must be present
# All data variables must have dimensions ("epoch", "sid")
assert "SNR" in ds.data_vars
assert "Phase" in ds.data_vars
assert ds.SNR.dims == ("epoch", "sid")
```

## Testing

### Unit Tests

```python
# tests/test_my_format.py
from pathlib import Path
import pytest
from my_package.readers import MyFormatReader

class TestMyFormatReader:
    """Test custom format reader."""

    def test_initialization(self):
        """Test reader initialization."""
        reader = MyFormatReader(fpath=Path("test.dat"))
        assert reader.fpath.name == "test.dat"

    def test_file_hash(self, tmp_path):
        """Test file hash computation."""
        test_file = tmp_path / "test.dat"
        test_file.write_text("test content")

        reader = MyFormatReader(fpath=test_file)
        hash1 = reader.file_hash
        hash2 = reader.file_hash  # Should be deterministic

        assert hash1 == hash2
        assert len(hash1) == 16

    def test_to_ds_structure(self):
        """Test Dataset structure."""
        reader = MyFormatReader(fpath=Path("real_test_file.dat"))
        ds = reader.to_ds()

        # Validate structure
        assert "epoch" in ds.dims
        assert "sid" in ds.dims
        assert "SNR" in ds.data_vars
        assert ds.SNR.dims == ("epoch", "sid")

    def test_validation_passes(self):
        """Test validation passes for valid output."""
        reader = MyFormatReader(fpath=Path("real_test_file.dat"))
        ds = reader.to_ds()

        # Should not raise
        from canvod.readers.base import DatasetStructureValidator
        validator = DatasetStructureValidator(dataset=ds)
        validator.validate_all()
```

### Integration Tests

```python
def test_full_pipeline():
    """Test complete pipeline from file to filtered Dataset."""
    reader = MyFormatReader(fpath=Path("real_file.dat"))

    # Convert to Dataset
    ds = reader.to_ds(keep_rnx_data_vars=["SNR"])

    # Filter by system
    gps = ds.where(ds.system == 'G', drop=True)
    assert len(gps.sid) > 0

    # Compute statistics
    mean_snr = gps.SNR.mean()
    assert mean_snr > 0
```

## Registering with ReaderFactory

Once the reader is verified, it can be registered with the factory for automatic format detection:

```python
from canvod.readers.base import ReaderFactory
from my_package.readers import MyFormatReader

# Register
ReaderFactory.register('my_format', MyFormatReader)

# Automatic format detection
reader = ReaderFactory.create("file.dat")
# Returns MyFormatReader instance if format is detected
```

The detection logic should be updated to recognize the new format:

```python
# In ReaderFactory._detect_format()
@staticmethod
def _detect_format(fpath: Path) -> str:
    """Detect file format."""
    with open(fpath, 'r') as f:
        first_line = f.readline()

    # Check for RINEX
    if first_line[60:73].strip() == "RINEX VERSION":
        version = float(first_line[:9].strip())
        if 3.0 <= version < 4.0:
            return 'rinex_v3'
        elif 2.0 <= version < 3.0:
            return 'rinex_v2'

    # Check for custom format
    if first_line.startswith("MY_FORMAT"):
        return 'my_format'

    raise ValueError(f"Unknown format: {fpath}")
```

## Common Pitfalls

### Incorrect dtype for frequencies

```python
# Incorrect: float32
freq_center = np.array([...], dtype=np.float32)

# Correct: float64
freq_center = np.array([...], dtype=np.float64)
```

### Missing validation

```python
# Incorrect: No validation before return
def to_ds(self, **kwargs) -> xr.Dataset:
    ds = self._build_dataset()
    return ds  # Missing validation

# Correct: Always validate
def to_ds(self, **kwargs) -> xr.Dataset:
    ds = self._build_dataset()
    self.validate_output(ds)  # Required
    return ds
```

### Incorrect dimension names

```python
# Incorrect: Non-standard dimension names
data_vars={"SNR": (("time", "signal"), data)}

# Correct: Must be (epoch, sid)
data_vars={"SNR": (("epoch", "sid"), data)}
```

### Missing file hash attribute

```python
# Incorrect: No file hash in attributes
attrs={"Created": "...", "Software": "..."}

# Correct: Include file hash
attrs={
    "Created": "...",
    "Software": "...",
    "RINEX File Hash": self.file_hash,  # Required
}
```

## Pre-Submission Checklist

Before submitting a new reader, the following requirements should be verified:

- Inherits from `GNSSDataReader` and `BaseModel`
- Implements all abstract methods
- Returns validated xarray.Dataset
- Uses `SignalIDMapper` for Signal IDs
- Includes proper metadata (COORDS_METADATA, etc.)
- Has comprehensive tests (>90% coverage)
- Has docstrings (NumPy style)
- Type hints on all methods
- Validation passes (`validate_output()` called)
- File hash included in attributes
- Registered with `ReaderFactory` (if applicable)
