#!/usr/bin/python3
"""look-apply.py: a design round in one step. Adds this round's CSS to the look (or a served design folder), checks
it on the page, and closes the round's card when every check passes, so the Designer designs and proves it in one call.

  look-apply.py <look> --card <round card id> [--demo 1|2] [--page '<path#route>'] [--size WxH] [--label "<the round>"]
                --edit "<what this edit does>" --css '<rules>' [--edit ... --css ...]
                [--check '<js expression>' ...] [--done "<a line per note>" ...]
  look-apply.py <look> [--page ...] [--size ...] [--label "..."]
                [--check ...] [--done ...]  <<'CSS'
  ...the round's CSS as one block...
  CSS

  look-apply.py --dir vault/design/<folder> [--demo 1|2] [--page '/'] [--size WxH] [--label "..."]
                [--edit "<what this edit does>" --css '<rules>' ...] [--check ...] [--done ...]

- CSS is appended to vault/design/variants/<look>/style.css — or, with --dir, the folder's own style.css — as blocks
  headed with the label (later rules win, so nothing earlier has to be found and edited mid-round; the wrap-up tidies).
- `--edit` opens one edit of the round and the payload flag after it fills it in, in order: `--css '<rules>'` appends
  CSS, `--html-in '<text there now>' --html-out '<text that replaces it>'` replaces markup in the folder's own
  index.html (the text must match exactly once; one .bak-<HHMMSS> of that file is kept per call). Each edit is saved on
  its own, so the page updates as edit 1, 2, 3 land (the owner watches them arrive) and the card's chip names each:
  a note that needs markup is still one command, never a hand-patch. Without --edit, CSS on stdin is one block.
- `--dir <folder>` is for a design folder that is not a look: a page served on a demo slot, e.g. vault/design/<folder>/.
  Its CSS is the folder's own style.css, appended the same way, and the checks run on the demo slot that serves
  it (found off its systemd unit; `--demo 1|2` says which if that fails). A round on it is still one call.
- Each --check is a JavaScript expression evaluated on the look's page at that size (look-check.sh): it passes when
  its value is truthy. Typical: `getComputedStyle(document.querySelector('X')).color === 'rgb(...)'`,
  `!document.querySelector('X')`, `document.querySelector('X').naturalWidth > 0`.
- With --done and every check passing, the card is completed with those lines: `--card` names the card and
  `--board` the board it is on (the round card carries both), so closing it never depends on the environment.
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
import time

HOME = pathlib.Path.home()
SCRIPTS = HOME / ".hermes" / "scripts"
VARIANTS = HOME / "vault" / "design" / "variants"
DESIGN = HOME / "vault" / "design"
UNITS = HOME / ".config" / "systemd" / "user"


def demo_slot_for(folder):
    """Which demo slot (1 or 2) serves this folder, read off its systemd unit; None when none does. demo.sh writes
    the unit, so a folder shown with `demo.sh show <n> <folder>` is found without anyone repeating the slot."""
    for n in (1, 2):
        try:
            txt = (UNITS / f"design-demo-{n}.service").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"--directory\s+(\S+)", txt)
        if m and pathlib.Path(m.group(1)).resolve() == folder.resolve():
            return n
    return None


class Edit(argparse.Action):
    """--edit opens one edit of the round; the payload flags after it fill it in, so the command reads in order:
    `--edit 'note 1: ...' --css '...' --edit 'note 2: ...' --html-in '<what is there>' --html-out '<what replaces it>'`."""
    def __call__(self, parser, ns, value, option_string=None):
        ns.edits.append({"label": value})


def payload(key):
    """A payload flag belongs to the --edit above it (an implicit, unlabelled edit if there is none yet)."""
    class Payload(argparse.Action):
        def __call__(self, parser, ns, value, option_string=None):
            if not ns.edits:
                ns.edits.append({"label": ""})
            ns.edits[-1][key] = value
    return Payload


def chip(task, label, secs):
    """Name this step in the chip the owner is watching. The page reads the card's own log (feedback-inbox.round_step),
    so a round that does everything in one call still narrates each edit as it lands instead of going quiet."""
    if not task:
        return
    f = HOME / ".hermes" / "kanban" / "logs" / f"{task}.log"
    if not f.exists():
        return
    try:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"\n  \u250a \u270e {label}   {secs:.1f}s\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description="Add a round's CSS to a look or a served design folder, check it, close the card.")
    ap.add_argument("look", nargs="?")
    ap.add_argument("--dir", dest="folder", default=None,
                    help="a design folder served on a demo slot (vault/design/<folder>): its own style.css, checks on the demo's review link")
    ap.add_argument("--demo", type=int, choices=(1, 2), default=None,
                    help="which demo slot serves --dir (read off its systemd unit when omitted)")
    ap.add_argument("--page", default="/")
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--label", default="")
    ap.add_argument("--card", default="",
                    help="the round card this command works and closes (defaults to $HERMES_KANBAN_TASK)")
    ap.add_argument("--board", default=os.environ.get("HERMES_KANBAN_BOARD", ""), metavar="SLUG",
                    help="the board that card is on (defaults to $HERMES_KANBAN_BOARD). The round card names it, "
                         "so closing the card never depends on what the environment happens to hold")
    ap.set_defaults(edits=[])                      # one ordered list of edits, each with one payload
    ap.add_argument("--edit", action=Edit, dest="edits", metavar="LABEL",
                    help="what one edit of this round does; the next --css or --html-in/--html-out belongs to it")
    ap.add_argument("--css", action=payload("css"), dest="edits", metavar="RULES",
                    help="the CSS this edit appends to the page's style.css")
    ap.add_argument("--html-in", action=payload("html_in"), dest="edits", metavar="TEXT",
                    help="markup this edit replaces: must occur exactly once in the page's index.html")
    ap.add_argument("--html-out", action=payload("html_out"), dest="edits", metavar="TEXT",
                    help="the markup that replaces --html-in")
    ap.add_argument("--gap", type=float, default=1.5,
                    help="seconds between the round's edits, so the page shows each one land (default 1.5)")
    ap.add_argument("--check", action="append", default=[])
    ap.add_argument("--done", action="append", default=[])
    a = ap.parse_args()
    if bool(a.look) == bool(a.folder):
        ap.error("give a look or --dir <folder> under vault/design")
    check_args = []
    if a.look:
        vd = VARIANTS / a.look
        if not re.fullmatch(r"[\w-]+", a.look) or not vd.is_dir():
            print(f"look-apply: no look {a.look!r} in {VARIANTS}", file=sys.stderr)
            return 2
        check_page = a.look
    else:
        vd = pathlib.Path(a.folder).expanduser().resolve()
        if not vd.is_dir() or not vd.is_relative_to(DESIGN.resolve()):
            print(f"look-apply: --dir needs an existing folder under {DESIGN} (got {a.folder!r})", file=sys.stderr)
            return 2
        slot = a.demo or demo_slot_for(vd)
        if not slot:
            print(f"look-apply: nothing serves {vd} on a demo slot; pass --demo 1|2 for it", file=sys.stderr)
            return 2
        check_page = "current"                        # not a look: check the page as it is served
        check_args = ["--demo", str(slot)]
    for ed in a.edits:
        if ed.get("html_out") and not ed.get("html_in"):
            print("look-apply: --html-out needs the --html-in it replaces", file=sys.stderr)
            return 2
        if ed.get("css") and ed.get("html_in"):
            print("look-apply: one payload per --edit: either --css, or --html-in with --html-out", file=sys.stderr)
            return 2
    if not a.edits and not sys.stdin.isatty():
        css = sys.stdin.read().strip()
        if css:
            a.edits = [{"label": a.label, "css": css}]        # the older form: one block on stdin
    edits = [ed for ed in a.edits if ed.get("css") or ed.get("html_in")]
    card = a.card or os.environ.get("HERMES_KANBAN_TASK", "")     # the command names its own card: the env can be empty
    cssf, idx, bak = vd / "style.css", vd / "index.html", None
    try:
        shown_css = cssf.relative_to(HOME)
    except ValueError:                                        # a --dir outside home: show it as given
        shown_css = cssf
    for i, ed in enumerate(edits, 1):
        label = ed.get("label", "")
        t0, note = time.time(), ""
        if ed.get("css"):
            css, where_ = ed["css"], shown_css
            if css.count("{") != css.count("}") or re.search(r"</|javascript:|@import", css, re.I):
                print("look-apply: that CSS isn't safe to add (unbalanced braces, '</', javascript: or @import)", file=sys.stderr)
                return 2
            head = f"/* round {card} {datetime.datetime.now():%Y-%m-%d %H:%M}"
            head += (f": {label.replace('*/', '')}" if label else "") + " */"
            with open(cssf, "a", encoding="utf-8") as fh:      # appended, never rewritten: others may add while we work
                fh.write(f"\n{head}\n{css}\n")
        else:                                                 # markup: one exact, unique replacement in the page itself
            old, new = ed["html_in"], ed["html_out"]
            where_ = idx.name
            if not idx.exists():
                print(f"look-apply: no {idx} to change", file=sys.stderr)
                return 2
            if re.search(r"<script|javascript:|on[a-z]+\s*=", new, re.I):
                print("look-apply: that markup isn't safe to add (a script, javascript: or an inline handler)", file=sys.stderr)
                return 2
            text = idx.read_text(encoding="utf-8")
            n = text.count(old)
            if n != 1:
                print(f"look-apply: --html-in matches {n} times in {idx} - it must match exactly once; read the file and copy its text exactly",
                      file=sys.stderr)
                return 2
            if bak is None:                                   # one backup per call, before the first markup edit
                bak = idx.with_name(idx.name + f".bak-{datetime.datetime.now():%H%M%S}")
                bak.write_text(text, encoding="utf-8")
            idx.write_text(text.replace(old, new, 1), encoding="utf-8")
            note = f" (backup {bak.name})"
        chip(card, f"edit {i} of {len(edits)} \u00b7 {label}", time.time() - t0)
        print(f"edit {i} of {len(edits)} saved to {where_}: {label or 'CSS'}{note}")
        if i < len(edits) and a.gap > 0:
            time.sleep(a.gap)                                 # saved one at a time, so the page shows each arrive
    ok = True
    if a.check:
        t0 = time.time()
        r = subprocess.run([str(SCRIPTS / "look-check.sh"), check_page, a.page, "--size", a.size, *check_args,
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
        chip(card, f"{'checks pass' if ok else 'a check failed'} ({len(a.check)})", time.time() - t0)
    task = card
    if ok and a.done and task:
        summary = "\n".join(a.done) + (f"\nVerified: look-apply checks pass ({len(a.check)})" if a.check else "")
        env = {**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}
        if a.board:                                       # the card's own board, not whatever is ambient:
            env["HERMES_KANBAN_BOARD"] = a.board          # a delegate_task child has no board of its own
        cmd = ["hermes", "kanban", "complete", task, "--summary", summary, "--result", summary]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        if r.returncode:                                       # the worker holds the claim: close its run for it
            r = subprocess.run(cmd + ["--force"], capture_output=True, text=True, env=env, timeout=60)
        print(f"card {task} completed" if r.returncode == 0
              else f"look-apply: couldn't complete {task} (board {a.board or 'ambient'}): {r.stderr[-300:]}")
    elif a.done and not ok:
        print("Not every check passed: the card stays open. Fix and run it again.")
    elif a.done and not task:
        print("No card to close: pass --card <id> (or run inside the card's worker) and the command closes it itself.",
              file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
