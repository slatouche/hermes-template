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
- Structure, on a look (the app stays the app; the edits are listed in the look's dom.json and look-runtime.js
  keeps them true while the app redraws and the owner navigates; a moved button still works):
    --move '<what> -> before|after|into|start <where>'      --text '<what> => <new text>'
    --insert 'before|after|into|start <where> => <markup>'  --attr '<what> @<name> => <value>' (value `-` removes)
  `--on '<regex>'` after any payload limits that edit to matching screens (location.pathname + hash), e.g. '#/deck'.
  On a --dir folder (a prototype) edit its files instead: `--in-file pages/deck.html` points --html-in/--html-out at
  one of the folder's files (default index.html).
- When the edits are in, the page is opened in the team's warm browser and a screenshot saved (`--see <selector>`
  crops it to what changed) and looked at: it prints an `eye:` verdict (did each edit land, is anything off; --ask asks
  something specific). That look is the check; --check is only for a number.
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


def mockup_serves(folder):
    """Is this folder the prototype the mockup serves (mockup.sh proto)?"""
    try:
        txt = (SCRIPTS / "mockups.conf").read_text(encoding="utf-8")
    except OSError:
        return False
    m = re.search(r"^[^#\n]*\|-\|[^\n]*--directory\s+(\S+)", txt, re.M)
    return bool(m) and pathlib.Path(m.group(1)).resolve() == folder.resolve()


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


STRUCT = ("move", "text", "insert", "attr")
WHERE = ("before", "after", "into", "start")


def struct_op(ed):
    """One structural edit as a dom.json entry. Markup is plain: no scripts, handlers or javascript: URLs."""
    if ed.get("move"):
        m = re.fullmatch(r"\s*(.+?)\s*->\s*(before|after|into|start)\s+(.+?)\s*", ed["move"])
        if not m:
            raise ValueError("--move is '<what> -> before|after|into|start <where>'")
        return {"op": "move", "sel": m.group(1), "where": m.group(2), "ref": m.group(3)}
    if ed.get("text"):
        m = re.fullmatch(r"\s*(.+?)\s*=>\s*(.*)", ed["text"], re.S)
        if not m:
            raise ValueError("--text is '<what> => <new text>'")
        return {"op": "text", "sel": m.group(1), "text": m.group(2)}
    if ed.get("insert"):
        m = re.fullmatch(r"\s*(before|after|into|start)\s+(.+?)\s*=>\s*(.+)", ed["insert"], re.S)
        if not m:
            raise ValueError("--insert is 'before|after|into|start <where> => <markup>'")
        if re.search(r"<script|javascript:|\son[a-z]+\s*=", m.group(3), re.I):
            raise ValueError("that markup isn't safe to add (a script, javascript: or an inline handler)")
        return {"op": "insert", "where": m.group(1), "ref": m.group(2), "html": m.group(3)}
    m = re.fullmatch(r"\s*(.+?)\s*@([\w-]+)\s*=>\s*(.*)", ed["attr"], re.S)
    if not m or m.group(2).lower().startswith("on") or "javascript:" in m.group(3).lower():
        raise ValueError("--attr is '<what> @<name> => <value>' (no on* handlers, no javascript:)")
    return {"op": "attr", "sel": m.group(1), "name": m.group(2), "value": None if m.group(3).strip() == "-" else m.group(3)}


def glance(a, check_args):
    """Open the page in the team's warm browser (the feedback inbox keeps it) and save a screenshot."""
    import urllib.request
    try:
        port = next((l.split("=", 1)[1].strip() for l in (HOME / ".hermes" / ".env").read_text().splitlines()
                     if l.startswith("API_SERVER_PORT=")), "")
    except OSError:
        port = ""
    if not port:
        return {"error": "no API_SERVER_PORT"}
    w, _, h = a.size.partition("x")
    body = {"op": "see", "target": f"demo{check_args[1]}" if check_args else "mockup", "route": a.page,
            "look": a.look or "", "selector": a.see, "width": int(w or 1440), "height": int(h or 900), "report": True,
            "ask": a.ask or ("These edits were just made: " + "; ".join(e.get("label") or "a change" for e in a.edits)
                             + ". Did each one land as described? Is anything misaligned, unevenly spaced or broken?")}
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{int(port) + 99}/look", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:                            # a glance that can't be taken never fails the edits
        return {"error": str(e)[:200]}


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
    ap.add_argument("--move", action=payload("move"), dest="edits", metavar="'SEL -> WHERE REF'")
    ap.add_argument("--text", action=payload("text"), dest="edits", metavar="'SEL => TEXT'")
    ap.add_argument("--insert", action=payload("insert"), dest="edits", metavar="'WHERE REF => HTML'")
    ap.add_argument("--attr", action=payload("attr"), dest="edits", metavar="'SEL @NAME => VALUE'")
    ap.add_argument("--on", action=payload("on"), dest="edits", metavar="REGEX",
                    help="limit the edit above to screens whose path+hash matches")
    ap.add_argument("--in-file", action=payload("file"), dest="edits", metavar="PATH",
                    help="the folder file the edit above's --html-in/--html-out changes (default index.html)")
    ap.add_argument("--see", default="", metavar="SELECTOR",
                    help="crop the closing screenshot to this element (default: the viewport)")
    ap.add_argument("--no-see", action="store_true", help="skip the closing screenshot")
    ap.add_argument("--ask", default="", metavar="QUESTION",
                    help="what to check in the closing screenshot (default: did the edits land, and is anything off)")
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
        check_page = "current"                        # not a look: check the page as it is served
        if slot:
            check_args = ["--demo", str(slot)]
        elif not mockup_serves(vd):
            print(f"look-apply: nothing serves {vd} (not the mockup, not a demo slot); pass --demo 1|2 for it", file=sys.stderr)
            return 2
    for ed in a.edits:
        if ed.get("html_out") and not ed.get("html_in"):
            print("look-apply: --html-out needs the --html-in it replaces", file=sys.stderr)
            return 2
        kinds = [k for k in ("css", "html_in", "move", "text", "insert", "attr") if ed.get(k)]
        if len(kinds) > 1:
            print("look-apply: one payload per --edit: --css, --html-in/--html-out, --move, --text, --insert or --attr",
                  file=sys.stderr)
            return 2
        if kinds and kinds[0] in STRUCT and not a.look:
            print("look-apply: --move/--text/--insert/--attr are for a look on the app; in a --dir folder edit its files "
                  "(--html-in/--html-out, with --in-file for a page)", file=sys.stderr)
            return 2
    if not a.edits and not sys.stdin.isatty():
        css = sys.stdin.read().strip()
        if css:
            a.edits = [{"label": a.label, "css": css}]        # the older form: one block on stdin
    edits = [ed for ed in a.edits if ed.get("css") or ed.get("html_in") or any(ed.get(k) for k in STRUCT)]
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
        elif any(ed.get(k) for k in STRUCT):                  # structure on a look: one more entry in its dom.json
            try:
                op = struct_op(ed)
            except ValueError as e:
                print(f"look-apply: {e}", file=sys.stderr)
                return 2
            domf = vd / "dom.json"
            ops = json.loads(domf.read_text(encoding="utf-8")) if domf.exists() else []
            n = 1 + max([int(o["id"][1:]) for o in ops if re.fullmatch(r"e\d+", str(o.get("id", "")))] or [0])
            op = {"id": f"e{n}", **op, **({"on": ed["on"]} if ed.get("on") else {}), "label": label}
            ops.append(op)
            tmp = domf.with_suffix(".tmp")
            tmp.write_text(json.dumps(ops, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(domf)
            where_ = f"{domf.name} ({op['op']})"
        else:                                                 # markup: one exact, unique replacement in a folder file
            old, new = ed["html_in"], ed["html_out"]
            idx = vd / "index.html"
            if ed.get("file"):
                idx = (vd / ed["file"]).resolve()
                if not idx.is_relative_to(vd.resolve()) or not idx.is_file():
                    print(f"look-apply: --in-file {ed['file']!r} isn't a file in {vd}", file=sys.stderr)
                    return 2
            where_ = str(idx.relative_to(vd.resolve())) if idx.is_relative_to(vd.resolve()) else idx.name
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
            bak = idx.with_name(idx.name + f".bak-{datetime.datetime.now():%H%M%S}")     # a backup per file changed
            if not bak.exists():
                bak.write_text(text, encoding="utf-8")
            idx.write_text(text.replace(old, new, 1), encoding="utf-8")
            note = f" (backup {bak.name})"
        chip(card, f"edit {i} of {len(edits)} \u00b7 {label}", time.time() - t0)
        print(f"edit {i} of {len(edits)} saved to {where_}: {label or 'CSS'}{note}")
        if i < len(edits) and a.gap > 0:
            time.sleep(a.gap)                                 # saved one at a time, so the page shows each arrive
    ok = True
    if edits and not a.no_see:                                # the glance: the page as it is now, through the warm browser
        t0 = time.time()
        seen = glance(a, check_args)
        if seen.get("path"):
            print(f"see: {seen['path']}  ({seen.get('url', '')}, {time.time() - t0:.1f}s)")
        if seen.get("eye"):
            print("eye: " + seen["eye"].replace("\n", "\n     "))
        for r in seen.get("report") or []:
            if r.get("status") not in ("ok", "skipped (other screen)"):
                ok = False
                print(f"FAIL {r.get('id')} {r.get('op')}: {r.get('status')}")
        if seen.get("error"):
            print(f"(no screenshot: {seen['error']})")
        chip(card, "a look at the page", time.time() - t0)
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
