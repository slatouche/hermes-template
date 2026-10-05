#!/bin/bash
# Screenshots of the live app with a design variant on, in seconds (headless Chromium through the review link).
#
#   variant-shot.sh <variant|current> [page path, e.g. "/#/deck/cidding"] [--app <name>] [--all]
#
# <variant> is a folder in ~/vault/design/variants/ (style.css, optional script.js and note.md); "current" shoots the
# app as it is today into variants/current/ for side-by-side comparison. Writes <page>-390.png and <page>-1440.png
# (--all adds 834) into the variant's folder; the owner sees them at http://<host>:<review port>/__mark/variants.
set -euo pipefail
V="${1:?usage: variant-shot.sh <variant|current> [path] [--app <name>] [--all]}"; shift
PAGE="/"; APP=""; WIDTHS="390x844 1440x900"
while [ $# -gt 0 ]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    --all) WIDTHS="390x844 834x1112 1440x900"; shift ;;
    *) PAGE="$1"; shift ;;
  esac
done
CONF="$HOME/.hermes/scripts/review-mirrors.conf"
[ -f "$CONF" ] || { echo "no review links yet ($CONF): the app needs one first" >&2; exit 1; }
if [ -n "$APP" ]; then PORT=$(grep -v '^\s*#' "$CONF" | grep -i -- "$APP" | awk 'NR==1{print $1}')
else PORT=$(grep -v '^\s*#' "$CONF" | grep -vi 'design' | awk 'NF>=2 && $1 ~ /^[0-9]+$/ {print $1; exit}'); fi
[ -n "${PORT:-}" ] || { echo "no review link matches ${APP:-an app} in $CONF" >&2; exit 1; }
SB="$HOME/.hermes/scripts/sandboxes.conf"     # shoot the design sandbox when there is one (same code snapshot the owner sees)
if [ -f "$SB" ]; then
  SPORT=$(grep -v '^\s*#' "$SB" | grep -i -- "${APP:-}" | awk -F'|' 'NR==1{print $2}')
  [ -n "${SPORT:-}" ] && PORT=$((SPORT + 50))
fi
CHROME=$(ls -d "$HOME"/.hermes/tools/chromium-*/chrome-linux64/chrome 2>/dev/null | tail -1)
[ -x "${CHROME:-}" ] || { echo "no headless Chromium under ~/.hermes/tools (the browser tool installs it on first use)" >&2; exit 1; }

DIR="$HOME/vault/design/variants/$V"
mkdir -p "$DIR"
[ "$V" = current ] && [ ! -f "$DIR/note.md" ] && printf '# The current look\nThe app as it is today, for comparison.\n' > "$DIR/note.md"
[ "$V" = current ] && SW=off || SW="$V"
[ "$V" = current ] || [ -f "$DIR/style.css" ] || [ -f "$DIR/script.js" ] || { echo "$DIR has no style.css or script.js" >&2; exit 1; }

base="${PAGE%%#*}"; hash=""; [[ "$PAGE" == *"#"* ]] && hash="#${PAGE#*#}"
[[ "$base" == *"?"* ]] && sep="&" || sep="?"
URL="http://127.0.0.1:$PORT${base:-/}${sep}__variant=$SW&__shot=1$hash"
printf '%s\n' "$PAGE" > "$DIR/page.txt"   # the variants page opens "try it live" on this screen
slug=$(printf '%s' "$PAGE" | tr -c 'A-Za-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//'); slug="${slug:-home}"
for wh in $WIDTHS; do
  out="$DIR/$slug-${wh%x*}.png"
  timeout 60 "$CHROME" --headless=new --no-sandbox --disable-gpu --hide-scrollbars --virtual-time-budget=6000 \
    --window-size="${wh/x/,}" --screenshot="$out" "$URL" >/dev/null 2>&1 || true
  [ -s "$out" ] && echo "$out" || echo "failed: $out" >&2
done
echo "compare: http://<host>:$PORT/__mark/variants"
