# Development Guide

## Initial Setup

```bash
git clone https://github.com/nfb2021/canvodpy.git
cd canvodpy
uv sync
just test
```

## Prerequisites

Two external tools are required:

1. **uv** -- Python package manager ([installation](https://docs.astral.sh/uv/getting-started/installation/))
2. **just** -- Command runner ([installation](https://github.com/casey/just))

Verify installation:

```bash
just check-dev-tools
```

## Configuration Management

### CLI Configuration Tool

```bash
canvodpy config init         # Initialize configuration files
canvodpy config show         # View current settings
canvodpy config validate     # Validate configuration
canvodpy config edit processing  # Edit processing config
```

### First-Time Setup

1. Initialize config files: `uv run canvodpy config init`
2. Create `.env` with credentials (never commit):
   ```bash
   CDDIS_MAIL=your.email@example.com
   GNSS_ROOT_DIR=/path/to/gnss/data
   ```
3. Edit processing configuration: `uv run canvodpy config edit processing`
4. Define research sites: `uv run canvodpy config edit sites`
5. Validate: `uv run canvodpy config validate`

## Testing

```bash
just test                    # All tests
just test-package canvod-readers  # Specific package
just test-coverage           # With coverage report
```

Tests are located in each package's `tests/` directory.

## Code Quality

```bash
just check                   # Lint + format + type-check
just check-lint              # Linting only
just check-format            # Formatting only
```

Tools used:
- **ruff**: Linting and formatting
- **ty**: Type checking
- **pytest**: Testing with coverage

## Documentation

```bash
just docs                    # Build and serve locally
```

Documentation is built with MyST/Zensical and served at http://localhost:3000.

## Dependency Analysis

```bash
just deps-report             # Full metrics report
just deps-graph              # Mermaid dependency graph
```

Architecture summary:
```
Foundation (0 deps):          Consumers (1 dep):
  canvod-readers              canvod-auxiliary -> canvod-readers
  canvod-grids                canvod-viz -> canvod-grids
  canvod-vod                  canvod-store -> canvod-grids
  canvod-utils
```

## Contributing Workflow

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make changes in `packages/<package>/src/canvod/<package>/`
3. Add tests in `packages/<package>/tests/`
4. Run quality checks: `just check && just test`
5. Commit with conventional commits:
   ```bash
   git commit -m "feat(readers): add RINEX 4.0 support"
   ```
6. Push and create PR: `git push origin feature/my-feature`

### Conventional Commit Scopes

`readers`, `aux`, `grids`, `vod`, `store`, `viz`, `utils`, `docs`, `ci`, `deps`

## Common Just Commands

```bash
just                         # List all commands
just check                   # Lint + format + type-check
just test                    # Run all tests
just sync                    # Install/update dependencies
just clean                   # Remove build artifacts
just hooks                   # Install pre-commit hooks
just docs                    # Preview documentation
just build-all               # Build all packages
just release <VERSION>       # Full release workflow
```

## Troubleshooting

**"No module named 'canvod.X'"**: Run `uv sync` to install packages.

**"Command not found: canvodpy"**: Use `uv run canvodpy config init`.

**Tests fail after dependency changes**: Run `uv sync --all-extras`.
