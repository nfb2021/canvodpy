"""Quick stats on what the config actually discovers for a site's receivers.

Mirrors the real pipeline's file-discovery logic (canvodpy.workflows.tasks.
validate_data_dirs) instead of reinventing it, so the numbers reported here
match what canvodpy run/config validate would actually see:

  - recipe-based receivers (config `recipe: <name>`) -- the common case,
    uses the same canvod.filemap.recipe.NamingRecipe as the real validator
  - receivers with neither recipe nor naming -- the real validator just
    skips these; this script still reports raw file counts (no canonical-
    name matching) since "nothing at all" is less useful than "here's
    what's actually on disk"

For each receiver, reports: total files, total size, extension breakdown,
matched/unmatched counts (recipe receivers only), and average files per
day -- both per CALENDAR day (total / date span, shows gaps) and per
ACTIVE day (total / distinct days with any file, ignores gaps).

Usage
-----
    uv run python dev/data_discovery_stats.py examplesite
    uv run python dev/data_discovery_stats.py examplesite --receiver canopy_01
"""

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}PB"


def date_from_recipe_parse(parsed: dict) -> date | None:
    """Best-effort calendar date from a NamingRecipe.parse_filename() result."""
    try:
        if "year" in parsed:
            year = parsed["year"]
        elif "yy" in parsed:
            from canvod.filemap.patterns import resolve_year_from_yy

            year = resolve_year_from_yy(parsed["yy"])
        else:
            return None

        if "doy" in parsed:
            return date(year, 1, 1) + timedelta(days=int(parsed["doy"]) - 1)
        if "month" in parsed and "day" in parsed:
            return date(year, int(parsed["month"]), int(parsed["day"]))
    except ValueError, KeyError:
        return None
    return None


def stats_for_recipe_receiver(recipe_name: str, base_dir: Path) -> dict:
    from canvod.config.loader import find_monorepo_root
    from canvod.filemap.recipe import NamingRecipe

    recipe_path = find_monorepo_root() / "config" / "recipes" / f"{recipe_name}.yaml"
    if not recipe_path.exists():
        return {"error": f"Recipe file not found: {recipe_path}"}

    recipe = NamingRecipe.load(recipe_path)

    if not base_dir.exists():
        return {"error": f"Directory does not exist: {base_dir}"}

    all_files = [f for f in base_dir.rglob(recipe.glob) if f.is_file()]
    matched_dates: list[date] = []
    unmatched_samples: list[str] = []
    extensions: Counter[str] = Counter()
    total_size = 0

    for f in all_files:
        extensions[f.suffix.lower() or "(none)"] += 1
        total_size += f.stat().st_size

        if not recipe.matches(f.name):
            if len(unmatched_samples) < 20:
                unmatched_samples.append(f.name)
            continue
        try:
            parsed = recipe.parse_filename(f.name)
            d = date_from_recipe_parse(parsed)
            if d is not None:
                matched_dates.append(d)
        except ValueError:
            if len(unmatched_samples) < 20:
                unmatched_samples.append(f.name)

    n_matched = len(matched_dates)

    return {
        "mode": "recipe",
        "recipe": recipe_name,
        "total_files": len(all_files),
        "total_size": total_size,
        "matched": n_matched,
        "unmatched": len(all_files) - n_matched,
        "extensions": extensions,
        "unmatched_samples": unmatched_samples,
        "dates": matched_dates,
        "date_label": "Date range",
    }


def stats_for_raw_receiver(base_dir: Path) -> dict:
    """Fallback for receivers with no recipe/naming config: raw file stats only."""
    if not base_dir.exists():
        return {"error": f"Directory does not exist: {base_dir}"}

    all_files = [f for f in base_dir.rglob("*") if f.is_file()]
    extensions: Counter[str] = Counter()
    total_size = 0
    mtimes: list[date] = []

    for f in all_files:
        extensions[f.suffix.lower() or "(none)"] += 1
        stat = f.stat()
        total_size += stat.st_size
        mtimes.append(date.fromtimestamp(stat.st_mtime))

    return {
        "mode": "raw",
        "total_files": len(all_files),
        "total_size": total_size,
        "matched": None,
        "unmatched": None,
        "extensions": extensions,
        "unmatched_samples": [],
        "dates": mtimes,
        "date_label": "Date range (by mtime, no naming convention configured)",
    }


def print_receiver_report(name: str, result: dict, note: str | None = None) -> None:
    print(f"\n=== {name} ===")
    if note:
        print(f"  Note: {note}")
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    mode = result["mode"]
    if mode == "recipe":
        print(f"  Mode: recipe ({result['recipe']})")
    print(
        f"  Total files: {result['total_files']:,}  ({human_size(result['total_size'])})"
    )

    if result["matched"] is not None:
        pct = (
            100 * result["matched"] / result["total_files"]
            if result["total_files"]
            else 0
        )
        print(
            f"  Matched:     {result['matched']:,} / {result['total_files']:,} ({pct:.1f}%)"
        )
        if result["unmatched"]:
            print(f"  Unmatched:   {result['unmatched']:,}")
            print("  Sample unmatched filenames:")
            for sample in result["unmatched_samples"][:10]:
                print(f"    - {sample}")
            if len(result["unmatched_samples"]) > 10:
                print(
                    f"    ... and more (showing first 10 of {len(result['unmatched_samples'])})"
                )

    ext_summary = ", ".join(
        f"{ext}={n}" for ext, n in result["extensions"].most_common(5)
    )
    print(f"  Extensions:  {ext_summary}")

    dates = result["dates"]
    if dates:
        min_d, max_d = min(dates), max(dates)
        span_days = (max_d - min_d).days + 1
        distinct_days = len(set(dates))
        avg_calendar = len(dates) / span_days if span_days else 0
        avg_active = len(dates) / distinct_days if distinct_days else 0
        print(
            f"  {result['date_label']}: {min_d} to {max_d} ({span_days} calendar days)"
        )
        print(f"  Days with data: {distinct_days} / {span_days}")
        print(f"  Avg files/day (calendar): {avg_calendar:.2f}")
        print(f"  Avg files/day (active only): {avg_active:.2f}")
    else:
        print("  Date range:  (no dated files found)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", help="Site name as defined in canvod-settings.yaml")
    parser.add_argument("--receiver", default=None, help="Limit to one receiver")
    args = parser.parse_args()

    from canvod.config import load_config

    config = load_config()
    if args.site not in config.sites.sites:
        available = ", ".join(config.sites.sites.keys()) or "(none)"
        print(f"Unknown site {args.site!r}. Available: {available}", file=sys.stderr)
        sys.exit(1)

    site_cfg = config.sites.sites[args.site]
    base = site_cfg.get_base_path()

    receivers = list(site_cfg.receivers.items())
    if args.receiver is not None:
        if args.receiver not in site_cfg.receivers:
            available = ", ".join(site_cfg.receivers.keys())
            print(
                f"Unknown receiver {args.receiver!r}. Available: {available}",
                file=sys.stderr,
            )
            sys.exit(1)
        receivers = [(args.receiver, site_cfg.receivers[args.receiver])]

    print(f"Site: {args.site}  (base: {base})")

    for name, rcfg in receivers:
        receiver_base_dir = base / rcfg.directory

        if rcfg.recipe:
            try:
                result = stats_for_recipe_receiver(rcfg.recipe, receiver_base_dir)
            except ModuleNotFoundError:
                result = {
                    "error": "canvod.filemap is not installed. Run: uv sync --extra filemap"
                }
            print_receiver_report(name, result)
        else:
            result = stats_for_raw_receiver(receiver_base_dir)
            print_receiver_report(
                name, result, note="no recipe/naming configured -- raw file stats only"
            )


if __name__ == "__main__":
    main()
