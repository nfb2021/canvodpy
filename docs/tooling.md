---
title: Development Tooling
description: Understanding the modern Python tools used in canVODpy
---

# Development Tooling

This document explains every tool we use and why we chose it. Think of this as a comprehensive guide for someone completely new to modern Python development.

## The Problem: Traditional Python Tooling

Traditional Python development involves many separate tools:
- `pip` for installing packages
- `virtualenv` or `venv` for environments
- `setuptools` or `distutils` for building
- `flake8` + `black` + `isort` for code quality
- `mypy` for type checking
- `twine` for publishing
- `requirements.txt` or `setup.py` for dependencies

Each tool has its own configuration format, its own commands, and they don't always work well together.

## Our Solution: Modern, Integrated Tooling

We use a modern toolchain from [Astral](https://astral.sh/) that consolidates functionality and works seamlessly together.

---

## Core Tools

### 1. uv - The Package Manager

**Website:** https://docs.astral.sh/uv/

**What it does:**
- Manages Python versions
- Creates virtual environments
- Installs packages (like `pip`)
- Resolves dependencies
- Locks dependencies
- Runs commands
- Builds packages

**Why we chose it:**
- **10-100x faster** than pip
- **Written in Rust** for speed and reliability
- **All-in-one tool** replaces pip, venv, pip-tools, and more
- **Compatible with pip** - uses PyPI, respects requirements.txt
- **From Astral** - same team as ruff, actively maintained

**Common commands:**

```bash
# Install dependencies
uv sync

# Add a new dependency
uv add numpy

# Run a command in the environment
uv run python script.py
uv run pytest

# Build the package
uv build

# Create environment with specific Python version
uv venv --python 3.13
```

**How it works:**

1. **Dependency Resolution:** uv reads `pyproject.toml` and figures out all dependencies
2. **Lockfile Creation:** Creates `uv.lock` with exact versions
3. **Installation:** Downloads and installs packages blazingly fast
4. **Environment Management:** Creates `.venv/` directory with everything installed

**Configuration:**

All configuration lives in `pyproject.toml`:

```toml
[project]
name = "canvod-readers"
dependencies = [
    "numpy>=1.24",
    "pandas>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.14",
]
```

---

### 2. uv_build - The Build Backend

**Website:** https://docs.astral.sh/uv/concepts/build-backend/

**What it does:**
- Builds Python packages (creates `.whl` and `.tar.gz` files)
- Handles package metadata
- Supports namespace packages
- Integrates with uv

**Why we chose it:**
- **Native namespace package support** (critical for our `canvod.*` structure)
- **Fast** - built in Rust
- **Simple configuration** - minimal boilerplate
- **Pure uv ecosystem** - no need for setuptools or hatchling

**How it works:**

In `pyproject.toml`:

```toml
[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"  # The dot creates a namespace package!
```

The dot in `"canvod.readers"` tells uv_build:
- This is a **namespace package**
- Don't create `canvod/__init__.py`
- Allow multiple packages to share the `canvod` namespace

**Building:**

```bash
uv build              # Creates dist/canvod_readers-0.1.0.tar.gz and .whl
```

---

### 3. ruff - The Linter and Formatter

**Website:** https://docs.astral.sh/ruff/

**What it does:**
- **Lints** Python code (finds errors, style issues, bad practices)
- **Formats** Python code (makes it pretty and consistent)
- **Replaces:** flake8, pylint, black, isort, and 10+ other tools

**Why we chose it:**
- **10-100x faster** than traditional tools
- **Written in Rust**
- **All-in-one** - no need for black + isort + flake8
- **Configurable** - thousands of rules
- **Auto-fixes** many issues

**What makes it special:**

Ruff implements **700+ linting rules** from many different tools:
- Pyflakes (F)
- pycodestyle (E, W)
- isort (I)
- pep8-naming (N)
- flake8-bugbear (B)
- flake8-comprehensions (C4)
- ... and many more

**Our configuration:**

```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "W",   # pycodestyle warnings
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "SIM", # flake8-simplify
    "C4",  # flake8-comprehensions
    "RUF", # ruff-specific
    "PIE", # flake8-pie
    "PT",  # flake8-pytest-style
]
```

**Common commands:**

```bash
# Check for issues
ruff check .

# Check and auto-fix
ruff check . --fix

# Format code
ruff format .

# Check if formatted
ruff format . --check
```

**Example:**

Before ruff:
```python
import os, sys  # Multiple imports on one line
x=1+2  # No spaces around operators
def badname( ): pass  # Bad style
```

After ruff:
```python
import os
import sys

x = 1 + 2


def badname():
    pass
```

---

### 4. ty - The Type Checker

**Website:** Part of Astral's ecosystem (new tool)

**What it does:**
- Checks Python type hints
- Finds type errors before runtime
- **Replaces:** mypy

**Why we chose it:**
- **Faster** than mypy
- **From Astral** - same ecosystem as uv and ruff
- **Better error messages**
- **Modern** - designed for modern Python

**How type checking works:**

Python supports optional type hints:

```python
# Without types (old way)
def add(a, b):
    return a + b

# With types (modern way)
def add(a: int, b: int) -> int:
    return a + b
```

The type checker verifies:
```python
add(1, 2)       # ✓ OK
add("a", "b")   # ✗ Error: expected int, got str
```

**Configuration:**

ty requires minimal configuration. It is still in early development (alpha stage) and is installed as a dev dependency (`ty>=0.0.1a27`).

**Common commands:**

```bash
# Check types
ty check .

# Check specific file
ty check src/canvod/readers/__init__.py
```

---

## Supporting Tools

### 5. Just - Task Runner

**Website:** https://github.com/casey/just

**What it does:**
- Runs common development commands
- Like `make` but for any language
- **Replaces:** Makefile, shell scripts, npm scripts

**Why we chose it:**
- **Simple syntax** - easier than Makefiles
- **Cross-platform** - works on Windows, Mac, Linux
- **Commands with arguments** - flexible
- **Aliases** - shortcuts for common tasks

**Example Justfile:**

```just
# Run tests
test:
    uv run pytest

# Format and lint
check:
    uv run ruff format .
    uv run ruff check . --fix
    uv run ty check

# Clean build artifacts
clean:
    rm -rf dist/ build/
```

**Usage:**

```bash
just test         # Run tests
just check        # Check code quality
just              # List all commands
```

---

### 6. pytest - Testing Framework

**Website:** https://docs.pytest.org/

**What it does:**
- Runs tests
- Generates coverage reports
- Provides fixtures and mocking

**Why we chose it:**
- **Industry standard** for Python testing
- **Simple** - just write `test_*.py` files
- **Powerful** - fixtures, parametrization, plugins
- **Good integration** with coverage tools

**Example test:**

```python
# tests/test_readers.py
def test_rnx_reader():
    from canvod.readers import Rnxv3Obs
    reader = Rnxv3Obs()
    assert reader is not None
```

**Running:**

```bash
uv run pytest                    # Run all tests
uv run pytest tests/test_file.py # Run specific test
uv run pytest --cov=canvod       # With coverage
```

---

### 7. pre-commit - Git Hooks

**Website:** https://pre-commit.com/

**What it does:**
- Runs checks before you commit code
- Prevents bad code from being committed
- Auto-formats code on commit

**Why we chose it:**
- **Catches issues early** - before they reach CI
- **Configurable** - run any checks you want
- **Standard tool** - widely used

**Our configuration:**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/astral-sh/uv-pre-commit
    hooks:
      - id: uv-lock  # Update lockfile
```

**Installation:**

```bash
just hooks        # Installs pre-commit hooks
# OR
uvx pre-commit install
```

Now every time you `git commit`, the hooks run automatically!

---

### 8. MyST - Documentation

**Website:** https://mystmd.org/

**What it does:**
- Modern documentation system
- **Markdown-based** (easier than reStructuredText)
- **Supports Jupyter notebooks**
- **Beautiful output**

**Why we chose it:**
- **Markdown** - easier to write than RST
- **Jupyter integration** - include notebooks
- **Modern** - better than Sphinx for new projects
- **Interactive** - live preview

**Usage:**

```bash
uv run myst        # Preview docs locally
```

---

## Tool Comparison

| Task            | Traditional     | Modern (Our Choice) |
| --------------- | --------------- | ------------------- |
| Package manager | pip             | **uv**              |
| Environment     | venv            | **uv** (built-in)   |
| Linting         | flake8 + pylint | **ruff**            |
| Formatting      | black + isort   | **ruff**            |
| Type checking   | mypy            | **ty**              |
| Building        | setuptools      | **uv_build**        |
| Task runner     | make / shell    | **just**            |
| Testing         | pytest          | **pytest** (same)   |
| Documentation   | Sphinx          | **MyST**            |

---

## The Workflow

Here's how all these tools work together:

1. **Write code** in your editor
2. **pre-commit** runs ruff and checks on commit
3. **uv** manages dependencies automatically
4. **just test** runs pytest
5. **just check** runs ruff + ty
6. **GitHub Actions** runs everything in CI
7. **uv build** creates packages
8. **MyST** generates documentation

Everything is **fast**, **integrated**, and **modern**.

---

## Learning Resources

- [uv documentation](https://docs.astral.sh/uv/)
- [ruff documentation](https://docs.astral.sh/ruff/)
- [Just manual](https://just.systems/man/en/)
- [pytest documentation](https://docs.pytest.org/)
- [MyST documentation](https://mystmd.org/)

---

## Next Steps

- [Namespace Packages](namespace-packages.md) - How `canvod.*` works
- [Development Workflow](development-workflow.md) - Day-to-day development
- [Build System](build-system.md) - How building works
