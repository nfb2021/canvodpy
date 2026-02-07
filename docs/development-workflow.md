---
title: Development Workflow
description: Day-to-day development in the canVODpy monorepo
---

# Development Workflow

This guide explains how to work effectively in the canVODpy monorepo, from setup to publishing.

## Initial Setup

### 1. Clone the Repository

```bash
git clone https://github.com/nfb2021/canvodpy.git
cd canvodpy
```

### 2. Install Dependencies

```bash
# Install all packages in the workspace
uv sync

# This creates .venv/ and installs everything
```

**What happens:**
- uv reads `pyproject.toml` (workspace root)
- uv reads all package `pyproject.toml` files
- uv resolves all dependencies together
- uv creates a virtual environment (`.venv/`)
- uv installs all packages in editable mode
- Creates/updates `uv.lock` with exact versions

### 3. Install Pre-commit Hooks

```bash
just hooks
# OR
uvx pre-commit install
```

This ensures code quality checks run automatically before each commit.

---

## Daily Development

### Understanding the Workspace

In a monorepo workspace:
- **One virtual environment** (`.venv/`) shared by all packages
- **One lockfile** (`uv.lock`) for all dependencies
- **Editable installs**: Changes to any package immediately affect others

```
canvodpy/
├── .venv/                  # Shared virtual environment
├── uv.lock                 # Shared lockfile
└── packages/               # Your packages
    ├── canvod-readers/
    └── canvod-auxiliary/
```

### Activating the Environment

**Option 1: Use `uv run`** (recommended)
```bash
uv run python script.py
uv run pytest
uv run ruff check .
```

**Option 2: Activate manually**
```bash
source .venv/bin/activate    # Linux/Mac
# OR
.venv\Scripts\activate       # Windows

# Now you can use commands directly
python script.py
pytest
```

---

## Working on a Package

### Example: Adding a Feature to canvod-readers

#### 1. Navigate to the package

```bash
cd packages/canvod-readers
```

#### 2. Create a new module

```bash
# Create a new Python file
touch src/canvod/readers/rinex_v4.py
```

#### 3. Write code

```python
# src/canvod/readers/rinex_v4.py
"""RINEX version 4 reader."""

class Rnxv4Obs:
    """Read RINEX 4 observation files."""

    def __init__(self, filepath: str):
        self.filepath = filepath

    def read(self) -> dict:
        """Read the file and return data."""
        # Implementation here
        pass
```

#### 4. Update `__init__.py`

```python
# src/canvod/readers/__init__.py
"""GNSS data format readers."""

from canvod.readers.rinex_v3 import Rnxv3Obs
from canvod.readers.rinex_v4 import Rnxv4Obs  # Add new import

__all__ = ["Rnxv3Obs", "Rnxv4Obs"]
```

#### 5. Write tests

```python
# tests/test_rinex_v4.py
from canvod.readers import Rnxv4Obs

def test_rnxv4_creation():
    """Test that Rnxv4Obs can be created."""
    reader = Rnxv4Obs("test.rnx")
    assert reader is not None
    assert reader.filepath == "test.rnx"
```

#### 6. Run tests

```bash
# From package directory
just test

# OR from workspace root
just test-package canvod-readers

# OR run specific test
uv run pytest tests/test_rinex_v4.py
```

#### 7. Check code quality

```bash
# Format, lint, and type check
just check

# OR individually
uv run ruff format .
uv run ruff check . --fix
uv run ty check
```

#### 8. Commit your changes

```bash
git add .
git commit -m "Add RINEX v4 reader"

# Pre-commit hooks run automatically:
# - ruff format
# - ruff check --fix
# - uv lock (updates lockfile)
```

---

## Working Across Packages

### Scenario: canvod-grids needs new features from canvod-readers

Because packages are installed in **editable mode**, changes propagate immediately.

#### 1. Add feature to canvod-readers

```python
# packages/canvod-readers/src/canvod/readers/utils.py
def parse_metadata(file):
    """Parse RINEX metadata."""
    return {"version": "4.0", "interval": 30}
```

#### 2. Use it immediately in canvod-grids

```python
# packages/canvod-grids/src/canvod/grids/loader.py
from canvod.readers.utils import parse_metadata  # Works instantly!

def load_grid(rinex_file):
    metadata = parse_metadata(rinex_file)
    # ... use metadata
```

**No reinstalling needed!** Editable mode means Python loads code directly from source.

---

## Adding Dependencies

### To a Specific Package

```bash
# Navigate to the package
cd packages/canvod-readers

# Add dependency
uv add numpy pandas

# This updates:
# - packages/canvod-readers/pyproject.toml (adds numpy, pandas)
# - uv.lock (locks versions for entire workspace)
```

### To Development Dependencies

```bash
# Add dev dependencies (for testing, linting, etc.)
cd packages/canvod-readers
uv add --group dev pytest-mock ipython
```

### To Workspace Root

```bash
# Dependencies needed by ALL packages
cd ~/path/to/canvodpy
uv add --group dev ruff ty pytest
```

---

## Testing Strategies

### Test a Single Package

```bash
cd packages/canvod-readers
just test

# OR from root
just test-package canvod-readers
```

### Test All Packages

```bash
# From workspace root
just test
```

### Test with Coverage

```bash
uv run pytest --cov=canvod.readers --cov-report=html
# Opens htmlcov/index.html in browser
```

### Test Specific Features

```bash
# Run tests matching a pattern
uv run pytest -k "rinex"

# Run specific test file
uv run pytest tests/test_rinex_v4.py

# Run specific test function
uv run pytest tests/test_rinex_v4.py::test_rnxv4_creation
```

---

## Code Quality Workflow

### Manual Checks

```bash
# From any package or root
just check

# This runs:
# 1. ruff format .    (format code)
# 2. ruff check . --fix (lint and auto-fix)
# 3. ty check         (type check)
```

### Pre-commit (Automatic)

When you commit, pre-commit hooks run automatically:

```bash
git commit -m "Add feature"

# Runs automatically:
# - ruff format
# - ruff check --fix
# - uv lock update

# If checks fail, commit is rejected
# Fix the issues and commit again
```

### CI/CD (GitHub Actions)

On every push, GitHub Actions runs:

1. **Code Quality** (`.github/workflows/code_quality.yml`):

   - Lock file check
   - Linting
   - Formatting
   - Type checking

2. **Test Coverage** (`.github/workflows/test_coverage.yml`):

   - Run tests
   - Generate coverage report
   - Post coverage comment on PR

3. **Multi-platform Tests** (`.github/workflows/test_platforms.yml`):

   - Test on Ubuntu, Windows, macOS
   - Test on Python 3.13

---

## Building Packages

### Build a Single Package

```bash
# From the repository root:
just build-package canvod-readers

# Creates:
# dist/canvod_readers-0.1.0-py3-none-any.whl
# dist/canvod_readers-0.1.0.tar.gz
```

### Build All Packages

```bash
# From workspace root
just dist

# OR manually
for pkg in packages/*/; do
  cd "$pkg"
  uv build
  cd ../..
done
```

### Verify Build

```bash
# Check wheel contents
unzip -l dist/canvod_readers-0.1.0-py3-none-any.whl

# Should see:
# canvod/readers/__init__.py
# canvod/readers/rinex_v3.py
# ... etc
```

---

## Version Management

### Bump Version

```bash
# From workspace root
just bump patch    # 0.1.0 → 0.1.1
just bump minor    # 0.1.0 → 0.2.0
just bump major    # 0.1.0 → 1.0.0

# This:
# 1. Updates pyproject.toml
# 2. Updates uv.lock
# 3. Creates git commit
# 4. Creates git tag
```

### Manual Version Update

```toml
# packages/canvod-readers/pyproject.toml
[project]
name = "canvod-readers"
version = "0.2.0"  # ← Change this
```

Then:
```bash
uv lock  # Update lockfile
git commit -am "Bump canvod-readers to 0.2.0"
git tag v0.2.0
```

---

## Common Tasks

### Adding a New Package to the Workspace

```bash
# 1. Create package structure
mkdir -p packages/canvod-newpackage/src/canvod/newpackage
mkdir -p packages/canvod-newpackage/tests
mkdir -p packages/canvod-newpackage/docs

# 2. Create pyproject.toml
cat > packages/canvod-newpackage/pyproject.toml << 'EOF'
[project]
name = "canvod-newpackage"
version = "0.1.0"
description = "New package description"
requires-python = ">=3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.newpackage"
EOF

# 3. Create __init__.py
echo '"""New package."""' > packages/canvod-newpackage/src/canvod/newpackage/__init__.py

# 4. Sync workspace
uv sync

# 5. Verify
python -c "from canvod.newpackage import *"
```

### Cleaning Build Artifacts

```bash
# From workspace root
just clean

# This removes:
# - build/
# - dist/
# - *.egg-info
# - __pycache__
# - .pytest_cache
# - .coverage
```

### Updating Dependencies

```bash
# Update all dependencies to latest compatible versions
uv lock --upgrade

# Update specific package
uv lock --upgrade-package numpy
```

---

## Troubleshooting

### "Module not found" after adding new code

**Problem:** Python can't find your new module.

**Solution:** Make sure package is installed in editable mode:
```bash
uv sync  # Reinstalls all packages
```

### "Lock file out of date"

**Problem:** `uv.lock` doesn't match `pyproject.toml`.

**Solution:**
```bash
uv lock  # Regenerate lockfile
```

### Pre-commit hooks fail

**Problem:** Code doesn't pass quality checks.

**Solution:**
```bash
# Run checks manually to see errors
just check

# Fix issues
uv run ruff check . --fix
uv run ruff format .

# Try commit again
git commit -m "..."
```

### Import errors between packages

**Problem:** Package A can't import from Package B.

**Solution:**
1. Check Package B is a dependency of Package A:
```toml
# packages/canvod-grids/pyproject.toml
[project]
dependencies = [
    "canvod-readers",  # ← Must be listed
]
```

2. Run `uv sync` to install dependencies

---

## Best Practices

### 1. Always Run Tests Before Committing

```bash
just test && just check
git commit -m "..."
```

### 2. Keep Packages Focused

Each package should have a **single, clear responsibility**:
- ✓ `canvod-readers`: Read GNSS data
- ✗ `canvod-readers`: Read data + process + visualize (too much)

### 3. Document New Features

Add docstrings to all public functions:
```python
def parse_rinex(filepath: str) -> dict:
    """Parse a RINEX observation file.

    Args:
        filepath: Path to RINEX file

    Returns:
        Dictionary containing observations

    Raises:
        FileNotFoundError: If file doesn't exist
    """
```

### 4. Write Tests for New Features

Every new feature needs tests:
```python
def test_new_feature():
    """Test that new feature works."""
    result = new_feature()
    assert result == expected
```

### 5. Use Type Hints

```python
# Good
def process(data: dict) -> list[str]:
    ...

# Bad
def process(data):
    ...
```

---

## Workflow Summary

**Daily development cycle:**

1. `git checkout -b feature-branch`
2. Make changes to code
3. `just test` (run tests)
4. `just check` (code quality)
5. `git commit -m "..."` (pre-commit runs automatically)
6. `git push`
7. Create pull request
8. GitHub Actions run CI
9. Merge when green ✓

**Key commands to remember:**

```bash
uv sync          # Install/update dependencies
just test        # Run tests
just check       # Check code quality
just clean       # Clean artifacts
just hooks       # Install pre-commit
```

---

## Next Steps

- [Architecture](architecture.md) - Understanding the project structure
- [Tooling](tooling.md) - Deep dive into tools
- [Build System](build-system.md) - How packages are built
