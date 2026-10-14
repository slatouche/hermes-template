#!/usr/bin/python3
"""build-notes.py: the build notes, a running, consolidated list (vault/design/build-notes.md) of what the Manager,
Engineer and the rest need to know for the build.

What the owner noticed about what the app does, noted in seconds and worked on properly later. Each item has a kind:
function (what something should do, or something that doesn't work), usage (how they use it or move through the app),
feel (how it should feel or behave). The design view adds them as the owner gives
feedback; the Manager adds the ones raised in a chat and plans the list with the owner. Each item ends up under Done
saying where it went (a build, a card, or dropped and why).

  build-notes.py add "<note>" [--kind function|usage|feel] [--said "<owner's words>"] [--screen "#/x"] [--source chat]
                         [--evidence "<line>"]...
  build-notes.py list [--json]                the open ones
  build-notes.py done F3 "<where it went>"     e.g. "build design-20261014-0910", "card t_ab12", "dropped: works as designed"
  build-notes.py tidy [--days 30] [--dry]      keep it short and single (the vault sweep runs it every 15 min, no model):
                                               open items saying the same thing are merged into the older one (its
                                               words and evidence kept, the newer one done as "merged into F<n>"),
                                               and Done items older than --days move to build-notes-archive.md
  --page <path>                                  another page (a test copy); default ~/vault/design/build-notes.md
"""
import argparse
import contextlib
import datetime
import json
import pathlib
import re
import sys

PAGE = pathlib.Path.home() / "vault" / "design" / "build-notes.md"
HEAD = """---
title: "Build notes"
type: note
status: active
owner: manager
updated: {day}
summary: "The running, consolidated list of what the Manager, Engineer and the rest need to know for the build: how the app should work, be used and feel, from the owner's design view notes and chats; planned with the owner."
tags: [design, backlog]
---
# Build notes

What the owner noticed about what the app does, noted as they gave feedback, so it can be worked on properly later.
The design view adds items (`build-notes.py add`); the Manager adds what the owner raises in a chat, plans the
open ones with them, and moves each to Done saying where it went (`build-notes.py done`). Nothing here is checked
yet: a note is what the owner said and saw, not a diagnosis.

## Open

## Done
"""
ITEM = re.compile(r"^- \[( |x)\] \*\*(F\d+)\*\* (.*)$")
KINDS = ("function", "usage", "feel")


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
        raise SystemExit("build-notes: the page has lost its '## Open' or '## Done' heading; put them back")

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
    k = re.match(r"\((%s)\) (.*)$" % "|".join(KINDS), parts[0])
    item = {"id": m.group(2), "done": m.group(1) == "x", "kind": k.group(1) if k else "function",
            "note": k.group(2) if k else parts[0], "screen": "", "when": "", "source": "", "said": "", "evidence": [],
            "outcome": ""}
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


def add(note, said="", screen="", source="", evidence=(), page=PAGE, kind="function"):
    """Add an open item; returns its id (F<n>)."""
    kind = kind if kind in KINDS else "function"
    page = pathlib.Path(page)
    with locked(page):
        head, op, op_rest, dn, dn_rest = blocks(read(page))
        used = [int(b[0].split("**F")[1].split("**")[0]) for b in op + dn]
        fid = f"F{max(used, default=0) + 1}"
        bits = [f"({kind}) " + (one_line(note, 300) or "(no note)")] + [x for x in (one_line(screen, 80), datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
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


def same(a, b):
    """Two notes saying the same thing: most of their words in common (as the design view judges it)."""
    wa, wb = (set(re.findall(r"[a-z0-9]{3,}", x.lower())) for x in (a, b))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.75


ARCHIVE_HEAD = """---
title: "Build notes: archive"
type: note
status: active
owner: manager
updated: {day}
summary: "Build notes done more than a month ago, moved here from build-notes.md to keep that page short. Each says where it went."
tags: [design, backlog, archive]
---
# Build notes: archive

Done items from [[design/build-notes]], oldest at the bottom.
"""


def tidy(page=PAGE, days=30, dry=False):
    """Merge open items that say the same thing (into the older one: its line stays, the newer one's words and
    evidence are added under it, and the newer one goes to Done as merged); move Done items older than `days` to the
    archive page. -> (merged [(newer, older)], archived [ids])"""
    page = pathlib.Path(page)
    if not page.exists():
        return [], []
    with locked(page):
        head, op, op_rest, dn, dn_rest = blocks(read(page))
        kept, merged, closed = [], [], []
        for b in op:                                           # oldest first, as they were added
            it = parse(b)
            twin = next((k for k in kept if same(parse(k)["note"], it["note"])), None)
            if twin is None:
                kept.append(b)
                continue
            into = parse(twin)["id"]
            twin.append(f"  - merged {it['id']}: {it['note']}" + (f" · {it['screen']}" if it["screen"] and it["screen"] != parse(twin)["screen"] else ""))
            twin += [ln for ln in b[1:] if ln.strip()]
            closed.append([b[0].replace("- [ ] ", "- [x] ", 1)] + b[1:] + [f"  - went: merged into {into} ({datetime.date.today().isoformat()})"])
            merged.append((it["id"], into))
        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        old = []
        for b in dn:
            went = re.findall(r"\((\d{4}-\d\d-\d\d)\)\s*$", "\n".join(b), re.M)
            if went and datetime.date.fromisoformat(went[-1]) < cutoff:
                old.append(b)
        if (merged or old) and not dry:
            dn = closed + [b for b in dn if b not in old]
            write(page, assemble(head, kept, op_rest, dn, dn_rest))
            if old:
                arch = page.with_name(page.stem + "-archive.md")
                text = arch.read_text(encoding="utf-8") if arch.exists() else ARCHIVE_HEAD.format(day=datetime.date.today().isoformat())
                head_a, _, body = text.partition("\n# Build notes: archive\n")
                body_lines = body.split("\n")
                intro = body_lines[:2]                         # the blank line and the "Done items from" line
                rest = "\n".join(body_lines[2:]).strip("\n")
                text = (head_a + "\n# Build notes: archive\n" + "\n".join(intro) + "\n\n"
                        + "\n".join(ln for b in old for ln in b) + ("\n" + rest if rest else "") + "\n")
                write(arch, text)
    return merged, [parse(b)["id"] for b in old]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", default=str(PAGE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("note")
    a.add_argument("--said", default="")
    a.add_argument("--kind", default="function", choices=KINDS)
    a.add_argument("--screen", default="")
    a.add_argument("--source", default="chat")
    a.add_argument("--evidence", action="append", default=[])
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--done", action="store_true")
    d = sub.add_parser("done")
    d.add_argument("id")
    d.add_argument("outcome")
    t = sub.add_parser("tidy")
    t.add_argument("--days", type=int, default=30)
    t.add_argument("--dry", action="store_true")
    o = ap.parse_args(argv)
    if o.cmd == "add":
        print(add(o.note, o.said, o.screen, o.source, o.evidence, o.page, o.kind))
    elif o.cmd == "list":
        its = items(o.page, o.done)
        if o.json:
            print(json.dumps(its))
        else:
            print("\n".join(f"{i['id']}  ({i['kind']}) {i['note']}" + (f"  ({i['screen']})" if i["screen"] else "")
                            + (f"  -> {i['outcome']}" if i["outcome"] else "") for i in its) or "(none)")
    elif o.cmd == "done":
        if not close(o.id, o.outcome, o.page):
            print(f"no open item {o.id}", file=sys.stderr)
            return 1
        print(f"{o.id} done: {o.outcome}")
    elif o.cmd == "tidy":                                     # silent when there's nothing to do (the sweep's rule)
        merged, archived = tidy(o.page, o.days, o.dry)
        for new, old in merged:
            print(f"{'would merge' if o.dry else 'merged'} {new} into {old}")
        if archived:
            print(f"{'would archive' if o.dry else 'archived'} {len(archived)} done item(s): {', '.join(archived)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
