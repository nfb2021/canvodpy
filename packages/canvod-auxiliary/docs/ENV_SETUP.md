# Environment Setup for canvod-auxiliary

## Quick Start

### 1. Copy Environment Template

```bash
cd packages/canvod-auxiliary
cp .env.example .env
```

### 2. Configure CDDIS Email (Optional)

Edit `.env` and uncomment the CDDIS_MAIL line:

```bash
# .env file
CDDIS_MAIL=your.email@example.com
```

**⚠️ IMPORTANT:**
- The `.env` file is gitignored - your email stays private
- Never commit your `.env` file to version control
- Share `.env.example` with collaborators, not `.env`

### 3. Register for NASA Earthdata (If Using CDDIS)

1. Visit: https://urs.earthdata.nasa.gov/users/new
2. Create free account
3. Use your registered email in `.env`

## Usage

### Without CDDIS (Default)

```python
from canvod.auxiliary.ephemeris.reader import Sp3File
import datetime

# Works out-of-the-box, no configuration needed
sp3 = Sp3File.from_datetime_date(
    date=datetime.date(2023, 9, 11),
    agency="COD",
    product_type="final",
    ftp_server="ftp://gssc.esa.int/gnss",
    local_dir="/tmp/aux",
)
```

Output:
```
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set CDDIS_MAIL environment variable
```

### With CDDIS Fallback

After setting `CDDIS_MAIL` in `.env`:

```python
import os
from canvod.auxiliary.ephemeris.reader import Sp3File
from canvod.auxiliary.core.downloader import FtpDownloader

# Load from environment
user_email = os.environ.get("CDDIS_MAIL")
downloader = FtpDownloader(user_email=user_email)

sp3 = Sp3File.from_datetime_date(
    date=datetime.date(2023, 9, 11),
    agency="COD",
    product_type="final",
    ftp_server="ftp://gssc.esa.int/gnss",
    local_dir="/tmp/aux",
    downloader=downloader,
)
```

Output:
```
ℹ NASA CDDIS fallback enabled
```

## FTP Server Strategy

### Primary: ESA (No Auth Required)
- Server: `ftp://gssc.esa.int/gnss`
- Authentication: None
- Default behavior

### Fallback: NASA CDDIS (Requires Email)
- Server: `ftp://gdc.cddis.eosdis.nasa.gov`
- Authentication: Email from NASA Earthdata registration
- Enabled when `CDDIS_MAIL` is set
- Only used if ESA fails

## Security Best Practices

### ✅ DO:
- Keep `.env` in `.gitignore`
- Use `.env.example` as template
- Share `.env.example` with team
- Use different `.env` per environment (dev/prod)

### ❌ DON'T:
- Commit `.env` to git
- Share your actual `.env` file
- Put credentials in code
- Use production credentials in dev

## Loading Environment Variables

### Method 1: System Environment

```bash
export CDDIS_MAIL="your.email@example.com"
python your_script.py
```

### Method 2: .env File (Recommended)

```python
# .env file is automatically loaded by python-dotenv
# if package is installed with dev dependencies

# Or manually load:
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

import os
email = os.environ.get("CDDIS_MAIL")
```

### Method 3: In Code (Not Recommended)

```python
import os
# Only for testing - don't commit this!
os.environ["CDDIS_MAIL"] = "test@example.com"
```

## Troubleshooting

### "CDDIS_MAIL not set" Warning

**Symptom:** You see:
```
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set CDDIS_MAIL environment variable
```

**Solutions:**
1. This is normal if you haven't set CDDIS_MAIL
2. ESA server works fine without it
3. To enable CDDIS: set CDDIS_MAIL in `.env`

### "NASA CDDIS requires authentication" Error

**Symptom:** Downloads fail with authentication error

**Solutions:**
1. Verify `CDDIS_MAIL` is set: `echo $CDDIS_MAIL`
2. Check email matches NASA Earthdata registration
3. Reload environment variables
4. Try running: `export CDDIS_MAIL="your.email@example.com"`

### .env File Not Loading

**Symptom:** Environment variables not found

**Solutions:**
1. Check file is named `.env` (not `env` or `.env.txt`)
2. File must be in package root: `packages/canvod-auxiliary/.env`
3. Install python-dotenv: `uv add python-dotenv`
4. Manually load: `load_dotenv(Path('.env'))`

## Example Workflow

```bash
# 1. Initial setup (once)
cd packages/canvod-auxiliary
cp .env.example .env
nano .env  # Edit CDDIS_MAIL if desired

# 2. Run tests
uv run pytest

# 3. Run demo
uv run marimo edit docs/demo.py

# 4. Use in your code
uv run python your_script.py
```

## Multiple Environments

### Development
```bash
# .env.dev
CDDIS_MAIL=dev@example.com
```

### Production
```bash
# .env.prod
CDDIS_MAIL=prod@example.com
```

Load specific file:
```python
from dotenv import load_dotenv
load_dotenv('.env.prod')
```

## Checking Configuration

```python
import os

# Check if CDDIS is configured
cddis_mail = os.environ.get("CDDIS_MAIL")

if cddis_mail:
    print(f"✓ CDDIS configured: {cddis_mail}")
else:
    print("ℹ CDDIS not configured (using ESA only)")
```

## Further Reading

- [NASA CDDIS Registration](https://urs.earthdata.nasa.gov/users/new)
- [NASA CDDIS Documentation](https://cddis.nasa.gov/Data_and_Derived_Products/GNSS/gnss_data_products.html)
- [python-dotenv Documentation](https://github.com/theskumar/python-dotenv)
