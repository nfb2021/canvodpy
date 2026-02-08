## Overview: Multi-Package Monorepo Publishing

This monorepo publishes **8 separate packages** to PyPI:

**Individual packages:**
1. `canvod-readers` - GNSS data readers
2. `canvod-auxiliary` - Auxiliary data handling
3. `canvod-grids` - Grid operations
4. `canvod-store` - Storage backends
5. `canvod-utils` - Utility functions
6. `canvod-viz` - Visualization tools
7. `canvod-vod` - VOD calculation

**Umbrella package:**
8. `canvodpy` - Depends on all 7 above

**User experience:**
```bash
pip install canvodpy  # Gets all 8 packages automatically
```

---

## Quick Commands

```bash
# Build all 8 packages locally
just build-all

# Manual publish to TestPyPI (requires credentials)
just publish-testpypi

# Manual publish to PyPI (requires credentials)
just publish-pypi

# Automated publish (beta) - triggers workflow
git tag v0.1.0-beta.1 && git push --tags

# Automated publish (production) - triggers workflow
git tag v0.1.0 && git push --tags
```

---

## Phase 1: TestPyPI Setup (Completed)

### Step 1: Create TestPyPI Account (Done)

Already done! Account created at https://test.pypi.org

### Step 2: Manual First Publish (Done)

Already completed with `twine upload --repository testpypi dist/*`

All 8 packages published:
- https://test.pypi.org/project/canvod-readers/
- https://test.pypi.org/project/canvod-auxiliary/
- https://test.pypi.org/project/canvod-grids/
- https://test.pypi.org/project/canvod-store/
- https://test.pypi.org/project/canvod-utils/
- https://test.pypi.org/project/canvod-viz/
- https://test.pypi.org/project/canvod-vod/
- https://test.pypi.org/project/canvodpy/

### Step 3: Set Up OIDC Automation (Done)

**3.1: Create GitHub Environment**

1. Go to: https://github.com/nfb2021/canvodpy/settings/environments
2. Click "New environment"
3. Name: `testpypi`
4. Save

**3.2: Register Trusted Publishers (FOR EACH OF 8 PACKAGES)**

For each package, go to its publishing settings:
- https://test.pypi.org/manage/project/canvod-readers/settings/publishing/
- https://test.pypi.org/manage/project/canvod-auxiliary/settings/publishing/
- https://test.pypi.org/manage/project/canvod-grids/settings/publishing/
- https://test.pypi.org/manage/project/canvod-store/settings/publishing/
- https://test.pypi.org/manage/project/canvod-utils/settings/publishing/
- https://test.pypi.org/manage/project/canvod-viz/settings/publishing/
- https://test.pypi.org/manage/project/canvod-vod/settings/publishing/
- https://test.pypi.org/manage/project/canvodpy/settings/publishing/

On each page:
1. Click "Add a new publisher"
2. Select "GitHub"
3. Fill in:
   - Owner: `nfb2021`
   - Repository: `canvodpy`
   - Workflow: `publish_testpypi.yml`
   - Environment: `testpypi`
4. Click "Add"

**3.3: Test OIDC Publishing**

```bash
git tag v0.1.0-beta.1 -m "Test OIDC"
git push --tags
cd /path/to/canvodpy
uv build
```

**Upload manually (first time only):**
```bash
uvx twine upload --repository testpypi dist/*
```

**When prompted:**
```
username: your_testpypi_username
password: your_testpypi_password
```

**Success looks like:**
```
Uploading canvodpy-0.1.0-py3-none-any.whl
100% ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Verify it's there:**
- Go to: https://test.pypi.org/project/canvodpy/

### Step 3: Configure OIDC on TestPyPI

1. **Go to project settings:**
   - https://test.pypi.org/manage/project/canvodpy/settings/publishing/

2. **Scroll to "Publishing"**

3. **Click "Add a new publisher"**

4. **Fill in the form:**
   ```
   PyPI project name:     canvodpy
   Owner:                 nfb2021
   Repository name:       canvodpy
   Workflow name:         publish_testpypi.yml
   Environment name:      test-release
   ```

5. **Click "Add"**

6. **You should see:**
   ```
   ✓ Trusted publisher added

   Publisher:
   - Repository: nfb2021/canvodpy
   - Workflow: publish_testpypi.yml
   - Environment: test-release
   ```

### Step 4: Create GitHub Environment

1. **Go to your repo:**
   - https://github.com/nfb2021/canvodpy

2. **Settings → Environments**

3. **New environment:**
   - Name: `test-release`
   - Click "Configure environment"

4. **Add protection rules (optional):**
   - Required reviewers: Add yourself
   - Wait timer: 0 minutes (it's just testing)

5. **Save**

### Step 5: Create TestPyPI Workflow

Create: `.github/workflows/publish_testpypi.yml`

```yaml
name: Publish to TestPyPI

on:
  release:
    types: [published]

  # Manual trigger for testing
  workflow_dispatch:

permissions:
  id-token: write  # REQUIRED for OIDC
  contents: read

jobs:
  publish-testpypi:
    name: Upload to TestPyPI
    runs-on: ubuntu-latest
    environment: test-release

    # Only run if tag contains 'beta' or 'alpha' (for testing)
    if: contains(github.ref, 'beta') || contains(github.ref, 'alpha')

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "0.9.27"

      - name: Set up Python
        run: uv python install 3.13

      - name: Build package
        run: uv build

      - name: Publish to TestPyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/
          print-hash: true
```

### Step 6: Test the Workflow

**Create a beta release:**
```bash
just release 0.1.0-beta.1
git push origin main
git push origin --tags
```

**Publish the draft release:**
1. Go to: https://github.com/nfb2021/canvodpy/releases
2. Find draft for `v0.1.0-beta.1`
3. Click "Publish release"

**Watch the workflow:**
1. Go to: https://github.com/nfb2021/canvodpy/actions
2. See "Publish to TestPyPI" running
3. Wait ~2-3 minutes
4. Should say "✓ Complete"

**Verify upload:**
- https://test.pypi.org/project/canvodpy/
- Should see version 0.1.0b1

**Test installation:**
```bash
# Create test environment
uv venv test-env
source test-env/bin/activate  # or test-env\Scripts\activate on Windows

# Install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ canvodpy

# Test it works
python -c "import canvodpy; print(canvodpy.__version__)"
# Should print: 0.1.0b1

# Clean up
deactivate
rm -rf test-env
```

**If it works, you are ready for real PyPI.**

---

## Phase 2: Real PyPI Setup

### Step 7: Create Real PyPI Account

1. Go to: https://pypi.org/account/register/
2. Fill in details (can use same email as TestPyPI)
3. Verify email
4. **Enable 2FA** (PyPI requires it for trusted publishers!)

### Step 8: Reserve Package Name on PyPI

**CAUTION:** This is permanent! Double-check everything.

```bash
# Build fresh
cd /path/to/canvodpy
rm -rf dist/
uv build

# Upload to REAL PyPI
uvx twine upload dist/*
```

**When prompted:**
```
username: your_pypi_username
password: your_pypi_password
```

**Verify:**
- https://pypi.org/project/canvodpy/

### Step 9: Configure OIDC on Real PyPI

**Exactly same as TestPyPI:**

1. **Go to:**
   - https://pypi.org/manage/project/canvodpy/settings/publishing/

2. **Add publisher:**
   ```
   PyPI project name:     canvodpy
   Owner:                 nfb2021
   Repository name:       canvodpy
   Workflow name:         publish_pypi.yml
   Environment name:      release
   ```

3. **Click "Add"**

### Step 10: Create Production GitHub Environment

1. **Settings → Environments → New**
2. **Name:** `release`
3. **Protection rules (IMPORTANT!):**
   - Required reviewers: Add all maintainers
   - Wait timer: 5 minutes (think before publishing)
4. **Save**

### Step 11: Create Production Workflow

Create: `.github/workflows/publish_pypi.yml`

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

permissions:
  id-token: write
  contents: read

jobs:
  publish-pypi:
    name: Upload to PyPI
    runs-on: ubuntu-latest
    environment: release

    # Skip beta/alpha releases for production PyPI
    if: "!contains(github.ref, 'beta') && !contains(github.ref, 'alpha')"

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "0.9.27"

      - name: Set up Python
        run: uv python install 3.13

      - name: Build package
        run: uv build

      - name: Check package
        run: |
          uvx twine check dist/*
          ls -lh dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          print-hash: true
```

### Step 12: First Production Release

**When ready for v0.1.0:**

```bash
# Create release
just release 0.1.0
git push origin main
git push origin --tags
```

**Publish:**
1. Go to releases
2. Find draft v0.1.0
3. **Review carefully!**
4. Click "Publish release"
5. Approve the workflow when prompted
6. Wait 5 minutes (your wait timer)
7. Workflow runs
8. Package published to PyPI!

**Verify:**
```bash
pip install canvodpy
python -c "import canvodpy; print(canvodpy.__version__)"
# Should print: 0.1.0
```

**Your package is now on PyPI.**

---

## Summary: What You Get

### For Beta/Test Releases:
```bash
just release 0.2.0-beta.1
git push --tags
# → Publishes to TestPyPI
```

### For Stable Releases:
```bash
just release 0.2.0
git push --tags
# → Publishes to real PyPI
```

### Users Can Install:
```bash
pip install canvodpy       # Latest stable
pip install canvodpy==0.2.0   # Specific version
```

---

## Troubleshooting

### "Publisher not configured"

**Problem:** OIDC upload fails with authentication error

**Check:**
1. Environment name in workflow matches PyPI config
2. Workflow name matches exactly
3. Repository owner/name correct
4. You've enabled 2FA on PyPI

### "Package already exists"

**Problem:** Can't upload same version twice

**Solution:** Bump version and try again
```bash
just bump patch  # 0.1.0 → 0.1.1
```

### "Build failed"

**Problem:** `uv build` doesn't work

**Check:**
```bash
# Test locally first
uv build
ls dist/
# Should see .whl and .tar.gz files
```

### "Environment approval stuck"

**Problem:** Workflow waiting for approval forever

**Solution:** Check Environment protection rules
- Maybe you need to approve manually
- Check who's configured as reviewer

---

## Best Practices

1. **Always test on TestPyPI first**
   - Use `-beta.X` or `-alpha.X` versions
   - Verify installation works

2. **Use environment protection**
   - Required reviewers prevent accidents
   - Wait timer gives you time to think

3. **Version numbers are permanent**
   - Can't delete from PyPI
   - Can't reuse version numbers
   - Be careful!

4. **Keep pre-releases separate**
   - TestPyPI: beta/alpha releases
   - Real PyPI: stable releases only

5. **Monitor your releases**
   - Check PyPI after each upload
   - Verify install works
   - Check download stats

---

## Next Steps

- [ ] Test with beta release on TestPyPI
- [ ] First production release v0.1.0
- [ ] Set up Zenodo for DOI (academic citations)
- [ ] Configure GitHub Sponsors (optional)
- [ ] Add download badges to README

**Questions?** Check `/files/how_it_works.md` for detailed explanations!
