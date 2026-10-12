#!/usr/bin/python3
"""Checks for template/scripts/design-view.py (the design view server) and dv.py, without a model or a browser.

  python3 tests/test_design_view.py      (a temporary HOME and a server on a free local port)
"""
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent / "template"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


def load():
    spec = importlib.util.spec_from_file_location("dvserver", ROOT / "scripts" / "design-view.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def refused(m, op):
    try:
        m.check_op(op)
        return False
    except ValueError:
        return True


def main():
    home = pathlib.Path(tempfile.mkdtemp(prefix="dv-"))
    os.environ["HOME"] = str(home)
    m = load()

    # ---- edits are checked before anything is stored -------------------------------------------------------------
    good = [{"op": "token", "name": "--accent", "value": "#3b6fd8"},
            {"op": "css", "rule": ".grid { gap: var(--sp-4); }"},
            {"op": "move", "sel": "#a", "where": "before", "ref": "#b"},
            {"op": "insert", "where": "into", "ref": "@screen:#/maker", "html": "<section class='card'><h2>Maker</h2></section>"},
            {"op": "repeat", "sel": ".card", "n": 8, "fill": {".name": ["A", "B"], "img@src": ["https://placehold.co/10x10"]}},
            {"op": "screen", "route": "#/maker", "label": "Card maker"},
            {"op": "link", "sel": ".card", "to": "#/deck"},
            {"op": "behavior", "name": "sortable", "sel": ".list", "item": ".row"},
            {"op": "undo", "notes": ["n3"]}]
    check("well-formed edits pass", all(not refused(m, o) for o in good), [o for o in good if refused(m, o)])
    bad = [({"op": "insert", "where": "into", "ref": "#a", "html": "<script>x()</script>"}, "a script"),
           ({"op": "insert", "where": "into", "ref": "#a", "html": "<img src=x onerror=alert(1)>"}, "an inline handler"),
           ({"op": "css", "rule": ".a { color: red; } </style><script>"}, "CSS breaking out"),
           ({"op": "css", "rule": "@import url(x.css); .a{}"}, "@import"),
           ({"op": "attr", "sel": "#a", "name": "onclick", "value": "x()"}, "an on* attribute"),
           ({"op": "attr", "sel": "a", "name": "href", "value": "javascript:x()"}, "javascript: URL"),
           ({"op": "repeat", "sel": ".c", "fill": {"a@onclick": ["x"]}}, "a handler through fill"),
           ({"op": "token", "name": "--x", "value": "red; } body { display:none"}, "a token breaking out"),
           ({"op": "link", "sel": "a", "to": "https://evil.example"}, "a link off the app"),
           ({"op": "behavior", "name": "sortable", "sel": ".l", "item": "<img src=x onerror=1>"}, "markup in a behavior option"),
           ({"op": "behavior", "name": "../x", "sel": ".l"}, "a behavior name with a path"),
           ({"op": "eval", "code": "x"}, "an unknown edit")]
    for op, why in bad:
        check(f"refused: {why}", refused(m, op), op)

    # ---- the layer: notes, undo, options, archive -----------------------------------------------------------------
    layer = m.Layer(home / "vault" / "design" / "layer")
    n1 = layer.new_note("one", [], "#/")
    layer.add({"op": "token", "name": "--a", "value": "1"}, n1)
    layer.finish(n1)
    n2 = layer.new_note("two", [], "#/")
    layer.add({"op": "css", "rule": ".b{color:red}"}, n2)
    layer.finish(n2)
    check("edits get ids in order and keep their note", [(o["id"], o["note"]) for o in layer.ops] == [("e1", "n1"), ("e2", "n2")], layer.ops)
    layer.undo_notes([layer.last_note_with_ops()])
    check("undo last removes only the last note's edits", [o["note"] for o in layer.ops] == ["n1"], layer.ops)
    n3 = layer.new_note("options", [], "#/")
    sid = layer.new_option_set(n3)
    for letter in "AB":
        layer.add_choice(sid, letter, f"opt {letter}")
        layer.add({"op": "token", "name": "--c", "value": letter}, n3, (sid, letter))
    check("option edits stay out of the layer until picked", len(layer.ops) == 1 and len(layer.options[sid]["choices"]) == 2)
    layer.pick(sid, "B")
    check("picking folds that choice in and drops the set", layer.ops[-1]["value"] == "B" and sid not in layer.options, layer.ops)
    again = m.Layer(home / "vault" / "design" / "layer")
    check("the layer reloads from disk with the next ids", [o["id"] for o in again.ops] == [o["id"] for o in layer.ops]
          and again.next_op == layer.next_op and again.next_note == layer.next_note, (again.next_op, layer.next_op))

    # ---- a note's plan: parts read as they stream, then the quick edits ------------------------------------------------
    import argparse
    (home / "workspace" / "fe").mkdir(parents=True)
    app = m.App(argparse.Namespace(project="t", app=str(home / "workspace" / "fe"), layer=str(home / "vault" / "design" / "lp"),
                                   no_cards=True))

    def stream(*lines):
        for ln in lines:
            yield "line", ln
        yield "usage", {}
    plans, got = [], []
    rec = app.layer.new_note("tighter cards, header styles, real import", [], "#/")
    n = {"id": rec["id"], "text": rec["note"], "route": "#/"}
    e, r, u, _ = app.consume(stream("PART 1 quick | tighten the cards", "PART 2 options | three header styles",
                                    "PART 3 function | import Moxfield links", "END", '{"op":"css","rule":".card{padding:8px}"}'),
                             rec, n, time.monotonic(), on_plan=plans.append, got=got)
    check("the plan's parts are read before the work", len(plans) == 1 and [p["kind"] for p in plans[0]] == ["quick", "options", "function"],
          plans)
    check("...and the quick edits under END are stored and counted as the main call's", e == 1 and len(got) == 1, (e, got))
    plans.clear()
    app.consume(stream('{"op":"css","rule":".x{color:red}"}'), rec, n, time.monotonic(), on_plan=plans.append)
    check("no plan line at all: one quick part", plans and [p["kind"] for p in plans[0]] == ["quick"], plans)
    plans.clear()
    app.consume(stream("VERDICT options | colours", "OPTION A Warm", '{"op":"token","name":"--bg","value":"#111"}'),
                rec, n, time.monotonic(), on_plan=plans.append)
    check("the single-verdict form still plans, and inline options make a set", plans and plans[0][0]["kind"] == "options"
          and rec["id"] in app.layer.options, (plans, list(app.layer.options)))
    part = {"k": 2, "kind": "options", "text": "header styles"}
    app.consume(stream("OPTION A Bold", '{"op":"css","rule":"h1{font-weight:800}"}'), rec, n, time.monotonic(), mode="edits", part=part)
    check("a part's options get their own set (note-part), kept apart from the note's", f"{rec['id']}-2" in app.layer.options,
          list(app.layer.options))

    # ---- the server ------------------------------------------------------------------------------------------------
    (home / ".hermes").mkdir(exist_ok=True)
    shutil.copytree(ROOT / "design-view", home / ".hermes" / "design-view")
    app_dir = home / "workspace" / "frontend"
    shutil.copytree(ROOT / "starter" / "frontend", app_dir)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    (home / ".hermes" / ".env").write_text(f"API_SERVER_PORT={port - 51}\n")
    srv = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "design-view.py"), "--project", "t", "--port", str(port),
                            "--app", str(app_dir), "--layer", str(home / "vault" / "design" / "layer2"), "--bind", "127.0.0.1"],
                           env=dict(os.environ, HOME=str(home)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"

    def get(path):
        try:
            with urllib.request.urlopen(base + path, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    try:
        for _ in range(50):
            try:
                get("/dv/ops")
                break
            except OSError:
                time.sleep(0.1)
        code, html = get("/")
        check("the shell is served with the project's name", code == 200 and "t · design" in html and "/dv/shell.js" in html, code)
        code, html = get("/app/")
        check("the app's index gets the layer and behaviors", code == 200 and '<script src="/dv/behaviors.js"></script><script src="/dv/layer.js"></script>' in html, html[:300])
        code, _ = get("/app/../../.hermes/.env")
        check("no path out of the app folder", code == 404, code)
        code, body = post("/dv/op", {"ops": [{"op": "text", "sel": "h1", "text": "Hi"}, {"op": "behavior", "name": "toast", "sel": ".btn", "text": "Saved"}],
                                     "group": "t_abc", "label": "designer job"})
        code2, body2 = post("/dv/op", {"ops": [{"op": "css", "rule": "h1{color:red}"}], "group": "t_abc"})
        ops = json.loads(get("/dv/ops")[1])["ops"]
        check("a Designer's batches with one group share one note", code == 200 and code2 == 200 and body["note"] == body2["note"]
              and len(ops) == 3 and len({o["note"] for o in ops}) == 1, (body, body2, ops))
        v1 = json.loads(get("/dv/version")[1])["v"]
        post("/dv/op", {"op": {"op": "css", "rule": "h3{color:blue}"}})
        v2 = json.loads(get("/dv/version")[1])["v"]
        check("every change bumps the layer version (pages catch up on what they missed)", v2 > v1, (v1, v2))
        code, body = post("/dv/op", {"op": {"op": "insert", "where": "into", "ref": "body", "html": "<script>1</script>"}})
        check("an unsafe direct edit is refused with 400", code == 400, (code, body))
        post("/dv/map", {"route": "#/deck", "map": "main > .cards x10"})
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "dv.py"), "map", "#/deck"], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home)))
        check("dv.py map reads the screen map the page sent", "main > .cards x10" in r.stdout, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "dv.py"), "apply", "--group", "t_xyz"], input='{"op":"token","name":"--bg","value":"#000"}\n',
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
        check("dv.py apply sends stdin edits", r.returncode == 0 and "applied 1 edits" in r.stdout, r.stdout + r.stderr)
        code, sheet = get("/dv/export")
        check("the build sheet groups tokens and rules", code == 200 and "--bg: #000;" in sheet and "h1{color:red}" in sheet, sheet[:400])
        code, body = post("/api/decks", {"name": "New"})
        check("a mock write is echoed (kept in memory only)", code == 200 and body.get("name") == "New", body)
        code, js = get("/dv/behaviors.js")
        check("the behaviors library is served", code == 200 and "B.sortable" in js)
        # Agreed freezes the layer (the Manager card can't be made without Hermes here; the freeze must still hold)
        (home / "vault" / "design" / "layer2" / "FROZEN").write_text('{"at": "x"}')
        srv.terminate(); srv.wait(5)
        srv = subprocess.Popen(srv.args, env=dict(os.environ, HOME=str(home)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                get("/dv/ops")
                break
            except OSError:
                time.sleep(0.1)
        code, body = post("/dv/op", {"op": {"op": "css", "rule": "h2{color:red}"}})
        check("a frozen mockup takes no edits", code == 409, (code, body))
        code, body = post("/dv/preview", {"dir": str(home / "nope"), "branch": "design/x"})
        check("a preview must be a front-end folder in the project", code == 400, body)
        code, body = post("/dv/preview", {"dir": str(app_dir), "branch": "design/x"})
        code2, html = get("/preview/")
        check("a built preview is served as is (no layer)", code == 200 and code2 == 200 and "/dv/layer.js" not in html, (code, body))
    finally:
        srv.terminate()
        srv.wait(5)
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
