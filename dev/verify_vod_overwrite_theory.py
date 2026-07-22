"""Verify the group_exists() VOD overwrite-data-loss theory against a real store.

Theory (see packages/canvod-store/src/canvod/store/store.py::group_exists,
"Confirmed 2026-07-21" docstring note): before the fix, `group_exists()` only
checked *top-level* Zarr group keys, so it always returned False for nested
VOD analysis group paths (e.g. "tau_omega/canopy_01_vs_reference_01"). Every
VOD write after a group's first therefore took the `mode="w"` branch in
`write_or_append_vod_group` instead of appending -- silently destroying all
previously-written VOD data on each subsequent write.

IMPORTANT caveat, found by smoke-testing this script against a simulated bad
store: `mode="w"` on the group also wipes the group's own
`metadata/table` subgroup, not just the data arrays. So after N buggy
writes, the on-disk metadata ledger shows only **1** row (the last write) --
it can never show "many write rows, zero appends" on its own, because each
overwrite erases the evidence of the previous one along with the data. A
naive read of the metadata table alone will therefore always look
"innocent" on a bug-affected store. This script does NOT trust the metadata
table's row count to rule the bug in or out -- it only uses it to report
what's *currently* readable, and cross-references pipeline log files (which
are append-only and survive the store wipes) for the real write-attempt
history via `--log-glob`.

Usage
-----
    # List VOD analysis groups (nested paths) found in the store
    uv run python dev/verify_vod_overwrite_theory.py /path/to/vod_store

    # Report on every group: current on-disk state only
    uv run python dev/verify_vod_overwrite_theory.py /path/to/vod_store --all

    # Same, but also cross-reference the run's log files for the true
    # write-attempt history (glob or directory; searched recursively for
    # "icechunk_write_data_started" lines)
    uv run python dev/verify_vod_overwrite_theory.py /path/to/vod_store --all \\
        --log-glob "/path/to/logs/**/*.log"
"""

import argparse
import glob
import re
import sys
from collections import Counter
from pathlib import Path

from canvod.store import MyIcechunkStore

WRITE_STARTED_RE = re.compile(
    r"icechunk_write_data_started\s*\[action=(?P<action>\w+),.*?group=(?P<group>[\w./]+),"
)


def discover_vod_groups(store: MyIcechunkStore, branch: str = "main") -> list[str]:
    """Enumerate nested `{calculator}/{analysis_name}` VOD group paths.

    `store.list_groups()` only returns top-level keys (e.g. "tau_omega") --
    VOD analysis groups nest one level under that. Walk one level down to
    recover the full paths `write_or_append_vod_group` actually writes to.
    """
    import zarr

    nested: list[str] = []
    with store.readonly_session(branch) as session:
        root = zarr.open_group(session.store, mode="r")
        for top in store.list_groups(branch=branch):
            if top not in root:
                continue
            sub = root[top]
            if not hasattr(sub, "group_keys"):
                continue
            for name in sub.group_keys():
                nested.append(f"{top}/{name}")
    return nested


def scan_logs_for_write_history(log_glob: str) -> dict[str, Counter]:
    """Count action=write/append occurrences per group across log files.

    Log files are append-only across a run (unlike the store itself), so
    this is the only reliable source for "how many times did this group
    actually get written to" on a store that may have wiped its own
    metadata ledger along with the data.
    """
    paths = [Path(p) for p in glob.glob(log_glob, recursive=True)]
    per_group: dict[str, Counter] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for match in WRITE_STARTED_RE.finditer(text):
            group = match.group("group")
            action = match.group("action")
            per_group.setdefault(group, Counter())[action] += 1
    return per_group


def report_group(
    store: MyIcechunkStore,
    group_name: str,
    branch: str = "main",
    log_history: dict[str, Counter] | None = None,
) -> None:
    print(f"\n{'=' * 70}")
    print(f"Group: {group_name}")
    print("=" * 70)

    if log_history is not None:
        counts = log_history.get(group_name)
        if counts:
            n_write = counts.get("write", 0)
            n_append = counts.get("append", 0)
            total = sum(counts.values())
            print(
                f"\n  Log-derived write history: {total} attempt(s) across all log files"
            )
            print(
                f"    write={n_write}  append={n_append}  other={total - n_write - n_append}"
            )
            if n_write > 1:
                print(
                    f"\n  *** SMOKING GUN CONFIRMED (from logs): {n_write} 'write' "
                    f"events and only {n_append} 'append' events. Every write "
                    "after the first silently overwrote this group instead of "
                    "appending -- all data from every write except the last one "
                    "is gone. ***"
                )
            elif n_write == 1 and n_append == total - 1:
                print(
                    f"\n  Log history looks correct: 1 initial 'write' + "
                    f"{n_append} 'append'(s). This group does NOT show the bug "
                    "pattern."
                )
            else:
                print(
                    f"\n  Ambiguous log pattern: write={n_write}, append={n_append}, "
                    f"total={total}."
                )
        else:
            print("\n  No log entries found for this group in --log-glob.")

    df = store.load_metadata_for_dedup(group_name, branch=branch)
    if df is not None and df.height > 0:
        df = df.sort("written_at") if "written_at" in df.columns else df
        print(
            f"\n  On-disk metadata table right now: {df.height} row(s) -- NOTE: "
            "this only reflects what survived the LAST write to this group. If "
            "the bug fired, earlier rows were wiped along with the data, so a "
            "small row count here does NOT mean the bug didn't fire (see "
            "log-derived history above)."
        )
        for row in df.iter_rows(named=True):
            start = row.get("start")
            end = row.get("end")
            print(
                f"    [{row.get('written_at')}] action={row.get('action')!r:9} "
                f"range=({start} -> {end})"
            )
    else:
        print("\n  No metadata table currently present for this group.")

    # What's actually readable right now -- this is "how much valid data".
    try:
        ds = store.read_group(group_name, branch=branch)
        actual_epochs = ds.sizes.get("epoch", 0)
        if actual_epochs:
            actual_start = ds.epoch.min().values
            actual_end = ds.epoch.max().values
            print(
                f"\n  Actual data on disk right now: {actual_epochs:,} epochs, "
                f"{actual_start} -> {actual_end}"
            )
        else:
            print("\n  Actual data on disk right now: 0 epochs (empty group).")
    except Exception as exc:
        print(f"\n  Could not read group data: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("store_path", help="Path to the VOD Icechunk store")
    parser.add_argument("--branch", default="main", help="Branch to read from")
    parser.add_argument(
        "--group",
        default=None,
        help="One nested group path, e.g. tau_omega/canopy_01_vs_reference_01",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Report on every VOD group found in the store",
    )
    parser.add_argument(
        "--log-glob",
        default=None,
        help=(
            "Glob (recursive, e.g. '/path/to/logs/**/*.log') of pipeline log "
            "files to scan for the true write-attempt history per group. "
            "Strongly recommended -- the store's own metadata table can't be "
            "trusted alone (see module docstring)."
        ),
    )
    args = parser.parse_args()

    store = MyIcechunkStore(args.store_path)
    groups = discover_vod_groups(store, branch=args.branch)

    if not groups:
        print(f"No nested VOD analysis groups found under branch {args.branch!r}.")
        sys.exit(1)

    log_history = scan_logs_for_write_history(args.log_glob) if args.log_glob else None

    if args.group is None and not args.all:
        print(f"Found {len(groups)} VOD analysis group(s):")
        for g in groups:
            print(f"  {g}")
        print("\nRe-run with --group <name> or --all to inspect.")
        sys.exit(0)

    targets = groups if args.all else [args.group]
    for g in targets:
        if g not in groups:
            print(f"\nGroup {g!r} not found. Available: {groups}")
            continue
        report_group(store, g, branch=args.branch, log_history=log_history)


if __name__ == "__main__":
    main()
