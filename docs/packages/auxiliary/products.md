# Product Registry

The product registry provides declarative configuration for 37 SP3 and CLK products from 17 analysis centres. Products are defined in TOML — no hardcoded URLs in the processing code.

---

## Product Types

<div class="grid cards" markdown>

-   :fontawesome-solid-star: &nbsp; **Final**

    ---

    Latency **14–21 days** · Accuracy **cm-level**

    Highest quality. Use for scientific research, reprocessing campaigns,
    and publication-quality VOD products.

-   :fontawesome-solid-bolt: &nbsp; **Rapid**

    ---

    Latency **17–24 hours** · Accuracy **near-final (cm-level)**

    Available the following day. Use for near-real-time processing when
    final products have not yet been released.

-   :fontawesome-solid-clock: &nbsp; **Ultra-rapid**

    ---

    Latency **3–9 hours** · Accuracy **few cm (predicted half)**

    Partially predicted. The predicted half has lower accuracy.
    Use only when rapid products are insufficient.

</div>

| Type | Latency | Orbit accuracy | Clock accuracy |
|------|---------|---------------|----------------|
| Final | 14–21 d | < 2.5 cm | < 75 ps |
| Rapid | 17–24 h | < 2.5 cm | < 75 ps |
| Ultra-rapid (observed) | 3–9 h | < 3 cm | < 150 ps |
| Ultra-rapid (predicted) | 0 h | < 5 cm | < 3 ns |

---

## Available Agencies

| Agency | Code | Products |
|--------|------|---------|
| Center for Orbit Determination in Europe | CODE | Final, Rapid |
| GeoForschungsZentrum Potsdam | GFZ | Final, Rapid |
| European Space Agency | ESA | Final, Rapid, Ultra-rapid |
| Jet Propulsion Laboratory | JPL | Final |
| International GNSS Service | IGS | Final, Rapid, Ultra-rapid |
| NASA CDDIS | — | FTP mirror for most products |

!!! tip "Automatic fallback"
    The pipeline tries the primary agency first; if the FTP connection fails
    or the file is not yet available, it falls back to the NASA CDDIS mirror
    automatically.

---

## Usage

=== "Lookup a product"

    ```python
    from canvod.auxiliary import get_product_spec

    spec = get_product_spec("CODE", "final")
    print(spec.latency_hours)      # 336 (14 days)
    print(spec.ftp_server)         # ftp.aiub.unibe.ch
    print(spec.requires_auth)      # False
    ```

=== "Download and parse"

    ```python
    from canvod.auxiliary import Sp3File
    from datetime import date

    sp3 = Sp3File.from_url(date(2024, 1, 1), agency="CODE", product="final")
    ds = sp3.to_dataset()

    # ds.dims: {'epoch': 96, 'sv': 32}
    # ds.data_vars: X, Y, Z, Vx, Vy, Vz
    ```

=== "Configuration (canvod-settings.yaml)"

    ```yaml
    auxiliary:
      agency:       ESA
      product_type: final
      cache_dir:    /data/aux_cache
    ```

    The pipeline reads these keys automatically — no manual product lookup needed.

---

## Registry Format

Products are declared in `packages/canvod-auxiliary/src/canvod/auxiliary/products/registry.toml`:

```toml
[CODE.final]
sp3_url_template = "ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.EPH.Z"
clk_url_template = "ftp://ftp.aiub.unibe.ch/CODE/{yyyy}/COD{gpsweek}{dow}.CLK.Z"
latency_hours    = 336
ftp_server       = "ftp.aiub.unibe.ch"
requires_auth    = false

[ESA.rapid]
sp3_url_template = "..."
clk_url_template = "..."
latency_hours    = 18
ftp_server       = "navigation.esa.int"
requires_auth    = false
```

URL templates support: `{yyyy}`, `{doy}`, `{gpsweek}`, `{dow}` (day-of-week within GPS week).
