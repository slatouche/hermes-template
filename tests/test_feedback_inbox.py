#!/usr/bin/python3
"""End-to-end checks for the Mark tool's server (template/scripts/feedback-inbox.py), against a fake app.

  python3 tests/test_feedback_inbox.py        (Linux; uses ports 18101-18199 on 127.0.0.1 and a temporary HOME)

Covers: the review link (overlay injected, page served, app never sees the __ switches), drafts (save, list, edit,
delete), Send (one batch, drafts become open, no draft pins left, sent notes can't be edited or deleted), variants
(CSS injected, cookie, the variants page, no path escape), the look badge on a sandbox, and gzip-free proxying.
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
APP, REVIEW, INBOX_PORT = 18101, 18151, 18199
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


def call(method, path, body=None, port=REVIEW, headers=None):
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
    (scripts / "review-mirrors.conf").write_text(f"{REVIEW} {APP} test design sandbox\n")
    (scripts / "sandboxes.conf").write_text(f"test|{APP}|data|true\n")
    (home / "sandbox" / "test").mkdir(parents=True)
    (home / "sandbox" / "test" / "SNAPSHOT").write_text("abc123 test snapshot")
    (home / "vault" / "raw" / "feedback").mkdir(parents=True)
    var = home / "vault" / "design" / "variants" / "v1"
    var.mkdir(parents=True)
    (var / "style.css").write_text("h1{color:red}")
    (var / "note.md").write_text("# Variant one\nRed headings.\n")

    app = http.server.ThreadingHTTPServer(("127.0.0.1", APP), FakeApp)
    threading.Thread(target=app.serve_forever, daemon=True).start()
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

        # the review link
        st, h, page = call("GET", "/")
        check("review link serves the app", st == 200 and b"Hello" in page, st)
        check("overlay injected", b"/__mark/overlay.js" in page)
        check("sandbox badge config injected", b"__markBadge" in page and b"abc123" in page)
        check("app's ETag dropped on injected pages", "ETag" not in h and h.get("Cache-Control") == "no-store", h)
        st, _, js = call("GET", "/__mark/overlay.js")
        check("overlay served with the app name", st == 200 and b"test design sandbox" in js and b"__INBOX__" not in js)

        # variants
        st, h, page = call("GET", "/?__variant=v1&__shot=1&__scroll=40#x")
        check("variant CSS injected", b"/__mark/v/v1/style.css" in page)
        check("shot mode: no overlay, scroll script", b"overlay.js" not in page and b"scrollTo(0,40)" in page)
        check("app never sees the __ switches", seen and seen[-1] == "/", seen[-1:])
        st, h, _ = call("GET", "/?__variant=v1")
        check("variant remembered in a cookie", "mark_variant=v1" in h.get("Set-Cookie", ""), h.get("Set-Cookie"))
        st, _, vp = call("GET", "/__mark/variants")
        check("variants page lists the variant", st == 200 and b"Variant one" in vp)
        st, _, css = call("GET", "/__mark/v/v1/style.css")
        check("variant file served", st == 200 and css == b"h1{color:red}")
        st, _, _ = call("GET", "/__mark/v/v1/..%2F..%2F..%2F.hermes%2Fscripts%2Ffeedback-inbox.py")
        check("no path escape from the variants folder", st == 404, st)

        # drafts
        base = {"page": f"http://127.0.0.1:{REVIEW}/#/deck", "kind": "element", "selector": "#t", "rect": {"x": 1, "y": 2, "w": 3, "h": 4},
                "viewport": {"w": 800, "h": 600}, "scroll": {"x": 0, "y": 0}, "draft": True}
        st, _, out = call("POST", "/__mark/notes", {**base, "note": "first note\nsecond line"}, headers={"Cookie": "mark_variant=v1"})
        a = json.loads(out)["id"]
        md = (home / "vault/raw/feedback" / f"{a}.md").read_text()
        check("draft keeps the variant from the cookie", '"variant": "v1"' in md and "design/variants/v1" in md)
        check("multi-line notes are quoted on every line", "> first note\n> second line" in md)
        st, _, out = call("POST", "/__mark/notes", {**base, "note": "another"})
        b = json.loads(out)["id"]
        st, _, out = call("POST", "/__mark/notes", {**base, "note": "  "})
        check("empty note refused", st == 400, st)
        drafts = json.loads(call("GET", "/__mark/notes?status=draft&page=" + base["page"].replace("#", "%23"))[2])
        check("two drafts on this screen", len(drafts) == 2, len(drafts))
        st, _, _ = call("POST", f"/__mark/notes/{a}/edit", {"note": "first note, edited"})
        md = (home / "vault/raw/feedback" / f"{a}.md").read_text()
        check("edit rewrites the draft", st == 200 and "first note, edited" in md and "status: draft" in md, st)
        st, _, _ = call("POST", f"/__mark/notes/{b}/withdraw", {})
        check("delete a draft", st == 200 and "status: withdrawn" in (home / "vault/raw/feedback" / f"{b}.md").read_text(), st)
        check("no log line for drafts", not (home / "vault" / "log.md").exists())

        # send
        st, _, out = call("POST", "/__mark/notes/send", {"summary": "overall comment"})
        d = json.loads(out)
        check("send returns one batch", st == 200 and d["sent"] == 1 and d["batch"], d)
        check("send falls back to the Manager without hermes", d.get("to") == "Manager", d)
        bpage = (home / "vault/raw/feedback" / f"{d['batch']}.md").read_text()
        check("batch page lists the note and the comment", "overall comment" in bpage and a in bpage)
        md = (home / "vault/raw/feedback" / f"{a}.md").read_text()
        check("sent note is open and in the batch", "status: open" in md and f"batch: {d['batch']}" in md)
        drafts = json.loads(call("GET", "/__mark/notes?status=draft")[2])
        check("no drafts left, so no pins", drafts == [], drafts)
        st, _, _ = call("POST", f"/__mark/notes/{a}/edit", {"note": "late change"})
        check("a sent note can't be edited", st == 409, st)
        st, _, _ = call("POST", f"/__mark/notes/{a}/withdraw", {})
        check("a sent note can't be deleted", st == 409, st)
        st, _, out = call("POST", "/__mark/notes/send", {})
        check("nothing to send", json.loads(out)["sent"] == 0)

        # the inbox's own page
        st, _, page = call("GET", "/", port=INBOX_PORT)
        check("inbox page lists the review link", st == 200 and str(REVIEW).encode() in page)
    finally:
        srv.terminate()
        err = srv.communicate(timeout=5)[1].decode()
        app.shutdown()
        if "Traceback" in err:
            check("server raised no errors", False, err[-800:])
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
