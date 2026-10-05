#!/usr/bin/python3
"""retro-gate: decides whether the weekly retro is worth a Manager run, with no model (Hermes cron, Mondays).

Wakes the Manager only when there is evidence since the last retro:
  - 2+ cards sent back or blocked,
  - a skill written or changed by a bot,
  - a memory file over 85% full,
  - 10+ cards finished.
Otherwise the last line is {"wakeAgent": false} and the week costs nothing. When it wakes, the output is the
evidence pack the `retro` skill works from (card ids, skills, memory fill, test suite size, lessons count).
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HOME = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home())
H = HOME / ".hermes"
STATE = H / "profiles" / "manager" / "scripts" / ".retro-state.json"
NOW = time.time()


def kanban(*args):
    r = subprocess.run(["hermes", "kanban", *args, "--json"], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "")})
    try:
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except ValueError:
        return None


def main():
    try:
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
    except ValueError:
        state = {}
    since = state.get("last_retro", NOW - 7 * 86400)
    tasks = kanban("list") or []
    done = [t for t in tasks if t.get("status") == "done" and (t.get("completed_at") or 0) > since]
    troubled = []
    for t in tasks:
        if (t.get("created_at") or 0) < since - 14 * 86400:
            continue
        ev = (kanban("show", t["id"]) or {}).get("events", [])
        sb = sum(1 for e in ev if e.get("kind") == "changes_requested" and (e.get("created_at") or 0) > since)
        bl = sum(1 for e in ev if e.get("kind") == "blocked" and (e.get("created_at") or 0) > since)
        if sb or bl:
            troubled.append(f"{t['id']} '{(t.get('title') or '')[:50]}' ({t.get('assignee')}): {sb} send-back(s), {bl} block(s)")

    skills, seen = [], {}
    known = state.get("skills")                       # skill path -> content hash at the last retro (or setup)
    for prof in sorted((H / "profiles").glob("*")):
        root = prof / "skills"
        manifest = root / ".bundled_manifest"
        bundled = {l.split(":", 1)[0].strip() for l in manifest.read_text().splitlines()} if manifest.exists() else set()
        for sk in root.rglob("SKILL.md") if root.is_dir() else []:
            if any(part.startswith(".") for part in sk.relative_to(root).parts) or sk.parent.name in bundled:
                continue
            key = f"{prof.name}: {sk.parent.relative_to(root)}"
            seen[key] = hashlib.md5(sk.read_bytes()).hexdigest()
            if known is not None and known.get(key) != seen[key]:
                skills.append(key + (" (new)" if key not in known else " (changed)"))

    memory, full = [], False
    for prof in [H] + sorted((H / "profiles").glob("*")):
        name = "default" if prof == H else prof.name
        for fn, cap in (("MEMORY.md", 2200), ("USER.md", 1375)):
            p = prof / "memories" / fn
            if p.exists():
                pct = int(100 * p.stat().st_size / cap)
                memory.append(f"{name} {fn} {pct}%")
                full |= pct > 85

    model = subprocess.run(["hermes", "config", "get", "model.default"], capture_output=True, text=True,
                           env={**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "")}).stdout.strip().splitlines()
    model = model[-1].strip() if model else ""
    if "--baseline" in sys.argv:                      # setup / hire: today's skills and model are the starting point
        state["skills"] = seen
        state["model"] = model
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
        return 0
    model_changed = bool(model and state.get("model") and state["model"] != model)
    wake = len(troubled) >= 2 or bool(skills) or full or len(done) >= 10 or model_changed
    if not wake:
        print(json.dumps({"wakeAgent": False}))
        return 0
    lessons = H.parent / "vault" / "system" / "lessons.md"
    n_lessons = len(re.findall(r"^\d{4}-\d{2}-\d{2}", lessons.read_text(errors="replace"), re.M)) if lessons.exists() else 0
    tests = subprocess.run(["bash", "-c", "cd ~/workspace && git ls-files | grep -Ec '(^|/)(test_[^/]*\\.py|[^/]*_test\\.(py|go)|[^/]*\\.(test|spec)\\.[jt]sx?)$'"],
                           capture_output=True, text=True).stdout.strip() or "0"
    print(f"Retro evidence since {time.strftime('%Y-%m-%d', time.localtime(since))}:")
    print(f"- cards done: {len(done)}" + (": " + ", ".join(t['id'] for t in done[:15]) if done else ""))
    print("- cards with send-backs or blocks:" + ("" if troubled else " none"))
    for t in troubled[:15]:
        print(f"  - {t}")
    print("- bot-written skills new or changed:" + ("" if skills else " none"))
    for s in skills[:15]:
        print(f"  - {s}")
    print("- memory fill: " + ", ".join(memory))
    print(f"- test files tracked: {tests}; lessons: {n_lessons}/40")
    if model_changed:
        print(f"- MODEL CHANGED: {state['model']} -> {model}. Re-check skills (the retro skill's 'Model changed' step) and run every bot's eval.")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_retro": NOW, "skills": seen, "model": model or state.get("model")}))
    print(json.dumps({"wakeAgent": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
