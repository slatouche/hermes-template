#!/usr/bin/python3
"""Checks for template/scripts/look-apply.py (a design round in one step), without a browser.

  python3 tests/test_look_apply.py      (a temporary HOME; the page checks themselves are covered by the live tests)
"""
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
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
