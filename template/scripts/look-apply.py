#!/usr/bin/python3
"""look-apply.py: a design round in one step. Adds this round's CSS to the look, checks it on the page, and closes
the round's card when every check passes, so the Designer designs and proves it in a single call.

  look-apply.py <look> --page '<path#route>' --size WxH [--label "<what this round does>"]
                [--check '<js expression>' ...] [--done "<a line per note>" ...]  <<'CSS'
  ...the round's CSS...
  CSS

- The CSS is appended to vault/design/variants/<look>/style.css as one block headed with the label (later rules
  win, so nothing earlier has to be found and edited mid-round; the wrap-up tidies). No CSS on stdin: checks only.
- Each --check is a JavaScript expression evaluated on the look's page at that size (look-check.sh): it passes when
  its value is truthy. Typical: `getComputedStyle(document.querySelector('X')).color === 'rgb(...)'`,
  `!document.querySelector('X')`, `document.querySelector('X').naturalWidth > 0`.
- With --done and every check passing, the card ($HERMES_KANBAN_TASK) is completed with those lines.
Exit 0 when every check passes, 1 otherwise (the values say why), 2 on bad input.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

HOME = pathlib.Path.home()
SCRIPTS = HOME / ".hermes" / "scripts"
VARIANTS = HOME / "vault" / "design" / "variants"


def main():
    ap = argparse.ArgumentParser(description="Add a round's CSS to a look, check it, close the card.")
    ap.add_argument("look")
    ap.add_argument("--page", default="/")
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--label", default="")
    ap.add_argument("--check", action="append", default=[])
    ap.add_argument("--done", action="append", default=[])
    a = ap.parse_args()
    vd = VARIANTS / a.look
    if not re.fullmatch(r"[\w-]+", a.look) or not vd.is_dir():
        print(f"look-apply: no look {a.look!r} in {VARIANTS}", file=sys.stderr)
        return 2
    css = "" if sys.stdin.isatty() else sys.stdin.read().strip()
    if css:
        if css.count("{") != css.count("}") or re.search(r"</|javascript:|@import", css, re.I):
            print("look-apply: that CSS isn't safe to add (unbalanced braces, '</', javascript: or @import)", file=sys.stderr)
            return 2
        f = vd / "style.css"
        head = f"/* round {os.environ.get('HERMES_KANBAN_TASK', '')} {datetime.datetime.now():%Y-%m-%d %H:%M}"
        head += (f": {a.label.replace('*/', '')}" if a.label else "") + " */"
        with open(f, "a", encoding="utf-8") as fh:            # appended, never rewritten: others may add while we work
            fh.write(f"\n{head}\n{css}\n")
        print(f"added {len(css)} chars of CSS to {f.relative_to(HOME)}")
    ok = True
    if a.check:
        r = subprocess.run([str(SCRIPTS / "look-check.sh"), a.look, a.page, "--size", a.size,
                            *[x for c in a.check for x in ("--js", c)]], capture_output=True, text=True, timeout=120)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print(f"look-apply: the page check failed: {(r.stderr or r.stdout)[-400:]}", file=sys.stderr)
            return 1
        if out.get("error"):
            print(f"FAIL page: {out['error']}")
            ok = False
        for item in out.get("results") or []:
            v = item.get("value")
            good = bool(v) and not (isinstance(v, dict) and v.get("error"))
            ok = ok and good
            print(f"{'PASS' if good else 'FAIL'} {item.get('js')} -> {json.dumps(v)[:200]}")
        if out.get("shot"):
            print(f"screenshot: {out['shot']}")
    task = os.environ.get("HERMES_KANBAN_TASK")
    if ok and a.done and task:
        summary = "\n".join(a.done) + (f"\nVerified: look-apply checks pass ({len(a.check)})" if a.check else "")
        env = {**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}
        cmd = ["hermes", "kanban", "complete", task, "--summary", summary, "--result", summary]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        if r.returncode:                                       # the worker holds the claim: close its run for it
            r = subprocess.run(cmd + ["--force"], capture_output=True, text=True, env=env, timeout=60)
        print(f"card {task} completed" if r.returncode == 0 else f"look-apply: couldn't complete {task}: {r.stderr[-300:]}")
    elif a.done and not ok:
        print("Not every check passed: the card stays open. Fix and run again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
