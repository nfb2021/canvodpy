# Versioning Strategy

**Last Updated:** 2026-02-04
**Status:** Active

## Overview

canvodpy uses unified semantic versioning across all packages in the monorepo. All packages share the same version number and are released together.

## Rationale

### FAIR Principles and Scientific Reproducibility

Unified versioning supports the FAIR principles for scientific software:
- A single version number enables unambiguous citation in scientific papers
- Environment recreation requires only one version identifier
- Compatible package combinations are guaranteed by the unified release

### User Experience

A single version number simplifies usage:
- `pip install canvodpy==0.2.0` installs a known-compatible set
- Individual packages share the same version: `pip install canvod-readers==0.2.0`

### Monorepo with Sollbruchstellen

The monorepo provides modularity during development while maintaining coherence at release time:
- **Development**: Independent package development and testing
- **Release**: Coordinated releases with unified version
- **Installation**: Individual packages installable if needed

## Semantic Versioning

Following [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH
```

| Increment | Meaning | Example |
|-----------|---------|---------|
| MAJOR | Breaking API changes | 0.9.0 -> 1.0.0 |
| MINOR | New features (backward compatible) | 0.1.0 -> 0.2.0 |
| PATCH | Bug fixes (backward compatible) | 0.1.0 -> 0.1.1 |

Pre-release versions: `0.2.0-alpha.1`, `0.2.0-beta.1`, `0.2.0-rc.1`

## Version Management

### Creating a Release

```bash
just release 0.2.0    # Minor release
just release 0.1.1    # Patch release
just release 1.0.0    # Major release
```

This runs tests, generates a changelog, bumps the version in all packages, and creates a git tag.

### Manual Version Bump

```bash
just bump minor       # 0.1.0 -> 0.2.0
just bump patch       # 0.1.0 -> 0.1.1
just bump major       # 0.1.0 -> 1.0.0
```

## Version Files

All package versions are synchronized via commitizen:

```toml
[tool.commitizen]
version = "0.1.0"
version_files = [
    "canvodpy/pyproject.toml:version",
    "packages/canvod-readers/pyproject.toml:version",
    "packages/canvod-auxiliary/pyproject.toml:version",
    "packages/canvod-grids/pyproject.toml:version",
    "packages/canvod-vod/pyproject.toml:version",
    "packages/canvod-store/pyproject.toml:version",
    "packages/canvod-viz/pyproject.toml:version",
    "packages/canvod-utils/pyproject.toml:version",
]
```

## Git Tags

Tags follow the format `vMAJOR.MINOR.PATCH` (e.g., `v0.1.0`, `v1.0.0`, `v0.2.0-beta.1`).

## Deprecation Policy

1. **Version N**: Feature deprecated with warning
2. **Version N+1**: Louder warning, migration guide in docs
3. **Version N+2**: Feature removed, MAJOR version bump

## Citation

### Recommended Format

```bibtex
@software{canvodpy2026,
  author = {Bader, Nicolas and Contributors},
  title = {canvodpy: GNSS Vegetation Optical Depth Analysis},
  version = {0.2.0},
  year = {2026},
  url = {https://github.com/nfb2021/canvodpy},
  doi = {10.5281/zenodo.XXXXXXX}
}
```

### In-text

> "Analysis was performed using canvodpy v0.2.0 (Bader et al., 2026)."

## See Also

- [Semantic Versioning](https://semver.org/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [RELEASING.md](./RELEASING.md)
