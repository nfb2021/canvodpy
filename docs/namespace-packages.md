---
title: Namespace Packages Explained
description: Understanding how Python namespace packages work and why we use them
---

# Namespace Packages Explained

## The Problem: Package Naming

Imagine you're building a data science toolkit. The traditional approach creates separate packages:

```python
import mycompany_readers
import mycompany_processors
import mycompany_writers
```

This works but has issues:
- **Verbose**: Long package names
- **Disorganized**: Packages aren't clearly related
- **Cluttered**: Every package takes a top-level name

## The Solution: Namespace Packages

Namespace packages let multiple packages share a common prefix:

```python
from mycompany.readers import CSVReader
from mycompany.processors import DataCleaner
from mycompany.writers import ExcelWriter
```

Notice the pattern: `mycompany.{subpackage}`. This creates a **professional, hierarchical API** while keeping packages independent.

---

## How We Use Them

In canVODpy, we have seven packages that all share the `canvod` namespace:

```python
from canvod.readers import Rnxv3Obs              # canvod-readers package
from canvod.auxiliary import Sp3File              # canvod-auxiliary package
from canvod.grids import EqualAreaBuilder         # canvod-grids package
from canvod.vod import VODCalculator              # canvod-vod package
from canvod.store import MyIcechunkStore          # canvod-store package
from canvod.viz import HemisphereVisualizer       # canvod-viz package
```

Each import comes from a **different package**, but they all use the `canvod.*` namespace.

---

## Understanding the Structure

### Regular Package (Before)

A traditional package structure:

```
canvod_readers/              # Package name
├── pyproject.toml
└── src/
    └── canvod_readers/      # Module name (matches package)
        └── __init__.py
```

Import: `from canvod_readers import Rnxv3Obs`

**Problem:** The package name `canvod_readers` pollutes the global namespace.

### Namespace Package (After)

Our namespace package structure:

```
canvod-readers/              # Package name (with dash)
├── pyproject.toml
└── src/
    └── canvod/              # Namespace (NO __init__.py!)
        └── readers/         # Module name
            └── __init__.py
```

Import: `from canvod.readers import Rnxv3Obs`

**Key differences:**
1. Package name uses **dashes**: `canvod-readers`
2. Namespace directory has **NO `__init__.py`**: `canvod/` (empty)
3. Module directory has **`__init__.py`**: `canvod/readers/`

---

## The Magic: No `__init__.py`

The critical part is that **`src/canvod/` has NO `__init__.py` file**.

```
src/
└── canvod/                   # ← NO __init__.py here!
    └── readers/
        └── __init__.py       # ← __init__.py ONLY here
```

**Why?**

When Python sees a directory without `__init__.py`, it treats it as a **namespace package**. Multiple packages can contribute to the same namespace.

### Visual Comparison

**Regular package:**
```
src/
└── canvod/
    ├── __init__.py           # ← This makes it a regular package
    └── readers/
        └── __init__.py
```
Result: **Only one package can use the name `canvod`**

**Namespace package:**
```
src/
└── canvod/                   # ← NO __init__.py = namespace
    └── readers/
        └── __init__.py
```
Result: **Multiple packages can share the `canvod` namespace**

---

## How Python Finds Imports

When you write:
```python
from canvod.readers import Rnxv3Obs
```

Python searches:

1. Look for `canvod` (finds it's a namespace - no `__init__.py`)
2. Look for `readers` within `canvod` (finds regular package with `__init__.py`)
3. Import `Rnxv3Obs` from `canvod/readers/__init__.py`

### With Multiple Packages Installed

If you have both `canvod-readers` and `canvod-grids` installed:

```python
from canvod.readers import Rnxv3Obs    # From canvod-readers package
from canvod.grids import EqualAreaBuilder       # From canvod-grids package
```

Python finds both because:
- Both packages contribute to the `canvod` namespace
- Python merges them seamlessly
- No conflict because each has its own submodule (`readers` vs `grids`)

---

## Implicit Namespace Packages

Our approach uses Python 3.3+ implicit namespace packages.

**Before Python 3.3 (Python 2):**
You needed special code in `__init__.py`:
```python
# canvod/__init__.py (OLD WAY - DON'T DO THIS)
__path__ = __import__('pkgutil').extend_path(__path__, __name__)
```

**After Python 3.3+:**
Just... don't create `__init__.py` in the namespace directory. That's it!

```
src/canvod/              # NO __init__.py needed!
```

**Why is this better?**
- Simpler
- Standard Python
- Faster
- Better tool support

---

## Configuring uv_build

To tell `uv_build` we're creating a namespace package, we use a **dotted module name**:

```toml
# packages/canvod-readers/pyproject.toml
[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"  # ← The dot indicates namespace!
```

The dot in `"canvod.readers"` tells uv_build:
- `canvod` is a **namespace** (don't package it as a regular module)
- `readers` is the **actual module** (package this)

### What Gets Built

When you run `uv build`, uv_build creates a wheel containing:

```
canvod_readers-0.1.0-py3-none-any.whl
└── canvod/
    └── readers/
        ├── __init__.py
        └── ... (your code)
```

Notice:
- No `canvod/__init__.py` in the wheel
- Only `canvod/readers/` content is included
- This allows other packages to add to `canvod/`

---

## Multiple Packages, Same Namespace

Here's how all seven packages coexist:

**Package: canvod-readers**
```
wheel: canvod_readers-0.1.0.whl
└── canvod/
    └── readers/
        └── __init__.py
```

**Package: canvod-auxiliary**
```
wheel: canvod_auxiliary-0.1.0.whl
└── canvod/
    └── auxiliary/
        └── __init__.py
```

**Package: canvod-grids**
```
wheel: canvod_grids-0.1.0.whl
└── canvod/
    └── grids/
        └── __init__.py
```

**When all installed:**
```
site-packages/
└── canvod/
    ├── readers/      # From canvod-readers
    ├── auxiliary/    # From canvod-auxiliary
    ├── grids/        # From canvod-grids
    ├── vod/          # From canvod-vod
    ├── store/        # From canvod-store
    └── viz/          # From canvod-viz
```

All packages contribute to the same `canvod/` directory without conflict!

---

## Common Pitfalls

### ❌ Pitfall 1: Creating `__init__.py` in namespace

```
src/
└── canvod/
    ├── __init__.py        # ← DON'T DO THIS!
    └── readers/
        └── __init__.py
```

**Problem:** Creates a regular package, breaks namespace sharing.

### ❌ Pitfall 2: Wrong module-name syntax

```toml
[tool.uv.build-backend]
module-name = "canvod_readers"    # ← Wrong! No dot = regular package
```

**Problem:** Won't create proper namespace structure.

### ✓ Correct: Use dot notation

```toml
[tool.uv.build-backend]
module-name = "canvod.readers"    # ← Correct! Dot = namespace
```

---

## Testing Namespace Packages

You can verify namespace packages work:

```python
# Test that imports work
from canvod.readers import Rnxv3Obs
from canvod.grids import EqualAreaBuilder

# Test that canvod is a namespace (has no __file__)
import canvod
print(canvod.__file__)  # Should raise AttributeError

# Test that submodules are real packages (have __file__)
from canvod import readers
print(readers.__file__)  # Should show the file path
```

---

## Advantages of Namespace Packages

1. **Professional API**: Clean, hierarchical imports
2. **Modularity**: Users install only what they need
3. **Independence**: Each package can be developed separately
4. **No conflicts**: Packages don't step on each other's toes
5. **Extensibility**: Anyone can add to the namespace
6. **Organization**: Related packages clearly grouped

## Disadvantages

1. **Complexity**: Slightly more complex setup
2. **Understanding**: Developers need to understand the concept
3. **Tooling**: Some old tools don't support them well (we use modern tools that do)

---

## Real-World Examples

Many major Python projects use namespace packages:

- **Azure SDK**: `azure.storage`, `azure.compute`, `azure.ai`
- **Google Cloud**: `google.cloud.storage`, `google.cloud.compute`
- **Zope**: `zope.interface`, `zope.component`, `zope.schema`
- **Sphinx extensions**: `sphinxcontrib.*`

---

## Summary

**Namespace packages let multiple independent packages share a common prefix.**

In canVODpy:
- Seven packages all use `canvod.*` namespace
- Each package is independent and installable separately
- No `__init__.py` in `src/canvod/` (that's the key!)
- uv_build configured with dotted `module-name`
- Result: Clean, professional API

```python
# Users import from a unified namespace
from canvod.readers import Rnxv3Obs
from canvod.grids import EqualAreaBuilder

# But behind the scenes, these are separate packages!
```

---

## Next Steps

- [Architecture Overview](architecture.md) - Overall project structure
- [Build System](build-system.md) - How packages are built
- [Development Workflow](development-workflow.md) - Working with namespace packages
