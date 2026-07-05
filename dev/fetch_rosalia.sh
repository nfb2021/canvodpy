#!/usr/bin/env bash
# fetch_rosalia.sh — copy 4 weeks of 15-min RINEX from geo-jump-nbader
#
# Remote layout:
#   01_Rosalia/{rx}/01_GNSS/01_raw/{YYDDD}/*.{25o,25_}
# Local layout (matches existing Sample_data):
#   /Volumes/ExtremePro/Sample_data/{rx}/{YYDDD}/*.{25o,25_}
#
# Usage:
#   ./dev/fetch_rosalia.sh          # real transfer
#   ./dev/fetch_rosalia.sh --dry    # show what would be copied, no transfer

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
REMOTE_HOST="geo-jump-nbader"
REMOTE_BASE="/home/nbader/shares/climers/Studies/GNSS_Vegetation_Study/05_data/01_Rosalia"
LOCAL_BASE="/Volumes/ExtremePro/Sample_data"

RECEIVERS=("01_reference" "02_canopy")
YEAR="25"
START_DOY=1
N_DAYS=28   # 4 weeks

# ── Args ─────────────────────────────────────────────────────────────────────
DRY_FLAG=""
if [[ "${1:-}" == "--dry" ]]; then
    DRY_FLAG="--dry-run"
    echo "DRY RUN — listing what would be transferred, nothing written"
    echo ""
fi

# ── SSH multiplexing — one connection for all 56 rsync calls ─────────────────
SOCK="/tmp/fetch-rosalia-$$.sock"
SSH_CMD="ssh -o ControlMaster=auto -o ControlPath=${SOCK} -o ControlPersist=15m"
# Open the master connection once (prompts for password/key once if needed)
ssh -o ControlMaster=yes -o ControlPath="${SOCK}" -o ControlPersist=15m \
    -nNf "${REMOTE_HOST}" 2>/dev/null || true

cleanup() {
    ssh -O exit -o ControlPath="${SOCK}" "${REMOTE_HOST}" 2>/dev/null || true
}
trap cleanup EXIT

# ── Transfer ─────────────────────────────────────────────────────────────────
TOTAL_FILES=0
SKIPPED=()

for rx in "${RECEIVERS[@]}"; do
    echo "── ${rx} ──────────────────────────────────────────────"
    for i in $(seq "${START_DOY}" $((START_DOY + N_DAYS - 1))); do
        DOY=$(printf "%s%03d" "${YEAR}" "${i}")
        REMOTE_DIR="${REMOTE_BASE}/${rx}/01_GNSS/01_raw/${DOY}"
        LOCAL_DIR="${LOCAL_BASE}/${rx}/${DOY}"

        # Create local dir (will be removed on failure if dry-run skips it)
        [[ -z "${DRY_FLAG}" ]] && mkdir -p "${LOCAL_DIR}"

        echo -n "  ${DOY} ... "

        if rsync -az \
            --include="*.${YEAR}o" \
            --include="*.${YEAR}_" \
            --exclude="*" \
            -e "${SSH_CMD}" \
            ${DRY_FLAG} \
            "${REMOTE_HOST}:${REMOTE_DIR}/" \
            "${LOCAL_DIR}/" \
            2>/dev/null; then

            if [[ -n "${DRY_FLAG}" ]]; then
                echo "ok (dry)"
            else
                N=$(find "${LOCAL_DIR}" \( -name "*.${YEAR}o" -o -name "*.${YEAR}_" \) 2>/dev/null | wc -l | tr -d ' ')
                echo "${N} files"
                TOTAL_FILES=$((TOTAL_FILES + N))
            fi
        else
            echo "MISSING on remote — skipped"
            SKIPPED+=("${rx}/${DOY}")
            # Clean up empty dir we may have created
            [[ -z "${DRY_FLAG}" ]] && rmdir "${LOCAL_DIR}" 2>/dev/null || true
        fi
    done
done

echo ""
if [[ -z "${DRY_FLAG}" ]]; then
    echo "Done. ${TOTAL_FILES} .25o/.25_ files now in ${LOCAL_BASE}"
fi
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
    echo "Missing on remote (${#SKIPPED[@]} DOYs):"
    printf '  %s\n' "${SKIPPED[@]}"
fi
