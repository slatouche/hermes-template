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
ASSETS = pathlib.Path(os.environ.get("DV_ASSETS") or HOME / ".hermes" / "design-view")   # a test copy can bring its own
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}

RULES = """You change how a live web app looks while its owner watches. Answer in lines and nothing else.

First the plan: split the note into parts, one line each, then a line END.
PART 1 <quick|options|screen|background|function|review|ask> | <one short line for the owner: what you'll do>
PART 2 ...
END
Splitting: one part per separate ask; asks about the same element or area are one part; a note with one ask is one
part; at most 5 parts. Kinds:
- quick: a visible change you can make now with the edits below (style, spacing, colour, move, text, add or repeat
  elements, placeholder content, a ready-made behavior, undo of named notes). A small taste remark ("a bit warmer",
  "tighter") is quick: make your best call.
- options: the owner asks for choices ("options", "try some", "which"), or a big matter of taste with several good
  answers (a whole new look for something).
- screen: a new screen or panel that doesn't exist yet.
- background: interaction work no ready-made behavior covers (custom animation choreography, multi-step flows, new
  kinds of widget).
- function: it needs real behaviour or data (parsing, saving, importing, accounts). The plan line is for the Manager.
- review: the note asks a question about what's on the page ("why is there…", "should this…", "does this make
  sense?"). That is the owner asking you to judge it: think about whether it's right, what should be there instead,
  and change it if it isn't. Never do a review part yourself here; it is thought through separately.
- ask: you can't tell what they want (e.g. a bare "undo"). The plan line is one short question; when there are a
  few clear answers, add them after it, each after " :: " (e.g. "Which one should go? :: the toolbar button :: the
  nav link"). The owner's answer comes back as a new note with your question and their original note.

Then the work, under END:
- the edits for every quick part, one per line, in order;
- only if the note is a single part of kind options or screen, do it here:
  options: a line OPTION A <short name>, its edits, then OPTION B, OPTION C (each set stands alone);
  screen: a line SCREEN #/<route> <menu label>, then insert edits with "ref":"@screen" (into the new screen) building
  it top to bottom, a section per insert, using the app's classes; plus a link edit for whatever opens it;
- nothing for any other part: those are done separately, at the same time.

Edits, each a JSON object on its own line:
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
{"op":"redo","notes":["n3"]}                                  bring back notes that were taken back
Any edit may add "on":"#/route" to apply on one screen only.
Ready-made interactions (behavior edits; quick, not background):
{"op":"behavior","name":"sortable","sel":"<the lists>","item":"<an item>"}   drag to reorder, and between all those lists
{"op":"behavior","name":"toggle","sel":"<button>","target":"<what shows>"}    click shows/hides target
{"op":"behavior","name":"dialog","sel":"<button>","target":"<hidden dialog markup>"}  click opens it as a modal
  (insert the dialog's markup first with a hidden attribute; give its close button data-close)
{"op":"behavior","name":"tabs","sel":"<the tab row>","panels":"<the panels>"}  click a tab, see its panel
{"op":"behavior","name":"toast","sel":"<button>","text":"Saved"}             click shows a short message (simulated save)
{{EXTRA_BEHAVIORS}}
Rules: prefer token edits; one-off CSS only when the note names one element. Selectors must match the map you are
given. Markup is plain HTML with classes: no style attributes (style it with css edits), no scripts, no on* handlers,
no javascript: URLs; placeholder text and images (https://placehold.co/WxH) are fine. Where the map shows an
element's own style="...", a css edit for those properties needs !important. Do the minimum that makes the change
visible and clickable; it is a mockup."""

PART_RULES = {
    "review": "The owner asked a question about this: judge it. Think it through: is what they pointed at right for "
              "this app and its users, and if not, what should be there instead? Your FIRST line must be WHY <your judgement in "
              "one or two plain sentences, and what you are changing, or why it is fine as it is>. Then the edits that "
              "carry it out (none if it is fine). No plan, no END.",
    "options": "Do only this part now: give 3 choices. A line OPTION A <short name>, its edits, then OPTION B and OPTION "
               "C; each set stands alone and touches only what this part is about. No plan, no END.",
    "screen": "Do only this part now: a line SCREEN #/<route> <menu label>, then insert edits with \"ref\":\"@screen\" "
              "building it top to bottom, a section per insert, using the app's classes; plus a link edit for whatever "
              "opens it. No plan, no END.",
}

UNSAFE_HTML = re.compile(r"<\s*(script|iframe|object|embed|link|meta|base)\b|javascript:|\son[a-z]+\s*=", re.I)
UNSAFE_CSS = re.compile(r"</|javascript:|@import|expression\(|behavior:", re.I)


def check_op(op):
    """A safe, well-formed edit or a ValueError saying why not."""
    if not isinstance(op, dict) or not isinstance(op.get("op"), str):
        raise ValueError("not an edit")
    k = op["op"]
    need = {"token": ("name", "value"), "css": ("rule",), "move": ("sel", "where", "ref"), "text": ("sel", "text"),
            "insert": ("where", "ref", "html"), "attr": ("sel", "name", "value"), "repeat": ("sel",),
            "remove": ("sel",), "screen": ("route", "label"), "undo": ("notes",), "redo": ("notes",), "link": ("sel", "to"),
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
    if k in ("undo", "redo") and not (isinstance(op["notes"], list) and all(re.fullmatch(r"n\d+", str(n)) for n in op["notes"])):
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
        self.undone = self._read("undone.jsonl")
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
                self._take_back(op["notes"])
            elif op["op"] == "redo":
                self._bring_back(op["notes"])
            else:
                self.ops.append(op)
            note["ops"].append(op["id"])
            self._save()
            return op

    # Undo keeps what it took away (undone.jsonl, newest last), so redo can put exactly those edits back.
    def _take_back(self, ids):
        ids = [i for i in ids if any(o.get("note") == i for o in self.ops)]
        for i in ids:
            self.undone.append({"note": i, "ops": [o for o in self.ops if o.get("note") == i], "at": time.strftime("%H:%M:%S")})
        self.undone = self.undone[-50:]
        self.ops = [o for o in self.ops if o.get("note") not in set(ids)]
        self._save_undone()
        return ids

    def _bring_back(self, ids):
        back = [u for u in self.undone if u["note"] in set(ids)]
        self.undone = [u for u in self.undone if u not in back]
        for u in back:
            self.ops.extend(u["ops"])
        self._save_undone()
        return [u["note"] for u in back]

    def _save_undone(self):
        tmp = self.root / "undone.jsonl.tmp"
        tmp.write_text("".join(json.dumps(u) + "\n" for u in self.undone), encoding="utf-8")
        tmp.replace(self.root / "undone.jsonl")

    def undo_notes(self, ids):
        with self.lock:
            done = self._take_back(ids)
            self._save()
            return done

    def redo_notes(self, ids=None):
        """Bring back taken-back notes (the most recent undo when none are named)."""
        with self.lock:
            ids = ids or ([self.undone[-1]["note"]] if self.undone else [])
            done = self._bring_back(ids)
            self._save()
            return done

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

    def new_option_set(self, note, sid=None, about=None):
        """A new choice on show. Sets from earlier notes that were never picked go: the switcher is only ever for
        what's happening now (a note's own parts may each have a set, and those stay together)."""
        with self.lock:
            sid = sid or note["id"]
            for old in [k for k in self.options if k != note["id"] and not k.startswith(note["id"] + "-")]:
                self.options.pop(old)
            self.options[sid] = {"note": about or note["note"], "choices": {}}
            self._save()
            return sid

    def add_choice(self, sid, letter, name):
        with self.lock:
            self.options[sid]["choices"][letter] = {"name": name, "ops": []}
            self._save()

    def discard(self, sid):
        """None of these: the set goes, nothing from it stays."""
        with self.lock:
            gone = self.options.pop(sid, None)
            self._save()
            return bool(gone)

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
        """Live: the layer's edits, options and notes go to archive/<stamp>/ and the layer starts clean."""
        with self.lock:
            dest = self.root / "archive" / stamp
            dest.mkdir(parents=True, exist_ok=True)
            for name in ("ops.jsonl", "options.json", "history.jsonl", "undone.jsonl", "FROZEN"):
                if (self.root / name).exists():
                    (self.root / name).replace(dest / name)
            self.ops, self.options, self.history, self.undone = [], {}, [], []
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

    def send(self, event_type, /, **data):
        msg = json.dumps(dict(data, type=event_type, t=round(time.time(), 3)))
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


def behavior_check(path, name):
    """behavior-check.py's verdict on a proposed behavior, as a dict (ok, fails, notes)."""
    try:
        r = subprocess.run([sys.executable, str(HOME / ".hermes" / "scripts" / "behavior-check.py"), str(path), "--name", name,
                            "--json"], capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"behavior-check didn't run: {e}"}


def behavior_card(name, why, rec, rep):
    """The Manager's card for a behavior that passed the script: what's left is whether it fits."""
    src = f"note {rec['id']}: {rec['note'][:140]}" if rec else "the Designer"
    return (f"A new mockup behavior '{name}' from {src}: {why}\n\nFile: vault/design/behaviors/proposed/{name}.js\n"
            f"behavior-check.py passed it: plain DOM only (no network, storage, eval, navigation; none reached at runtime "
            f"either), registers itself, sets up without errors" + (f" ({'; '.join(rep.get('notes') or [])})" if rep.get("notes") else "")
            + ".\n\nWhat's left is judgement, a minute's read: does it do what the note needs, and is it a reusable "
            f"interaction rather than a one-off? Yes: `dv.py approve {name}` (every note can use it from then on). "
            f"No: `dv.py reject {name} \"<why>\"`. Shape: quick. Review: none.")


def approved_behaviors():
    """Behaviors the Manager approved: vault/design/behaviors/<name>.js (proposals wait in proposed/)."""
    return sorted(p for p in BEHAVIORS.glob("*.js") if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,40}", p.stem))


def first_comment(p):
    m = re.search(r"/\*\s*(.*?)(?:\*/|\n)", p.read_text(encoding="utf-8", errors="replace"))
    return (m.group(1).strip() if m else "")[:140]


ANSWER_RULES = """You are the designer of a live web app, answering the owner's question about it. Nothing on the page
changes: you only answer. Think it through, then write a short, plain answer (at most 6 lines, no headings, no
markdown lists longer than 4 items). If there are changes worth making, end with up to 3 lines, each:
SUGGEST <a note the owner could send to make that change, written as the owner would write it>"""

DEEP_RULES = """
## This note needs more than a quick change: you have time to think it through
The plan called it background work. Build that part now, as edits (no plan, no END this time): every
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
        self.pending = {}                   # note id -> the designer's open question about it
        self.status = {"busy": None, "queued": 0}
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.watch_app, daemon=True).start()
        self.build = {}
        threading.Thread(target=self.watch_build, daemon=True).start()

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
        undo, redo = n.get("undo"), n.get("redo")
        line = lambda h: f'{h["id"]}: {h["note"][:160]} -> {h.get("verdict")}: {(h.get("plan") or "")[:100]}'
        if undo:
            # Only what is still on the page can be taken back: two lists, so "the last 3" counts the right notes.
            live = {o.get("note") for o in self.layer.ops}
            showing = [h for h in self.layer.history if h["id"] in live][-20:][::-1]
            notes = ("Changes still on the page, newest first (only these can be undone; \"the last N\" means 1 to N of "
                     "this list):\n" + ("\n".join(f"{i}. {line(h)}" for i, h in enumerate(showing, 1)) or "(none)"))
        elif redo:
            byid = {h["id"]: h for h in self.layer.history}
            back = [byid[u["note"]] for u in self.layer.undone if u["note"] in byid][-20:][::-1]
            notes = ("Changes that were taken back, newest first (only these can be brought back; \"the last N\" means 1 "
                     "to N of this list):\n" + ("\n".join(f"{i}. {line(h)}" for i, h in enumerate(back, 1)) or "(none)"))
        else:
            notes = "\n".join(map(line, self.layer.history[-6:])) or "(none)"
        def mark(m):
            if m.get("kind") == "area":
                return (f'- an area the owner drew ({m.get("rect")}), inside {m.get("sel")}; it covers: '
                        f'{", ".join((m.get("inside") or [])[:12]) or "-"}')
            if m.get("kind") == "arrow":
                return f'- an arrow the owner drew from {m.get("from")} to {m.get("to")} (usually: move the first there)'
            return f'- {m.get("sel")}\n  html: {(m.get("html") or "")[:600]}\n  styles: {m.get("styles") or ""}'
        marks = "\n".join(mark(m) for m in n.get("marks") or []) or "(none)"
        # The page's latest map of this screen, not the one from when the note was sent: a note that waited in the
        # queue sees what the notes before it changed.
        page = self.maps.get(n.get("route") or "#/") or n.get("map") or ""
        what = (f"Note {n['id']} is an UNDO request: take back what the owner names, as one quick part. Whole notes: an "
                f"undo edit with their ids (\"the last 3\" = items 1 to 3 of the list). Part of a note (\"put the "
                f"button back\"): edits that restore just that. Owner: {n['text'] or 'the last note'}") if undo \
            else (f"Note {n['id']} is a REDO request: bring back what the owner names, as one quick part: a redo edit "
                  f"{{\"op\":\"redo\",\"notes\":[...]}} with ids from the list. Owner: {n['text'] or 'the last undo'}") if redo \
            else f"Note {n['id']}: {n['text']}"
        return (f"Screen: {n.get('route') or '#/'}\nMap of the screen:\n{page[:9000]}\n\n"
                f"Marked:\n{marks}\n\nNotes so far:\n{notes}\n\n{what}")

    # ---- the quick path ----------------------------------------------------------------------------------------
    def worker(self):
        while True:
            n = self.notes.get()
            self.status["queued"] = self.notes.qsize()
            self.status["busy"] = n["id"]
            try:
                (self.run_answer if n.get("ask") else self.run_note)(n)
            except Exception as e:                                      # a failed note never stops the worker
                self.events.send("error", note=n["id"], message=f"{type(e).__name__}: {str(e)[:200]}")
            self.status["busy"] = None

    def run_note(self, n):
        """One note: a single call that plans first (its parts, each with a kind) and then streams the edits for the
        quick parts. The moment the plan is in, every other part starts at the same time on its own: options and new
        screens as their own calls, background work on the deep path, function changes as Manager cards. Then the
        check: quick edits the page says didn't take get one repair call. One note, one record, one "done"."""
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
        said, main_ids, threads, cards = [], [], [], []
        tally = {"edits": 0, "refused": [], "usage": []}
        tlock = threading.Lock()

        def add_up(e, r, u):
            with tlock:
                tally["edits"] += e
                tally["refused"] += r
                tally["usage"].append(u or {})

        def on_plan(parts):
            rec["parts"] = [{k: p[k] for k in ("k", "kind", "text")} for p in parts]
            rec["verdict"] = parts[0]["kind"] if len(parts) == 1 else "mixed"
            rec["plan"] = parts[0]["text"] if len(parts) == 1 else " · ".join(f"{p['kind']}: {p['text']}" for p in parts)
            el = round(time.monotonic() - t0, 2)
            self.events.send("plan", note=n["id"], parts=rec["parts"], s=el)
            self.events.send("verdict", note=n["id"], verdict=rec["verdict"], plan=rec["plan"], s=el)
            inline = len(parts) == 1 and parts[0]["kind"] in ("options", "screen")
            for p in parts:
                if p["kind"] == "quick" or inline:
                    continue
                if p["kind"] == "function":
                    c = self.card(rec, p)
                    cards.append(c)
                    self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="card", card=c,
                                     s=round(time.monotonic() - t0, 2))
                elif p["kind"] == "ask":
                    q, *choices = [x.strip() for x in p["text"].split("::")]
                    choices = [c for c in choices if c][:5]
                    # Remembered until answered: the answer goes back with the question and the original note.
                    self.pending[n["id"]] = {"question": q, "choices": choices, "note": n["text"],
                                             "marks": n.get("marks") or [], "route": n.get("route") or "#/"}
                    self.events.send("question", note=n["id"], question=q, choices=choices, about=n["text"][:200])
                    self.events.send("part", note=n["id"], k=p["k"], kind="ask", state="asked", text=q,
                                     s=round(time.monotonic() - t0, 2))
                else:
                    th = threading.Thread(target=self.run_part, args=(mc, rec, n, t0, p, parts, add_up, cards), daemon=True)
                    th.start()
                    threads.append(th)

        e, r, u, _ = self.consume(stream_lines(mc, msgs, session=f"dv-{self.project}"), rec, n, t0, said=said,
                                  on_plan=on_plan, got=main_ids)
        add_up(e, r, u)
        if main_ids:
            # The check: the owner's open page measured each quick edit. Edits that matched nothing on this screen,
            # or were beaten by an element's own style attribute, get one repair call in the same note.
            bad = self.not_landed(main_ids, n.get("route") or "#/")
            if bad:
                self.events.send("part", note=n["id"], k=0, kind="check", state="fixing",
                                 text=f"{len(bad)} edit(s) didn't take; fixing", s=round(time.monotonic() - t0, 2))
                why = "\n".join(f"- {json.dumps({k: v for k, v in o.items() if k not in ('id', 'note')})[:300]}\n  -> {st}"
                                for o, st in bad)
                fix = msgs + [{"role": "assistant", "content": "\n".join(said)},
                              {"role": "user", "content": "Checked on the owner's page, these edits didn't take effect:\n" + why +
                               "\nReplace them now with edits that will work. An element's own style attribute beats any css "
                               "rule: add !important to those declarations (or change the attribute). A selector that matches "
                               "nothing: use one from the map. Edits only, no plan."}]
                e, r, u, _ = self.consume(stream_lines(mc, fix, session=f"dv-{self.project}"), rec, n, t0, mode="edits")
                add_up(e, r, u)
                rec["repaired"] = len(bad)
        for th in threads:
            th.join(timeout=300)
        usage = {k: sum((x.get(k) or 0) for x in tally["usage"]) for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens")}
        rec["s"] = round(time.monotonic() - t0, 2)
        rec["tokens"] = {"in": usage["prompt_tokens"], "cached": usage["prompt_cache_hit_tokens"], "out": usage["completion_tokens"]}
        rec["refused"] = tally["refused"]
        if not tally["edits"] and rec.get("verdict") in (None, "quick"):
            rec["said"] = "\n".join(said)[:2000]                    # a quick note that changed nothing: keep why
        rec["verdict"] = rec["verdict"] or "quick"
        if cards:
            rec["cards"] = cards
        self.layer.finish(rec)
        self.events.send("done", note=n["id"], verdict=rec["verdict"], plan=rec["plan"], edits=tally["edits"],
                         refused=tally["refused"], card=cards[0] if len(cards) == 1 else None, cards=cards,
                         s=rec["s"], tokens=rec["tokens"])

    def run_answer(self, n):
        """The Ask button: the designer's answer to a question, with suggestions the owner can send as notes. Nothing
        on the page changes."""
        mc = model_config()
        if not mc:
            raise RuntimeError("no model config/key for the design view")
        rec = self.layer.new_note(n["text"], n.get("marks"), n.get("route"), nid=n["id"])
        rec["verdict"], t0 = "answer", time.monotonic()
        self.events.send("doing", note=n["id"], text=n["text"][:140])
        msgs = [{"role": "system", "content": self.pack().replace(RULES.split("\n\nEdits, each")[0], ANSWER_RULES)},
                {"role": "user", "content": self.ask(n)}]
        lines, sugg, usage = [], [], {}
        for kind, val in stream_lines(mc, msgs, session=f"dv-{self.project}-deep", max_tokens=6000, thinking=True):
            if kind == "usage":
                usage = val
                continue
            if val.upper().startswith("SUGGEST "):
                sugg.append(val[8:].strip()[:200])
            else:
                lines.append(val)
            self.events.send("answer", note=n["id"], title="Answer", text="\n".join(lines), suggest=sugg, kind="answer",
                             s=round(time.monotonic() - t0, 2))
        rec["answer"], rec["suggest"], rec["plan"] = "\n".join(lines), sugg, (lines[0] if lines else "")[:200]
        rec["s"] = round(time.monotonic() - t0, 2)
        rec["tokens"] = {"in": usage.get("prompt_tokens"), "cached": usage.get("prompt_cache_hit_tokens"), "out": usage.get("completion_tokens")}
        self.layer.finish(rec)
        self.events.send("done", note=n["id"], verdict="answer", plan="answered (see the panel)", edits=0, s=rec["s"],
                         tokens=rec["tokens"])

    def run_part(self, mc, rec, n, t0, p, parts, add_up, cards):
        """One part of a note that isn't quick, in parallel with the rest: options, a new screen, or background work
        (the deep path: thinking on, the other screens' maps)."""
        self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="doing", text=p["text"],
                         s=round(time.monotonic() - t0, 2))
        plan = "\n".join(f"PART {q['k']} {q['kind']} | {q['text']}" for q in parts)
        focus = f"\n\nThe plan for this note:\n{plan}\n\nYour part: PART {p['k']} {p['kind']} | {p['text']}\n"
        try:
            if p["kind"] == "background":
                others = "\n\n".join(f"Map of {r}:\n{m[:5000]}" for r, m in list(self.maps.items())[-5:] if r != n.get("route"))
                msgs = [{"role": "system", "content": self.pack() + DEEP_RULES},
                        {"role": "user", "content": self.ask(n) + (f"\n\nOther screens:\n{others}" if others else "") + focus}]
                e, r, u, proposal = self.consume(stream_lines(mc, msgs, session=f"dv-{self.project}-deep", max_tokens=12000,
                                                              thinking=True), rec, n, t0, mode="deep", part=p)
                if proposal:
                    cards.append(self.propose(proposal, rec))
                elif not e:
                    cards.append(self.card(rec, p))                       # it couldn't: the Designer takes it
            else:
                msgs = [{"role": "system", "content": self.pack()},
                        {"role": "user", "content": self.ask(n) + focus + PART_RULES[p["kind"]]}]
                think = p["kind"] == "review"                              # a judgement: worth the thinking time
                whys = len(rec.get("why") or [])
                e, r, u, _ = self.consume(stream_lines(mc, msgs, session=f"dv-{self.project}" + ("-deep" if think else ""),
                                                       max_tokens=8000 if think else 3000, thinking=think),
                                          rec, n, t0, mode="edits", part=p)
                if think and len(rec.get("why") or []) == whys:          # a review always says what it decided
                    self.events.send("answer", note=n["id"], title=f"Why ({p['text'][:60]})", kind="review",
                                     text=(f"Changed it ({e} edit{'s' if e != 1 else ''}); no reason was given."
                                           if e else "Looked at it and left it as it is; no reason was given."),
                                     s=round(time.monotonic() - t0, 2))
            add_up(e, r, u)
            self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="done", edits=e,
                             s=round(time.monotonic() - t0, 2))
        except Exception as ex:
            self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="failed",
                             text=f"{type(ex).__name__}: {str(ex)[:120]}", s=round(time.monotonic() - t0, 2))

    def not_landed(self, ids, route, wait=2.0):
        """The note's edits that the owner's open page (on the note's screen) says didn't take: matched nothing, or
        were beaten by an element's own style. Nothing to say when no page is open on that screen."""
        byid = {o["id"]: o for o in self.layer.ops}
        ids = [i for i in ids if i in byid]

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

    def consume(self, stream, rec, n, t0, mode="main", said=None, on_plan=None, got=None, part=None):
        """Read a model answer line by line, acting on each line as it arrives: the plan (main call: PART lines and
        END, handed to on_plan), option and screen markers, a behavior proposal (deep path), and the edits, each
        checked, stored and sent to the page. mode: main | edits (a part or a repair) | deep."""
        option, screen, edits, refused, usage, sid, proposal = None, None, 0, [], {}, None, None
        plan, planned = [], mode != "main"

        def finish_plan():
            nonlocal planned
            planned = True
            if not plan:                     # no plan line at all: a single quick part
                plan.append({"k": 1, "kind": "quick", "text": "On it."})
            if on_plan:
                on_plan(plan)
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
            if mode == "deep" and m:
                proposal = {"name": m.group(1), "why": m.group(2).strip(), "js": ""}
                continue
            if not planned:
                m = re.match(r"PART\s+(\d+)\s*[:.]?\s*<?(quick|options|screen|background|function|review|ask)>?\s*\|?\s*(.*)", line, re.I)
                if m and len(plan) < 5:
                    plan.append({"k": int(m.group(1)), "kind": m.group(2).lower(), "text": m.group(3).strip()})
                    continue
                m = re.match(r"VERDICT\s+<?(\w+)>?\s*\|?\s*(.*)", line, re.I)       # the single-verdict form still works
                if m and not plan:
                    kind_ = m.group(1).lower()
                    plan.append({"k": 1, "kind": kind_ if kind_ in ("quick", "options", "screen", "background", "function", "review", "ask")
                                 else "quick", "text": m.group(2).strip()})
                    finish_plan()
                    continue
                if line.strip().upper() == "END":
                    finish_plan()
                    continue
                finish_plan()                 # the work started without an END line
            if line.upper().startswith("WHY ") and part:
                why = line[4:].strip()
                rec.setdefault("why", []).append(why)
                self.events.send("answer", note=n["id"], title=f"Why ({part['text'][:60]})", text=why, kind="review",
                                 s=round(time.monotonic() - t0, 2))
                continue
            m = re.match(r"OPTION\s+([A-Z])\b\s*[:|-]?\s*(.*)", line)
            if m:
                if sid is None:
                    sid = self.layer.new_option_set(rec, sid=n["id"] + (f"-{part['k']}" if part else ""),
                                                    about=part["text"] if part else None)
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
            if got is not None and not option:
                got.append(op["id"])
            if op["op"] in ("undo", "redo"):
                self.events.send("reload-ops", why=f"{op['op']} {', '.join(op['notes'])}")
                continue
            self.events.send("op", note=n["id"], op=op, option=option and {"set": option[0], "choice": option[1]},
                             s=round(time.monotonic() - t0, 2))
        if not planned:
            finish_plan()
        return edits, refused, usage, (proposal if proposal and proposal["js"].strip() else None)

    def propose(self, p, rec):
        """A behavior the deep path needs: checked by script first (behavior-check.py: safe, registers, sets up fast).
        Passed: the Manager only judges fit. Failed: the Designer gets it with what failed. Never served until approved."""
        dest = BEHAVIORS / "proposed"
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"{p['name']}.js"
        f.write_text(f"/* {p['why']} */\n{p['js']}", encoding="utf-8")
        rep = behavior_check(f, p["name"])
        if not rep.get("ok"):
            f.unlink(missing_ok=True)
            return self.kanban(f"Design (background): fix behavior {p['name']}", "designer",
                               f"From the design view, note {rec['id']}: {rec['note'][:200]}\n\nThe deep path wrote a new mockup "
                               f"behavior '{p['name']}' ({p['why']}) and it failed the behavior check:\n"
                               + "\n".join(f"- {x}" for x in rep.get("fails") or [rep.get("error", "?")])
                               + f"\n\nThe code:\n```js\n{p['js'][:6000]}\n```\nFix it and `dv.py propose {p['name']} <file.js> "
                               f"\"<why>\"` (it re-checks), then use it with a behavior edit.")
        return self.kanban(f"Review proposed behavior: {p['name']}", "manager", behavior_card(p["name"], p["why"], rec, rep))

    def card(self, rec, part=None):
        kind = part["kind"] if part else rec["verdict"]
        what = part["text"] if part else rec["plan"]
        who = "designer" if kind == "background" else "manager"
        title = ("Design (background): " if who == "designer" else "Function change from the mockup: ") + (what or rec["note"])[:80]
        body = (f"From the design view, note {rec['id']} on screen {rec.get('route') or '#/'}.\n\nOwner's note: {rec['note']}\n"
                f"Marked: {', '.join(rec.get('marks') or []) or '-'}\nThis part ({kind}): {what}\n")
        if who == "designer":
            body += ("\nA background design job: build it in the design layer with dv.py (see your instructions), so it "
                     "streams into the owner's mockup; nothing in the app's code. Group your edits with --group <this card>.")
        return self.kanban(title, who, body)

    def kanban(self, title, who, body):
        if self.a.no_cards:                                       # a test copy: say what would be carded, make nothing
            return {"to": who, "id": "not-made (test copy)", "title": title[:80]}
        env = dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", ""))
        env.pop("HERMES_KANBAN_BOARD", None)
        try:
            out = subprocess.run(["hermes", "kanban", "create", title, "--assignee", who, "--body", body, "--json"],
                                 capture_output=True, text=True, timeout=60, env=env)
            m = re.search(r'"(?:id|task_id)"\s*:\s*"([^"]+)"', out.stdout)
            return {"to": who, "id": m.group(1) if m else None}
        except Exception as e:
            return {"to": who, "error": str(e)[:120]}

    # ---- agreed -> built into the main app by build.py -> live ---------------------------------------------------------
    def build_py(self, *args):
        r = subprocess.run([sys.executable, str(HOME / ".hermes" / "scripts" / "build.py"), *args],
                           capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", "")))
        if r.returncode != 0:
            raise RuntimeError((r.stdout + r.stderr).strip()[-300:])
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}

    def agree(self):
        """Agreed: the layer freezes, build.py makes the build's branch and worktree, and the Manager plans its cards.
        When they're done, build.py checks the whole build once and puts it live on the main app; then the layer is
        archived and the mockup starts from the new app (watch_build)."""
        if self.layer.frozen:
            return {"error": "already agreed and frozen"}
        stamp = time.strftime("%Y%m%d-%H%M")
        slug = f"design-{stamp}"
        if self.a.no_cards:                                       # a test copy: no branch, no card
            self.layer.set_state("FROZEN", {"at": stamp, "build": slug, "card": self.kanban("x", "manager", ""), "t": time.time()})
            self.events.send("frozen", stamp=stamp)
            return {"ok": True, "stamp": stamp, "build": slug}
        try:
            wt = self.build_py("start", slug, "--design", stamp, "--title", f"the design agreed {stamp}")["worktree"]
        except (RuntimeError, ValueError, KeyError) as e:
            return {"error": f"couldn't start the build: {e}"}
        card = self.kanban(
            f"Build the agreed design ({stamp})", "manager",
            f"The owner pressed Agreed in the design view: build this design into the main app. The design layer stays "
            f"frozen until it is live.\n\nThe build is `{slug}`: branch `design/{stamp}`, worktree `{wt}`. Plan it as "
            f"cards, each with the line `Build: {slug}` and `--workspace dir:{wt}`:\n"
            f"1. Designer: fold the design layer into the real front end in the worktree: `dv.py export` prints the build "
            f"sheet (tokens -> theme.css, rules -> ui.css, each simulated screen -> screens/<route>.html and a nav link, "
            f"other edits -> the screens' markup). Same look, real files, no layer.\n"
            f"2. Engineer: wire what must really work behind it (the API, data), in the same worktree.\n"
            f"Each card runs only its own quick checks and commits; mark the check against the running app `(live)`. "
            f"No per-card review, merge or restart: when this card and every card of the build are done, build.py checks "
            f"the whole build once (suite + every card's checks), merges it into main, restarts the app and runs the live "
            f"checks; the owner's mockup then unfreezes onto it. `Review: tester` on a card only for behaviour cases you "
            f"write (one Tester review for the whole build). A defect noticed in the frozen mockup is fixed in the build, "
            f"never in the layer. Don't merge or restart yourself. Progress: `build.py status {slug}`.")
        try:
            self.build_py("start", slug, "--plan-card", card.get("id") or "")
        except (RuntimeError, ValueError) as e:
            print(f"build {slug}: couldn't record the plan card: {e}", file=sys.stderr, flush=True)
        self.layer.set_state("FROZEN", {"at": stamp, "build": slug, "card": card, "t": time.time()})
        self.events.send("frozen", card=card, stamp=stamp)
        return {"ok": True, "card": card, "stamp": stamp, "build": slug}

    def unfreeze(self):
        """The owner stops the build (Unfreeze): nothing goes live; the branch is kept for the Manager."""
        fz = self.layer.state("FROZEN") or {}
        if self.build.get("state") == "landing":
            return {"error": "it's going live right now; wait a moment"}
        if fz.get("build") and not self.a.no_cards:
            try:
                self.build_py("abort", fz["build"], "the owner unfroze the mockup")
            except (RuntimeError, ValueError) as e:
                return {"error": f"couldn't stop the build: {e}"}
        self.layer.set_state("FROZEN", None)
        self.events.send("reload-ops", why="unfrozen")
        return {"ok": True}

    def landed(self):
        """The agreed design is live in the main app: archive the layer, and the mockup starts from the new app."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        agreed = self.layer.root / "agreed.md"
        with agreed.open("a", encoding="utf-8") as f:
            f.write(f"\n## Live {stamp}\n" + "\n".join(f"- {h['note'][:140]}" for h in self.layer.history
                                                       if h.get("verdict") not in ("ask", "frozen")) + "\n")
        self.layer.archive(stamp)
        self.events.send("live")
        self.events.send("reload-ops", why="live: the mockup now starts from the new app")
        if self.a.api_proxy:                                    # a fresh start: the new app on today's data
            self.reset_data(why="after going live")

    def reset_data(self, why="asked"):
        """Make the design copy's data the app's real data again (design-view.sh reset-data: the real data is only
        read), in the background, telling the page as it goes. One at a time."""
        if not self.a.api_proxy:
            return {"error": "this design view uses placeholder data; there's no copy to refresh"}
        if self.status.get("data") == "refreshing":
            return {"error": "already refreshing"}
        self.status["data"] = "refreshing"
        self.events.send("data", state="started", why=why)

        def run():
            t0 = time.monotonic()
            try:
                r = subprocess.run(["bash", str(HOME / ".hermes" / "scripts" / "design-view.sh"), "reset-data"],
                                   capture_output=True, text=True, timeout=3600,
                                   env=dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}"))
                ok, out = r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
            except Exception as e:
                ok, out = False, [str(e)]
            for _ in range(60):                                  # the copy's back end takes a moment to answer
                try:
                    urllib.request.urlopen(self.a.api_proxy, timeout=2)
                    break
                except urllib.error.HTTPError:
                    break
                except (urllib.error.URLError, OSError):
                    time.sleep(0.5)
            self.status["data"] = None
            self.events.send("data", state="done" if ok else "failed", text=out[0][:200], s=round(time.monotonic() - t0, 1))
            if ok:
                self.events.send("app-changed")                  # the page reloads onto the refreshed data
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

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

    def watch_build(self):
        """While the agreed design is being built: its stage and cards from build.py, sent to the page when they
        change; when it's live, the layer is archived and the mockup unfreezes onto the new app."""
        while True:
            time.sleep(5)
            fz = self.layer.state("FROZEN") if self.layer.frozen else None
            if not fz or not fz.get("build") or self.a.no_cards:
                if self.build:
                    self.build = {}
                    self.events.send("build", state=None, step="", rows=[])
                continue
            try:
                st = self.build_py("status", fz["build"], "--json")
            except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                continue
            now = {"state": st.get("state"), "step": st.get("step") or "", "rows": st.get("cards") or []}
            if now != self.build:
                self.build = now
                self.events.send("build", **now)
            if now["state"] == "live":
                self.landed()

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
                                           "frozen": app.layer.state("FROZEN"),
                                           "v": app.layer.version, "data": bool(app.a.api_proxy),
                                           "build": app.build})
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
                if app.a.api_proxy:
                    return self.proxy()
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

        def proxy(self):
            """/api/... to the design copy of the app's back end (design-view.sh up --api-cmd): any method, body and
            answer passed through as they are. It runs on a copy of the data, so writes are safe."""
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else None
            hdrs = {k: v for k, v in self.headers.items() if k.lower() in ("content-type", "accept", "range")}
            req = urllib.request.Request(app.a.api_proxy.rstrip("/") + self.path, data=data, headers=hdrs, method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    code, body, ctype = r.status, r.read(), r.headers.get("Content-Type", "application/octet-stream")
            except urllib.error.HTTPError as e:
                code, body, ctype = e.code, e.read(), e.headers.get("Content-Type", "application/json")
            except (urllib.error.URLError, OSError) as e:
                return self.send(502, {"error": f"the design copy of the back end didn't answer ({e})"})
            self.send(code, body, ctype)

        def do_DELETE(self):
            if app.a.api_proxy and self.path.startswith("/api/"):
                return self.proxy()
            return self.do_POST()

        def do_POST(self):
            path = self.path.split("?")[0]
            if app.a.api_proxy and path.startswith("/api/"):
                return self.proxy()
            try:
                d = self.body()
            except ValueError:
                return self.send(400, {"error": "bad json"})
            if path == "/dv/note":
                text = str(d.get("note") or "").strip()
                if not text:
                    return self.send(400, {"error": "empty note"})
                marks = (d.get("marks") or [])[:6]
                q = app.pending.pop(str(d.get("reply_to") or ""), None)
                if q:
                    # An answer to the designer's question: the question and the original note travel with it, and
                    # the original note's marks too, so the work carries on where it stopped.
                    text = (f"The owner's original note: {q['note']}\nYou asked: {q['question']}\nTheir answer: {text}\n"
                            f"Now do what the original note asked, using this answer.")
                    marks = marks or q["marks"]
                nid = app.layer.note_id()
                app.notes.put({"id": nid, "text": text[:3000], "marks": marks, "ask": bool(d.get("ask")), "undo": bool(d.get("undo")), "redo": bool(d.get("redo")),
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
                    if op["op"] in ("undo", "redo"):
                        app.events.send("reload-ops", why=op["op"])
                    else:
                        app.events.send("op", note=rec["id"], op=op, s=0)
                if fresh:
                    app.layer.finish(rec)
                app.events.send("done", note=rec["id"], verdict=rec["verdict"], plan=label, edits=len(done), s=0)
                return self.send(200, {"note": rec["id"], "ops": [o["id"] for o in done]})
            if path == "/dv/agree":
                return self.send(200, app.agree())
            if path == "/dv/unfreeze":
                r = app.unfreeze()
                return self.send(409 if "error" in r else 200, r)
            if path == "/dv/reset-data":                             # the toolbar's Data button
                r = app.reset_data()
                return self.send(409 if "error" in r else 200, r)
            if path == "/dv/landed":                                 # a build finished by hand (dv.py landed)
                if not app.layer.frozen:
                    return self.send(409, {"error": "nothing agreed is waiting to go live"})
                app.landed()
                return self.send(200, {"ok": True})
            if path in ("/dv/undo", "/dv/redo", "/dv/pick", "/dv/discard") and app.layer.frozen:
                return self.send(409, {"error": "the mockup is frozen while the agreed design is built"})
            if path == "/dv/undo":
                ids = d.get("notes") or ([app.layer.last_note_with_ops()] if d.get("last") else [])
                ids = [i for i in ids if i]
                if not ids:
                    return self.send(200, {"undone": []})
                ids = app.layer.undo_notes(ids)
                app.events.send("reload-ops", why=f"undid {', '.join(ids)}")
                return self.send(200, {"undone": ids})
            if path == "/dv/redo":                                   # bring back taken-back notes (the last undo by default)
                ids = app.layer.redo_notes([str(i) for i in d.get("notes") or []] or None)
                if ids:
                    app.events.send("reload-ops", why=f"redid {', '.join(ids)}")
                return self.send(200, {"redone": ids})
            if path == "/dv/discard":                                # the switcher's Discard: none of these
                ok = app.layer.discard(str(d.get("set")))
                if ok:
                    rec = app.layer.new_note(f"discarded the options of {d.get('set')}", [], "")
                    rec["verdict"], rec["plan"] = "discard", f"none of the options of {d.get('set')}"
                    app.layer.finish(rec)
                    app.events.send("reload-ops", why="options discarded")
                return self.send(200 if ok else 404, {"ok": ok})
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
    ap.add_argument("--no-cards", action="store_true", help="a test copy: never create kanban cards")
    ap.add_argument("--api-proxy", default="", help="pass /api/... to this back end (a design copy, on copied data)")
    a = ap.parse_args()
    app = App(a)
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(app))
    srv.daemon_threads = True
    print(f"design view for {a.project} on {a.bind}:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
