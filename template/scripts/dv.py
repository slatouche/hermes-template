#!/usr/bin/python3
"""dv.py: the Designer's (and Manager's) handle on the design view. Every command is one quick call.

  dv.py map [#/route]                  the screen's structure, as the owner last saw it (selectors to use in edits)
  dv.py layer                          the design layer's edits so far, one per line
  dv.py apply --group <card> [--label "<what>"] [<edit json> ...]   add edits (or one JSON edit per line on stdin);
                                       they stream into the owner's open mockup at once, and undo together
  dv.py undo <note id> [...]           take back notes (ids from `dv.py notes`)
  dv.py notes                          the last notes and what each did
  dv.py behaviors                      the ready-made interactions (behavior edits) and their options
  dv.py propose <name> <file.js> "<why>"   propose a new behavior: behavior-check.py checks it first (safe, registers,
                                       sets up fast); passed, it waits in vault/design/behaviors/proposed/ and the
                                       Manager gets a card to judge fit (only approved ones are served)
  dv.py approve <name> | reject <name> "<why>"   the Manager's verdict on a proposed behavior
  dv.py export                         the build sheet: what the owner asked, change by change (their words, what was
                                       done, the edits), this round's build notes (the functions to make work), and
                                       the layer grouped for folding into the real front end
  dv.py look <worktree> [--out <dir>] [--json]   the look check: each screen of the agreed design, the build in the
                                       worktree against the agreed mockup, at the owner's window size; prints how much
                                       of each screen differs and saves the pictures (mockup, build, and the build with
                                       what differs in magenta: look at those, not the whole screens). Default out:
                                       ~/.hermes/look/
  dv.py landed                         an agreed design finished by hand is live: archive the layer, unfreeze

Edits are the same as the quick path's: token, css, move, text, insert, attr, repeat, remove, link, behavior, screen
(see `dv.py help-edits`). Nothing here writes the app's code.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = pathlib.Path.home()
BEHAVIOR_DIR = HOME / "vault" / "design" / "behaviors"
EDITS = """Edits (one JSON object each):
{"op":"token","name":"--x","value":"..."}            change a theme token (preferred)
{"op":"css","rule":"<selector> { ... }"}               a rule, written with the tokens
{"op":"move","sel":"<what>","where":"before|after|into|start","ref":"<where>"}
{"op":"text","sel":"<what>","text":"..."}     {"op":"attr","sel":"<what>","name":"<attr>","value":"..."}
{"op":"insert","where":"before|after|into|start","ref":"<where>","html":"<plain markup>"}
{"op":"repeat","sel":"<the list's items>","n":8,"fill":{"<part>":["a","b"],"img@src":["url","url"]}}
   one per list: the list ends up with n items (copies of its first real one; copies click like it), and fill sets
   each item's parts in order, one value per item (text, or an attribute after @); the real items keep their real
   content (their values go unused).
   Several repeats of one list share the same copies.
{"op":"remove","sel":"<what>"}  (hides it)     {"op":"link","sel":"<what is clicked>","to":"#/route"}
{"op":"screen","route":"#/name","label":"Menu label"}  then inserts with "ref":"@screen:#/name" (adds a nav link;
   the screen shows at its route in the app's screen area, the app's own content there hidden)
{"op":"behavior","name":"<name>","sel":"...", ...options}   see `dv.py behaviors`
Any edit may add "on":"#/route" (one screen only). Edits apply in order and are re-applied whenever the app redraws.
Markup: classes, no style attributes (style with css edits), no scripts, no on* handlers, no javascript: URLs.
An element's own style="..." (shown in `dv.py map`) beats css: use !important for those properties. `dv.py apply` prints how each edit fared on the owner's
open page: that is your check."""
BEHAVIORS = """Ready-made behaviors (set up once per element the sel matches; they work on placeholder copies too):
  sortable  sel=<the lists> [item=<an item inside a list>]  drag items to reorder, and between every list sel matches
            (a FLIP animation). Main deck <-> sideboard: give both lists one shared selector, e.g.
            {"op":"behavior","name":"sortable","sel":"[data-ui=cards], [data-ui=side-cards]","item":"[data-ui=card-row]"}
  toggle    sel=<button> target=<what shows> [class=<class to toggle>]  click shows/hides target (hidden attribute)
  dialog    sel=<button> target=<dialog markup, inserted with hidden>  click opens it as a modal; backdrop, Escape
            or an element with data-close closes it
  tabs      sel=<the tab row> panels=<the panels> [class=active]  the nth tab shows the nth panel
  toast     sel=<button> text=<message>  click shows a short message (a simulated save, export, ...)"""


def base():
    env = (HOME / ".hermes" / ".env").read_text()
    port = int(re.search(r"^API_SERVER_PORT=(\d+)", env, re.M).group(1)) + 51
    return f"http://127.0.0.1:{port}"


def call(path, body=None, raw=False, timeout=30):
    req = urllib.request.Request(base() + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read().decode()
    except urllib.error.HTTPError as e:
        data = e.read().decode()
        sys.exit(f"dv: {json.loads(data).get('error', data) if data.startswith('{') else data}")
    except urllib.error.URLError:
        sys.exit("dv: the design view isn't running (design-view.sh up)")
    return data if raw else json.loads(data)


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "help-edits":
        print(EDITS)
    elif cmd == "map":
        r = call("/dv/map?route=" + urllib.parse.quote(rest[0] if rest else "#/"))
        print(r["map"] or f"(no map of {r['route']} yet; screens seen: {', '.join(r['routes']) or 'none'})")
    elif cmd == "layer":
        for o in call("/dv/ops")["ops"]:
            print(json.dumps({k: v for k, v in o.items() if k != "id"})[:300])
    elif cmd == "notes":
        for n in call("/dv/status")["notes"]:
            print(f"{n['id']}: {n['note'][:100]} -> {n.get('verdict')}: {(n.get('plan') or '')[:80]} ({len(n.get('ops') or [])} edits)")
    elif cmd == "apply":
        group, label, edits = "", "", []
        i = 0
        while i < len(rest):
            if rest[i] == "--group":
                group, i = rest[i + 1], i + 2
            elif rest[i] == "--label":
                label, i = rest[i + 1], i + 2
            else:
                edits.append(rest[i])
                i += 1
        if not edits:
            edits = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
        try:
            ops = [json.loads(e) for e in edits]
        except ValueError as e:
            sys.exit(f"dv: not JSON: {e}")
        r = call("/dv/op", {"ops": ops, "group": group, "label": label or f"{len(ops)} edits"})
        print(f"applied {len(r['ops'])} edits as {r['note']}")
        # The owner's open page reports how each edit fared; that's the check (no browser needed).
        seen = {}
        for _ in range(16):
            time.sleep(0.25)
            seen = {k: v for k, v in call("/dv/report?ids=" + ",".join(r["ops"])).items() if v}
            if len(seen) == len(r["ops"]):
                break
        if not seen:
            print("no mockup page is open to confirm them; they apply when the owner opens it")
        for i, op in zip(r["ops"], ops):
            st = (seen.get(i) or {}).get("status", "not on the open screen")
            if not st.startswith("ok"):
                print(f"  {i} {op.get('op')}: {st}")
        if seen and all((seen.get(i) or {}).get("status", "").startswith("ok") for i in r["ops"]):
            print("all landed on the owner's page")
    elif cmd == "undo":
        print(call("/dv/undo", {"notes": rest}))
    elif cmd == "behaviors":
        print(BEHAVIORS)
        for p in sorted(BEHAVIOR_DIR.glob("*.js")):
            m = re.search(r"/\*\s*(.*?)(?:\*/|\n)", p.read_text(errors="replace"))
            print(f"  {p.stem:<9} {(m.group(1).strip() if m else '')[:160]}  (approved)")
    elif cmd == "propose":
        if len(rest) < 3 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,40}", rest[0]):
            sys.exit('dv: propose <name> <file.js> "<why>"')
        name, why = rest[0], rest[2]
        r = subprocess.run([sys.executable, str(HOME / ".hermes" / "scripts" / "behavior-check.py"), rest[1], "--name", name],
                           capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode != 0:
            sys.exit("dv: not proposed; fix what failed and propose again")
        dest = BEHAVIOR_DIR / "proposed"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(rest[1], dest / f"{name}.js")
        notes = [ln.strip(" ()") for ln in r.stdout.splitlines()[1:] if ln.strip().startswith("(")]
        body = (f"A new mockup behavior '{name}' from the Designer: {why}\n\nFile: vault/design/behaviors/proposed/{name}.js\n"
                f"behavior-check.py passed it: plain DOM only (no network, storage, eval, navigation; none reached at "
                f"runtime either), registers itself, sets up without errors" + (f" ({'; '.join(notes)})" if notes else "")
                + f".\n\nWhat's left is judgement, a minute's read: does it do what the note needs, and is it a reusable "
                f"interaction rather than a one-off? Yes: `dv.py approve {name}`. No: `dv.py reject {name} \"<why>\"`. "
                f"Shape: quick. Review: none.")
        out = subprocess.run(["hermes", "kanban", "create", f"Review proposed behavior: {name}", "--assignee", "manager",
                              "--body", body], capture_output=True, text=True)
        print(f"proposed {name}; review card: {out.stdout.strip()[:120] or out.stderr.strip()[:120]}")
    elif cmd in ("approve", "reject"):
        if not rest or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,40}", rest[0]):
            sys.exit(f"dv: {cmd} <name>" + (' "<why>"' if cmd == "reject" else ""))
        f = BEHAVIOR_DIR / "proposed" / f"{rest[0]}.js"
        if not f.is_file():
            sys.exit(f"dv: no proposed behavior '{rest[0]}'")
        if cmd == "approve":
            r = subprocess.run([sys.executable, str(HOME / ".hermes" / "scripts" / "behavior-check.py"), str(f), "--name", rest[0]],
                               capture_output=True, text=True)
            if r.returncode != 0:                                   # changed since it was proposed: check again
                sys.exit("dv: it no longer passes the check:\n" + r.stdout.strip())
            f.replace(BEHAVIOR_DIR / f.name)
            print(f"approved {rest[0]}: every note can use it now (the design view serves it at once)")
        else:
            (BEHAVIOR_DIR / "rejected").mkdir(exist_ok=True)
            f.replace(BEHAVIOR_DIR / "rejected" / f.name)
            (BEHAVIOR_DIR / "rejected" / f"{rest[0]}.why.txt").write_text(" ".join(rest[1:]) or "rejected")
            print(f"rejected {rest[0]}")
    elif cmd == "export":
        print(call("/dv/export", raw=True))
    elif cmd == "look":
        if not rest or rest[0].startswith("--"):
            sys.exit("dv: look <worktree> [--out <dir>] [--json]")
        out = rest[rest.index("--out") + 1] if "--out" in rest else str(HOME / ".hermes" / "look")
        r = call("/dv/look", {"worktree": rest[0], "out": out}, timeout=600)
        if "--json" in rest:
            print(json.dumps(r))
        elif r.get("error"):
            sys.exit(f"dv: {r['error']}")
        else:
            for x in r["screens"]:
                print(f"{x['route']}: " + (f"couldn't compare ({x['error']})" if x.get("error") else
                      f"{x['diff']}% differs" + ("  <- look: " + x["overlay"] if x["diff"] >= r["tolerance"] else "")))
            print(f"{len(r['differ'])} of {len(r['screens'])} screens differ by {r['tolerance']}% or more "
                  f"(at {r['view']['w']}x{r['view']['h']}); pictures in {out}")
        return 1 if r.get("error") or r.get("differ") else 0
    elif cmd == "landed":
        print(call("/dv/landed", {}))
    else:
        sys.exit(f"dv: unknown command {cmd} (dv.py help)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
