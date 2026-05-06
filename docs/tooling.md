---
title: Development Tooling
description: Tools used in canVODpy development
---

# Development Tooling

canVODpy uses a modern Python toolchain built almost entirely on the [Astral](https://astral.sh/) ecosystem.

<div class="grid cards" markdown>

-   :fontawesome-solid-box: &nbsp; **uv**

    ---

    Replaces pip, venv, pip-tools, and twine in a single binary.
    Manages Python versions, virtual environments, dependency resolution,
    and builds.

    [:octicons-arrow-right-24: astral.sh/uv](https://docs.astral.sh/uv/)

-   :fontawesome-solid-broom: &nbsp; **ruff**

    ---

    Linter + formatter in one tool. Implements 700+ rules from flake8,
    pylint, black, and isort at 10–100× their speed.

    [:octicons-arrow-right-24: astral.sh/ruff](https://docs.astral.sh/ruff/)

-   :fontawesome-solid-magnifying-glass-chart: &nbsp; **ty**

    ---

    Type checker replacing mypy. Early development (alpha) but already
    significantly faster for large codebases.

-   :fontawesome-solid-list-check: &nbsp; **just**

    ---

    Task runner with simpler syntax than Make. All common development
    tasks — test, check, docs, config — are `just <command>` away.

    [:octicons-arrow-right-24: github.com/casey/just](https://github.com/casey/just)

</div>

---

## Core Tools

=== "uv — Package Manager"

    ```bash
    uv sync                  # Install all dependencies (workspace-aware)
    uv add numpy             # Add a runtime dependency
    uv add --dev pytest      # Add a dev dependency
    uv run pytest            # Run in the managed environment
    uv build                 # Build a wheel
    uv publish               # Publish to PyPI
    ```

    Configuration in `pyproject.toml`:

    ```toml
    [project]
    dependencies = ["numpy>=2.0", "xarray>=2024.0"]

    [dependency-groups]
    dev = ["pytest>=8.0", "ruff>=0.14", "ty>=0.0.1"]
    ```

=== "uv_build — Build Backend"

    Builds wheel and sdist with native namespace package support:

    ```toml
    # packages/canvod-readers/pyproject.toml
    [build-system]
    requires      = ["uv_build>=0.9.17,<0.10.0"]
    build-backend = "uv_build"

    [tool.uv.build-backend]
    module-name = "canvod.readers"   # dot → namespace package
    ```

    !!! note
        `canvod-utils` uses `hatchling` as its build backend — the only
        exception in the monorepo.

=== "ruff — Linter + Formatter"

    ```bash
    ruff check .          # Lint
    ruff check . --fix    # Lint with auto-fix
    ruff format .         # Format
    ```

    Configuration (workspace root `pyproject.toml` — inherited by all packages):

    ```toml
    [tool.ruff]
    line-length = 88
    target-version = "py314"

    [tool.ruff.lint]
    select = ["E", "F", "W", "I", "UP", "B", "RUF"]
    ```

    Philosophy: catch real bugs, enforce consistent formatting, don't fight
    scientists over naming or style. Dropped stylistic rules (N, SIM, C4, PIE, PT)
    that add noise without catching bugs.

=== "ty — Type Checker"

    ```bash
    uv run ty check packages/canvod-readers/src/canvod/readers/
    uv run ty check canvodpy/src/canvodpy/
    ```

    Configured per-package in `pyproject.toml`:

    ```toml
    [tool.ty]
    python = "3.14"
    ```

---

## Supporting Tools

=== "just — Task Runner"

    All common tasks are single commands:

    ```bash
    just test             # Run the full test suite
    just check            # Lint + format + type-check
    just hooks            # Install pre-commit hooks
    just docs             # Build and serve documentation locally
    just config-init      # Initialize YAML config from templates
    just config-validate  # Validate config files
    just --list           # Show all available commands
    ```

=== "pytest — Testing"

    ```bash
    uv run pytest                        # All tests
    uv run pytest --cov=canvod           # With coverage
    uv run pytest -m "not integration"   # Skip integration tests
    uv run pytest packages/canvod-readers/tests/
    ```

    Integration tests are marked `@pytest.mark.integration` and excluded
    from the default run.

=== "pre-commit — Git Hooks"

    ```bash
    just hooks    # Install hooks (run once after clone)
    ```

    Configured in `.pre-commit-config.yaml`:

    ```yaml
    repos:
      - repo: https://github.com/astral-sh/ruff-pre-commit
        hooks:
          - id: ruff-check
            args: [--fix]
            stages: [pre-commit]
          - id: ruff-format
            stages: [pre-commit]
      - repo: https://github.com/astral-sh/uv-pre-commit
        hooks:
          - id: uv-lock
            stages: [pre-commit]
      - repo: https://github.com/pre-commit/pre-commit-hooks
        hooks:
          - id: trailing-whitespace
          - id: check-added-large-files
          - id: detect-private-key
          - id: end-of-file-fixer
      - repo: https://github.com/commitizen-tools/commitizen
        hooks:
          - id: commitizen
            stages: [commit-msg]
    ```

    Hooks run on every `git commit` — ruff, uv-lock, and file hygiene checks run at
    the `pre-commit` stage; commitizen validates the commit message at `commit-msg`.
    Failures block the commit.

---

## Tool Comparison

| Task | Traditional stack | canVODpy |
|------|------------------|----------|
| Package management | pip | uv |
| Virtual environments | venv / virtualenv | uv (built-in) |
| Linting | flake8 + pylint | ruff |
| Formatting | black + isort | ruff |
| Type checking | mypy | ty |
| Building | setuptools | uv_build |
| Publishing | twine | uv |
| Task runner | make / tox | just |
| Documentation | Sphinx | Zensical (MkDocs) |

---

## Quality & Security

canVODpy follows FAIR software principles and OpenSSF best practices:

<div class="grid cards" markdown>

-   :fontawesome-solid-shield-halved: &nbsp; **OpenSSF Best Practices**

    ---

    Certified compliance with open source security best practices.

    **Status:** ✅ Passing level
    **Badge:** [Project 12329](https://www.bestpractices.dev/projects/12329)

    [:octicons-arrow-right-24: Application Guide](OPENSSF_BADGE_GUIDE.md)

-   :fontawesome-solid-star: &nbsp; **FAIR Software**

    ---

    Compliance with the 5 FAIR software recommendations (findable,
    accessible, interoperable, reusable).

    **Status:** 4/5 met (PyPI pending v1.0)
    **Automated:** howfairis workflow runs on every push

    [:octicons-arrow-right-24: Implementation Summary](FAIR_IMPLEMENTATION_SUMMARY.md)

-   :fontawesome-solid-chart-line: &nbsp; **OpenSSF Scorecard**

    ---

    Automated security monitoring across 18+ best practice checks.

    **Runs:** Weekly + on every push to main
    **Results:** GitHub Security tab

    [:octicons-arrow-right-24: View Scorecard](https://securityscorecards.dev/viewer/?uri=github.com/nfb2021/canvodpy)

-   :fontawesome-solid-lock: &nbsp; **Security Policy**

    ---

    Vulnerability reporting process with defined response timelines.

    **Private reporting:** GitHub Security Advisories
    **Response time:** 48 hours initial, 7-90 days fix

    [:octicons-arrow-right-24: Security Policy](SECURITY.md)

</div>

### Continuous Integration

All quality checks run automatically:

| Workflow | Runs On | Purpose |
|----------|---------|---------|
| `test_platforms.yml` | Push, PR | Multi-platform tests (Linux/macOS/Windows) |
| `test_coverage.yml` | Push, PR | Coverage tracking → Coveralls |
| `code_quality.yml` | Push | Linting, formatting, type checking |
| `audit.yml` | PR, Weekly | Integration tests with real data |
| `fair-software.yml` | Push, PR | FAIR compliance checks |
| `scorecard.yml` | Weekly, Push to main | Security best practices |

All workflows must pass before merging to `main`.

**See also:** [Security Policy](SECURITY.md) · [FAIR Compliance](FAIR_IMPLEMENTATION_SUMMARY.md)
