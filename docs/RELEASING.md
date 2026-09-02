# Release Process

!!! warning "Maintainers only"
    This guide is for repository maintainers with push access to the main branch.

---

## Prerequisites

Before starting a release:

- [ ] All CI checks passing on `main`
- [ ] `main` branch is stable
- [ ] All changes committed and pushed
- [ ] You have push access to the repository (`main` requires a PR — see step 4 —
      but tagging in step 6 is a direct push)

---

## Release Types

| Type | Version Bump | Example | When to use |
|------|-------------|---------|-------------|
| Patch | `0.1.X` | 0.1.0 → 0.1.1 | Bug fixes only, fully backwards compatible |
| Minor | `0.X.0` | 0.1.0 → 0.2.0 | New features, backwards compatible |
| Major | `X.0.0` | 0.9.0 → 1.0.0 | Breaking changes — requires migration guide |

---

## Step-by-Step

### 1. Prepare

```bash
git checkout main
git pull origin main
just test && just check
```

### 2. Create the release

```bash
just release 0.2.0
```

This command:

1. Runs all tests
2. Generates `CHANGELOG.md` from conventional commits
3. Bumps version in all `pyproject.toml` files
4. Creates git commit + tag `v0.2.0`

### 3. Review

```bash
git log --oneline -5   # verify commit
git tag | tail -1      # verify tag
```

### 4. Open a PR for the release commit

`main` requires a PR (branch protection: `required_pull_request_reviews`,
0 approvals needed but a PR is mandatory — `enforce_admins` is off, so an
admin bypass with a direct push is *possible*, but don't: see
`canvodpy-test-data`'s #8/#9 for what happened the one time this was tried
elsewhere in this project).

**Don't push the tag yet.** A PR merge can produce a different commit SHA
than what you tagged locally (a "Merge pull request" commit, or a
squash/rebase merge) — the tag would end up pointing at an orphaned,
unreachable commit. Drop the local tag before pushing the branch:

```bash
git tag -d v0.2.0
git checkout -b chore/release-v0.2.0
git push -u origin chore/release-v0.2.0
gh pr create --title "bump: version X.Y.Z → 0.2.0" --body "..."
```

Merge the PR once CI passes.

### 5. Pull the merged commit, recreate the tag

```bash
git checkout main
git pull origin main
git tag -a "v0.2.0" -m "Release v0.2.0"
git push origin v0.2.0
```

### 6. Publish GitHub Release

The `.github/workflows/release.yml` workflow detects the new tag and creates a **draft** release. Review and publish at [github.com/nfb2021/canvodpy/releases](https://github.com/nfb2021/canvodpy/releases).

Pushing the tag does **not** publish to PyPI — tagging/versioning and PyPI
publishing are deliberately decoupled (see step 7).

### 7. Publish to PyPI (separate, manual, whenever you decide)

Not automatic. Trigger `publish_pypi.yml` explicitly, either from the
[Actions tab](https://github.com/nfb2021/canvodpy/actions/workflows/publish_pypi.yml)
("Run workflow", choosing the tag/ref to build from) or:

```bash
gh workflow run publish_pypi.yml --ref v0.2.0 -f version=0.2.0
```

You can create several tags/GitHub releases before ever running this — a
tag existing is not a promise that PyPI has it.

### 8. Post-release

- Monitor issues for regressions
- Create a Zenodo snapshot for DOI ([Zenodo Setup](guides/ZENODO_SETUP.md))
- Update citation information if needed

---

## Troubleshooting

??? failure "Tests fail during release"
    Fix the failing tests on `main` before retrying `just release`.

??? failure "Version bump fails"
    Use an explicit `X.Y.Z` format (no `v` prefix):
    ```bash
    just release 0.2.0    # correct
    just release v0.2.0   # wrong
    ```

??? failure "Tag already exists"
    ```bash
    git tag -d v0.2.0             # delete local tag
    git push origin :v0.2.0       # delete remote tag (if already pushed)
    just release 0.2.0            # recreate
    ```

??? failure "Draft release did not appear"
    Verify the tag matches the pattern `v*.*.*` at
    [github.com/nfb2021/canvodpy/actions](https://github.com/nfb2021/canvodpy/actions).
    (PyPI publishing never triggers from a tag push at all — see step 6.)

---

## Manual Release (Fallback)

```bash
just changelog v0.2.0
```

Then create a release manually at [github.com/nfb2021/canvodpy/releases/new](https://github.com/nfb2021/canvodpy/releases/new).
