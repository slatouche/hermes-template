#!/usr/bin/python3
"""state-pack.py: the project's state in a few hundred words, read in about a second, with no model.

What the Manager would otherwise spend several steps reading at the start of a reply: the status page's fields,
the board (running, next, blocked), the open build notes, the owner's queue, open builds and the last log lines. The Manager's
`state-pack` plugin adds it to each chat message when it has changed, so "where are we?" or "what needs me?"
is answered from it in one step.

  state-pack.py            the pack (plain text)
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HOME = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home())
ENV = dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", ""))
ENV.pop("HERMES_KANBAN_BOARD", None)
WAITING = ("needs_input", "capability")


def age(ts):
    if not ts:
        return ""
    s = int(time.time() - ts)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m"


def status_fields():
    """The status page's frontmatter: phase, gate, blockers and what waits on the owner."""
    try:
        text = (HOME / "vault" / "00-status.md").read_text(errors="replace")
    except OSError:
        return []
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    fm, out, key = (m.group(1) if m else ""), [], None
    for line in fm.splitlines():
        k = re.match(r"^(phase|active_gate|blockers|waiting_on_owner):\s*(.*)$", line)
        if k:
            key = k.group(1)
            if k.group(2).strip() not in ("", "[]"):
                out.append(f"{key}: {k.group(2).strip()}")
            elif k.group(2).strip() == "[]":
                key = None
            continue
        if key and re.match(r"^\s+-\s+", line):
            out.append(f"  {key}: {line.strip()[2:].strip().strip(chr(34))[:120]}")
        elif not line.startswith(" "):
            key = None
    return out


def board():
    try:
        r = subprocess.run(["hermes", "kanban", "list", "--json"], capture_output=True, text=True, timeout=20, env=ENV)
        return json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def build_notes():
    """The open items on the running list of function and usage notes (build-notes.py reads the page)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_notes", pathlib.Path(__file__).resolve().parent / "build-notes.py")
        fn = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fn)
        return fn.items(HOME / "vault" / "design" / "build-notes.md")
    except (OSError, SystemExit, AttributeError, ImportError):
        return []


def builds():
    out = []
    for p in sorted((HOME / ".hermes" / "builds").glob("*.json")):
        try:
            b = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if b.get("state") in ("planning", "building", "checking", "reviewing", "landing", "stuck"):
            out.append(f"{b['slug']}: {b['state']} - {b.get('step') or ''}"[:160])
    return out


def main():
    lines = [f"[Project state at {time.strftime('%Y-%m-%d %H:%M')}, from state-pack.py: answer status and queue "
             f"questions from this; read further only for what it doesn't cover]"]
    lines += status_fields()
    cards = board()
    if cards is None:
        lines.append("board: couldn't be read just now")
    else:
        run = sorted([c for c in cards if c.get("status") == "running"], key=lambda c: c.get("started_at") or 0)
        nxt = [c for c in cards if c.get("status") in ("ready", "todo")]
        blocked = [c for c in cards if c.get("status") == "blocked"]
        review = [c for c in cards if c.get("status") == "review"]
        lines.append(f"board: {len(run)} running, {len(nxt)} next, {len(review)} in review, {len(blocked)} blocked")
        for c in run:
            lines.append(f"  running {c['id']} {c.get('assignee')}: {(c.get('title') or '')[:60]} ({age(c.get('started_at'))})")
        for c in nxt[:5]:
            lines.append(f"  next {c['id']} {c.get('assignee')}: {(c.get('title') or '')[:60]}")
        for c in blocked[:8]:
            lines.append(f"  blocked {c['id']} {c.get('assignee')}: {(c.get('title') or '')[:60]}")
    notes = build_notes()
    if notes:
        lines.append(f"build notes open: {len(notes)} (vault/design/build-notes.md; plan with the owner when they ask)")
        lines += [f"  {i['id']}: {i['note'][:90]}" for i in notes[-6:]]
    bs = builds()
    if bs:
        lines.append("builds: " + "; ".join(bs))
    try:                                                 # tidies applied in the last day: tell the owner in a line
        since = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 86400))
        tidies = [l[2:] for l in (HOME / "vault" / "system" / "optimiser" / "applied.md").read_text(errors="replace").splitlines()
                  if l.startswith("- ") and l[2:18] >= since]
        if tidies:
            lines.append("applied by the Optimiser's tidy since yesterday (tell the owner in one line):")
            lines += ["  " + t[:200] for t in tidies[-3:]]
    except OSError:
        pass
    try:
        log = [l for l in (HOME / "vault" / "log.md").read_text(errors="replace").splitlines() if re.match(r"^\d{4}-", l)]
        lines.append("last log lines:")
        lines += ["  " + l[:170] for l in log[-4:]]
    except OSError:
        pass
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
