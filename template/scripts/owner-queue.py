#!/usr/bin/python3
"""What's waiting on the owner, across every board: one numbered list, no model tokens.

  owner-queue.py            the list (the /queue quick command in a Manager chat)
  owner-queue.py --json     the same as JSON (for manager-watch and scripts)

A card waits on the owner when it is blocked as `needs_input` (a decision, an answer, an approval) or
`capability` (something only a person can do: a secret, a purchase, a physical step), or sits in triage.
Those cards never time out and nothing re-runs them: the rest of the board carries on, and only cards that
depend on them wait. The Manager goes through this list with the owner one item at a time, records each
answer on its card and unblocks it.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

HOME = pathlib.Path.home()
ENV = {**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "")}


def kanban(*args):
    r = subprocess.run(["hermes", "kanban", *args, "--json"], capture_output=True, text=True, env=ENV)
    try:
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except ValueError:
        return None


def queue():
    items = []
    boards = kanban("boards", "list") or [{"slug": "default"}]
    for b in boards:
        if b.get("archived"):
            continue
        slug = b["slug"]
        for t in kanban("--board", slug, "list") or []:
            if t.get("status") not in ("blocked", "triage"):
                continue
            d = kanban("--board", slug, "show", t["id"]) or {}
            blocks = [e for e in d.get("events", []) if e.get("kind") == "blocked"]
            last = blocks[-1] if blocks else {}
            kind = (last.get("payload") or {}).get("kind") or ("triage" if t["status"] == "triage" else "")
            if kind not in ("needs_input", "capability", "triage"):
                continue                                   # dependency/transient: not the owner's to answer
            reason = ((last.get("payload") or {}).get("reason") or "").strip()
            since = last.get("created_at") or t.get("created_at") or time.time()
            items.append({"card": t["id"], "board": slug, "title": t.get("title", ""), "kind": kind,
                          "assignee": t.get("assignee"), "question": reason, "waiting_days": round((time.time() - since) / 86400, 1)})
    items.sort(key=lambda i: -i["waiting_days"])
    return items


def main():
    items = queue()
    if "--json" in sys.argv:
        print(json.dumps(items))
        return 0
    if not items:
        print("Nothing is waiting on you.")
        return 0
    label = {"needs_input": "decision", "capability": "your hands", "triage": "triage"}
    print(f"Waiting on you: {len(items)}  (answer in any order: \"1: yes\", \"2: B\", or ask the Manager to go through them)\n")
    for n, i in enumerate(items, 1):
        where = "" if i["board"] == "default" else f" [{i['board']}]"
        q = " ".join(i["question"].split())
        print(f"{n}. {i['title']}{where} ({label[i['kind']]}, {i['card']}, {i['waiting_days']:g} d)")
        if q:
            print(f"   {q[:400]}{'…' if len(q) > 400 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
