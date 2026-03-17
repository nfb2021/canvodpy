#!/usr/bin/env bash
# Render all .mmd diagrams to 3 SVG variants each:
#   <stem>-light.svg              (solid light background)
#   <stem>-dark.svg               (solid dark background)
#   <stem>-transparent.svg        (no background — embeds cleanly on any surface)
#
# Sources:  ../          (main diagrams)
#           ../paper/    (paper diagrams → stored in paper/ subdir)
# Output:   ./           (test/)
#           ./paper/
#
# Usage: ./render.sh

set -euo pipefail

SCRIPT="/Users/work/.agents/skills/beautiful-mermaid/scripts/render.ts"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # docs/diagrams/
OUT="$(cd "$(dirname "$0")" && pwd)"       # docs/diagrams/test/

mkdir -p "$OUT/paper"

# ---------------------------------------------------------------------------
make_transparent() {
  local src="$1" dst="$2"
  python3 - "$src" "$dst" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f: s = f.read()
# Remove background:var(--bg) from the SVG element's inline style
s = re.sub(r';?background:[^;"\']+', '', s)
with open(dst, 'w') as f: f.write(s)
PY
}

render_dir() {
  local SRC="$1"   # source dir containing .mmd files
  local DST="$2"   # output dir for SVGs

  for mmd in "$SRC"/*.mmd; do
    [[ -f "$mmd" ]] || continue
    base="$(basename "$mmd" .mmd)"
    echo "── $base ──"

    npx tsx "$SCRIPT" --input "$mmd" --output "$DST/${base}-light" --theme default \
      2>&1 | grep -E "SVG written|Error"
    npx tsx "$SCRIPT" --input "$mmd" --output "$DST/${base}-dark"  --theme github-dark \
      2>&1 | grep -E "SVG written|Error"

    make_transparent "$DST/${base}-light.svg" "$DST/${base}-transparent.svg"
    echo "  transparent → ${base}-transparent.svg"
  done
}

echo "=== Main diagrams ==="
render_dir "$ROOT" "$OUT"

echo ""
echo "=== Paper diagrams ==="
render_dir "$ROOT/paper" "$OUT/paper"

echo ""
echo "=== Dimensions (light variants) ==="
python3 - "$OUT" "$OUT/paper" <<'PY'
import re, sys
from pathlib import Path
for d in sys.argv[1:]:
    for svg in sorted(Path(d).glob("*-light.svg")):
        s = svg.read_text()[:400]
        w = re.search(r'width="([\d.]+)"', s)
        h = re.search(r'height="([\d.]+)"', s)
        if w and h:
            W, H = float(w.group(1)), float(h.group(1))
            tag = "[paper] " if "paper" in str(svg) else "        "
            print(f"  {tag}{svg.stem:<45}  {W:.0f}x{H:.0f}  ratio={W/H:.2f}")
PY
