# Release Process

**Last Updated:** 2026-02-04
**Audience:** Maintainers

## Prerequisites

- All CI checks passing
- Main branch is stable
- Push access to the repository
- All changes committed and pushed

## Release Types

| Type | Version Bump | Example | Description |
|------|-------------|---------|-------------|
| Patch | 0.1.X | 0.1.0 -> 0.1.1 | Bug fixes only, backward compatible |
| Minor | 0.X.0 | 0.1.0 -> 0.2.0 | New features, backward compatible |
| Major | X.0.0 | 0.9.0 -> 1.0.0 | Breaking changes, requires migration guide |

## Step-by-Step Process

### 1. Prepare

```bash
git checkout main
git pull origin main
just test
just check
```

### 2. Create Release

```bash
just release 0.2.0
```

This command:
1. Runs all tests
2. Generates CHANGELOG.md from commits
3. Bumps version in all packages
4. Creates git tag `vX.Y.Z`
5. Commits changes

### 3. Review

```bash
git log --oneline -5
git tag | tail -1
```

### 4. Push

```bash
git push origin main
git push origin --tags
```

### 5. Publish GitHub Release

The `.github/workflows/release.yml` workflow detects the new tag and creates a draft release. Review and publish at https://github.com/nfb2021/canvodpy/releases.

### 6. PyPI Publishing (Future)

Once configured, publishing the GitHub release triggers PyPI upload.

## Troubleshooting

**Tests fail during release**: Fix failing tests before retrying.

**Version bump fails**: Use explicit `X.Y.Z` format without `v` prefix.

**Tag already exists**: Delete with `git tag -d v0.2.0` and recreate.

**Workflow did not trigger**: Verify tag matches pattern `v*.*.*` at https://github.com/nfb2021/canvodpy/actions.

## Manual Release (Fallback)

```bash
just changelog v0.2.0
```

Then create a release manually at https://github.com/nfb2021/canvodpy/releases/new.

## Post-Release

- Monitor for issues related to the new release
- Create Zenodo snapshot for DOI (optional)
- Update citation information

## See Also

- [VERSIONING.md](./VERSIONING.md)
- [CONTRIBUTING.md](./CONTRIBUTING.md)
