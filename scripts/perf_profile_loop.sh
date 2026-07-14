#!/usr/bin/env bash
# Unattended, continuous py-spy profiling for a long-running canvodpy
# process (e.g. an overnight backfill). Runs until the target PID exits --
# no manual timing needed, safe to start with nohup and walk away.
#
# Uses `--format speedscope` rather than the default flamegraph: a
# flamegraph aggregates every sample into one blended picture, which loses
# exactly what we need (was function X slow only during the spike, or all
# the time?). speedscope keeps a scrubbable timeline per chunk, so you can
# jump straight to the minute a spike happened and see the live call stack
# then -- view at https://speedscope.app (drag-and-drop the .json file).
#
# Recording is chunked (default 1h) rather than one giant multi-hour file
# purely to bound memory/file size and survive a crash without losing
# everything already captured -- chunks run back-to-back with zero gap by
# default, so coverage is continuous, not sampled every N minutes.
#
# Usage:
#   ./scripts/perf_profile_loop.sh <PID> [OUTPUT_DIR] [CHUNK_SEC] [RATE] [GAP_SEC] [FORMAT]
#
# Defaults: OUTPUT_DIR=./perf_profiles CHUNK_SEC=3600 RATE=50 GAP_SEC=0 FORMAT=speedscope
#
# Example (find the canvodpy run PID, then launch detached so it survives
# logout / going to sleep):
#
#   PID=$(pgrep -of "canvodpy run")
#   nohup sudo ./scripts/perf_profile_loop.sh "$PID" ~/canvod-logs/profiles \
#       > ~/canvod-logs/profiles/loop.log 2>&1 &
#
# Requires py-spy (`uv tool install py-spy` / `pipx install py-spy`) and
# typically root/ptrace privileges to attach to another process -- run
# the whole script with sudo rather than trying to sudo-wrap just the
# py-spy call (keeps output file ownership simple).
set -euo pipefail

PID="${1:?Usage: $0 <PID> [OUTPUT_DIR] [CHUNK_SEC] [RATE] [GAP_SEC] [FORMAT]}"
OUTPUT_DIR="${2:-./perf_profiles}"
CHUNK_SEC="${3:-3600}"
RATE="${4:-50}"
GAP_SEC="${5:-0}"
FORMAT="${6:-speedscope}"

EXT="json"
if [ "$FORMAT" = "flamegraph" ]; then
    EXT="svg"
fi

if ! command -v py-spy &>/dev/null; then
    echo "py-spy not found on PATH. Install with: uv tool install py-spy" >&2
    exit 1
fi

if ! kill -0 "$PID" 2>/dev/null; then
    echo "PID $PID is not running (or not visible to this user/permissions)." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Watching PID $PID. Recording ${CHUNK_SEC}s ${FORMAT} chunks (gap=${GAP_SEC}s) into $OUTPUT_DIR"
echo "Stops automatically once PID $PID exits."

chunk_n=0
while kill -0 "$PID" 2>/dev/null; do
    chunk_n=$((chunk_n + 1))
    ts="$(date +%Y%m%d_%H%M%S)"
    out="$OUTPUT_DIR/profile_${ts}_n${chunk_n}.${EXT}"
    echo "[$ts] chunk #$chunk_n -> $out"

    if py-spy record -o "$out" --format "$FORMAT" --pid "$PID" --subprocesses \
        --rate "$RATE" --duration "$CHUNK_SEC" 2>>"$OUTPUT_DIR/py-spy.err"; then
        echo "[$ts] chunk #$chunk_n complete"
    else
        echo "[$ts] chunk #$chunk_n FAILED (process may have exited mid-capture)" \
            "-- see $OUTPUT_DIR/py-spy.err"
    fi

    if [ "$GAP_SEC" -gt 0 ]; then
        # Sleep in short steps so a process exit is noticed promptly
        # instead of waiting out the whole gap.
        slept=0
        while [ "$slept" -lt "$GAP_SEC" ] && kill -0 "$PID" 2>/dev/null; do
            sleep 10
            slept=$((slept + 10))
        done
    fi
done

echo "PID $PID no longer running. Recorded $chunk_n chunk(s) in $OUTPUT_DIR."
