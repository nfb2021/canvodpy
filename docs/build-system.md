---
title: Build System
description: Package building and distribution for canVODpy
---

# Build System

## Distribution Formats

Python packages are distributed in two formats:

**Source distribution (sdist):** `canvod_readers-0.1.0.tar.gz` -- contains source code and metadata. Requires a build step during installation.

**Wheel (built distribution):** `canvod_readers-0.1.0-py3-none-any.whl` -- pre-built, ready to install by copying to site-packages. Preferred format for installation.

Wheel filename components:
```
canvod_readers-0.1.0-py3-none-any.whl
  package name - version - python - ABI - platform
```

## Build Backend Configuration

```toml
# packages/canvod-readers/pyproject.toml
[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"       # Dot creates namespace package
```

The dotted `module-name` instructs uv_build to create a namespace package structure: `canvod/` contains no `__init__.py`, while `canvod/readers/` is the actual module.

## Building

```bash
cd packages/canvod-readers
uv build
```

This produces:
- `dist/canvod_readers-0.1.0.tar.gz`
- `dist/canvod_readers-0.1.0-py3-none-any.whl`

### Wheel Contents

```
canvod/                           # Namespace directory (no __init__.py)
  readers/                        # Module directory
    __init__.py
    base.py
    rinex/
      ...
canvod_readers-0.1.0.dist-info/   # Metadata
  METADATA
  WHEEL
  RECORD
```

### Building All Packages

```bash
just dist                         # Build all packages
```

## Package Metadata

```toml
[project]
name = "canvod-readers"
version = "0.1.0"
description = "GNSS data format readers for canVODpy"
readme = "README.md"
license = {text = "Apache-2.0"}
authors = [{name = "Nicolas Bader", email = "nicolas.bader@geo.tuwien.ac.at"}]
keywords = ["gnss", "rinex", "geodesy"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: GIS",
]
requires-python = ">=3.13"
dependencies = ["numpy>=1.24", "pandas>=2.0"]

[project.urls]
Homepage = "https://github.com/nfb2021/canvodpy"
Repository = "https://github.com/nfb2021/canvodpy"
Issues = "https://github.com/nfb2021/canvodpy/issues"
```

## Publishing to PyPI

### Test on TestPyPI

```bash
cd packages/canvod-readers
uv build
uv publish --repository testpypi
pip install --index-url https://test.pypi.org/simple/ canvod-readers
```

### Publish to Production

```bash
uv build
uv publish
```

## Version Management

All packages follow [Semantic Versioning](https://semver.org/) with unified version numbers.

```bash
just bump patch    # 0.1.0 -> 0.1.1
just bump minor    # 0.1.0 -> 0.2.0
just bump major    # 0.1.0 -> 1.0.0
```

Version bumps update `pyproject.toml` in all packages, create a git commit, and tag the release.

## Including Extra Files

```toml
[tool.uv.build-backend]
module-name = "canvod.readers"
include = ["src/canvod/readers/data/*.dat", "LICENSE", "README.md"]
exclude = ["src/canvod/readers/tests/", "*.pyc"]
```

## Console Scripts

```toml
[project.scripts]
canvod-read = "canvod.readers.cli:main"
```

## Troubleshooting

**ModuleNotFoundError**: Verify `module-name` in `pyproject.toml` uses dotted notation.

**Wrong package structure**: Ensure `module-name = "canvod.readers"` (with dot), not `"canvod_readers"`.

**Build failures**: Run `uv build --verbose` for detailed diagnostics.
