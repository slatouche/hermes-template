#!/usr/bin/python3
"""End-to-end checks for the Mark tool's server (template/scripts/feedback-inbox.py), against fake apps.

  python3 tests/test_feedback_inbox.py        (Linux; uses ports 18101-18199 on 127.0.0.1 and a temporary HOME)

Three review links, as on a real project: the mockup (a copy of an app), demo 1 (a new thing), and the real app.
Covers: the review link (overlay injected, the app never sees the __ switches), the badge on the mockup and on a demo,
each note recording where it was left, drafts (save, list, edit, delete), Send (one batch across the mockup and the
demos, the real app's notes kept apart, grouped by source, no draft pins left, sent notes can't be edited or deleted),
looks (CSS injected, cookie, the variants page, no path escape).
"""
import http.client
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "template" / "scripts"
MOCK_APP, DEMO_APP, REAL_APP = 18101, 18102, 18103
MOCK, DEMO, REAL, INBOX_PORT = 18151, 18152, 18153, 18199
seen = []


class FakeApp(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        seen.append(self.path)
        body = b"<!doctype html><html><head><title>Fake</title></head><body><h1 id=t>Hello</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", '"abc"')
        self.end_headers()
        self.wfile.write(body)


def call(method, path, body=None, port=MOCK, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    data = json.dumps(body).encode() if body is not None else None
    c.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
    r = c.getresponse()
    out = r.read()
    return r.status, dict(r.getheaders()), out


failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


def main():
    home = pathlib.Path(tempfile.mkdtemp(prefix="fitest-"))
    scripts = home / ".hermes" / "scripts"
    scripts.mkdir(parents=True)
    for f in ("feedback-inbox.py", "feedback-overlay.js"):
        (scripts / f).write_bytes((SCRIPTS / f).read_bytes())
    (scripts / "review-mirrors.conf").write_text(f"{MOCK} {MOCK_APP} test mockup\n{DEMO} {DEMO_APP} demo 1: card backs\n"
                                                 f"{REAL} {REAL_APP} Test app\n")
    (scripts / "mockups.conf").write_text(f"test|{MOCK_APP}|data|true\n")
    (home / "mockup" / "test").mkdir(parents=True)
    (home / "mockup" / "test" / "SNAPSHOT").write_text("abc123 test snapshot")
    fb = home / "vault" / "raw" / "feedback"
    fb.mkdir(parents=True)
    var = home / "vault" / "design" / "variants" / "v1"
    var.mkdir(parents=True)
    (var / "style.css").write_text("h1{color:red}")
    (var / "note.md").write_text("# Variant one\nRed headings.\n")

    apps = [http.server.ThreadingHTTPServer(("127.0.0.1", p), FakeApp) for p in (MOCK_APP, DEMO_APP, REAL_APP)]
    for a in apps:
        threading.Thread(target=a.serve_forever, daemon=True).start()
    env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}   # no hermes on PATH: Send must still work
    srv = subprocess.Popen([sys.executable, str(scripts / "feedback-inbox.py"), str(INBOX_PORT)], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            try:
                call("GET", "/__mark/notes")
                break
            except OSError:
                time.sleep(0.1)

        # review links
        st, h, page = call("GET", "/")
        check("mockup link serves the app", st == 200 and b"Hello" in page, st)
        check("overlay injected", b"/__mark/overlay.js" in page)
        check("mockup badge: its snapshot", b"__markBadge" in page and b"abc123" in page and b'"demo": null' in page)
        check("app's ETag dropped on injected pages", "ETag" not in h and h.get("Cache-Control") == "no-store", h)
        st, _, page = call("GET", "/", port=DEMO)
        check("demo badge: which demo", b'"demo": "demo 1: card backs"' in page and b'"looks": []' in page)
        st, _, page = call("GET", "/", port=REAL)
        check("real app link: no badge without looks", b"__markBadge" not in page)
        st, _, js = call("GET", "/__mark/overlay.js")
        check("overlay served with the link's name", st == 200 and b"test mockup" in js and b"__INBOX__" not in js)

        # looks
        st, h, page = call("GET", "/?__variant=v1&__shot=1&__scroll=40#x")
        check("look's CSS injected", b"/__mark/v/v1/style.css" in page)
        check("shot mode: no overlay, scroll script", b"overlay.js" not in page and b"scrollTo(0,40)" in page)
        check("the app never sees the __ switches", seen and seen[-1] == "/", seen[-1:])
        st, h, _ = call("GET", "/?__variant=v1")
        check("look remembered in a cookie", "mark_variant=v1" in h.get("Set-Cookie", ""), h.get("Set-Cookie"))
        st, _, page = call("GET", "/", port=REAL, headers={"Cookie": "mark_variant=v1"})
        check("the mockup's look doesn't follow onto the real app", b"/__mark/v/v1/style.css" not in page)
        st, _, vp = call("GET", "/__mark/variants")
        check("variants page lists the look", st == 200 and b"Variant one" in vp)
        st, _, vp = call("GET", "/__mark/variants", port=REAL)
        check("from the real app, try-it-live opens the mockup", f":{MOCK}/".encode() in vp)
        st, _, css = call("GET", "/__mark/v/v1/style.css")
        check("look file served", st == 200 and css == b"h1{color:red}")
        st, _, _ = call("GET", "/__mark/v/v1/..%2F..%2F..%2F.hermes%2Fscripts%2Ffeedback-inbox.py")
        check("no path escape from the looks folder", st == 404, st)

        # drafts, with where each was left
        base = {"page": f"http://127.0.0.1:{MOCK}/#/deck", "kind": "element", "selector": "#t", "rect": {"x": 1, "y": 2, "w": 3, "h": 4},
                "viewport": {"w": 800, "h": 600}, "scroll": {"x": 0, "y": 0}, "draft": True}
        a = json.loads(call("POST", "/__mark/notes", {**base, "note": "first note\nsecond line"}, headers={"Cookie": "mark_variant=v1"})[2])["id"]
        md = (fb / f"{a}.md").read_text()
        check("note keeps the look from the cookie", '"variant": "v1"' in md and "design/variants/v1" in md)
        check("note says it was left on the mockup", "**Left on:** the mockup (test)" in md)
        check("multi-line notes are quoted on every line", "> first note\n> second line" in md)
        b = json.loads(call("POST", "/__mark/notes", {**base, "note": "another"})[2])["id"]
        d1 = json.loads(call("POST", "/__mark/notes", {**base, "page": f"http://127.0.0.1:{DEMO}/", "note": "demo option B"}, port=DEMO)[2])["id"]
        check("note says which demo", "**Left on:** demo 1: card backs" in (fb / f"{d1}.md").read_text())
        r1 = json.loads(call("POST", "/__mark/notes", {**base, "page": f"http://127.0.0.1:{REAL}/", "note": "real app bug"}, port=REAL)[2])["id"]
        check("note says it was the real app", "(the real app)" in (fb / f"{r1}.md").read_text())
        st, _, _ = call("POST", "/__mark/notes", {**base, "note": "  "})
        check("empty note refused", st == 400, st)
        mine = json.loads(call("GET", "/__mark/notes?status=draft&scope=mine")[2])
        check("Send from the mockup covers mockup and demo drafts", sorted(n["id"] for n in mine) == sorted([a, b, d1]), [n["id"] for n in mine])
        mine = json.loads(call("GET", "/__mark/notes?status=draft&scope=mine", port=REAL)[2])
        check("Send from the real app covers only its own", [n["id"] for n in mine] == [r1], [n["id"] for n in mine])
        st, _, _ = call("POST", f"/__mark/notes/{a}/edit", {"note": "first note, edited"})
        md = (fb / f"{a}.md").read_text()
        check("edit rewrites the draft", st == 200 and "first note, edited" in md and "status: draft" in md, st)
        st, _, _ = call("POST", f"/__mark/notes/{b}/withdraw", {})
        check("delete a draft", st == 200 and "status: withdrawn" in (fb / f"{b}.md").read_text(), st)
        check("no log line for drafts", not (home / "vault" / "log.md").exists())

        # send from the mockup: one batch across the design links
        st, _, out = call("POST", "/__mark/notes/send", {"summary": "overall comment"})
        d = json.loads(out)
        check("send returns one batch of 2", st == 200 and d["sent"] == 2 and d["batch"], d)
        check("send falls back to the Manager without hermes", d.get("to") == "Manager", d)
        bpage = (fb / f"{d['batch']}.md").read_text()
        check("batch lists notes under where they were left",
              "**the mockup (test), look `v1`**" in bpage and "**demo 1: card backs**" in bpage and "overall comment" in bpage, bpage[:400])
        check("the real app's draft is not in the design batch", r1 not in bpage)
        md = (fb / f"{a}.md").read_text()
        check("sent note is open and in the batch", "status: open" in md and f"batch: {d['batch']}" in md)
        check("no design drafts left, so no pins", json.loads(call("GET", "/__mark/notes?status=draft&scope=mine")[2]) == [])
        st, _, _ = call("POST", f"/__mark/notes/{a}/edit", {"note": "late change"})
        check("a sent note can't be edited", st == 409, st)
        st, _, _ = call("POST", f"/__mark/notes/{a}/withdraw", {})
        check("a sent note can't be deleted", st == 409, st)
        check("nothing more to send from the design links", json.loads(call("POST", "/__mark/notes/send", {})[2])["sent"] == 0)
        d = json.loads(call("POST", "/__mark/notes/send", {}, port=REAL)[2])
        check("the real app's note sends on its own", d["sent"] == 1, d)

        st, _, page = call("GET", "/", port=INBOX_PORT)
        check("inbox page lists the review links", st == 200 and str(MOCK).encode() in page and str(DEMO).encode() in page)
    finally:
        srv.terminate()
        err = srv.communicate(timeout=5)[1].decode()
        for a in apps:
            a.shutdown()
        if "Traceback" in err:
            check("server raised no errors", False, err[-800:])
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
