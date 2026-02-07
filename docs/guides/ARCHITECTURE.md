# Architecture & Design Patterns

This document explains the architectural decisions and design patterns used in canvodpy.

---

## 🎯 Design Philosophy

canvodpy follows these core principles:

1. **Modularity** - Independent, reusable packages
2. **Extensibility** - Easy to add custom implementations
3. **Type Safety** - Modern Python type hints (2026 standards)
4. **Simplicity** - Explicit over magic, simple over complex
5. **Scientific Focus** - Optimized for research workflows

---

## 📦 Package Architecture

### The Sollbruchstellen Principle

canvodpy uses the German engineering concept of *Sollbruchstellen* (predetermined breaking points):

> **Design packages to be independent** so they can be used separately or replaced without breaking the entire system.

### Package Independence Metrics

```
✅ No circular dependencies
✅ 4 packages with ZERO dependencies (57%)
✅ Only 3 total internal dependencies
✅ Maximum dependency depth: 1
```

### Dependency Graph

```
Foundation Packages (0 dependencies):
  canvod-readers    → RINEX data readers
  canvod-grids      → Grid implementations
  canvod-vod        → VOD algorithms
  canvod-utils      → Shared utilities

Consumer Packages (1 dependency):
  canvod-auxiliary        → depends on canvod-readers
  canvod-viz        → depends on canvod-grids
  canvod-store      → depends on canvod-grids

Orchestration Package:
  canvodpy          → depends on all packages
```

**Benefits:**
- Foundation packages can be used independently
- Consumer packages add functionality without breaking foundations
- Umbrella package provides unified API
- Easy to swap implementations (e.g., replace grid package)

---

## 🏗️ Design Patterns

### 1. ABC + Factory Pattern

canvodpy uses Abstract Base Classes (ABCs) with Factory pattern for extensibility.

#### Why This Pattern?

**Modern Python (2026):**
- ✅ Type-safe with `Generic[T]`
- ✅ Open/Closed principle (open for extension, closed for modification)
- ✅ Dependency injection
- ✅ Single responsibility

**Scientific Package Priorities:**
- ✅ Simple > Complex
- ✅ Explicit > Magic
- ✅ No framework dependencies
- ✅ Scientists can understand it

#### How It Works

**Step 1: Define ABC (Contract)**

```python
from abc import ABC, abstractmethod
from typing import Protocol
import xarray as xr

class GNSSDataReader(ABC):
    """Abstract base class for RINEX readers."""

    @abstractmethod
    def to_ds(self, keep_rnx_data_vars=None) -> xr.Dataset:
        """Convert RINEX data to xarray Dataset."""
        pass

    @property
    @abstractmethod
    def metadata(self) -> dict:
        """Return metadata about the file."""
        pass
```

**Step 2: Implement Concrete Class**

```python
class Rnxv3Obs(GNSSDataReader):
    """RINEX 3.04 observation file reader."""

    def to_ds(self, keep_rnx_data_vars=None) -> xr.Dataset:
        # Actual implementation
        return xr.Dataset(...)

    @property
    def metadata(self) -> dict:
        return {"version": "3.04", ...}
```

**Step 3: Create Factory**

```python
from typing import Generic, TypeVar

T = TypeVar('T')

class ComponentFactory(Generic[T]):
    """Type-safe factory for creating components."""

    _registry: dict[str, type[T]] = {}

    @classmethod
    def register(cls, name: str, component_class: type[T]) -> None:
        """Register a component implementation."""
        cls._registry[name] = component_class

    @classmethod
    def create(cls, name: str, **kwargs) -> T:
        """Create a component by name."""
        if name not in cls._registry:
            raise ValueError(f"Unknown component: {name}")
        return cls._registry[name](**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered components."""
        return list(cls._registry.keys())

# Specialized factories
class ReaderFactory(ComponentFactory[GNSSDataReader]):
    """Factory for RINEX readers."""
    pass

class GridFactory(ComponentFactory[BaseGridBuilder]):
    """Factory for grid builders."""
    pass

class VODFactory(ComponentFactory):
    """Factory for VOD calculation methods."""
    pass
```

**Step 4: Register Built-in Implementations**

```python
# canvodpy/__init__.py

from canvodpy.factories import ReaderFactory, GridFactory, VODFactory

def _register_builtins():
    """Register built-in implementations."""
    # Readers
    from canvod.readers import Rnxv3Obs
    ReaderFactory.register("rinex_v3", Rnxv3Obs)

    # Grids
    from canvod.grids import EqualAreaBuilder
    GridFactory.register("equal_area", EqualAreaBuilder)

    # VOD methods
    from canvod.vod import TauOmegaZerothOrder
    VODFactory.register("tau_omega", TauOmegaZerothOrder)

# Runs on import (happens in every process)
_register_builtins()
```

**Step 5: Provide Simple API**

```python
def read_rinex(
    file_path: str,
    date: str,
    reader_type: str = "rinex_v3"
) -> xr.Dataset:
    """
    Read RINEX file using specified reader.

    Parameters
    ----------
    file_path : str
        Path to RINEX file
    date : str
        Date in YYYYMMDD format
    reader_type : str
        Reader type (default: "rinex_v3")

    Returns
    -------
    xr.Dataset
        Observations as xarray Dataset
    """
    reader = ReaderFactory.create(reader_type)
    return reader.to_ds()

def create_grid(
    resolution: float,
    grid_type: str = "equal_area"
) -> GridData:
    """
    Create hemisphere grid.

    Parameters
    ----------
    resolution : float
        Angular resolution in degrees
    grid_type : str
        Grid type (default: "equal_area")

    Returns
    -------
    GridData
        Grid object
    """
    builder = GridFactory.create(grid_type)
    return builder.build(resolution)
```

#### User Extensibility

Users can register custom implementations:

```python
from canvodpy import ReaderFactory
from canvod.readers import GNSSDataReader
import xarray as xr

# Define custom reader
class MyLabReader(GNSSDataReader):
    """Custom reader for our lab's format."""

    def to_ds(self, keep_rnx_data_vars=None) -> xr.Dataset:
        # Custom parsing logic
        return xr.Dataset(...)

    @property
    def metadata(self) -> dict:
        return {"format": "mylab_v1", ...}

# Register it
ReaderFactory.register("mylab_v1", MyLabReader)

# Use it!
from canvodpy import read_rinex
data = read_rinex("data.obs", "20260101", reader_type="mylab_v1")
```

#### Type Safety Benefits

```python
# Type checker knows this returns GNSSDataReader
reader = ReaderFactory.create("rinex_v3")

# Type checker knows this returns BaseGridBuilder
builder = GridFactory.create("equal_area")

# Type checker can validate function signatures
def process_data(reader: GNSSDataReader) -> xr.Dataset:
    return reader.to_ds()  # ✅ Type-safe
```

---

### 2. Namespace Packages

canvodpy uses namespace packages for modular distribution:

```
canvod.readers      → canvod-readers package
canvod.auxiliary          → canvod-auxiliary package
canvod.grids        → canvod-grids package
canvod.store        → canvod-store package
canvod.utils        → canvod-utils package
canvod.viz          → canvod-viz package
canvod.vod          → canvod-vod package
```

**Benefits:**
- Users can install only needed packages: `uv add canvod-readers`
- Packages share `canvod` namespace: `from canvod.readers import Rnxv3Obs`
- Clear package boundaries
- Facilitates independent versioning (future option)

**Implementation:**

Each package has:
```
packages/canvod-readers/
  └── src/
      └── canvod/           ← Namespace root
          └── readers/      ← Package code
              └── __init__.py
```

No `__init__.py` in `canvod/` directory (makes it a namespace package).

---

### 3. Unified API Surface

The umbrella package (`canvodpy`) provides a clean, top-level API:

```python
# Instead of:
from canvod.readers import Rnxv3Obs
reader = Rnxv3Obs(file_path, date)
data = reader.to_ds()

# Users do:
from canvodpy import read_rinex
data = read_rinex(file_path, date)
```

**Benefits:**
- Simple for beginners
- Hides implementation details
- Consistent API across components
- Easy to document

**Implementation:**

```python
# canvodpy/__init__.py

# Re-export simple API functions
from canvodpy.api.readers import read_rinex
from canvodpy.api.grids import create_grid, assign_to_grid
from canvodpy.api.vod import calculate_vod

# Re-export factories (for advanced users)
from canvodpy.factories import (
    ReaderFactory,
    GridFactory,
    VODFactory,
)

__all__ = [
    # Simple API
    "read_rinex",
    "create_grid",
    "assign_to_grid",
    "calculate_vod",

    # Advanced API
    "ReaderFactory",
    "GridFactory",
    "VODFactory",
]
```

---

### 4. Configuration Management

canvodpy separates credentials from configuration:

**Credentials → `.env` file (never committed)**
```bash
CDDIS_MAIL=your@email.com
GNSS_ROOT_DIR=/data/gnss
```

**Configuration → YAML files (committed)**
```yaml
# config/processing.yaml
metadata:
  author: Your Name
  institution: Your Uni

aux_data:
  agency: COD
  product_type: final
```

**Benefits:**
- Secrets never committed to git
- Configuration is version-controlled
- Easy to share configurations
- Clear separation of concerns

**Implementation:**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Application settings (from .env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cddis_mail: str | None = None
    gnss_root_dir: str

# Load settings
settings = Settings()

# Load configuration
from canvod.utils.config import load_config
config = load_config("config/processing.yaml")
```

---

## 🔄 Airflow Compatibility

The ABC + Factory pattern is designed for Apache Airflow workflows.

### Pure Functions (Airflow Requirement)

Each API function is stateless:

```python
from airflow.decorators import task

@task
def process_rinex_task(file_path: str, date: str) -> str:
    """Process RINEX → save → return path."""
    from canvodpy import read_rinex

    # Creates fresh objects each call (no state)
    obs = read_rinex(file_path, date)

    output = f"/data/obs_{date}.zarr"
    obs.to_zarr(output)
    return output  # Return path, not large Dataset

@task
def create_grid_task(resolution: float) -> str:
    """Create grid → pickle → return path."""
    from canvodpy import create_grid
    import pickle

    grid = create_grid(resolution)

    output = f"/data/grid_{resolution}.pkl"
    with open(output, "wb") as f:
        pickle.dump(grid, f)
    return output

@task
def calculate_vod_task(canopy_path: str, ref_path: str) -> str:
    """Load data → calculate VOD → save."""
    from canvodpy import calculate_vod
    import xarray as xr

    canopy = xr.open_zarr(canopy_path)
    reference = xr.open_zarr(ref_path)

    vod = calculate_vod(canopy, reference)

    output = f"/data/vod.zarr"
    vod.to_zarr(output)
    return output
```

### Worker Process Compatibility

Factory registration happens on module import, ensuring each Airflow worker has registered implementations:

```python
# canvodpy/__init__.py

def _register_builtins():
    """Register built-in implementations."""
    ReaderFactory.register("rinex_v3", Rnxv3Obs)
    GridFactory.register("equal_area", EqualAreaBuilder)
    # ...

# Runs when module imported (happens in every worker)
_register_builtins()
```

### Complete Airflow Example

```python
"""vod_processing_dag.py - Production-ready Airflow DAG"""

from airflow.decorators import dag, task
from datetime import datetime

# Factory registration happens on import in each worker ✅
from canvodpy import read_rinex, create_grid, calculate_vod

@dag(
    dag_id="vod_processing",
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
)
def vod_processing_pipeline():
    """VOD calculation pipeline."""

    @task
    def process_rinex_task(file_path: str, date: str) -> str:
        obs = read_rinex(file_path, date)
        output = f"/data/obs_{date}.zarr"
        obs.to_zarr(output)
        return output

    @task
    def create_grid_task(resolution: float) -> str:
        import pickle
        grid = create_grid(resolution)
        output = f"/data/grid_{resolution}.pkl"
        with open(output, "wb") as f:
            pickle.dump(grid, f)
        return output

    @task
    def calculate_vod_task(canopy_path: str, ref_path: str) -> str:
        import xarray as xr
        canopy = xr.open_zarr(canopy_path)
        reference = xr.open_zarr(ref_path)
        vod = calculate_vod(canopy, reference)
        output = "/data/vod.zarr"
        vod.to_zarr(output)
        return output

    # Build DAG
    date = "{{ ds_nodash }}"

    canopy = process_rinex_task(f"/data/rinex/canopy_{date}.rnx", date)
    reference = process_rinex_task(f"/data/rinex/ref_{date}.rnx", date)
    grid = create_grid_task(5.0)

    vod_result = calculate_vod_task(canopy, reference)

dag = vod_processing_pipeline()
```

---

## 🎨 Design Principles Summary

### 1. Modularity
- **Independent packages** with minimal dependencies
- **Namespace packages** for clean distribution
- **Foundation packages** (0 deps) can be used standalone

### 2. Extensibility
- **ABC + Factory pattern** for user implementations
- **Type-safe** with Generic[T]
- **Simple registration** API

### 3. Type Safety
- **Modern Python 3.12+ type hints**
- **Pydantic** for configuration validation
- **Type-safe factories** with Generic[T]

### 4. Simplicity
- **Explicit over magic** - no hidden framework dependencies
- **Simple over complex** - scientists can understand it
- **Clean API surface** - easy to learn and use

### 5. Scientific Focus
- **Airflow-compatible** - pure functions, no state
- **xarray-first** - idiomatic scientific Python
- **Configuration management** - reproducible research
- **FAIR principles** - unified versioning, DOI support

---

## 📚 References

- [Package Dependencies](../dependencies.md) - Detailed dependency analysis
- [Development Workflow](../development-workflow.md) - Build system and tools
- [Namespace Packages](../namespace-packages.md) - Technical details

---

**Questions? See [Development Guide](./DEVELOPMENT.md) or [Contributing Guidelines](../../CONTRIBUTING.md)**
