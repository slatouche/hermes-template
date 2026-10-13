#!/usr/bin/python3
"""function-notes.py: the running list of function and usage notes (vault/design/function-notes.md).

What the owner noticed about what the app does (something that doesn't work, a missing behaviour, a usage point
inside design feedback), noted in seconds and worked on properly later. The design view adds them as the owner gives
feedback; the Manager adds the ones raised in a chat and plans the list with the owner. Each item ends up under Done
saying where it went (a build, a card, or dropped and why).

  function-notes.py add "<note>" [--said "<owner's words>"] [--screen "#/x"] [--source chat] [--evidence "<line>"]...
  function-notes.py list [--json]                the open ones
  function-notes.py done F3 "<where it went>"     e.g. "build design-20261014-0910", "card t_ab12", "dropped: works as designed"
  --page <path>                                  another page (a test copy); default ~/vault/design/function-notes.md
"""
import argparse
import contextlib
import datetime
import json
import pathlib
import re
import sys

PAGE = pathlib.Path.home() / "vault" / "design" / "function-notes.md"
HEAD = """---
title: "Function notes"
type: note
status: active
owner: manager
updated: {day}
summary: "The owner's running notes on what the app does (problems, missing behaviour, usage), noted from the design view and chats; the Manager plans them with the owner."
tags: [design, backlog]
---
# Function notes

What the owner noticed about what the app does, noted as they gave feedback, so it can be worked on properly later.
The design view adds items (`function-notes.py add`); the Manager adds what the owner raises in a chat, plans the
open ones with them, and moves each to Done saying where it went (`function-notes.py done`). Nothing here is checked
yet: a note is what the owner said and saw, not a diagnosis.

## Open

## Done
"""
ITEM = re.compile(r"^- \[( |x)\] \*\*(F\d+)\*\* (.*)$")


def one_line(text, cap):
    return " ".join(str(text or "").split())[:cap]


@contextlib.contextmanager
def locked(page):
    """One writer at a time (the design view and the Manager can both add)."""
    lock = page.with_name(page.name + ".lock")
    page.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:                                    # not Linux: a single writer is assumed
            pass
        yield


def read(page):
    if not page.exists():
        return HEAD.format(day=datetime.date.today().isoformat())
    return page.read_text(encoding="utf-8")


def write(page, text):
    text = re.sub(r"^updated:.*$", f"updated: {datetime.date.today().isoformat()}", text, count=1, flags=re.M)
    tmp = page.with_name(page.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(page)


def blocks(text):
    """The page split into (head, [open item blocks], middle, [done item blocks], tail), each block its lines."""
    lines = text.split("\n")
    try:
        o = lines.index("## Open")
        d = lines.index("## Done")
    except ValueError:
        raise SystemExit("function-notes: the page has lost its '## Open' or '## Done' heading; put them back")

    def items(part):
        out, rest = [], []
        for ln in part:
            if ITEM.match(ln):
                out.append([ln])
            elif out and ln.startswith("  "):
                out[-1].append(ln)
            elif ln.strip():
                rest.append(ln)
        return out, rest
    op, op_rest = items(lines[o + 1:d])
    dn, dn_rest = items(lines[d + 1:])
    return lines[:o + 1], op, op_rest, dn, dn_rest


def assemble(head, op, op_rest, dn, dn_rest):
    out = head + [""] + op_rest + [ln for b in op for ln in b] + ([""] if op or op_rest else []) + ["## Done", ""]
    out += dn_rest + [ln for b in dn for ln in b]
    return "\n".join(out).rstrip("\n") + "\n"


def parse(block):
    m = ITEM.match(block[0])
    parts = [p.strip() for p in m.group(3).split(" · ")]
    item = {"id": m.group(2), "done": m.group(1) == "x", "note": parts[0], "screen": "", "when": "", "source": "",
            "said": "", "evidence": [], "outcome": ""}
    for p in parts[1:]:
        if p.startswith("#/"):
            item["screen"] = p
        elif re.match(r"\d{4}-\d\d-\d\d", p):
            item["when"] = p
        else:
            item["source"] = p
    for ln in block[1:]:
        k, _, v = ln.strip()[2:].partition(": ")
        if k == "said":
            item["said"] = v.strip('"')
        elif k == "went":
            item["outcome"] = v
        elif v:
            item["evidence"].append(f"{k}: {v}")
    return item


def add(note, said="", screen="", source="", evidence=(), page=PAGE):
    """Add an open item; returns its id (F<n>)."""
    page = pathlib.Path(page)
    with locked(page):
        head, op, op_rest, dn, dn_rest = blocks(read(page))
        used = [int(b[0].split("**F")[1].split("**")[0]) for b in op + dn]
        fid = f"F{max(used, default=0) + 1}"
        bits = [one_line(note, 300) or "(no note)"] + [x for x in (one_line(screen, 80), datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                                   one_line(source, 80)) if x]
        block = [f"- [ ] **{fid}** " + " · ".join(b.replace(" · ", ", ") for b in bits)]
        if said and one_line(said, 400) != one_line(note, 400):
            block.append(f'  - said: "{one_line(said, 400).replace(chr(34), chr(39))}"')
        block += [f"  - {one_line(e, 400)}" for e in evidence if one_line(e, 400)]
        op.append(block)
        write(page, assemble(head, op, op_rest, dn, dn_rest))
    return fid


def items(page=PAGE, done=False):
    page = pathlib.Path(page)
    if not page.exists():
        return []
    _, op, _, dn, _ = blocks(read(page))
    return [parse(b) for b in (dn if done else op)]


def close(fid, outcome, page=PAGE):
    """Move an open item to Done with where it went. False when there's no such open item."""
    page = pathlib.Path(page)
    with locked(page):
        head, op, op_rest, dn, dn_rest = blocks(read(page))
        hit = [b for b in op if ITEM.match(b[0]).group(2) == fid]
        if not hit:
            return False
        b = hit[0]
        op.remove(b)
        b[0] = b[0].replace("- [ ] ", "- [x] ", 1)
        dn.insert(0, b + [f"  - went: {one_line(outcome, 300)} ({datetime.date.today().isoformat()})"])
        write(page, assemble(head, op, op_rest, dn, dn_rest))
    return True


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", default=str(PAGE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("note")
    a.add_argument("--said", default="")
    a.add_argument("--screen", default="")
    a.add_argument("--source", default="chat")
    a.add_argument("--evidence", action="append", default=[])
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--done", action="store_true")
    d = sub.add_parser("done")
    d.add_argument("id")
    d.add_argument("outcome")
    o = ap.parse_args(argv)
    if o.cmd == "add":
        print(add(o.note, o.said, o.screen, o.source, o.evidence, o.page))
    elif o.cmd == "list":
        its = items(o.page, o.done)
        if o.json:
            print(json.dumps(its))
        else:
            print("\n".join(f"{i['id']}  {i['note']}" + (f"  ({i['screen']})" if i["screen"] else "")
                            + (f"  -> {i['outcome']}" if i["outcome"] else "") for i in its) or "(none)")
    elif o.cmd == "done":
        if not close(o.id, o.outcome, o.page):
            print(f"no open item {o.id}", file=sys.stderr)
            return 1
        print(f"{o.id} done: {o.outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
