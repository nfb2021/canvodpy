# ============================================================================
# canVODpy Monorepo - Root Justfile
# ============================================================================

# ANSI color codes
GREEN := '\033[0;32m'
BOLD := '\033[1m'
NORMAL := '\033[0m'

# Default command lists all available recipes
_default:
    @just --list --unsorted

alias c := clean
alias d := dist
alias h := hooks
alias q := check
alias t := test

# ============================================================================
# Code Quality (All Packages)
# ============================================================================

# check uv.lock is up to date
check-lock:
    uv lock --check

# lint python code using ruff
[private]
check-lint:
    uv run ruff check . --fix

# lint python code without auto-fixing (for CI)
check-lint-only:
    uv run ruff check .

# format python code using ruff
[private]
check-format:
    uv run ruff format .

# check formatting without modifying files (for CI)
check-format-only:
    uv run ruff format --check . --exclude "*.ipynb"

# run the type checker ty
[private]
check-types:
    uv run ty check

# lint, format with ruff and type-check with ty (all packages)
check: check-lint check-format check-types

# ============================================================================
# Testing (All Packages)
# ============================================================================

# run tests with coverage for all packages
test:
    uv run pytest tests/

# run tests for all supported Python versions
testall:
    uv run --python=3.13 pytest

# run tests per package to avoid namespace collisions (for CI)
test-all-packages:
    @echo "Running tests per package to avoid namespace collisions..."
    uv run pytest canvodpy/tests/ --verbose --color=yes
    uv run pytest packages/canvod-auxiliary/tests/ --verbose --color=yes
    uv run pytest packages/canvod-readers/tests/ --verbose --color=yes
    uv run pytest packages/canvod-store/tests/ --verbose --color=yes
    uv run pytest packages/canvod-grids/tests/ --verbose --color=yes
    uv run pytest packages/canvod-viz/tests/ --verbose --color=yes
    uv run pytest packages/canvod-vod/tests/ --verbose --color=yes

# run tests with coverage report
test-coverage:
    uv run pytest --verbose --color=yes \
      --cov=canvodpy \
      --cov=canvod \
      --cov-report=term-missing

# run all formatting, linting, and testing commands
ci PYTHON="3.13":
    uv run --python={{ PYTHON }} ruff format .
    uv run --python={{ PYTHON }} ruff check . --fix
    uv run --python={{ PYTHON }} ty check .
    uv run --python={{ PYTHON }} pytest tests/

# ============================================================================
# Utilities
# ============================================================================

# check if required development tools are installed
check-dev-tools:
    @bash scripts/check_dev_tools.sh

# setup the pre-commit hooks
hooks:
    uvx pre-commit install
    uvx pre-commit install --hook-type commit-msg

# ============================================================================
# Release Management
# ============================================================================

# generate CHANGELOG.md from git commits (VERSION can be "auto" or specific like "v0.2.0")
changelog VERSION="auto":
    uvx git-changelog -Tio CHANGELOG.md -B="{{VERSION}}" -c angular

# bump version across all packages (major, minor, patch, or explicit like 0.2.0)
bump VERSION:
    @echo "{{GREEN}}{{BOLD}}Bumping all packages to {{VERSION}}{{NORMAL}}"
    uv run cz bump --increment {{VERSION}} --yes
    uv lock
    @echo "{{GREEN}}Version bumped to $(uv version --short){{NORMAL}}"

# bump a single package version (for testing/development only)
[private]
bump-package PKG VERSION:
    @echo "{{GREEN}}Bumping {{PKG}} to {{VERSION}}{{NORMAL}}"
    cd packages/{{PKG}} && uv version {{VERSION}}
    uv lock
    @echo "{{GREEN}}{{PKG}} bumped to {{VERSION}}{{NORMAL}}"

# create a new release (runs tests, updates changelog, bumps version, tags)
release VERSION: test
    @echo "{{GREEN}}{{BOLD}}Creating release {{VERSION}}{{NORMAL}}"
    @just changelog "v{{VERSION}}"
    git add CHANGELOG.md
    git commit -m "chore: update changelog for v{{VERSION}}"
    @just bump {{VERSION}}
    git add .
    git commit -m "chore: bump version to {{VERSION}}"
    git tag -a "v{{VERSION}}" -m "Release v{{VERSION}}"
    @echo ""
    @echo "{{GREEN}}{{BOLD}}✅ Release v{{VERSION}} created!{{NORMAL}}"
    @echo ""
    @echo "Next steps:"
    @echo "  1. Review the commits and tag"
    @echo "  2. Push with: git push && git push --tags"
    @echo "  3. GitHub Actions will create the release draft"

# ============================================================================
# Build & Publish Recipes
# ============================================================================

# Build all 8 packages (outputs to workspace root dist/)
build-all:
    @echo "🔨 Building all 8 packages..."
    @rm -rf dist/
    @mkdir -p dist/
    cd packages/canvod-readers && uv build
    cd packages/canvod-auxiliary && uv build
    cd packages/canvod-grids && uv build
    cd packages/canvod-store && uv build
    cd packages/canvod-utils && uv build
    cd packages/canvod-viz && uv build
    cd packages/canvod-vod && uv build
    cd canvodpy && uv build
    @echo "✅ Built 8 packages to dist/"
    @ls -lh dist/*.whl

# Publish all packages to TestPyPI (requires credentials)
publish-testpypi:
    @echo "📦 Publishing to TestPyPI..."
    @if [ ! -d "dist" ] || [ -z "$$(ls -A dist)" ]; then \
        echo "❌ No dist/ found. Run 'just build-all' first"; \
        exit 1; \
    fi
    uv tool run twine upload --repository testpypi dist/*
    @echo "✅ Published to https://test.pypi.org"

# Publish all packages to PyPI (requires credentials or OIDC)
publish-pypi:
    @echo "📦 Publishing to PyPI..."
    @if [ ! -d "dist" ] || [ -z "$$(ls -A dist)" ]; then \
        echo "❌ No dist/ found. Run 'just build-all' first"; \
        exit 1; \
    fi
    uv tool run twine upload dist/*
    @echo "✅ Published to https://pypi.org"

# print the current status of the project
status:
    @echo "canVODpy Monorepo"
    @echo "Running on: `uname`"

# clean all python build/compilation files and directories
clean: clean-build clean-pyc clean-test

# remove build artifacts
[private]
clean-build:
    rm -fr build/
    rm -fr _build/
    rm -fr dist/
    rm -fr .eggs/
    find . -name '*.egg-info' -exec rm -fr {} +
    find . -name '*.egg' -exec rm -f {} +

# remove Python file artifacts
[private]
clean-pyc:
    find . -name '*.pyc' -exec rm -f {} +
    find . -name '*.pyo' -exec rm -f {} +
    find . -name '*~' -exec rm -f {} +
    find . -name '__pycache__' -exec rm -fr {} +

# remove test and coverage artifacts
[private]
clean-test:
    rm -f .coverage
    rm -fr htmlcov/
    rm -fr .pytest_cache

# install all packages in workspace
sync:
    uv sync

# ============================================================================
# Version Management
# ============================================================================
# Note: Version management should be done at the package level
# Use: just build-package <package-name>
# Workspace root does not have a version

# [confirm("Do you really want to bump? (y/n)")]
# [private]
# prompt-confirm:

# bump the version, commit and add a tag <major|minor|patch|...>
# bump INCREMENT="patch": && tag
#     @uv version --bump {{ INCREMENT }} --dry-run
#     @just prompt-confirm
#     uv version --bump {{ INCREMENT }}

# tag the latest version
# tag VERSION=`uv version --short`:
#     git add pyproject.toml
#     git add uv.lock
#     git commit -m "Bumped version to {{VERSION}}"
#     git tag -a "v{{VERSION}}"
#     @echo "{{ GREEN }}{{ BOLD }}Version has been bumped to {{VERSION}}.{{ NORMAL }}"

# ============================================================================
# Building & Distribution
# ============================================================================

# build the source distribution and wheel file
dist:
    uv build

# ============================================================================
# Per-Package Commands
# ============================================================================

# run check for a specific package
check-package PACKAGE:
    cd packages/{{PACKAGE}} && uv run ruff check . --fix && uv run ruff format . && uv run ty check

# run tests for a specific package
test-package PACKAGE:
    cd packages/{{PACKAGE}} && uv run pytest

# build a specific package
build-package PACKAGE:
    cd packages/{{PACKAGE}} && uv build

# ============================================================================
# Documentation
# ============================================================================

# preview the documentation locally
docs:
    uv run zensical serve --open

# build the documentation
docs-build:
    uv run zensical build

# ============================================================================
# Dependency Analysis
# ============================================================================

# generate ALL dependency graphs (per-package + cross-package + API) using pydeps
deps-all:
    @echo "{{ GREEN }}{{ BOLD }}Generating comprehensive dependency graphs...{{ NORMAL }}"
    @python3 scripts/generate_all_graphs.py --type all --open
    @echo "{{ GREEN }}{{ BOLD }}✨ Open dependency-graphs/index.html to view all graphs{{ NORMAL }}"

# generate internal dependency graph for specific package
deps-package PACKAGE:
    @python3 scripts/generate_all_graphs.py --type internal --package {{PACKAGE}}
    @echo "{{ GREEN }}{{ BOLD }}✅ Created dependency-graphs/{{PACKAGE}}-internal.svg{{ NORMAL }}"

# generate cross-package dependency graph
deps-cross:
    @python3 scripts/generate_all_graphs.py --type cross-package
    @echo "{{ GREEN }}{{ BOLD }}✅ Created dependency-graphs/cross-package-dependencies.svg{{ NORMAL }}"

# generate API orchestration graph (how umbrella uses everything)
deps-api:
    @python3 scripts/generate_all_graphs.py --type api
    @echo "{{ GREEN }}{{ BOLD }}✅ Created dependency-graphs/api-orchestration.svg{{ NORMAL }}"

# quick dependency overview (package-level metrics)
deps-report:
    @python3 scripts/analyze_dependencies.py --format report

# generate dependency graph (Mermaid format)
deps-mermaid:
    python3 scripts/analyze_dependencies.py --format mermaid

# ============================================================================
# Initialization
# ============================================================================

# initialize a git repo and add all files
init: sync
    git init --initial-branch=main
    git add .
    git commit -m "initial commit"
    @echo "{{ GREEN }}{{ BOLD }}Git has been initialized{{ NORMAL }}"
