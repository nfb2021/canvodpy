---
title: Development Tooling
description: Tools used in canVODpy development
---

# Development Tooling

## Overview

canVODpy uses a modern Python toolchain, primarily from the [Astral](https://astral.sh/) ecosystem. This page documents each tool and its role.

## Core Tools

### uv -- Package Manager

[Documentation](https://docs.astral.sh/uv/)

uv manages Python versions, virtual environments, dependency resolution, package installation, and builds. It replaces pip, venv, pip-tools, and twine.

```bash
uv sync                    # Install dependencies
uv add numpy               # Add a dependency
uv run pytest              # Run command in the environment
uv build                   # Build the package
```

Configuration is specified in `pyproject.toml`:

```toml
[project]
dependencies = ["numpy>=1.24", "pandas>=2.0"]

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.14"]
```

### uv_build -- Build Backend

[Documentation](https://docs.astral.sh/uv/concepts/build-backend/)

uv_build creates wheel and source distributions from Python packages. It provides native support for namespace packages via the dotted `module-name` configuration.

```toml
[build-system]
requires = ["uv_build>=0.9.17,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "canvod.readers"  # Dot creates namespace package
```

Note: `canvod-utils` uses `hatchling` as its build backend instead.

### ruff -- Linter and Formatter

[Documentation](https://docs.astral.sh/ruff/)

ruff provides linting and formatting in a single tool, replacing flake8, pylint, black, and isort. It implements 700+ rules from multiple linting tools.

```bash
ruff check .          # Lint
ruff check . --fix    # Lint with auto-fix
ruff format .         # Format
```

Configuration:

```toml
[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "C4", "RUF", "PIE", "PT"]
```

### ty -- Type Checker

ty checks Python type annotations, replacing mypy. It is currently in early development (alpha).

```bash
ty check .
```

## Supporting Tools

### just -- Task Runner

[Documentation](https://github.com/casey/just)

just provides a command runner with simpler syntax than Make. It is used for all common development tasks and in CI/CD.

```bash
just test             # Run tests
just check            # Lint + format + type-check
just docs             # Build and serve documentation
just --list           # Show all available commands
```

### pytest -- Testing Framework

[Documentation](https://docs.pytest.org/)

pytest runs the test suite and generates coverage reports. Tests reside in each package's `tests/` directory.

```bash
uv run pytest                    # All tests
uv run pytest --cov=canvod       # With coverage
```

### pre-commit -- Git Hooks

[Documentation](https://pre-commit.com/)

pre-commit runs ruff and other checks automatically before each commit.

```bash
just hooks            # Install hooks
```

Configuration in `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

### MyST -- Documentation

[Documentation](https://mystmd.org/)

MyST is a Markdown-based documentation system supporting Jupyter notebooks, Mermaid diagrams, and cross-references.

```bash
uv run myst           # Preview docs locally
```

## Tool Comparison

| Task | Traditional | canVODpy |
|------|-------------|----------|
| Package management | pip | uv |
| Environments | venv | uv (built-in) |
| Linting | flake8 + pylint | ruff |
| Formatting | black + isort | ruff |
| Type checking | mypy | ty |
| Building | setuptools | uv_build |
| Task runner | make | just |
| Documentation | Sphinx | MyST |
