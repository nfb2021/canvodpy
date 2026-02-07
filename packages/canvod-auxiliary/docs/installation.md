---
title: Installation Guide
description: How to install and set up canvod-auxiliary
---

# Installation Guide

Complete guide to installing `canvod-auxiliary` for different use cases.

## Prerequisites

### Python Version

**Required:** Python 3.13 or higher

Check your version:
```bash
python --version
# Should show: Python 3.13.x or higher
```

### Package Manager

We recommend **uv** (modern, fast) or **pip** (traditional):

**Install uv:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Or use pip** (comes with Python)

---

## Installation Methods

### Method 1: From PyPI (Recommended)

**For end users:**

```bash
# Using pip
pip install canvod-auxiliary

# Using uv
uv pip install canvod-auxiliary
```

**Verify installation:**
```bash
python -c "from canvod.auxiliary import Sp3File, ClkFile; print('✓ Works!')"
```

### Method 2: Development Install

**For contributors and developers:**

```bash
# Clone repository
git clone https://github.com/nfb2021/canvodpy.git
cd canvodpy/packages/canvod-auxiliary

# Install in editable mode
uv pip install -e .

# Or with pip
pip install -e .
```

**Verify:**
```bash
python -c "import canvod.auxiliary; print(canvod.auxiliary.__version__)"
```

### Method 3: With Development Dependencies

**For running tests and code quality checks:**

```bash
cd canvodpy/packages/canvod-auxiliary

# Install with dev dependencies
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"
```

**Includes:**
- pytest ≥8.0 (testing)
- pytest-cov ≥5.0 (coverage)
- ruff ≥0.14 (linting/formatting)
- ty ≥0.0.9 (type checking)
- marimo ≥0.9.0 (notebooks)

### Method 4: From Workspace (Monorepo Development)

**For working on multiple packages:**

```bash
# From monorepo root
cd canvodpy

# Install entire workspace
uv sync

# canvod-auxiliary is now available along with all other packages
```

---

## Dependencies

### Core Dependencies

Automatically installed with the package:

| Package | Version | Purpose |
|---------|---------|---------|
| scipy | ≥1.15.0 | Interpolation algorithms |
| numpy | ≥1.24.0 | Numerical operations |
| xarray | ≥2023.12.0 | Multi-dimensional arrays |
| pydantic | ≥2.5.0 | Data validation |
| requests | ≥2.31.0 | HTTP client |
| python-dotenv | ≥1.0.1 | Environment variables |
| retrying | ≥1.3.4 | Retry logic |
| beautifulsoup4 | ≥4.12.0 | HTML parsing |
| lxml | ≥5.3.0 | XML parsing |
| pint | ≥0.23 | Units handling |

### Optional Dependencies

**Development tools** (installed with `[dev]`):

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | ≥8.0 | Test framework |
| pytest-cov | ≥5.0 | Coverage reporting |
| ruff | ≥0.14 | Linter + formatter |
| ty | ≥0.0.9 | Type checker |
| marimo | ≥0.9.0 | Interactive notebooks |

---

## Virtual Environments

### Using uv (Recommended)

```bash
# Create project
cd my-project
uv init

# Add canvod-auxiliary
uv add canvod-auxiliary

# Install dependencies
uv sync
```

### Using venv + pip

```bash
# Create environment
python -m venv .venv

# Activate
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows

# Install
pip install canvod-auxiliary
```

### Using conda

```bash
# Create environment
conda create -n gnss python=3.13
conda activate gnss

# Install
pip install canvod-auxiliary
```

---

## Verification

### Quick Test

```python
from canvod.auxiliary import Sp3File, ClkFile, AuxDataPipeline
from canvod.auxiliary._internal import UREG, YYYYDOY, get_logger

print("✓ All imports successful!")
```

### Run Test Suite

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Expected output:
# ===== 65 passed in 0.5s =====
```

### Check Version

```python
import canvod.auxiliary
print(canvod.auxiliary.__version__)  # Should show: 0.1.0
```

---

## Troubleshooting

### Import Errors

**Problem:**
```
ModuleNotFoundError: No module named 'canvod'
```

**Solutions:**
1. Verify installation:
   ```bash
   pip list | grep canvod
   ```

2. Check Python version:
   ```bash
   python --version  # Must be 3.13+
   ```

3. Reinstall:
   ```bash
   pip install --force-reinstall canvod-auxiliary
   ```

### Dependency Conflicts

**Problem:**
```
ERROR: Cannot install canvod-auxiliary due to dependency conflicts
```

**Solutions:**
1. Use virtual environment (recommended)
2. Update pip:
   ```bash
   pip install --upgrade pip
   ```
3. Install specific versions:
   ```bash
   pip install canvod-auxiliary==0.1.0
   ```

### Permission Errors

**Problem:**
```
PermissionError: [Errno 13] Permission denied
```

**Solutions:**
1. Use virtual environment (recommended)
2. Or install for user only:
   ```bash
   pip install --user canvod-auxiliary
   ```

### Network Issues (FTP/HTTPS)

**Problem:**
FTP downloads fail or timeout

**Solutions:**
1. Check internet connection
2. Configure NASA CDDIS authentication:
   ```bash
   # Set environment variable
   export CDDIS_MAIL="your@email.com"
   ```
3. Use alternative FTP server:
   ```python
   pipeline = AuxDataPipeline(
       ftp_server="ftp://gssc.esa.int/gnss"
   )
   ```

---

## Platform-Specific Notes

### macOS

```bash
# Install uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or use Homebrew
brew install uv

# Install canvod-auxiliary
uv pip install canvod-auxiliary
```

### Linux

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or use distribution package manager
# Ubuntu/Debian:
sudo apt install python3-pip
pip install canvod-auxiliary
```

### Windows

```bash
# Install uv (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex

# Or use pip
pip install canvod-auxiliary
```

---

## Docker

### Dockerfile Example

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install canvod-auxiliary
RUN uv pip install canvod-auxiliary

# Copy your application
COPY . .

CMD ["python", "your_script.py"]
```

### Build and Run

```bash
docker build -t my-gnss-app .
docker run my-gnss-app
```

---

## Next Steps

**Installation complete!** Now:

1. 🚀 **[Quick Start Tutorial →](quickstart.md)** - Your first 5 minutes
2. 📖 **[Architecture Overview →](architecture.md)** - Understand the design
3. 💡 **[Examples →](examples/basic.md)** - See practical code

---

## Getting Help

**Issues during installation?**

- 📖 Read [Troubleshooting](#troubleshooting) section above
- 🐛 Open a [GitHub Issue](https://github.com/nfb2021/canvodpy/issues)
- 💬 Ask in [Discussions](https://github.com/nfb2021/canvodpy/discussions)

---

*Last updated: January 2025*
