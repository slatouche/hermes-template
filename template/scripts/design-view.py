#!/usr/bin/python3
"""design-view.py: the owner's design view for one project, on one port (API port + 51).

  design-view.py --project <name> --port <n> --app <frontend dir> --layer <layer dir> [--bind 0.0.0.0]

What it serves:
  /            the shell: a toolbar above the app (status line, marking, options, undo)
  /app/...     the app's real front end, read from disk on every request (so Engineer changes show at once),
               with layer.js added to its index.html
  /api/...     a mock API: layer/data/<path>.json, else snapshot/<path>.json; writes are kept in memory only
  /dv/...      the toolbar's own files, the layer's edits (/dv/ops), live events (/dv/events), notes (/dv/note),
               direct edits (/dv/op), undo (/dv/undo), picking an option (/dv/pick), where the owner is (/dv/view),
               and a dry run of a note (/dv/dry-run: what it would be taken to mean and planned as; nothing changes)

The design view's eyes are its own headless browser (design-view/mirror.js, the project's Chromium), kept running
beside this server: it shows the app as the owner has it (page, window size, scroll, option, the edits so far) and
takes every picture (real screenshots) and every measurement; the owner's own page draws and measures nothing, so it
stays smooth. It stays current by itself (every edit, undo or app change reloads it) and tidies up after itself.

A note, in turn (direct model calls, thinking off; no Hermes session, so every call is the same size):
  1. What the owner means: each spot they pointed at (a mark, a drawn box, where two marks meet) as a sharp close-up
     with exactly what is drawn there as numbered entries; three looks at once say what the thing is and what's wrong
     with it, pointing at entries. Two that agree go ahead; looks that don't are put to the owner as a question.
  2. The plan: the note's parts (a change, options, a new screen, background work, a function point, an answer, ...).
  3. Each change: the elements measured, the change made from the numbers, checked up to twice (the numbers, and
     what is drawn at the spots before and after), then a final look at the result. DONE, or an ISSUE put to the
     owner like a question (more words, try again with thinking, or undo).
Options never change the mockup: each choice is its own set, checked in the headless browser. A function point (what
the app does, not how it looks) is only noted, on the running list vault/design/build-notes.md (build-notes.py), for
the Manager to plan with the owner (/dv/functions lists the open ones); background work becomes a Designer card.
The layer is the design: ops.jsonl (the edits), history.jsonl (every note and what it did, for undo), options.json
(choices on show), data/ (fill data), config.json (where screens go).
"""
import argparse
import base64
import json
import os
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = pathlib.Path.home()


def _sibling(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), pathlib.Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fnotes = _sibling("build-notes")                    # the running list of function and usage notes
ASSETS = pathlib.Path(os.environ.get("DV_ASSETS") or HOME / ".hermes" / "design-view")   # a test copy can bring its own
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}

PLAN_RULES = """You are the designer of a live web app, reading a note from its owner. A picture of their screen comes
with it; anything they marked is outlined in magenta and lettered A, B, ... (the same letters as under "Marked"), and a
sharp close-up of each spot they pointed at follows it. Use the pictures to see what they point at and what else they
mean ("the other box", "like the sidebar"); the screen map lists the real elements with their selectors. When the note
comes with what they mean already worked out (the thing, and what's wrong with it), plan from that. Plan the work; you
don't make any change here.

Split the note into parts: one per separate ask; asks about the same element or area are one part; at most 5. Kinds:
- change: anything visible to change on the page now: style, spacing, size, alignment, position, wording, adding,
  removing or repeating elements, placeholder content, a ready-made behavior, undoing or bringing back earlier notes
  ("undo the colour change"), a taste remark ("a bit warmer"), a problem they point out ("looks broken", "still
  wrong"), or a question whether something looks right ("is this aligned?": judged, and changed if it isn't).
- options: they ask for choices ("options", "try some", "which"), or a big matter of taste with several good answers.
- screen: a new screen or panel that doesn't exist yet.
- background: interaction work no ready-made behavior covers (custom animation, multi-step flows, new kinds of widget).
- function: anything about what the app does, not how it looks: something that doesn't work, real behaviour or data,
  how fast it is, remembering a place or a choice, saving, what happens when something is used, or a usage point
  inside design feedback. It is only noted for later (a build note), never mocked up. Its text IS the note: one line,
  specific enough to act on later without asking. A note with a visible change too gets both parts. "Note it" or "put
  it on the backlog" is function too.
- answer: a question that wants information or an opinion, not a change ("what font is this?"). Nothing changes.
- ask: you can't tell what they want. The text is one short question; with a few clear answers, add each after " :: ".
- prefer: a standing instruction about how you work with them ("stop explaining unless you need me"); the text is
  the instruction in their words. To remove one they gave before, the text starts with "drop:".
- ack: a reaction with nothing to do ("nice", "ok").

Answer with only this JSON, no other text:
{"parts": [{"kind": "<kind>", "text": "<one short line for the owner: what will happen>",
            "marked": ["A"],
            "target": [{"what": "<what will actually change, as you see it (often the marked thing; for a mark round a
                         whole area, the element inside it that changes)>", "selector": "<from the map, or ''>"}],
            "refers_to": [{"what": "<what it should match or behave like, or anything else it points to>",
                           "selector": "<from the map, or ''>"}],
            "work": "align|move|spacing|size|style|text|add|remove|scroll|undo|judge|other",
            "done_when": "<what must be true, measurably, when it's done: only what the note asks, in its terms ('the card
                          list's gap under the header equals the sidebar's, at rest and scrolled'); never a number or a
                          target the owner didn't give>"}]}
"marked", "target", "refers_to", "work" and "done_when" only for change parts."""


IDENTIFY = ("Answer in four labelled parts:\n"
            "THING: what do you think is the thing they are talking about? Look closely at the close-ups and at what is "
            "drawn in each. List the candidates: the things at their spots that their words could mean, quoting the "
            "entries; when they give numbers or places (\"2 lines\", \"1 on the left\"), count each candidate there. Then "
            "say which candidate fits all their words and numbers. What is between two things they marked is in the "
            "close-up of where they meet. When they ask for something to be added, the thing is the place where it "
            "should go (often empty now) and what it should match, not something already there.\n"
            "SHORT: that thing in a few words a person would use (\"the double divider between the search box and CARDS\").\n"
            "POINT: the numbered entries that are that thing (\"B|A.1, B|A.2\").\n"
            "WRONG: what is wrong with it, according to what they asked (if they ask for something new rather than point "
            "out a problem: what they want of it). One or two short lines.")


RULES = """You change how a live web app looks while its owner watches. Answer in lines and nothing else.

Edits, each a JSON object on its own line:
{"op":"token","name":"--x","value":"..."}                 change a theme token (preferred: the whole app follows)
{"op":"css","rule":"<selector> { ... }"}                     a CSS rule written with the tokens
{"op":"move","sel":"<what>","where":"before|after|into|start","ref":"<where>"}
{"op":"text","sel":"<what>","text":"<new text>"}
{"op":"insert","where":"before|after|into|start","ref":"<where>","html":"<markup>"}   into the first match of ref;
    add "each":true to put it into every match (each row of a list gets its own copy)
{"op":"attr","sel":"<what>","name":"<attribute>","value":"<value>"}
{"op":"repeat","sel":"<the list's items>","n":8,"fill":{"<part>":["text 1","text 2"],"img@src":["url 1","url 2"]}}
    one per list: the list ends up with n items (copies of its first), and fill sets each item's parts in order, one value
    per item (text, or an attribute after @); the list's real items keep their real content (their values go unused). Build one item, then repeat
    it; never insert the same item many times.
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
no javascript: URLs. Real content and pictures come from the app's own data ("The app's real data" below, and
each picture's src in the map): when the owner wants the real thing, use it, never a placeholder. Placeholder text
and images (https://placehold.co/WxH) only for what doesn't exist yet. Where the map shows an
element's own style="...", a css edit for those properties needs !important. Do the minimum that makes the change
visible and clickable; it is a mockup."""

PART_RULES = {
    "options": "Do only this part now: give 3 choices. A line OPTION A <short name>, its edits, then OPTION B and OPTION "
               "C (more when the owner asks for a range); each set stands alone and touches only what this part is "
               "about. Nothing changes outside the choices: every edit comes after an OPTION line, and what every choice "
               "needs is repeated in each. The choices are different answers to exactly what was asked (\"where could "
               "it go\": three different places; \"what colour\": three different colours), never one answer in "
               "three styles. A size: set it and release what holds "
               "the element in the same rule (min-/max- size, flex grow/shrink, grid stretch: the map shows them). A share "
               "of a picture (\"the top 55% of the card\") comes from its own shape (the map's \"image WxH\"): its box "
               "gets aspect-ratio: W / (H x share), height: auto, min-height: 0, flex: none, and the img object-fit: "
               "cover; object-position: top; e.g. the top 55% of a 488x680 picture: aspect-ratio: 488 / 374. "
               "No plan, no END.",
    "screen": "Do only this part now: a line SCREEN #/<route> <menu label>, then insert edits with \"ref\":\"@screen\" "
              "building it top to bottom, a section per insert, using the app's classes; plus a link edit for whatever "
              "opens it. No plan, no END.",
}

URGENT = re.compile(r"\b(urgent|asap|right away|straight away|immediately|blocking me|can'?t (work|use it))\b", re.I)
NOTE_IT = re.compile(r"\blog (it|this)\b|\bnote (it|this) (down|for later)\b|\b(put|add) (it|this|that) (on|to) the "
                     r"(backlog|list)\b|\bfor later\b", re.I)


ASKS_UNDO = re.compile(r"\b(undo|undid|revert|take (it |that |this )?back|taken back|put (it |that |this )?back|bring (it |that |this )?back|"
                       r"redo|go back|as it was|before (the|my) )", re.I)


def same_note(a, b):
    """Two notes saying the same thing: most of their words in common."""
    wa, wb = (set(re.findall(r"[a-z0-9]{3,}", x.lower())) for x in (a, b))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.75


CHANGE_RULES = ("Make this change now: the edits only, one JSON object per line, no plan, no END. Work from the measured "
                "numbers, not from estimates. To match something, copy the values measured on it literally (10px, "
                "rgb(11, 14, 22)): never a theme token unless the measurements show it resolves to that exact value. Where "
                "the measurements name the rule behind a difference, fix that (change or override that rule for the same "
                "elements) instead of adding something on top. For how something behaves while scrolling, copy the setup of "
                "the element it should behave like (from \"while scrolling\" in the measurements: its own scroll area with a "
                "set height, or a sticky container and its top offset); where the measurements give a recipe (\"To behave "
                "like ...\"), apply it, then make the gaps match the measured numbers. Never make a whole column or "
                "section sticky. "
                "Change only what the note is about; leave everything else as it is.")

LOOK_TOLERANCE = 1.0   # % of a screen's pixels that may differ between the build and the agreed mockup (data, a cursor)
VISUAL_FINAL = True    # the look-at-the-result check, on the headless browser's real screenshots (without one, a measured OK decides)

FINAL_RULES = ("You check a change made for the owner's note by looking at the result. The pictures are real screenshots "
               "of the screen now: picture 1 is the whole screen (the owner's marks outlined in magenta, lettered), then "
               "the pictures listed above (close-ups: A is what changed, R1, R2 what it was compared with; and the screen "
               "scrolled, when the note is about scrolling). Does the result look like what the owner asked (\"done "
               "when\")? Judge only what was asked; ignore everything else. Exact sizes, gaps and line-ups (a few px) "
               "can't be judged by eye: take them from the measurements when there are some (a gap is between elements' "
               "own edges, their border or background, not the content inside them). Judge by the pictures how it looks: "
               "colour, shape, centring, what shows and what's hidden, and anything the numbers miss. Judge scrolling "
               "only by pictures of it scrolled, or the measurements of it scrolled. Answer one line: first what you see "
               "that decides it (and why, when it isn't what was asked), then the verdict last: \"... -> MET\" or "
               "\"... -> NOT MET\".")

VERIFY_RULES = ("You just made a change for the owner's note. Below: what the note means, the measurements before and after "
                "the change, what is drawn at the spots they pointed at before and after (lines, boxes, text: compare the "
                "entries), and a picture of the screen after it. Judge by these (the gaps under the top bars as the owner "
                "sees them in each state, the differences listed, what is drawn), not by estimating from the picture or from "
                "where boxes sit (a box can sit apart from another and draw no line): is the note's "
                "\"done_when\" now true in the numbers, and did nothing else move or break? Judge only against what the note "
                "asks: never a number or a target the owner didn't give (\"the same\" is met by any equal values). First line OK or FIX <what is still wrong, "
                "quoting the numbers>. After FIX, the edits that finish it, one JSON object per line. If the numbers moved "
                "the right way, keep your approach and only adjust values; change the approach only if it made things worse.")


def point_ids(text):
    """The entries a look points at: "B|A.1, B|A.2", "A.12-A.18", "A.12–18" or "A.3, 4, 5" -> ["A.12", "A.13", ...]"""
    out, label = [], None
    for m in re.finditer(r"([A-Z](?:\|[A-Z])*)\.(\d+)(?:\s*(?:-|–|—|to)\s*(?:[A-Z](?:\|[A-Z])*\.)?(\d+))?|(?<![\w.])(\d+)(?![\w.])", text):
        if m.group(1):
            label, a = m.group(1), int(m.group(2))
            b = int(m.group(3)) if m.group(3) else a
            out += [f"{label}.{i}" for i in range(a, min(b, a + 40) + 1)]
        elif label:                                            # a bare number after one with a letter: same close-up
            out.append(f"{label}.{m.group(4)}")
    return out


def thing_of(entry):
    """Which thing an entry of "what is drawn" is, for telling whether two looks mean the same: the element, and for a
    line which way it runs (the same border listed in two close-ups, or any of seven alike drag dots, is one thing; a
    panel's side border and its bottom border are not)."""
    el = re.search(r'border of (\S+)|scrollbar of (\S+)|::\w+ of (\S+)|(?:picture|graphic) (\S+)|, in (\S+?)\)$|^(\S+?)(?: "[^"]*")?: a box', entry)
    if not el:
        return None
    name = next(g for g in el.groups() if g)
    way = re.match(r"(vertical|horizontal) line", entry)
    return (way.group(1) + " " if way else "") + name


def spots_text(zoom):
    """What is drawn at each spot the owner pointed at, as one text (from the headless browser's close-ups)."""
    return "\n\n".join(f"[{z.get('label')}: {str(z.get('what') or '')[:90]}]\n{z.get('drawn')}" for z in zoom or [] if z.get("drawn"))[:5000]


def view_of(v):
    """The owner's screen as their page reported it (window size, scroll, lists scrolled, option), cleaned. -> dict"""
    if not isinstance(v, dict):
        return {}
    num = lambda x, lo, hi: max(lo, min(hi, int(x))) if isinstance(x, (int, float)) else None
    out = {"route": str(v.get("route") or "#/")[:100], "w": num(v.get("w"), 320, 4000), "h": num(v.get("h"), 240, 3000),
           "scroll": num(v.get("scroll"), 0, 10 ** 6) or 0, "opt": str(v.get("opt") or "none")[:80],
           "scrollers": [{"sel": str(x.get("sel") or "")[:200], "top": num(x.get("top"), 0, 10 ** 6) or 0,
                          "left": num(x.get("left"), 0, 10 ** 6) or 0}
                         for x in (v.get("scrollers") if isinstance(v.get("scrollers"), list) else [])[:8] if isinstance(x, dict)]}
    return {k: x for k, x in out.items() if x is not None}


def with_image(n, text):
    """A note's message to the model, with its pictures: the whole screen (marks outlined and lettered), then a sharp
    close-up of each mark, where details too fine for the whole screen (a 1 px line, a border, a few px) show."""
    if not n.get("image"):
        return text
    zoom = [z for z in n.get("zoom") or [] if str(z.get("image") or "").startswith("data:image/")]
    legend = ("\n\nPictures: 1 = the whole screen, the marks outlined in magenta and lettered; then a close-up of each "
              "spot they pointed at, without the outline: " + "; ".join(f"{i} = {z.get('label')}: {str(z.get('what') or '')[:90]}"
                                                       for i, z in enumerate(zoom, 2)) + ".") if zoom else ""
    return ([{"type": "text", "text": text + legend}, {"type": "image_url", "image_url": {"url": n["image"]}}]
            + [{"type": "image_url", "image_url": {"url": z["image"]}} for z in zoom])


def kenv():
    """The environment for the hermes CLI: ~/.local/bin on the PATH, the default board."""
    env = dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", ""))
    env.pop("HERMES_KANBAN_BOARD", None)
    return env


NOT_A_NOTE = ("The mockup already carries every visual change into the build, so a look, layout, placement, "
              "spacing, alignment or wording is never a note, even when the owner asked for it, and nor is asking the "
              "designer for options or ideas about one (\"options for where it could go\"). A note is only what "
              "the mockup can't show: what happens when something is used (clicks, saving, data, search results, "
              "what a popup does), how the owner uses the app or moves through it, and how it should behave over "
              "time (while scrolling, as things change, how fast it should feel). Never an instruction to you about "
              "how to work, nothing about you or the notes list itself, and never something already on the list "
              "(open or done) in other words.")

NOTE_RULES = ("You check one message the owner sent their app's designer for what is worth keeping for later work: "
              "what something should do or how it should work (function), how they use the app or move through it "
              "(usage), how it should behave or feel (feel: \"should feel instant\", \"should keep my place\"). " + NOT_A_NOTE +
              " Only what they said or clearly meant. Answer only lines NOTE <function|usage|feel> | <one specific line, "
              "enough to act on later without asking>; nothing worth keeping (most messages): a single line NONE.")

SWEEP_RULES = ("You read every message the owner sent the designer in this design round, with what each one became. "
               "Find what is worth keeping for later work and is not on their notes list yet: what something should do "
               "or how it should work (function), how they use it or move through the app (usage), how it should behave "
               "or feel (feel). " + NOT_A_NOTE + " Skip questions, reactions, undos, complaints that a change didn't "
               "work, and messages marked [taken back]. Only what they said or clearly meant; merge what several "
               "messages say into one note; few notes is normal. One line each, specific enough to act on later "
               "without asking:\nNOTE <function|usage|feel> | <the note> | <the message ids it came from>\n"
               "Nothing new: a single line NONE.")


UNSAFE_HTML = re.compile(r"<\s*(script|iframe|object|embed|link|meta|base)\b|javascript:|\son[a-z]+\s*=", re.I)
UNSAFE_CSS = re.compile(r"</|javascript:|@import|expression\(|behavior:", re.I)


def why_lines(bad, oset=None):
    """What didn't take, for a repair call: each edit (with its option choice, when it has one) and what the page saw."""
    where = {o["id"]: c for c, ch in (oset or {}).get("choices", {}).items() for o in ch["ops"]}
    return "\n".join((f"- choice {where[o['id']]}: " if o["id"] in where else "- ")
                     + json.dumps({k: v for k, v in o.items() if k not in ("id", "note")})[:300] + f"\n  -> {st}" for o, st in bad)


REPAIR_RULES = ("Replace them with edits that will work. The page says what holds each one: an element's own style "
                "attribute beats any rule (add !important, or change the attribute); a size held by min-/max-height or "
                "-width, flex (grow/shrink) or a grid row is released in the same rule (e.g. min-height: 0; flex: none; "
                "align-self: start); another rule that sets the same property is beaten by a more specific selector or "
                "!important; clipped by a parent: release the parent's overflow or size, or fit inside it; hidden by a "
                "parent: show that parent or move the element out; covered: raise it (position: relative; z-index) above "
                "what covers it. A selector that matches nothing: use one from the map.")


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
        op.pop("on")                # a route with an item in it (one deck's page): the edit applies on every screen
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


AGREED_HEAD = """---
title: "Agreed designs"
type: note
status: active
owner: manager
updated: {day}
summary: "Each design the owner agreed in the design view and that went live, with its notes (written by the design view)."
tags: [design]
---
# Agreed designs
"""


def agreed_page(path):
    """agreed.md is a vault page like any other: the standard header, kept current (vault-lint checks every page)."""
    day = time.strftime("%Y-%m-%d")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text.startswith("---\n"):
        text = AGREED_HEAD.format(day=day) + ("\n" + text.lstrip("\n") if text.strip() else "")
    else:
        text = re.sub(r"^updated:.*$", f"updated: {day}", text, count=1, flags=re.M)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    quick path (twice as fast, and it judges better); the deep path turns it on. A thinking call that spends its whole
    budget thinking and answers nothing (it happens: about one in three on a hard judgement) is asked once more
    without thinking, so the part never ends empty."""
    said, usage = False, {}
    for kind, val in _stream(mc, messages, session, max_tokens, thinking):
        if kind == "usage":
            usage = val
        else:
            said = True
            yield kind, val
    if thinking and not said:
        nudge = messages + [{"role": "user", "content": "You used all your thinking time without answering. Answer now, "
                             "from what you can see, in exactly the format asked above (no plan, no PART lines)."}]
        for kind, val in _stream(mc, nudge, session, 3000, False):
            if kind == "usage":
                usage = {k: (usage.get(k) or 0) + (val.get(k) or 0) for k in ("prompt_tokens", "completion_tokens",
                                                                                "prompt_cache_hit_tokens")}
            else:
                yield kind, val
    yield "usage", usage


def _stream(mc, messages, session, max_tokens, thinking):
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



def find_chrome():
    """A Chromium for the design view's own headless browser: Hermes' (its browser tool installs one), or the system's."""
    found = sorted(HOME.glob(".hermes/tools/chromium-*/chrome-linux64/chrome"))
    return str(found[-1]) if found else next(filter(None, (shutil.which(c) for c in ("chromium", "chromium-browser", "google-chrome"))), None)


class Mirror:
    """The design view's eyes: one headless Chromium beside this server (design-view/mirror.js), kept running and showing
    the app as the owner has it (screen, window size, scroll, option, the edits so far), so every picture is a real
    screenshot, pixel-true and taken in a moment. Nothing is saved. Started on first use, and again if it stops; without
    node or a Chromium, the owner's page draws the pictures instead."""

    def __init__(self, host, port):
        self.base, self.chrome, self.node = f"http://{host}:{port}", find_chrome(), shutil.which("node")
        self.ok = bool(self.chrome and self.node and (ASSETS / "mirror.js").is_file())
        self.proc, self.lock, self.wait, self.n = None, threading.Lock(), {}, 0

    def alive(self):
        return bool(self.proc and self.proc.poll() is None)

    def stop(self):
        """Shut it down (the server is stopping): it takes its Chromium and its temporary profile with it."""
        if self.alive():
            try:
                self.proc.stdin.close()
                self.proc.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()

    def _up(self):
        if self.proc and self.proc.poll() is None:
            return self.proc
        self.proc = subprocess.Popen([self.node, str(ASSETS / "mirror.js"), self.chrome, self.base], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        return self.proc

    def _read(self, proc):
        for line in proc.stdout:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            w = self.wait.get(m.get("id"))
            if w:
                w[1] = m
                w[0].set()

    def call(self, cmd, timeout=25.0, wait=True, **args):
        """One request (see mirror.js). -> its answer, or None (not running, or no answer in time)."""
        if not self.ok:
            return None
        holder = [threading.Event(), None]
        with self.lock:
            self.n += 1
            rid = self.n
            if wait:
                self.wait[rid] = holder
            try:
                proc = self._up()
                proc.stdin.write(json.dumps({"id": rid, "cmd": cmd, **args}) + "\n")
                proc.stdin.flush()
            except OSError:
                self.proc = None
                self.wait.pop(rid, None)
                return None
        if not wait:
            return None
        holder[0].wait(timeout)
        self.wait.pop(rid, None)
        return holder[1]

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
        if (self.layer.root / "agreed.md").exists():          # an older page without the vault's header gets it
            try:
                agreed_page(self.layer.root / "agreed.md")
            except OSError:
                pass
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.watch_app, daemon=True).start()
        self.build = {}
        self.api_seen, self.api_lock = {}, threading.Lock()
        self.api_log = []                   # the last 40 API calls: what the page saw, kept with a build note
        self.page_wait = {}                 # a measure or picture request to the owner's page -> [event, result]
        self.page_seen = 0.0                # when an open page last reported in (maps, reports, replies)
        bind = getattr(a, "bind", "")
        self.mirror = Mirror("127.0.0.1" if bind in ("0.0.0.0", "", "::") else bind, getattr(a, "port", 0))
        self.last_view = {}                 # the owner's screen as last seen (window size, scroll, option)
        self.app_v = 0                      # counts the app's own changes: the headless browser then reloads too
        self.built_dir = None               # a build's front end for the look check (served at /built/)
        if self.mirror.ok:                  # the headless browser starts with the server (once it's serving) and stays up
            threading.Timer(2.0, lambda: self.mirror.call("follow", wait=False, view={"route": "#/", "key": self.mirror_key()})).start()
            threading.Thread(target=self.keep_mirror_current, daemon=True).start()
        self.recent = {}                    # the last 20 notes as sent (with their picture), for "try again"
        # The running list: vault/design/build-notes.md (a test copy keeps its own, inside its layer).
        self.notes_page = (self.layer.root if a.no_cards else self.layer.root.parent) / "build-notes.md"
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
        agreed = (re.sub(r"\A---\n.*?\n---\n", "", agreed_p.read_text(encoding="utf-8", errors="replace"), count=1, flags=re.S)[:3000]
                  if agreed_p.exists() else "(nothing agreed yet)")
        extra = "\n".join(f'{{"op":"behavior","name":"{p.stem}","sel":"..."}}   {first_comment(p)}'
                          for p in approved_behaviors())
        try:
            prefs = json.loads((self.layer.root / "prefs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prefs = []
        standing = ("\n\n## The owner's standing instructions (keep to these in every answer and edit)\n"
                    + "\n".join(f"- {x}" for x in prefs)) if prefs else ""
        try:
            open_ = fnotes.items(self.notes_page)
        except (OSError, SystemExit):
            open_ = []
        fn = ("\n\n## The owner's build notes\nEvery function part you plan is saved, as you plan it, to the owner's "
              "build notes (vault/design/build-notes.md; the toolbar's 🔧 button lists them); the Manager plans them "
              "with the owner later. You can't read more of it or change it here. Open now:\n"
              + ("\n".join(f"- {i['id']} ({i['kind']}): {i['note'][:160]}" for i in open_[-15:]) or "(none)"))
        return (RULES.replace("{{EXTRA_BEHAVIORS}}", extra) + standing + fn + self.api_pack() + "\n\n## Design brief\n" + brief + "\n\n## Agreed so far\n" + agreed +
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
            back = {u["note"] for u in self.layer.undone}
            notes = "\n".join(line(h) + (" [taken back]" if h["id"] in back else "")
                              for h in self.layer.history[-10:]) or "(none)"
        def mark(m):
            if m.get("kind") == "area":
                return (f'- an area the owner drew ({m.get("rect")}), inside {m.get("sel")}; it covers: '
                        f'{", ".join((m.get("inside") or [])[:12]) or "-"}')
            if m.get("kind") == "arrow":
                return f'- an arrow the owner drew from {m.get("from")} to {m.get("to")} (usually: move the first there)'
            return (f'- {m.get("sel")}\n  html: {(m.get("html") or "")[:600]}\n  styles: {m.get("styles") or ""}'
                    + (f'\n  measured: {m.get("facts")}' if m.get("facts") else ""))
        marks = "\n".join("- " + chr(65 + i) + ": " + mark(m)[2:] for i, m in enumerate(n.get("marks") or [])) or "(none)"
        if n.get("image"):
            marks += "\n(The picture with this note shows these marks outlined in magenta, lettered as above.)"
        hint = ""
        if not undo and not redo:
            back = {u["note"] for u in self.layer.undone}       # a note the owner took back isn't one to follow up
            prev = [h for h in self.layer.history if h["id"] != n["id"] and h["id"] not in back
                    and h.get("verdict") not in ("discard", "pick", "prefer", "answer")][-1:]
            mine = {str(m.get("sel") or "") for m in n.get("marks") or []} - {""}
            if prev:
                same = mine & {str(x) for x in prev[0].get("marks") or []}
                retry = re.search(r"\b(still|again|didn'?t work|not (fixed|working|right)|broke|worse|wrong)\b", n["text"], re.I)
                fn_prev = prev[0].get("verdict") == "function" or any(q.get("kind") == "function" for q in prev[0].get("parts") or [])
                if fn_prev and (same or retry):
                    hint = (f"\n\nThis follows {prev[0]['id']}, a function point noted for later "
                            f"({(prev[0].get('plan') or '')[:120]}). More about the same thing is a function part (noted "
                            "with the new detail); don't mock up a fix for it.")
                elif same or retry:
                    hint = (f"\n\nThis follows {prev[0]['id']} ({(prev[0].get('plan') or '')[:120]})"
                            + (" on the same element" if same else "") + (": the owner says it isn't right yet" if retry else "")
                            + ".")
            wide = [m for m in n.get("marks") or [] if m.get("kind") == "arrow"
                    or (m.get("kind") == "area" and len(m.get("inside") or []) >= 3)]
            if wide:
                hint += "\n\nThe owner drew " + ("an arrow" if wide[0].get("kind") == "arrow" else "an area over several elements") + ": a change to it usually needs working out (think)."
            if re.search(r"\bthink\b", n["text"], re.I):
                hint += "\n\nThe owner asked you to think it through."
            if NOTE_IT.search(n["text"]):
                hint += "\n\nThe owner wants this noted for later: plan it as a function part."
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
                f"Marked:\n{marks}\n\nNotes so far:\n{notes}\n\n{what}{hint}")

    # ---- the quick path ----------------------------------------------------------------------------------------
    def worker(self):
        while True:
            n = self.notes.get()
            self.status["queued"] = self.notes.qsize()
            self.status["busy"] = n["id"]
            try:
                if not n.get("image"):
                    got = self.look(n, zoom=True)
                    n["image"], n["zoom"] = got.get("image"), got.get("zoom") or []
                (self.run_answer if n.get("ask") else self.run_note)(n)
            except Exception as e:                                      # a failed note never stops the worker
                self.events.send("error", note=n["id"], message=f"{type(e).__name__}: {str(e)[:200]}")
            self.status["busy"] = None

    def run_note(self, n):
        """One note, in the design view's one flow. A picture of the owner's screen comes with it (their marks outlined).
        1. The plan (one fast call, no thinking): the note's parts, and for each change what it is about (the marked
           element, what else it refers to, the kind of work).
        2. Each change part: the owner's page measures the elements involved (inspect: exact numbers, what differs and
           the rule behind it); the change is made from those numbers; then checked up to twice (measured again, a new
           picture, the edits that didn't take and why: OK, or FIX with the edits that finish it); then a final check of
           the before and after pictures: DONE, or ISSUE, which is put to the owner like a question (more words, try
           again with thinking, or undo).
        Options, new screens, background work, answers, questions, standing instructions and build notes keep their own
        paths, in parallel. One note, one record, one "done"."""
        if self.layer.frozen:
            self.events.send("done", note=n["id"], verdict="frozen", plan="The mockup is frozen while it's built.", s=0)
            return
        mc = model_config()
        if not mc:
            raise RuntimeError("no model config/key for the design view")
        n["think"] = bool(n.get("think") or re.search(r"\bthink\b", n["text"], re.I))
        self.recent[n["id"]] = n
        for k in list(self.recent)[:-20]:
            self.recent.pop(k, None)
        rec = self.layer.new_note(n["text"], n.get("marks"), n.get("route"), nid=n["id"])
        t0 = time.monotonic()
        self.events.send("doing", note=n["id"], text=n["text"][:140])
        threads, cards, noted, finals = [], [], [], []
        tally = {"edits": 0, "refused": [], "usage": []}
        tlock = threading.Lock()

        def add_up(e, r, u):
            with tlock:
                tally["edits"] += e
                tally["refused"] += r
                tally["usage"].append(u or {})

        parts, u = self.plan(mc, n)
        add_up(0, [], u)
        rec["parts"] = [{k: p[k] for k in ("k", "kind", "text")} for p in parts]
        rec["verdict"] = parts[0]["kind"] if len(parts) == 1 else "mixed"
        rec["plan"] = parts[0]["text"] if len(parts) == 1 else " · ".join(f"{p['kind']}: {p['text']}" for p in parts)
        el = round(time.monotonic() - t0, 2)
        self.events.send("plan", note=n["id"], parts=rec["parts"], s=el)
        self.events.send("verdict", note=n["id"], verdict=rec["verdict"], plan=rec["plan"], s=el)
        th = threading.Thread(target=self.note_check, args=(mc, rec, n, parts, noted), daemon=True)   # build notes
        th.start()
        threads.append(th)
        changes = []
        for p in parts:
            if p["kind"] == "change":
                changes.append(p)
            elif p["kind"] == "function":                      # a build note, on the spot: no call, no wait
                self.note_function(rec, n, p, t0, cards, noted)
            elif p["kind"] == "ack":
                self.events.send("part", note=n["id"], k=p["k"], kind="ack", state="done", text="Noted", s=round(time.monotonic() - t0, 2))
            elif p["kind"] == "prefer":
                said_as = n["text"].strip() if re.match(r"\s*drop\s*:", n["text"], re.I) else p["text"]   # their own "drop:"
                self.events.send("part", note=n["id"], k=p["k"], kind="prefer", state="done", text=self.prefer(said_as),
                                 s=round(time.monotonic() - t0, 2))
            elif p["kind"] == "ask":
                self.ask_owner(n, p, p["text"], t0)
            else:
                th = threading.Thread(target=self.run_part, args=(mc, rec, n, t0, p, parts, add_up, cards), daemon=True)
                th.start()
                threads.append(th)
        for p in changes:                                      # one at a time: they share the owner's page
            try:
                finals.append(self.do_change(mc, rec, n, t0, p, parts, add_up))
            except Exception as ex:
                finals.append(f"ISSUE {type(ex).__name__}: {str(ex)[:120]}")
        for th in threads:
            th.join(timeout=300)
        usage = {k: sum((x.get(k) or 0) for x in tally["usage"]) for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens")}
        rec["s"] = round(time.monotonic() - t0, 2)
        rec["tokens"] = {"in": usage["prompt_tokens"], "cached": usage["prompt_cache_hit_tokens"], "out": usage["completion_tokens"]}
        rec["refused"] = tally["refused"]
        if finals:
            rec["final"] = finals
            issue = next((f for f in finals if f.upper().startswith("ISSUE")), None)
            rec["plan"] = ("⚠ " + issue[5:].strip(" :")) if issue else ("✓ " + " · ".join(f[4:].strip(" :") for f in finals))
            if issue:
                self.issue(n, issue[5:].strip(" :"))
        if cards:
            rec["cards"] = cards
        if noted:
            rec["noted"] = noted
        self.layer.finish(rec)
        self.events.send("done", note=n["id"], verdict=rec["verdict"], plan=rec["plan"], edits=tally["edits"],
                         refused=tally["refused"], card=cards[0] if len(cards) == 1 else None, cards=cards, noted=noted,
                         s=rec["s"], tokens=rec["tokens"])

    def identify(self, mc, n, looks=3):
        """What the owner means, worked out before anything is planned (their way of asking it): what is the thing
        they're talking about, and what is wrong with it according to their note. It sees the whole screen, a close-up of
        each spot they pointed at (a mark, the box they drew, where two marks meet) and, read from the page, exactly what
        is drawn in each spot as numbered entries (lines, boxes, text, icons, where they sit: the model reads that far
        better than fine pixels), and points at the entries it means.
        One look can still pick the wrong thing on an ambiguous note (n145: about 1 in 4), so it takes three looks at
        once (no slower): when two point at the same thing, that's what is meant; when they don't, it isn't clear, and
        the owner is asked which one, with the candidates as answers.
        -> {"thing", "short", "wrong"} | {"ask": [short, ...]} | {} (nothing pointed at)"""
        zoom = n.get("zoom") or []
        if not zoom or not n.get("image"):
            return {}
        t0, entries, blocks = time.monotonic(), {}, []
        for i, z in enumerate(zoom, 2):
            if not z.get("drawn"):
                continue
            head, *rest = str(z["drawn"]).split("\n")
            for j, line in enumerate(rest, 1):
                entries[f"{z.get('label')}.{j}"] = line
            blocks.append(f"[picture {i}: {z.get('label')}, {str(z.get('what') or '')[:90]}]\n{head}\n"
                          + "\n".join(f"{z.get('label')}.{j} {line}" for j, line in enumerate(rest, 1)))
        intro = (f"The owner of a web app wrote this note about their screen: \"{n['text'][:1500]}\"\n"
                 f"What they pointed at:\n" + "\n".join(f"- {chr(65 + i)}: " + ("a box they drew on the screen" if m.get("kind") == "area" else
                                                      f"an arrow from {m.get('from')} to {m.get('to')}" if m.get("kind") == "arrow" else str(m.get("sel")))
                                                      for i, m in enumerate(n.get("marks") or []))
                 + ("\n\nWhat is drawn in each close-up, read from the page (exact; px from the close-up's top-left, before "
                    "it was enlarged), as numbered entries:\n" + "\n\n".join(blocks) if blocks else ""))
        msgs = [{"role": "user", "content": with_image(n, intro + "\n\n" + IDENTIFY)}]
        done, arrived = threading.Condition(), []

        def look():
            try:
                a = "\n".join(v for k, v in stream_lines(mc, msgs, session=f"dv-{self.project}-identify", max_tokens=900) if k == "line")
            except Exception as e:                             # one look failing still leaves the others
                a = ""
                print(f"identify look failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
            with done:
                arrived.append(a)
                done.notify_all()

        def read(a):
            part = lambda name: (re.search(rf"\b{name}\W*(.*?)(?=\n\s*\W*(THING|SHORT|POINT|WRONG)\b|\Z)", a or "", re.S) or [None, ""])[1].strip()
            key = frozenset(filter(None, (thing_of(entries[x]) for x in point_ids(part("POINT")) if x in entries)))
            return {"thing": part("THING")[:1200], "short": part("SHORT")[:120], "wrong": part("WRONG")[:600], "key": key} \
                if part("THING") or part("SHORT") else None
        # Two looks agree when they point at some of the same thing, or name it in mostly the same words
        words = lambda t: set(re.findall(r"[a-z]{3,}", t.lower())) - {"the", "and", "for", "with", "that", "this", "their"}
        same = lambda a, b: bool(a["key"] & b["key"]) or \
            len(words(a["short"]) & words(b["short"])) * 2 >= max(1, len(words(a["short"]) | words(b["short"])))

        def agreed(reads):
            backed = [sum(same(r, o) for o in reads if o is not r) for r in reads]
            best = max(range(len(reads)), key=lambda i: backed[i]) if reads else None
            return reads[best] if best is not None and backed[best] >= 1 else None
        for _ in range(looks):
            threading.Thread(target=look, daemon=True).start()
        # As soon as two agree, that's it: a slow third look isn't waited for (one took 19 s). Without agreement after
        # two, the third gets a few seconds more.
        deadline, reads, got = time.monotonic() + 60, [], None
        with done:
            while True:
                reads = [r for r in map(read, arrived) if r]
                got = agreed(reads)
                if got or len(arrived) >= looks or time.monotonic() > deadline:
                    break
                if len(arrived) >= 2:
                    deadline = min(deadline, time.monotonic() + 3)
                done.wait(max(0.05, deadline - time.monotonic()))
        took = time.monotonic() - t0
        if not reads:
            return {}
        if not got and len(reads) > 1:                         # they put it differently: same thing or not? (one short call)
            got, groups = self.same_thing(mc, n, reads)
            if not got and len(groups) > 1:
                shorts = [g[0]["short"] for g in groups][:3]
                print(f"identified {n.get('id', '-')} in {time.monotonic() - t0:.1f} s: it isn't clear, asking: {shorts}", flush=True)
                return {"ask": shorts}
        r = got or reads[0]
        print(f"identified {n.get('id', '-')} in {took:.1f} s ({len(reads)} looks): {r['short']} / {r['wrong'][:150]}", flush=True)
        return {k: r[k] for k in ("thing", "short", "wrong")}

    def same_thing(self, mc, n, reads):
        """Looks that put it differently: one short text call groups them by the thing on screen they mean. Two in one
        group: that's what is meant. -> (the reading to go with or None, [groups of readings, biggest first])"""
        listed = "\n".join(f"{i}. {r['short']}: {r['thing'][-400:]}" for i, r in enumerate(reads, 1))
        out = " ".join(v for k, v in stream_lines(mc, [{"role": "user", "content":
                       f"The owner's note: \"{n['text'][:600]}\"\nThree readings of what it is about:\n{listed}\n\n"
                       "Which readings mean the same thing on the screen (the same element or the same spot, however they "
                       "put it)? Answer one line: the groups, numbers joined by + and groups split by | (\"1+3 | 2\")."}],
                       session=f"dv-{self.project}-identify", max_tokens=60) if k == "line")
        groups, seen = [], set()
        for g in re.findall(r"\d+(?:\s*\+\s*\d+)*", out):
            idx = [int(x) - 1 for x in re.findall(r"\d+", g) if 0 < int(x) <= len(reads) and int(x) - 1 not in seen]
            seen.update(idx)
            if idx:
                groups.append([reads[i] for i in idx])
        groups += [[r] for i, r in enumerate(reads) if i not in seen]
        groups.sort(key=len, reverse=True)
        return (groups[0][0] if len(groups[0]) >= 2 else None), groups

    def plan(self, mc, n):
        """The note's parts, from the note and the picture (one fast call). Unreadable: one change part with the note."""
        brief_p = HOME / "vault" / "design" / "brief.md"
        brief = brief_p.read_text(encoding="utf-8", errors="replace")[:1500] if brief_p.exists() else ""
        try:
            prefs = json.loads((self.layer.root / "prefs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prefs = []
        system = PLAN_RULES + ("\n\nThe owner's standing instructions:\n" + "\n".join(f"- {x}" for x in prefs) if prefs else "") \
            + (f"\n\nDesign brief (short):\n{brief}" if brief else "")
        out, usage = [], {}
        got = self.identify(mc, n) if n.get("identify", True) else {}
        if got.get("ask"):                                     # it isn't clear which thing they mean: ask, don't guess
            n["seen"] = "asked: " + " | ".join(got["ask"])
            return [{"k": 1, "kind": "ask", "text": "Which do you mean? :: " + " :: ".join(got["ask"])}], {}
        n["seen"] = f"{got.get('short', '')}: {got.get('wrong', '')}".strip(": ")
        meant = (f"\n\nWhat the owner means, worked out from the close-ups:\n- The thing they're talking about: {got['short']}. "
                 f"{got['thing']}\n- What is wrong with it, by their note: {got['wrong']}\nNow: what needs a fix, and how? (the plan)"
                 if got.get("thing") else "")
        for k, v in stream_lines(mc, [{"role": "system", "content": system}, {"role": "user", "content": with_image(n, self.ask(n) + meant)}],
                                 session=f"dv-{self.project}-plan", max_tokens=1500):
            if k == "line":
                out.append(v)
            else:
                usage = v
        text = "\n".join(out)
        m = re.search(r"\{.*\}", text, re.S)
        try:
            got = json.loads(m.group(0)) if m else {}
        except ValueError:
            got = {}
        kinds = ("change", "options", "screen", "background", "function", "answer", "ask", "prefer", "ack")
        parts = []
        for i, q in enumerate((got.get("parts") or [])[:5], 1):
            if isinstance(q, dict) and q.get("kind") in kinds:
                parts.append({"k": i, "kind": q["kind"], "text": str(q.get("text") or "")[:300], "marked": q.get("marked") or [],
                              "target": [r for r in q.get("target") or [] if isinstance(r, dict)][:3],
                              "refers_to": [r for r in q.get("refers_to") or [] if isinstance(r, dict)][:4], "work": q.get("work") or "",
                              "done_when": str(q.get("done_when") or "")[:300]})
        return parts or [{"k": 1, "kind": "change", "text": n["text"][:200], "marked": [], "refers_to": [], "work": "other"}], usage

    def look(self, n, close=None, scrolled=None, zoom=False):
        """A real screenshot of the owner's screen as they had it for this note (the headless browser: same page, window
        size, scroll and option, with the edits as they are now), their marks outlined and lettered; on request a sharp
        close-up of each element in a spec, and the screen scrolled. The owner's page never draws one (it froze it for
        seconds). Tried twice; without it the note still goes, on its words, marks and measurements. Each picture is
        logged (journal): where it came from and how long it took. -> {"image", "close": [...], "scrolled": [...]} or {}"""
        t = time.monotonic()
        for _ in (1, 2):
            got = self.mirror.call("shot", view=self.view_for(n), marks=n.get("marks") or [], close=close, scrolled=scrolled,
                                   zoom=zoom)
            if got and got.get("image"):
                print(f"picture {n.get('id', '-')}: headless {got.get('ms')} ms, {len(got.get('zoom') or [])} of the marks, "
                      f"{len(got.get('close') or [])} close-ups, "
                      f"{len(got.get('scrolled') or [])} scrolled" + (f", not on screen: {got['missing']}" if got.get("missing") else ""), flush=True)
                return got
        print(f"picture {n.get('id', '-')}: NONE after {time.monotonic() - t:.1f} s ({(got or {}).get('error') or 'no answer'})", flush=True)
        return {}

    def view_for(self, n):
        """The owner's screen for this note, for the headless browser: their view, the note's page, the edits as now."""
        return dict(n.get("view") or self.last_view or {}, route=n.get("route") or "#/", key=self.mirror_key())

    def mirror_key(self):
        """What the headless browser's page is made of: the edits, the app's own files, the design view's scripts and the
        approved behaviors. When it changes, the page is loaded fresh."""
        try:
            own = max((f.stat().st_mtime for d in (ASSETS, BEHAVIORS / "approved") if d.is_dir() for f in d.iterdir() if f.is_file()), default=0)
        except OSError:
            own = 0
        return f"{self.layer.version}.{self.app_v}.{int(own)}"

    def keep_mirror_current(self):
        """While the headless browser is up, it follows every change (an edit, an undo, the app or the design view
        updated) to the owner's last screen in the background, so the next picture is ready. Asleep (idle), it isn't
        woken: it loads fresh when next needed."""
        last = None
        while True:
            time.sleep(2.0)
            try:
                key = self.mirror_key()
                if key != last and self.last_view and self.mirror.alive():
                    self.mirror.call("follow", wait=False, view=dict(self.last_view, key=key))
                last = key
            except Exception:
                pass

    def measure(self, n, spec):
        """The elements a change is about, measured exactly (inspect), in the headless browser showing the owner's
        screen (nothing runs in the owner's page); without it, in the owner's own page. -> text ("" if nothing)"""
        got = self.mirror.call("inspect", view=self.view_for(n), spec=spec)
        if got and isinstance(got.get("value"), str):
            print(f"measured {n.get('id', '-')}: headless {got.get('ms')} ms", flush=True)
            return got["value"]
        print(f"measured {n.get('id', '-')}: in the owner's page ({(got or {}).get('error') or 'headless browser unavailable'})", flush=True)
        return self.page_call("inspect", spec=spec, route=n.get("route") or "#/") or ""

    def page_call(self, what, timeout=6.0, **args):
        """Ask the owner's open page (on the note's screen) to measure (inspect), when the headless browser can't."""
        if time.time() - self.page_seen > 600:              # no page of the owner's open: nothing to ask
            return None
        req = f"{what}-{time.monotonic_ns()}"
        ev = threading.Event()
        self.page_wait[req] = [ev, None]
        self.events.send("page-call", req=req, what=what, **args)
        ev.wait(timeout)
        return self.page_wait.pop(req, [None, None])[1]

    def do_change(self, mc, rec, n, t0, p, parts, add_up):
        """One change part: measured, made from the numbers, checked up to twice, then the final check.
        -> "DONE <what changed>" or "ISSUE <what's wrong>"."""
        route, think = n.get("route") or "#/", bool(n.get("think"))
        stage = lambda text: self.events.send("stage", note=n["id"], k=p["k"], text=text, s=round(time.monotonic() - t0, 2))
        letters = {chr(65 + i): m for i, m in enumerate(n.get("marks") or []) if isinstance(m, dict)}
        marked = [letters[x] for x in p.get("marked") or [] if x in letters] or list(letters.values())
        targets = [t for t in p.get("target") or [] if isinstance(t, dict) and (t.get("selector") or t.get("what"))]
        spec = {"marked": [t.get("selector") or "" for t in targets] if targets else
                          [m.get("sel") or m.get("from") for m in marked if m.get("sel") or m.get("from")],
                "refers": [{"selector": r.get("selector") or "", "what": r.get("what") or ""} for r in p.get("refers_to") or []]}
        meaning = json.dumps(dict({k: p.get(k) for k in ("text", "marked", "target", "refers_to", "work", "done_when")},
                                  seen_at_the_marks=n.get("seen") or ""), ensure_ascii=False)
        focus = "\n\nThe plan for this note:\n" + "\n".join(f"{q['k']}. {q['kind']}: {q['text']}" for q in parts) + f"\n\nThis part: {meaning}"
        stage(f"understood: {p['text'][:90]} · measuring")
        before = self.measure(n, spec) if (spec["marked"] or spec["refers"]) else ""
        stage("changing" + (" (thinking)" if think else ""))
        sysmsg = {"role": "system", "content": self.pack()}
        call = lambda text, img, said=None, got=None, deep=False: self.consume(
            stream_lines(mc, [sysmsg, {"role": "user", "content": with_image({"image": img}, text)}], session=f"dv-{self.project}-change",
                         max_tokens=8000 if deep else 3000, thinking=deep), rec, n, t0, mode="edits", part=p, said=said, got=got)
        e, r, u, _ = call(self.ask(n) + focus + (f"\n\nMeasured on the page now (exact):\n{before[:6000]}" if before else "")
                          + "\n\n" + CHANGE_RULES, n.get("image"), deep=think)    # thinking, when asked for, goes here only
        add_up(e, r, u)
        after_img, ok, verdict = None, False, "FIX not checked"
        drawn_before, drawn_after = spots_text(n.get("zoom")), ""
        for rnd in (1, 2, 3):
            if rnd == 3 and ok:
                break
            stage(f"checking (round {rnd})")
            after = self.measure(n, spec) if before else ""
            seen_now = self.look(n, zoom=bool(n.get("zoom")))
            after_img, drawn_after = seen_now.get("image"), spots_text(seen_now.get("zoom"))
            ids = [o["id"] for o in self.layer.ops if o.get("note") == n["id"]]
            bad = self.not_landed(ids, route, wait=1.0)
            said, new = [], []
            vtext = (self.ask(n) + focus + (f"\n\nMeasured before the change:\n{before[:5000]}" if before else "")
                     + (f"\n\nMeasured after the change:\n{after[:5000]}" if after else "")
                     + (f"\n\nWhat is drawn at the spots they pointed at, before the change:\n{drawn_before}\n\nAnd now:\n{drawn_after}"
                        if drawn_before and drawn_after else "")
                     + (f"\n\nYour edits that didn't take (the page says why):\n{why_lines(bad)}\n{REPAIR_RULES}" if bad else "")
                     + "\n\n" + VERIFY_RULES)
            if rnd == 3:                                       # after a second fix: check it, no more edits
                said = [v for k, v in stream_lines(mc, [sysmsg, {"role": "user", "content": with_image({"image": after_img or n.get("image")},
                        vtext + " This is the last check: answer OK or FIX only, no edits.")}], session=f"dv-{self.project}-change",
                        max_tokens=600) if k == "line"]
            else:
                e, r, u, _ = call(vtext, after_img or n.get("image"), said=said, got=new)
                add_up(e, r, u)
            verdict = next((x for x in said if not x.startswith("{")), "OK")
            ok = verdict.upper().startswith("OK")
            rec.setdefault("checks", []).append(f"{p['k']}.{rnd} {verdict[:160]}")
            if ok or not new or rnd == 3:
                break
            after_img = None
        if after_img is None:
            after_img = self.look(n).get("image")
        if not ok:                                             # the numbers still say no: never "done"
            return "ISSUE " + re.sub(r"^FIX\W*", "", verdict)[:220]
        if before and not (VISUAL_FINAL and self.mirror.ok):   # measured and confirmed: that decides, unless the final
            return "DONE " + (re.sub(r"^OK\W*", "", verdict) or p["text"])[:180]   # check has real screenshots to look at
        stage("final check: does it look like what you asked?")
        scrolly = p.get("work") == "scroll" or re.search(r"scroll", f"{p['text']} {p.get('done_when') or ''}", re.I)
        got = (self.look(n, close=spec, scrolled=spec if scrolly else None, zoom=bool(n.get("zoom"))) if self.mirror.ok
               else {"image": after_img})
        drawn_now = spots_text(got.get("zoom"))
        met, said = self.final_check(mc, n, p, got.get("image") or after_img, got.get("close"), got.get("scrolled"),
                                     (self.measure(n, spec) if before else "")
                                     + (f"\n\nWhat is drawn at the spots they pointed at, before the change:\n{drawn_before}"
                                        f"\n\nAnd now (compare the entries: what went, what's left, what's new):\n{drawn_now}"
                                        if drawn_before and drawn_now else ""))
        if met is False:
            return "ISSUE " + ("it measures right but doesn't look it: " if before else "") + said
        return "DONE " + (said if met else (re.sub(r"^OK\W*", "", verdict) or p["text"]))[:180]

    def final_check(self, mc, n, p, after_img, close=None, scrolled=None, measured=""):
        """The result against the ask, by eye: the screen now, a close-up of each element involved, and the screen
        scrolled when the ask is about scrolling; with the exact measurements for sizes and gaps. -> (met, said)"""
        pics = [{"type": "image_url", "image_url": {"url": after_img}}] if str(after_img or "").startswith("data:image/") else []
        legend = []
        for c in close or []:
            if str(c.get("image") or "").startswith("data:image/"):
                pics.append({"type": "image_url", "image_url": {"url": c["image"]}})
                legend.append(f"picture {len(pics)}: close-up of {c.get('label')} = {str(c.get('what') or '')[:80]}")
        for c in scrolled or []:
            if str(c.get("image") or "").startswith("data:image/"):
                pics.append({"type": "image_url", "image_url": {"url": c["image"]}})
                legend.append(f"picture {len(pics)}: {str(c.get('label') or 'the screen scrolled')[:160]}")
        if not pics:
            return None, "no picture to look at"
        text = (f"The owner's note: {n['text'][:1000]}\nThe change: {p['text']}\nDone when: {p.get('done_when') or p['text']}\n"
                + ("\n".join(legend) + "\n" if legend else "")
                + (f"\nMeasured on the screen now (exact):\n{measured[:5000]}\n" if measured else "") + "\n" + FINAL_RULES)
        out = [v for k_, v in stream_lines(mc, [{"role": "user", "content": [{"type": "text", "text": text}] + pics}],
                                           session=f"dv-{self.project}-final", max_tokens=400) if k_ == "line"]
        said = " ".join(out).strip()
        m = re.search(r"(.*?)\W*\b(NOT MET|MET)\W*$", said, re.I | re.S)          # the verdict comes last
        m = m or re.match(r"\W*()(NOT MET|MET)\b", said, re.I)                        # (or first, the old way)
        if not m:
            return None, said[:220]
        return m.group(2).upper() == "MET", (m.group(1).strip() or said)[:220]

    def issue(self, n, what):
        """A change that didn't come out: put to the owner like a question, with what they can do about it."""
        self.pending[n["id"]] = {"question": what, "choices": [], "note": n["text"], "marks": n.get("marks") or [],
                                 "route": n.get("route") or "#/", "issue": True}
        self.events.send("question", note=n["id"], question="⚠ " + what, choices=[], about=n["text"][:200],
                         actions=[{"label": "↻ Try again with thinking", "do": "retry"}, {"label": "✕ Undo this", "do": "undo"}])

    def run_answer(self, n):
        """A note sent as a question only (dv API "ask": the toolbar sends everything through the plan now, where a
        question is an answer part): the designer's answer, with suggestions the owner can send as notes. Nothing
        on the page changes."""
        mc = model_config()
        if not mc:
            raise RuntimeError("no model config/key for the design view")
        rec = self.layer.new_note(n["text"], n.get("marks"), n.get("route"), nid=n["id"])
        rec["verdict"], t0 = "answer", time.monotonic()
        self.events.send("doing", note=n["id"], text=n["text"][:140])
        msgs = [{"role": "system", "content": self.pack().replace(RULES.split("\n\nEdits, each")[0], ANSWER_RULES)},
                {"role": "user", "content": with_image(n, self.ask(n))}]
        ans, sugg, usage = self.answer_stream(mc, msgs, n, t0, think=True, usage_out=True)
        rec["answer"], rec["suggest"], rec["plan"] = ans, sugg, (ans.split("\n")[0] if ans else "")[:200]
        rec["s"] = round(time.monotonic() - t0, 2)
        rec["tokens"] = {"in": usage.get("prompt_tokens"), "cached": usage.get("prompt_cache_hit_tokens"), "out": usage.get("completion_tokens")}
        self.layer.finish(rec)
        self.events.send("done", note=n["id"], verdict="answer", plan="answered (see the panel)", edits=0, s=rec["s"],
                         tokens=rec["tokens"])

    def answer_stream(self, mc, msgs, n, t0, think=False, usage_out=False):
        """An answer streamed into the owner's panel as it comes, with SUGGEST lines as "Do it" buttons."""
        lines, sugg, usage = [], [], {}
        for kind, val in stream_lines(mc, msgs, session=f"dv-{self.project}" + ("-deep" if think else ""),
                                      max_tokens=6000 if think else 2500, thinking=think):
            if kind == "usage":
                usage = val
                continue
            if val.upper().startswith("SUGGEST "):
                sugg.append(val[8:].strip()[:200])
            else:
                lines.append(val)
            self.events.send("answer", note=n["id"], title="Answer", text="\n".join(lines), suggest=sugg, kind="answer",
                             s=round(time.monotonic() - t0, 2))
        ans = "\n".join(lines).strip()
        return (ans, sugg, usage) if usage_out else (ans, sugg)

    def run_part(self, mc, rec, n, t0, p, parts, add_up, cards):
        """One part of a note that isn't quick, in parallel with the rest: options, a new screen, or background work
        (the deep path: thinking on, the other screens' maps)."""
        self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="doing", text=p["text"],
                         s=round(time.monotonic() - t0, 2))
        plan = "\n".join(f"PART {q['k']} {q['kind']} | {q['text']}" for q in parts)
        focus = f"\n\nThe plan for this note:\n{plan}\n\nYour part: PART {p['k']} {p['kind']} | {p['text']}\n"
        try:
            if p["kind"] == "answer":
                msgs = [{"role": "system", "content": self.pack().replace(RULES.split("\n\nEdits, each")[0], ANSWER_RULES)},
                        {"role": "user", "content": with_image(n, self.ask(n) + focus + "Answer only this part.")}]
                ans, sugg = self.answer_stream(mc, msgs, n, t0, think=False)
                rec["answer"], rec["suggest"] = ans, sugg
                e, r, u = 0, [], {}
            elif p["kind"] == "background":
                others = "\n\n".join(f"Map of {r}:\n{m[:5000]}" for r, m in list(self.maps.items())[-5:] if r != n.get("route"))
                msgs = [{"role": "system", "content": self.pack() + DEEP_RULES},
                        {"role": "user", "content": with_image(n, self.ask(n) + (f"\n\nOther screens:\n{others}" if others else "") + focus)}]
                e, r, u, proposal = self.consume(stream_lines(mc, msgs, session=f"dv-{self.project}-deep", max_tokens=12000,
                                                              thinking=True), rec, n, t0, mode="deep", part=p)
                if proposal:
                    cards.append(self.propose(proposal, rec))
                elif not e:
                    cards.append(self.card(rec, p))                       # it couldn't: the Designer takes it
            else:
                msgs = [{"role": "system", "content": self.pack()},
                        {"role": "user", "content": with_image(n, self.ask(n) + focus + PART_RULES[p["kind"]])}]
                think = p["kind"] in ("review", "think")                   # a judgement: worth the thinking time
                e, r, u, _ = self.consume(stream_lines(mc, msgs, session=f"dv-{self.project}" + ("-deep" if think else ""),
                                                       max_tokens=8000 if think else 3000, thinking=think),
                                          rec, n, t0, mode="edits", part=p)
                if p["kind"] == "options":
                    e2, r2 = self.check_options(mc, msgs, rec, n, t0, f"{n['id']}-{p['k']}", p)
                    e, r = e + e2, r + r2
                if think:
                    # The reasoning is shown only when it's needed: the owner asked why, or nothing was changed (so
                    # they know why it stays). A review that changed something says so in a line, no panel.
                    why = p.get("why") or ""
                    asked_why = re.search(r"\bwhy\b|\bhow come\b", n["text"], re.I)
                    if not why and not e:                          # it came back with nothing: say so, plainly
                        msg = ("Couldn't work this out, so nothing changed. Marking exactly what you mean (both things, "
                               "to match one to the other) helps.")
                        self.events.send("part", note=n["id"], k=0, kind=p["kind"], state="failed", text=msg,
                                         s=round(time.monotonic() - t0, 2))
                        if len(parts) == 1:
                            rec["plan"] = msg
                    elif why and ((not e and p["kind"] == "review") or asked_why):
                        self.events.send("answer", note=n["id"], title=f"Why ({p['text'][:60]})", kind="review",
                                         text=why, s=round(time.monotonic() - t0, 2))
                    elif why:
                        self.events.send("part", note=n["id"], k=0, kind="review", state="done",
                                         text="Changed: " + why[:140], s=round(time.monotonic() - t0, 2))
                        if len(parts) == 1:                                # the note's "done" line says what changed
                            rec["plan"] = "Changed: " + why[:140]
            add_up(e, r, u)
            self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="done", edits=e,
                             s=round(time.monotonic() - t0, 2))
        except Exception as ex:
            self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="failed",
                             text=f"{type(ex).__name__}: {str(ex)[:120]}", s=round(time.monotonic() - t0, 2))

    def ask_owner(self, n, p, text, t0):
        """The designer's question to the owner ("question :: answer :: answer"), shown above the box. Remembered until
        answered: the answer goes back with the question and the original note."""
        q, *choices = [x.strip() for x in text.split("::")]
        choices = [c for c in choices if c][:5]
        self.pending[n["id"]] = {"question": q, "choices": choices, "note": n["text"],
                                 "marks": n.get("marks") or [], "route": n.get("route") or "#/"}
        self.events.send("question", note=n["id"], question=q, choices=choices, about=n["text"][:200])
        self.events.send("part", note=n["id"], k=p["k"], kind=p["kind"], state="asked", text=q,
                         s=round(time.monotonic() - t0, 2))

    # ---- a function point: noted for later, with what the page saw ------------------------------------------------------
    def log_api(self, method, path, code, ms, body=b""):
        """Every API call the page makes, with a short answer for a failed one (kept with a build note)."""
        err = ""
        if code >= 400:
            err = (body[:300].decode("utf-8", "replace") if isinstance(body, bytes) else str(body)[:300]).strip()
        with self.api_lock:
            self.api_log.append({"t": time.time(), "m": method, "path": path[:200], "code": code, "ms": ms, "err": err})
            del self.api_log[:-40]

    def saw(self, n):
        """What the page saw around the note, as it was (nothing judged): the owner's last actions, the page's errors and
        the requests that failed in the last 5 minutes. Only what's there."""
        out = []
        trail = (n.get("trail") or [])[-4:]
        if trail:
            out.append("last actions: " + "; ".join(f"{a.get('did')} {a.get('on')}" + (f' "{a.get("text")}"' if a.get("text") else "")
                                                     for a in trail) + f" (on {trail[-1].get('route') or '#/'})")
        errs = (n.get("errors") or [])[-4:]
        if errs:
            out.append("page errors: " + "; ".join(f"{e.get('kind')}: {str(e.get('text'))[:150]}" for e in errs))
        with self.api_lock:
            failed = [c for c in self.api_log if c["code"] >= 400 and c["t"] > time.time() - 300][-4:]
        if failed:
            out.append("failed requests: " + "; ".join(f"{c['m']} {c['path']} -> {c['code']}" + (f" {c['err'][:120]}" if c["err"] else "")
                                                      for c in failed))
        return out

    def note_function(self, rec, n, p, t0, cards, noted):
        """A function point: its plan line goes on the running list with the owner's words and what the page saw, at
        once (no model call). The Manager plans the list with the owner; "urgent" also gives the Manager a card now."""
        text = (p["text"] or n["text"]).strip()
        try:
            extra = []
            if URGENT.search(n["text"]):
                c = self.kanban("Function (urgent): " + text[:70], "manager",
                                f"The owner said it's urgent, in the design view (note {rec['id']}, screen {n.get('route') or '#/'}).\n\n"
                                f"Note: {text}\nOwner's words: {n['text'][:1000]}\n" + "\n".join(self.saw(n))
                                + "\n\nIt is also on vault/design/build-notes.md: when it's dealt with, build-notes.py done <id> \"<where it went>\".")
                c["label"] = "for the Manager now (urgent)"
                cards.append(c)
                extra.append(f"urgent: card {c.get('id')} for the Manager")
            fid = fnotes.add(text, said=n["text"], screen=n.get("route") or "#/", source=f"design view {rec['id']}",
                             evidence=self.saw(n) + extra, page=self.notes_page, kind="function")
            noted.append(fid)
            self.events.send("part", note=n["id"], k=p["k"], kind="function", state="noted", text=f"{fid}: {text[:100]}",
                             s=round(time.monotonic() - t0, 2))
            self.events.send("functions")
        except Exception as ex:
            self.events.send("part", note=n["id"], k=p["k"], kind="function", state="failed",
                             text=f"not noted: {type(ex).__name__}: {str(ex)[:120]}", s=round(time.monotonic() - t0, 2))

    def note_check(self, mc, rec, n, parts, noted):
        """Every message is checked for notes for later (function, usage, feel) by one small call of its own (just the
        message and the open notes, no knowledge pack), in parallel with the work once the plan is in. What a function
        part already noted is not noted again."""
        try:
            fn = [q["text"] for q in parts if q["kind"] == "function"]
            doing = [q["text"] for q in parts if q["kind"] in ("change", "options", "screen", "background")]
            open_ = fnotes.items(self.notes_page)
            marks = ", ".join(str(m.get("sel") or m.get("kind") or "") for m in n.get("marks") or [] if m) or "-"
            text = (f"Open notes:\n" + ("\n".join(f"- {i['note'][:160]}" for i in open_[-30:]) or "(none)")
                    + "\n\nAlready noted from this message: " + ("; ".join(fn) or "nothing")
                    + "\n\nBeing done in the mockup from this message now (the build carries it, so it is never a note): "
                    + ("; ".join(doing) or "nothing")
                    + f"\n\nThe message (screen {n.get('route') or '#/'}, pointing at {marks}):\n{n['text'][:1500]}")
            for kind, val in stream_lines(mc, [{"role": "system", "content": NOTE_RULES}, {"role": "user", "content": text}],
                                          session=f"dv-{self.project}-notes", max_tokens=400):
                m = re.match(r"NOTE\s+<?(function|usage|feel)>?\s*[|:\-–]\s*(.+)", val, re.I) if kind == "line" else None
                if m and not any(same_note(m.group(2), x) for x in [i["note"] for i in open_] + fn + doing):   # never twice,
                    # and never the visual change itself (the mockup carries it into the build)
                    noted.append(fnotes.add(m.group(2).strip(), said=n["text"], screen=n.get("route") or "#/",
                                            source=f"design view {rec['id']}", page=self.notes_page, kind=m.group(1).lower()))
                    self.events.send("functions")
        except Exception as ex:
            print(f"note check {n['id']}: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)

    def sweep(self, why="asked"):
        """Every message since the last sweep, read once more (one call, thinking on) for notes the plans missed; new
        ones go on the list with source "sweep". Runs on demand (the 🔧 panel, /dv/sweep) and before the Manager plans an
        agreed build. -> {"added": [...], "read": n}"""
        mc = model_config()
        if not mc:
            return {"added": [], "read": 0, "error": "no model config"}
        state_f = self.layer.root / "sweep.json"
        try:
            since = json.loads(state_f.read_text(encoding="utf-8")).get("at", "")
        except (OSError, ValueError):
            since = ""
        msgs = [h for h in self.layer.history if (h.get("at") or "") > since and h.get("verdict") not in ("pick", "discard", "direct")
                and h.get("note") and not str(h["note"]).startswith(("picked option", "discarded the options"))]
        if not msgs:
            return {"added": [], "read": 0}
        t0 = time.monotonic()
        self.events.send("sweep", state="started", n=len(msgs), why=why)
        listed = fnotes.items(self.notes_page) + fnotes.items(self.notes_page, done=True)
        back = {u["note"] for u in self.layer.undone}
        text = ("Their notes list now:\n" + ("\n".join(f"- {i['id']} ({i['kind']}): {i['note'][:200]}" for i in listed) or "(empty)")
                + "\n\nTheir messages, oldest first (id [what it became]: words):\n"
                + "\n".join(f"{h['id']} [{h.get('verdict')}: {(h.get('plan') or '')[:90]}]{' [taken back]' if h['id'] in back else ''}: "
                            f"{str(h['note'])[:400]}" for h in msgs))
        lines = [v for k, v in stream_lines(mc, [{"role": "system", "content": SWEEP_RULES}, {"role": "user", "content": text}],
                                            session=f"dv-{self.project}-sweep", max_tokens=8000, thinking=True) if k == "line"]
        added = []
        for ln in lines:
            m = re.match(r"NOTE\s+<?(function|usage|feel)>?\s*[|:\-–]\s*([^|]+?)\s*(?:\|\s*(.*))?$", ln, re.I)
            if not m or any(same_note(m.group(2), i["note"]) for i in listed):
                continue
            listed.append({"note": m.group(2)})
            ids = re.findall(r"n\d+", m.group(3) or "")
            said = " / ".join(str(h["note"])[:200] for h in msgs if h["id"] in ids)[:400]
            added.append(fnotes.add(m.group(2).strip(), said=said, screen=next((h.get("route") for h in msgs if h["id"] in ids), "") or "",
                                    source="sweep of " + (", ".join(ids[:6]) or "the round"), page=self.notes_page, kind=m.group(1).lower()))
        state_f.write_text(json.dumps({"at": msgs[-1].get("at") or "", "note": msgs[-1]["id"], "added": added,
                                       "t": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
        self.events.send("sweep", state="done", added=added, n=len(msgs), s=round(time.monotonic() - t0, 1))
        self.events.send("functions")
        return {"added": added, "read": len(msgs)}

    def open_notes(self):
        """The open build notes (the toolbar's 🔧 list)."""
        try:
            return [{"id": i["id"], "kind": i["kind"], "note": i["note"], "screen": i["screen"], "when": i["when"]}
                    for i in fnotes.items(self.notes_page)]
        except (OSError, SystemExit):
            return []

    def saw_api(self, path, body, ctype):
        """What the app fetched from its API (the design copy's real data, or the mock's): the last answer per endpoint,
        cut short, and each picture route, so a note asking for real content or pictures can use them."""
        with self.api_lock:
            route = re.sub(r"\?.*$", "", path)
            if ctype.startswith("image/"):
                self.api_seen[route] = {"image": True, "example": path[:240], "t": time.time()}
            elif "json" in ctype:
                try:
                    sample = json.dumps(json.loads(body), ensure_ascii=False)[:700]
                except ValueError:
                    return
                self.api_seen[route] = {"example": path[:240], "sample": sample, "t": time.time()}
            if len(self.api_seen) > 24:                          # the 24 most recent endpoints
                for k in sorted(self.api_seen, key=lambda k: self.api_seen[k]["t"])[:len(self.api_seen) - 24]:
                    del self.api_seen[k]

    def api_pack(self):
        with self.api_lock:
            seen = sorted(self.api_seen.values(), key=lambda v: -v["t"])
        if not seen:
            return ""
        imgs = [v["example"] for v in seen if v.get("image")][:6]
        data = [f"GET {v['example']}\n  -> {v['sample']}" for v in seen if not v.get("image")][:10]
        return ("\n\n## The app's real data (what its own API answered just now)\n" + "\n".join(data)
                + ("\nPictures it loads from its own routes (use the same route with another id for another one):\n"
                   + "\n".join(imgs) if imgs else ""))

    def prefer(self, text):
        """A standing instruction from the owner (how to work with them, not about the page): kept in the layer's
        prefs.json and given with every later note. "drop: <it>" removes the one that matches best."""
        f = self.layer.root / "prefs.json"
        try:
            prefs = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except ValueError:
            prefs = []
        t = text.strip().strip('"')
        if t.lower().startswith("drop:"):
            words = set(re.findall(r"\w+", t[5:].lower()))
            best = max(prefs, key=lambda x: len(words & set(re.findall(r"\w+", x.lower()))), default=None)
            if best and words & set(re.findall(r"\w+", best.lower())):
                prefs.remove(best)
                said_ = f"Dropped: {best}"
            else:
                said_ = "No standing instruction like that to drop"
        else:
            prefs = [x for x in prefs if x.lower() != t.lower()] + [t]
            prefs = prefs[-12:]
            said_ = f"Kept from now on: {t}"
        f.write_text(json.dumps(prefs, indent=1), encoding="utf-8")
        return said_

    def check_options(self, mc, msgs, rec, n, t0, sid, p=None):
        """Every choice of an option set is checked: the headless browser loads each at the owner's view size and the
        layer reports its edits (nothing loads in the owner's page; without the headless browser, the toolbar does it
        in hidden frames). A choice with edits that didn't take gets its own repair call (only its failures,
        its fix added to it alone, the calls in parallel), and is checked again; a second round only when the first
        fixed some. -> (edits added, refused)."""
        if sid not in self.layer.options:
            return 0, []
        route = n.get("route") or "#/"
        ids = [o["id"] for c in self.layer.options[sid]["choices"].values() for o in c["ops"]]
        prev, edits, refused, lock = None, 0, [], threading.Lock()
        for _ in range(2):
            if self.mirror.ok:                                 # each choice judged in the headless browser, one after another
                for c in list(self.layer.options[sid]["choices"]):
                    self.mirror.call("measure", view=dict(self.view_for(n), opt=f"{sid}:{c}"), timeout=20)
            else:                                              # (no headless browser: the owner's page does it in frames)
                self.events.send("measure-options", set=sid, choices=list(self.layer.options[sid]["choices"]), route=route)
            bad = self.not_landed(ids, route, wait=2 if self.mirror.ok else 10)
            print(f"options {sid}: {len(self.layer.options[sid]['choices'])} choices judged "
                  f"{'in the headless browser' if self.mirror.ok else 'in the owner page'}, {len(bad)} edit(s) didn't take", flush=True)
            if not bad or (prev is not None and len(bad) >= prev):
                break
            where = {o["id"]: c for c, ch in self.layer.options[sid]["choices"].items() for o in ch["ops"]}
            per = {}
            for o, st in bad:
                per.setdefault(where.get(o["id"]), []).append((o, st))
            self.events.send("part", note=n["id"], k=p["k"] if p else 0, kind="options" if p else "check", state="doing",
                             text=f"{len(bad)} option edit(s) in {len(per)} choice(s) didn't take; fixing",
                             s=round(time.monotonic() - t0, 2))
            new = []

            def fix_choice(letter, items):
                nonlocal edits, refused
                ch = self.layer.options[sid]["choices"][letter]
                have = "\n".join(json.dumps({k: v for k, v in o.items() if k not in ("id", "note")})[:300] for o in ch["ops"])
                fix = msgs + [{"role": "user", "content": f"Option {letter} ({ch['name']}) has these edits:\n{have}\n\n"
                               "Checked on the owner's page, these of them didn't take effect:\n" + why_lines(items) + "\n"
                               + REPAIR_RULES + f" Give only the extra edits option {letter} needs so it looks as it "
                               "was meant to. Edits only: no OPTION line, no plan."}]
                got = []
                e2, r2, _, _ = self.consume(stream_lines(mc, fix, session=f"dv-{self.project}"), rec, n, t0,
                                            mode="edits", part=p, into=(sid, letter), got=got)
                with lock:
                    edits, refused = edits + e2, refused + r2
                    new.extend(got)
            ths = [threading.Thread(target=fix_choice, args=(c, items)) for c, items in per.items() if c]
            for th in ths:
                th.start()
            for th in ths:
                th.join(timeout=120)
            rec["repaired"] = rec.get("repaired", 0) + len(bad)
            ids, prev = new, len(bad)
            if not new:
                break
        return edits, refused

    def not_landed(self, ids, route, wait=2.0):
        """The note's edits that the owner's open page (on the note's screen) says didn't take: matched nothing, or
        didn't come out as asked (the page names what holds them). Option edits count too (the page measures the
        choice on show). Nothing to say when no page is open on that screen."""
        byid = {o["id"]: o for o in self.layer.ops}
        byid.update({o["id"]: o for st in self.layer.options.values() for c in st["choices"].values() for o in c["ops"]})
        ids = [i for i in ids if i in byid]

        def settled(i):                      # a css edit reports "ok" when applied, then its measurement
            r = self.reports.get(i)
            return bool(r) and not (byid[i]["op"] in ("css", "remove") and r["status"] == "ok")
        end = time.monotonic() + wait
        while time.monotonic() < end and not all(settled(i) for i in ids):
            time.sleep(0.15)
        bad = []
        for i in ids:
            r = self.reports.get(i)
            if not r or r.get("route") != route or i not in byid:
                continue
            st = r["status"]
            if st.startswith(("missing", "no effect: overridden", "didn't take")):
                bad.append((byid[i], st))
        return bad

    def consume(self, stream, rec, n, t0, mode="main", said=None, on_plan=None, got=None, part=None, into=None):
        """Read a model answer line by line, acting on each line as it arrives: the plan (main call: PART lines and
        END, handed to on_plan), option and screen markers, a behavior proposal (deep path), and the edits, each
        checked, stored and sent to the page. mode: main | edits (a part or a repair) | deep."""
        option, screen, edits, refused, usage, sid, proposal = None, None, 0, [], {}, None, None
        shared = []                                            # options: edits before the first choice (each gets them)
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
                m = re.match(r"PART\s+(\d+)\s*[:.]?\s*<?(quick|think|options|screen|background|function|review|answer|ask|prefer|ack)>?\s*[|:\-–]?\s*(.*)", line, re.I)
                if m and len(plan) < 5:
                    plan.append({"k": int(m.group(1)), "kind": m.group(2).lower(), "text": m.group(3).strip()})
                    continue
                m = re.match(r"VERDICT\s+<?(\w+)>?\s*\|?\s*(.*)", line, re.I)       # the single-verdict form still works
                if m and not plan:
                    kind_ = m.group(1).lower()
                    plan.append({"k": 1, "kind": kind_ if kind_ in ("quick", "think", "options", "screen", "background", "function", "review", "answer", "ask", "prefer", "ack")
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
                part["why"] = why
                continue
            m = re.match(r"OPTION\s+([A-Z])\b\s*[:|-]?\s*(.*)", line)
            if m and into:                                         # a repair of one choice: no new choices
                continue
            if m:
                if sid is None:
                    sid = self.layer.new_option_set(rec, sid=n["id"] + (f"-{part['k']}" if part else ""),
                                                    about=part["text"] if part else None)
                option = (sid, m.group(1))
                self.layer.add_choice(sid, m.group(1), m.group(2).strip()[:60] or m.group(1))
                self.events.send("option", note=n["id"], set=sid, choice=m.group(1), name=m.group(2).strip()[:60])
                for b in shared:                               # what came before the first choice belongs to each one
                    o2 = self.layer.add(dict(b), rec, option)
                    edits += 1
                    self.events.send("op", note=n["id"], op=o2, option={"set": sid, "choice": option[1]}, s=round(time.monotonic() - t0, 2))
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
            if op["op"] in ("undo", "redo") and not ASKS_UNDO.search(n["text"]):
                rec.setdefault("dropped", []).append(line[:160])  # only the owner takes notes back: never as a side effect
                continue
            if mode == "main" and not (option or screen) and not any(q["kind"] == "quick" for q in plan) \
                    and not (op["op"] in ("undo", "redo") and [x for x in op["notes"] if x != n["id"]]):
                rec.setdefault("dropped", []).append(line[:160])  # the plan has no change to make here (e.g. only
                continue                                           # a function problem): an edit is a stray, kept out
            if into:                                               # a repair of one option choice: the fix goes in it alone
                o2 = self.layer.add(op, rec, into)
                if got is not None:
                    got.append(o2["id"])
                self.events.send("op", note=n["id"], op=o2, option={"set": into[0], "choice": into[1]},
                                 s=round(time.monotonic() - t0, 2))
                edits += 1
                continue
            if part and part.get("kind") == "options" and not option and op["op"] not in ("undo", "redo"):
                shared.append(op)                              # options asked for: never a change to the mockup itself
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
        title = ("Design (background): " if who == "designer" else "From the mockup: ") + (what or rec["note"])[:80]
        body = (f"From the design view, note {rec['id']} on screen {rec.get('route') or '#/'}.\n\nOwner's note: {rec['note']}\n"
                f"Marked: {', '.join(rec.get('marks') or []) or '-'}\nThis part ({kind}): {what}\n")
        if who == "designer":
            body += ("\nA background design job: build it in the design layer with dv.py (see your instructions), so it "
                     "streams into the owner's mockup; nothing in the app's code. Group your edits with --group <this card>.")
        return self.kanban(title, who, body)

    def kanban(self, title, who, body, extra=()):
        if self.a.no_cards:                                       # a test copy: say what would be carded, make nothing
            return {"to": who, "id": "not-made (test copy)", "title": title[:80], "body": body[:6000]}
        try:
            out = subprocess.run(["hermes", "kanban", "create", title, "--assignee", who, "--body", body, *extra, "--json"],
                                 capture_output=True, text=True, timeout=60, env=kenv())
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
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = f"design-{stamp}"
        if self.a.no_cards:                                       # a test copy: no branch, no card
            self.layer.set_state("FROZEN", {"at": stamp, "build": slug, "card": self.kanban("x", "manager", ""), "t": time.time()})
            self.events.send("frozen", stamp=stamp)
            return {"ok": True, "stamp": stamp, "build": slug}
        try:
            wt = self.build_py("start", slug, "--design", stamp, "--title", f"the design agreed {stamp}")["worktree"]
        except (RuntimeError, ValueError, KeyError) as e:
            return {"error": f"couldn't start the build: {e}"}
        self.layer.set_state("FROZEN", {"at": stamp, "build": slug, "card": None, "t": time.time()})
        self.events.send("frozen", stamp=stamp)
        threading.Thread(target=self.plan_agreed, args=(stamp, slug, wt), daemon=True).start()
        return {"ok": True, "stamp": stamp, "build": slug}

    def plan_agreed(self, stamp, slug, wt):
        """After Agreed: the round's messages read once more for notes (the sweep), then the Manager's plan card."""
        try:
            swept = self.sweep("agreed")
        except Exception as e:
            swept = {"added": [], "error": str(e)[:120]}
        ours, others = self.round_notes()
        card = self.kanban(
            f"Build the agreed design ({stamp})", "manager",
            f"The owner pressed Agreed in the design view. The mockup is the main app with the visible changes they want: "
            f"build them into the real app, exactly as they look, and make everything they show really work. The design "
            f"layer stays frozen (the reference) until the build is live.\n\n"
            f"The build is `{slug}`: branch `design/{stamp}`, worktree `{wt}`. Read the build sheet first: `dv.py export` "
            f"(what the owner asked, change by change in their words, the edits, and this round's build notes).\n\n"
            f"Plan it as few cards as the work allows (usually one Engineer card per area of the app), each with the line "
            f"`Build: {slug}` and `--workspace dir:{wt}`:\n"
            f"- **Engineer**: fold the look into the real front end exactly (tokens -> theme.css, rules -> ui.css, screens and "
            f"markup) and make it work: the API, data, state and this round's build notes. Where it needs something the "
            f"design didn't show (an empty, loading or error state, a confirmation), follow the design's language and list "
            f"it under `Look decisions:` in the result. Before finishing: `dv.py look {wt}` (each screen against the agreed "
            f"mockup; aim for none differing, or each difference explained). A change that would alter the agreed look "
            f"itself is a question for the owner, through you: block the card and ask, don't decide it.\n"
            f"- **Designer**: not needed to fold or check by default. The look check runs by itself when the build is checked, "
            f"and only screens that still differ get one Designer look review. Plan a Designer card only for a design "
            f"decision the mockup left open.\n"
            f"- **Tester**: `Review: tester` only on a card with behaviour worth one review (forms, saving, a multi-step flow), "
            f"with its cases in vault/qa/; one review for the whole build, never per card.\n"
            f"Each card runs only its own quick checks and commits; mark the checks against the running app `(live)`. No "
            f"per-card review, merge or restart: when every card is done, build.py checks the whole build once (suite, "
            f"every card's checks, the look), runs the reviews it needs, merges into main, restarts the app and runs the "
            f"live checks; the mockup then starts from the new app. A defect noticed in the frozen mockup is fixed in the "
            f"build, never in the layer. Don't merge or restart yourself. Progress: `build.py status {slug}`."
            + (f"\n\nThis round's build notes are part of this build (the functions behind the look): "
               f"{', '.join(x['id'] for x in ours)}. Each card closes the ones it builds: `build-notes.py done <id> \"build {slug}\"`."
               if ours else "")
            + (f"\n\nOther open build notes ({len(others)}, vault/design/build-notes.md) are not in this build unless the "
               f"owner says: tell them in one line which could fit, and plan the rest with them (work-planning, "
               f"\"Build notes\")." if others else "")
            + (f"\n({len(swept['added'])} were just found by the sweep of this round's messages: {', '.join(swept['added'])}.)"
               if swept.get("added") else ""))
        try:
            self.build_py("start", slug, "--plan-card", card.get("id") or "")
        except (RuntimeError, ValueError) as e:
            print(f"build {slug}: couldn't record the plan card: {e}", file=sys.stderr, flush=True)
        self.layer.set_state("FROZEN", {"at": stamp, "build": slug, "card": card, "t": time.time()})
        self.events.send("frozen", card=card, stamp=stamp)

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
        agreed_page(agreed)
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
                self.app_v += 1
                self.events.send("app-changed")                  # the page reloads onto the refreshed data
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def round_notes(self):
        """The build notes of this design round (noted from a note still in the layer: the functions behind the look),
        and the other open ones. -> (this round's, others)"""
        mine = {h["id"] for h in self.layer.history}
        open_ = fnotes.items(self.notes_page)
        ours = [x for x in open_ if (re.search(r"\bn\d+\b", x.get("source") or "") or [None])[0] in mine]
        return ours, [x for x in open_ if x not in ours]

    def export(self):
        """The build sheet: what the owner asked for, change by change (their words, what was done, the edits and the
        screen), the functions behind it (this round's build notes), then the layer grouped the way a build uses it."""
        ops = list(self.layer.ops)
        stamp = (self.layer.state("FROZEN") or {}).get("at") or time.strftime("%Y%m%d-%H%M%S")
        out = [f"# Build sheet: the design agreed {stamp}", "",
               "The look below is agreed: build it into the real front end exactly (same tokens, rules and markup), and make "
               "what it shows really work (the build notes). Where making it work needs something the design didn't show "
               "(an empty state, an error, loading, a confirmation), follow the design's own language and list it under "
               "`Look decisions:` in your result. Check the look with `dv.py look <worktree>`: each screen of the build "
               "against the agreed mockup.", ""]
        by_note = {}
        for o in ops:
            by_note.setdefault(o.get("note"), []).append(o)
        changes = [h for h in self.layer.history if by_note.get(h["id"])]
        if changes:
            out += ["## What the owner asked, change by change", ""]
            for h in changes:
                out += [f"### {h['id']} · {h.get('route') or '#/'}", f"Owner: \"{(h.get('note') or '').strip()[:400]}\"",
                        f"Done: {(h.get('plan') or '').lstrip('✓⚠ ').strip()[:300]}", "```"]
                out += [json.dumps({k_: v for k_, v in o.items() if k_ not in ("id", "note")})[:600] for o in by_note[h["id"]]] + ["```", ""]
        ours, others = self.round_notes()
        if ours:
            out += ["## Make it work: this round's build notes (part of this build)", ""]
            out += [f"- **{x['id']}** ({x['kind']}) {x['note']}" + (f" · {x['screen']}" if x.get("screen") else "")
                    + (f"\n  - owner: \"{x['said']}\"" if x.get("said") else "") for x in ours] + [
                "", "When one is built, close it: `build-notes.py done <id> \"build <slug>\"`.", ""]
        if others:
            out += ["## Other open build notes (not in this build unless the owner says)", ""]
            out += [f"- **{x['id']}** ({x['kind']}) {x['note']}" for x in others] + [""]
        out += ["## The layer, grouped for the front end", ""]
        toks = [o for o in ops if o["op"] == "token"]
        if toks:
            out += ["### Theme tokens (theme.css :root)", "```css", ":root {"] + [f"  {o['name']}: {o['value']};" for o in toks] + ["}", "```", ""]
        css = [o for o in ops if o["op"] in ("css", "remove")]
        if css:
            out += ["### Rules (ui.css)", "```css"] + [o["rule"] if o["op"] == "css" else f"{o['sel']} {{ display: none; }}  /* remove */"
                                                     for o in css] + ["```", ""]
        for sc in [o for o in ops if o["op"] == "screen"]:
            parts = [o["html"] for o in ops if o["op"] == "insert" and o.get("ref") == "@screen:" + sc["route"]]
            out += [f"### Screen {sc['route']} ({sc['label']}) -> screens/{sc['route'][2:] or 'home'}.html, nav link '{sc['label']}'",
                    "```html"] + parts + ["```", ""]
        rest = [o for o in ops if o["op"] not in ("token", "css", "remove", "screen")
                and not (o["op"] == "insert" and str(o.get("ref", "")).startswith("@screen:"))]
        if rest:
            out += ["### Other edits (apply to the markup they name; behaviors become real code)", "```"]
            out += [json.dumps({k_: v for k_, v in o.items() if k_ not in ("id", "note")}) for o in rest] + ["```"]
        return "\n".join(out) + "\n"

    def look_routes(self):
        """The screens the agreed design touches: where its notes were made, and its new screens."""
        routes = [h.get("route") or "#/" for h in self.layer.history if any(o.get("note") == h["id"] for o in self.layer.ops)]
        routes += [o["route"] for o in self.layer.ops if o["op"] == "screen"] + [o["on"] for o in self.layer.ops if o.get("on")]
        return list(dict.fromkeys(r for r in routes if r))[:12] or ["#/"]

    def look_check(self, worktree, out_dir):
        """The look check: each screen of the agreed design, rendered by the headless browser twice at the owner's
        window size, the agreed mockup (the app with the design layer) and the build (its own front end, served from
        the worktree at /built/, no layer), compared pixel by pixel. The three pictures of each screen are saved in
        out_dir (mockup, build, and the build with what differs in magenta). -> {"screens": [...], "differ": [...]}"""
        if not self.mirror.ok:
            return {"error": "no headless browser here (node and the project's Chromium are needed)"}
        try:
            rel = self.app_dir.resolve().relative_to((HOME / "workspace").resolve())
        except ValueError:
            return {"error": f"the app's front end ({self.app_dir}) isn't in the workspace repo, so a worktree doesn't have it"}
        built = pathlib.Path(worktree).expanduser().resolve() / rel
        if not (built / "index.html").is_file():
            return {"error": f"no front end at {built}"}
        out = pathlib.Path(out_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.png"):
            old.unlink()
        self.built_dir = built
        view = {k_: v for k_, v in (self.last_view or {}).items() if k_ in ("w", "h")} or {"w": 1440, "h": 900}
        screens = []
        for i, route in enumerate(self.look_routes(), 1):
            got = self.mirror.call("compare", timeout=60, view=dict(view, route=route, scroll=0, key=self.mirror_key() + ".look"))
            if not got or got.get("error") or got.get("diff") is None:
                screens.append({"route": route, "error": (got or {}).get("error") or "no answer"})
                continue
            name = re.sub(r"[^\w-]+", "-", urllib.parse.unquote(route)).strip("-") or "home"
            files = {}
            for what in ("mockup", "built", "overlay"):
                f = out / f"{i:02d}-{name[:40]}-{what}.png"
                f.write_bytes(base64.b64decode(got[what].split(",", 1)[1]))
                files[what] = str(f)
            screens.append({"route": route, "diff": round(got["diff"] * 100, 2), **files})
        differ = [x for x in screens if x.get("diff", 0) >= LOOK_TOLERANCE]
        return {"screens": screens, "differ": [x["route"] for x in differ], "tolerance": LOOK_TOLERANCE, "view": view}

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
                self.app_v += 1
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
            if path == "/dv/functions":                              # the open build notes (the toolbar's 🔧)
                return self.send(200, {"items": app.open_notes()})
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
            if path.startswith("/built/") and app.built_dir:            # a build's own front end, for the look check
                return self.file(app.built_dir, path[7:] or "index.html", inject=True)
            if path.startswith("/api/"):
                if app.a.api_proxy:
                    return self.proxy()
                key = self.api_path()
                if key in app.mem:
                    return self.send(200, app.mem[key])
                for base in (app.layer.root / "data", app.layer.root / "snapshot"):
                    p = base / (key + ".json")
                    if p.is_file():
                        app.saw_api(self.path, p.read_bytes(), "application/json")
                        app.log_api("GET", self.path, 200, 0)
                        return self.send(200, p.read_bytes())
                app.log_api("GET", self.path, 404, 0, f"no mock data for {key}")
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
            t = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    code, body, ctype = r.status, r.read(), r.headers.get("Content-Type", "application/octet-stream")
            except urllib.error.HTTPError as e:
                code, body, ctype = e.code, e.read(), e.headers.get("Content-Type", "application/json")
            except (urllib.error.URLError, OSError) as e:
                app.log_api(self.command, self.path, 502, round((time.monotonic() - t) * 1000), f"the back end didn't answer ({e})")
                return self.send(502, {"error": f"the design copy of the back end didn't answer ({e})"})
            app.log_api(self.command, self.path, code, round((time.monotonic() - t) * 1000), body)
            if self.command == "GET" and code == 200:
                app.saw_api(self.path, body, ctype)
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
                    text = (f"The owner's original note: {q['note']}\nYour last attempt didn't work: {q['question']}\n"
                            f"The owner adds: {text}\nNow do what the original note asked, using this." if q.get("issue") else
                            f"The owner's original note: {q['note']}\nYou asked: {q['question']}\nTheir answer: {text}\n"
                            f"Now do what the original note asked, using this answer.")
                    marks = marks or q["marks"]
                nid = app.layer.note_id()
                img = d.get("image")                             # the picture of what's marked: in memory only
                img = img if isinstance(img, str) and img.startswith("data:image/") and len(img) < 3_000_000 else None
                clip = lambda xs, keys: [{k: str(x.get(k) or "")[:300] for k in keys} for x in (xs if isinstance(xs, list) else [])[-12:] if isinstance(x, dict)]
                app.notes.put({"id": nid, "text": text[:3000], "marks": marks, "ask": bool(d.get("ask")), "undo": bool(d.get("undo")), "redo": bool(d.get("redo")),
                               "map": str(d.get("map") or ""), "route": str(d.get("route") or "#/"),
                               "trail": clip(d.get("trail"), ("did", "on", "text", "route")), "errors": clip(d.get("errors"), ("kind", "text")),
                               "image": img, "view": view_of(d.get("view"))})
                waiting = app.notes.qsize() - (0 if app.status["busy"] else 1)
                app.events.send("received", note=nid, text=text[:140], queued=max(0, waiting))
                return self.send(200, {"id": nid, "queued": max(0, waiting)})
            if path == "/dv/view":                                   # where the owner is: the headless browser goes there
                app.last_view = view_of(d)
                app.mirror.call("follow", wait=False, view=dict(app.last_view, key=app.mirror_key()))
                return self.send(200, {"ok": True})
            if path == "/dv/map":
                app.page_seen = time.time()
                app.maps[str(d.get("route") or "#/")[:100]] = str(d.get("map") or "")[:20000]
                return self.send(200, {"ok": True})
            if path == "/dv/report":                                 # the open page: how each edit fared
                app.page_seen = time.time()
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
            if path == "/dv/page-reply":                           # the owner's page answering a measure or picture request
                w = app.page_wait.get(str(d.get("req") or ""))
                if w and not w[0].is_set():
                    w[1] = d.get("result")
                    w[0].set()
                return self.send(200, {"ok": True})
            if path == "/dv/dry-run":                               # what a note would be taken to mean and planned as; nothing
                note = {"id": "dry-run", "text": str(d.get("note") or "")[:3000], "route": str(d.get("route") or "#/"),   # changes
                        "view": view_of(d.get("view")), "marks": (d.get("marks") or [])[:6], "identify": bool(d.get("identify", True))}
                t = time.monotonic()
                got = app.look(note, zoom=True)
                note["image"], note["zoom"] = got.get("image"), got.get("zoom") or []
                t1 = time.monotonic()
                parts, _ = app.plan(model_config(), note)
                return self.send(200, {"parts": parts, "seen": note.get("seen"), "pictures": 1 + len(note["zoom"]), "shot_s": round(t1 - t, 2),
                                       "plan_s": round(time.monotonic() - t1, 1)})
            if path == "/dv/retry":                                 # an ISSUE's "try again with thinking": undo it, run it again
                old = app.recent.get(str(d.get("note") or ""))
                if not old:
                    return self.send(404, {"error": "that note is no longer at hand: send it again"})
                app.pending.pop(old["id"], None)
                if app.layer.undo_notes([old["id"]]):
                    app.events.send("reload-ops", why=f"undid {old['id']} to try again")
                nid = app.layer.note_id()
                app.notes.put(dict(old, id=nid, think=True))
                app.events.send("received", note=nid, text=("again, thinking: " + old["text"])[:140], queued=0)
                return self.send(200, {"id": nid})
            if path == "/dv/sweep":                                  # the 🔧 panel's Sweep: notes the plans missed
                threading.Thread(target=app.sweep, args=("asked",), daemon=True).start()
                return self.send(200, {"started": True})
            if path == "/dv/look":                                   # the look check: a build against the agreed mockup
                if not d.get("worktree"):
                    return self.send(400, {"error": "which worktree? (the build's, e.g. ~/wt/<slug>)"})
                return self.send(200, app.look_check(str(d["worktree"]), str(d.get("out") or HOME / ".hermes" / "look")))
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
                app.log_api(self.command, self.path, 200, 0)
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
    import atexit
    import signal
    atexit.register(app.mirror.stop)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # systemd's stop: exit cleanly, so the headless browser goes too
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(app))
    srv.daemon_threads = True
    print(f"design view for {a.project} on {a.bind}:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
