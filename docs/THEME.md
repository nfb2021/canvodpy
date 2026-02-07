# Custom Theme Documentation

## Overview

The canVODpy documentation uses a custom dark theme optimized for readability and modern aesthetics.

## Color Scheme

The theme uses a Nordic Green palette built from 5 colors:

| Token | Hex Code | Usage |
|-------|----------|-------|
| g1 | `#E1E6B9` | Light background, dark-mode muted text |
| g2 | `#C4D7A4` | Surface, dark-mode main text |
| g3 | `#ABC8A4` | Borders, code borders |
| g4 | `#375D3B` | Links, muted text, UI actions |
| g5 | `#183128` | Dark background, main text |

### Color Psychology

- **Green palette**: Vegetation/nature theme (VOD = Vegetation Optical Depth)
- **No blue anywhere**: Deliberate constraint for visual consistency
- **Light/dark mode**: Tokens swap roles between modes
- **5-color constraint**: Every UI element uses only these 5 colors

## Typography

**Font Family**: [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk)

Space Grotesk is a modern, geometric sans-serif font that provides:
- Excellent readability at all sizes
- Professional technical aesthetic
- Good distinction between similar characters (important for code)

**Font Weights Used**:
- 300 (Light): Rarely used
- 400 (Regular): Body text
- 500 (Medium): Subtle emphasis
- 600 (Semi-Bold): Headings, strong emphasis
- 700 (Bold): Main headings (h1)

## Customization

### Changing Colors

Edit `docs/assets/canvod-nordic.css`:

```css
:root {
  /* Update these variables */
  --g1: #E1E6B9;  /* light */
  --g2: #C4D7A4;
  --g3: #ABC8A4;
  --g4: #375D3B;
  --g5: #183128;  /* dark */
}
```

### Changing Font

Replace the Google Fonts import:

```css
@import url('https://fonts.googleapis.com/css2?family=YourFont:wght@300;400;500;600;700&display=swap');

:root {
  --font-family: 'YourFont', sans-serif;
}
```

### Adding Custom Styles

Add new rules to the bottom of `canvod-nordic.css`:

```css
/* Custom additions */
.my-custom-class {
  color: var(--canvod-green);
  background: var(--canvod-purple);
}
```

## Logo

**Current Logo**: TU Wien logo (white version for dark background)

**Location in config**: `myst.yml`

```yaml
site:
  options:
    logo: https://www.tuwien.at/...
    logo_url: https://github.com/nfb2021/canvodpy
```

### Changing the Logo

1. **Use a different URL**:
   ```yaml
   logo: https://example.com/your-logo.png
   ```

2. **Use a local file**:
   ```yaml
   logo: docs/assets/logo.png
   ```

3. **Remove logo entirely**:
   ```yaml
   logo: null
   ```

## Theme Components

### Styled Elements

The custom theme includes styling for:

#### Typography
- All heading levels (h1-h6)
- Paragraphs, lists, tables
- Emphasis (bold, italic)
- Links (with hover effects)

#### Code
- Inline code blocks
- Multi-line code blocks
- Syntax highlighting
- Monospace font styling

#### Navigation
- Sidebar navigation
- Active page highlighting
- Hover effects
- Breadcrumbs

#### Interactive Elements
- Buttons
- Search input
- Form elements
- Focus indicators (accessibility)

#### Content Blocks
- Blockquotes
- Admonitions (notes, warnings, tips)
- Cards and containers
- Tables

### Special Features

#### Smooth Transitions
All interactive elements have smooth color transitions (0.2s ease).

#### Custom Scrollbar
Webkit browsers get a styled scrollbar matching the theme.

#### Responsive Design
Mobile-optimized with adjusted font sizes and layouts.

#### Accessibility
- Focus indicators for keyboard navigation
- High contrast ratios
- Semantic color usage

## Testing Changes

After modifying the CSS:

1. **Clear build cache**:
   ```bash
   uv run myst build --clean
   ```

2. **Restart server**:
   ```bash
   uv run myst start
   ```

3. **Force browser refresh**:
   - Chrome/Firefox: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)

## Browser Compatibility

The theme is tested and works with:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Note**: Some features (custom scrollbar, smooth scrolling) may vary by browser.

## Performance

The custom CSS file is:
- **Size**: ~15 KB (minified: ~10 KB)
- **Load time**: <50ms on typical connections
- **No JavaScript**: Pure CSS implementation

## Maintenance

### Regular Updates

Check these periodically:
- Google Fonts availability
- Logo URL validity
- Color contrast ratios (WCAG 2.1 Level AA)

### Color Contrast

Current ratios (on black background):
- Light Green 1 (#C9DABC): 12.5:1 ✓ (Excellent)
- Light Green 2 (#CCD9BF): 13.1:1 ✓ (Excellent)
- Green (#007449): 4.8:1 ✓ (Good)
- Gray (#53585F): 3.2:1 ⚠️ (Adequate for large text)

## Tips

### Dark Mode Best Practices

1. **Avoid pure white**: Use light greens instead
2. **Reduce contrast**: Not as high as light mode
3. **Use warm colors**: Avoid pure blues (eye strain)
4. **Test in different lighting**: Should work in bright and dim environments

### Content Creation

When writing documentation:
- Use `**bold**` for emphasis (styled in light green)
- Use `code` for inline code (purple background)
- Use headers liberally (styled in green/light green)
- Add horizontal rules (`---`) for visual breaks

## Troubleshooting

### CSS Not Loading

1. Check file path in `myst.yml`
2. Rebuild: `uv run myst build --clean`
3. Clear browser cache

### Font Not Showing

1. Check Google Fonts URL
2. Verify internet connection
3. Check browser console for errors

### Colors Look Wrong

1. Verify hex codes in CSS
2. Check for overriding styles
3. Inspect element in browser DevTools

## Resources

- [Space Grotesk Font](https://fonts.google.com/specimen/Space+Grotesk)
- [Color Contrast Checker](https://webaim.org/resources/contrastchecker/)
- [CSS Custom Properties (MDN)](https://developer.mozilla.org/en-US/docs/Web/CSS/--*)
- [MyST Documentation Theming](https://mystmd.org/guide/themes)

## Version History

### v1.0.0 (Current)
- Initial dark theme
- Space Grotesk font
- Custom color scheme from presentation
- Complete component coverage
- Responsive design
- Accessibility features
