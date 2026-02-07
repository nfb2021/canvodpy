# MyST Configuration Guide

## Custom Theme

canVODpy uses a custom dark theme optimized for documentation. See [THEME.md](THEME.md) for complete details.

**Quick facts:**
- **Colors**: Nordic Green palette (#E1E6B9, #C4D7A4, #ABC8A4, #375D3B, #183128)
- **Font**: Space Grotesk + Fira Code (monospace)
- **Logo**: TU Wien (white version)
- **File**: `docs/assets/canvod-nordic.css`

---

## Logo Customization

The TU Wien logo appears because your `myst.yml` extends the TUW-GEO configuration:

```yaml
extends:
  - https://github.com/TUW-GEO/cookiecutter-docs-config/raw/main/myst.yml
```

### How to Change the Logo

You can override the logo by adding a `site` section in your `myst.yml`:

#### Option 1: Remove the logo

```yaml
site:
  logo: null
```

#### Option 2: Use your own logo image

```yaml
site:
  logo: docs/assets/logo.png  # Local file
  # OR
  logo: https://example.com/logo.png  # Remote URL
```

Supported formats: PNG, SVG, JPEG

#### Option 3: Use text instead of image

```yaml
site:
  logo_text: canVODpy
```

#### Option 4: Customize logo with options

```yaml
site:
  logo: docs/assets/logo.png
  logo_width: 200px
  logo_link: https://github.com/nfb2021/canvodpy
```

### Additional Site Customization

```yaml
site:
  # Remove or replace logo
  logo: null

  # Site title (appears in browser tab)
  title: canVODpy Documentation

  # Footer customization
  footer: "© 2026 Nicolas Bader. Licensed under Apache 2.0."

  # Social links
  nav:
    - title: GitHub
      url: https://github.com/nfb2021/canvodpy
```

### Full Example

```yaml
version: 1

extends:
  - https://github.com/TUW-GEO/cookiecutter-docs-config/raw/main/myst.yml

site:
  logo: null  # Remove TU Wien logo
  title: canVODpy Documentation
  footer: "© 2026 Nicolas Bader"

project:
  title: canVODpy
  # ... rest of your config
```

### Testing Changes

After modifying `myst.yml`:

```bash
# Restart MyST server
uv run myst start

# Or rebuild with cache clear
uv run myst build --clean
uv run myst start
```

### Where Settings Come From

**Priority order (highest to lowest):**
1. Your local `myst.yml` settings
2. Extended configuration (TUW-GEO)
3. MyST defaults

Settings in your local file **override** the extended configuration.

### Common Customizations

```yaml
site:
  # Branding
  logo: null
  logo_text: canVODpy

  # Navigation
  nav:
    - title: Home
      url: /
    - title: GitHub
      url: https://github.com/nfb2021/canvodpy

  # Theme
  theme: book  # Options: book, article, default

  # Analytics (optional)
  analytics:
    google: G-XXXXXXXXXX
```

## References

- [MyST Site Configuration](https://mystmd.org/guide/site-config)
- [MyST Theming](https://mystmd.org/guide/themes)
