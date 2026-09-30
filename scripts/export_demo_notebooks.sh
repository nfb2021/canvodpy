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

mkdir -p "$OUT_DIR"
cd "$DEMO_DIR"

# Notebooks run with `demo/` as cwd, a separate git submodule -- the
# monorepo-root autodetection in canvod.config.get_default_config_dir()
# can't see past that boundary, so bare `load_config()` calls would
# otherwise fall through to the XDG default and fail on machines with no
# global ~/.config/canvodpy/canvod-settings.yaml. Point it at the real one.
export CANVOD_CONFIG_DIR="$REPO_ROOT/config"

# Every numbered notebook in demo/ (NN_name.py), so renaming or adding a
# notebook there needs no change here. 08 and 18 build their Icechunk
# store at run time with the canvodpy CLI (demo/_live_store.py), so no
# notebook is skipped.
NOTEBOOKS=([0-9][0-9]_*.py)

echo "== Static HTML exports, code included (${#NOTEBOOKS[@]}) =="
for nb in "${NOTEBOOKS[@]}"; do
    echo "-- ${nb%.py}"
    uv run --project "$REPO_ROOT" marimo export html "$nb" -o "$OUT_DIR/${nb%.py}.html"
done

echo "Done. Output in $OUT_DIR"
