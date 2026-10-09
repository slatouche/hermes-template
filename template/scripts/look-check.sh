#!/bin/bash
# Check a design change in one step: open a page with a look on (the mockup) or a demo, at a size, evaluate the
# checks, and take a screenshot. Prints the results as JSON. One call instead of open, measure, re-measure, shoot.
#
#   look-check.sh <look|current> [page path] [--size WxH] [--app <name>] [--demo <1|2>] [--port <review port>] [--no-overlay] [--js '<expression>' | --drag '<selector> -> <x>,<y>'] ...
#   (--port: any review link, e.g. the real app's after a build, to compare it with the mockup)
#
#   look-check.sh atlas-air "/#/deck/My%20Deck" --size 1278x945 \
#     --js 'getComputedStyle(document.querySelector(".rail")).width' \
#     --js 'document.querySelectorAll(".info-btn").length'
#
# The page carries the Mark overlay exactly as the owner sees it — the round chip, the boxes, the note bar and the
# left badge with its toolbar — so a --js check can trust what is on screen. They live in the overlay's open shadow
# root, so a plain document.querySelectorAll misses them. Read them with the deep helpers the check pre-defines:
#   look-check.sh atlas-air "/" --js "__markCount('.round,.cbar,.mtools,.mbadge')"      # count, shadow roots included
#   look-check.sh atlas-air "/" --js "getComputedStyle(__markQ('.round')).borderRadius"
# A drag is a step, run in the order you write it, and the --js after it sees what moved. It is a REAL pointer: the
# pointer goes down inside the element, moves to the target and lifts (CDP Input.dispatchMouseEvent with the button
# held down, and the check reports the trusted press-move-release it saw), so the page's own drag handler runs —
# never a scripted move. '<selector> -> <x>,<y>' puts the element's top-left corner at x,y; the step reports where
# it landed and the miss, because the pointer moves in whole pixels (a real mouse does too), so a box whose own
# layout sits on a fraction of a pixel lands that fraction off. A drag with no distance is a plain click and must
# move nothing. Repeatable, and mixing it with --js is what proves it did something:
#   look-check.sh atlas-air "/" --drag ".round -> 300,300" --js "__markQ('.round').getBoundingClientRect().x"
# --no-overlay asks for the opposite (a picture with no overlay UI in it); only pictures need that, a check does not.
#
# Real input: anything the owner types into, or clicks, is checked with a REAL mouse click at the element's centre
# and REAL per-character key events (CDP Input.dispatchMouseEvent / Input.dispatchKeyEvent), never by assigning
# `.value`. A scripted `.value =` is NOT evidence that the owner can type. Use it for every verdict about a typing
# box or a button; the box is reported as blocked if a real click fails to focus it. Selectors reach inside the
# overlay's open shadow root.
#
#   look-check.sh --type '<selector>' '<text>' --url <url>
#   look-check.sh --type '.rbar textarea' 'hello' --url http://127.0.0.1:<demo port>/
#   look-check.sh --click '<selector>' --url <url> --expect '<js, truthy when the click worked>'
#   look-check.sh --click '.bar .mark' --url http://127.0.0.1:<demo port>/ \
#     --expect '[...document.documentElement.children].find(e=>e.shadowRoot&&e.shadowRoot.querySelector(".mark")).shadowRoot.querySelector(".mark").classList.contains("on")'
#   --js expressions also run in these modes (side effects included): inject a transparent blocker over the box to
#   prove the check has teeth (it must FAIL).
#   Exit 0 = PASS, 1 = FAIL (box blocked / not focusable / expectation false).
#
# The screenshot lands in the look's folder (or design/demo-checks/) as check-<page>.png. The browser runs in the
# feedback-inbox service (it can crash inside a bot's terminal). The real-input modes run their browser as a
# transient systemd user unit (systemd-run), the same way the service runs it, so Chrome is not killed by the
# bot's sandbox.
set -euo pipefail
V=""; PAGE="/"; APP=""; SIZE="1440x900"; DEMO=""; FORCE_PORT=""; NO_OVERLAY=""; JS=()
TYPE_SEL=""; TYPE_TEXT=""; CLICK_SEL=""; EXPECT=""; URL=""
KIND=(); VAL=()                       # a look check's steps, in the order they were written: js | drag
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE_SEL="${2:?--type needs a selector}"; TYPE_TEXT="${3:?--type needs text}"; shift 3 ;;
    --click) CLICK_SEL="${2:?--click needs a selector}"; shift 2 ;;
    --expect) EXPECT="${2:?--expect needs a js expression}"; shift 2 ;;
    --url) URL="${2:?--url needs a url}"; shift 2 ;;
    --size) SIZE="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --demo) DEMO="$2"; shift 2 ;;
    --port) FORCE_PORT="$2"; shift 2 ;;
    --no-overlay) NO_OVERLAY=1; shift ;;
    --drag) KIND+=(drag); VAL+=("$2"); shift 2 ;;
    --js) JS+=("$2"); KIND+=(js); VAL+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
    *) if [ -z "$V" ]; then V="$1"; else PAGE="$1"; fi; shift ;;
  esac
done

# ---- real-input mode: a real click (+ real key events) then read the state back ------------------------------
if [ -n "$TYPE_SEL" ] || [ -n "$CLICK_SEL" ]; then
  if [ ${#KIND[@]} -gt 0 ] && printf '%s\n' "${KIND[@]}" | grep -qx drag; then
    echo "look-check: --drag is a look-mode step and this mode is the real-input one (--type/--click);" >&2
    echo "run the drag as its own check: look-check.sh <look|current> [path] --drag '<selector> -> <x>,<y>' --js '...'" >&2
    exit 2
  fi
  command -v systemd-run >/dev/null || { echo "look-check: real-input mode needs systemd-run (the browser must " \
    "run outside the bot's sandbox); use the feedback inbox service instead." >&2; exit 2; }
  [ -n "$URL" ] || { echo "look-check: --type/--click need --url <the page to open>" >&2; exit 2; }
  MODE=type; SEL="$TYPE_SEL"; TXT="$TYPE_TEXT"
  if [ -n "$CLICK_SEL" ]; then MODE=click; SEL="$CLICK_SEL"; fi
  TMP=$(mktemp "${TMPDIR:-/tmp}/look-type-XXXXXX.sh")
  cat > "$TMP" <<'INNER_EOF'
#!/bin/bash
# Runs inside a transient systemd user unit (outside the bot sandbox), so Chrome can start.
set -uo pipefail
MODE="$1"; URL="$2"; SEL="$3"; TXT="$4"; SIZE="$5"; EXPECT="$6"; shift 6
HOMEDIR="$HOME"
CH=$(ls "$HOMEDIR"/.hermes/tools/chromium-*/chrome-linux64/chrome 2>/dev/null | head -1)
AB=$(ls "$HOMEDIR"/.hermes/tools/agent-browser-*/bin/agent-browser-linux-* 2>/dev/null | head -1)
[ -n "$CH" ] && [ -n "$AB" ] || { echo "look-check: no browser tools under $HOMEDIR/.hermes/tools" >&2; exit 2; }
export AGENT_BROWSER_EXECUTABLE_PATH="$CH" AGENT_BROWSER_ARGS="--no-sandbox"
W="${SIZE%x*}"; H="${SIZE#*x}"
S="lk$RANDOM$$"
ab() { "$AB" --session "$S" --json "$@"; }
res() { python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: print(""); sys.exit()
if isinstance(d,dict) and isinstance(d.get("data"),dict) and "result" in d["data"]:
    r=d["data"]["result"]; print(r if isinstance(r,str) else json.dumps(r))
else: print("")'; }
# eval a js expression supplied in a file (no shell quoting of the expression)
evaljs() { "$AB" --session "$S" --json eval --stdin < "$1" | res; }

echo "== real input check: $MODE =="
ab set viewport "$W" "$H" >/dev/null
echo "open $URL  (viewport ${W}x${H})"
ab open "$URL" >/dev/null
ab wait 2000 >/dev/null
for e in "$@"; do printf '[js] %s\n' "$e"; printf '     -> %s\n' "$(ab eval "$e" | res)"; done

SELJSON=$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$SEL")
ab eval "window.__trSel = $SELJSON" >/dev/null
FIND='(()=>{const sel=window.__trSel;const deepFind=(s,root)=>{let f;try{f=root.querySelector(s)}catch(e){return null}if(f)return f;for(const el of root.querySelectorAll("*")){if(el.shadowRoot){const g=deepFind(s,el.shadowRoot);if(g)return g}}return null};const el=deepFind(sel,document);if(!el)return JSON.stringify({found:false});el.scrollIntoView({block:"center",inline:"center"});const r=el.getBoundingClientRect();const cs=getComputedStyle(el);return JSON.stringify({found:true,visible:(r.width>1&&r.height>1&&cs.display!=="none"&&cs.visibility!=="hidden"),x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),w:Math.round(r.width),h:Math.round(r.height),tag:el.tagName});})()'

BOX=""
for _ in $(seq 1 12); do                     # the overlay opens its round bar off a poll: give it a moment
  BOX=$(ab eval "$FIND" | res)
  case "$BOX" in *'"visible":true'*) break ;; esac
  ab wait 700 >/dev/null
done
echo "deep find '$SEL' -> $BOX"
FOUND=$(python3 -c 'import sys,json
try: d=json.loads(sys.argv[1] or "{}")
except Exception: d={}
print("yes" if d.get("found") and d.get("visible") else "no")' "$BOX")
if [ "$FOUND" != yes ]; then
  echo "FAIL: '$SEL' is not on the page (or not visible) with a real page query -> $BOX"
  ab close >/dev/null 2>&1; exit 1
fi
X=$(python3 -c 'import sys,json;print(json.loads(sys.argv[1])["x"])' "$BOX")
Y=$(python3 -c 'import sys,json;print(json.loads(sys.argv[1])["y"])' "$BOX")

# arm: record whether the arrival really happened in the browser's input pipeline (isTrusted)
ab eval '(()=>{window.__mk={down:null,pointer:null,key:null,keys:[]};document.addEventListener("mousedown",e=>{window.__mk.down={trusted:e.isTrusted,target:e.target&&e.target.tagName}},true);document.addEventListener("pointerdown",e=>{window.__mk.pointer={trusted:e.isTrusted}},true);document.addEventListener("keydown",e=>{window.__mk.key={trusted:e.isTrusted,key:e.key};window.__mk.keys.push(e.key)},true);return "armed"})()' >/dev/null

echo "real click: mouse move ($X,$Y) -> mousePressed -> mouseReleased"
ab mouse move "$X" "$Y" >/dev/null
ab mouse down >/dev/null
ab mouse up >/dev/null
RC=0
if [ "$MODE" = click ]; then
  HITJS='(()=>{const sel=window.__trSel;const deepFind=(s,root)=>{let f;try{f=root.querySelector(s)}catch(e){return null}if(f)return f;for(const el of root.querySelectorAll("*")){if(el.shadowRoot){const g=deepFind(s,el.shadowRoot);if(g)return g}}return null};const el=deepFind(sel,document);const r=el.getBoundingClientRect();const x=Math.round(r.left+r.width/2),y=Math.round(r.top+r.height/2);const at=document.elementFromPoint(x,y);return JSON.stringify({hit:(at===el),atInEl:!!(el&&at&&el.contains(at)),at:at?(at.tagName+(at.className?"."+String(at.className).split(" ")[0]:"")):"",trust:(window.__mk||{}).down});})()'
  HIT=$(ab eval "$HITJS" | res)
  echo "hit test -> $HIT"
  if [ -n "$EXPECT" ]; then
    EF=$(mktemp); { printf '(()=>{try{return !!('; printf '%s' "$EXPECT"; printf ')}catch(e){return false}})()'; } > "$EF"
    EV=$(evaljs "$EF"); rm -f "$EF"
    echo "expect: $EXPECT"
    echo "      -> $EV"
    if [ "$EV" = "true" ]; then
      echo "PASS: the real click changed the state '$SEL' was checked for"
    else
      echo "FAIL: the real click did not change the state (expectation -> $EV; hit -> $HIT)"
      RC=1
    fi
  else
    if python3 -c 'import sys,json;d=json.loads(sys.argv[1] or "{}");sys.exit(0 if (d.get("hit") or d.get("atInEl")) else 1)' "$HIT"; then
      echo "PASS: a real click landed on '$SEL' (hit test -> $HIT)"
    else
      echo "FAIL: a real click at '$SEL' hit something else (hit test -> $HIT)"
      RC=1
    fi
  fi
else
  KEYS=""
  case "$TXT" in *" "*) echo "note: spaces are sent as the Space key" ;; esac
  for ((i=0;i<${#TXT};i++)); do
    c="${TXT:$i:1}"; k="$c"; [ "$c" = " " ] && k="Space"
    ab press "$k" >/dev/null
    KEYS="$KEYS $k"
  done
  echo "real keys: keyDown/keyUp each character ->$KEYS"
  READ='(()=>{const sel=window.__trSel;const deepFind=(s,root)=>{let f;try{f=root.querySelector(s)}catch(e){return null}if(f)return f;for(const el of root.querySelectorAll("*")){if(el.shadowRoot){const g=deepFind(s,el.shadowRoot);if(g)return g}}return null};const el=deepFind(sel,document);let a=document.activeElement;while(a&&a.shadowRoot&&a.shadowRoot.activeElement)a=a.shadowRoot.activeElement;return JSON.stringify({value:el?(el.value!==undefined?el.value:null):null,focused:(!!el&&a===el),active:a?(a.tagName+(a.className?"."+String(a.className).split(" ")[0]:"")):"",trust:window.__mk||null});})()'
  RB=$(ab eval "$READ" | res)
  echo "read back -> $RB"
  python3 - "$TXT" "$SEL" "$RB" <<'PY'
import sys, json
text, sel, raw = sys.argv[1], sys.argv[2], sys.argv[3]
try: rb = json.loads(raw or "{}")
except ValueError: rb = {}
val, foc = rb.get("value"), rb.get("focused")
t = rb.get("trust") or {}
down, ptr, key = t.get("down") or {}, t.get("pointer") or {}, t.get("key") or {}
ok = (val == text and foc and down.get("trusted") is True and key.get("trusted") is True)
print("observed: value=%r focused=%s deep-activeElement=%r mousedown.isTrusted=%s pointerdown.isTrusted=%s keydown.isTrusted=%s"
      % (val, foc, rb.get("active"), down.get("trusted"), ptr.get("trusted"), key.get("trusted")))
if ok:
    print("PASS: real input reached %s (value read back == %r)" % (sel, text))
else:
    why = ("a real click at its centre did not focus it (not focusable: it is covered or it swallows the click)"
           if not foc else "the typed text did not land in it")
    print("FAIL: %s is not taking typing -- %s (value=%r, expected %r)" % (sel, why, val, text))
sys.exit(0 if ok else 1)
PY
  RC=$?
fi
ab close >/dev/null 2>&1
exit $RC
INNER_EOF
  chmod +x "$TMP"
  UNIT="lookcheck-$MODE-$PPID-$$"
  RC=0
  systemd-run --user --wait --pipe --collect --unit="$UNIT" /bin/bash "$TMP" "$MODE" "$URL" "$SEL" "$TXT" "$SIZE" "$EXPECT" "${JS[@]+"${JS[@]}"}" || RC=$?
  rm -f "$TMP"
  echo
  [ $RC -eq 0 ] && echo "look-check: PASS" || echo "look-check: FAIL (exit $RC)"
  exit $RC
fi

# ---- look mode (unchanged) -----------------------------------------------------------------------------------
[ -n "$V" ] || { echo "usage: look-check.sh <look|current> [path] [--js '<expr>' ...]  |  look-check.sh --type '<selector>' '<text>' --url <url>" >&2; exit 2; }
CONF="$HOME/.hermes/scripts/review-mirrors.conf"
api=$(grep -m1 '^API_SERVER_PORT=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2 || true)
[ -n "$api" ] || { echo "no API_SERVER_PORT in ~/.hermes/.env" >&2; exit 1; }
if [ -n "$DEMO" ]; then
  PORT=$((api + 45 + DEMO + 50))                  # the demo slot's review link (see demo.sh)
  OUTDIR="$HOME/vault/design/demo-checks"
else
  PORT=$(grep -v '^\s*#' "$CONF" 2>/dev/null | grep -viE 'design|demo|mockup' | awk 'NF>=2 && $1 ~ /^[0-9]+$/ {print $1; exit}' || true)
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
NOOV=""; [ -n "$NO_OVERLAY" ] && NOOV="&__nooverlay=1"        # --no-overlay: a picture with no overlay UI in it
URL="http://127.0.0.1:$PORT${base:-/}${sep}__variant=$SW&__shot=1$NOOV$hash"; URL="${URL//\'/%27}"
slug=$(printf '%s' "${PAGE//%[0-9A-Fa-f][0-9A-Fa-f]/-}" | tr -c 'A-Za-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//' | cut -c1-40)
SHOT="$OUTDIR/check-${slug:-home}.png"
kinds=""; if [ ${#KIND[@]} -gt 0 ]; then kinds=$(IFS=,; echo "${KIND[*]}"); fi
req=$(python3 -c '
import json, sys
url, size, shot, kinds = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
steps = [{"drag": v} if k == "drag" else {"js": v} for k, v in zip(kinds.split(",") if kinds else [], sys.argv[5:])]
w, h = size.split("x")
print(json.dumps({"url": url, "width": int(w), "height": int(h), "shot": shot, "steps": steps}))' \
  "$URL" "$SIZE" "$SHOT" "$kinds" ${VAL[@]+"${VAL[@]}"})
curl -fs -m 300 -H 'Content-Type: application/json' -d "$req" "http://127.0.0.1:$((api + 99))/check"
echo
