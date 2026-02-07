# Development Guide

This guide covers development workflows, tools, and practices for contributing to canvodpy.

---

## 🚀 Quick Start

### Initial Setup

```bash
# Clone and setup
git clone https://github.com/nfb2021/canvodpy.git
cd canvodpy

# Install dependencies
uv sync

# Run tests
just test

# Build documentation
just docs
```

---

## 📋 Configuration Management

### CLI Configuration Tool

canvodpy provides a configuration CLI for managing settings:

```bash
# Show all commands
canvodpy config --help

# Initialize configuration files
canvodpy config init

# View current configuration
canvodpy config show

# Validate configuration
canvodpy config validate

# Edit configuration files
canvodpy config edit processing
canvodpy config edit sites
canvodpy config edit sids
```

### First-Time Setup

**Step 1: Initialize Config Files**

```bash
uv run canvodpy config init
```

Creates:
- `config/processing.yaml` - Processing parameters
- `config/sites.yaml` - Research site definitions
- `config/sids.yaml` - Signal ID configuration

**Step 2: Configure Credentials**

Create `.env` file (never commit this!):

```bash
cp .env.example .env
```

Edit `.env` to set:
```bash
# NASA CDDIS authentication (optional)
CDDIS_MAIL=your.email@example.com

# GNSS data root directory (required)
GNSS_ROOT_DIR=/path/to/your/gnss/data
```

**Step 3: Edit Processing Configuration**

```bash
uv run canvodpy config edit processing
```

Key fields to configure:
- `metadata.author` - Your name
- `metadata.email` - Your email
- `metadata.institution` - Your institution
- `storage.stores_root_dir` - Where processed data is stored

**Step 4: Define Research Sites**

```bash
uv run canvodpy config edit sites
```

Example configuration:
```yaml
sites:
  rosalia:
    base_dir: /data/gnss/01_Rosalia
    receivers:
      reference_01:
        directory: 01_reference_01
        type: reference
        antenna_height: 2.0
      canopy_01:
        directory: 02_canopy_01
        type: canopy
        antenna_height: 15.0
    vod_analyses:
      pair_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
        canopy_height: 15.0
```

**Step 5: Validate Configuration**

```bash
uv run canvodpy config validate
```

Should show:
```
✓ Configuration is valid!
  Sites: 1
  SID mode: all
  Agency: COD
  GNSS root: /path/to/your/gnss/data
  ✓ NASA CDDIS enabled
```

### Configuration File Structure

```
your-project/
├── .env                    ← Credentials (create manually, never commit)
└── config/                 ← Created by `config init`
    ├── processing.yaml     ← Processing settings
    ├── sites.yaml          ← Site definitions
    └── sids.yaml           ← Signal ID configuration
```

**Two Configuration Systems:**

1. **Settings (Credentials) → `.env` file**
   - Used for: NASA CDDIS FTP auth, data directory paths
   - Never committed to git

2. **Configuration (Settings) → YAML files**
   - Used for: Processing params, site definitions, metadata
   - Committed to git (no secrets!)

---

## 📊 Dependency Analysis

### View Package Dependencies

**Interactive Documentation (Recommended)**

```bash
just docs
# Navigate to: Documentation > Package Dependencies
```

You'll see:
- Interactive Mermaid diagram (clickable!)
- Metrics table
- Architecture analysis
- Recommendations

**Command Line Report**

```bash
# Full metrics report
python3 scripts/analyze_dependencies.py --format report

# Just the Mermaid diagram
python3 scripts/analyze_dependencies.py --format mermaid

# Graphviz DOT format
python3 scripts/analyze_dependencies.py --format dot
```

**Using Just Commands**

```bash
# Show dependency report
just deps-report

# Generate Mermaid graph
just deps-graph

# Update documentation
just deps-update
```

### Architecture Summary

canvodpy maintains excellent package independence:

```
✅ No circular dependencies
✅ 4 packages with ZERO dependencies (57%)
✅ Only 3 total internal dependencies
✅ Maximum dependency depth: 1

Foundation (0 deps):          Consumers (1 dep):
  canvod-readers ────────────→ canvod-auxiliary
  canvod-grids ──────────────→ canvod-viz
  canvod-grids ──────────────→ canvod-store
  canvod-vod
  canvod-utils
```

Monitor regularly to maintain this architecture:
```bash
python3 scripts/analyze_dependencies.py --format report
```

---

## 🔍 Detailed Dependency Visualization

### Using pydeps

**pydeps** analyzes actual Python imports (not just pyproject.toml), showing:
1. Class-level dependencies within packages
2. Cross-package imports
3. Circular import detection

**Installation**

```bash
uv pip install pydeps
```

**Generate Internal Package Dependencies**

```bash
# For a single package
cd packages/canvod-readers
uv run pydeps canvod.readers \
  --max-bacon=2 \
  --cluster \
  -o ../../dependency-graphs/canvod-readers-internal.svg \
  --rmprefix canvod.
```

**Generate Cross-Package Dependencies**

```bash
# From root
uv run pydeps packages \
  --max-bacon=2 \
  --cluster \
  --only canvod \
  -o dependency-graphs/cross-package.svg
```

**Options:**
- `--max-bacon=2` - Only show 2 levels deep (prevents overwhelming graphs)
- `--cluster` - Group by module/subpackage
- `--rmprefix canvod.` - Simplify node labels
- `-o file.svg` - Output as SVG (scales perfectly)
- `--show-cycles` - Detect circular dependencies

**What to Look For:**

Good signs:
- ✅ Clear hierarchy (top-to-bottom flow)
- ✅ Minimal cross-cluster connections
- ✅ No circular arrows

Warning signs:
- ⚠️ Circular connections (import cycles)
- ⚠️ Dense spider webs (high coupling)
- ⚠️ Many cross-package imports (tight coupling)

**Generate All Package Graphs**

```bash
# Create output directory
mkdir -p dependency-graphs

# Generate per-package graphs
for pkg in canvod-readers canvod-auxiliary canvod-grids canvod-store canvod-utils canvod-viz canvod-vod; do
  cd packages/$pkg
  uv run pydeps canvod.${pkg#canvod-} \
    --max-bacon=2 \
    --cluster \
    --rmprefix canvod. \
    -o ../../dependency-graphs/$pkg-internal.svg
  cd ../..
done
```

**Detect Circular Imports**

```bash
uv run pydeps canvod.auxiliary --show-cycles -o cycles.svg
```

**Compare Before/After Refactoring**

```bash
# Before refactoring
uv run pydeps canvod.auxiliary -o before.svg

# ... make changes ...

# After refactoring
uv run pydeps canvod.auxiliary -o after.svg

# Compare visually
open before.svg after.svg
```

---

## 🧪 Testing

### Run Tests

```bash
# All tests
just test

# Specific package
just test-package canvod-readers

# With coverage
just test-coverage
```

### Test Organization

Tests are located in each package's `tests/` directory:
```
packages/canvod-readers/tests/
packages/canvod-auxiliary/tests/
packages/canvod-grids/tests/
...
```

### Coverage Reports

```bash
# Generate coverage report
just test-coverage

# View HTML report
open _coverage/index.html
```

Current coverage targets:
- Overall: 63%
- canvod-store: 70%
- canvod-grids: 75%
- canvod-vod: 75%
- canvod-utils: 79%

---

## 📚 Documentation

### Build Documentation

```bash
# Build and serve locally
just docs

# Or manually
uv run myst
```

View at: http://localhost:3000

### Documentation Structure

**MyST (Package Docs)**
```
packages/canvod-readers/docs/
packages/canvod-auxiliary/docs/
packages/canvod-grids/docs/
...
```

**Zensical (Umbrella Docs)**
```
canvodpy/docs/
docs/                    ← Top-level docs
docs-site/               ← Generated (DO NOT EDIT)
```

### Sync Package Docs

Package docs are synced to the main documentation site:

```bash
# Sync package docs → docs-site/
just docs-sync
```

**Important:** `docs-site/` is generated. Never edit it directly!

---

## 🔨 Just Commands

### Most Used

```bash
# Install dependencies
just install

# Run tests
just test

# Build docs
just docs

# Run all quality checks (lint + format + types)
just check
```

### Build & Release

```bash
# Build all 8 packages
just build-all

# Bump version
just bump <VERSION>

# Generate changelog
just changelog [VERSION]

# Full release workflow
just release <VERSION>
```

### Dependency Management

```bash
# Show dependency report
just deps-report

# Generate dependency graph
just deps-graph

# Update docs with dependencies
just deps-update
```

### Documentation

```bash
# Sync package docs
just docs-sync

# Build docs
just docs-build

# Serve docs
just docs-serve

# Full docs workflow
just docs
```

---

## 📦 Package Structure

canvodpy is a multi-package monorepo:

### The 8 Packages

1. **canvod-readers** - RINEX readers (foundation)
2. **canvod-auxiliary** - Auxiliary GNSS data (depends on readers)
3. **canvod-grids** - Grid implementations (foundation)
4. **canvod-store** - Icechunk storage (depends on grids)
5. **canvod-utils** - Shared utilities (foundation)
6. **canvod-viz** - Visualization (depends on grids)
7. **canvod-vod** - VOD algorithms (foundation)
8. **canvodpy** - Umbrella package (depends on all)

### Unified Versioning

All packages share the same version number for FAIR principles.

When bumping version:
```bash
just bump 0.2.0
```

This updates all 8 packages simultaneously.

---

## 🚀 Contributing Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/my-feature
```

### 2. Make Changes

Edit code in `packages/<package>/src/canvod/<package>/`

### 3. Add Tests

Add tests in `packages/<package>/tests/`

### 4. Run Quality Checks

```bash
# Run all quality checks (lint + format + types)
just check

# Run tests
just test
```

### 5. Commit with Conventional Commits

```bash
# Feature
git commit -m "feat(readers): add RINEX 4.0 support"

# Bug fix
git commit -m "fix(grids): correct equal-area cell assignment"

# Documentation
git commit -m "docs: update configuration guide"

# Refactor
git commit -m "refactor(vod): extract shared tau-omega logic"
```

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for commit message guidelines.

### 6. Push and Create PR

```bash
git push origin feature/my-feature
```

Create PR on GitHub.

---

## 🔧 Troubleshooting

### "No module named 'canvod.X'"

**Solution:** Ensure packages are installed:
```bash
uv sync
```

### "Command not found: canvodpy"

**Solution:** Use `uv run`:
```bash
uv run canvodpy config init
```

### Tests Fail After Dependency Changes

**Solution:** Re-sync dependencies:
```bash
uv sync --all-extras
```

### Documentation Build Fails

**Solution:** Sync package docs first:
```bash
just docs-sync
just docs-build
```

### pydeps Graphs Too Complex

**Solution:** Reduce scope:
```bash
# Lower bacon number
uv run pydeps canvod.auxiliary --max-bacon=1 -o output.svg

# Focus on one module
uv run pydeps canvod.auxiliary.preprocessing -o output.svg
```

---

## 📖 Additional Resources

- [Architecture Documentation](./ARCHITECTURE.md)
- [Contributing Guidelines](../../CONTRIBUTING.md)
- [Release Process](../../RELEASING.md)
- [PyPI Setup Guide](./PYPI_SETUP.md)
- [Zenodo DOI Setup](./ZENODO_SETUP.md)

---

**Happy developing! 🚀**
