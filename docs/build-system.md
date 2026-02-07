---
title: Build System Deep Dive
description: Understanding how Python packages are built and distributed
---

# Build System Deep Dive

This document explains how Python packages are built, distributed, and installed. We'll go from basic concepts to our specific implementation.

## What is "Building" a Package?

**Building** a Python package means creating distribution files that can be:
- Uploaded to PyPI (Python Package Index)
- Installed with `pip` or `uv`
- Shared with users

### Distribution Formats

Python has two main distribution formats:

#### 1. Source Distribution (sdist)

**File:** `canvod_readers-0.1.0.tar.gz`

**Contains:**
- Source code (`.py` files)
- `pyproject.toml`
- `README.md`, `LICENSE`
- Everything needed to build the package

**When used:**
- No prebuilt wheel available
- Source-only packages (rare)
- Building from source

**Install process:**
1. Download `.tar.gz`
2. Extract files
3. Run build process
4. Install resulting files

#### 2. Wheel (Built Distribution)

**File:** `canvod_readers-0.1.0-py3-none-any.whl`

**Contains:**
- Pre-built package ready to install
- Just copy files to site-packages
- No compilation needed

**When used:**
- Preferred format (fastest)
- Most packages on PyPI have wheels
- Cross-platform (pure Python)

**Install process:**
1. Download `.whl`
2. Extract directly to site-packages
3. Done! (very fast)

**Filename breakdown:**
```
canvod_readers-0.1.0-py3-none-any.whl
│              │     │   │    │
│              │     │   │    └─ Platform (any = all platforms)
│              │     │   └────── ABI tag (none = pure Python)
│              │     └────────── Python version (py3 = Python 3)
│              └──────────────── Version (0.1.0)
└─────────────────────────────── Package name
```

---

## The Build System: pyproject.toml

All build configuration lives in `pyproject.toml`:

```toml
[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]  # Build tool needed
build-backend = "uv_build"                # Which backend to use
```

### What is a Build Backend?

A **build backend** is a tool that knows how to:
1. Read your source code
2. Package it correctly
3. Create distribution files

**Common build backends:**
- `uv_build` (modern, fast, Rust-based)
- `hatchling` (popular, feature-rich)
- `setuptools` (traditional, widely used)
- `flit` (simple, lightweight)
- `poetry-core` (used by Poetry)

**We use `uv_build` for most packages because:**
- Native namespace package support
- Extremely fast (Rust)
- Simple configuration
- Part of the uv ecosystem

Note: `canvod-utils` uses `hatchling` as its build backend instead.

---

## Our Build Configuration

### Standard Package Configuration

```toml
# packages/canvod-readers/pyproject.toml
[project]
name = "canvod-readers"              # PyPI package name
version = "0.1.0"                    # Semantic version
description = "GNSS data readers"    # Short description
requires-python = ">=3.13"           # Python version requirement
dependencies = [                     # Runtime dependencies
    "numpy>=1.24",
    "pandas>=2.0",
]

[dependency-groups]
dev = [                              # Development dependencies
    "pytest>=8.0",
    "ruff>=0.14",
]

[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"       # Namespace package config
```

### The Critical Part: module-name

```toml
[tool.uv.build-backend]
module-name = "canvod.readers"
```

This single line tells uv_build:
- Create a namespace package structure
- `canvod` is the namespace (shared)
- `readers` is the module (unique to this package)

**Without the dot:**
```toml
module-name = "canvod_readers"  # Regular package
```
Result: `canvod_readers/__init__.py`

**With the dot:**
```toml
module-name = "canvod.readers"  # Namespace package
```
Result: `canvod/readers/__init__.py` (no `canvod/__init__.py`)

---

## The Build Process

### Manual Build

```bash
cd packages/canvod-readers
uv build
```

**What happens:**

1. **Read Configuration**
   - uv reads `pyproject.toml`
   - Finds `build-backend = "uv_build"`
   - Loads `uv_build` package

2. **Prepare Source**
   - Scans `src/` directory
   - Finds `canvod/readers/` based on `module-name`
   - Excludes test files, pycache, etc.

3. **Create Source Distribution**
   - Packages source code
   - Includes metadata
   - Creates `dist/canvod_readers-0.1.0.tar.gz`

4. **Create Wheel**
   - Copies Python files
   - Generates metadata files
   - Creates `dist/canvod_readers-0.1.0-py3-none-any.whl`

### What's Inside the Wheel

```bash
unzip -l dist/canvod_readers-0.1.0-py3-none-any.whl
```

```
canvod/                           # Namespace directory
  readers/                        # Module directory
    __init__.py
    base.py
    rinex/
      __init__.py
      v3_04.py
    gnss_specs/
      ...
    matching/
      ...
canvod_readers-0.1.0.dist-info/   # Metadata
  METADATA                        # Package metadata
  WHEEL                           # Wheel format metadata
  RECORD                          # File checksums
```

**Key observations:**
- `canvod/` has NO `__init__.py` (namespace!)
- `canvod/readers/` has `__init__.py` (regular package)
- Metadata in separate `.dist-info` directory

---

## Building the Entire Workspace

### Build All Packages

```bash
# From workspace root
for pkg in packages/*/; do
  cd "$pkg"
  uv build
  cd ../..
done

# OR use Just
just dist
```

This creates:
```
packages/
├── canvod-readers/
│   └── dist/
│       ├── canvod_readers-0.1.0.tar.gz
│       └── canvod_readers-0.1.0-py3-none-any.whl
├── canvod-auxiliary/
│   └── dist/
│       ├── canvod_aux-0.1.0.tar.gz
│       └── canvod_aux-0.1.0-py3-none-any.whl
└── ...
```

### Collect All Wheels

```bash
# Copy all wheels to a single directory
mkdir -p dist-all
find packages -name "*.whl" -exec cp {} dist-all/ \;

# Result:
# dist-all/
#   ├── canvod_readers-0.1.0-py3-none-any.whl
#   ├── canvod_aux-0.1.0-py3-none-any.whl
#   └── ...
```

---

## Installing Built Packages

### From Local Wheel

```bash
# Install specific package
pip install dist/canvod_readers-0.1.0-py3-none-any.whl

# OR with uv
uv pip install dist/canvod_readers-0.1.0-py3-none-any.whl
```

### From PyPI (after publishing)

```bash
pip install canvod-readers

# OR install specific version
pip install canvod-readers==0.1.0
```

### Installing All Packages

```bash
# Install all from local wheels
pip install dist-all/*.whl

# OR from PyPI
pip install canvodpy  # Umbrella package that depends on all
```

---

## Publishing to PyPI

### Prerequisites

1. **PyPI Account**
   - Sign up at https://pypi.org
   - Create API token

2. **Configure Credentials**
   ```bash
   # Store token securely
   uv publish --token $PYPI_TOKEN

   # OR use .pypirc
   cat > ~/.pypirc << EOF
   [pypi]
   username = __token__
   password = pypi-...your-token...
   EOF
   ```

### Publishing Process

#### Test on TestPyPI First

```bash
cd packages/canvod-readers

# Build
uv build

# Upload to TestPyPI
uv publish --repository testpypi

# Test installation
pip install --index-url https://test.pypi.org/simple/ canvod-readers
```

#### Publish to Production PyPI

```bash
# Build
uv build

# Upload to PyPI
uv publish

# Now anyone can install:
pip install canvod-readers
```

### Publishing All Packages

```bash
for pkg in packages/*/; do
  cd "$pkg"
  uv build
  uv publish
  cd ../..
done
```

---

## Version Management

### Semantic Versioning

We follow [Semantic Versioning](https://semver.org/):

**Format:** `MAJOR.MINOR.PATCH` (e.g., `1.2.3`)

- **MAJOR**: Breaking changes (1.0.0 → 2.0.0)
- **MINOR**: New features, backwards compatible (1.0.0 → 1.1.0)
- **PATCH**: Bug fixes (1.0.0 → 1.0.1)

**Pre-release:** `1.0.0-alpha`, `1.0.0-beta`, `1.0.0-rc1`

### Version Bumping

```bash
# From workspace root
just bump patch    # 0.1.0 → 0.1.1
just bump minor    # 0.1.0 → 0.2.0
just bump major    # 0.1.0 → 1.0.0
```

This:
1. Updates `version` in `pyproject.toml`
2. Updates `uv.lock`
3. Creates git commit
4. Creates git tag (`v0.1.1`)

### Version Constraints in Dependencies

When one package depends on another:

```toml
# packages/canvod-grids/pyproject.toml
[project]
dependencies = [
    "canvod-readers>=0.1.0",    # Any version ≥ 0.1.0
    "canvod-auxiliary>=0.1.0,<0.2.0", # Pin to 0.1.x
    "numpy~=1.24.0",            # Compatible with 1.24.x
]
```

**Constraint types:**
- `>=0.1.0` - At least 0.1.0
- `<2.0.0` - Below 2.0.0
- `~=1.2.0` - Compatible release (1.2.0 to <1.3.0)
- `==1.2.3` - Exact version (avoid unless necessary)

---

## Metadata in pyproject.toml

### Full Example

```toml
[project]
name = "canvod-readers"
version = "0.1.0"
description = "GNSS data format readers for canVODpy"
readme = "README.md"
license = {text = "Apache-2.0"}
authors = [
    {name = "Nicolas Bader", email = "nicolas.bader@geo.tuwien.ac.at"}
]
maintainers = [
    {name = "Nicolas Bader", email = "nicolas.bader@geo.tuwien.ac.at"}
]
keywords = ["gnss", "rinex", "geodesy"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: GIS",
]
requires-python = ">=3.13"
dependencies = [
    "numpy>=1.24",
    "pandas>=2.0",
]

[project.urls]
Homepage = "https://github.com/nfb2021/canvodpy"
Documentation = "https://canvodpy.readthedocs.io"
Repository = "https://github.com/nfb2021/canvodpy"
Issues = "https://github.com/nfb2021/canvodpy/issues"

[project.optional-dependencies]
viz = ["matplotlib>=3.7"]
ml = ["scikit-learn>=1.3"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.14",
    "ty>=0.0.9",
]

[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"
```

**Metadata shows up on PyPI:**

- Package name, description
- Author information
- License
- Links (homepage, docs, issues)
- Python version requirements
- Dependencies
- Keywords and classifiers

---

## Build Customization

### Including Extra Files

By default, only Python files in `src/` are included. To include extra files:

```toml
[tool.uv.build-backend]
module-name = "canvod.readers"
include = [
    "src/canvod/readers/data/*.dat",  # Include data files
    "LICENSE",
    "README.md",
]
exclude = [
    "src/canvod/readers/tests/",      # Exclude tests
    "*.pyc",
    "__pycache__",
]
```

### Package Data

To include non-Python files that should be installed:

```toml
[tool.uv.build-backend]
module-name = "canvod.readers"

# Include data files in package
package-data = {"canvod.readers" = ["data/*.json", "schemas/*.yaml"]}
```

Access in code:
```python
from importlib.resources import files

data = files("canvod.readers").joinpath("data/config.json").read_text()
```

---

## Advanced: Entry Points

### Console Scripts

Create command-line tools from your package:

```toml
[project.scripts]
canvod-read = "canvod.readers.cli:main"
```

Now users can run:
```bash
canvod-read file.rnx
```

Which calls:
```python
# canvod/readers/cli.py
def main():
    import sys
    print(f"Reading {sys.argv[1]}")
```

---

## Troubleshooting Builds

### Common Issues

**1. Module not found**
```
ModuleNotFoundError: No module named 'canvod.readers'
```
**Fix:** Check `module-name` in `pyproject.toml`

**2. Wrong package structure in wheel**
```
# Wrong: canvod_readers/...
# Right: canvod/readers/...
```
**Fix:** Use dotted `module-name = "canvod.readers"`

**3. Missing dependencies in wheel**
```
# dependencies not in dependencies list
```
**Fix:** Add to `[project.dependencies]`

**4. Build fails**
```
Build backend returned an error
```
**Fix:** Check `pyproject.toml` syntax with:
```bash
uv build --verbose
```

---

## Summary

**Build system hierarchy:**
```
pyproject.toml
  ↓
[build-system] → uv_build
  ↓
[tool.uv.build-backend] → module-name config
  ↓
Source code → Wheel + Source dist
  ↓
PyPI → pip install
  ↓
User's computer
```

**Key files:**
- `pyproject.toml` - Configuration
- `uv.lock` - Locked dependencies
- `dist/*.whl` - Built wheels
- `dist/*.tar.gz` - Source distributions

**Key commands:**
```bash
uv build          # Build package
uv publish        # Publish to PyPI
just bump patch   # Version bump
just dist         # Build all packages
```

---

## Next Steps

- [Architecture](architecture.md) - Project structure
- [Namespace Packages](namespace-packages.md) - How namespaces work
- [Development Workflow](development-workflow.md) - Daily development
- [Tooling](tooling.md) - All tools explained
