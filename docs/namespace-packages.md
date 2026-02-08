---
title: Namespace Packages
description: Implementation of Python implicit namespace packages in canVODpy
---

# Namespace Packages

## Overview

canVODpy uses Python 3.3+ implicit namespace packages to allow seven independent packages to share the `canvod.*` import prefix. This enables a unified API while keeping packages independently installable.

```python
from canvod.readers import Rnxv3Obs        # from canvod-readers package
from canvod.auxiliary import Sp3File        # from canvod-auxiliary package
from canvod.grids import EqualAreaBuilder   # from canvod-grids package
```

## Mechanism

### Directory Structure

A namespace package is created by omitting `__init__.py` from the shared parent directory:

```
canvod-readers/
  src/
    canvod/              # Namespace directory -- NO __init__.py
      readers/           # Package directory
        __init__.py      # Regular package
```

When Python encounters a directory without `__init__.py`, it treats it as a namespace package. Multiple installed packages can each contribute a subdirectory under the same namespace without conflict.

### Comparison with Regular Packages

**Regular package** (only one package can claim the name):
```
src/
  canvod/
    __init__.py        # Makes this a regular package -- blocks other contributors
    readers/
      __init__.py
```

**Namespace package** (multiple packages share the name):
```
src/
  canvod/              # No __init__.py -- namespace is open for extension
    readers/
      __init__.py
```

## Build Configuration

The `uv_build` backend is configured with a dotted `module-name` to produce correct namespace structure:

```toml
# packages/canvod-readers/pyproject.toml
[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"  # Dot indicates namespace package
```

The dot in `"canvod.readers"` instructs uv_build to:
- Treat `canvod` as a namespace (do not include `__init__.py` for it)
- Package only the `readers` subdirectory

## Wheel Contents

A built wheel contains the namespace structure without a top-level `__init__.py`:

```
canvod_readers-0.1.0-py3-none-any.whl
  canvod/
    readers/
      __init__.py
      base.py
      rinex/
        ...
  canvod_readers-0.1.0.dist-info/
    METADATA
    WHEEL
    RECORD
```

## Combined Installation

When multiple packages are installed, Python merges them under one namespace:

```
site-packages/
  canvod/
    readers/      # From canvod-readers
    auxiliary/    # From canvod-auxiliary
    grids/        # From canvod-grids
    vod/          # From canvod-vod
    store/        # From canvod-store
    viz/          # From canvod-viz
```

## Import Resolution

When Python processes `from canvod.readers import Rnxv3Obs`:

1. It finds `canvod` as a namespace (no `__init__.py`)
2. It locates `readers` within `canvod` (has `__init__.py` -- regular package)
3. It imports `Rnxv3Obs` from `canvod/readers/__init__.py`

## Verification

```python
import canvod
print(canvod.__file__)   # AttributeError -- namespace packages have no __file__

from canvod import readers
print(readers.__file__)  # Prints the file path -- regular package
```

## Common Pitfalls

### Adding `__init__.py` to the Namespace Directory

Creating `src/canvod/__init__.py` converts the namespace into a regular package, preventing other packages from contributing to it.

### Incorrect module-name Configuration

```toml
# Incorrect -- creates regular package, not namespace
module-name = "canvod_readers"

# Correct -- creates namespace package
module-name = "canvod.readers"
```

## Precedents

Namespace packages are used by several major Python projects:

- **Azure SDK**: `azure.storage`, `azure.compute`, `azure.ai`
- **Google Cloud**: `google.cloud.storage`, `google.cloud.compute`
- **Zope**: `zope.interface`, `zope.component`
- **Sphinx extensions**: `sphinxcontrib.*`
