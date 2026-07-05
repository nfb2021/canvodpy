#!/usr/bin/env python3
"""concat_daily.py — splice 96×15-min RINEX 3.04 files into 24h daily files.

Both the 15-min source files (.25o) and the target daily files (.rnx) are
RINEX 3.04 — Septentrio's ssrcrin outputs RINEX 3 with legacy .25o naming.

gfzrnx (v2.2.0 arm64) is broken on macOS 15 (PAR-packed Perl IO bundle fails
code-signature validation).  This script does a pure-Python text splice:

  • Keep the full header from the first 15-min file unchanged.
  • For every subsequent file strip everything up to and including the
    "END OF HEADER" line, then concatenate all epoch records.
  • Epoch lines in RINEX 3 start with ">".

Output naming mirrors the existing daily files:
    {STATION9}_R_{YYYY}{DOY}0000_01D_05S_AA.rnx
    e.g.  ROSR01TUW_R_20250020000_01D_05S_AA.rnx

Usage
-----
    uv run python dev/concat_daily.py           # process all available DOYs
    uv run python dev/concat_daily.py --dry     # list what would be done
    uv run python dev/concat_daily.py --doy 25003  # single DOY only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_BASE = Path("/Volumes/ExtremePro/Sample_data")
DST_BASE = Path("/Volumes/ExtremePro/Daily_data")

# (subdir, 9-char RINEX 3 station ID matching existing daily files)
RECEIVERS: list[tuple[str, str]] = [
    ("01_reference", "ROSR01TUW"),
    ("02_canopy", "ROSA01TUW"),
]

YEAR = "25"
YEAR4 = f"20{YEAR}"
START_DOY = 1
N_DAYS = 28


def splice_rinex3(files: list[Path], out_path: Path) -> int:
    """Splice RINEX 3 observation files into *out_path*.

    Keeps the full header from *files[0]* and strips headers from all
    subsequent files.  Returns the number of epoch records written.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    epochs = 0
    with out_path.open("w") as out:
        for idx, f in enumerate(files):
            in_header = True
            with f.open() as inp:
                for line in inp:
                    if in_header:
                        if "END OF HEADER" in line:
                            in_header = False
                            if idx == 0:
                                out.write(line)
                            # subsequent files: drop header line, data follows
                        elif idx == 0:
                            out.write(line)  # write header from first file only
                    else:
                        out.write(line)
                        if line.startswith(">"):  # RINEX 3 epoch record marker
                            epochs += 1
    return epochs


def output_name(station_id: str, doy: str) -> str:
    """Build RINEX 3 long filename for a 24h daily file.

    Pattern: {STATION9}_R_{YYYY}{DOY}0000_01D_05S_AA.rnx
    doy is in YYDDD format (e.g. '25002').
    """
    return f"{station_id}_R_{YEAR4}{doy[2:]}0000_01D_05S_AA.rnx"


def discover_doys(doy_filter: str | None) -> list[str]:
    """Return sorted list of YYDDD strings that have source .25o files."""
    doys: list[str] = []
    for i in range(START_DOY, START_DOY + N_DAYS):
        doy = f"{YEAR}{i:03d}"
        if doy_filter and doy != doy_filter:
            continue
        for rx_dir, _ in RECEIVERS:
            if list((SRC_BASE / rx_dir / doy).glob(f"*.{YEAR}o")):
                doys.append(doy)
                break
    return doys


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Show what would be done without writing anything",
    )
    parser.add_argument(
        "--doy", metavar="YYDDD", help="Process a single DOY only (e.g. 25003)"
    )
    args = parser.parse_args()

    doys = discover_doys(args.doy)
    if not doys:
        print("No source DOYs found — has fetch_rosalia.sh run yet?")
        sys.exit(1)

    print(
        f"{'DRY RUN — ' if args.dry else ''}Splicing {len(doys)} DOY(s) × "
        f"{len(RECEIVERS)} receivers into {DST_BASE}\n"
    )

    total_written = 0
    skipped = 0

    for rx_dir, station_id in RECEIVERS:
        print(f"── {rx_dir} ({station_id}) ──")
        for doy in doys:
            src_dir = SRC_BASE / rx_dir / doy
            dst_dir = DST_BASE / rx_dir / doy

            files = sorted(src_dir.glob(f"*.{YEAR}o"))
            if not files:
                print(f"  {doy}: no .{YEAR}o files — skip")
                skipped += 1
                continue

            out_name = output_name(station_id, doy)
            out_path = dst_dir / out_name

            if out_path.exists():
                size_mb = out_path.stat().st_size / 1024**2
                print(f"  {doy}: exists ({out_name}, {size_mb:.0f} MB) — skip")
                skipped += 1
                continue

            print(
                f"  {doy}: {len(files)} × 15-min → {out_name} ...", end="", flush=True
            )

            if args.dry:
                print("  (dry)")
                continue

            epochs = splice_rinex3(files, out_path)
            size_mb = out_path.stat().st_size / 1024**2
            print(f"  {epochs} epochs, {size_mb:.0f} MB")
            total_written += 1

        print()

    if not args.dry:
        print(f"Done. {total_written} file(s) written, {skipped} skipped.")


if __name__ == "__main__":
    main()
