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
    nu = layer.new_note("to undo and redo", [], "#/")
    layer.add({"op": "css", "rule": ".u{color:blue}"}, nu)
    layer.finish(nu)
    kept = [o for o in layer.ops if o["note"] == nu["id"]]
    layer.undo_notes([nu["id"]])
    check("undo keeps what it took back", nu["id"] not in {o["note"] for o in layer.ops}
          and layer.undone and layer.undone[-1]["note"] == nu["id"], layer.undone[-1:])
    check("redo puts exactly those edits back", layer.redo_notes() == [nu["id"]]
          and [o for o in layer.ops if o["note"] == nu["id"]] == kept
          and nu["id"] not in {u["note"] for u in layer.undone}, layer.ops[-2:])
    layer.undo_notes([nu["id"]])
    check("undo and redo survive a restart", m.Layer(home / "vault" / "design" / "layer").undone[-1]["note"] == nu["id"])
    n3 = layer.new_note("options", [], "#/")
    sid = layer.new_option_set(n3)
    for letter in "AB":
        layer.add_choice(sid, letter, f"opt {letter}")
        layer.add({"op": "token", "name": "--c", "value": letter}, n3, (sid, letter))
    check("option edits stay out of the layer until picked", len(layer.ops) == 1 and len(layer.options[sid]["choices"]) == 2)
    layer.pick(sid, "B")
    check("picking folds that choice in and drops the set", layer.ops[-1]["value"] == "B" and sid not in layer.options, layer.ops)
    na = layer.new_note("options, please", [], "#/")
    first = layer.new_option_set(na)
    nb = layer.new_note("not those, more options", [], "#/")
    layer.new_option_set(nb, sid=nb["id"] + "-1")
    layer.new_option_set(nb, sid=nb["id"] + "-2")
    check("new options close an earlier note's unpicked set; a note's own sets stay together",
          first not in layer.options and {nb["id"] + "-1", nb["id"] + "-2"} == set(layer.options), list(layer.options))
    check("Discard closes a set and keeps nothing from it", layer.discard(nb["id"] + "-1") and nb["id"] + "-1" not in layer.options
          and not layer.discard("n999"), list(layer.options))
    layer.options.clear()
    layer._save()
    layer.finish(na)
    layer.finish(nb)
    again = m.Layer(home / "vault" / "design" / "layer")
    check("the layer reloads from disk with the next ids", [o["id"] for o in again.ops] == [o["id"] for o in layer.ops]
          and again.next_op == layer.next_op and again.next_note == layer.next_note, (again.next_op, layer.next_op))

    # ---- a note's plan: parts read as they stream, then the quick edits ------------------------------------------------
    import argparse
    (home / "workspace" / "fe").mkdir(parents=True)
    app = m.App(argparse.Namespace(project="t", app=str(home / "workspace" / "fe"), layer=str(home / "vault" / "design" / "lp"),
                                   no_cards=True, api_proxy=""))

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
        code, body = post("/dv/discard", {"set": "nope"})
        check("discarding a set that isn't there says so", code == 404, (code, body))
        code, body = post("/dv/op", {"op": {"op": "insert", "where": "into", "ref": "body", "html": "<script>1</script>"}})
        check("an unsafe direct edit is refused with 400", code == 400, (code, body))
        post("/dv/map", {"route": "#/deck", "map": "main > .cards x10"})
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "dv.py"), "map", "#/deck"], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home)))
        check("dv.py map reads the screen map the page sent", "main > .cards x10" in r.stdout, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "dv.py"), "apply", "--group", "t_xyz"], input='{"op":"token","name":"--bg","value":"#000"}\n',
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
        check("dv.py apply sends stdin edits", r.returncode == 0 and "applied 1 edits" in r.stdout, r.stdout + r.stderr)
        code, body = post("/dv/reset-data", {})
        ops_now = json.loads(get("/dv/ops")[1])
        check("placeholder data: no Data refresh, and the toolbar is told so", code == 409 and ops_now.get("data") is False, (code, body))
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
        code, body = post("/dv/undo", {"last": True})
        code2, body2 = post("/dv/redo", {})
        check("a frozen mockup can't be undone or redone either", code == 409 and code2 == 409, (code, code2))
        try:
            pcode = get("/preview/")[0]
        except urllib.error.HTTPError as e:
            pcode = e.code
        code, body = post("/dv/ship", {})
        check("no Built preview and no Ship: the build goes to the main app", pcode == 404 and code == 404, (pcode, code))
        code, body = post("/dv/landed", {})
        st = json.loads(get("/dv/ops")[1])
        check("live: the layer is archived and the mockup unfreezes", code == 200 and not st["frozen"] and st["ops"] == []
              and any((home / "vault" / "design" / "layer2" / "archive").iterdir()), (code, st["frozen"], len(st["ops"])))
        code, body = post("/dv/landed", {})
        check("landed with nothing agreed is refused", code == 409, (code, body))
        ag = (home / "vault" / "design" / "layer2" / "agreed.md").read_text(encoding="utf-8")
        check("agreed.md is a vault page: the standard header, then what went live",
              ag.startswith("---\n") and all(f"\n{k}:" in ag.split("\n---\n")[0] for k in ("title", "type", "status", "owner", "updated", "summary"))
              and "## Live " in ag, ag[:200])
    finally:
        srv.terminate()
        srv.wait(5)

    # ---- an app with a real back end: /api passes through to its design copy ---------------------------------------
    import http.server, threading
    class Stub(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def answer(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.dumps({"method": self.command, "path": self.path, "got": (self.rfile.read(n) if n else b"").decode()}).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        do_GET = do_POST = do_DELETE = answer
    stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    s2 = socket.socket(); s2.bind(("127.0.0.1", 0)); port2 = s2.getsockname()[1]; s2.close()
    (home / "vault" / "design" / "layer3").mkdir(parents=True, exist_ok=True)
    (home / "vault" / "design" / "layer3" / "agreed.md").write_text("\n## Shipped 2026-10-01\n- an older entry\n")
    # for a real Agreed: a product repo, build.py, and a fake board on the PATH (no Hermes here)
    (home / "workspace").mkdir(exist_ok=True)
    subprocess.run("git init -q -b main && git config user.email t@t && git config user.name t && "
                   "git commit -q --allow-empty -m init", shell=True, cwd=home / "workspace", check=True)
    (home / ".hermes" / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "scripts" / "build.py", home / ".hermes" / "scripts" / "build.py")
    (home / ".hermes" / "scripts" / "vault-log.sh").write_text("#!/bin/bash\n")
    (home / ".local" / "bin").mkdir(parents=True, exist_ok=True)
    (home / ".local" / "bin" / "hermes").write_text(r'''#!/usr/bin/python3
import json, os, sys, time, pathlib
f = pathlib.Path(os.environ["HOME"]) / "board.json"
board = json.loads(f.read_text()) if f.exists() else []
a = sys.argv[1:]
if a[1] == "list":
    print(json.dumps(board))
elif a[1] == "create":
    rest = [x for x in a[3:] if x != "--json"]
    o = dict(zip(rest[0::2], rest[1::2]))
    c = {"id": "t_%04d" % (len(board) + 1), "title": a[2], "assignee": o.get("--assignee"), "body": o.get("--body", ""),
         "status": "todo", "created_at": time.time()}
    board.append(c); f.write_text(json.dumps(board)); print(json.dumps({"id": c["id"]}))
''')
    (home / ".local" / "bin" / "hermes").chmod(0o755)
    srv2 = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "design-view.py"), "--project", "t", "--port", str(port2),
                             "--app", str(app_dir), "--layer", str(home / "vault" / "design" / "layer3"), "--bind", "127.0.0.1",
                             "--api-proxy", f"http://127.0.0.1:{stub.server_address[1]}"],
                            env=dict(os.environ, HOME=str(home)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/ops", timeout=2).read()
                break
            except OSError:
                time.sleep(0.1)
        g = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/api/decks?x=1", timeout=5).read())
        req = urllib.request.Request(f"http://127.0.0.1:{port2}/api/decks", data=b'{"name":"New"}',
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            code, p = r.status, json.loads(r.read())
        check("with a back-end copy, /api GET passes through (query kept)", g == {"method": "GET", "path": "/api/decks?x=1", "got": ""}, g)
        check("...and POST with its body and status", code == 201 and p["got"] == '{"name":"New"}', (code, p))
        o2 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/ops", timeout=5).read())
        check("with a back-end copy the toolbar offers the Data refresh", o2.get("data") is True, o2.get("data"))
        ag3 = (home / "vault" / "design" / "layer3" / "agreed.md").read_text(encoding="utf-8")
        check("an older agreed.md gets the vault header at startup, its entries kept", ag3.startswith("---\n")
              and "an older entry" in ag3, ag3[:150])

        # ---- Agreed for real (not a test copy): build.py makes the build, the Manager gets the plan card ---------
        def post2(path, body):
            req = urllib.request.Request(f"http://127.0.0.1:{port2}{path}", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")
        post2("/dv/op", {"op": {"op": "token", "name": "--bg", "value": "#111"}})
        code, r = post2("/dv/agree", {})
        b = json.loads((home / ".hermes" / "builds" / f"{r.get('build')}.json").read_text()) if r.get("build") else {}
        board = json.loads((home / "board.json").read_text()) if (home / "board.json").exists() else []
        check("Agreed starts a build: branch, worktree, frozen layer", code == 200 and b.get("branch", "").startswith("design/")
              and pathlib.Path(b.get("worktree", "/nope")).is_dir() and json.loads(urllib.request.urlopen(
                  f"http://127.0.0.1:{port2}/dv/ops").read())["frozen"]["build"] == r.get("build"), (code, r, b))
        check("...and the Manager's plan card names the build and its worktree, recorded as the plan card",
              len(board) == 1 and board[0]["assignee"] == "manager" and f"Build: {r.get('build')}" in board[0]["body"]
              and b.get("worktree", "?") in board[0]["body"] and b.get("plan_card") == board[0]["id"], (board, b.get("plan_card")))
        time.sleep(6)
        st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/ops").read()).get("build") or {}
        check("the toolbar follows the build's stage", st.get("state") == "planning" and st.get("rows"), st)
        b["state"] = "live"                                  # as build.py leaves it once it went live
        (home / ".hermes" / "builds" / f"{r['build']}.json").write_text(json.dumps(b))
        time.sleep(6)
        o3 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/ops").read())
        check("live: the mockup unfreezes onto the new app and the layer is archived", not o3["frozen"] and o3["ops"] == [], o3["frozen"])
        post2("/dv/op", {"op": {"op": "token", "name": "--bg", "value": "#222"}})
        code, r2 = post2("/dv/agree", {})
        code, u = post2("/dv/unfreeze", {})
        b2 = json.loads((home / ".hermes" / "builds" / f"{r2['build']}.json").read_text())
        check("Unfreeze stops the build: nothing goes live", code == 200 and b2["state"] == "aborted", (code, u, b2["state"]))
    finally:
        srv2.terminate(); srv2.wait(5); stub.shutdown()
    shutil.rmtree(home, ignore_errors=True)                  # the temporary HOME: nothing left behind
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
