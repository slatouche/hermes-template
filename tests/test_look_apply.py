#!/usr/bin/python3
"""Checks for template/scripts/look-apply.py (a design round in one step), without a browser.

  python3 tests/test_look_apply.py      (a temporary HOME; the page checks themselves are covered by the live tests)
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).resolve().parent.parent / "template" / "scripts" / "look-apply.py"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


def run(home, args, css=None, task="t_123"):
    env = {**os.environ, "HOME": str(home), "HERMES_KANBAN_TASK": task, "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, str(TOOL), *args], input=css, capture_output=True, text=True, env=env, timeout=60)


def main():
    home = pathlib.Path(tempfile.mkdtemp(prefix="latest-"))
    look = home / "vault" / "design" / "variants" / "v1"
    look.mkdir(parents=True)
    (look / "style.css").write_text("h1{color:red}\n")

    r = run(home, ["v1", "--label", "make it blue"], css="h1 { color: blue; }")
    css = (look / "style.css").read_text()
    check("the round's CSS is appended after what was there", r.returncode == 0 and css.startswith("h1{color:red}")
          and css.rstrip().endswith("h1 { color: blue; }"), (r.returncode, r.stderr, css))
    check("...under a header naming the card and the round", "/* round t_123 " in css and ": make it blue */" in css, css)
    before = (look / "style.css").read_text()
    for bad in ("h1 { color: blue; ", "h1 { color: red } </style><script>", "@import url(x.css); h1{}"):
        r = run(home, ["v1"], css=bad)
        check(f"unsafe CSS refused and nothing written: {bad[:28]!r}", r.returncode == 2 and (look / "style.css").read_text() == before,
              (r.returncode, r.stderr))
    r = run(home, ["nope"], css="h1{}")
    check("a look that doesn't exist is refused", r.returncode == 2 and "no look" in r.stderr, r.stderr)
    r = run(home, ["../v1"], css="h1{}")
    check("no path escape through the look name", r.returncode == 2, r.returncode)
    r = run(home, ["v1"], css="")
    check("no CSS and no checks: nothing written, nothing failed", r.returncode == 0 and (look / "style.css").read_text() == before)

    # a round as a list of edits, on a design folder that isn't a look: CSS and markup, each saved in turn
    page = home / "vault" / "design" / "page1"
    page.mkdir(parents=True)
    (page / "style.css").write_text("p{margin:0}\n")
    (page / "index.html").write_text("<main><div class=bar>3 of 5</div><p>hi</p><p>hi</p></main>\n")
    r = run(home, ["--dir", str(page), "--demo", "1", "--edit", "tighten", "--css", "main{padding:8px}",
                   "--edit", "a stepper", "--html-in", "<div class=bar>3 of 5</div>", "--html-out", "<ol class=steps></ol>"])
    css, html = (page / "style.css").read_text(), (page / "index.html").read_text()
    check("--edit list: CSS edit appended to the folder's style.css", r.returncode == 0 and "main{padding:8px}" in css, (r.returncode, r.stderr))
    check("--edit list: markup edit replaced once, with a backup", "<ol class=steps></ol>" in html and "3 of 5" not in html
          and any(page.glob("index.html.bak-*")), (html, r.stderr))
    for args, why in ((["--html-in", "<p>hi</p>", "--html-out", "<p>yo</p>"], "matches 2 times"),
                      (["--html-in", "<b>nope</b>", "--html-out", "<b>x</b>"], "matches 0 times"),
                      (["--html-in", "<ol class=steps></ol>", "--html-out", "<script>x()</script>"], "isn't safe")):
        before_html = (page / "index.html").read_text()
        r = run(home, ["--dir", str(page), "--demo", "1", "--edit", "bad", *args])
        check(f"markup edit refused, nothing written: {why}", r.returncode == 2 and (page / "index.html").read_text() == before_html,
              (r.returncode, r.stderr))

    # structure on a look: moves, text, inserts and attributes go into dom.json, in order, with ids and screens
    r = run(home, ["v1", "--no-see", "--gap", "0", "--edit", "toggle left", "--move", "#theme -> before .brand h1",
                   "--edit", "rename", "--text", ".head > h2 => My decks", "--on", "#/$",
                   "--edit", "a badge", "--insert", "after .brand => <span class='tag'>beta</span>",
                   "--edit", "label", "--attr", ".btn @aria-label => Create a deck"])
    ops = json.loads((look / "dom.json").read_text()) if (look / "dom.json").exists() else []
    check("structural edits saved to dom.json in order", r.returncode == 0 and [o["op"] for o in ops] == ["move", "text", "insert", "attr"],
          (r.returncode, r.stderr, ops))
    check("...with ids, the move's parts and the screen limit", ops and ops[0]["id"] == "e1" and ops[0]["sel"] == "#theme"
          and ops[0]["where"] == "before" and ops[0]["ref"] == ".brand h1" and ops[1].get("on") == "#/$"
          and ops[1]["text"] == "My decks", ops)
    r = run(home, ["v1", "--no-see", "--edit", "another", "--move", ".a -> into .b"])
    ops2 = json.loads((look / "dom.json").read_text())
    check("a later round appends with the next id", r.returncode == 0 and len(ops2) == 5 and ops2[-1]["id"] == "e5", ops2[-1:])
    for args, why in ((["--insert", "after .x => <script>alert(1)</script>"], "a script"),
                      (["--insert", "after .x => <img src=x onerror=alert(1)>"], "an inline handler"),
                      (["--attr", ".x @onclick => alert(1)"], "an on* attribute"),
                      (["--move", ".a into .b"], "a malformed move")):
        before_ops = (look / "dom.json").read_text()
        r = run(home, ["v1", "--no-see", "--edit", "bad", *args])
        check(f"structural edit refused, nothing written: {why}", r.returncode == 2 and (look / "dom.json").read_text() == before_ops,
              (r.returncode, r.stderr))
    r = run(home, ["--dir", str(page), "--demo", "1", "--no-see", "--edit", "x", "--move", ".a -> into .b"])
    check("a move on a folder needs the prototype page it names", r.returncode == 2 and "pages/home.html" in r.stderr, r.stderr)

    # placeholders and mock screens on a look
    (look / "dom.json").unlink()
    (look / "maker.html").write_text("<h2>Card maker</h2>")
    r = run(home, ["v1", "--no-see", "--gap", "0", "--edit", "more decks", "--repeat", ".card => .name: A | B | C",
                   "--edit", "six more", "--repeat", ".row x 6",
                   "--edit", "card maker", "--screen", "#/card-maker in #main => @maker.html"])
    ops = json.loads((look / "dom.json").read_text()) if (look / "dom.json").exists() else []
    check("--repeat with words: one copy per word, into the part named", r.returncode == 0 and ops and ops[0]["op"] == "repeat"
          and ops[0]["values"] == ["A", "B", "C"] and ops[0]["child"] == ".name", (r.returncode, r.stderr, ops[:1]))
    check("--repeat x N", len(ops) > 1 and ops[1]["op"] == "repeat" and ops[1]["n"] == 6 and not ops[1].get("values"), ops[1:2])
    css = (look / "style.css").read_text()
    check("--screen: the markup goes in at its route, the app's own content there hidden", len(ops) > 2
          and ops[2]["op"] == "insert" and "Card maker" in ops[2]["html"] and 'data-look-screen="card-maker"' in ops[2]["html"]
          and ops[2]["on"].endswith("card\-maker$") and 'html[data-look-route="#/card-maker"] #main > :not([data-look-screen])' in css,
          (ops[2:3], css[-200:]))
    for args, why in ((["v1", "--edit", "x", "--link", ".a => #/b"], "--link on a look (the app's own links work)"),
                      (["--dir", str(page), "--demo", "1", "--edit", "x", "--screen", "#/x in #main => <p>x</p>"], "--screen on a prototype"),
                      (["v1", "--edit", "x", "--screen", "#/x in #main => @../../../.bashrc"], "--screen reading outside the look"),
                      (["v1", "--edit", "x", "--screen", "#/x in #main => <img src=x onerror=alert(1)>"], "--screen with a handler")):
        before_ops = (look / "dom.json").read_text()
        r = run(home, [*args, "--no-see"])
        check(f"refused: {why}", r.returncode == 2 and (look / "dom.json").read_text() == before_ops, (r.returncode, r.stderr))

    # a prototype page: --in-file points the markup edit at pages/<page>.html, and it must stay inside the folder
    (page / "pages").mkdir()
    (page / "pages" / "deck.html").write_text("<h1>Deck</h1><p>cards</p>\n")
    r = run(home, ["--dir", str(page), "--demo", "1", "--no-see", "--edit", "title", "--in-file", "pages/deck.html",
                   "--html-in", "<h1>Deck</h1>", "--html-out", "<h1>Your deck</h1>"])
    check("--in-file edits a page of the folder", r.returncode == 0 and "<h1>Your deck</h1>" in (page / "pages" / "deck.html").read_text(),
          (r.returncode, r.stderr))
    r = run(home, ["--dir", str(page), "--demo", "1", "--no-see", "--edit", "escape", "--in-file", "../../../.bashrc",
                   "--html-in", "a", "--html-out", "b"])
    check("--in-file can't leave the folder", r.returncode == 2, (r.returncode, r.stderr))
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
