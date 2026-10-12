#!/usr/bin/python3
"""behavior-check.py: the mechanical half of reviewing a proposed mockup behavior, in seconds, with no model.

  behavior-check.py <file.js> [--name <name>] [--json]

  1. Reads the code: size, that it registers window.__dvBehaviors.<name> (or ["<name>"]), and nothing it must never
     touch (network, storage, cookies, eval / new Function, dynamic import, workers, opening windows, navigating).
  2. Runs it in the project's headless browser on a small fixture page (a list of rows, a button, a panel), with every
     forbidden API trapped, and sets it up on the list twice: it must register, set up without an error, touch no
     trapped API (even disguised), and set up fast (under 50 ms).
Exit 0 = passed (what's left is the judgement: does it fit), 1 = failed (the report says what), 2 = couldn't run.
Without the browser tools, step 2 is skipped and the report says so.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

HOME = pathlib.Path.home()
MAX_BYTES = 16000
SETUP_MS = 50
FORBIDDEN = [
    (r"\bfetch\s*\(", "network (fetch)"), (r"XMLHttpRequest", "network (XMLHttpRequest)"),
    (r"\bWebSocket\b", "network (WebSocket)"), (r"\bEventSource\b", "network (EventSource)"),
    (r"sendBeacon", "network (sendBeacon)"), (r"\blocalStorage\b|\bsessionStorage\b|\bindexedDB\b", "storage"),
    (r"document\s*\.\s*cookie", "cookies"), (r"\beval\s*\(", "eval"), (r"\bnew\s+Function\b|\bFunction\s*\(", "new Function"),
    (r"\bimport\s*\(", "dynamic import"), (r"\bimportScripts\b|\bnew\s+(?:Shared)?Worker\b", "workers"),
    (r"window\s*\.\s*open\s*\(", "opening windows"), (r"(?:window\s*\.\s*|document\s*\.\s*|\b)location\s*(?:\.\s*(?:href|assign|replace)\b|=)", "navigating"),
    (r"\.postMessage\s*\(", "messaging other frames"), (r"<script|\.src\s*=\s*['\"]https?:", "loading code or remote files"),
]

HARNESS = r"""<!doctype html><meta charset="utf-8"><title>behavior check</title>
<script>
window.__trap = [];
(function () {
  function trap(obj, key, what) { try { Object.defineProperty(obj, key, { configurable: true, get: function () { __trap.push(what); return function () { throw new Error("blocked: " + what); }; } }); } catch (e) {} }
  ["fetch", "XMLHttpRequest", "WebSocket", "EventSource", "Worker", "SharedWorker", "open"].forEach(function (k) { trap(window, k, k); });
  trap(window, "eval", "eval"); trap(window, "Function", "Function");
  ["localStorage", "sessionStorage", "indexedDB"].forEach(function (k) { trap(window, k, k); });
  try { Object.defineProperty(Document.prototype, "cookie", { get: function () { __trap.push("cookie"); return ""; }, set: function () { __trap.push("cookie"); } }); } catch (e) {}
  try { navigator.sendBeacon = function () { __trap.push("sendBeacon"); return false; }; } catch (e) {}
  window.__errors = [];
  window.addEventListener("error", function (e) { __errors.push(String(e.message)); });
})();
</script>
<style>body{font:14px sans-serif} li{padding:6px;border:1px solid #ccc;margin:2px}</style>
<button id="btn" data-ui="btn">Open</button><div id="panel" hidden>Panel</div>
<ul id="list" data-ui="cards"><li data-ui="card-row">One</li><li data-ui="card-row">Two</li><li data-ui="card-row">Three</li>
<li data-ui="card-row">Four</li><li data-ui="card-row">Five</li></ul>
<ul id="list2" data-ui="side-cards"><li data-ui="card-row">Six</li><li data-ui="card-row">Seven</li></ul>
<script>window.__dvBehaviors = {};</script>
<script src="proposal.js" onerror="__errors.push('the file did not load')"></script>
<script>
window.__result = (function () {
  var name = __NAME__, fn = window.__dvBehaviors[name], out = { registered: typeof fn === "function", setup: [], traps: [], errors: [] };
  if (out.registered) [["#list", { name: name, sel: "#list", item: "[data-ui=card-row]", target: "#panel" }],
                       ["#list2", { name: name, sel: "#list2", item: "[data-ui=card-row]", target: "#panel" }]].forEach(function (p) {
    var el = document.querySelector(p[0]), t0 = performance.now();
    try { fn(el, p[1]); out.setup.push({ el: p[0], ms: +(performance.now() - t0).toFixed(1) }); }
    catch (e) { out.setup.push({ el: p[0], ms: +(performance.now() - t0).toFixed(1), error: String(e && e.message || e) }); }
  });
  try { document.querySelector("#list li").dispatchEvent(new MouseEvent("click", { bubbles: true })); } catch (e) { out.errors.push("click: " + e.message); }
  out.traps = __trap.slice(); out.errors = out.errors.concat(__errors);
  return JSON.stringify(out);
})();
</script>
"""


def static(js, name):
    found = []
    code = re.sub(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", " ", js, flags=re.S)          # what runs, not what's said about it
    for pat, what in FORBIDDEN:
        if re.search(pat, code):
            found.append(what)
    reg = re.search(r"__dvBehaviors\s*(?:\.\s*" + re.escape(name) + r"|\[\s*['\"]" + re.escape(name) + r"['\"]\s*\])\s*=", code)
    alias = re.search(r"(\w+)\s*=\s*window\.__dvBehaviors", code)
    if not reg and alias:
        reg = re.search(re.escape(alias.group(1)) + r"\s*(?:\.\s*" + re.escape(name) + r"|\[\s*['\"]" + re.escape(name) + r"['\"]\s*\])\s*=", code)
    return found, bool(reg)


def browser():
    ch = sorted((HOME / ".hermes" / "tools").glob("chromium-*/chrome-linux64/chrome"))
    ab = sorted((HOME / ".hermes" / "tools").glob("agent-browser-*/bin/agent-browser-linux-*"))
    return (str(ch[0]), str(ab[0])) if ch and ab else (None, None)


def runtime(path, name):
    ch, ab = browser()
    if not ch:
        return None, "no browser tools under ~/.hermes/tools: the runtime check was skipped"
    d = pathlib.Path(tempfile.mkdtemp(prefix="behavior-check-", dir=str(HOME / ".cache") if (HOME / ".cache").is_dir() else None))
    (d / "proposal.js").write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    (d / "index.html").write_text(HARNESS.replace("__NAME__", json.dumps(name)), encoding="utf-8")
    script = (f"export AGENT_BROWSER_EXECUTABLE_PATH={json.dumps(ch)} AGENT_BROWSER_ARGS=--no-sandbox\n"
              f"S=bc$RANDOM$$\nA={json.dumps(ab)}\n"
              f"$A --session $S --json open 'file://{d}/index.html' >/dev/null\n$A --session $S --json wait 300 >/dev/null\n"
              f"$A --session $S --json eval 'window.__result'\n$A --session $S close >/dev/null 2>&1\n")
    (d / "run.sh").write_text(script)
    cmd = ["bash", str(d / "run.sh")]
    if subprocess.run(["bash", "-c", "command -v systemd-run"], capture_output=True).returncode == 0:
        cmd = ["systemd-run", "--user", "--wait", "--pipe", "--collect", "--quiet", f"--unit=behavior-check-{os.getpid()}"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                           env=dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"))
    except subprocess.TimeoutExpired:
        return None, "the browser didn't answer in 90 s"
    finally:
        subprocess.run(["rm", "-rf", str(d)])
    try:
        outer = json.loads(r.stdout.strip().splitlines()[-1])
        res = outer.get("data", {}).get("result")
        return json.loads(res) if isinstance(res, str) else res, None
    except (ValueError, IndexError, AttributeError):
        return None, f"the browser run failed: {(r.stdout + r.stderr).strip()[-300:]}"


def check(path, name):
    js = path.read_text(encoding="utf-8", errors="replace")
    fails, notes = [], []
    if len(js.encode()) > MAX_BYTES:
        fails.append(f"too big: {len(js.encode())} bytes (at most {MAX_BYTES}); a behavior is one interaction")
    found, registered = static(js, name)
    fails += [f"uses {w}: a mockup behavior is plain DOM only" for w in found]
    if not registered:
        fails.append(f"doesn't register window.__dvBehaviors.{name} (or [\"{name}\"])")
    res, why = runtime(path, name)
    if res is None:
        notes.append(why)
    else:
        if not res.get("registered"):
            fails.append("in the browser it didn't register itself")
        for s in res.get("setup") or []:
            if s.get("error"):
                fails.append(f"setting it up on {s['el']} threw: {s['error']}")
            elif s["ms"] > SETUP_MS:
                fails.append(f"setting it up on {s['el']} took {s['ms']} ms (at most {SETUP_MS})")
        if res.get("traps"):
            fails.append(f"reached for {', '.join(sorted(set(res['traps'])))} at runtime")
        fails += [f"page error: {e}" for e in res.get("errors") or []]
        notes.append("set up in " + ", ".join(f"{s['el']} {s['ms']} ms" for s in res.get("setup") or []) if res.get("setup") else "")
    return {"name": name, "ok": not fails, "fails": fails, "notes": [n for n in notes if n], "bytes": len(js.encode())}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    path = pathlib.Path(argv[0])
    if not path.is_file():
        print(f"behavior-check: no file {path}", file=sys.stderr)
        return 2
    name = argv[argv.index("--name") + 1] if "--name" in argv else path.stem
    r = check(path, name)
    if "--json" in argv:
        print(json.dumps(r))
    else:
        print(f"{'PASS' if r['ok'] else 'FAIL'}: behavior '{name}' ({r['bytes']} bytes)")
        for f in r["fails"]:
            print(f"  - {f}")
        for n in r["notes"]:
            print(f"  ({n})")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
