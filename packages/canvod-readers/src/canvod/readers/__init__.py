"""GNSS data format readers.

This package provides readers for various GNSS data formats, all implementing
a common interface for seamless integration with processing pipelines.

Supported formats:
- RINEX v3.04 (GNSS observations)
- More formats coming soon...

Quick Start
-----------
```python
from canvod.readers import Rnxv3Obs

# Read RINEX v3 file
reader = Rnxv3Obs(fpath="station.24o")
dataset = reader.to_ds()
```

Or use the canvodpy factory for automatic format detection:
```python
from canvodpy import ReaderFactory

# Auto-detects format from file header
reader = ReaderFactory.create_from_file("station.24o")
dataset = reader.to_ds()
```

Directory Matching:
```python
from canvod.readers import DataDirMatcher

# Find dates with RINEX files in both receivers
matcher = DataDirMatcher(root=Path("/data/01_Rosalia"))
for matched_dirs in matcher:
    print(matched_dirs.yyyydoy)
    # Load RINEX files from matched_dirs.canopy_data_dir
```
"""

from canvod.readers.base import (
    DEFAULT_REQUIRED_VARS,
    REQUIRED_ATTRS,
    REQUIRED_COORDS,
    REQUIRED_DIMS,
    DatasetStructureValidator,
    GNSSDataReader,
    SignalID,
    validate_dataset,
)
from canvod.readers.builder import DatasetBuilder
from canvod.readers.matching import (
    DataDirMatcher,
    MatchedDirs,
    PairDataDirMatcher,
    PairMatchedDirs,
)
from canvod.readers.rinex import Rnxv2Obs
from canvod.readers.rinex.v3_04 import Rnxv3Obs
from canvod.readers.sbf import SbfEpoch, SbfHeader, SbfReader, SbfSignalObs
from canvod.utils.tools import YYYYDOY

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_REQUIRED_VARS",
    "REQUIRED_ATTRS",
    "REQUIRED_COORDS",
    "REQUIRED_DIMS",
    "YYYYDOY",
    "DataDirMatcher",
    "DatasetBuilder",
    "DatasetStructureValidator",
    "GNSSDataReader",
    "MatchedDirs",
    "PairDataDirMatcher",
    "PairMatchedDirs",
    "Rnxv2Obs",
    "Rnxv3Obs",
    "SbfEpoch",
    "SbfHeader",
    "SbfReader",
    "SbfSignalObs",
    "SignalID",
    "validate_dataset",
]
