#!/usr/bin/env bash
# fetch_rosalia.sh — copy 15-min RINEX (.25o only) from geo-jump-nbader
#
# Remote layout:
#   01_Rosalia/{rx}/01_GNSS/01_raw/{YYDDD}/*.25o
# Local layout (matches the live canvodpy-perf local test setup):
#   /Volumes/ExtremePro/canvodpy_stresstest/ROS_tmp_data/01_Rosalia/{rx}/01_GNSS/01_raw/{YYDDD}/*.25o
#
# Idempotent: --ignore-existing means already-present local files are never
# re-touched, so it's always safe to re-run after widening START_DOY/N_DAYS
# or after a partial/interrupted transfer -- it only ever fills gaps.
#
# Usage:
#   ./dev/fetch_rosalia.sh          # real transfer
#   ./dev/fetch_rosalia.sh --dry    # show what would be copied, no transfer

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
REMOTE_HOST="geo-jump-nbader"
REMOTE_BASE="/home/nbader/shares/climers/Studies/GNSS_Vegetation_Study/05_data/01_Rosalia"
LOCAL_BASE="/Volumes/ExtremePro/canvodpy_stresstest/ROS_tmp_data/01_Rosalia"

# {local receiver dir}:{path suffix under it, before the DOY dir}
RECEIVERS=("01_reference:01_GNSS/01_raw" "02_canopy:01_GNSS/01_raw" "03_canopy_ext1:01_GNSS/01_raw")
YEAR="25"
START_DOY=87
N_DAYS=177   # 2025087 .. 2025300 -- covers the existing 142-264+ range plus room to grow

# ── Args ─────────────────────────────────────────────────────────────────────
DRY_FLAG=""
if [[ "${1:-}" == "--dry" ]]; then
    DRY_FLAG="--dry-run"
    echo "DRY RUN — listing what would be transferred, nothing written"
    echo ""
fi

# ── SSH multiplexing — one connection for every rsync call below ─────────────
SOCK="/tmp/fetch-rosalia-$$.sock"
SSH_CMD="ssh -o ControlMaster=auto -o ControlPath=${SOCK} -o ControlPersist=15m"
# geo-jump-nbader is a 3-hop ProxyCommand chain (ssh.geo.tuwien.ac.at ->
# linuxs2.geo.tuwien.ac.at -> nbader). Open the master connection FIRST, in
# the foreground, with a real remote command (not -N) so it can interactively
# prompt for each hop's password -- ControlPersist then keeps this connection
# alive in the background afterward for every rsync call to reuse.
# Deliberately NOT -f/-nNf here: -f implies -n (stdin -> /dev/null) for ANY
# ssh invocation, which silently blocks password prompts across a multi-hop
# chain -- that was the actual bug (every rsync call re-authenticating all
# 3 hops from scratch instead of reusing one cached connection).
echo "Opening SSH connection to ${REMOTE_HOST} (3 hops -- may prompt for a password at each)..."
if ! ssh -o ControlMaster=yes -o ControlPath="${SOCK}" -o ControlPersist=15m \
    "${REMOTE_HOST}" true; then
    echo "ERROR: could not establish SSH connection to ${REMOTE_HOST}" >&2
    exit 1
fi
echo "Connected -- reusing this session for all transfers below."
echo ""

cleanup() {
    ssh -O exit -o ControlPath="${SOCK}" "${REMOTE_HOST}" 2>/dev/null || true
}
trap cleanup EXIT

# ── Transfer ─────────────────────────────────────────────────────────────────
TOTAL_FILES=0
SKIPPED=()

for entry in "${RECEIVERS[@]}"; do
    rx="${entry%%:*}"
    rx_suffix="${entry#*:}"
    echo "── ${rx} ──────────────────────────────────────────────"
    for i in $(seq "${START_DOY}" $((START_DOY + N_DAYS - 1))); do
        DOY=$(printf "%s%03d" "${YEAR}" "${i}")
        REMOTE_DIR="${REMOTE_BASE}/${rx}/${rx_suffix}/${DOY}"
        LOCAL_DIR="${LOCAL_BASE}/${rx}/${rx_suffix}/${DOY}"

        echo -n "  ${DOY} ... "

        if [[ -n "${DRY_FLAG}" ]]; then
            # --dry-run needs the target dir to exist for rsync to compare against;
            # doesn't write anything either way.
            mkdir -p "${LOCAL_DIR}"
            if rsync -az --ignore-existing \
                --include="*.${YEAR}o" \
                --exclude="*" \
                -e "${SSH_CMD}" \
                ${DRY_FLAG} \
                "${REMOTE_HOST}:${REMOTE_DIR}/" \
                "${LOCAL_DIR}/" \
                2>/dev/null; then
                echo "ok (dry)"
            else
                echo "MISSING on remote — skipped"
                SKIPPED+=("${rx}/${DOY}")
            fi
            continue
        fi

        # Real transfer: let rsync create LOCAL_DIR itself (its parent already
        # exists). Don't pre-mkdir -- that's what left empty dirs behind before,
        # since rsync exits 0 even when the remote day is empty / has nothing
        # matching the include filters, not just on a genuinely missing dir.
        mkdir -p "$(dirname "${LOCAL_DIR}")"
        rsync -az --ignore-existing \
            --include="*.${YEAR}o" \
            --exclude="*" \
            -e "${SSH_CMD}" \
            "${REMOTE_HOST}:${REMOTE_DIR}/" \
            "${LOCAL_DIR}/" \
            2>/dev/null || true

        # Guard against a nonexistent LOCAL_DIR (rsync can fail hard enough
        # not to create it at all) -- under `set -o pipefail`, `find` erroring
        # on a missing dir kills the whole script here otherwise, silently
        # (its stderr is suppressed), with no indication which DOY it died on.
        N=0
        if [[ -d "${LOCAL_DIR}" ]]; then
            N=$(find "${LOCAL_DIR}" -name "*.${YEAR}o" 2>/dev/null | wc -l | tr -d ' ')
        fi
        if [[ "${N}" -gt 0 ]]; then
            echo "${N} files"
            TOTAL_FILES=$((TOTAL_FILES + N))
        else
            echo "no data on remote — skipped"
            SKIPPED+=("${rx}/${DOY}")
            # No matching files ended up here, whether the remote day was
            # missing entirely or just had nothing worth keeping -- never
            # leave an empty dir behind.
            rmdir "${LOCAL_DIR}" 2>/dev/null || true
        fi
    done
done

echo ""
if [[ -z "${DRY_FLAG}" ]]; then
    echo "Done. ${TOTAL_FILES} .25o files now in ${LOCAL_BASE}"
fi
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
    echo "Missing on remote (${#SKIPPED[@]} DOYs):"
    printf '  %s\n' "${SKIPPED[@]}"
fi
