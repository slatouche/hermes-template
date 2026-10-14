#!/usr/bin/python3
"""Checks for template/scripts/design-view.py (the design view server) and dv.py, without a model or a browser.

  python3 tests/test_design_view.py      (a temporary HOME and a server on a free local port)
"""
import importlib.util
import datetime
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
    mock_before = len(app.layer.ops)
    part3 = {"k": 3, "kind": "options", "text": "where the count could go"}
    app.consume(stream('{"op":"remove","sel":".count"}', "OPTION A By the title", '{"op":"insert","where":"after","ref":"h1","html":"<b>1</b>"}',
                       "OPTION B In the toolbar", '{"op":"insert","where":"into","ref":".bar","html":"<b>1</b>"}'),
                rec, n, time.monotonic(), mode="edits", part=part3)
    ch3 = app.layer.options.get(f"{rec['id']}-3", {}).get("choices", {})
    check("options asked for never change the mockup: edits before the first choice go into every choice",
          len(app.layer.ops) == mock_before and sorted(ch3) == ["A", "B"]
          and all(any(o["op"] == "remove" and o["sel"] == ".count" for o in c["ops"]) for c in ch3.values()),
          (len(app.layer.ops) - mock_before, {k: [o["op"] for o in c["ops"]] for k, c in ch3.items()}))
    plans.clear()
    app.consume(stream("PART 1 prefer | no reasoning unless you need a decision from me", "END"), rec, n, time.monotonic(),
                on_plan=plans.append)
    check("a standing instruction is its own kind of part", plans and plans[0][0]["kind"] == "prefer", plans)
    said = app.prefer("no reasoning unless you need a decision from me")
    app.prefer("tell me the percentage each time")
    check("a standing instruction is kept and goes with every later note",
          said.startswith("Kept") and "tell me the percentage each time" in app.pack() and "no reasoning unless" in app.pack(), said)
    said = app.prefer("drop: the percentage thing")
    check("...and 'drop:' removes the one that matches", "percentage" in said and "- tell me the percentage each time" not in app.pack()
          and "no reasoning unless" in app.pack(), said)
    app.saw_api("/api/projects", b'{"projects":[{"name":"Thor deck","cover":{"card_id":"abc"}}]}', "application/json")
    app.saw_api("/api/projects/Thor/tokens/card-image?card_id=abc&size=normal", b"\x89PNG", "image/png")
    pk = app.pack()
    check("what the app fetched is in every note's context: data samples and picture routes",
          "The app's real data" in pk and '"card_id": "abc"' in pk and "card-image?card_id=abc" in pk, pk[-600:])
    plans.clear()
    app.consume(stream("PART 1 think | find why the title glows and fix the cause", "END"), rec, n, time.monotonic(),
                on_plan=plans.append)
    check("a change that needs working out is its own kind of part (think)", plans and plans[0][0]["kind"] == "think", plans)
    plans.clear()
    app.consume(stream("PART 1 ack | glad it works", "PART 2 answer | which font the title uses", "END"), rec, n,
                time.monotonic(), on_plan=plans.append)
    check("one box: a reaction and an information question are their own kinds", plans
          and [p["kind"] for p in plans[0]] == ["ack", "answer"], plans)
    ra = app.layer.new_note("think about the header spacing", [{"sel": "header", "kind": "area", "inside": ["h1", "nav", "button"]}], "#/")
    ha = app.ask({"id": ra["id"], "text": ra["note"], "route": "#/", "marks": [{"sel": "header", "kind": "area", "inside": ["h1", "nav", "button"]}]})
    check("'think' in a note, and a drawn area over several elements, both point to thinking time",
          "asked you to think" in ha and "area over several elements" in ha, ha[-400:])
    check("the notes list says which notes were taken back (undo and redo in words)", "Notes so far" in ha)
    r1 = app.layer.new_note("make the title glow", [{"sel": "h1.title"}], "#/")
    app.layer.finish(dict(r1, verdict="quick", plan="Glow on the title"))
    r2 = app.layer.new_note("it still looks wrong", [], "#/")
    hint2 = app.ask({"id": r2["id"], "text": r2["note"], "route": "#/", "marks": []})
    r3 = app.layer.new_note("now make the button blue", [], "#/")
    hint3 = app.ask({"id": r3["id"], "text": r3["note"], "route": "#/", "marks": []})
    r4 = app.layer.new_note("this one again", [{"sel": "h1.title"}], "#/")
    hint4 = app.ask({"id": r4["id"], "text": r4["note"], "route": "#/", "marks": [{"sel": "h1.title"}]})
    check("'still wrong' after a change: the planner is told it follows an attempt that isn't right yet", "isn't right yet" in hint2, hint2[-300:])
    check("an unrelated note gets no such hint", "isn't right yet" not in hint3, hint3[-300:])
    check("the same element marked again: the planner is told so", "on the same element" in hint4, hint4[-300:])
    part = {"k": 1, "kind": "review", "text": "the glow"}
    app.consume(stream("WHY The glow stacked three shadows; one underline now.", '{"op":"css","rule":".t{text-shadow:none}"}'),
                rec, n, time.monotonic(), mode="edits", part=part)
    check("a review's reasoning is kept with its part (shown only when needed)", part.get("why", "").startswith("The glow"), part)

    # ---- function points: noted for later on the running list, never worked on here -----------------------------------
    rx = app.layer.new_note("new deck does nothing", [], "#/")
    ex, _, _, _ = app.consume(stream("PART 1 function | New deck does nothing", "END", '{"op":"behavior","name":"toast","sel":"b","text":"soon"}'),
                              rx, {"id": rx["id"], "text": rx["note"], "route": "#/"}, time.monotonic(), on_plan=lambda p: None)
    check("a plan with no change to make keeps no edits from the planning call", ex == 0 and rx.get("dropped"), (ex, rx.get("dropped")))
    ru = app.layer.new_note("undo the padding and match the gap", [], "#/")
    eu, _, _, _ = app.consume(stream("PART 1 think | match the gap", "END", '{"op":"undo","notes":["n999"]}'),
                              ru, {"id": ru["id"], "text": ru["note"], "route": "#/"}, time.monotonic(), on_plan=lambda p: None)
    check("...but an undo it writes is the owner's request and is kept", eu == 1, (eu, ru.get("dropped")))
    rn = app.layer.new_note("align the title with the other box", [], "#/")
    en, _, _, _ = app.consume(stream("PART 1 quick | align the title", "END", '{"op":"undo","notes":["n1"]}', '{"op":"css","rule":".t{margin:0}"}'),
                              rn, {"id": rn["id"], "text": rn["note"], "route": "#/"}, time.monotonic(), on_plan=lambda p: None)
    check("an undo the owner didn't ask for is never applied (only they take notes back)", en == 1 and any("undo" in x for x in rn.get("dropped") or []),
          (en, rn.get("dropped")))
    check("an edit scoped to one item's page (a deck name in the route) applies everywhere instead of being refused",
          "on" not in m.check_op({"op": "css", "rule": ".a{color:red}", "on": "#/deck/You've%20Got"})
          and m.check_op({"op": "css", "rule": ".a{color:red}", "on": "#/decks"})["on"] == "#/decks")
    calls = []

    def fake_stream(mc, msgs, session, max_tokens, thinking):
        calls.append(thinking)
        if not thinking:
            yield "line", "WHY fine"
        yield "usage", {"completion_tokens": max_tokens}
    real_stream = m._stream
    m._stream = fake_stream
    out = list(m.stream_lines({}, [], "s", 8000, thinking=True))
    m._stream = real_stream
    check("a thinking call that answers nothing is asked once more without thinking (never an empty part)",
          calls == [True, False] and ("line", "WHY fine") in out and out[-1] == ("usage", {"prompt_tokens": 0, "completion_tokens": 11000, "prompt_cache_hit_tokens": 0}), (calls, out))
    app.log_api("POST", "/api/import", 500, 41, b'{"error":"boom"}')
    app.log_api("GET", "/api/decks", 200, 12)
    nf = {"text": "the import button does nothing", "route": "#/decks", "marks": [{"sel": "#import"}],
          "trail": [{"did": "set", "on": "#link", "text": "https://moxfield.com/decks/x", "route": "#/decks"},
                    {"did": "click", "on": "#import", "text": "Import", "route": "#/decks"}],
          "errors": [{"kind": "console", "text": "import failed: 500"}]}
    saw = app.saw(nf)
    check("what the page saw is kept as it was: last actions, page errors, failed requests only (no model)",
          any("click #import" in x for x in saw) and any("import failed: 500" in x for x in saw)
          and any("POST /api/import -> 500" in x and "boom" in x for x in saw) and not any("/api/decks" in x for x in saw), saw)
    check("...and no actions or errors for a note that has none", all(x.startswith("failed requests") for x in app.saw({"text": "x"})))

    # a whole note through run_note: the plan (from the note and its picture), then each change made, checked and finally
    # checked; build notes on the spot. The fake model answers each step by its session and what it's asked.
    plan_calls, plan_lines, fake = [], [], {"plan": {}, "edits": [], "notes": [], "final": "MET it shows"}
    m.model_config = lambda: {"model": "test", "url": "http://127.0.0.1:9", "key": "x"}

    def fake_model(mc, msgs, session, max_tokens=3000, thinking=False):
        plan_calls.append(session)
        c = msgs[-1]["content"]
        text = c if isinstance(c, str) else c[0]["text"]
        if session.endswith("-identify"):
            fake["identify_text"] = text
            looks = fake.get("looks") or []                  # each look's answer in turn (three looks at once), or the same
            out = looks.pop(0) if looks else [
                "THING: the two vertical lines side by side: the right border of the search panel and the left border of the Cards group",
                "SHORT: the double divider between the search box and CARDS", "POINT: B|A.1, B|A.2",
                "WRONG: there should be one line there, as on the left"]
        elif session.endswith("-plan"):
            fake["plan_text"] = text
            out = [json.dumps(fake["plan"])]
        elif session.endswith("-notes"):
            out = fake["notes"]
        elif session.endswith("-final"):
            out = [fake["final"]]
        elif session.endswith("-sweep"):
            out = plan_lines
        elif m.VERIFY_RULES in text:
            out = fake.get("verify") or ["OK"]
        else:
            out = fake["edits"]
        return [("line", x) for x in out] + [("usage", {})]
    m.stream_lines = fake_model
    class FakeMirror:                                        # the headless browser, faked: pictures and measures on request
        ok = True
        def call(self, cmd, **a):
            seen.append(cmd)
            return ({"image": "data:image/png;base64,QUZURVI=", "ms": 1} if cmd == "shot"
                    else {"value": "" if fake.get("blind") else "A = div.issues: box x0 y0 10×10"})
    seen = []
    app.mirror = FakeMirror()
    app.page_call = lambda what, timeout=6.0, **a: seen.append("owner page " + what)
    evq = app.events.add()

    def run(text, parts, edits=(), notes=(), final="MET it shows", route="#/decks", **extra):
        fake.update(plan={"parts": parts}, edits=list(edits), notes=list(notes), final=final, verify=extra.pop("verify", None),
                    blind=extra.pop("blind", False))
        plan_calls.clear()
        nid = app.layer.note_id()
        app.run_note(dict(nf, id=nid, text=text, route=route, image="data:image/png;base64,QkVGT1JF", **extra))
        evs = []
        while not evq.empty():
            evs.append(json.loads(evq.get()))
        return [h for h in app.layer.history if h["id"] == nid][-1], evs
    ops_before = len(app.layer.ops)
    r1, e1 = run("this shouldn't be in my list of cards, it should be on the sidebar as the last item in the column. possibly with some functions to fix the issues found",
                 [{"kind": "change", "text": "move the issues panel to the end of the sidebar column", "marked": ["A"], "work": "move"},
                  {"kind": "function", "text": "the issues panel in the sidebar should offer actions that fix the issues it lists"}],
                 edits=['{"op":"move","sel":".issues","where":"into","ref":".sidebar"}'])
    done1 = [e for e in e1 if e["type"] == "done"][-1]
    open1 = app.open_notes()
    page = (app.layer.root / "build-notes.md").read_text(encoding="utf-8")
    check("a note in the one flow: planned from its picture, measured, the change made and checked, then a final look at "
          "the result; the function point noted on the spot",
          len(app.layer.ops) == ops_before + 1
          and sorted(plan_calls) == ["dv-t-change", "dv-t-change", "dv-t-final", "dv-t-notes", "dv-t-plan"]
          and done1.get("noted") == ["F1"] and r1.get("noted") == ["F1"] and done1["plan"].startswith("✓")
          and open1 and open1[0]["note"] == "the issues panel in the sidebar should offer actions that fix the issues it lists"
          and open1[0]["screen"] == "#/decks", (len(app.layer.ops) - ops_before, plan_calls, done1, open1))
    check("...the list keeps the owner's words, where it was said, and what the page saw",
          'said: "this shouldn\'t be in my list of cards' in page and f"design view {r1['id']}" in page
          and "failed requests: POST /api/import -> 500" in page and page.startswith("---\n")
          and all(f"\n{k}:" in page.split("\n---\n")[0] for k in ("title", "type", "status", "owner", "updated", "summary")), page[:900])
    r2, e2 = run("saving decks is broken, urgent", [{"kind": "function", "text": "saving a deck fails"}])
    check("'urgent': noted, and the Manager gets a card now", r2.get("cards") and r2["cards"][0]["title"].startswith("Function (urgent): ")
          and "urgent: card" in (app.layer.root / "build-notes.md").read_text(encoding="utf-8") and r2.get("noted") == ["F2"], r2.get("cards"))
    r3, e3 = run("I flick between decks all the time so this should feel instant, make the title smaller",
                 [{"kind": "change", "text": "make the deck title smaller", "work": "size"}],
                 edits=['{"op":"css","rule":"h1{font-size:20px}"}'],
                 notes=["NOTE usage | the owner switches between decks often", "NOTE feel: switching decks should feel instant"])
    its = {i["id"]: i for i in app.open_notes()}
    check("every message is checked for build notes: a design change still gets its usage and feel notes",
          r3.get("noted") == ["F3", "F4"] and its["F3"]["kind"] == "usage" and its["F4"]["kind"] == "feel"
          and its["F4"]["note"] == "switching decks should feel instant", (r3.get("noted"), its))
    r3b, _ = run("again: decks should switch instantly", [{"kind": "function", "text": "deck switching should be instant"}],
                 notes=["NOTE feel | switching decks should feel instant!"])
    check("a note already on the list (or already noted by a function part) isn't saved again",
          r3b.get("noted") == ["F5"] and len(app.open_notes()) == 5, (r3b.get("noted"), app.open_notes()))
    r4, e4 = run("make this match the other box", [{"kind": "change", "text": "match the box", "work": "style"}],
                 edits=['{"op":"css","rule":".box{padding:4px}"}'], final="NOT MET the box still has a border", blind=True)
    q4 = [e for e in e4 if e["type"] == "question"]
    check("with nothing measured, the before/after pictures decide; an ISSUE is put to the owner like a question: more "
          "words, try again with thinking, or undo", q4 and [a["do"] for a in q4[0]["actions"]] == ["retry", "undo"]
          and r4["plan"].startswith("⚠") and r4["id"] in app.pending and app.pending[r4["id"]].get("issue")
          and r4["id"] in app.recent, (q4, r4.get("plan")))
    r5, _ = run("think about the spacing here", [{"kind": "change", "text": "even out the spacing", "work": "spacing"}],
                edits=['{"op":"css","rule":".sp{gap:8px}"}'])
    check("'think' in a note, or a retry, gives the change thinking time", app.recent[r5["id"]]["think"] is True)
    r7, e7 = run("make this gap match the sidebar", [{"kind": "change", "text": "match the gap", "work": "spacing"}],
                 edits=['{"op":"css","rule":".g{margin-top:0}"}'], final="MET looks matched", verify=["FIX the gap is still 12px, not 18px"])
    check("never 'done' while the check still says it isn't: an ISSUE with what's wrong, whatever the pictures suggest",
          r7["plan"].startswith("⚠") and "still 12px" in r7["plan"] and any(e["type"] == "question" for e in e7), r7.get("plan"))
    r8, _ = run("make this box match the other", [{"kind": "change", "text": "match the box", "work": "style"}],
                edits=['{"op":"css","rule":".box{padding:2px}"}'], final="the box still has a border, unlike the other -> NOT MET", blind=True)
    check("the final check gives what it saw first and its verdict last", r8["plan"].startswith("⚠") and "still has a border" in r8["plan"],
          r8.get("plan"))
    spot = {"label": "B|A", "what": "where B (left) and A (right) meet", "image": "data:image/png;base64,U1BPVA==",
            "drawn": "The spot is 72×36 px; positions are px from its top-left.\nvertical line at x 27: the right border of "
                     "details.panel-fold\nvertical line at x 44: the left border of div.vgroup"}
    run("there are 2 lines here when there should be 1", [{"kind": "change", "text": "remove the extra divider", "work": "remove"}],
        edits=['{"op":"css","rule":".vgroup{border-left:0}"}'], zoom=[spot])
    check("what the owner means is worked out first (three looks at once, from the close-ups and exactly what's drawn in "
          "them, as numbered entries); when they agree the plan gets it",
          plan_calls[:4] == ["dv-t-identify"] * 3 + ["dv-t-plan"]
          and "B|A.2 vertical line at x 44" in fake.get("identify_text", "") and "the double divider between the search box and CARDS" in fake.get("plan_text", "")
          and "there should be one line there" in fake.get("plan_text", ""), (plan_calls, fake.get("plan_text", "")[-300:]))
    lines = lambda short, point: ["THING: it", f"SHORT: {short}", f"POINT: {point}", "WRONG: one too many"]
    fake["looks"] = [lines("the double divider", "B|A.1"), lines("the extra line by CARDS", "B|A.1, B|A.2"), lines("the header's bottom edge", "")]
    r9, e9 = run("there are 2 lines here when there should be 1", [{"kind": "change", "text": "should not be planned", "work": "remove"}], zoom=[spot])
    check("two looks pointing at the same thing (in any words) go ahead", "-plan" in " ".join(plan_calls) and not r9["plan"].startswith("?"),
          (plan_calls, r9.get("plan")))
    fake["looks"] = [lines("the double divider", "B|A.1"), lines("the search box's top and bottom edges", "B.3"),
                     lines("the header's bottom edge", "B.5")]
    spot3 = dict(spot, drawn=spot["drawn"] + "\nhorizontal line at y 2: the top border of input.filter-q\nhorizontal line at y 33: "
                                              "the bottom border of input.filter-q\nhorizontal line at y 35: the bottom border of div.deck-head")
    spotB = dict(spot3, label="B")
    r10, e10 = run("there are 2 lines here when there should be 1", [{"kind": "change", "text": "should not be planned", "work": "remove"}],
                   zoom=[spot, spotB])
    q10 = [e for e in e10 if e["type"] == "question"]
    check("when the looks don't agree it isn't clear: the owner is asked which they mean, with each as an answer (nothing planned or changed)",
          not any(c.endswith("-plan") for c in plan_calls) and q10 and "the double divider" in json.dumps(q10)
          and "the search box's top and bottom edges" in json.dumps(q10) and not r10.get("ops"), (plan_calls, q10, r10.get("plan")))
    run("make the title bigger", [{"kind": "change", "text": "bigger title", "work": "size"}], edits=['{"op":"css","rule":"h1{font-size:24px}"}'])
    check("nothing pointed at, nothing to work out: no extra step", not any(c.endswith("-identify") for c in plan_calls), plan_calls)
    check("every picture and measurement comes from the headless browser, never the owner's page",
          "shot" in seen and "inspect" in seen and not any(x.startswith("owner page") for x in seen), sorted(set(seen)))
    v = m.view_of({"route": "#/x", "w": 99999, "h": "900", "scroll": -5, "opt": "s1:A", "scrollers": [{"sel": "#list", "top": 120}, "junk"]})
    check("the owner's view is cleaned before the headless browser shows it",
          v == {"route": "#/x", "w": 4000, "scroll": 0, "opt": "s1:A", "scrollers": [{"sel": "#list", "top": 120, "left": 0}]}, v)
    made = next(h for h in reversed(app.layer.history) if any(o.get("note") == h["id"] for o in app.layer.ops))
    real_page, app.notes_page = app.notes_page, app.layer.root / "sheet-notes.md"     # its own list, for this check
    f_ours = m.fnotes.add("the count is a live total of the deck", said="this should be the live count", source=f"design view {made['id']}",
                          page=app.notes_page)
    f_old = m.fnotes.add("something from an older chat", source="chat", page=app.notes_page)
    ours, others = app.round_notes()
    sheet = app.export()
    app.layer.undone.append({"note": made["id"], "ops": [], "at": "00:00:00"})       # the owner took that message back
    ours_back, others_back = app.round_notes()
    app.layer.undone.pop()
    app.notes_page = real_page
    check("a build note from a message the owner took back isn't part of the build (it's theirs to confirm)",
          not ours_back and f_ours in [x["id"] for x in others_back], (ours_back, others_back))
    check("the build sheet: what the owner asked, change by change (their words, what was done, the edits), then this "
          "round's build notes as part of the build, the older ones apart",
          [x["id"] for x in ours] == [f_ours] and f_old in [x["id"] for x in others]
          and "## What the owner asked, change by change" in sheet and f"### {made['id']}" in sheet
          and f'Owner: "{made["note"][:30]}' in sheet and "## Make it work: this round's build notes" in sheet
          and f"**{f_ours}**" in sheet.split("## Other open")[0] and f"**{f_old}**" in sheet.split("## Other open")[1]
          and "dv.py look" in sheet, sheet[:900])
    pf = app.layer.root / "prefs.json"
    pf.write_text(json.dumps(["keep a running backlog of notes", "no reasoning unless asked"]))
    run("drop: the backlog instruction", [{"kind": "prefer", "text": "Drop the backlog instruction, no running backlog from now on"}])
    check("'drop:' in the owner's words removes the instruction, even when the plan rewords it",
          json.loads(pf.read_text()) == ["no reasoning unless asked"], pf.read_text())
    r6, _ = run("hmm", [{"kind": "nonsense"}])
    check("a plan that can't be read becomes one change part with the note (never nothing)",
          r6["parts"] == [{"k": 1, "kind": "change", "text": "hmm"}], r6.get("parts"))
    app.events.drop(evq)
    plan_lines[:] = ["NOTE function | each category row should be editable in place | n1, n3", "not a note line", "NOTE nonsense | x",
                     "NOTE usage | the owner switches between decks often | n2"]
    sw = app.sweep("test")
    swept = [i for i in app.open_notes() if i["id"] in sw["added"]]
    check("the sweep reads the round's messages once more and adds what the plans missed, with where it came from",
          sw["read"] > 3 and len(sw["added"]) == 1 and swept and swept[0]["kind"] == "function"
          and "sweep of n1, n3" in (app.layer.root / "build-notes.md").read_text(encoding="utf-8"), (sw, swept))
    check("...and a second sweep reads only what came after it", app.sweep("test")["read"] == 0)
    check("the designer knows its build notes: the open ones are in every note's context",
          "## The owner's build notes" in app.pack() and "F2 (function): saving a deck fails" in app.pack(), app.pack()[-900:])

    # the Manager's side: the same list from a chat, and every item ends up saying where it went
    fnp = str(app.layer.root / "build-notes.md")
    fn_cli = [sys.executable, str(ROOT / "scripts" / "build-notes.py"), "--page", fnp]
    r = subprocess.run(fn_cli + ["add", "deck export should include the sideboard", "--said", "export misses my sideboard"],
                       capture_output=True, text=True)
    ls = json.loads(subprocess.run(fn_cli + ["list", "--json"], capture_output=True, text=True).stdout)
    check("a note from a chat goes on the same list (build-notes.py add)", r.stdout.strip() == "F7"
          and [i["id"] for i in ls] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7"] and ls[6]["source"] == "chat", (r.stdout, r.stderr, ls))
    txt = pathlib.Path(fnp).read_text(encoding="utf-8")
    pathlib.Path(fnp).write_text(txt.replace("## Open\n", "## Open\nThe Manager's own line under Open.\n"), encoding="utf-8")
    r = subprocess.run(fn_cli + ["done", "F1", "build design-20261014-0910"], capture_output=True, text=True)
    bad = subprocess.run(fn_cli + ["done", "F9", "x"], capture_output=True, text=True)
    txt = pathlib.Path(fnp).read_text(encoding="utf-8")
    left = json.loads(subprocess.run(fn_cli + ["list", "--json"], capture_output=True, text=True).stdout)
    gone = json.loads(subprocess.run(fn_cli + ["list", "--json", "--done"], capture_output=True, text=True).stdout)
    check("done moves an item under Done saying where it went; the rest and any hand-written lines stay",
          r.returncode == 0 and bad.returncode == 1 and [i["id"] for i in left] == ["F2", "F3", "F4", "F5", "F6", "F7"]
          and gone and gone[0]["id"] == "F1" and gone[0]["outcome"].startswith("build design-20261014-0910")
          and "The Manager's own line under Open." in txt and txt.index("**F1**") > txt.index("## Done"), (r.stderr, txt[-700:]))
    check("ids never repeat once items are done", subprocess.run(fn_cli + ["add", "another"], capture_output=True, text=True).stdout.strip() == "F8")
    tp = str(app.layer.root / "tidy-notes.md")
    t_cli = [sys.executable, str(ROOT / "scripts" / "build-notes.py"), "--page", tp]
    for note, said in (("the info button should open a help note covering what each control does", "help me"),
                       ("save should keep my scroll position", ""),
                       ("The info button's help note should cover what each control does", "explain the controls")):
        subprocess.run(t_cli + ["add", note, "--said", said] if said else t_cli + ["add", note], capture_output=True, text=True)
    subprocess.run(t_cli + ["done", "F2", "build design-old"], capture_output=True, text=True)
    pg = pathlib.Path(tp)
    pg.write_text(pg.read_text().replace(f"(build design-old ({datetime.date.today().isoformat()})", "x").replace(
        f"build design-old ({datetime.date.today().isoformat()})", "build design-old (2026-01-02)"))
    quiet = subprocess.run(t_cli + ["tidy", "--dry"], capture_output=True, text=True).stdout
    out = subprocess.run(t_cli + ["tidy"], capture_output=True, text=True).stdout
    again = subprocess.run(t_cli + ["tidy"], capture_output=True, text=True).stdout
    page_now, arch = pg.read_text(), pathlib.Path(tp.replace(".md", "-archive.md"))
    open_now = json.loads(subprocess.run(t_cli + ["list", "--json"], capture_output=True, text=True).stdout)
    check("tidy: the same note twice is merged into the older (its words kept), and a done item over a month old moves "
          "to the archive; a second run has nothing to do",
          "would merge F3 into F1" in quiet and "merged F3 into F1" in out and "archived 1" in out and again == ""
          and [x["id"] for x in open_now] == ["F1"] and "merged F3: The info button's help note" in page_now
          and "explain the controls" in page_now and "went: merged into F1" in page_now
          and arch.exists() and "**F2**" in arch.read_text() and "**F2**" not in page_now, (out, page_now[-700:]))

    rf = app.layer.new_note("new deck does nothing", [], "#/")
    app.layer.finish(dict(rf, verdict="function", plan="New deck does nothing"))
    rs = app.layer.new_note("the new deck button is still dead", [], "#/")
    hs = app.ask({"id": rs["id"], "text": rs["note"], "route": "#/", "marks": []})
    check("'still broken' after a function point: noted again with the detail, not a mocked-up fix",
          "a function point noted for later" in hs and "Plan it as think" not in hs, hs[-300:])
    hl = app.ask({"id": "n99", "text": "put that on the backlog please", "route": "#/", "marks": []})
    hn = app.ask({"id": "n98", "text": "note that the header is too tall", "route": "#/", "marks": []})
    check("'put it on the backlog' tells the planner it's a function part; 'note that the header…' doesn't",
          "noted for later: plan it as a function part" in hl and "noted for later: plan it as" not in hn, (hl[-200:], hn[-200:]))

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
        code, fl = get("/dv/functions")
        check("the toolbar's backlog count has its endpoint", code == 200 and json.loads(fl) == {"items": []}, fl)
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
        for _ in range(50):                                  # the sweep, then the plan card, follow Agreed in the background
            b = json.loads((home / ".hermes" / "builds" / f"{r.get('build')}.json").read_text()) if r.get("build") else {}
            if b.get("plan_card"):
                break
            time.sleep(0.2)
        board = json.loads((home / "board.json").read_text()) if (home / "board.json").exists() else []
        check("Agreed starts a build: branch, worktree, frozen layer", code == 200 and b.get("branch", "").startswith("design/")
              and pathlib.Path(b.get("worktree", "/nope")).is_dir() and json.loads(urllib.request.urlopen(
                  f"http://127.0.0.1:{port2}/dv/ops").read())["frozen"]["build"] == r.get("build"), (code, r, b))
        check("...and the Manager's plan card names the build and its worktree, recorded as the plan card",
              len(board) == 1 and board[0]["assignee"] == "manager" and f"Build: {r.get('build')}" in board[0]["body"]
              and b.get("worktree", "?") in board[0]["body"] and b.get("plan_card") == board[0]["id"], (board, b.get("plan_card")))
        check("...which says how to build it: the Engineer folds the look exactly and makes it work, checks it with dv.py "
              "look; the Designer and the Tester only when needed, once",
              board and all(x in board[0]["body"] for x in ("dv.py export", "**Engineer**", f"dv.py look {b.get('worktree')}",
                                                            "Look decisions:", "only screens that still differ", "never per card")),
              board[0]["body"][:400] if board else board)
        time.sleep(6)
        st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/ops").read()).get("build") or {}
        check("the toolbar follows the build's stage", st.get("state") == "planning" and st.get("rows"), st)
        op_note = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/status").read())["notes"][-1]["id"]
        bn2 = [sys.executable, str(ROOT / "scripts" / "build-notes.py"), "--page", str(home / "vault" / "design" / "build-notes.md")]
        subprocess.run(bn2 + ["add", "the background colour is saved per deck", "--source", f"design view {op_note}"], capture_output=True)
        b["state"] = "live"                                  # as build.py leaves it once it went live
        (home / ".hermes" / "builds" / f"{r['build']}.json").write_text(json.dumps(b))
        time.sleep(6)
        o3 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/dv/ops").read())
        check("live: the mockup unfreezes onto the new app and the layer is archived", not o3["frozen"] and o3["ops"] == [], o3["frozen"])
        left = [c for c in json.loads((home / "board.json").read_text()) if c["title"].startswith("Build notes still open after")]
        check("live: this round's build notes still open go to the Manager on one card, so none is forgotten",
              len(left) == 1 and left[0]["assignee"] == "manager" and "the background colour is saved per deck" in left[0]["body"]
              and "build-notes.py done" in left[0]["body"], left)
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
