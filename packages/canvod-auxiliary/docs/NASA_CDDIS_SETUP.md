# NASA CDDIS Setup Guide

## Overview

NASA CDDIS (Crustal Dynamics Data Information System) provides a fallback FTP server for GNSS auxiliary data. While **not required** for normal operation (ESA server works out-of-the-box), enabling CDDIS provides redundancy.

## Why Enable CDDIS?

**Benefits:**
- Automatic fallback if primary ESA server is unavailable
- Redundancy for mission-critical applications
- Access to NASA's GNSS product archive

**Not Required:**
- Application works perfectly with ESA server only
- No authentication needed for ESA
- CDDIS is optional enhancement

## Setup Steps

### 1. Register for NASA Earthdata Account

Visit: https://urs.earthdata.nasa.gov/users/new

- Create a free account
- Verify your email address
- Remember your registered email (you'll need it)

### 2. Set Environment Variable

Add to your `.env` file or export in terminal:

```bash
# In .env file
CDDIS_MAIL=your.email@example.com
```

Or in terminal:
```bash
export CDDIS_MAIL="your.email@example.com"
```

### 3. Verify Setup

Run test script:
```bash
cd /Users/work/Developer/GNSS/canvodpy/packages/canvod-auxiliary
uv run python test_download.py
```

You should see:
```
ℹ NASA CDDIS fallback enabled
```

Instead of:
```
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set CDDIS_MAIL environment variable
```

## Testing

### Test ESA Only (Default)
```python
from canvod.auxiliary.ephemeris.reader import Sp3File
import datetime

# No CDDIS_MAIL set - uses ESA only
sp3 = Sp3File.from_datetime_date(
    date=datetime.date(2023, 9, 11),
    agency="COD",
    product_type="final",
    ftp_server="ftp://gssc.esa.int/gnss",
    local_dir="/tmp/test",
)
```

### Test with CDDIS Fallback
```python
import os
os.environ["CDDIS_MAIL"] = "your.email@example.com"

# Now has NASA CDDIS as fallback
sp3 = Sp3File.from_datetime_date(
    date=datetime.date(2023, 9, 11),
    agency="COD",
    product_type="final",
    ftp_server="ftp://gssc.esa.int/gnss",
    local_dir="/tmp/test",
)
```

## Troubleshooting

### Error: "NASA CDDIS requires authentication"

**Cause:** CDDIS_MAIL not set or incorrect

**Fix:**
1. Verify `CDDIS_MAIL` is set: `echo $CDDIS_MAIL`
2. Check email matches your NASA Earthdata registration
3. Restart application after setting

### Error: "550 No such file or directory"

**Cause:** File not available on server yet

**Fix:**
- Check product latency (COD final: ~168 hours, rapid: ~17 hours)
- Try older date (known to be available)
- FTP path may be incorrect for that specific server

### Downloads Work Without CDDIS

**This is normal!** ESA server is the primary and works without authentication. CDDIS is only used as fallback if ESA fails.

## FTP Server Priority

1. **Primary:** ESA (ftp://gssc.esa.int/gnss) - No auth required
2. **Fallback:** NASA CDDIS (ftp://gdc.cddis.eosdis.nasa.gov) - Requires CDDIS_MAIL

Application always tries ESA first, only falling back to NASA if ESA fails.

## Security Note

The CDDIS_MAIL is your NASA Earthdata registered email, **not a password**. NASA CDDIS uses anonymous FTP with email-based tracking, not password authentication.
