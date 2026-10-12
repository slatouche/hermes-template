#!/usr/bin/python3
"""design-view.py: the owner's design view for one project, on one port (API port + 51).

  design-view.py --project <name> --port <n> --app <frontend dir> --layer <layer dir> [--bind 0.0.0.0]

What it serves:
  /            the shell: a toolbar above the app (status line, marking, options, undo)
  /app/...     the app's real front end, read from disk on every request (so Engineer changes show at once),
               with layer.js added to its index.html
  /api/...     a mock API: layer/data/<path>.json, else snapshot/<path>.json; writes are kept in memory only
  /dv/...      the toolbar's own files, the layer's edits (/dv/ops), live events (/dv/events), notes (/dv/note),
               direct edits (/dv/op), undo (/dv/undo), picking an option (/dv/pick)

A note is one streamed model call (the quick path): a knowledge pack (rules, edit commands, the app's theme tokens,
the brief, the layer so far) plus the screen, the marks and the note. The model answers a VERDICT line and then one
edit per line; each edit is checked and sent to the page the moment it arrives. Notes that are not quick become
kanban cards (background -> designer, function -> manager). No Hermes session is involved, so nothing grows or
compacts: every call is the same size. The layer is the design: ops.jsonl (the edits), history.jsonl (every note
and what it did, for undo), options/ (choices on show), data/ (fill data), config.json (where screens go).
"""
import argparse
import json
import os
import pathlib
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = pathlib.Path.home()
ASSETS = HOME / ".hermes" / "design-view"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}

RULES = """You change how a live web app looks while its owner watches. Answer in lines and nothing else.
Line 1: VERDICT <quick|options|screen|background|function|ask> | <one short line for the owner: what you'll do>
Then one edit per line, each a JSON object:
{"op":"token","name":"--x","value":"..."}                 change a theme token (preferred: the whole app follows)
{"op":"css","rule":"<selector> { ... }"}                     a CSS rule written with the tokens
{"op":"move","sel":"<what>","where":"before|after|into|start","ref":"<where>"}
{"op":"text","sel":"<what>","text":"<new text>"}
{"op":"insert","where":"before|after|into|start","ref":"<where>","html":"<markup>"}
{"op":"attr","sel":"<what>","name":"<attribute>","value":"<value>"}
{"op":"repeat","sel":"<the list's items>","n":8,"fill":{"<part>":["text 1","text 2"],"img@src":["url 1","url 2"]}}
    one per list: the list ends up with n items (copies of its first), and fill sets each item's parts in order
    (text, or an attribute after @). Build one item, then repeat it; never insert the same item many times.
{"op":"remove","sel":"<what>"}
{"op":"link","sel":"<what is clicked>","to":"#/route"}           clicking it goes to that screen (prototype navigation)
{"op":"undo","notes":["n3"]}                                  take back earlier notes (ids from "Notes so far")
Any edit may add "on":"#/route" to apply on one screen only.
Verdicts:
- quick: a visible change you can make now with the edits above (style, spacing, colour, move, text, add or repeat
  elements, placeholder content, undo of named notes).
- options: the owner asks for choices, or it is a matter of taste with several good answers. Give 3 sets; start each
  with a line: OPTION A <short name>  (then B, C). Each set must stand alone.
- screen: a new screen or panel that doesn't exist yet. First a line: SCREEN #/<route> <menu label>. Then insert edits
  with "ref":"@screen" (into the new screen) building it top to bottom, a section per insert, using the app's classes.
  If it is opened from something on another screen (a deck card, a button), add a link edit for that too.
- background: a visible change that needs interaction work no behavior below covers (custom animation choreography,
  multi-step flows, new kinds of widget). No edits; the plan line says what will be built.
Ready-made interactions (behavior edits; use them instead of calling something background):
{"op":"behavior","name":"sortable","sel":"<the lists>","item":"<an item>"}   drag to reorder, and between all those lists
{"op":"behavior","name":"toggle","sel":"<button>","target":"<what shows>"}    click shows/hides target
{"op":"behavior","name":"dialog","sel":"<button>","target":"<hidden dialog markup>"}  click opens it as a modal
  (insert the dialog's markup first with a hidden attribute; give its close button data-close)
{"op":"behavior","name":"tabs","sel":"<the tab row>","panels":"<the panels>"}  click a tab, see its panel
{"op":"behavior","name":"toast","sel":"<button>","text":"Saved"}             click shows a short message (simulated save)
{{EXTRA_BEHAVIORS}}
- function: it needs real behaviour or data (parsing, saving, importing, accounts). No edits; one line for the Manager.
- ask: you can't tell what they want (e.g. a bare "undo"). No edits; the plan line is one short question.
Rules: prefer token edits; one-off CSS only when the note names one element. Selectors must match the map you are
given. Markup is plain HTML with classes: no style attributes (style it with css edits), no scripts, no on* handlers,
no javascript: URLs; placeholder text and images (https://placehold.co/WxH) are fine. Where the map shows an
element's own style="...", a css edit for those properties needs !important. Do the minimum that makes the change
visible and clickable; it is a mockup."""

UNSAFE_HTML = re.compile(r"<\s*(script|iframe|object|embed|link|meta|base)\b|javascript:|\son[a-z]+\s*=", re.I)
UNSAFE_CSS = re.compile(r"</|javascript:|@import|expression\(|behavior:", re.I)


def check_op(op):
    """A safe, well-formed edit or a ValueError saying why not."""
    if not isinstance(op, dict) or not isinstance(op.get("op"), str):
        raise ValueError("not an edit")
    k = op["op"]
    need = {"token": ("name", "value"), "css": ("rule",), "move": ("sel", "where", "ref"), "text": ("sel", "text"),
            "insert": ("where", "ref", "html"), "attr": ("sel", "name", "value"), "repeat": ("sel",),
            "remove": ("sel",), "screen": ("route", "label"), "undo": ("notes",), "link": ("sel", "to"),
            "behavior": ("name", "sel")}.get(k)
    if need is None:
        raise ValueError(f"unknown edit '{k}'")
    for f in need:
        if op.get(f) in (None, ""):
            raise ValueError(f"{k} needs {f}")
    if k == "token":
        if not re.fullmatch(r"--[A-Za-z0-9_-]+", op["name"]) or re.search(r"[;{}<]", str(op["value"])):
            raise ValueError("bad token")
    if k == "css":
        r = op["rule"]
        if r.count("{") != r.count("}") or "{" not in r or UNSAFE_CSS.search(r):
            raise ValueError("unsafe or unbalanced CSS")
    if k in ("move", "insert") and op["where"] not in ("before", "after", "into", "start"):
        raise ValueError("where must be before|after|into|start")
    if k == "insert" and UNSAFE_HTML.search(op["html"]):
        raise ValueError("unsafe markup")
    if k == "attr" and (str(op["name"]).lower().startswith("on") or "javascript:" in str(op["value"]).lower()
                        or not re.fullmatch(r"[A-Za-z_:][-A-Za-z0-9_:.]*", str(op["name"]))):
        raise ValueError("unsafe attribute")
    if k == "repeat" and not (op.get("values") or op.get("fill") or isinstance(op.get("n"), int)):
        raise ValueError("repeat needs n or fill")
    if k == "repeat" and op.get("fill") is not None:
        if not isinstance(op["fill"], dict) or not all(isinstance(v, list) for v in op["fill"].values()):
            raise ValueError("fill is {part: [values]}")
        for key, vals in op["fill"].items():
            attr = key.split("@", 1)[1] if "@" in key else ""
            if attr.lower().startswith("on") or any("javascript:" in str(v).lower() for v in vals):
                raise ValueError("unsafe fill")
    if k == "repeat" and isinstance(op.get("n"), int) and not 0 < op["n"] <= 200:
        raise ValueError("repeat n out of range")
    if k == "screen" and not re.fullmatch(r"#/[A-Za-z0-9_/-]*", op["route"]):
        raise ValueError("bad route")
    if k == "link" and not re.fullmatch(r"#/[A-Za-z0-9_/-]*", str(op["to"])):
        raise ValueError("link goes to a #/route")
    if k == "behavior":
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,40}", str(op["name"])):
            raise ValueError("bad behavior name")
        for f, v in op.items():
            if f not in ("op", "name", "sel", "id", "note", "on") and (not isinstance(v, (str, int, float, bool))
                                                                       or "javascript:" in str(v).lower() or "<" in str(v)):
                raise ValueError(f"bad behavior option {f}")
    if k == "undo" and not (isinstance(op["notes"], list) and all(re.fullmatch(r"n\d+", str(n)) for n in op["notes"])):
        raise ValueError("undo needs note ids")
    if op.get("on") is not None and not re.fullmatch(r"#/[A-Za-z0-9_/-]*", str(op["on"])):
        raise ValueError("bad on")
    return op


class Layer:
    """The design layer on disk, and the one lock every change to it takes."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "data").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.ops = self._read("ops.jsonl")
        self.history = self._read("history.jsonl")
        self.options = json.loads((self.root / "options.json").read_text()) if (self.root / "options.json").exists() else {}
        self.frozen = (self.root / "FROZEN").exists()
        nums = [int(o["id"][1:]) for o in self.ops if re.fullmatch(r"e\d+", str(o.get("id")))]
        nums += [int(o["id"][1:]) for s in self.options.values() for c in s["choices"].values() for o in c["ops"]
                 if re.fullmatch(r"e\d+", str(o.get("id")))]
        self.next_op = max(nums, default=0) + 1
        used = [h.get("id") for h in self.history] + [o.get("note") for o in self.ops] + list(self.options)
        self.next_note = max([int(str(u)[1:]) for u in used if re.fullmatch(r"n\d+", str(u))], default=0) + 1
        # Bumped on every change. A page compares it with what it last loaded and catches up on anything it missed
        # (an edit that arrived while it was reloading). Starts from the clock, so it only grows across restarts.
        self.version = int(time.time() * 1000)

    def _read(self, name):
        p = self.root / name
        out = []
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
        return out

    def config(self):
        p = self.root / "config.json"
        cfg = {"screen": "[data-ui=screen]", "nav": "[data-ui=nav]"}
        if p.exists():
            try:
                cfg.update(json.loads(p.read_text()))
            except ValueError:
                pass
        return cfg

    def _save(self):
        tmp = self.root / "ops.jsonl.tmp"
        tmp.write_text("".join(json.dumps(o) + "\n" for o in self.ops), encoding="utf-8")
        tmp.replace(self.root / "ops.jsonl")
        tmp = self.root / "options.json.tmp"
        tmp.write_text(json.dumps(self.options, indent=1), encoding="utf-8")
        tmp.replace(self.root / "options.json")
        self.version += 1

    def note_id(self):
        with self.lock:
            self.next_note += 1
            return f"n{self.next_note - 1}"

    def new_note(self, text, marks, route, nid=None):
        return {"id": nid or self.note_id(), "note": text, "marks": [m.get("sel") for m in marks or []], "route": route,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ops": [], "verdict": None, "plan": None}

    def add(self, op, note, option=None):
        """Store one checked edit (into the layer, or into an option set) and return it with its id."""
        with self.lock:
            op = dict(op, id=f"e{self.next_op}", note=note["id"])
            self.next_op += 1
            if option:
                self.options[option[0]]["choices"][option[1]]["ops"].append(op)
            elif op["op"] == "undo":
                gone = set(op["notes"])
                self.ops = [o for o in self.ops if o.get("note") not in gone]
            else:
                self.ops.append(op)
            note["ops"].append(op["id"])
            self._save()
            return op

    def undo_notes(self, ids):
        with self.lock:
            ids = set(ids)
            self.ops = [o for o in self.ops if o.get("note") not in ids]
            self._save()

    def last_note_with_ops(self):
        with self.lock:
            live = {o.get("note") for o in self.ops}
            for h in reversed(self.history):
                if h["id"] in live:
                    return h["id"]
        return None

    def finish(self, note):
        with self.lock:
            self.history.append(note)
            with (self.root / "history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(note) + "\n")

    def new_option_set(self, note):
        with self.lock:
            sid = note["id"]
            self.options[sid] = {"note": note["note"], "choices": {}}
            return sid

    def add_choice(self, sid, letter, name):
        with self.lock:
            self.options[sid]["choices"][letter] = {"name": name, "ops": []}
            self._save()

    def pick(self, sid, letter):
        with self.lock:
            s = self.options.pop(sid, None)
            if s and letter in s["choices"]:
                self.ops.extend(s["choices"][letter]["ops"])
            self._save()
            return bool(s)

    def state(self, name):
        p = self.root / name
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except ValueError:
            return {}

    def set_state(self, name, value):
        p = self.root / name
        if value is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(json.dumps(value, indent=1))
        self.frozen = (self.root / "FROZEN").exists()

    def archive(self, stamp):
        """Shipped: the layer's edits, options and notes go to archive/<stamp>/ and the layer starts clean."""
        with self.lock:
            dest = self.root / "archive" / stamp
            dest.mkdir(parents=True, exist_ok=True)
            for name in ("ops.jsonl", "options.json", "history.jsonl", "FROZEN", "PREVIEW"):
                if (self.root / name).exists():
                    (self.root / name).replace(dest / name)
            self.ops, self.options, self.history = [], {}, []
            self._save()
            self.frozen = False

    def summary(self, limit=80):
        with self.lock:
            rows = [json.dumps({k: v for k, v in o.items() if k != "id"})[:220] for o in self.ops[-limit:]]
        return "\n".join(rows) or "(nothing yet)"


class Events:
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()

    def add(self):
        q = queue.Queue()
        with self.lock:
            self.clients.append(q)
        return q

    def drop(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def send(self, kind, **data):
        msg = json.dumps(dict(data, type=kind, t=round(time.time(), 3)))
        with self.lock:
            for q in list(self.clients):
                q.put(msg)


def model_config():
    """The project's model, endpoint and key, as Hermes runs it. The key stays in this process."""
    import yaml
    h = HOME / ".hermes"
    cfg = next((p for p in (h / "profiles" / "designer" / "config.yaml", h / "config.yaml") if p.exists()), None)
    if not cfg:
        return None
    m = {k: str(v) for k, v in ((yaml.safe_load(cfg.read_text()) or {}).get("model") or {}).items() if v is not None}
    if not (m.get("default") and m.get("base_url")):
        return None
    var = re.sub(r"[^A-Z0-9]", "_", (m.get("provider") or "").upper()) + "_API_KEY"
    for env in (h / "profiles" / "designer" / ".env", h / ".env"):
        if env.exists():
            for ln in env.read_text().splitlines():
                if ln.startswith(var + "=") and ln.split("=", 1)[1].strip():
                    return {"model": os.environ.get("DV_MODEL") or m["default"],
                            "url": m["base_url"].rstrip("/") + "/chat/completions",
                            "key": ln.split("=", 1)[1].strip().strip('"')}
    return None


BEHAVIORS = HOME / "vault" / "design" / "behaviors"


def approved_behaviors():
    """Behaviors the Manager approved: vault/design/behaviors/<name>.js (proposals wait in proposed/)."""
    return sorted(p for p in BEHAVIORS.glob("*.js") if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,40}", p.stem))


def first_comment(p):
    m = re.search(r"/\*\s*(.*?)(?:\*/|\n)", p.read_text(encoding="utf-8", errors="replace"))
    return (m.group(1).strip() if m else "")[:140]


DEEP_RULES = """
## This note needs more than a quick change: you have time to think it through
The quick judge called it background work. Build the whole thing now, as edits (no VERDICT line this time): every
screen, state and interaction it needs, with behaviors for anything interactive and placeholder content. Use the
maps you are given for selectors. If an interaction truly needs a behavior that doesn't exist, build everything
visible first, then end with a proposal for it:
PROPOSE <name> | <one line: what it does and its options>
```js
window.__dvBehaviors["<name>"] = function (el, op) { /* plain DOM; no network, storage or eval; once per element */ };
```"""


def stream_lines(mc, messages, session, max_tokens=3000, thinking=False):
    """Yield the model's answer line by line as it arrives, then a final ('usage', {...}). Thinking is off for the
    quick path (twice as fast, and it judges better); the deep path turns it on."""
    body = {"model": mc["model"], "messages": messages, "max_tokens": max_tokens, "temperature": 0.3, "stream": True,
            "stream_options": {"include_usage": True}}
    if "deepseek" in mc["model"].lower():
        body["thinking"] = {"type": "enabled" if thinking else "disabled"}
    req = urllib.request.Request(mc["url"], data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": "Bearer " + mc["key"], "Content-Type": "application/json", "User-Agent": "hermes-design-view/1.0",
        "x-opencode-session": session})
    buf, usage = "", None
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            s = raw.decode("utf-8", "replace").strip()
            if not s.startswith("data:"):
                continue
            s = s[5:].strip()
            if s == "[DONE]":
                break
            try:
                ev = json.loads(s)
            except ValueError:
                continue
            usage = ev.get("usage") or usage
            for ch in ev.get("choices") or []:
                buf += (ch.get("delta") or {}).get("content") or ""
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        yield "line", line.strip()
    if buf.strip():
        yield "line", buf.strip()
    yield "usage", usage or {}


class App:
    def __init__(self, a):
        self.a = a
        self.project = a.project
        self.app_dir = pathlib.Path(a.app).resolve()
        self.layer = Layer(a.layer)
        self.events = Events()
        self.notes = queue.Queue()
        self.mem = {}                       # mock API writes: path -> value
        self.maps = {}                      # route -> the latest screen map the page sent
        self.groups = {}                    # a Designer card's id -> its note record (its edits undo together)
        self.reports = {}                   # edit id -> how it fared on the owner's open page
        self.status = {"busy": None, "queued": 0}
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.watch_app, daemon=True).start()

    # ---- the knowledge pack ------------------------------------------------------------------------------------
    def tokens(self):
        """The app's theme tokens: every --name: value declared in its CSS files' :root blocks."""
        out = []
        for p in sorted(self.app_dir.glob("*.css")):
            for block in re.findall(r":root\s*\{(.*?)\}", p.read_text(encoding="utf-8", errors="replace"), re.S):
                out += [m.strip() for m in re.findall(r"(--[\w-]+\s*:[^;]+);", block)]
        return "\n".join(dict.fromkeys(out)) or "(none)"

    def classes(self):
        """The app's component classes, so new markup reuses them."""
        seen = []
        for p in sorted(self.app_dir.glob("*.css")):
            for sel in re.findall(r"(?m)^\s*([.#][\w-][^{]*)\{", p.read_text(encoding="utf-8", errors="replace")):
                seen += re.findall(r"\.[A-Za-z][\w-]*", sel)
        return " ".join(list(dict.fromkeys(seen))[:300]) or "(none)"

    def pack(self):
        brief_p = HOME / "vault" / "design" / "brief.md"
        brief = brief_p.read_text(encoding="utf-8", errors="replace")[:4000] if brief_p.exists() else "(no brief yet)"
        agreed_p = self.layer.root / "agreed.md"
        agreed = agreed_p.read_text(encoding="utf-8", errors="replace")[:3000] if agreed_p.exists() else "(nothing agreed yet)"
        extra = "\n".join(f'{{"op":"behavior","name":"{p.stem}","sel":"..."}}   {first_comment(p)}'
                          for p in approved_behaviors())
        return (RULES.replace("{{EXTRA_BEHAVIORS}}", extra) + "\n\n## Design brief\n" + brief + "\n\n## Agreed so far\n" + agreed +
                "\n\n## App theme tokens\n" + self.tokens() + "\n\n## App component classes\n" + self.classes() +
                "\n\n## The design layer so far (edits on top of the app)\n" + self.layer.summary())

    def ask(self, n):
        notes = "\n".join(f'{h["id"]}: {h["note"][:160]} -> {h.get("verdict")}: {(h.get("plan") or "")[:100]}'
                          for h in self.layer.history[-6:]) or "(none)"
        def mark(m):
            if m.get("kind") == "area":
                return (f'- an area the owner drew ({m.get("rect")}), inside {m.get("sel")}; it covers: '
                        f'{", ".join((m.get("inside") or [])[:12]) or "-"}')
            if m.get("kind") == "arrow":
                return f'- an arrow the owner drew from {m.get("from")} to {m.get("to")} (usually: move the first there)'
            return f'- {m.get("sel")}\n  html: {(m.get("html") or "")[:600]}\n  styles: {m.get("styles") or ""}'
        marks = "\n".join(mark(m) for m in n.get("marks") or []) or "(none)"
        return (f"Screen: {n.get('route') or '#/'}\nMap of the screen:\n{(n.get('map') or '')[:9000]}\n\n"
                f"Marked:\n{marks}\n\nNotes so far:\n{notes}\n\nNote {n['id']}: {n['text']}")

    # ---- the quick path ----------------------------------------------------------------------------------------
    def worker(self):
        while True:
            n = self.notes.get()
            self.status["queued"] = self.notes.qsize()
            self.status["busy"] = n["id"]
            try:
                self.run_note(n)
            except Exception as e:                                      # a failed note never stops the worker
                self.events.send("error", note=n["id"], message=f"{type(e).__name__}: {str(e)[:200]}")
            self.status["busy"] = None

    def run_note(self, n):
        if self.layer.frozen:
            self.events.send("done", note=n["id"], verdict="frozen", plan="The mockup is frozen while it's built.", s=0)
            return
        mc = model_config()
        if not mc:
            raise RuntimeError("no model config/key for the design view")
        rec = self.layer.new_note(n["text"], n.get("marks"), n.get("route"), nid=n["id"])
        t0 = time.monotonic()
        self.events.send("doing", note=n["id"], text=n["text"][:140])
        msgs = [{"role": "system", "content": self.pack()}, {"role": "user", "content": self.ask(n)}]
        said = []
        edits, refused, usage, _ = self.consume(stream_lines(mc, msgs, session=f"dv-{self.project}"), rec, n, t0, said=said)
        card = None
        if rec["verdict"] in ("quick", "screen") and rec["ops"]:
            # The check: the owner's open page measured each edit. Edits that matched nothing on this screen, or were
            # beaten by an element's own style attribute, get one repair call in the same note.
            bad = self.not_landed(rec, n.get("route") or "#/")
            if bad:
                self.events.send("verdict", note=n["id"], verdict=rec["verdict"],
                                 plan=f"{len(bad)} edit(s) didn't take; fixing", s=round(time.monotonic() - t0, 2))
                why = "\n".join(f"- {json.dumps({k: v for k, v in o.items() if k not in ('id', 'note')})[:300]}\n  -> {st}"
                                for o, st in bad)
                fix = msgs + [{"role": "assistant", "content": "\n".join(said)},
                              {"role": "user", "content": "Checked on the owner's page, these edits didn't take effect:\n" + why +
                               "\nReplace them now with edits that will work. An element's own style attribute beats any css "
                               "rule: add !important to those declarations (or change the attribute). A selector that matches "
                               "nothing: use one from the map. Edits only, no VERDICT line."}]
                e2, r2, u2, _ = self.consume(stream_lines(mc, fix, session=f"dv-{self.project}"), rec, n, t0, deep=True)
                edits, refused = edits + e2, refused + r2
                usage = {k: (usage.get(k) or 0) + (u2.get(k) or 0) for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens")}
                rec["repaired"] = len(bad)
        if rec["verdict"] == "background":
            # The deep path: the same kind of call with thinking on and the other screens' maps, still no agent.
            self.events.send("verdict", note=n["id"], verdict="background",
                             plan="thinking it through: " + (rec["plan"] or ""), s=round(time.monotonic() - t0, 2))
            others = "\n\n".join(f"Map of {r}:\n{m[:5000]}" for r, m in list(self.maps.items())[-5:] if r != n.get("route"))
            deep = [{"role": "system", "content": self.pack() + DEEP_RULES},
                    {"role": "user", "content": self.ask(n) + (f"\n\nOther screens:\n{others}" if others else "") +
                     f"\n\nThe quick judge said: background: {rec['plan']}"}]
            e2, r2, u2, proposal = self.consume(stream_lines(mc, deep, session=f"dv-{self.project}-deep", max_tokens=12000,
                                                             thinking=True), rec, n, t0, deep=True)
            edits, refused = edits + e2, refused + r2
            usage = {k: (usage.get(k) or 0) + (u2.get(k) or 0) for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens")}
            if proposal:
                card = self.propose(proposal, rec)
            elif not e2:
                card = self.card(rec)                                    # it couldn't: the Designer takes it
        rec["s"] = round(time.monotonic() - t0, 2)
        rec["tokens"] = {"in": usage.get("prompt_tokens"), "cached": usage.get("prompt_cache_hit_tokens",
                         (usage.get("prompt_tokens_details") or {}).get("cached_tokens")), "out": usage.get("completion_tokens")}
        rec["refused"] = refused
        if rec["verdict"] == "function":
            card = self.card(rec)
        self.layer.finish(rec)
        self.events.send("done", note=n["id"], verdict=rec["verdict"], plan=rec["plan"], edits=edits, refused=refused,
                         card=card, s=rec["s"], tokens=rec["tokens"])

    def not_landed(self, rec, route, wait=2.0):
        """The note's edits that the owner's open page (on the note's screen) says didn't take: matched nothing, or
        were beaten by an element's own style. Nothing to say when no page is open on that screen."""
        byid = {o["id"]: o for o in self.layer.ops}
        ids = [i for i in rec["ops"] if i in byid]

        def settled(i):                      # a css edit reports "ok" when applied, then its measurement
            r = self.reports.get(i)
            return bool(r) and not (byid[i]["op"] == "css" and r["status"] == "ok")
        end = time.monotonic() + wait
        while time.monotonic() < end and not all(settled(i) for i in ids):
            time.sleep(0.15)
        bad = []
        for i in ids:
            r = self.reports.get(i)
            if not r or r.get("route") != route or i not in byid:
                continue
            st = r["status"]
            if st.startswith("missing") or st.startswith("no effect: overridden"):
                bad.append((byid[i], st))
        return bad

    def consume(self, stream, rec, n, t0, deep=False, said=None):
        """Read a model answer line by line: the verdict, option and screen markers, a behavior proposal (deep path),
        and the edits, each checked, stored and sent to the page as it arrives."""
        option, screen, edits, refused, usage, sid, proposal = None, None, 0, [], {}, None, None
        for kind, val in stream:
            if kind == "usage":
                usage = val
                continue
            line = val
            if said is not None:
                said.append(line)
            if proposal is not None and not proposal.get("closed"):
                if line.startswith("```"):
                    if proposal.get("open"):
                        proposal["closed"] = True
                    proposal["open"] = True
                elif proposal.get("open"):
                    proposal["js"] += line + "\n"
                continue
            m = re.match(r"PROPOSE\s+([A-Za-z][A-Za-z0-9-]{0,40})\s*\|?\s*(.*)", line)
            if deep and m:
                proposal = {"name": m.group(1), "why": m.group(2).strip(), "js": ""}
                continue
            if not deep and rec["verdict"] is None and line.upper().startswith("VERDICT"):
                body = line[7:].strip()
                verdict, _, plan = body.partition("|")
                rec["verdict"] = verdict.strip(" <>").lower() or "quick"
                rec["plan"] = plan.strip()
                self.events.send("verdict", note=n["id"], verdict=rec["verdict"], plan=rec["plan"],
                                 s=round(time.monotonic() - t0, 2))
                if rec["verdict"] == "options":
                    sid = self.layer.new_option_set(rec)
                continue
            m = re.match(r"OPTION\s+([A-Z])\b\s*[:|-]?\s*(.*)", line)
            if m and rec["verdict"] == "options" and sid:
                option = (sid, m.group(1))
                self.layer.add_choice(sid, m.group(1), m.group(2).strip()[:60] or m.group(1))
                self.events.send("option", note=n["id"], set=sid, choice=m.group(1), name=m.group(2).strip()[:60])
                continue
            m = re.match(r"SCREEN\s+(#/[\w/-]*)\s*(.*)", line)
            if m:
                screen = m.group(1)
                op = self.layer.add(check_op({"op": "screen", "route": screen, "label": m.group(2).strip()[:40] or screen}), rec)
                self.events.send("op", note=n["id"], op=op, s=round(time.monotonic() - t0, 2))
                edits += 1
                continue
            if not line.startswith("{"):
                continue
            try:
                op = json.loads(line)
                if op.get("ref") == "@screen" and screen:
                    op["ref"] = "@screen:" + screen
                op = check_op(op)
            except ValueError as e:
                refused.append(f"{e}: {line[:120]}")
                continue
            op = self.layer.add(op, rec, option)
            edits += 1
            if op["op"] == "undo":
                self.events.send("reload-ops", why=f"undid {', '.join(op['notes'])}")
                continue
            self.events.send("op", note=n["id"], op=op, option=option and {"set": option[0], "choice": option[1]},
                             s=round(time.monotonic() - t0, 2))
        return edits, refused, usage, (proposal if proposal and proposal["js"].strip() else None)

    def propose(self, p, rec):
        """A behavior the deep path needs: saved for the Manager's review, never served until approved."""
        dest = BEHAVIORS / "proposed"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{p['name']}.js").write_text(f"/* {p['why']} */\n{p['js']}", encoding="utf-8")
        return self.kanban(f"Review proposed behavior: {p['name']}", "manager",
                           f"The design view (note {rec['id']}: {rec['note'][:140]}) needs a new mockup behavior "
                           f"'{p['name']}': {p['why']}\n\nFile: vault/design/behaviors/proposed/{p['name']}.js\n"
                           f"Review it for speed, safety (plain DOM; no network, storage or eval; registers "
                           f"window.__dvBehaviors[\"{p['name']}\"] = function (el, op)) and fit. Approve by moving it to "
                           f"vault/design/behaviors/{p['name']}.js; every page and note can use it from then on.")

    def card(self, rec):
        who = "designer" if rec["verdict"] == "background" else "manager"
        title = ("Design (background): " if who == "designer" else "Function change from the mockup: ") + rec["note"][:80]
        body = (f"From the design view, note {rec['id']} on screen {rec.get('route') or '#/'}.\n\nOwner's note: {rec['note']}\n"
                f"Marked: {', '.join(rec.get('marks') or []) or '-'}\nQuick judge: {rec['verdict']}: {rec['plan']}\n")
        if who == "designer":
            body += ("\nA background design job: build it in the design layer with dv.py (see your instructions), so it "
                     "streams into the owner's mockup; nothing in the app's code. Group your edits with --group <this card>.")
        return self.kanban(title, who, body)

    def kanban(self, title, who, body):
        env = dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", ""))
        env.pop("HERMES_KANBAN_BOARD", None)
        try:
            out = subprocess.run(["hermes", "kanban", "create", title, "--assignee", who, "--body", body, "--json"],
                                 capture_output=True, text=True, timeout=60, env=env)
            m = re.search(r'"(?:id|task_id)"\s*:\s*"([^"]+)"', out.stdout)
            return {"to": who, "id": m.group(1) if m else None}
        except Exception as e:
            return {"to": who, "error": str(e)[:120]}

    # ---- agreed -> built preview -> shipped ------------------------------------------------------------------------
    def agree(self):
        if self.layer.frozen:
            return {"error": "already agreed and frozen"}
        stamp = time.strftime("%Y%m%d-%H%M")
        card = self.kanban(
            f"Build the agreed design ({stamp})", "manager",
            f"The owner pressed Agreed in the design view. The design layer is frozen until it is built and shipped.\n\n"
            f"Plan the build as cards:\n"
            f"1. Designer: on a branch design/{stamp} (a worktree of ~/workspace), fold the design layer into the real front end "
            f"(frontend/): `dv.py export` prints the build sheet (tokens -> theme.css, rules -> ui.css, each simulated screen "
            f"-> screens/<route>.html and a nav link, other edits -> the screens' markup). Same look, real files, no layer.\n"
            f"2. Engineer: wire anything that must really work behind the new screens (the API, data), on the same branch.\n"
            f"3. When it is built: `dv.py preview <worktree>/frontend --branch design/{stamp}`. The owner compares Mockup and "
            f"Built in the design view and presses Ship, which merges the branch into main and empties the layer.\n"
            f"The layer stays frozen through the build: a defect anyone notices in the mockup is fixed in the build "
            f"(and listed in that card's result), never in the layer, and is not a reason for a mockup card.\n"
            f"Tester only for functional cases you write. Don't merge yourself.")
        self.layer.set_state("FROZEN", {"at": stamp, "card": card})
        self.events.send("frozen", card=card, stamp=stamp)
        return {"ok": True, "card": card, "stamp": stamp}

    def set_preview(self, d):
        folder = pathlib.Path(str(d.get("dir") or "")).expanduser().resolve()
        if HOME.resolve() not in folder.parents or not (folder / "index.html").is_file():
            return {"error": "preview needs a front-end folder (with index.html) under the project's home"}
        branch = str(d.get("branch") or "")
        if not re.fullmatch(r"[\w./-]{1,80}", branch):
            return {"error": "preview needs the branch to ship (--branch design/<stamp>)"}
        self.layer.set_state("PREVIEW", {"dir": str(folder), "branch": branch, "at": time.strftime("%Y-%m-%d %H:%M")})
        self.events.send("preview", branch=branch)
        return {"ok": True}

    def ship(self):
        pv = self.layer.state("PREVIEW")
        if not pv:
            return {"error": "nothing built to ship yet"}
        repo = HOME / "workspace"
        def git(*a):
            return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)
        r = git("merge", "--no-ff", pv["branch"], "-m", f"Ship design {pv['branch']} (owner pressed Ship in the design view)")
        if r.returncode != 0:
            git("merge", "--abort")
            card = self.kanban(f"Ship failed: merge {pv['branch']}", "manager",
                               f"The owner pressed Ship but merging {pv['branch']} into main failed:\n{(r.stdout + r.stderr)[-1500:]}\n"
                               f"Resolve it, merge, then archive the layer (POST /dv/shipped) so the mockup restarts from the app.")
            self.events.send("ship-failed", card=card)
            return {"error": "merge failed; the Manager has a card", "card": card}
        self.shipped()
        return {"ok": True}

    def shipped(self):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        agreed = self.layer.root / "agreed.md"
        with agreed.open("a", encoding="utf-8") as f:
            f.write(f"\n## Shipped {stamp}\n" + "\n".join(f"- {h['note'][:140]}" for h in self.layer.history
                                                          if h.get("verdict") not in ("ask", "frozen")) + "\n")
        self.layer.archive(stamp)
        self.events.send("reload-ops", why="shipped: the mockup now starts from the new app")

    def export(self):
        """The build sheet: the layer, grouped the way a build uses it."""
        ops = list(self.layer.ops)
        out = ["# Build sheet: the design layer to fold into the front end", ""]
        toks = [o for o in ops if o["op"] == "token"]
        if toks:
            out += ["## Theme tokens (theme.css :root)", "```css", ":root {"] + [f"  {o['name']}: {o['value']};" for o in toks] + ["}", "```", ""]
        css = [o for o in ops if o["op"] in ("css", "remove")]
        if css:
            out += ["## Rules (ui.css)", "```css"] + [o["rule"] if o["op"] == "css" else f"{o['sel']} {{ display: none; }}  /* remove */"
                                                    for o in css] + ["```", ""]
        for s in [o for o in ops if o["op"] == "screen"]:
            parts = [o["html"] for o in ops if o["op"] == "insert" and o.get("ref") == "@screen:" + s["route"]]
            out += [f"## Screen {s['route']} ({s['label']}) -> screens/{s['route'][2:] or 'home'}.html, nav link '{s['label']}'",
                    "```html"] + parts + ["```", ""]
        rest = [o for o in ops if o["op"] not in ("token", "css", "remove", "screen")
                and not (o["op"] == "insert" and str(o.get("ref", "")).startswith("@screen:"))]
        if rest:
            out += ["## Other edits (apply to the markup they name; behaviors become real code)", "```"]
            out += [json.dumps({k: v for k, v in o.items() if k not in ("id", "note")}) for o in rest] + ["```"]
        return "\n".join(out) + "\n"

    def watch_app(self):
        """Tell the page when the app's own files change (the Engineer committed), so it reloads."""
        def stamp():
            try:
                return max((p.stat().st_mtime for p in self.app_dir.rglob("*") if p.is_file()), default=0)
            except OSError:
                return 0
        last = stamp()
        while True:
            time.sleep(1.0)
            now = stamp()
            if now != last:
                last = now
                self.events.send("app-changed")


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body)
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ValueError("too big")
            return json.loads(self.rfile.read(n) or b"{}")

        def file(self, base, rel, inject=False):
            p = (base / rel).resolve()
            if base.resolve() not in p.parents and p != base.resolve():
                return self.send(404, {"error": "not found"})
            if p.is_dir():
                p = p / "index.html"
            if not p.is_file():
                return self.send(404, {"error": "not found"})
            data = p.read_bytes()
            if p.name == "index.html" and inject:
                tag = b'<script src="/dv/behaviors.js"></script><script src="/dv/layer.js"></script>'
                data = data.replace(b"</head>", tag + b"</head>", 1) if b"</head>" in data else tag + data
            self.send(200, data, TYPES.get(p.suffix.lower(), "application/octet-stream"))

        def api_path(self):
            return re.sub(r"[^\w/.-]", "", self.path.split("?")[0][len("/api/"):]).strip("/").replace("..", "")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                html = (ASSETS / "shell.html").read_text(encoding="utf-8").replace("{{PROJECT}}", app.project)
                return self.send(200, html, TYPES[".html"])
            if path.startswith("/dv/") and path[4:] in ("shell.js", "layer.js", "shell.css"):
                return self.file(ASSETS, path[4:])
            if path == "/dv/behaviors.js":
                js = (ASSETS / "behaviors.js").read_text(encoding="utf-8")
                for p in approved_behaviors():
                    js += f"\n/* approved: {p.name} */\n" + p.read_text(encoding="utf-8", errors="replace")
                return self.send(200, js, TYPES[".js"])
            if path == "/dv/ops":
                with app.layer.lock:
                    return self.send(200, {"ops": app.layer.ops, "options": app.layer.options, "config": app.layer.config(),
                                           "frozen": app.layer.state("FROZEN"), "preview": app.layer.state("PREVIEW"),
                                           "v": app.layer.version})
            if path == "/dv/version":
                return self.send(200, {"v": app.layer.version})
            if path == "/dv/map":
                r = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("route", ["#/"])[0]
                return self.send(200, {"route": r, "map": app.maps.get(r), "routes": sorted(app.maps)})
            if path == "/dv/report":
                ids = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("ids", [""])[0].split(",")
                return self.send(200, {i: app.reports.get(i) for i in ids if i})
            if path == "/dv/export":
                return self.send(200, app.export(), "text/markdown; charset=utf-8")
            if path == "/preview" or path.startswith("/preview/"):
                pv = app.layer.state("PREVIEW")
                if not pv:
                    return self.send(404, {"error": "nothing built yet"})
                return self.file(pathlib.Path(pv["dir"]), path[9:] or "index.html")
            if path == "/dv/status":
                return self.send(200, dict(app.status, notes=app.layer.history[-10:], queued=app.notes.qsize()))
            if path == "/dv/events":
                q = app.events.add()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(b"data: {\"type\":\"hello\"}\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            msg = q.get(timeout=15)
                            self.wfile.write(f"data: {msg}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    app.events.drop(q)
                self.close_connection = True
                return
            if path == "/app" or path.startswith("/app/"):
                return self.file(app.app_dir, path[5:] or "index.html", inject=True)
            if path.startswith("/api/"):
                key = self.api_path()
                if key in app.mem:
                    return self.send(200, app.mem[key])
                for base in (app.layer.root / "data", app.layer.root / "snapshot"):
                    p = base / (key + ".json")
                    if p.is_file():
                        return self.send(200, p.read_bytes())
                return self.send(404, {"error": f"no mock data for {key}"})
            if path == "/favicon.ico":
                return self.send(204, b"", "image/x-icon")
            return self.send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                d = self.body()
            except ValueError:
                return self.send(400, {"error": "bad json"})
            if path == "/dv/note":
                text = str(d.get("note") or "").strip()
                if not text:
                    return self.send(400, {"error": "empty note"})
                nid = app.layer.note_id()
                app.notes.put({"id": nid, "text": text[:2000], "marks": (d.get("marks") or [])[:6],
                               "map": str(d.get("map") or ""), "route": str(d.get("route") or "#/")})
                waiting = app.notes.qsize() - (0 if app.status["busy"] else 1)
                app.events.send("received", note=nid, text=text[:140], queued=max(0, waiting))
                return self.send(200, {"id": nid, "queued": max(0, waiting)})
            if path == "/dv/map":
                app.maps[str(d.get("route") or "#/")[:100]] = str(d.get("map") or "")[:20000]
                return self.send(200, {"ok": True})
            if path == "/dv/report":                                 # the open page: how each edit fared
                for k, v in (d.get("statuses") or {}).items():
                    app.reports[str(k)[:20]] = {"status": str(v)[:120], "route": str(d.get("route") or "")[:100], "t": time.time()}
                return self.send(200, {"ok": True})
            if path == "/dv/op":
                # Direct edits: one from the toolbar (Move, Text), or a batch from the Designer (dv.py apply), whose
                # edits share one note per card (--group) so they undo together. No model involved.
                if app.layer.frozen:
                    return self.send(409, {"error": "the mockup is frozen while the agreed design is built"})
                raw = d.get("ops") if isinstance(d.get("ops"), list) else [d.get("op") or {}]
                try:
                    checked = [check_op(o) for o in raw]
                except ValueError as e:
                    return self.send(400, {"error": str(e)})
                label = str(d.get("label") or checked[0]["op"])[:200]
                group = re.sub(r"[^\w-]", "", str(d.get("group") or ""))[:40]
                rec = app.groups.get(group) if group else None
                fresh = rec is None
                if fresh:
                    rec = app.layer.new_note(label, [], str(d.get("route") or ""))
                    rec["verdict"], rec["plan"] = ("background" if group else "direct"), label
                    if group:
                        rec["card"] = group
                        app.groups[group] = rec
                done = []
                for op in checked:
                    op = app.layer.add(op, rec)
                    done.append(op)
                    if op["op"] == "undo":
                        app.events.send("reload-ops", why="undo")
                    else:
                        app.events.send("op", note=rec["id"], op=op, s=0)
                if fresh:
                    app.layer.finish(rec)
                app.events.send("done", note=rec["id"], verdict=rec["verdict"], plan=label, edits=len(done), s=0)
                return self.send(200, {"note": rec["id"], "ops": [o["id"] for o in done]})
            if path == "/dv/agree":
                return self.send(200, app.agree())
            if path == "/dv/unfreeze":
                app.layer.set_state("FROZEN", None)
                app.layer.set_state("PREVIEW", None)
                app.events.send("reload-ops", why="unfrozen")
                return self.send(200, {"ok": True})
            if path == "/dv/preview":
                r = app.set_preview(d)
                return self.send(400 if "error" in r else 200, r)
            if path == "/dv/ship":
                r = app.ship()
                return self.send(409 if "error" in r else 200, r)
            if path == "/dv/shipped":                                # after a Manager resolved a failed merge
                app.shipped()
                return self.send(200, {"ok": True})
            if path == "/dv/undo":
                ids = d.get("notes") or ([app.layer.last_note_with_ops()] if d.get("last") else [])
                ids = [i for i in ids if i]
                if not ids:
                    return self.send(200, {"undone": []})
                app.layer.undo_notes(ids)
                app.events.send("reload-ops", why=f"undid {', '.join(ids)}")
                return self.send(200, {"undone": ids})
            if path == "/dv/pick":
                ok = app.layer.pick(str(d.get("set")), str(d.get("choice")))
                if ok:
                    rec = app.layer.new_note(f"picked option {d.get('choice')} of {d.get('set')}", [], "")
                    rec["verdict"], rec["plan"] = "pick", f"option {d.get('choice')} of {d.get('set')} folded in"
                    app.layer.finish(rec)
                app.events.send("reload-ops", why="picked an option")
                return self.send(200 if ok else 404, {"ok": ok})
            if path.startswith("/api/"):                             # a mock write: kept in memory, echoed back
                key = self.api_path()
                cur = app.mem.get(key)
                if cur is None:
                    p = app.layer.root / "data" / (key + ".json")
                    cur = json.loads(p.read_text()) if p.is_file() else None
                if isinstance(cur, list):
                    item = dict(d, id=d.get("id") or f"mock-{int(time.time() * 1000)}")
                    app.mem[key] = cur + [item]
                    return self.send(200, item)
                app.mem[key] = d
                return self.send(200, d)
            return self.send(404, {"error": "not found"})

        do_PUT = do_POST
        do_PATCH = do_POST

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--app", required=True, help="the app's front-end folder")
    ap.add_argument("--layer", required=True, help="the design layer folder")
    ap.add_argument("--bind", default="0.0.0.0")
    a = ap.parse_args()
    app = App(a)
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(app))
    srv.daemon_threads = True
    print(f"design view for {a.project} on {a.bind}:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
