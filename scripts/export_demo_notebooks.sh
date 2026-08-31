#!/usr/bin/env bash
# Export the demo/ marimo notebooks for embedding in the docs site.
#
# All notebooks export via `marimo export html`: a real Python execution
# against real test data at build time, frozen into static HTML with the
# source code included by default (--include-code is marimo's default).
#
# `marimo export html-wasm` (live, in-browser via Pyodide) was tried first
# but rejected: its default "run" mode hides code entirely (app-mode UX),
# and neither `--show-code` nor `--mode edit` fit -- code is the whole
# point of these notebooks, and duplicating it into markdown text to force
# visibility would make the notebooks clunky to maintain. Static HTML
# already shows code, so there is no live/static split to make here.
#
# See dev/notebook_docs_integration_plan.md for the full writeup.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$REPO_ROOT/demo"
OUT_DIR="$REPO_ROOT/docs/notebooks/_build"

NOTEBOOKS=(
    00_cli_quickstart
    01_naming_convention
    02_rinex_reading
    03_satellite_catalog
    04_sbf_reading
    05_ephemeris_coordinates
    06_hemispheric_grids
    07_vod_retrieval
    09_store_metadata
    10_visualization
    11_configuration
    12_api_overview
    13_site_pipeline
    14_functional_api
    15_single_day_python
    16_batch_processing
    18_grid_exploration
)

# 08_icechunk_store and 17_store_operations are intentionally excluded here:
# their bundled `rosalia_rinex` store fixture is an empty first-commit
# snapshot with no populated data, so `marimo export html` fails with
# `IcechunkError: object not found` before ever reaching this script.
# Pre-existing, not introduced by this export pipeline -- fix the fixture,
# then add both names to NOTEBOOKS above.
SKIPPED_NOTEBOOKS=(
    08_icechunk_store
    17_store_operations
)

mkdir -p "$OUT_DIR"
cd "$DEMO_DIR"

# Notebooks run with `demo/` as cwd, a separate git submodule -- the
# monorepo-root autodetection in canvod.config.get_default_config_dir()
# can't see past that boundary, so bare `load_config()` calls would
# otherwise fall through to the XDG default and fail on machines with no
# global ~/.config/canvodpy/canvod-settings.yaml. Point it at the real one.
export CANVOD_CONFIG_DIR="$REPO_ROOT/config"

echo "== Static HTML exports, code included (${#NOTEBOOKS[@]}) =="
for nb in "${NOTEBOOKS[@]}"; do
    echo "-- $nb"
    if [ "$nb" = "00_cli_quickstart" ]; then
        # This notebook gates its pipeline run behind an mo.ui.run_button(),
        # which can never be "clicked" during a non-interactive export --
        # bypass the gate so the static docs page shows a real run.
        CANVOD_DEMO_RUN_PIPELINE=1 uv run --project "$REPO_ROOT" marimo export html "${nb}.py" -o "$OUT_DIR/${nb}.html"
    else
        uv run --project "$REPO_ROOT" marimo export html "${nb}.py" -o "$OUT_DIR/${nb}.html"
    fi
done

echo "== Skipped (pre-existing store-fixture failure, see comment above) =="
for nb in "${SKIPPED_NOTEBOOKS[@]}"; do
    echo "-- $nb (not exported)"
done

echo "Done. Output in $OUT_DIR"
