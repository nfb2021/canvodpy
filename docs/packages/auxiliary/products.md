# Product Registry

The product registry provides declarative configuration for 37 SP3 and CLK products from 17 analysis centres (agency codes). Products are defined in TOML — no hardcoded URLs in the processing code.

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

| Code | Agency | Product types in the registry |
|------|--------|-------------------------------|
| COD | Center for Orbit Determination in Europe | final, rapid, ultrarapid |
| EMR | Natural Resources Canada | final, rapid, ultrarapid |
| ESA | European Space Agency | final, rapid, ultrarapid |
| GFZ | GeoForschungsZentrum Potsdam | final, rapid, ultrarapid |
| GRG | CNES | final, rapid, ultrarapid |
| IAC | Information-Analytical Centre | final |
| IGS | International GNSS Service | rapid, ultrarapid, real-time |
| JAX, JGX | JAXA | final (JAX); final, rapid, ultrarapid (JGX) |
| JPL | Jet Propulsion Laboratory | final, rapid |
| MIT | Massachusetts Institute of Technology | final |
| NGS | National Geodetic Survey | final, rapid |
| SHA | Shanghai Observatory | ultrarapid |
| SIO | Scripps Institution of Oceanography | rapid, ultrarapid |
| USN | US Naval Observatory | rapid, ultrarapid |
| WHU | Wuhan University | rapid, ultrarapid |
| WUM | Wuhan University (Multi-GNSS) | rapid, near-real-time |

`canvod.auxiliary.list_products()` lists them; the registry is the truth. The final
products of EMR, GFZ, GRG, JGX, JPL, MIT and NGS are hosted by NASA CDDIS only
(see below); COD and ESA final products come from ESA.

!!! tip "Servers and fallback"
    Products are downloaded from ESA GSSC (no account needed). NASA CDDIS is a
    fallback, tried when ESA fails, once `credentials.nasa_earthdata_acc_mail`
    holds the email of a free NASA Earthdata account. Products that only NASA
    CDDIS hosts need that account.

---

## Usage

=== "Look up a product"

    ```python
    from canvod.auxiliary import get_product_spec

    spec = get_product_spec("COD", "final")
    spec.prefix              # "COD0MGXFIN"
    spec.sampling_rate       # "05M"
    spec.available_formats   # ["SP3", "CLK"]
    [s.url for s in spec.ftp_servers]  # ESA first, then NASA CDDIS
    ```

=== "In a run"

    Runs pick the product from the settings; no manual lookup is needed:

    ```yaml
    processing:
      aux_data:
        agency: COD
        product_type: final
        fetch_clock: true   # false: skip CLK, which VOD does not use
    ```

    To add satellite geometry to a dataset in your own code, use an ephemeris
    provider (see [canvod-auxiliary](overview.md)).

---

## Registry Format

Products are declared in
`packages/canvod-auxiliary/src/canvod/auxiliary/products/products.toml`, one
`[[products]]` table each, with its servers in priority order:

```toml
[[products]]
agency = "COD"
type = "final"
prefix = "COD0MGXFIN"
sampling = "05M"
duration = "01D"
description = "CODE final multi-GNSS"
formats = ["SP3", "CLK"]
ftp_path = "/gnss/products/{gps_week}/{file}"

[[products.ftp_servers]]
url = "ftp://gssc.esa.int"
priority = 1
description = "ESA primary"

[[products.ftp_servers]]
url = "ftps://gdc.cddis.eosdis.nasa.gov"
priority = 2
description = "NASA CDDIS fallback"
requires_auth = true
```
