#!/usr/bin/python3
"""A throwaway page for trying the Mark overlay by hand or in a browser test, without touching any real app or notes.

  python3 tests/mark_demo.py [minutes]     serves a demo app on 127.0.0.1:18101 and its review link on 127.0.0.1:18151

The demo page has a long window scroll, a panel that scrolls on its own, and a keyboard shortcut counter (window.keys)
so you can check that typing a note never reaches the app. Notes go to a temporary vault, deleted afterwards.
"""
import http.server
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "template" / "scripts"
APP, REVIEW, INBOX_PORT = 18101, 18151, 18199
ROWS = "".join(f"<div class=row id=r{i}>Row {i}</div>" for i in range(60))
PAGE = f"""<!doctype html><html><head><meta charset=utf-8><title>Mark demo</title><style>
body{{font:15px system-ui;margin:0;background:#111;color:#eee}}header{{padding:16px;background:#222}}
main{{display:flex;gap:16px;padding:16px}}#panel{{height:300px;overflow:auto;width:300px;border:1px solid #444}}
.row{{padding:10px;border-bottom:1px solid #333}}#long{{height:2000px;flex:1;border:1px solid #444;padding:8px}}
</style></head><body><header><h1 id=title>Mark demo</h1><button id=save>Save</button></header>
<main><div id=panel>{ROWS}</div><div id=long><p id=top>Top of the long column</p><p id=far style="margin-top:1500px">Far down</p></div></main>
<script>window.keys=0;addEventListener('keydown',()=>window.keys++)</script></body></html>""".encode()


class Demo(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    home = pathlib.Path(tempfile.mkdtemp(prefix="markdemo-"))
    scripts = home / ".hermes" / "scripts"
    scripts.mkdir(parents=True)
    for f in ("feedback-inbox.py", "feedback-overlay.js"):
        shutil.copy(SCRIPTS / f, scripts / f)
    (scripts / "review-mirrors.conf").write_text(f"{REVIEW} {APP} demo\n")
    (home / "vault" / "raw" / "feedback").mkdir(parents=True)
    app = http.server.ThreadingHTTPServer(("127.0.0.1", APP), Demo)
    threading.Thread(target=app.serve_forever, daemon=True).start()
    srv = subprocess.Popen([sys.executable, str(scripts / "feedback-inbox.py"), str(INBOX_PORT)],
                           env={**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"})
    print(f"demo: http://127.0.0.1:{REVIEW}/  (notes in {home}/vault/raw/feedback, for {minutes:g} minutes)", flush=True)
    try:
        time.sleep(minutes * 60)
    finally:
        srv.terminate()
        app.shutdown()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
