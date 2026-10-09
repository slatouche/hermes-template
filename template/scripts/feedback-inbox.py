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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

HOME = pathlib.Path.home()
INBOX = HOME / "vault" / "raw" / "feedback"
SCRIPTS = HOME / ".hermes" / "scripts"
OVERLAY = SCRIPTS / "feedback-overlay.js"
MIRRORS = SCRIPTS / "review-mirrors.conf"
VARIANTS = HOME / "vault" / "design" / "variants"
MOCKUP_LOOK = VARIANTS.parent / "mockup-look"     # the one look the mockup shows: the Designer's work in progress
BASE = 0                                          # the project's API port: the inbox listens on BASE + 99
DESIGN_VIEWS = ((51, "Mockup"), (52, "Demo 1"), (53, "Demo 2"))   # the same three design views in every project
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
        for field in ("batch", "answer_to"):        # which thread a note is in, and which round it answers
            m2 = re.search(rf"^{field}:\s*(\S+)", txt, re.M)
            if m2 and m2.group(1) not in ("none", "-"):
                d[field] = m2.group(1)
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


CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(s, n):
    """Text from a page is untrusted: no carriage returns or control characters (a null byte can't go in a command)."""
    return CONTROL.sub("", str(s or "").replace("\r", ""))[:n]


TEST_VALUES = ("1", "true", "yes", "on")


def is_test(d):
    """Did a browser check leave this note or answer, not the owner? The page it was left on carries `?test=1` (the
    overlay records `location.href`), or its json says `"test": true`. A test note is recorded as evidence and can
    never become work: never batched, never shown on a page's round block, never spawns or answers a round."""
    if d.get("test") is True:
        return True
    try:
        u = urlparse(str(d.get("page") or ""))
    except ValueError:
        return False
    queries = [u.query] + ([u.fragment.split("?", 1)[1]] if "?" in u.fragment else [])   # a #route may carry it too
    return any(parse_qs(q).get("test", [""])[0].lower() in TEST_VALUES for q in queries)


def render(rec, status, now, stem=None):
    note = rec["note"]
    summary = note.splitlines()[0][:90].replace('"', "'")
    vp = rec.get("viewport") or {}
    quoted = "\n".join("> " + ln for ln in note.splitlines())
    return (f"---\ntitle: \"Owner note: {summary}\"\ntype: research\nstatus: {status}\nowner: manager\n"
            f"updated: {now:%Y-%m-%d}\nsummary: \"Owner feedback on {clean(rec.get('app') or rec.get('title') or rec.get('page'), 60)}: {summary}\"\n"
            f"tags: [feedback]\ncard: none\n---\n"
            f"# {summary}\n\n{quoted}\n\n"
            + ("- **Test note:** a browser check left this (`?test=1`); it is recorded as evidence and is never "
               "batched, carded or answered.\n" if rec.get("test") else "")
            + f"- **App / page:** {rec.get('app') or '-'} · {rec.get('page')}\n"
            + (f"- **Left on:** {(rec.get('source') or {}).get('label')}\n" if (rec.get("source") or {}).get("label") else "")
            + (f"- **Variant on:** `design/variants/{rec['variant']}/`\n" if rec.get("variant") else "")
            + (f"- **Snip:** ![what was marked]({stem}.png) (the page opened fresh; the app's own state may differ)\n"
               if stem and (INBOX / f"{stem}.png").exists() else "") +
            f"- **Where:** `{rec.get('selector') or (rec.get('anchor') or {}).get('selector') or 'an area'}` ({rec.get('kind')})\n"
            + "".join(f"  - inside: `{e.get('selector')}` {clean(e.get('text'), 60)!r}\n" for e in rec.get("elements") or []) +
            f"- **Element text:** {clean(rec.get('text'), 200)!r}\n"
            + (f"- **Element now:** {'; '.join(f'{k} {v}' for k, v in ((rec.get('ctx') or {}).get('style') or {}).items())[:300]}\n"
               if (rec.get("ctx") or {}).get("style") else "")
            + f"- **Screen:** {vp.get('w')}x{vp.get('h')}\n\n"
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
                                 "scroll", "anchor", "elements", "ua", "ctx")}
    if not isinstance(rec.get("ctx"), dict) or len(json.dumps(rec["ctx"])) > 4000:   # the element as it is now, capped
        rec["ctx"] = None
    else:                                                       # pages can hold control characters (data attributes)
        rec["ctx"] = json.loads(re.sub(r"\\u00(?:0[0-8bcef]|1[0-9a-f]|7f)", "", json.dumps(rec["ctx"])))
    rec["note"] = note
    test = is_test(d)                          # a browser check's note (`?test=1`, or json `test: true`)
    if test:
        rec["test"] = True
    rec = {k: (clean(v, 600) if isinstance(v, str) and k != "note" else v) for k, v in rec.items()}
    status = "draft" if d.get("draft") else "open"   # the overlay's notes wait as drafts until the owner presses Send
    if test:
        status = "withdrawn"                   # recorded, never work: it can't be batched, carded or answered
    (INBOX / f"{stem}.md").write_text(render(rec, status, now), encoding="utf-8")
    if d.get("_snip"):      # only where opening the page can't touch real data (the mockup or a demo)
        SNIPPING.add(stem)
        threading.Thread(target=snip, args=(stem, rec), daemon=True).start()
    log = SCRIPTS / "vault-log.sh"
    if log.exists() and status == "open":
        subprocess.run([str(log), "owner", "note", f"Feedback on {clean(rec.get('app') or rec.get('title'), 40)}: "
                        f"{note.splitlines()[0][:80]}", f"raw/feedback/{stem}"], capture_output=True)
    return stem


SNIP_LOCK = threading.Lock()
SNIPPING = set()          # notes whose picture is still being taken (Send waits a moment for an area's)


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
        keep = [p for p in u.query.split("&") if p and not p.startswith(
            ("__variant=", "__shot=", "__scroll=", "__nooverlay="))]
        keep += [f"__variant={rec.get('variant') or 'off'}", "__shot=1", "__nooverlay=1"]
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
    finally:
        SNIPPING.discard(stem)


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


def browser_tools():
    """The bots' own headless browser (agent-browser), run from this service where it doesn't crash. Returns
    browse(session, *args) -> the command's data, or None when the tools aren't installed yet."""
    import glob
    ab = sorted(glob.glob(str(HOME / ".hermes/tools/agent-browser-*/bin/agent-browser-linux-*")))
    chrome = sorted(glob.glob(str(HOME / ".hermes/tools/chromium-*/chrome-linux64/chrome")))
    if not (ab and chrome):
        return None
    env = {**os.environ, "AGENT_BROWSER_EXECUTABLE_PATH": chrome[-1], "AGENT_BROWSER_ARGS": "--no-sandbox"}

    def browse(session, *args, timeout=90):
        r = subprocess.run([ab[-1], "--session", session, "--json", *args], capture_output=True, text=True, env=env,
                           timeout=timeout)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            return None
        return d.get("data") if d.get("data") is not None else d.get("result")
    return browse


CHECK_LOCK = threading.Lock()


def demo_folder(slot):
    """The folder a demo slot serves, read off its systemd unit (demo.sh writes it), so a round card can name the one
    command for the page a note was left on without anyone repeating which folder it is."""
    try:
        unit = HOME / ".config" / "systemd" / "user" / f"design-demo-{slot}.service"
        m = re.search(r"--directory\s+(\S+)", unit.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return m.group(1) if m else None


DEEP_HELPERS = (
    "(()=>{"
    "window.__markQ=(s,root)=>{root=root||document;let f;try{f=root.querySelector(s)}catch(e){return null}"
    "if(f)return f;for(const el of root.querySelectorAll('*')){if(el.shadowRoot){"
    "const g=window.__markQ(s,el.shadowRoot);if(g)return g}}return null};"
    "window.__markCount=(s)=>{let n=0;const walk=r=>{try{n+=r.querySelectorAll(s).length}catch(e){}"
    "for(const el of r.querySelectorAll('*')){if(el.shadowRoot)walk(el.shadowRoot)}};walk(document);return n};"
    "return 'mark deep-query helpers ready'})()"
)

# A drag, driven with a real pointer (agent-browser's mouse = CDP Input.dispatchMouseEvent, so the page sees trusted
# pointerdown/move/up with buttons=1 held). The pointer goes down inside the element on a point that is not a button
# or an input — the overlay's own draggable() ignores those — moves to the target and lifts. '<selector> -> <x>,<y>'
# leaves the element's top-left corner at x,y: the element follows the pointer, so the pointer must end dx,dy past
# the target, dx,dy being where inside the element it was grabbed.
DRAG_MOVES = 4                     # pointer moves inside a drag: a real move, not a jump
DRAG_FIND = (
    "(()=>{const sel=window.__dragSel;const el=window.__markQ(sel);"
    "if(!el)return JSON.stringify({found:false});"
    "el.scrollIntoView({block:'center',inline:'center'});"
    "const r=el.getBoundingClientRect();"
    "const hit=(x,y)=>{let a=document.elementFromPoint(x,y);"
    "while(a&&a.shadowRoot){const n=a.shadowRoot.elementFromPoint(x,y);if(!n||n===a)break;a=n}return a};"
    "const small=el.classList.contains('small');"
    "const off=[[5,r.height/2],[r.width-5,r.height/2],[r.width/2,5],[r.width/2,r.height-5],[5,5],"
    "[r.width-5,5],[5,r.height-5],[r.width-5,r.height-5],[r.width/2,r.height/2]];"
    "let g=null;"
    "for(const o of off){const x=r.left+o[0],y=r.top+o[1];"
    "if(x<0||y<0||x>innerWidth||y>innerHeight)continue;"
    "const a=hit(x,y);if(!a||!(a===el||el.contains(a)))continue;"
    "if(!small&&a.closest('button,input,textarea'))continue;"
    "g=[x,y];break}"
    "const out={found:true,grabbable:!!g,left:r.left,top:r.top,w:r.width,h:r.height};"
    "if(g){out.px=g[0];out.py=g[1];out.dx=g[0]-r.left;out.dy=g[1]-r.top}"
    "return JSON.stringify(out)})()"
)
DRAG_ARM = (
    "(()=>{window.__dragEv={down:null,moves:0,up:null};"
    "if(!window.__dragArmed){window.__dragArmed=1;"
    "const rec=(t)=>(e)=>{const p={trusted:e.isTrusted,buttons:e.buttons,x:Math.round(e.clientX),y:Math.round(e.clientY)};"
    "if(t==='pointerdown')window.__dragEv.down=p;"
    "else if(t==='pointermove'&&window.__dragEv.down)window.__dragEv.moves++;"
    "else if(t==='pointerup')window.__dragEv.up=p};"
    "['pointerdown','pointermove','pointerup'].forEach(t=>addEventListener(t,rec(t),true))}"
    "return 'drag armed'})()"
)
DRAG_AFTER = (
    "(()=>{const el=window.__markQ(window.__dragSel);const r=el?el.getBoundingClientRect():null;"
    "return JSON.stringify({ev:window.__dragEv,box:r?[r.left,r.top,r.width,r.height]:null})})()"
)


def look_check(url, width, height, exprs, shot=None, steps=None):
    """One step for the Designer instead of five: open a page (a look on the mockup, or a demo) at a size, wait for
    it, do each step in order — read a JavaScript expression, or drive a real pointer drag — and take a screenshot.
    Returns {"results": [...], "shot": path}."""
    browse = browser_tools()
    if not browse:
        return {"error": "the browser tools aren't installed yet (they arrive with the bots' first browser use)"}
    todo = [s for s in steps if isinstance(s, dict)] if steps else [{"js": e} for e in exprs]
    results = []
    with CHECK_LOCK:
        try:
            browse("lookcheck", "set", "viewport", str(width), str(height))
            browse("lookcheck", "open", url)
            browse("lookcheck", "wait", "1500")
            if todo:                    # the overlay is in a shadow root: give the check a deep query first
                browse("lookcheck", "eval", DEEP_HELPERS)
            try:
                for step in todo:
                    if "drag" in step:
                        results.append(drag_step(browse, str(step["drag"])))
                    else:
                        e = str(step.get("js", ""))
                        v = browse("lookcheck", "eval", e, timeout=20)
                        results.append({"js": e, "value": v.get("result", v) if isinstance(v, dict) else v})
                if shot:
                    browse("lookcheck", "screenshot", shot, timeout=20)
            except subprocess.TimeoutExpired:
                return {"error": "the page didn't answer within 20 s: it's hung, usually a look script that keeps "
                                 "re-running on its own changes. Fix the script first.", "results": results}
        finally:
            try:
                browse("lookcheck", "close", timeout=20)
            except subprocess.TimeoutExpired:
                pass
    return {"results": results, "shot": shot if shot and pathlib.Path(shot).exists() else None}


def mark_eval(browse, expr):
    """Run an expression in the check's page and read the value back (a JSON string comes back as the object)."""
    v = browse("lookcheck", "eval", expr, timeout=20)
    v = v.get("result", v) if isinstance(v, dict) else v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def coord(v):
    """A pointer coordinate as agent-browser takes it: whole pixels, like a real mouse (it refuses fractions)."""
    return "%d" % int(round(v))


def drag_step(browse, spec):
    """Drive one real pointer drag: '<selector> -> <x>,<y>' leaves the element's top-left at x,y. The pointer goes
    down inside the element on a point that is not a button or an input (the overlay's draggable() ignores those),
    moves to the target and lifts, so the page sees a genuine trusted press-move-release."""
    m = re.match(r"^\s*(.+?)\s*(?:->|to)\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*$", spec)
    if not m:
        return {"drag": spec, "error": "write a drag as '<selector> -> <x>,<y>'"}
    sel, x, y = m.group(1), float(m.group(2)), float(m.group(3))
    mark_eval(browse, "window.__dragSel=" + json.dumps(sel))
    info = mark_eval(browse, DRAG_FIND)
    if not isinstance(info, dict) or not info.get("found"):
        return {"drag": spec, "error": "%s is not on the page" % sel}
    if not info.get("grabbable"):
        return {"drag": spec, "error": "%s has no draggable point inside it (every point sits on a button or an "
                                      "input): open its panel first, or grab it by a padding strip" % sel}
    px, py, dx, dy = round(info["px"]), round(info["py"]), info["dx"], info["dy"]
    tx, ty = round(x + dx), round(y + dy)   # end the pointer dx,dy past the target: the element's top-left lands there
    mark_eval(browse, DRAG_ARM)
    browse("lookcheck", "mouse", "move", coord(px), coord(py), timeout=20)
    browse("lookcheck", "mouse", "down", timeout=20)
    for i in range(1, DRAG_MOVES + 1):
        browse("lookcheck", "mouse", "move", coord(px + (tx - px) * i / DRAG_MOVES),
               coord(py + (ty - py) * i / DRAG_MOVES), timeout=20)
    browse("lookcheck", "mouse", "up", timeout=20)
    got = mark_eval(browse, DRAG_AFTER)
    got = got if isinstance(got, dict) else {}
    box = got.get("box")
    ev = got.get("ev") or {}
    down, up = ev.get("down") or {}, ev.get("up") or {}
    rnd = lambda b: [round(v, 2) for v in b] if b else None
    travel = (abs(up.get("x", 0) - down.get("x", 0)) + abs(up.get("y", 0) - down.get("y", 0))) if down and up else None
    shift = max(abs(box[0] - info["left"]), abs(box[1] - info["top"])) if box else None
    return {"drag": spec, "pointer": got.get("ev"), "before": rnd([info["left"], info["top"], info["w"], info["h"]]),
            "target": [x, y], "after": rnd(box),
            # the pointer moves in whole pixels, so a box whose own layout sits on a fraction of a pixel lands that
            # fraction off: the miss is reported, never hidden (the page's clamp can also pull a drop back on screen)
            "miss": rnd([box[0] - x, box[1] - y]) if box else None,
            "travel": travel,           # how far the pointer went: 0 is a plain click, which must move nothing
            "moved": shift is not None and shift >= 0.5}


def round_text(batch, drafts, where, card, summary="", quick=None, card_id=None):
    """Everything a round needs, in the message itself: each note (words, place, element, size, picture), the look's
    map, and the one command for the page the notes were left on - carrying the card's own id, because the worker's
    HERMES_KANBAN_TASK can be empty and then the command can neither narrate itself nor close the card."""
    looks = sorted({n["variant"] for n in drafts if n.get("variant")})
    out = [f"Owner design round, card `{card}` (batch `vault/raw/feedback/{batch}.md`), {len(drafts)} notes from {where}."]
    if summary:
        out.append(f"Their overall comment: {summary}")
    for i, n in enumerate(drafts, 1):
        anchor = (n.get("anchor") or {}).get("selector")
        inside = ", ".join(f"`{e.get('selector')}` {e.get('text')!r}" for e in (n.get("elements") or [])[:6])
        pic = INBOX / f"{n['id']}.png"
        vp = n.get("viewport") or {}
        ctx = n.get("ctx") or {}
        now_ = "; ".join(f"{k} {v}" for k, v in (ctx.get("style") or {}).items())
        out.append(f"{i}. \"{clean(n.get('note'), 1500)}\"\n   on {n.get('page')} ({source_label(n)}), screen {vp.get('w')}x{vp.get('h')}\n"
                   f"   element `{n.get('selector') or anchor or 'an area'}`" + (f"; inside: {inside}" if inside else "")
                   + (f"\n   now: {now_[:400]}" if now_ else "")
                   + (f"\n   html: {clean(ctx.get('html'), 600)}" if ctx.get("html") else "")
                   + (f"\n   snip (only to find a drawn area, or to check a change): `{pic}`" if pic.exists() else ""))
    if quick:
        done = "".join(f"\n- note {a['n']}: {a['did']}" for a in quick["applied"]) or " none"
        todo = "".join(f"\n- note {o['n']}: {o['why']}" for o in quick["open"]) or " none"
        out.append(f"Already live (the quick lane put CSS in `design/variants/{quick['look']}/style.css` in {quick['secs']} s, "
                   f"each block headed `quick fix`):{done}\nYours:{todo}")
    for look in looks:
        m = VARIANTS / look / "map.md"
        if m.exists():
            out.append(f"The map of look `{look}` (`{m}`):\n" + m.read_text(encoding="utf-8", errors="replace")[:8000])
        css = VARIANTS / look / "style.css"
        if css.exists():
            out.append(f"The look's CSS now (`{css}`, quick fixes included):\n```css\n"
                       + css.read_text(encoding="utf-8", errors="replace")[-10000:] + "\n```")
    first = urlparse(drafts[0].get("page") or "") if drafts else None
    vp0 = (drafts[0].get("viewport") or {}) if drafts else {}
    target = None                                          # the one command for the page these notes were left on
    if looks:
        target = f"look-apply.py {looks[0]}"
    elif drafts and (drafts[0].get("source") or {}).get("kind") == "demo":
        label = ((drafts[0].get("source") or {}).get("label") or drafts[0].get("app") or "")
        m = re.search(r"demo\s*(\d)", label, re.I)
        folder = demo_folder(m.group(1)) if m else None
        if folder:
            target = f"look-apply.py --dir {folder} --demo {m.group(1)}"
    if first and target:
        where_ = quote(first.path or "/", safe="/") + ("#" + quote(first.fragment, safe="/%=&?") if first.fragment else "")
        if card_id:
            target += f" --card {card_id}"
            # the board travels with the card: a delegate_task child, or any worker without the board in its
            # environment, still closes the right card
            target += f" --board {os.environ.get('HERMES_KANBAN_BOARD') or 'default'}"
        out.append(
            "Do the round with one command: it adds each edit, saves it, checks the page at the owner's size and closes "
            "this card when every check passes. Write the round as its edits, in order \u2014 the page updates as each one "
            "lands, and the chip names it:\n```\n"
            f"~/.hermes/scripts/{target} --page '{where_}' --size {vp0.get('w', 1440)}x{vp0.get('h', 900)} "
            "--label '<the round in a few words>' \\\n"
            "  --edit '<what edit 1 does>' --css '<its rules>' \\\n"
            "  --edit '<what edit 2 does>' --css '<its rules>' \\\n"
            "  --edit '<a note that needs markup>' \\\n"
            "     --html-in '<the page's own text, exactly as index.html has it>' --html-out '<what replaces it>' \\\n"
            "  --check '<js, truthy when note 1 landed>' --check '<note 2>' \\\n"
            "  --done 'note 1: <what changed>' --done 'note 2: <what changed>'\n```\n"
            "A check that fails leaves the card open: fix and run it again. Get anything the round needs first (an image "
            "into the look's folder, a look at the data) in the same command or one step before. Never hand-edit a "
            "page: a look change and a markup change are both edits of the round. A markup edit must match the page's "
            "own text exactly once (copy it from index.html) and leaves a .bak-<time> beside the file.")
    elif drafts:
        out.append(
            "This card carries no round command for the page its notes were left on: that is a card defect. Say so in "
            "your handoff in one line and stop \u2014 never hand-edit a page to work around a missing command.")
    out.append(
        "First classify each note: if it can be done without the owner's answer, do it. Put the crudest *visible* "
        "version of the change live inside the first minute (a colour or token flip is enough), then finish it and "
        "say in one line what you decided \u2014 most rounds decide everything and ask nothing. **Never ask the owner what "
        "to do next**: a question like `what should I change next?` is not a question, it hands the deciding back to "
        "them, and it is banned. The owner asks for a change in exactly two ways \u2014 a note in the toolbar's box on this "
        "page, or the marking tool on something pointed \u2014 so a round that wants more work waits for one of those "
        "instead of asking for it. **At most one question per round**, and only where the work cannot go further "
        "without their answer: a fork inside the change you are already making (two options, both visible and genuinely "
        "plausible), or something they raised that you cannot read either way. Write it on its own line in your "
        "handoff, starting `Question for the owner:` \u2014 the page shows it beside the Mark toolbar, they answer it "
        "there, and the answer comes back to this session; `look-check.sh` runs on the version that stays. A "
        f"question the owner never sees is a defect. The card is `{card}`; the notes close themselves.")
    out.append(
        "The round's edits are its numbered list: edit 1, saved, then edit 2, then 3 \u2014 the one command saves each in "
        "turn, so the owner watches them land and the chip names each. Never hand-patch a page, and never hold the edits "
        "back into one save at the end: one command is the whole round.")
    return "\n\n".join(out)


def round_tail():
    """The fixed tail of every round card body: a Send round and an answer round are the same card with the same rules."""
    return ("\n\n## Outcome\nEvery note answered in the mockup's look, or in the demo it was left on.\n\n"
            "## Verification\n- A line per note in the handoff: done (what changed), repeat of (which), carded "
            "(card id), or a question for the owner (at most one for the whole round).\n- `look-check.sh` evidence for each screen that changed; "
            "`map.md` updated.\n\n## Constraints\nThe mockup and the demo slots only; never the real app or its "
            "data. Never start a build: new app behaviour is designed, prototyped if needed, and waits for the "
            "owner's \"build it\" as an `Owner: build it?` card (blocked, needs_input).\n\n## Boundaries\nOwns: "
            "`vault/design/`. Do not touch: `workspace/`, `vault/product/`, `00-status.md`.\n\n## Stop when\nThe "
            "round is live and the handoff has a line per note.\n")


LOGS = HOME / ".hermes" / "kanban" / "logs"   # the workers' own progress logs (board-now.py reads the same path)
BOX = "\u250c\u2502\u2514\u250a\u2500"
STEP_CHARS = 60            # a step is a glance, not a paragraph
STEP_DONE_RE = re.compile(r"\d+\.\d+s\b")   # a finished tool row carries its duration; a `preparing X…` row does not
ROUND_TTL = 5.0            # how often a page's live round is re-read off the board
ROUND_TTL_DONE = 60.0      # a finished round doesn't change: read it again only rarely
ROUND_CACHE = {}           # scope -> (card, read_at, block): what this page was last told
CARD_CACHE = {}            # card -> the last board read of it
QUESTION_RE = re.compile(r"^\s*(?:[-*>]\s*)*(?:\*\*)?question(?: for the owner)?(?:\*\*)?\s*:\s*(.+)$", re.I)


def hermes(*args):
    """The kanban CLI, as this service runs it (the same call send() makes to create a round card)."""
    args = [CONTROL.sub("", a) for a in args]
    r = subprocess.run(["hermes", *args], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{HOME}/.local/bin:/usr/bin:/bin"}, timeout=60)
    if r.returncode:
        print(f"feedback-inbox: hermes {' '.join(args[:3])} failed: {r.stderr.strip()[-300:]}", file=sys.stderr)
    return r.stdout


def round_step(card):
    """The worker's last *finished* progress row and how long its log has been quiet: the last `\u250a` line of
    ~/.hermes/kanban/logs/<card>.log that carries its duration \u2014 board-now.py's read, with the transient
    `preparing <tool>\u2026` rows skipped, so the chip names the work rather than the tool. (None, None) with no log."""
    f = LOGS / f"{card}.log"
    if not f.exists():
        return None, None
    idle = max(0, int(time.time() - f.stat().st_mtime))
    try:
        txt = f.read_bytes()[-6000:].decode("utf-8", "replace")
    except OSError:
        return None, idle
    steps = [l.strip() for l in txt.splitlines() if l.strip().startswith("\u250a")]
    done = [l for l in steps if STEP_DONE_RE.search(l)]
    if done:
        step = done[-1].strip("\u250a ").strip()
    elif steps:
        step = steps[-1].strip("\u250a ").strip()
    else:
        step = ""
        for l in reversed(txt.splitlines()):
            l = l.strip().strip(BOX).strip()
            if l:
                step = l
                break
    return (step[:STEP_CHARS] or None), idle


def round_question(*texts):
    """The question a round left for the owner: its `Question for the owner:` line, the last one written."""
    out = None
    for t in texts:
        for ln in (t or "").splitlines():
            m = QUESTION_RE.match(ln.strip())
            if m and m.group(1).strip():
                out = clean(m.group(1).strip(), 400)
    return out


def _owner_name():
    """The owner's name as the board records it (hire-defaults.conf OWNER_NAME, written by the installer)."""
    try:
        m = re.search(r'^OWNER_NAME="?([^"\n]*)', (HOME / ".hermes/scripts/hire-defaults.conf").read_text(), re.M)
        return m.group(1).strip().lower() if m else ""
    except OSError:
        return ""


OWNER_AUTHORS = tuple(a for a in ("owner", _owner_name()) if a)   # the human, when they answer on the board itself
OWNER_ANSWER_RE = re.compile(r"^\s*(?:the )?owner(?:'s)? answer\b", re.I)


def round_answered(card, info=None):
    """Has this round's question been answered? An answer is a page under raw/feedback carrying `answer_to: <card>`
    — the page's own answers write it (`answer()`), and so does the Manager when the owner answers in chat instead —
    or a comment on the round card from the owner. However it was answered, a spent question must not sit on the
    page and nag."""
    if any(n.get("answer_to") == card and not is_test(n) for n in notes(None)):
        return True
    info = info if info is not None else board_card(card)
    for c in reversed(info.get("comments") or []):
        body = (c.get("body") or "").strip()
        if body and ((c.get("author") or "").lower() in OWNER_AUTHORS or OWNER_ANSWER_RE.match(body)):
            return True
    return False


def board_card(card, refresh=False):
    """One board read of a round card: its status, its handoff (where the question is written) and its block reason."""
    if not refresh and card in CARD_CACHE:
        return CARD_CACHE[card]
    info = {"status": "", "body": "", "result": "", "summary": "", "reason": "", "comments": [],
            "started": None, "done": None}
    env = {**os.environ, "PATH": f"{HOME}/.local/bin:/usr/bin:/bin"}
    try:
        r = subprocess.run(["hermes", "kanban", "show", card, "--json"], capture_output=True, text=True, env=env,
                           timeout=60)
        d = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"feedback-inbox: no board read for {card}: {e}", file=sys.stderr)
        d = None
    if d is not None:
        t = d.get("task") or {}
        blocked = [e for e in (d.get("events") or []) if e.get("kind") == "blocked"]
        info = {"status": t.get("status") or "", "body": t.get("body") or "", "result": t.get("result") or "",
                "summary": d.get("latest_summary") or "",
                "reason": ((blocked[-1].get("payload") or {}).get("reason") or "") if blocked else "",
                "comments": d.get("comments") or [],
                "started": t.get("started_at"), "done": t.get("completed_at")}
        CARD_CACHE[card] = info
    return CARD_CACHE.get(card, info)


def round_card_for(scope):
    """The round this link is on: the newest batch of notes left on it, and the card that batch went to. Only a
    mockup or a demo has rounds (send() cards those); anywhere else there is nothing to show or answer. A batch
    whose notes have all been withdrawn asked for nothing (a test round, or one the owner took back): it is
    skipped, so the link falls back to the next real batch it has, or to no round at all. A batch with even one
    live note is real — one withdrawn note inside it must not hide the round."""
    if scope[0] not in ("mockup", "demo"):
        return None, None
    mine = [n for n in notes(None) if n.get("batch") and in_scope(n, scope)]
    for batch in sorted({n["batch"] for n in mine}, reverse=True):
        if all(n.get("status") == "withdrawn" for n in mine if n["batch"] == batch):
            continue                                   # every note in it withdrawn: nothing was asked for
        f = INBOX / f"{batch}.md"
        if not f.exists():
            return batch, None
        m = re.search(r"^card:\s*(\S+)", f.read_text(encoding="utf-8", errors="replace"), re.M)
        card = m.group(1) if m else ""
        return batch, (card if re.fullmatch(r"t_[0-9a-f]{4,}", card or "") else None)
    return None, None


def round_block(scope):
    """What the page shows about its round: {card, state, question, secs, step, idle}, off the board and the
    worker's own log. None when this link has never had a Send. The board is read at most once every ~5 s while the round is live (once a minute once
    it is done) and not at all when there is no round; the answer itself comes back through /notes/answer."""
    now = time.monotonic()
    batch, card = round_card_for(scope)
    hit = ROUND_CACHE.get(scope)
    if hit and hit[0] == card:
        if now - hit[1] < (ROUND_TTL_DONE if (hit[2] or {}).get("state") == "done" else ROUND_TTL):
            return hit[2]
    if not card:
        ROUND_CACHE.pop(scope, None)
        return None
    info = board_card(card, refresh=True)
    state = {"ready": "working", "todo": "working", "running": "working", "blocked": "needs_you",
             "done": "done"}.get(info["status"], "working")
    # the block reason is the question only while the round is actually blocked on the owner — a card that was
    # blocked once must not resurface that old text as a question once it is done
    question = round_question(info["summary"], info["result"]) \
        or (clean(info["reason"], 400) if state == "needs_you" else None) or None
    if question and round_answered(card, info):
        question = None                       # answered, wherever it was answered: the page stops asking
    secs = max(0, int(info["done"] or time.time()) - int(info["started"])) if info["started"] else None
    step, idle = round_step(card)             # what the worker is on right now, and how long since the log moved
    block = {"card": card, "state": state, "question": question, "secs": secs, "step": step, "idle": idle}
    ROUND_CACHE[scope] = (card, now, block)
    return block


def round_topic(body, scope):
    """The Designer session a round runs on: the `Session: design:<topic>` line of the card being answered."""
    m = re.search(r"^Session:\s*(\S+)", body or "", re.M)
    return m.group(1) if m else "design:" + (re.sub(r"[^a-z0-9._-]+", "-", (scope[2] or "mockup").lower()).strip("-")[:60]
                                             or "mockup")


def answer(scope, card, text, page=None):
    """The owner answered a round on the page: the answer becomes its own page under raw/feedback, and one new round
    card goes to the Designer on the same session topic, carrying the answer and the note it belongs to. Returns
    {"answer": <page>, "card": <new card>, "batch": <batch>, "session": <topic>}. A browser check's answer (`?test=1`)
    is recorded the same way but spawns nothing and answers nothing: card is None and the live question stays live."""
    text = clean(text, MAX).strip()
    if not text:
        raise ValueError("empty answer")
    test = is_test({"page": page})             # a browser check answering: recorded, never a real answer
    batch, current = round_card_for(scope)
    card = str(card or "")
    if not re.fullmatch(r"t_[0-9a-f]{4,}", card):
        card = current
    if not card:
        raise ValueError("no round on this link to answer")
    info = board_card(card, refresh=True)
    question = round_question(info["summary"], info["result"]) or clean(info["reason"], 400)
    drafts = [n for n in notes(None) if batch and n.get("batch") == batch]
    now = datetime.datetime.now()
    stem = f"{now:%Y-%m-%d-%H%M%S}-answer-{card}"
    where = ", ".join(sorted({source_label(n) for n in drafts})) or clean(page, 120) or "the page"
    topic = round_topic(info["body"], scope)
    first = drafts[0] if drafts else {}
    rec = {"note": text, "kind": "answer", "page": page or first.get("page"), "app": first.get("app"),
           "source": first.get("source"), "variant": first.get("variant"), "viewport": first.get("viewport")}
    if test:
        rec["test"] = True
    (INBOX / f"{stem}.md").write_text(
        f"---\ntitle: \"{'Test answer' if test else 'Owner answer'} to round {card}\"\ntype: research\n"
        f"status: {'withdrawn' if test else 'answer'}\nowner: manager\n"
        f"updated: {now:%Y-%m-%d}\nsummary: \"{'A browser check answered' if test else 'The owner answered'} round "
        f"{card} on {clean(where, 60)}: {text.splitlines()[0][:70]}\"\ntags: [feedback, answer]\ncard: none\n"
        f"batch: {'none' if test else (batch or 'none')}\n"
        f"answer_to: {card}\n---\n# Answer to round `{card}`\n\n"
        + "\n".join("> " + ln for ln in text.splitlines()) + "\n\n"
        + ("- **Test answer:** a browser check typed this (`?test=1`); it is recorded as evidence and does not "
           "answer the round or spawn a new one.\n" if test else "")
        + f"- **Answered on:** {clean(page or where, 200)}\n- **The round:** `{card}` ({info['status'] or '?'})\n"
        f"- **Its question:** {question or '-'}\n- **The notes it answers:**\n"
        + "".join(f"  - [[raw/feedback/{n['id']}]]: {clean(n.get('note'), 200).splitlines()[0]}\n" for n in drafts)
        + f"- **The batch:** [[raw/feedback/{batch}]]\n\n"
        "_An answer, not a new note: it goes back to the round that asked, and the round card it creates resumes the "
        "same Designer session._\n\n"
        f"```json\n{json.dumps(rec, ensure_ascii=False)}\n```\n", encoding="utf-8")
    if test:                                    # recorded and left: no round is spawned, the live question stays live
        ROUND_CACHE.pop(scope, None)
        return {"answer": stem, "card": None, "batch": None, "session": topic, "test": True}
    body = (f"Context: the owner answered round `{card}` on the page they were looking at (answer page "
            f"`vault/raw/feedback/{stem}.md`, batch `vault/raw/feedback/{batch}.md`). Review: none (the owner reviews "
            f"it on the page).\nSession: {topic}\n\n"
            "**The owner's answer** (to the question below):\n"
            + "\n".join("> " + ln for ln in text.splitlines()) + "\n\n"
            f"**The round they are answering** (`{card}`, {info['status'] or '?'}) asked: {question or '(no question recorded)'}"
            f"\n\n**What they are looking at now:** {where}\n\n"
            + round_text(batch, drafts, where, "this card", "", None) + round_tail())
    bf = INBOX / f".{stem}.card.md"                 # a file, not an argument: no size or character limits
    bf.write_text(clean(body, 200_000), encoding="utf-8")
    new_card = None
    try:
        new_card = json.loads(hermes("kanban", "create", f"{DESIGN_ROUND}: answer to {card}", "--assignee", "designer",
                                     "--body-file", str(bf), "--workspace", f"dir:{HOME}", "--max-runtime", "10m",
                                     "--created-by", "owner", "--idempotency-key", stem, "--json")).get("id")
    finally:
        bf.unlink(missing_ok=True)
    f = INBOX / f"{batch}.md" if batch else None
    if f is not None and f.exists():
        if new_card:                                # the thread's round is the new card from now on
            set_field(f, "card", new_card)
        set_field(f, "status", "open")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"\n_Answered {now:%H:%M} on the page: [[raw/feedback/{stem}]] \u2192 round `{new_card or '-'}`._\n")
    ROUND_CACHE.pop(scope, None)                    # the page flips to working on its next 2 s poll
    log = SCRIPTS / "vault-log.sh"
    if log.exists():
        subprocess.run([str(log), "owner", "note", f"Answered round {card} on {where[:80]}: "
                        f"{text.splitlines()[0][:80]}", f"raw/feedback/{stem}"], capture_output=True)
    return {"answer": stem, "card": new_card, "batch": batch, "session": topic}


def in_scope(n, scope):
    """Which drafts one Send covers: only those left on the link it's pressed on (the mockup, demo 1, demo 2 or an
    app), matched by the link's port so a demo slot that gets a new label keeps its drafts. scope = (kind, port, name);
    the bookmarklet (no review link) matches by app name instead."""
    kind, port, name = scope
    if port:
        try:
            return urlparse(n.get("page") or "").port == port
        except ValueError:
            return False
    return not name or n.get("app") == name


def source_label(n):
    src = n.get("source") or {}
    label = src.get("label") or n.get("app") or "the app"
    return label + (f", look `{n['variant']}`" if n.get("variant") else "")


QUICK_LOOK = "quick"          # the look quick fixes go into when the owner had no look on


def model_config():
    """The project's model, endpoint and key (as Hermes runs it for the Designer), or None. The key never leaves this
    process except in the request to the provider."""
    h = HOME / ".hermes"
    cfg_file = next((p for p in (h / "profiles" / "designer" / "config.yaml", h / "config.yaml") if p.exists()), None)
    if not cfg_file:
        return None
    text = cfg_file.read_text(encoding="utf-8", errors="replace")
    try:
        import yaml                                            # /usr/bin/python3 has it
        m = {k: str(v) for k, v in ((yaml.safe_load(text) or {}).get("model") or {}).items() if v is not None}
    except Exception:                                          # no PyYAML: the block up to the next top-level key
        block = re.search(r"^model:[ \t]*\n((?:[ \t#].*\n|[ \t]*\n)+)", text, re.M)
        m = dict(re.findall(r"^[ \t]+(provider|default|base_url|api_mode):[ \t]*['\"]?([^'\"\n#]+?)['\"]?[ \t]*(?:#.*)?$",
                            block.group(1), re.M)) if block else {}
    if not (m.get("default") and m.get("base_url")) or m.get("api_mode", "chat_completions") != "chat_completions":
        return None
    var = re.sub(r"[^A-Z0-9]", "_", (m.get("provider") or "").upper()) + "_API_KEY"
    key = None
    for env_file in (h / "profiles" / "designer" / ".env", h / ".env"):
        if env_file.exists():
            for ln in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.startswith(var + "="):
                    key = ln.split("=", 1)[1].strip().strip('"')
        if key:
            break
    return {"model": m["default"], "url": m["base_url"].rstrip("/") + "/chat/completions", "key": key,
            "opencode": "opencode.ai" in m["base_url"]} if key else None


QUICK_SYSTEM = """You are the Designer's fast hands. The owner marked parts of a live web app and left short notes; you
turn each concrete note into CSS that is applied to the page at once (they watch it change). Rules:
- CSS only. Target the element you are given (its selector), or a close, stable ancestor/descendant from its HTML.
  Keep selectors specific enough to touch only what the note is about.
- Be decisive and visible: "too small, make it huge" means clearly huge; "more prominent" means clearly bigger or bolder.
  Use the design tokens (CSS variables) when they fit. Keep it working: no overflow off screen, no hidden controls.
- A note that needs new content, data, behaviour or real thought (e.g. "use this space for something", "redesign this",
  a question) is OPEN: don't guess, say in one line what the Designer should decide or ask.
- Reply with JSON only: {"fixes":[{"n":1,"css":"...","did":"one short line for the owner"}],
  "open":[{"n":2,"why":"one line"}]}"""


def css_ok(css):
    return (isinstance(css, str) and 0 < len(css) < 6000 and css.count("{") == css.count("}") and css.count("{") > 0
            and not re.search(r"<|javascript:|expression\(|@import|behavior:", css, re.I))


def quick_fix(drafts, look, summary=""):
    """One direct model call (no agent, no tools, thinking off): concrete notes become CSS in the look, live within
    seconds; open-ended ones are left for the Designer. Returns {"applied": [...], "open": [...], "look", "secs"} or
    None when there's no model to call (the Designer then takes the whole round, as before)."""
    mc = model_config()
    if not mc:
        return None
    t0 = datetime.datetime.now()
    vd = VARIANTS / look
    css_file = vd / "style.css"
    current = css_file.read_text(encoding="utf-8", errors="replace") if css_file.exists() else ""
    design = HOME / "vault" / "design" / "DESIGN.md"
    tokens = design.read_text(encoding="utf-8", errors="replace")[:3000] if design.exists() else ""
    items = []
    for i, n in enumerate(drafts, 1):
        items.append({"n": i, "note": n.get("note"), "kind": n.get("kind"), "selector": n.get("selector")
                      or (n.get("anchor") or {}).get("selector"), "text": (n.get("text") or "")[:200],
                      "inside": [e.get("selector") for e in (n.get("elements") or [])[:6]], "element": n.get("ctx"),
                      "screen": n.get("viewport")})
    user = (("Their overall comment: " + summary + "\n\n" if summary else "") + "Notes:\n" + json.dumps(items, indent=1)
            + "\n\nDesign tokens (DESIGN.md, start):\n" + tokens + "\n\nThe look's current CSS (yours to add to):\n"
            + current[-12000:])
    content = [{"type": "text", "text": user}]
    for _ in range(40):                                        # an area drawn just before Send: its snip is seconds away
        if not any(n["id"] in SNIPPING for n in drafts if n.get("kind") == "area"):
            break
        threading.Event().wait(0.25)
    for i, n in enumerate(drafts, 1):                          # areas: the snip shows the spot (elements: text is enough)
        pic = INBOX / f"{n['id']}.png"
        if n.get("kind") == "area" and pic.exists() and pic.stat().st_size < 1_500_000:
            import base64
            content += [{"type": "text", "text": f"Note {i}'s snip (what the owner boxed):"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(pic.read_bytes()).decode()}}]
    body = {"model": mc["model"], "max_tokens": 2500, "temperature": 0.3,
            "messages": [{"role": "system", "content": QUICK_SYSTEM},
                         {"role": "user", "content": content if len(content) > 1 else user}]}
    if "deepseek" in mc["model"].lower():
        body["thinking"] = {"type": "disabled"}              # seconds, not tens of seconds
    headers = {"Authorization": "Bearer " + mc["key"], "Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": "hermes-feedback-inbox/1.0"}
    if mc["opencode"]:
        headers["x-opencode-session"] = f"mark-{look}"          # same backend for every round on this look: warm cache
    try:
        import urllib.request
        req = urllib.request.Request(mc["url"], data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=45) as r:
            reply = json.loads(r.read())["choices"][0]["message"].get("content") or ""
        m = re.search(r"\{.*\}", reply, re.S)
        out = json.loads(m.group(0)) if m else {}
    except Exception as e:                                       # any failure: the Designer takes the round
        print(f"feedback-inbox: quick fix failed: {e}", file=sys.stderr)
        return None
    applied, opened, blocks = [], [], []
    for f in out.get("fixes") or []:
        try:
            n = drafts[int(f.get("n")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        if not css_ok(f.get("css")):
            opened.append({"n": f.get("n"), "why": "the quick fix wasn't usable CSS"})
            continue
        blocks.append(f"\n/* quick fix {t0:%Y-%m-%d %H:%M} (owner note {f['n']}, {n['id']}): "
                      f"{clean(n.get('note'), 120).splitlines()[0].replace('*/', '')} */\n{f['css'].strip()}\n")
        applied.append({"n": f["n"], "id": n["id"], "did": clean(f.get("did") or "", 160)})
    for o in out.get("open") or []:
        opened.append({"n": o.get("n"), "why": clean(o.get("why") or "", 200)})
    done = {a["n"] for a in applied}
    for i, n in enumerate(drafts, 1):                            # anything the model skipped is the Designer's
        if i not in done and i not in {o.get("n") for o in opened}:
            opened.append({"n": i, "why": "not answered by the quick fix"})
    if blocks:
        vd.mkdir(parents=True, exist_ok=True)
        if not (vd / "note.md").exists():
            (vd / "note.md").write_text("# Quick fixes\nThe owner's concrete notes, applied in seconds by the feedback "
                                        "inbox; the Designer tidies them.\n", encoding="utf-8")
        tmp = css_file.with_suffix(".css.tmp")
        tmp.write_text(current + "".join(blocks), encoding="utf-8")
        os.replace(tmp, css_file)
        for a in applied:
            set_field(INBOX / f"{a['id']}.md", "quick_fix", f"applied to {look}/style.css")
    return {"applied": applied, "open": opened, "look": look,
            "secs": round((datetime.datetime.now() - t0).total_seconds(), 1)}


DESIGN_ROUND = "Owner design round"


def send(scope, summary=""):
    """The owner pressed Send: the drafts left on this link (the mockup, demo 1 or 2, or an app) become one batch of
    open notes, listed by where they were left. Design batches go straight to the Designer as one card (or
    join the round already waiting for it); the rest wake the Manager to route them."""
    drafts = [n for n in notes("draft") if in_scope(n, scope) and not is_test(n)]    # a test note is never sent
    if not drafts:
        return None, 0, None, None
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
    quick = None
    looks_on = sorted({n["variant"] for n in drafts if n.get("variant")})
    if (SCRIPTS / "quick-lane.on").exists() and (scope[0] == "mockup" or (scope[0] == "app" and looks_on)):
        quick = quick_fix(drafts, looks_on[0] if looks_on else QUICK_LOOK, summary)
        if quick:
            with open(INBOX / f"{batch}.md", "a", encoding="utf-8") as fh:
                fh.write(f"\n**Quick lane** ({quick['secs']} s, into `design/variants/{quick['look']}/style.css`):\n"
                         + "".join(f"- note {a['n']}: {a['did']}\n" for a in quick["applied"])
                         + "".join(f"- note {o['n']}: for the Designer ({o['why']})\n" for o in quick["open"]))
    if scope[0] in ("mockup", "demo") and (HOME / ".hermes" / "profiles" / "designer").is_dir():
        card = None
        try:
            waiting = [t for t in json.loads(hermes("kanban", "list", "--json") or "[]")
                       if t.get("assignee") == "designer" and t.get("status") in ("ready", "todo")
                       and str(t.get("title", "")).startswith(DESIGN_ROUND)]
            if waiting:                          # a round that hasn't started yet takes this batch too
                card = waiting[0]["id"]
                hermes("kanban", "comment", card, f"More from the owner for this round (sent {now:%H:%M}):\n\n"
                       + round_text(batch, drafts, where, card, summary, quick, card_id=card))
            else:
                # The round resumes the Designer's session for this look or demo (hermes-worker.py), so it starts
                # knowing the page, the look and the last round instead of re-learning them.
                looks = sorted({n["variant"] for n in drafts if n.get("variant")}) or ([quick["look"]] if quick else [])
                place = looks[0] if looks else ("mockup" if scope[0] == "mockup" else (scope[2] or "demo").split(":")[0])
                topic = "design:" + (re.sub(r"[^a-z0-9._-]+", "-", place.lower()).strip("-")[:60] or "mockup")
                def body_for(cid):                   # twice: the id only exists once the card is created
                    return (f"Context: the owner's design feedback, sent together (batch `vault/raw/feedback/{batch}.md`). "
                            "Review: none (the owner reviews it on the mockup).\n"
                            f"Session: {topic}\n\n"
                            + round_text(batch, drafts, where, "this card", summary, quick, card_id=cid)
                            + round_tail())
                title = (f"{DESIGN_ROUND}: {len(quick['open'])} open, {len(quick['applied'])} live" if quick
                         else f"{DESIGN_ROUND}: {len(drafts)} notes")
                bf = INBOX / f".{batch}.card.md"                 # a file, not an argument: no size or character limits
                bf.write_text(clean(body_for(None), 200_000), encoding="utf-8")
                try:
                    args = ["kanban", "create", title, "--assignee", "designer", "--body-file", str(bf),
                            "--workspace", f"dir:{HOME}", "--max-runtime", "10m", "--created-by", "owner",
                            "--idempotency-key", batch, "--json"]
                    card = json.loads(hermes(*args)).get("id")
                    if card:                                 # name the card in its own command: nothing else carries the id
                        hermes("kanban", "edit", card, "--body", clean(body_for(card), 200_000))
                finally:
                    bf.unlink(missing_ok=True)
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError) as e:
            print(f"feedback-inbox: no Designer card for {batch}, waking the Manager: {e}", file=sys.stderr)
            card = None                          # no card: the Manager routes it instead (the batch page is saved either way)
        if card:
            set_field(INBOX / f"{batch}.md", "card", card)
            return batch, len(drafts), "Designer", quick
    # Otherwise wake the Manager now instead of at the next 15-minute watch (it runs on the scheduler's next tick).
    try:
        subprocess.Popen(["hermes", "-p", "manager", "cron", "run", "manager-watch"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env)
    except OSError:
        pass                                     # the 15-minute watch still picks the batch up
    return batch, len(drafts), "Manager", quick


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


def working_look():
    """The look the mockup shows (vault/design/mockup-look names it), or None for the app as built."""
    try:
        name = MOCKUP_LOOK.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name if re.fullmatch(r"[\w-]+", name or "") and (VARIANTS / name).is_dir() else None


def design_nav(here):
    """The nav badge: the mockup and the two demos, on their fixed ports, each with what it shows now."""
    if not BASE:
        return []
    names = {rp: name for rp, _, name in mirrors()}
    mk = set(mockups().values())
    out = []
    for off, label in DESIGN_VIEWS:
        port = BASE + off
        name = names.get(port)
        if off == 51:
            what = working_look() or "the app as built" if name else None
        else:
            what = re.sub(r"^demo \d+:\s*", "", name, flags=re.I) if name else None
        out.append({"label": label, "port": port, "what": what, "here": port == here})
    return out


def badge(variant, mockup, demo=None, looks=True, nav=None):
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
    cfg = {"variant": variant, "looks": names, "mockup": info, "demo": demo, "nav": nav or []}
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
        return ("app", None, self.app_name)

    def rounds_here(self):           # does this page carry a round? (a mockup or a demo; see send())
        return False

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
        if path == "/live-reload.js":          # a demo page watches its own files (added to demo pages below)
            self._send(200, (SCRIPTS / "live-reload.js").read_text(encoding="utf-8"), "application/javascript")
            return True
        if path == "/look-version":            # the page refreshes itself when the look it shows changes
            v = parse_qs(query).get("v", [""])[0]
            vd = VARIANTS / v if re.fullmatch(r"[\w-]+", v or "") else None
            stamp = lambda f: f.stat().st_mtime_ns if f.exists() else 0
            out = {"css": stamp(vd / "style.css"), "js": stamp(vd / "script.js")} if vd else {}
            if getattr(self, "kind", lambda: "")() == "mockup":
                out["look"] = working_look()       # the Designer (or a pick on a demo) changed it: the page reloads
            if self.rounds_here():             # a mockup or a demo: this page also carries its round
                try:
                    r = round_block(self.scope())
                except Exception as e:         # a broken board read must never break the page's look
                    print(f"feedback-inbox: no round for {self.scope()}: {e}", file=sys.stderr)
                    r = None
                if r:
                    out["round"] = r
            self._send(200, json.dumps(out))
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
        if path == "/pick-look":                # "Use this one" on a demo's portfolio: the mockup now shows that look
            try:
                look = str(json.loads(raw or b"{}").get("look") or "")
            except ValueError:
                look = ""
            if look == "off":                   # the app as built
                MOCKUP_LOOK.unlink(missing_ok=True)
            elif not re.fullmatch(r"[\w-]+", look) or not (VARIANTS / look).is_dir():
                self._send(400, '{"error":"no such look"}')
                return True
            else:
                MOCKUP_LOOK.write_text(look + "\n", encoding="utf-8")
            try:                                # the Designer learns it from the log
                subprocess.run([str(SCRIPTS / "vault-log.sh"), "owner", "decision", f"picked look {look} for the mockup",
                                f"design/variants/{look}"], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError) as e:
                print(f"feedback-inbox: pick not logged: {e}", file=sys.stderr)
            self._send(200, json.dumps({"look": look}))
            return True
        if path == "/notes/send":
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                d = {}
            batch, count, to, quick = send(self.scope(), d.get("summary", ""))
            self._send(200, json.dumps({"batch": batch, "sent": count, "to": to, "quick": quick}))
            return True
        if path == "/notes/answer":            # the owner answered the round: back to the same session it came from
            if not self.rounds_here():
                self._send(409, '{"error":"answers go to a round: only a mockup or a demo carries one"}')
                return True
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                d = {}
            try:
                self._send(201, json.dumps(answer(self.scope(), d.get("card"), d.get("text", ""), d.get("page"))))
            except ValueError as e:
                self._send(400, json.dumps({"error": str(e)}))
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
        path = urlparse(self.path).path
        if path == "/shoot":
            return self.shoot()
        if path == "/check":
            if self.client_address[0] != "127.0.0.1":
                return self._send(403, '{"error":"localhost only"}')
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                out = look_check(d["url"], int(d.get("width", 1440)), int(d.get("height", 900)), list(d.get("js", [])), d.get("shot"), d.get("steps"))
            except (ValueError, KeyError) as e:
                return self._send(400, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(out))
        if not self.inbox_post(path):
            self._send(404, '{"error":"not found"}')

    def shoot(self):
        """variant-shot.sh hands its screenshots to this service: a browser can crash inside a bot's terminal, but runs
        fine from here (the same place the Mark snips are taken). Localhost only."""
        if self.client_address[0] != "127.0.0.1":
            return self._send(403, '{"error":"localhost only"}')
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            args = [str(SCRIPTS / "variant-shot.sh"), str(d["variant"]), *[str(a) for a in d.get("args", [])]]
        except (ValueError, KeyError):
            return self._send(400, '{"error":"variant missing"}')
        if not re.fullmatch(r"[\w-]+", args[1]):
            return self._send(400, '{"error":"bad variant name"}')
        r = subprocess.run(args, capture_output=True, text=True, timeout=300,
                           env={**os.environ, "VARIANT_SHOT_LOCAL": "1", "PATH": f"{HOME}/.local/bin:/usr/bin:/bin"})
        self._send(200, json.dumps({"code": r.returncode, "out": r.stdout, "err": r.stderr[-2000:]}))


def mirror_handler(app_port, name, review_port=None):
    class Mirror(Base):
        prefix = "/__mark"
        app_name = name

        def current_variant(self):
            # The mockup always shows the Designer's working look (vault/design/mockup-look); an explicit
            # ?__variant= (a demo's portfolio frame, a screenshot) shows another one without changing it.
            q = parse_qs(urlparse(self.path).query).get("__variant", [None])[0]
            if q is None and self.kind() == "mockup":
                q = working_look()
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
            return (self.kind(), review_port, name)

        def rounds_here(self):
            return self.kind() in ("mockup", "demo")

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
                     ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
                     ".svg": "image/svg+xml", ".md": "text/plain", ".html": "text/html"}
            self._send(200, f.read_bytes(), types.get(f.suffix, "application/octet-stream"))

        def _proxy(self):
            u = urlparse(self.path)
            mockup = mockups().get(app_port)
            if u.path == "/look-version" and self.command in ("GET", "HEAD") and self.rounds_here():
                return self.inbox_get(u.path, u.query)   # the round channel belongs to the review link itself
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
            if any(n in u.query for n in ("__variant=", "__shot=", "__nooverlay=")):   # the app never sees these
                rest = "&".join(p for p in u.query.split("&") if not p.startswith(
                    ("__variant=", "__shot=", "__scroll=", "__nooverlay=")))
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
                shot = "__shot=" in u.query               # a snapshot: strip the marker params, set no cookie
                no_overlay = "__nooverlay=" in u.query    # an explicit ask for a picture with no overlay UI in it
                tag = b"" if no_overlay else b'<script src="/__mark/overlay.js" defer></script>'
                if self.kind() == "demo" and not shot:   # a demo is plain files: it updates itself as a round lands
                    tag += b'<script src="/__mark/live-reload.js" defer></script>'
                v = self.current_variant()
                if v:                                  # the Designer's variant on top of the live app
                    vd = VARIANTS / v
                    tag += f'<link rel="stylesheet" href="/__mark/v/{v}/style.css">'.encode() if (vd / "style.css").exists() else b""
                    tag += f'<script src="/__mark/v/{v}/script.js" defer></script>'.encode() if (vd / "script.js").exists() else b""
                # Looks are tried on the mockup; the real app's link offers them only when there is no mockup.
                tag += b"" if no_overlay else badge(v, mockup, name if self.kind() == "demo" else None,
                                                    looks=False, nav=design_nav(review_port))
                sy = parse_qs(u.query).get("__scroll", ["0"])[0]
                if shot and sy.isdigit() and int(sy):          # a snip: put the page at the owner's scroll position
                    tag += (f"<script>(()=>{{let n=0;const t=setInterval(()=>{{scrollTo(0,{int(sy)});if(++n>20)clearInterval(t)}},250)}})()"
                            "</script>").encode()
                page = re.sub(rb"(?i)</body>", lambda m: tag + m.group(0), page, count=1) if re.search(rb"(?i)</body>", page) else page + tag
                self.send_response(r.status, r.reason)
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
    BASE = int(sys.argv[1]) - 99
    servers = [ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Inbox)]
    for rp, ap, name in mirrors():
        try:
            servers.append(ThreadingHTTPServer(("0.0.0.0", rp), mirror_handler(ap, name, rp)))
        except OSError as e:
            print(f"feedback-inbox: review port {rp} for {name}: {e}", file=sys.stderr)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    servers[0].serve_forever()
