#!/bin/bash
# ui-check.sh: prove a control works with REAL input, the way the owner uses it. A real mouse click at the element's
# centre and real per-character key events (CDP Input.dispatchMouseEvent / Input.dispatchKeyEvent through the
# project's agent-browser), never a scripted `.value =` or `.click()`, which is no evidence anyone can click or type.
#
#   ui-check.sh --type '<selector>' '<text>' --url <url> [--size WxH] [--js '<expr>']...
#   ui-check.sh --click '<selector>' --url <url> [--expect '<js, truthy when the click worked>'] [--js '<expr>']...
#
# --js expressions run first (side effects included): inject a transparent blocker over the box to prove the check
# has teeth (it must FAIL). Selectors reach inside open shadow roots. Exit 0 = PASS, 1 = FAIL (not on the page,
# covered, not focusable, typed text didn't land, or the expectation was false), 2 = a usage or setup problem.
# The browser runs as a transient systemd user unit (systemd-run), outside the bot's sandbox, so Chrome can start.
set -euo pipefail
SIZE="1440x900"; JS=(); TYPE_SEL=""; TYPE_TEXT=""; CLICK_SEL=""; EXPECT=""; URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE_SEL="${2:?--type needs a selector}"; TYPE_TEXT="${3:?--type needs text}"; shift 3 ;;
    --click) CLICK_SEL="${2:?--click needs a selector}"; shift 2 ;;
    --expect) EXPECT="${2:?--expect needs a js expression}"; shift 2 ;;
    --url) URL="${2:?--url needs a url}"; shift 2 ;;
    --size) SIZE="$2"; shift 2 ;;
    --js) JS+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "ui-check: unknown option '$1' (ui-check.sh --help)" >&2; exit 2 ;;
  esac
done
[ -n "$TYPE_SEL" ] || [ -n "$CLICK_SEL" ] || { echo "ui-check: give --type '<selector>' '<text>' or --click '<selector>'" >&2; exit 2; }
if [ -n "$TYPE_SEL" ] || [ -n "$CLICK_SEL" ]; then
  command -v systemd-run >/dev/null || { echo "ui-check: real-input mode needs systemd-run (the browser must " \
    "run outside the bot's sandbox); run it from a bot terminal on the project host." >&2; exit 2; }
  [ -n "$URL" ] || { echo "ui-check: --type/--click need --url <the page to open>" >&2; exit 2; }
  MODE=type; SEL="$TYPE_SEL"; TXT="$TYPE_TEXT"
  if [ -n "$CLICK_SEL" ]; then MODE=click; SEL="$CLICK_SEL"; fi
  TMP=$(mktemp "${TMPDIR:-/tmp}/ui-check-XXXXXX.sh")
  cat > "$TMP" <<'INNER_EOF'
#!/bin/bash
# Runs inside a transient systemd user unit (outside the bot sandbox), so Chrome can start.
set -uo pipefail
MODE="$1"; URL="$2"; SEL="$3"; TXT="$4"; SIZE="$5"; EXPECT="$6"; shift 6
HOMEDIR="$HOME"
CH=$(ls "$HOMEDIR"/.hermes/tools/chromium-*/chrome-linux64/chrome 2>/dev/null | head -1)
AB=$(ls "$HOMEDIR"/.hermes/tools/agent-browser-*/bin/agent-browser-linux-* 2>/dev/null | head -1)
[ -n "$CH" ] && [ -n "$AB" ] || { echo "ui-check: no browser tools under $HOMEDIR/.hermes/tools" >&2; exit 2; }
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
for _ in $(seq 1 12); do                     # a control can appear a moment after load: give it a moment
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
  UNIT="uicheck-$MODE-$PPID-$$"
  RC=0
  systemd-run --user --wait --pipe --collect --unit="$UNIT" /bin/bash "$TMP" "$MODE" "$URL" "$SEL" "$TXT" "$SIZE" "$EXPECT" "${JS[@]+"${JS[@]}"}" || RC=$?
  rm -f "$TMP"
  echo
  [ $RC -eq 0 ] && echo "ui-check: PASS" || echo "ui-check: FAIL (exit $RC)"
  exit $RC
fi
