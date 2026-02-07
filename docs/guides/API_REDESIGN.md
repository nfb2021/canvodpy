# API Redesign Guide

**Version:** 0.2.0 (in development)
**Status:** Complete core implementation
**Date:** 2026-02-04

---

## Overview

The canvodpy API has been redesigned for **extensibility**, **Airflow compatibility**, and **modern Python best practices**. The new architecture provides three layers:

1. **Factories** - Component registration with ABC enforcement
2. **Workflow** - High-level orchestration with structured logging
3. **Functional** - Pure functions for notebooks and Airflow

### Key Benefits

- ✅ **Community extensible** - Register custom readers, grids, VOD calculators
- ✅ **Airflow-ready** - Path-returning functions for XCom serialization
- ✅ **LLM-friendly logging** - Structured output for debugging assistance
- ✅ **Type-safe** - Full modern type hints (Python 3.12+)
- ✅ **Backward compatible** - Legacy API still works

---

## Quick Start

### Installation

```bash
# Install from TestPyPI (beta)
uv add --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ canvodpy
```

### Basic Usage

```python
from canvodpy import VODWorkflow

# Create workflow
workflow = VODWorkflow(site="Rosalia")

# Process one day
data = workflow.process_date("2025001")

# Calculate VOD
vod = workflow.calculate_vod("canopy_01", "reference_01", "2025001")
```

---

## API Layers

### Layer 1: Factories (Community Extensions)

Factories enforce ABC compliance and enable community contributions.

#### Using Built-in Components

```python
from canvodpy import ReaderFactory, GridFactory, VODFactory

# List available components
print(ReaderFactory.list_available())  # ['rinex3']
print(GridFactory.list_available())    # ['equal_area']
print(VODFactory.list_available())     # ['tau_omega']

# Create instances
reader = ReaderFactory.create("rinex3", path="data.rnx")
grid = GridFactory.create("equal_area", angular_resolution=5.0)
```

#### Registering Custom Components

```python
from canvodpy import VODFactory
from canvod.vod.calculator import VODCalculator
import xarray as xr

# Define custom calculator (must inherit ABC)
class MLVODCalculator(VODCalculator):
    model_path: str  # Pydantic validated

    def calculate_vod(self) -> xr.Dataset:
        # Your ML model inference
        pass

# Register with factory
VODFactory.register("ml_vod", MLVODCalculator)

# Use in workflow
workflow = VODWorkflow(
    site="Rosalia",
    vod_calculator="ml_vod",
)
```

#### Factory Types

**ReaderFactory** - For GNSS data readers
- Must inherit: `canvod.readers.base.GNSSDataReader`
- Example: RINEX v3, RINEX v2, custom formats

**GridFactory** - For hemisphere grids
- Must inherit: `canvod.grids.core.grid_builder.BaseGridBuilder`
- Example: Equal area, HTM, HEALPix

**VODFactory** - For VOD calculators
- Must inherit: `canvod.vod.calculator.VODCalculator`
- Example: Tau-omega, ML models, custom algorithms

**AugmentationFactory** - For preprocessing steps
- Must inherit: `canvod.auxiliary.augmentation.AugmentationStep`
- Example: Filtering, interpolation, outlier removal

---

### Layer 2: VODWorkflow (High-Level Orchestration)

The `VODWorkflow` class provides stateful orchestration with factories.

#### Basic Workflow

```python
from canvodpy import VODWorkflow

# Initialize with defaults
workflow = VODWorkflow(site="Rosalia")

# Process single date
data = workflow.process_date("2025001")
print(data.keys())  # dict_keys(['canopy_01', 'reference_01'])

# Access receiver data
canopy = data["canopy_01"]
print(canopy.sizes)  # {'epoch': 2880, 'sv': 32, 'cell': 324}
```

#### Custom Configuration

```python
workflow = VODWorkflow(
    site="Rosalia",
    reader="rinex3",
    grid="equal_area",
    vod_calculator="tau_omega",
    grid_params={
        "angular_resolution": 5.0,
        "cutoff_theta": 75.0,
    },
    log_level="DEBUG",
)
```

#### Calculate VOD

```python
vod = workflow.calculate_vod(
    canopy_receiver="canopy_01",
    sky_receiver="reference_01",
    date="2025001",
)

print(vod.VOD.mean().item())  # 0.42
```

#### Structured Logging

All operations include context-bound logging:

```python
# Logs include site context automatically
workflow = VODWorkflow(site="Rosalia")

# Example log output:
# 2026-02-04T16:00:00 [info] workflow_initialized
#   site=Rosalia grid=equal_area ncells=6448
# 2026-02-04T16:00:01 [info] process_date_started date=2025001
# 2026-02-04T16:00:02 [info] processing_receiver
#   site=Rosalia date=2025001 receiver=canopy_01
```

Scientists can feed these logs to LLMs for debugging!

---

### Layer 3: Functional API (Notebooks & Airflow)

Pure functions for maximum flexibility.

#### For Interactive Notebooks

```python
from canvodpy.functional import (
    read_rinex,
    create_grid,
    assign_grid_cells,
    calculate_vod,
)

# Step 1: Read RINEX
canopy = read_rinex("canopy.rnx")
sky = read_rinex("sky.rnx")

# Step 2: Create grid
grid = create_grid("equal_area", angular_resolution=5.0)

# Step 3: Assign cells
canopy = assign_grid_cells(canopy, grid)
sky = assign_grid_cells(sky, grid)

# Step 4: Calculate VOD
vod = calculate_vod(canopy, sky)
```

#### For Airflow Pipelines

```python
from airflow import DAG
from airflow.decorators import task
from datetime import datetime

from canvodpy.functional import (
    read_rinex_to_file,
    create_grid_to_file,
    assign_grid_cells_to_file,
    calculate_vod_to_file,
)

@task
def load_canopy() -> str:
    """Returns path for XCom."""
    return read_rinex_to_file(
        rinex_path="/data/canopy.rnx",
        output_path="/tmp/canopy.nc",
    )

@task
def load_sky() -> str:
    """Returns path for XCom."""
    return read_rinex_to_file(
        rinex_path="/data/sky.rnx",
        output_path="/tmp/sky.nc",
    )

@task
def compute_vod(canopy_path: str, sky_path: str) -> str:
    """Calculate VOD from paths."""
    return calculate_vod_to_file(
        canopy_path=canopy_path,
        sky_path=sky_path,
        output_path="/tmp/vod.nc",
    )

# DAG definition
with DAG("vod_pipeline", start_date=datetime(2025, 1, 1)) as dag:
    canopy = load_canopy()
    sky = load_sky()
    vod = compute_vod(canopy, sky)
```

**Key difference:** Functions ending in `_to_file` return **str paths** (XCom serializable) instead of xarray Datasets.

---

## Migration Guide

### From Legacy API

The old Site + Pipeline pattern still works but is **deprecated**.

#### Old Way (Still Works)

```python
from canvodpy import Site, Pipeline

site = Site("Rosalia")
pipeline = Pipeline(site)
data = pipeline.process_date("2025001")
```

#### New Way (Recommended)

```python
from canvodpy import VODWorkflow

workflow = VODWorkflow(site="Rosalia")
data = workflow.process_date("2025001")
```

### Key Changes

| Old | New | Notes |
|-----|-----|-------|
| `Site("name")` | `VODWorkflow(site="name")` | Single class |
| `site.pipeline()` | N/A | No separate pipeline |
| Hardcoded components | Factories | Extensible |
| No logging context | Structured logging | LLM-friendly |

---

## Community Extension Guide

### Creating a Custom Reader

```python
from canvod.readers.base import GNSSDataReader
from pydantic import ConfigDict
import xarray as xr
from pathlib import Path

class CustomReader(GNSSDataReader):
    """Custom RINEX reader."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    custom_param: str = "default"

    def read(self) -> xr.Dataset:
        """Read and return Dataset."""
        # Your custom reading logic
        ds = xr.Dataset(...)
        return ds

# Register
from canvodpy import ReaderFactory
ReaderFactory.register("custom", CustomReader)

# Use
workflow = VODWorkflow(site="Rosalia", reader="custom")
```

### Creating a Custom Grid

```python
from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core import GridData

class CustomGridBuilder(BaseGridBuilder):
    """Custom grid builder."""

    def _build_grid(self) -> GridData:
        """Build grid structure."""
        # Your custom grid logic
        return GridData(...)

    def get_grid_type(self) -> str:
        return "custom"

# Register
from canvodpy import GridFactory
GridFactory.register("custom", CustomGridBuilder)

# Use
workflow = VODWorkflow(site="Rosalia", grid="custom")
```

### Creating a Custom VOD Calculator

```python
from canvod.vod.calculator import VODCalculator
import xarray as xr

class MLCalculator(VODCalculator):
    """ML-based VOD calculator."""

    model_path: str  # Pydantic validated

    def calculate_vod(self) -> xr.Dataset:
        """Calculate VOD using ML model."""
        # Load model
        model = load_model(self.model_path)

        # Calculate VOD
        vod = model.predict(self.canopy_ds, self.sky_ds)

        return xr.Dataset({"VOD": vod, ...})

# Register
from canvodpy import VODFactory
VODFactory.register("ml_vod", MLCalculator)

# Use
workflow = VODWorkflow(
    site="Rosalia",
    vod_calculator="ml_vod",
)
```

---

## Examples

Interactive marimo notebooks demonstrating the new API are available in the `demo/` directory:

- `demo/workflow_basic.py` - Basic VODWorkflow usage (coming soon)
- `demo/functional_api.py` - Functional API examples (coming soon)
- `demo/airflow_integration.py` - Airflow DAG examples (coming soon)
- `demo/custom_components.py` - Community extensions (coming soon)

To run marimo notebooks:

```bash
cd demo
marimo edit workflow_basic.py
```

---

## API Reference

### VODWorkflow

```python
class VODWorkflow:
    def __init__(
        self,
        site: str | Site,
        reader: str = "rinex3",
        grid: str = "equal_area",
        vod_calculator: str = "tau_omega",
        grid_params: dict[str, Any] | None = None,
        keep_vars: list[str] | None = None,
        log_level: str = "INFO",
    ) -> None: ...

    def process_date(
        self,
        date: str,
        receivers: list[str] | None = None,
    ) -> dict[str, xr.Dataset]: ...

    def calculate_vod(
        self,
        canopy_receiver: str,
        sky_receiver: str,
        date: str,
        use_cached: bool = True,
    ) -> xr.Dataset: ...
```

### Functional API

```python
# Data-returning versions
def read_rinex(
    path: str | Path,
    reader: str = "rinex3",
    **reader_kwargs: Any,
) -> xr.Dataset: ...

def create_grid(
    grid_type: str = "equal_area",
    **grid_params: Any,
) -> GridData: ...

def assign_grid_cells(
    ds: xr.Dataset,
    grid: GridData,
) -> xr.Dataset: ...

def calculate_vod(
    canopy_ds: xr.Dataset,
    sky_ds: xr.Dataset,
    calculator: str = "tau_omega",
    **calc_kwargs: Any,
) -> xr.Dataset: ...

# Path-returning versions (Airflow)
def read_rinex_to_file(
    rinex_path: str | Path,
    output_path: str | Path,
    reader: str = "rinex3",
    **reader_kwargs: Any,
) -> str: ...

def calculate_vod_to_file(
    canopy_path: str | Path,
    sky_path: str | Path,
    output_path: str | Path,
    calculator: str = "tau_omega",
    **calc_kwargs: Any,
) -> str: ...
```

### Factories

```python
class ComponentFactory[T]:
    @classmethod
    def register(cls, name: str, component_class: type[T]) -> None: ...

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> T: ...

    @classmethod
    def list_available(cls) -> list[str]: ...

class ReaderFactory(ComponentFactory): ...
class GridFactory(ComponentFactory): ...
class VODFactory(ComponentFactory): ...
class AugmentationFactory(ComponentFactory): ...
```

---

## Design Principles

### 1. Sollbruchstellen (Break Points)

Packages are independent with clean interfaces. No circular dependencies.

### 2. Factory Pattern for Extensibility

Community can extend without modifying core code.

### 3. Pure Functions for Airflow

Stateless functions that return serializable paths.

### 4. Structured Logging for LLMs

Scientists can feed logs to ChatGPT/Claude for debugging help.

### 5. Type Safety

Full modern type hints for IDE support and error prevention.

---

## Troubleshooting

### Import Errors

```python
# Error: cannot import name 'VODWorkflow'
# Solution: Ensure you're using canvodpy >= 0.2.0
pip show canvodpy
```

### Factory Registration

```python
# Error: Component 'custom' not registered
# Solution: Register before use
ReaderFactory.register("custom", CustomReader)
```

### Airflow XCom Errors

```python
# Error: Can't pickle Dataset
# Solution: Use *_to_file functions, not data-returning versions
# ❌ Bad: calculate_vod(canopy_ds, sky_ds)
# ✅ Good: calculate_vod_to_file(canopy_path, sky_path, output)
```

---

## Contributing

See `CONTRIBUTING.md` for guidelines on:
- Creating custom components
- Submitting pull requests
- Testing requirements
- Documentation standards

---

## Changelog

### v0.2.0-beta.1 (2026-02-04)

**New Features:**
- ✨ Factory-based component system
- ✨ VODWorkflow orchestration class
- ✨ Functional API with Airflow support
- ✨ Structured logging with context binding

**Breaking Changes:**
- None (backward compatible)

**Deprecated:**
- Site + Pipeline pattern (still works with warnings)

---

## Further Reading

- `docs/guides/ARCHITECTURE.md` - Design patterns
- `docs/guides/DEVELOPMENT.md` - Development workflow
- `examples/` - Complete code examples
