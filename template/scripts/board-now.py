#!/usr/bin/python3
"""What the board is doing right now: every live card, how long it has run, and its last step.

  board-now.py            running cards (the answer to "why is it slow?")
  board-now.py --all      also whatever is ready, blocked or in review

Read-only. No model, no tokens: it reads the kanban JSON and the workers' own logs,
so an answer costs nothing and takes under a second.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HOME = pathlib.Path.home()
ENV = {**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "")}
LOGS = HOME / ".hermes" / "kanban" / "logs"
BOX = "┌│└┊─"
STEP_CHARS = 60                            # a step is a glance, not a paragraph (matches the page chip's STEP_CHARS)
STEP_DONE_RE = re.compile(r"\d+\.\d+s\b")   # a finished tool row carries its duration; a `preparing X…` row does not


def kanban(*args):
    r = subprocess.run(["hermes", "kanban", *args, "--json"], capture_output=True, text=True, env=ENV)
    try:
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except ValueError:
        return None


def step(card):
    """The worker's last *finished* progress line and how long its log has been quiet: the last `┊` row
    carrying its duration, with transient `preparing <tool>…` rows skipped (the same read the page chip's
    round_step() makes), so the board names the work rather than the tool."""
    f = LOGS / f"{card}.log"
    if not f.exists():
        return "", None
    idle = time.time() - f.stat().st_mtime
    try:
        txt = f.read_bytes()[-6000:].decode("utf-8", "replace")
    except OSError:
        return "", idle
    steps = [l.strip() for l in txt.splitlines() if l.strip().startswith("┊")]
    done = [l for l in steps if STEP_DONE_RE.search(l)]
    tail = ""
    if done:
        tail = done[-1].strip("┊ ").strip()
    elif steps:
        tail = steps[-1].strip("┊ ").strip()
    else:
        for l in reversed(txt.splitlines()):
            l = l.strip().strip(BOX).strip()
            if l:
                tail = l
                break
    return tail[:STEP_CHARS], idle


def age(ts):
    if not ts:
        return "—"
    s = int(time.time() - ts)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def main():
    live = kanban("list") or []
    running = [t for t in live if t.get("status") == "running"]
    others = [t for t in live if t.get("status") in ("ready", "todo", "blocked", "review", "triage")]

    print(f"now {datetime.datetime.now().strftime('%H:%M:%S')}   running {len(running)}")
    for t in sorted(running, key=lambda t: t.get("started_at") or 0):
        tail, idle = step(t["id"])
        stalled = "  ⚠ QUIET" if idle is not None and idle > 90 else ""
        print(f"  {t['id']}  {t.get('assignee',''):9.9} {t.get('title','')[:44]:44} ran {age(t.get('started_at')):>7}  idle {age(time.time()-idle if idle is not None else None):>6}{stalled}")
        if tail:
            print(f"      └ {tail}")
    if "--all" in sys.argv or not running:
        for t in others:
            print(f"  {t['id']}  {t['status']:8} {t.get('assignee',''):9.9} {t.get('title','')[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
