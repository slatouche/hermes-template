#!/usr/bin/python3
"""The owner's feedback inbox: mark things on this project's web pages, and the notes land in the vault.

  feedback-inbox.py <inbox port>      run by the `feedback-inbox` systemd user service (last port of the block)

Two ways in:
- **Review links (recommended).** For each app in ~/.hermes/scripts/review-mirrors.conf (lines: `<review port> <app port> <name>`)
  the inbox serves the same live app on the review port with the Mark toolbar already in it, e.g. the app on :10301 is
  reviewed at :10351. Same address for page and notes, so no browser setting can block it. Live reloads and streams pass
  through; WebSockets don't.
- **The bookmarklet** on http://<host>:<inbox port>/ for any other page (works where the browser allows the request).

Design variants (the Designer's quick options on the real app, no rebuild): a folder vault/design/variants/<name>/ with
style.css (and optionally script.js for small DOM moves with placeholder content, note.md: a title line and two lines
of why, and screenshots). On a review link, `?__variant=<name>` turns it on (a cookie keeps it while you click around),
`?__variant=off` turns it off, and /__mark/variants shows every variant side by side with a "try it live" link.
Notes marked while a variant is on record its name.

Notes go to vault/raw/feedback/<time>-<slug>.md (status: open) with a log line. The Manager turns them into cards
(Designer for how it looks, Engineer for what's broken) and marks each done with the card id. Stdlib only; LAN-only
by the firewall. Restart the service after editing review-mirrors.conf.
"""
import datetime
import html
import http.client
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOME = pathlib.Path.home()
INBOX = HOME / "vault" / "raw" / "feedback"
SCRIPTS = HOME / ".hermes" / "scripts"
OVERLAY = SCRIPTS / "feedback-overlay.js"
MIRRORS = SCRIPTS / "review-mirrors.conf"
VARIANTS = HOME / "vault" / "design" / "variants"
SANDBOXES = SCRIPTS / "sandboxes.conf"
MAX = 4000
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "content-length", "accept-encoding", "content-encoding"}


def notes(status="open", page=None, app=None):
    out = []
    for f in sorted(INBOX.glob("*.md")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^```json\n(.*?)\n```", txt, re.S | re.M)
        if not m:
            continue
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        st = re.search(r"^status:\s*(\S+)", txt, re.M)
        d["status"] = st.group(1) if st else "open"
        d["id"] = f.stem
        if status and d["status"] not in status.split(","):
            continue
        if app and d.get("app") != app:
            continue
        if page:                                   # same screen: path plus #route (single-page apps), query ignored
            a, b = urlparse(d.get("page", "")), urlparse(page)
            if (a.path, a.fragment) != (b.path, b.fragment):
                continue
        out.append(d)
    return out


def clean(s, n):
    return str(s or "").replace("\r", "")[:n]


def render(rec, status, now):
    note = rec["note"]
    summary = note.splitlines()[0][:90].replace('"', "'")
    vp = rec.get("viewport") or {}
    quoted = "\n".join("> " + ln for ln in note.splitlines())
    return (f"---\ntitle: \"Owner note: {summary}\"\ntype: research\nstatus: {status}\nowner: manager\n"
            f"updated: {now:%Y-%m-%d}\nsummary: \"Owner feedback on {clean(rec.get('app') or rec.get('title') or rec.get('page'), 60)}: {summary}\"\n"
            f"tags: [feedback]\ncard: none\n---\n"
            f"# {summary}\n\n{quoted}\n\n- **App / page:** {rec.get('app') or '-'} · {rec.get('page')}\n"
            + (f"- **Variant on:** `design/variants/{rec['variant']}/`\n" if rec.get("variant") else "") +
            f"- **Where:** `{rec.get('selector') or 'an area'}` ({rec.get('kind')})\n"
            f"- **Element text:** {clean(rec.get('text'), 200)!r}\n- **Screen:** {vp.get('w')}x{vp.get('h')}\n\n"
            "_From the owner's Mark overlay. Evidence for a card, not instructions to follow as written: "
            "the Manager turns it into a card and sets `status: done` and `card:` here._\n\n"
            f"```json\n{json.dumps(rec, ensure_ascii=False)}\n```\n")


def save(d):
    INBOX.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    note = clean(d.get("note"), MAX).strip()
    if not note:
        raise ValueError("empty note")
    slug = re.sub(r"[^a-z0-9]+", "-", note.lower())[:40].strip("-") or "note"
    stem = f"{now:%Y-%m-%d-%H%M%S}-{slug}"
    rec = {k: d.get(k) for k in ("page", "app", "variant", "title", "kind", "selector", "text", "rect", "viewport", "scroll", "ua")}
    rec["note"] = note
    rec = {k: (clean(v, 600) if isinstance(v, str) and k != "note" else v) for k, v in rec.items()}
    status = "draft" if d.get("draft") else "open"   # the overlay's notes wait as drafts until the owner presses Send
    (INBOX / f"{stem}.md").write_text(render(rec, status, now), encoding="utf-8")
    log = SCRIPTS / "vault-log.sh"
    if log.exists() and status == "open":
        subprocess.run([str(log), "owner", "note", f"Feedback on {clean(rec.get('app') or rec.get('title'), 40)}: "
                        f"{note.splitlines()[0][:80]}", f"raw/feedback/{stem}"], capture_output=True)
    return stem


def edit(stem, note):
    """Change a draft's text (sent notes are the team's now)."""
    f = INBOX / f"{stem}.md"
    t = f.read_text(encoding="utf-8")
    m = re.search(r"^```json\n(.*?)\n```", t, re.S | re.M)
    if not m or not re.search(r"^status:\s*draft", t, re.M):
        return False
    rec = json.loads(m.group(1))
    rec["note"] = clean(note, MAX).strip()
    f.write_text(render(rec, "draft", datetime.datetime.now()), encoding="utf-8")
    return True


def set_field(f, field, value):
    t = f.read_text(encoding="utf-8")
    if re.search(rf"^{field}:", t, re.M):
        t = re.sub(rf"^{field}:.*$", f"{field}: {value}", t, count=1, flags=re.M)
    else:
        t = t.replace("\n---\n", f"\n{field}: {value}\n---\n", 1)
    f.write_text(t, encoding="utf-8")


def send(app, summary=""):
    """The owner pressed Send: every draft for this app becomes one batch of open notes, and the Manager is woken."""
    drafts = [n for n in notes("draft") if not app or n.get("app") == app]
    if not drafts:
        return None, 0
    now = datetime.datetime.now()
    batch = f"{now:%Y-%m-%d-%H%M%S}-batch"
    for n in drafts:
        f = INBOX / f"{n['id']}.md"
        set_field(f, "status", "open")
        set_field(f, "batch", batch)
    variants = sorted({n["variant"] for n in drafts if n.get("variant")})
    lines = "".join(f"- [[raw/feedback/{n['id']}]]" + (f" (variant `{n['variant']}`)" if n.get("variant") else "")
                    + f": {clean(n.get('note'), 200).splitlines()[0]}\n" for n in drafts)
    summary = clean(summary, MAX).strip()
    on = f" on variant {', '.join(variants)}" if variants else ""
    (INBOX / f"{batch}.md").write_text(
        f"---\ntitle: \"Owner feedback batch: {len(drafts)} notes{on}\"\ntype: research\nstatus: open\nowner: manager\n"
        f"updated: {now:%Y-%m-%d}\nsummary: \"{len(drafts)} notes the owner sent together{on}\"\ntags: [feedback, batch]\n"
        f"card: none\n---\n# Owner feedback: {len(drafts)} notes, sent together\n\n"
        + ("\n".join("> " + ln for ln in summary.splitlines()) + "\n\n" if summary else "")
        + lines + "\n_One review pass: card it as one round for the bot that owns it (the Designer when a variant was on), "
        "then set `status: done` and `card:` here and on each note._\n", encoding="utf-8")
    log = SCRIPTS / "vault-log.sh"
    if log.exists():
        subprocess.run([str(log), "owner", "note", f"Sent {len(drafts)} feedback notes{on}"
                        + (f": {summary.splitlines()[0][:80]}" if summary else ""), f"raw/feedback/{batch}"], capture_output=True)
    # Wake the Manager now instead of at the next 2-hourly watch (it runs on the scheduler's next tick).
    subprocess.Popen(["hermes", "-p", "manager", "cron", "run", "manager-watch"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env={**os.environ, "PATH": f"{HOME}/.local/bin:/usr/bin:/bin"})
    return batch, len(drafts)


def mirrors():
    out = []
    if MIRRORS.exists():
        for line in MIRRORS.read_text().splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                out.append((int(parts[0]), int(parts[1]), " ".join(parts[2:]) or f"app on {parts[1]}"))
    return out


def variant_list():
    out = []
    if VARIANTS.is_dir():
        for d in sorted(p for p in VARIANTS.iterdir() if p.is_dir() and re.fullmatch(r"[\w-]+", p.name)):
            note = d / "note.md"
            lines = [ln.strip("# ").strip() for ln in note.read_text(encoding="utf-8", errors="replace").splitlines()
                     if ln.strip() and not ln.startswith("---")] if note.exists() else []
            pf = d / "page.txt"                        # the screen variant-shot.sh shot, so "try it live" opens there
            page = pf.read_text(encoding="utf-8").strip() if pf.exists() else "/"
            out.append({"name": d.name, "title": lines[0] if lines else d.name, "why": " ".join(lines[1:3]), "page": page or "/",
                        "shots": sorted((p.name for p in d.glob("*.png")),
                                        key=lambda n: -int(m.group(1)) if (m := re.search(r"-(\d+)\.png$", n)) else 0)})
    out.sort(key=lambda v: v["name"] != "current")      # today's look first, to compare against
    return out


def sandboxes():
    """{sandbox port: name} from sandbox.sh's list: copies of an app, safe to click around in."""
    out = {}
    if SANDBOXES.exists():
        for line in SANDBOXES.read_text().splitlines():
            p = line.split("|")
            if len(p) >= 2 and p[1].strip().isdigit() and not line.lstrip().startswith("#"):
                out[int(p[1])] = p[0].strip()
    return out


def variants_page(base=""):
    """base: where "try it live" opens, "" for this link or "//host:port" for the design sandbox's link."""
    esc = html.escape
    cards = ""
    for v in variant_list():
        n = v["name"]
        path, _, frag = v["page"].partition("#")
        live = base + f"{path or '/'}{'&' if '?' in path else '?'}__variant={'off' if n == 'current' else n}" + (f"#{frag}" if frag else "")
        imgs = "".join(f"<a href='/__mark/v/{n}/{esc(s)}'><img loading=lazy src='/__mark/v/{n}/{esc(s)}' alt='{esc(s)}'></a>"
                       for s in v["shots"])
        cards += (f"<section><h2>{esc(v['title'])}</h2><p class=dim>{esc(v['why'])}</p><div class=shots>{imgs}</div>"
                  f"<a class=bm href='{esc(live, quote=True)}'>Try it live</a> <code>{n}</code></section>")
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Design variants</title><style>body{{font:15px/1.5 system-ui;background:#111214;color:#e8e8ea;margin:0 auto;max-width:90rem;padding:1.5rem 1rem}}
a{{color:#9db8ff}}.bm{{display:inline-block;padding:.45rem .9rem;border-radius:.5rem;background:#2d5bff;color:#fff;text-decoration:none;font-weight:600}}
section{{border-top:1px solid #2a2c31;padding:1rem 0}}.dim{{color:#9aa0ad;margin:.2rem 0 .6rem}}h2{{margin:0;font-size:1.1rem}}
.shots{{display:flex;gap:.6rem;overflow-x:auto;margin-bottom:.7rem}}.shots a{{flex:none}}.shots img{{display:block;height:min(24rem,62vw);width:auto;border:1px solid #2a2c31;border-radius:.4rem}}</style>
<h1>Design variants</h1><p class=dim>Each is the app with a different look{' (a sandbox copy: nothing you do touches your real data)' if base else ''}.
Try one, click around, Mark what you think, then Send.</p>{cards or '<p class=dim>No variants yet.</p>'}"""


def badge(variant, sandbox):
    """The pill bottom-left on a review link: every look as a one-click switch (it keeps you on the same screen), and
    on a sandbox, which snapshot it is. It stays while you click around."""
    names = [v["name"] for v in variant_list() if v["name"] != "current"]
    if not variant and not sandbox and not names:
        return b""
    esc = html.escape
    sw = ("(function(v){var u=new window.URL(location.href);u.searchParams.set('__variant',v);location.href=u.pathname+u.search+u.hash;"
          "return false})")
    looks = [("off", "current")] + [(n, n) for n in names]
    look = "Look: " + " ".join(
        f"<b>{esc(label)}</b>" if (key == variant or (key == "off" and not variant))
        else f"<button onclick=\"return {sw}('{key}')\">{esc(label)}</button>" for key, label in looks)
    look += " · <a href='/__mark/variants'>compare</a>"
    snap = ""
    if sandbox:
        sf = HOME / "sandbox" / sandbox / "SNAPSHOT"
        info = sf.read_text(encoding="utf-8").strip() if sf.exists() else ""
        snap = (f"<span title='{esc(info, quote=True)}'>Sandbox</span> · <button onclick=\"if(confirm('Put the sandbox data back to a "
                f"fresh copy of the real data?'))fetch('/__mark/sandbox/reset',{{method:'POST'}}).then(()=>location.reload());"
                f"return false\">reset data</button> · ")
    return (f"<div id=__mark_badge style='position:fixed;left:12px;bottom:12px;z-index:2147483646;font:600 12px system-ui;"
            f"background:{'#7a3cff' if sandbox else '#2d5bff'};color:#fff;padding:6px 10px;border-radius:999px;"
            f"box-shadow:0 2px 8px #0006'><style>#__mark_badge a,#__mark_badge button{{all:unset;color:#fff;text-decoration:underline;cursor:pointer}}</style>{snap}{look}</div>").encode()


class Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    prefix = ""          # where the inbox endpoints live: "" on the inbox port, "/__mark" inside a review mirror
    app_name = ""

    def log_message(self, *a):
        pass

    def current_variant(self):
        return None

    def _send(self, code, body, ctype="application/json", cors=True):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def inbox_get(self, path, query):
        if path == "/overlay.js":
            base = self.prefix or f"http://{self.headers.get('Host')}"
            js = OVERLAY.read_text(encoding="utf-8").replace("__INBOX__", base).replace("__APP__", self.app_name)
            self._send(200, js, "application/javascript")
            return True
        if path == "/notes":
            q = parse_qs(query)
            self._send(200, json.dumps(notes(q.get("status", ["open"])[0], q.get("page", [None])[0], q.get("app", [None])[0])))
            return True
        return False

    def inbox_post(self, path):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64_000:
            self._send(413, '{"error":"too big"}')
            return True
        raw = self.rfile.read(n) if n else b""
        if path == "/notes":
            try:
                d = json.loads(raw or b"{}")
                d.setdefault("app", self.app_name)
                d.setdefault("variant", self.current_variant())
                self._send(201, json.dumps({"id": save(d)}))
            except ValueError as e:
                self._send(400, json.dumps({"error": str(e)}))
            return True
        if path == "/notes/send":
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                d = {}
            batch, count = send(d.get("app") or self.app_name, d.get("summary", ""))
            self._send(200, json.dumps({"batch": batch, "sent": count}))
            return True
        m = re.fullmatch(r"/notes/([\w-]+)/edit", path)
        if m and (INBOX / f"{m.group(1)}.md").exists():
            try:
                ok = edit(m.group(1), json.loads(raw or b"{}").get("note", ""))
            except ValueError:
                ok = False
            self._send(200 if ok else 409, '{"ok":true}' if ok else '{"error":"only drafts can be edited"}')
            return True
        m = re.fullmatch(r"/notes/([\w-]+)/withdraw", path)
        if m and (INBOX / f"{m.group(1)}.md").exists():
            f = INBOX / f"{m.group(1)}.md"
            f.write_text(re.sub(r"^status:\s*\S+", "status: withdrawn", f.read_text(encoding="utf-8"), count=1, flags=re.M),
                         encoding="utf-8")
            self._send(200, '{"ok":true}')
            return True
        return False


class Inbox(Base):
    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        u = urlparse(self.path)
        if self.inbox_get(u.path, u.query):
            return
        if u.path == "/":
            host = self.headers.get("Host", "")
            addr = host.split(":")[0]
            bm = ("javascript:(()=>{if(window.__markLoaded){window.__markToggle&&window.__markToggle();return;}"
                  f"var s=document.createElement('script');s.src='http://{host}/overlay.js?'+Date.now();"
                  "document.body.appendChild(s);})()")
            esc = html.escape
            links = "".join(f"<li><a class=bm href='http://{esc(addr)}:{rp}/'>Review {esc(name)}</a> "
                            f"<span class=dim>the app on :{ap}, with the Mark toolbar</span></li>" for rp, ap, name in mirrors())
            open_notes = notes()
            rows = "".join(f"<li><a href='{esc(n.get('page') or '', quote=True)}'>{esc(n.get('app') or n.get('title') or 'page')}</a>: "
                           f"{esc(n['note'][:160])}</li>" for n in open_notes)
            page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Feedback inbox</title><style>body{{font:15px/1.55 system-ui;background:#111214;color:#e8e8ea;max-width:46rem;margin:3rem auto;padding:0 1rem}}
a{{color:#9db8ff}}.bm{{display:inline-block;padding:.55rem 1rem;border-radius:.6rem;background:#2d5bff;color:#fff;text-decoration:none;font-weight:600}}
li{{margin:.6rem 0}}.dim{{color:#9aa0ad}}code{{background:#1d1f23;padding:.1rem .3rem;border-radius:.3rem}}ul{{padding-left:1.1rem}}</style>
<h1>Feedback inbox</h1>
<h2>Review an app</h2><ul>{links or '<li class=dim>No review links yet: the team adds one when an app is running.</li>'}</ul>
<p>In the review link: <b>Mark</b> then click an element, or <b>Area</b> and drag a box. Type what's wrong, <b>Save</b>
(<code>Ctrl+Enter</code>). <code>Esc</code> stops. Numbered pins show notes still open.</p>
<h2>Any other page</h2><p>Drag <a class=bm href="{bm}">Mark</a> to your bookmarks bar and click it on the page
(if the browser blocks it, use a review link).</p>
<h2>Open notes ({len(open_notes)})</h2><ul>{rows or '<li class=dim>none</li>'}</ul>"""
            return self._send(200, page, "text/html")
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self.inbox_post(urlparse(self.path).path):
            self._send(404, '{"error":"not found"}')


def mirror_handler(app_port, name):
    class Mirror(Base):
        prefix = "/__mark"
        app_name = name

        def current_variant(self):
            q = parse_qs(urlparse(self.path).query).get("__variant", [None])[0]
            if q is None:
                m = re.search(r"(?:^|;\s*)mark_variant=([\w-]+)", self.headers.get("Cookie", ""))
                q = m.group(1) if m else None
            return q if q and q != "off" and (VARIANTS / q).is_dir() else None

        def _variant_file(self, sub):
            m = re.fullmatch(r"/v/([\w-]+)/([\w.-]+)", sub)
            f = VARIANTS / m.group(1) / m.group(2) if m else None
            if not f or not f.is_file():
                return self._send(404, '{"error":"not found"}')
            types = {".css": "text/css", ".js": "application/javascript", ".png": "image/png", ".jpg": "image/jpeg",
                     ".svg": "image/svg+xml", ".md": "text/plain", ".html": "text/html"}
            self._send(200, f.read_bytes(), types.get(f.suffix, "application/octet-stream"))

        def _proxy(self):
            u = urlparse(self.path)
            sandbox = sandboxes().get(app_port)
            if u.path == "/__mark/variants":
                # "Try it live" goes to the design sandbox when there is one, so trying a look never touches real data.
                sb = next(iter(sandboxes()), None)
                base = "" if sandbox or not sb else f"//{(self.headers.get('Host') or '').split(':')[0]}:{sb + 50}"
                return self._send(200, variants_page(base), "text/html")
            if u.path == "/__mark/sandbox/reset" and self.command == "POST" and sandbox:
                r = subprocess.run([str(SCRIPTS / "sandbox.sh"), "reset", sandbox], capture_output=True, text=True)
                return self._send(200 if r.returncode == 0 else 500, json.dumps({"ok": r.returncode == 0, "out": r.stdout[-300:] + r.stderr[-300:]}))
            if u.path.startswith("/__mark/v/"):
                return self._variant_file(u.path[len("/__mark"):])
            if u.path.startswith("/__mark/"):
                sub = u.path[len("/__mark"):]
                ok = self.inbox_get(sub, u.query) if self.command == "GET" else self.inbox_post(sub)
                if not ok:
                    self._send(404, '{"error":"not found"}')
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else None
            hdrs = {k: v for k, v in self.headers.items()
                    if k.lower() not in HOP and k.lower() not in ("host", "if-none-match", "if-modified-since")}
            hdrs["Host"] = f"127.0.0.1:{app_port}"
            fwd = self.path
            if "__variant=" in u.query or "__shot=" in u.query:   # the app never sees the variant switches
                rest = "&".join(p for p in u.query.split("&") if not p.startswith(("__variant=", "__shot=")))
                fwd = u.path + ("?" + rest if rest else "")
            conn = http.client.HTTPConnection("127.0.0.1", app_port, timeout=600)
            try:
                conn.request(self.command, fwd, body=body, headers=hdrs)
                r = conn.getresponse()
            except OSError as e:
                return self._send(502, f"The app on :{app_port} isn't answering ({e}).", "text/plain", cors=False)
            ctype = r.getheader("Content-Type", "")
            if "text/html" in ctype:
                page = r.read()
                shot = "__shot=" in u.query              # variant-shot.sh: no toolbar or badge in the picture
                tag = b"" if shot else b'<script src="/__mark/overlay.js" defer></script>'
                v = self.current_variant()
                if v:                                  # the Designer's variant on top of the live app
                    vd = VARIANTS / v
                    tag += f'<link rel="stylesheet" href="/__mark/v/{v}/style.css">'.encode() if (vd / "style.css").exists() else b""
                    tag += f'<script src="/__mark/v/{v}/script.js" defer></script>'.encode() if (vd / "script.js").exists() else b""
                tag += b"" if shot else badge(v, sandbox)
                page = re.sub(rb"(?i)</body>", tag + b"</body>", page, count=1) if re.search(rb"(?i)</body>", page) else page + tag
                self.send_response(r.status, r.reason)
                q = parse_qs(u.query).get("__variant", [None])[0]
                if q is not None and not shot:         # remember the choice while the owner clicks around
                    self.send_header("Set-Cookie", f"mark_variant={v or 'off'}; Path=/; SameSite=Lax")
                for k, val in r.getheaders():
                    if k.lower() not in HOP and k.lower() not in ("content-security-policy", "etag", "last-modified", "cache-control"):
                        self.send_header(k, val)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            else:
                self.send_response(r.status, r.reason)
                for k, v in r.getheaders():
                    if k.lower() not in HOP:
                        self.send_header(k, v)
                length = r.getheader("Content-Length")
                if length is not None:
                    self.send_header("Content-Length", length)
                else:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                while True:                       # stream (event streams and live reloads flush as they come)
                    chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            conn.close()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _proxy

        def do_OPTIONS(self):
            if self.path.startswith("/__mark/"):
                return self._send(204, b"")
            self._proxy()
    return Mirror


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        sys.exit("usage: feedback-inbox.py <inbox port>")
    servers = [ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Inbox)]
    for rp, ap, name in mirrors():
        try:
            servers.append(ThreadingHTTPServer(("0.0.0.0", rp), mirror_handler(ap, name)))
        except OSError as e:
            print(f"feedback-inbox: review port {rp} for {name}: {e}", file=sys.stderr)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    servers[0].serve_forever()
