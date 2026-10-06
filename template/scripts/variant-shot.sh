#!/bin/bash
# Screenshots of the live app with a design variant on, in seconds (headless Chromium through the review link).
#
#   variant-shot.sh <variant|current> [page path, e.g. "/#/deck/cidding"] [--app <name>] [--size WxH] [--all]
#
# <variant> is a folder in ~/vault/design/variants/ (style.css, optional script.js and note.md); "current" shoots the
# app as it is today into variants/current/ for side-by-side comparison. Writes <page>-1440.png (desktop; --size WxH for
# the owner's size, --all for phone, tablet and desktop in the responsive pass) into the variant's folder; the owner sees them at http://<host>:<review port>/__mark/variants.
set -euo pipefail
V="${1:?usage: variant-shot.sh <variant|current> [path] [--app <name>] [--size WxH] [--all]}"; shift
PAGE="/"; APP=""; WIDTHS="1440x900"   # desktop while designing; --all for the responsive pass
while [ $# -gt 0 ]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    --all) WIDTHS="390x844 834x1112 1440x900"; shift ;;
    --size) WIDTHS="$2"; shift 2 ;;
    *) PAGE="$1"; shift ;;
  esac
done
CONF="$HOME/.hermes/scripts/review-mirrors.conf"
[ -f "$CONF" ] || { echo "no review links yet ($CONF): the app needs one first" >&2; exit 1; }
if [ -n "$APP" ]; then PORT=$(grep -v '^\s*#' "$CONF" | grep -i -- "$APP" | awk 'NR==1{print $1}')
else PORT=$(grep -v '^\s*#' "$CONF" | grep -viE 'design|demo|mockup' | awk 'NF>=2 && $1 ~ /^[0-9]+$/ {print $1; exit}'); fi
[ -n "${PORT:-}" ] || { echo "no review link matches ${APP:-an app} in $CONF" >&2; exit 1; }
SB="$HOME/.hermes/scripts/mockups.conf"       # shoot the mockup when there is one (the same snapshot the owner sees)
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
URL="${URL//\'/%27}"                         # an apostrophe in a #route stops the browser
printf '%s\n' "$PAGE" > "$DIR/page.txt"   # the variants page opens "try it live" on this screen
slug=$(printf '%s' "${PAGE//%[0-9A-Fa-f][0-9A-Fa-f]/-}" | tr -c 'A-Za-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//' | cut -c1-40)
slug="${slug:-home}"
# The bots' browser (agent-browser) first: plain headless Chrome can crash inside a bot's terminal sandbox.
AB=$(ls -d "$HOME"/.hermes/tools/agent-browser-*/bin/agent-browser-linux-* 2>/dev/null | tail -1)
export AGENT_BROWSER_EXECUTABLE_PATH="$CHROME" AGENT_BROWSER_ARGS="--no-sandbox"
for wh in $WIDTHS; do
  out="$DIR/$slug-${wh%x*}.png"; rm -f "$out"
  if [ -n "$AB" ]; then
    { "$AB" --session variantshot set viewport "${wh%x*}" "${wh#*x}" && "$AB" --session variantshot open "$URL" \
      && "$AB" --session variantshot wait 1500 && "$AB" --session variantshot screenshot "$out"; } >/dev/null 2>&1 || true
  fi
  [ -s "$out" ] || timeout 60 "$CHROME" --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars \
    --virtual-time-budget=6000 --window-size="${wh/x/,}" --screenshot="$out" "$URL" >/dev/null 2>&1 || true
  [ -s "$out" ] && echo "$out" || echo "failed: $out" >&2
done
[ -n "$AB" ] && "$AB" --session variantshot close >/dev/null 2>&1 || true
echo "compare: http://<host>:$PORT/__mark/variants"
