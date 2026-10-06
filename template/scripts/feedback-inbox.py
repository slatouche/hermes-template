#!/usr/bin/python3
"""The owner's feedback inbox: mark things on this project's web pages, and the notes land in the vault.

  feedback-inbox.py <inbox port>      run by the `feedback-inbox` systemd user service (last port of the block)

Two ways in:
- **Review links (recommended).** For each app in ~/.hermes/scripts/review-mirrors.conf (lines: `<review port> <app port> <name>`)
  the inbox serves the same live app on the review port with the Mark toolbar already in it, e.g. the app on :10301 is
  reviewed at :10351. Same address for page and notes, so no browser setting can block it. Live reloads and streams pass
  through; WebSockets don't.
- **The bookmarklet** on http://<host>:<inbox port>/ for any other page (works where the browser allows the request).

Design links: the mockup (a copy of an app, mockup.sh) and two demo slots for new things (demo.sh), each with the
Mark tool; every note records which one it was left on. Design variants (the Designer's looks on the mockup): a folder vault/design/variants/<name>/ with
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
from urllib.parse import parse_qs, quote, urlparse

HOME = pathlib.Path.home()
INBOX = HOME / "vault" / "raw" / "feedback"
SCRIPTS = HOME / ".hermes" / "scripts"
OVERLAY = SCRIPTS / "feedback-overlay.js"
MIRRORS = SCRIPTS / "review-mirrors.conf"
VARIANTS = HOME / "vault" / "design" / "variants"
MOCKUPS = SCRIPTS / "mockups.conf"
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


def render(rec, status, now, stem=None):
    note = rec["note"]
    summary = note.splitlines()[0][:90].replace('"', "'")
    vp = rec.get("viewport") or {}
    quoted = "\n".join("> " + ln for ln in note.splitlines())
    return (f"---\ntitle: \"Owner note: {summary}\"\ntype: research\nstatus: {status}\nowner: manager\n"
            f"updated: {now:%Y-%m-%d}\nsummary: \"Owner feedback on {clean(rec.get('app') or rec.get('title') or rec.get('page'), 60)}: {summary}\"\n"
            f"tags: [feedback]\ncard: none\n---\n"
            f"# {summary}\n\n{quoted}\n\n- **App / page:** {rec.get('app') or '-'} · {rec.get('page')}\n"
            + (f"- **Left on:** {(rec.get('source') or {}).get('label')}\n" if (rec.get("source") or {}).get("label") else "")
            + (f"- **Variant on:** `design/variants/{rec['variant']}/`\n" if rec.get("variant") else "")
            + (f"- **Snip:** ![what was marked]({stem}.png) (the page opened fresh; the app's own state may differ)\n"
               if stem and (INBOX / f"{stem}.png").exists() else "") +
            f"- **Where:** `{rec.get('selector') or (rec.get('anchor') or {}).get('selector') or 'an area'}` ({rec.get('kind')})\n"
            + "".join(f"  - inside: `{e.get('selector')}` {clean(e.get('text'), 60)!r}\n" for e in rec.get("elements") or []) +
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
    rec = {k: d.get(k) for k in ("page", "app", "source", "variant", "title", "kind", "selector", "text", "rect", "viewport",
                                 "scroll", "anchor", "elements", "ua")}
    rec["note"] = note
    rec = {k: (clean(v, 600) if isinstance(v, str) and k != "note" else v) for k, v in rec.items()}
    status = "draft" if d.get("draft") else "open"   # the overlay's notes wait as drafts until the owner presses Send
    (INBOX / f"{stem}.md").write_text(render(rec, status, now), encoding="utf-8")
    if d.get("_snip"):      # only where opening the page can't touch real data (the mockup or a demo)
        threading.Thread(target=snip, args=(stem, rec), daemon=True).start()
    log = SCRIPTS / "vault-log.sh"
    if log.exists() and status == "open":
        subprocess.run([str(log), "owner", "note", f"Feedback on {clean(rec.get('app') or rec.get('title'), 40)}: "
                        f"{note.splitlines()[0][:80]}", f"raw/feedback/{stem}"], capture_output=True)
    return stem


SNIP_LOCK = threading.Lock()


def snip(stem, rec):
    """A picture of what the owner marked: the page opened fresh in a headless browser through its review link (same
    look, same screen size), the marked element (or the area's anchor) scrolled into view and measured, then cropped
    with a little margin and saved beside the note. Best effort: the app's own state (a selection, an open dialog)
    isn't reproduced, which is why the note also lists the elements."""
    import glob
    import shutil
    import tempfile
    try:
        ab = sorted(glob.glob(str(HOME / ".hermes/tools/agent-browser-*/bin/agent-browser-linux-*")))
        chrome = sorted(glob.glob(str(HOME / ".hermes/tools/chromium-*/chrome-linux64/chrome")))
        ffmpeg = shutil.which("ffmpeg") or next(iter(sorted(glob.glob(str(HOME / ".hermes/tools/ffmpeg-*/ffmpeg*")))), None)
        u, vp = urlparse(rec.get("page") or ""), rec.get("viewport") or {}
        anchor = rec.get("anchor") or {}
        sel, rel = anchor.get("selector") or rec.get("selector"), anchor.get("rel")
        if not (ab and chrome and ffmpeg and u.port and sel and vp.get("w")):
            return
        keep = [p for p in u.query.split("&") if p and not p.startswith(("__variant=", "__shot=", "__scroll="))]
        keep += [f"__variant={rec.get('variant') or 'off'}", "__shot=1"]
        enc = lambda s: quote(s, safe="/%:=&?~-._!*()@+,;")           # an apostrophe in a #route stops the browser
        url = f"http://127.0.0.1:{u.port}{enc(u.path or '/')}?{'&'.join(keep)}" + (f"#{enc(u.fragment)}" if u.fragment else "")
        env = {**os.environ, "AGENT_BROWSER_EXECUTABLE_PATH": chrome[-1], "AGENT_BROWSER_ARGS": "--no-sandbox"}
        W, H = int(vp["w"]), int(vp["h"])

        def browse(*args):
            r = subprocess.run([ab[-1], "--session", "marksnip", "--json", *args], capture_output=True, text=True, env=env, timeout=60)
            try:
                d = json.loads(r.stdout)
                return d.get("data") or d.get("result") or {}
            except ValueError:
                return {}

        def region():
            b = browse("get", "box", sel)
            if not b.get("width"):
                return None
            if rel:   # an area: the same fractions of its anchor the owner drew
                return (b["x"] + rel["x"] * b["width"], b["y"] + rel["y"] * b["height"], rel["w"] * b["width"], rel["h"] * b["height"])
            return b["x"], b["y"], b["width"], b["height"]

        out = INBOX / f"{stem}.png"
        with SNIP_LOCK, tempfile.TemporaryDirectory() as tmp:
            full = f"{tmp}/full.png"
            try:
                browse("set", "viewport", str(W), str(H))
                browse("open", url)
                browse("wait", "1500")
                browse("scrollintoview", sel)
                g = region()
                if g and (g[1] < 0 or g[1] + g[3] > H):        # a big anchor: bring the marked part itself into view
                    browse("eval", f"window.scrollBy(0, {int(g[1] - max(0, (H - g[3]) / 2))})")
                    browse("wait", "400")
                    g = region()
                if g:
                    browse("screenshot", full)
            finally:
                browse("close")
            if not g or not pathlib.Path(full).exists():
                return
            pad = 16
            x, y = max(0, int(g[0]) - pad), max(0, int(g[1]) - pad)
            w, h = min(int(g[2]) + 2 * pad, W - x), min(int(g[3]) + 2 * pad, H - y)
            if w < 8 or h < 8:
                return
            subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", full, "-vf", f"crop={w}:{h}:{x}:{y}", str(out)],
                           capture_output=True, timeout=60)
        f = INBOX / f"{stem}.md"
        if out.exists() and f.exists():
            t = f.read_text(encoding="utf-8")
            if "- **Snip:**" not in t:
                line = (f"- **Snip:** ![what was marked]({stem}.png) (the page opened fresh; "
                        "the app's own state may differ)\n")
                f.write_text(t.replace("- **Where:**", line + "- **Where:**", 1), encoding="utf-8")
    except Exception as e:                      # a missing picture never loses a note
        print(f"feedback-inbox: snip {stem}: {e}", file=sys.stderr)


def edit(stem, note):
    """Change a draft's text (sent notes are the team's now)."""
    f = INBOX / f"{stem}.md"
    t = f.read_text(encoding="utf-8")
    m = re.search(r"^```json\n(.*?)\n```", t, re.S | re.M)
    if not m or not re.search(r"^status:\s*draft", t, re.M):
        return False
    rec = json.loads(m.group(1))
    rec["note"] = clean(note, MAX).strip()
    f.write_text(render(rec, "draft", datetime.datetime.now(), stem), encoding="utf-8")
    return True


def set_field(f, field, value):
    t = f.read_text(encoding="utf-8")
    if re.search(rf"^{field}:", t, re.M):
        t = re.sub(rf"^{field}:.*$", f"{field}: {value}", t, count=1, flags=re.M)
    else:
        t = t.replace("\n---\n", f"\n{field}: {value}\n---\n", 1)
    f.write_text(t, encoding="utf-8")


def in_scope(n, scope):
    """Which drafts one Send covers. ("design", None): every draft from the design links (the mockup and the demo
    slots), so one review pass across them is one batch. ("app", name): the drafts left on that one app's review link."""
    kind, name = scope
    src = (n.get("source") or {}).get("kind")
    if kind == "design":
        return src in ("mockup", "demo")
    return src not in ("mockup", "demo") and (not name or n.get("app") == name)


def source_label(n):
    src = n.get("source") or {}
    label = src.get("label") or n.get("app") or "the app"
    return label + (f", look `{n['variant']}`" if n.get("variant") else "")


DESIGN_ROUND = "Owner design round"


def send(scope, summary=""):
    """The owner pressed Send: every draft in scope becomes one batch of open notes, listed by where each was left
    (the mockup, demo 1 or 2 and what it shows, or the app). Design batches go straight to the Designer as one card (or
    join the round already waiting for it); the rest wake the Manager to route them."""
    drafts = [n for n in notes("draft") if in_scope(n, scope)]
    if not drafts:
        return None, 0, None
    now = datetime.datetime.now()
    batch = f"{now:%Y-%m-%d-%H%M%S}-batch"
    for n in drafts:
        f = INBOX / f"{n['id']}.md"
        set_field(f, "status", "open")
        set_field(f, "batch", batch)
    groups = {}
    for n in drafts:
        groups.setdefault(source_label(n), []).append(n)
    lines = "".join(f"\n**{label}**\n" + "".join(f"- [[raw/feedback/{n['id']}]]: {clean(n.get('note'), 200).splitlines()[0]}\n"
                                                  for n in ns) for label, ns in groups.items())
    where = ", ".join(groups)
    summary = clean(summary, MAX).strip()
    (INBOX / f"{batch}.md").write_text(
        f"---\ntitle: \"Owner feedback batch: {len(drafts)} notes\"\ntype: research\nstatus: open\nowner: manager\n"
        f"updated: {now:%Y-%m-%d}\nsummary: \"{len(drafts)} notes the owner sent together, from {where[:120]}\"\n"
        f"tags: [feedback, batch]\ncard: none\n---\n# Owner feedback: {len(drafts)} notes, sent together\n\n"
        + ("\n".join("> " + ln for ln in summary.splitlines()) + "\n" if summary else "")
        + lines + "\n_One review pass: card it as one round for the bot that owns it (the Designer for the mockup and the "
        "demos), then set `status: done` and `card:` here and on each note._\n", encoding="utf-8")
    log = SCRIPTS / "vault-log.sh"
    if log.exists():
        subprocess.run([str(log), "owner", "note", f"Sent {len(drafts)} feedback notes ({where[:80]})"
                        + (f": {summary.splitlines()[0][:80]}" if summary else ""), f"raw/feedback/{batch}"], capture_output=True)
    env = {**os.environ, "PATH": f"{HOME}/.local/bin:/usr/bin:/bin"}

    def hermes(*args):
        r = subprocess.run(["hermes", *args], capture_output=True, text=True, env=env, timeout=60)
        return r.stdout

    if scope[0] == "design" and (HOME / ".hermes" / "profiles" / "designer").is_dir():
        card = None
        try:
            # A round that hasn't started yet takes this batch too: one round, not a queue of them.
            waiting = [t for t in json.loads(hermes("kanban", "list", "--json") or "[]")
                       if t.get("assignee") == "designer" and t.get("status") in ("ready", "todo")
                       and str(t.get("title", "")).startswith(DESIGN_ROUND)]
            if waiting:
                card = waiting[0]["id"]
                hermes("kanban", "comment", card, f"More from the owner for this round (sent {now:%H:%M}): "
                       f"`vault/raw/feedback/{batch}.md`, {len(drafts)} notes from {where}. Do them in the same round; "
                       "if one repeats an earlier note, say so and treat them as one.")
            else:
                body = (f"Context: the owner's design feedback, sent together: `vault/raw/feedback/{batch}.md` ({len(drafts)} notes "
                        f"from {where}). Each note says where it was left (the mockup, a demo slot and what it shows), the "
                        "element, the screen size, and often a picture. Review: none (the owner reviews it on the mockup).\n\n"
                        "## Outcome\nEvery note answered where it belongs: mockup notes in the mockup's look; demo notes in that "
                        "demo. A note that repeats an earlier one (sent before, or done already): say so and treat them as one. "
                        "If the round is big (many changes, several screens, or a note that needs research or the Engineer), do "
                        "the first part here and card the rest for yourself, chained, so the owner sees progress early.\n\n"
                        "## Verification\n- A line per note in the handoff: done (what changed), repeat of (which), carded "
                        "(card id), or a question for the owner.\n- `variant-shot.sh` shots of the mockup screens that changed; "
                        "the variants page and any demo answer 200.\n- The batch page and each note: `status: done`, `card:` "
                        "this card's id.\n\n## Constraints\nThe mockup and the demo slots only; never the real app or its "
                        "data.\n\n## Boundaries\nOwns: `vault/design/`. Do not touch: `workspace/`, `vault/product/`, "
                        "`00-status.md`.\n\n## Stop when\nThe round is live on the mockup (and demos) and the handoff has a line "
                        "per note.\n")
                card = json.loads(hermes("kanban", "create", f"{DESIGN_ROUND}: {len(drafts)} notes", "--assignee", "designer",
                                         "--body", body, "--workspace", f"dir:{HOME}", "--max-runtime", "30m",
                                         "--created-by", "owner", "--idempotency-key", batch, "--json")).get("id")
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
            card = None                          # no card: the Manager routes it instead (the batch page is saved either way)
        if card:
            set_field(INBOX / f"{batch}.md", "card", card)
            return batch, len(drafts), "Designer"
    # Otherwise wake the Manager now instead of at the next 2-hourly watch (it runs on the scheduler's next tick).
    try:
        subprocess.Popen(["hermes", "-p", "manager", "cron", "run", "manager-watch"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env)
    except OSError:
        pass                                     # the 2-hourly watch still picks the batch up
    return batch, len(drafts), "Manager"


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


def mockups():
    """{mockup port: name} from mockup.sh's list: copies of an app, safe to click around in."""
    out = {}
    if MOCKUPS.exists():
        for line in MOCKUPS.read_text().splitlines():
            p = line.split("|")
            if len(p) >= 2 and p[1].strip().isdigit() and not line.lstrip().startswith("#"):
                out[int(p[1])] = p[0].strip()
    return out


def variants_page(base=""):
    """base: where "try it live" opens, "" for this link or "//host:port" for the mockup's link."""
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
<h1>Design variants</h1><p class=dim>Each is the app with a different look{' (on the mockup: a copy, so nothing you do touches your real data)' if base else ''}.
Try one, click around, Mark what you think, then Send.</p>{cards or '<p class=dim>No variants yet.</p>'}"""


def badge(variant, mockup, demo=None, looks=True):
    """What the Mark overlay's badge shows (bottom-left): on the mockup, its snapshot and every look as a one-click
    switch; on a demo slot, which demo it is. The overlay draws it in its own layer, so the app can't swallow its
    clicks, and it folds away."""
    names = [v["name"] for v in variant_list() if v["name"] != "current"] if looks and not demo else []
    if not variant and not mockup and not names and not demo:
        return b""
    info = None
    if mockup:
        sf = HOME / "mockup" / mockup / "SNAPSHOT"
        info = sf.read_text(encoding="utf-8").strip() if sf.exists() else "a copy of the app"
    cfg = {"variant": variant, "looks": names, "mockup": info, "demo": demo}
    data = json.dumps(cfg).replace("<", "\\u003c")
    return f"<script>window.__markBadge={data}</script>".encode()


class Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    prefix = ""          # where the inbox endpoints live: "" on the inbox port, "/__mark" inside a review mirror
    app_name = ""

    def log_message(self, *a):
        pass

    def current_variant(self):
        return None

    def is_design(self):
        return False

    def safe_to_open(self):
        return False

    def scope(self):                 # which drafts a Send from here covers (see in_scope)
        return ("app", self.app_name)

    def source(self):                # where a note was left, recorded on it
        return {"kind": "app", "label": self.app_name or "a page (bookmarklet)"}

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
            found = notes(q.get("status", ["open"])[0], q.get("page", [None])[0], q.get("app", [None])[0])
            if q.get("scope") == ["mine"]:        # the drafts a Send from this link would cover
                found = [n for n in found if in_scope(n, self.scope())]
            self._send(200, json.dumps(found))
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
                d["source"] = self.source()
                d.setdefault("variant", self.current_variant())
                d["_snip"] = self.safe_to_open()
                self._send(201, json.dumps({"id": save(d)}))
            except ValueError as e:
                self._send(400, json.dumps({"error": str(e)}))
            return True
        if path == "/notes/send":
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                d = {}
            batch, count, to = send(self.scope(), d.get("summary", ""))
            self._send(200, json.dumps({"batch": batch, "sent": count, "to": to}))
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
            t = f.read_text(encoding="utf-8")
            if not re.search(r"^status:\s*draft", t, re.M):          # a sent note is the team's now
                self._send(409, '{"error":"only drafts can be deleted"}')
                return True
            f.write_text(re.sub(r"^status:\s*\S+", "status: withdrawn", t, count=1, flags=re.M), encoding="utf-8")
            (INBOX / f"{m.group(1)}.png").unlink(missing_ok=True)
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
            # Cookies are shared by every port on the host, so the look picked on the mockup would follow the owner onto
            # the real app's link; there, only an explicit ?__variant= counts while a mockup exists.
            if q is None and not (self.kind() == "app" and mockups()):
                m = re.search(r"(?:^|;\s*)mark_variant=([\w-]+)", self.headers.get("Cookie", ""))
                q = m.group(1) if m else None
            return q if q and q != "off" and (VARIANTS / q).is_dir() else None

        def kind(self):
            if app_port in mockups():
                return "mockup"
            return "demo" if name.lower().startswith("demo") else "app"

        def is_design(self):
            return self.kind() != "app" or bool(self.current_variant())

        def safe_to_open(self):      # the mockup or a demo (static pages): a headless visit can't change real data
            return self.kind() != "app" or "design" in name.lower()

        def scope(self):
            return ("design", None) if self.kind() != "app" else ("app", name)

        def source(self):
            k = self.kind()
            if k == "mockup":
                return {"kind": k, "label": f"the mockup ({mockups()[app_port]})"}
            return {"kind": k, "label": name if k == "demo" else f"{name} (the real app)"}

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
            mockup = mockups().get(app_port)
            if u.path == "/__mark/variants":
                # "Try it live" goes to the mockup when there is one, so trying a look never touches real data.
                mk = next(iter(mockups()), None)
                base = "" if mockup or not mk else f"//{(self.headers.get('Host') or '').split(':')[0]}:{mk + 50}"
                return self._send(200, variants_page(base), "text/html")
            if u.path == "/__mark/mockup/reset" and self.command == "POST" and mockup:
                r = subprocess.run([str(SCRIPTS / "mockup.sh"), "reset", mockup], capture_output=True, text=True)
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
                rest = "&".join(p for p in u.query.split("&") if not p.startswith(("__variant=", "__shot=", "__scroll=")))
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
                # Looks are tried on the mockup; the real app's link offers them only when there is no mockup.
                tag += b"" if shot else badge(v, mockup, name if self.kind() == "demo" else None,
                                              looks=self.kind() != "app" or not mockups())
                sy = parse_qs(u.query).get("__scroll", ["0"])[0]
                if shot and sy.isdigit() and int(sy):          # a snip: put the page at the owner's scroll position
                    tag += (f"<script>(()=>{{let n=0;const t=setInterval(()=>{{scrollTo(0,{int(sy)});if(++n>20)clearInterval(t)}},250)}})()"
                            "</script>").encode()
                page = re.sub(rb"(?i)</body>", lambda m: tag + m.group(0), page, count=1) if re.search(rb"(?i)</body>", page) else page + tag
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
