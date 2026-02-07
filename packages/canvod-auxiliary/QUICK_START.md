# Quick Start - Config-Based Registry

## ✅ Implementation Complete - Just Add Pydantic!

---

## 1. Add Dependency (30 seconds)

```bash
cd /Users/work/Developer/GNSS/canvodpy/packages/canvod-auxiliary
uv add pydantic
```

---

## 2. Verify (1 minute)

```bash
uv run python verify_registry.py
```

**Expected output:**
```
======================================================================
Config-Based Registry Verification
======================================================================

1. Loading registry...
   ✅ Loaded 39 products from 17 agencies

2. Verifying NASA/ESA data...
   ✅ All 17 agencies present

3. Checking server configurations...
   COD/rapid (ESA primary):
   Prefix: COD0OPSRAP
   Servers: 2
     [1] ftp://gssc.esa.int
     [2] ftps://gdc.cddis.eosdis.nasa.gov (auth)

   COD/final (NASA only):
   Prefix: COD0MGXFIN
   Servers: 1
     [1] ftps://gdc.cddis.eosdis.nasa.gov (auth)

...

✅ Config-based registry implementation COMPLETE!
```

---

## 3. Usage Example

```python
from canvod.auxiliary.products.registry_config import get_product_spec

# Get COD rapid product (ESA primary, NASA fallback)
spec = get_product_spec("COD", "rapid")

print(f"Product: {spec.prefix}")
print(f"Latency: {spec.latency_hours} hours")
print(f"Formats: {spec.available_formats}")

# Try servers in priority order
for server in sorted(spec.ftp_servers, key=lambda s: s.priority):
    print(f"[{server.priority}] {server.url}")
    if server.requires_auth:
        print("    Needs CDDIS_MAIL environment variable")
```

---

## What Was Built

### Files:
1. **products.toml** (824 lines) - 39 products, 17 agencies
2. **registry_config.py** (229 lines) - Pydantic validation
3. **verify_registry.py** (160 lines) - Comprehensive tests

### Features:
- ✅ External configuration (edit TOML, not code)
- ✅ Per-product server lists (ESA/NASA/custom)
- ✅ Pydantic validation (type-safe)
- ✅ Lazy FTP validation (fast startup)
- ✅ Automatic server fallback
- ✅ Clear error messages

### Server Strategy:
- **ESA primary** (29 products): rapid/ultrarapid, no auth
- **NASA-only** (8 products): final products, needs CDDIS_MAIL
- **Both servers** (2 products): ESA/IAC/JAX finals

---

## Total Time: 2 Minutes

- **Add pydantic:** 30 seconds
- **Verify:** 1 minute
- **Ready!** 🚀
