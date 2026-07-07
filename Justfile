# ============================================================================
# canVODpy Monorepo - Root Justfile
# ============================================================================

# Use Git Bash on Windows (installed with Git for Windows)
# Full path avoids resolving to WSL's bash on GitHub Actions runners
set windows-shell := ["C:/Program Files/Git/bin/bash.exe", "-c"]

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

# run the type checker ty (config lives in [tool.ty] in pyproject.toml)
check-types:
    uv run ty check

# lint, format and type-check (all packages)
check: check-lint check-format check-types

# ============================================================================
# Testing (All Packages)
# ============================================================================

# run tests for all packages
test:
    uv run pytest

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
    uv run pytest packages/canvod-virtualiconvname/tests/ --verbose --color=yes
    uv run pytest packages/canvod-vod/tests/ --verbose --color=yes
    uv run pytest packages/canvod-ops/tests/ --verbose --color=yes
    uv run pytest packages/canvod-store-metadata/tests/ --verbose --color=yes
    uv run pytest packages/canvod-audit/tests/ --verbose --color=yes

# run canvod-audit tests (comparison engine, tolerance checks, adapters)
test-audit:
    uv run pytest packages/canvod-audit/tests/ --verbose --color=yes

# run tests with coverage report
test-coverage:
    uv run pytest

# run all formatting, linting, and testing commands
ci PYTHON="3.13":
    uv run --python={{ PYTHON }} ruff format .
    uv run --python={{ PYTHON }} ruff check . --fix
    uv run --python={{ PYTHON }} ty check .
    uv run --python={{ PYTHON }} pytest

# ============================================================================
# Configuration
# ============================================================================

# validate canvod-settings.yaml configuration
config-validate:
    uv run canvodpy config validate

# validate data directories against naming convention (pre-flight check)
config-check-data SITE:
    uv run python -c "from canvodpy.workflows.tasks import validate_data_dirs; import json; print(json.dumps(validate_data_dirs('{{ SITE }}'), indent=2))"

# show the current configuration
config-show:
    uv run canvodpy config show

# initialize configuration from template
config-init:
    uv run canvodpy config init

# open canvod-settings.yaml in $EDITOR
config-edit:
    uv run canvodpy config edit

# ============================================================================
# Store Metadata
# ============================================================================

# show full metadata report for a store
metadata-show STORE_PATH:
    uv run python -m canvod.store_metadata.show {{ STORE_PATH }}

# show a specific metadata section (identity, creator, temporal, spatial, env, processing, summaries, validation, reproduce, uv, toml)
metadata-section STORE_PATH SECTION:
    uv run python -m canvod.store_metadata.show {{ STORE_PATH }} {{ SECTION }}

# validate store metadata against FAIR, DataCite, ACDD, STAC
metadata-validate STORE_PATH:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import read_metadata, validate_all; meta = read_metadata(Path('{{ STORE_PATH }}')); results = validate_all(meta); [print(f'{std}: {\"PASS\" if not issues else f\"{len(issues)} issues\"}') for std, issues in results.items()]; [print(f'  - {i}') for issues in results.values() for i in issues]"

# export STAC Collection JSON for a single store
metadata-stac STORE_PATH:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import write_stac_collection; p = write_stac_collection(Path('{{ STORE_PATH }}')); print(f'Written: {p}')"

# export STAC Catalog JSON for all stores under a directory
metadata-stac-catalog ROOT_DIR:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import write_stac_catalog; p = write_stac_catalog(Path('{{ ROOT_DIR }}')); print(f'Written: {p}')"

# scan a directory for stores and print inventory table
metadata-inventory ROOT_DIR:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import scan_stores; df = scan_stores(Path('{{ ROOT_DIR }}')); print(df)"

# extract pyproject.toml + uv.lock from a store for environment reproduction
metadata-extract-env STORE_PATH OUTPUT_DIR:
    uv run python -c "from pathlib import Path; from canvod.store_metadata import extract_env; p = extract_env(Path('{{ STORE_PATH }}'), Path('{{ OUTPUT_DIR }}')); print(f'Extracted to {p}. Run: cd {p} && uv sync --frozen')"

# run canvod-store-metadata tests
metadata-test:
    uv run pytest packages/canvod-store-metadata/tests/ -v

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

# install bundled Claude Code skills to ~/.claude/skills/
install-skills:
    @mkdir -p ~/.claude/skills/icechunk
    @cp .claude/skills/icechunk/SKILL.md ~/.claude/skills/icechunk/SKILL.md
    @echo "Installed: icechunk"

# ============================================================================
# uv venv and Dependency Management
# ============================================================================

venv-upgrade:
    uv lock --upgrade
    uv sync

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

# Build all packages (outputs to workspace root dist/)
build-all:
    @echo "🔨 Building all 12 packages..."
    @rm -rf dist/
    @mkdir -p dist/
    uv build --package canvod-readers --out-dir dist/
    uv build --package canvod-auxiliary --out-dir dist/
    uv build --package canvod-grids --out-dir dist/
    uv build --package canvod-store --out-dir dist/
    uv build --package canvod-store-metadata --out-dir dist/
    uv build --package canvod-utils --out-dir dist/
    uv build --package canvod-viz --out-dir dist/
    uv build --package canvod-virtualiconvname --out-dir dist/
    uv build --package canvod-vod --out-dir dist/
    uv build --package canvod-ops --out-dir dist/
    uv build --package canvod-audit --out-dir dist/
    uv build --package canvodpy --out-dir dist/
    @echo "✅ Built 12 packages to dist/"
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

# install all packages in workspace and ensure all git hooks are active
sync:
    uv sync
    uv run pre-commit install --hook-type pre-commit --hook-type commit-msg --hook-type pre-push --hook-type post-merge

# update all git submodules (demo + test_data) to their latest remote commits and record the new pointers
update-submodules:
    git submodule update --remote --merge demo
    git submodule update --remote --merge packages/canvod-readers/tests/test_data
    git add demo packages/canvod-readers/tests/test_data
    git diff --cached --quiet || git commit -m "chore: update submodule pointers (demo + test_data)"

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
# Notebooks (marimo)
# ============================================================================

# list all marimo notebooks in demo/
notebooks:
    @echo "{{ GREEN }}{{ BOLD }}Available notebooks:{{ NORMAL }}"
    @ls demo/*.py | grep -v __pycache__ | sed 's|demo/||' | sort

# open a marimo notebook for editing (e.g. just open-notebook grids_overview.py)
open-notebook NAME:
    uv run marimo edit demo/{{ NAME }}

# run a marimo notebook as a read-only app (e.g. just app-notebook grids_overview.py)
app-notebook NAME:
    uv run marimo run demo/{{ NAME }}

# start the hemisphere API server (run from repo root; see .icechunk_gridding_claude/RUNNING.md)
hemi-serve:
    CATALOG=.icechunk_gridding_claude/_out/catalog.json \
      uv run --with fastapi --with uvicorn --with xpublish \
      python .icechunk_gridding_claude/serve_hemisphere.py

# open the VOD hemisphere viewer notebook for interactive editing
hemi-view:
    uv run --with marimo --with plotly --with wigglystuff --with httpx \
      --with ipywidgets \
      marimo edit .icechunk_gridding_claude/view_vod_cube.py

# ============================================================================
# Documentation
# ============================================================================

# preview the documentation locally
docs:
    uv run zensical serve --open

# build the documentation
docs-build:
    uv run zensical build

# deploy the documentation via GitHub Actions
docs-deploy:
    gh workflow run "Deploy Docs"

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

# ============================================================================
# Danger Zone (destructive operations with confirmation)
# ============================================================================

# delete all log files
[confirm("This will delete ALL log files. Continue? (y/n)")]
danger-delete-logs:
    uv run python scripts/danger_zone.py delete-logs

# delete downloaded auxiliary data (SP3, CLK) and Zarr caches
[confirm("This will delete auxiliary data. Continue? (y/n)")]
danger-delete-aux:
    uv run python scripts/danger_zone.py delete-aux

# delete a specific Icechunk store (rinex or vod) for a site
[confirm("This will PERMANENTLY delete store data. Continue? (y/n)")]
danger-delete-store SITE STORE:
    uv run python scripts/danger_zone.py delete-store {{ SITE }} {{ STORE }}

# delete ALL Icechunk stores for a site
[confirm("This will PERMANENTLY delete ALL stores. Continue? (y/n)")]
danger-delete-all-stores SITE:
    uv run python scripts/danger_zone.py delete-all-stores {{ SITE }}

# ============================================================================
# Initialization
# ============================================================================

# initialize a git repo and add all files
init: sync
    git init --initial-branch=main
    git add .
    git commit -m "initial commit"
    @echo "{{ GREEN }}{{ BOLD }}Git has been initialized{{ NORMAL }}"
