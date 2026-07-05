#!/usr/bin/env python3
"""fetch_sp3_clk.py — pre-fetch CODE MGEX final SP3 + CLK for missing DOYs.

Downloads directly from CODE's own FTP at AIUB (no authentication required).
The canvod pipeline's products.toml only lists NASA CDDIS for COD0MGXFIN
(marked "NASA only"), but AIUB hosts identical files openly.

  AIUB base: ftp://ftp.aiub.unibe.ch/CODE_MGEX/CODE/2025/
  SP3 → /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_{YYYYDDD}0000_01D_05M_ORB.SP3
  CLK → /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_{YYYYDDD}0000_01D_30S_CLK.CLK

Usage
-----
    uv run python dev/fetch_sp3_clk.py           # fetch all missing DOYs
    uv run python dev/fetch_sp3_clk.py --dry     # show which are missing
    uv run python dev/fetch_sp3_clk.py --doy 25007  # single DOY
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import time
import urllib.request
from pathlib import Path

DAYS_DIR = Path("/Volumes/ExtremePro/Daily_data")
SP3_DIR = DAYS_DIR / "01_SP3"
CLK_DIR = DAYS_DIR / "02_CLK"

AIUB_BASE = "ftp://ftp.aiub.unibe.ch/CODE_MGEX/CODE/2025"
YEAR = "25"
YEAR4 = f"20{YEAR}"
START_DOY = 1
N_DAYS = 28


def sp3_path(doy: str) -> Path:
    return SP3_DIR / f"COD0MGXFIN_{YEAR4}{doy[2:]}0000_01D_05M_ORB.SP3"


def clk_path(doy: str) -> Path:
    return CLK_DIR / f"COD0MGXFIN_{YEAR4}{doy[2:]}0000_01D_30S_CLK.CLK"


def yyyydoy_str(doy: str) -> str:
    return f"{YEAR4}{doy[2:]}"


def _download_and_decompress(url: str, dest: Path) -> None:
    """Download a .gz file from *url* and decompress it to *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp.gz")
    try:
        urllib.request.urlretrieve(url, tmp)
        with gzip.open(tmp, "rb") as f_in, dest.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    finally:
        tmp.unlink(missing_ok=True)


def fetch_doy(doy: str) -> None:
    """Download SP3 + CLK for *doy* from AIUB if not already present."""
    stem = f"COD0MGXFIN_{yyyydoy_str(doy)}0000"
    for dest, suffix in [
        (sp3_path(doy), "01D_05M_ORB.SP3"),
        (clk_path(doy), "01D_30S_CLK.CLK"),
    ]:
        if dest.exists():
            continue
        url = f"{AIUB_BASE}/{stem}_{suffix}.gz"
        _download_and_decompress(url, dest)


def discover_missing(doy_filter: str | None) -> list[str]:
    missing = []
    for i in range(START_DOY, START_DOY + N_DAYS):
        doy = f"{YEAR}{i:03d}"
        if doy_filter and doy != doy_filter:
            continue
        if not (sp3_path(doy).exists() and clk_path(doy).exists()):
            missing.append(doy)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry", action="store_true", help="List missing files without downloading"
    )
    parser.add_argument(
        "--doy", metavar="YYDDD", help="Fetch a single DOY only (e.g. 25007)"
    )
    args = parser.parse_args()

    missing = discover_missing(args.doy)

    if not missing:
        print("All SP3 + CLK files present — nothing to do.")
        sys.exit(0)

    print(
        f"{'Would fetch' if args.dry else 'Fetching'} {len(missing)} DOY(s) from AIUB:\n"
    )

    for doy in missing:
        sp3_ok = sp3_path(doy).exists()
        clk_ok = clk_path(doy).exists()
        label = []
        if not sp3_ok:
            label.append("SP3")
        if not clk_ok:
            label.append("CLK")
        print(f"  {doy}: missing {'+'.join(label)}", end="", flush=True)

        if args.dry:
            print()
            continue

        t0 = time.perf_counter()
        try:
            fetch_doy(doy)
            elapsed = time.perf_counter() - t0
            sp3_mb = sp3_path(doy).stat().st_size / 1024**2
            clk_mb = clk_path(doy).stat().st_size / 1024**2
            print(f" → SP3 {sp3_mb:.0f} MB, CLK {clk_mb:.0f} MB  ({elapsed:.1f}s)")
        except Exception as exc:
            print(f" → ERROR: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
