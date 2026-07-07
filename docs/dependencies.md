# Package Dependencies

Inter-package dependency relationships and independence metrics for the canVODpy monorepo.

---

## Dependency Graph

```mermaid
graph TD
    subgraph CONSUMERS["Consumer Layer"]
        AUX["canvod-auxiliary"]
        VIZ["canvod-viz"]
        STORE["canvod-store"]
        STOREMETA["canvod-store-metadata"]
        OPS["canvod-ops"]
    end

    subgraph FOUNDATION["Foundation Layer (0 inter-package deps)"]
        READERS["canvod-readers"]
        GRIDS["canvod-grids"]
        VOD["canvod-vod"]
        UTILS["canvod-utils"]
        NAMING["canvod-filemap"]
    end

    AUX   --> READERS
    VIZ   --> GRIDS
    STORE --> GRIDS
    STOREMETA --> UTILS
    OPS   --> GRIDS
    OPS   --> UTILS
```

---

## Independence Metrics

| Package | Ce (deps) | Ca (dependents) | Instability | Independence |
|---------|:---------:|:---------------:|:-----------:|:------------:|
| canvod-readers | 0 | 1 | 0.00 | 1.00 |
| canvod-grids | 0 | 3 | 0.00 | 1.00 |
| canvod-vod | 0 | 0 | 0.00 | 1.00 |
| canvod-utils | 0 | 2 | 0.00 | 1.00 |
| canvod-filemap | 0 | 0 | 0.00 | 1.00 |
| canvod-auxiliary | 1 | 0 | 1.00 | 0.90 |
| canvod-viz | 1 | 0 | 1.00 | 0.90 |
| canvod-store | 1 | 0 | 1.00 | 0.90 |
| canvod-store-metadata | 1 | 0 | 1.00 | 0.90 |
| canvod-ops | 2 | 0 | 1.00 | 0.80 |

??? note "Metric definitions"
    - **Ce (efferent coupling)** — packages this package depends on. Lower = more independent.
    - **Ca (afferent coupling)** — packages that depend on this one. Higher = more reusable.
    - **Instability** — `Ce / (Ce + Ca)`. 0.0 = maximally stable (foundation). 1.0 = maximally unstable (leaf).
    - **Independence** — `1 − (Ce / total_packages)`. 1.0 = no inter-package dependencies.

---

## Architecture Summary

!!! success "Flat dependency graph"
    - **No circular dependencies**
    - 5 of 10 packages (50 %) have zero inter-package dependencies
    - 7 total internal dependency edges
    - **Maximum depth = 1** — a consumer depends on one or two foundation packages; foundations never depend on each other

This two-layer structure simplifies testing (test Layer 0 packages first, then Layer 1) and ensures that changes to a foundation package do not cascade to sibling packages.

---

## Extractability

All packages can be extracted to independent repositories with zero or minimal changes:

=== "Foundation packages"

    ```bash
    # Extract directly — no internal dependencies
    packages/canvod-readers/          → independent repo
    packages/canvod-grids/            → independent repo
    packages/canvod-vod/              → independent repo
    packages/canvod-utils/            → independent repo
    packages/canvod-filemap/ → independent repo
    ```

=== "Consumer packages"

    ```bash
    # Extract + add PyPI dependencies
    packages/canvod-auxiliary/      → independent repo (+ canvod-readers on PyPI)
    packages/canvod-viz/            → independent repo (+ canvod-grids on PyPI)
    packages/canvod-store/          → independent repo (+ canvod-grids on PyPI)
    packages/canvod-store-metadata/ → independent repo (+ canvod-utils on PyPI)
    packages/canvod-ops/            → independent repo (+ canvod-grids + canvod-utils on PyPI)
    ```

---

## Regenerate Reports

```bash
just deps-report    # Full metrics report
just deps-graph     # Mermaid dependency diagram
```
