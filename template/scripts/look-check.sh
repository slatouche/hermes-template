#!/bin/bash
# Check a design change in one step: open a page with a look on (the mockup) or a demo, at a size, evaluate the
# checks, and take a screenshot. Prints the results as JSON. One call instead of open, measure, re-measure, shoot.
#
#   look-check.sh <look|current> [page path] [--size WxH] [--app <name>] [--demo <1|2>] [--port <review port>] --js '<expression>' [--js ...]
#   (--port: any review link, e.g. the real app's after a build, to compare it with the mockup)
#
#   look-check.sh atlas-air "/#/deck/My%20Deck" --size 1278x945 \
#     --js 'getComputedStyle(document.querySelector(".rail")).width' \
#     --js 'document.querySelectorAll(".info-btn").length'
#
# The screenshot lands in the look's folder (or design/demo-checks/) as check-<page>.png. The browser runs in the
# feedback-inbox service (it can crash inside a bot's terminal).
set -euo pipefail
V="${1:?usage: look-check.sh <look|current> [path] [--size WxH] [--app <name>] [--demo <1|2>] --js '<expr>' ...}"; shift
PAGE="/"; APP=""; SIZE="1440x900"; DEMO=""; FORCE_PORT=""; JS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --size) SIZE="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --demo) DEMO="$2"; shift 2 ;;
    --port) FORCE_PORT="$2"; shift 2 ;;
    --js) JS+=("$2"); shift 2 ;;
    *) PAGE="$1"; shift ;;
  esac
done
CONF="$HOME/.hermes/scripts/review-mirrors.conf"
api=$(grep -m1 '^API_SERVER_PORT=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2 || true)
[ -n "$api" ] || { echo "no API_SERVER_PORT in ~/.hermes/.env" >&2; exit 1; }
if [ -n "$DEMO" ]; then
  PORT=$((api + 45 + DEMO + 50))                  # the demo slot's review link (see demo.sh)
  OUTDIR="$HOME/vault/design/demo-checks"
else
  PORT=$(grep -v '^\s*#' "$CONF" 2>/dev/null | grep -viE 'design|demo|mockup' | awk 'NF>=2 && $1 ~ /^[0-9]+$/ {print $1; exit}')
  MK="$HOME/.hermes/scripts/mockups.conf"
  if [ -f "$MK" ]; then
    MPORT=$(grep -v '^\s*#' "$MK" | grep -i -- "${APP:-}" | awk -F'|' 'NR==1{print $2}')
    [ -n "${MPORT:-}" ] && PORT=$((MPORT + 50))
  fi
  OUTDIR="$HOME/vault/design/variants/$V"
  [ "$V" = current ] || [ -d "$OUTDIR" ] || { echo "no look $V" >&2; exit 1; }
fi
[ -n "$FORCE_PORT" ] && PORT="$FORCE_PORT"
[ -n "${PORT:-}" ] || { echo "no review link found" >&2; exit 1; }
mkdir -p "$OUTDIR"
base="${PAGE%%#*}"; hash=""; [[ "$PAGE" == *"#"* ]] && hash="#${PAGE#*#}"
[[ "$base" == *"?"* ]] && sep="&" || sep="?"
[ "$V" = current ] && SW=off || SW="$V"
URL="http://127.0.0.1:$PORT${base:-/}${sep}__variant=$SW&__shot=1$hash"; URL="${URL//\'/%27}"
slug=$(printf '%s' "${PAGE//%[0-9A-Fa-f][0-9A-Fa-f]/-}" | tr -c 'A-Za-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//' | cut -c1-40)
SHOT="$OUTDIR/check-${slug:-home}.png"
req=$(python3 -c 'import json,sys; w,h=sys.argv[2].split("x"); print(json.dumps({"url": sys.argv[1], "width": int(w), "height": int(h), "shot": sys.argv[3], "js": sys.argv[4:]}))' "$URL" "$SIZE" "$SHOT" "${JS[@]}")
curl -fs -m 300 -H 'Content-Type: application/json' -d "$req" "http://127.0.0.1:$((api + 99))/check"
echo
