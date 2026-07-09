# Documentation commands for package-level documentation
# Run from package directory: just docs-build

# Build documentation
docs-build:
    @echo "Building documentation..."
    myst build --html

# Serve documentation with hot reload
docs-serve:
    @echo "Serving documentation at http://localhost:3000"
    @echo "Press Ctrl+C to stop"
    myst start

# Clean documentation build artifacts
docs-clean:
    @echo "Cleaning documentation..."
    rm -rf _build/

# Check documentation for errors
docs-check:
    @echo "Checking documentation..."
    myst build --html --strict

# Open documentation in browser
docs-open:
    @echo "Opening documentation..."
    @open _build/html/index.html || xdg-open _build/html/index.html || start _build/html/index.html
