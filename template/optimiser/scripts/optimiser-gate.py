#!/usr/bin/python3
"""optimiser-gate: the evidence pack for the Optimiser's nightly run, and whether it's worth a run at all. No model.

Reads, since the last run: the board (cards done, send-backs, blocks), every bot's own log (each card's model steps,
model and tool seconds, largest context; slow tool calls), the owner's chat turns (how long each reply took), the
builds (~/.hermes/builds: stages, failures), bot-written skills, memory fill and the model.
Wakes the Optimiser only when there is something to look at:
  - an outlier card (over twice its bot's median and over 10 min), a slow tool call (over 20 s), a big context;
  - a card shape repeated 3+ times (a step done per piece of work that may belong once, or in a script);
  - work done by the wrong role (a Tester or Designer card that builds);
  - the owner's replies slow (p90 over 3 min), a send-back or a block, a build that failed or got stuck;
  - a skill written or changed by a bot, a memory over 85% full, a model change, or 10+ cards done;
  - a file every bot loads (AGENTS.md: 8 KB; a SOUL: 10 KB) at 90% of its limit: what to move or merge is a proposal.
Every night it also picks tonight's tidy slice (tidy.py slices: the team rules, one bot's SOUL source, skills and
memory, the vault's system pages): the next one in the rotation whose files changed since it was last audited. The
Optimiser rewrites it so each thing is said once, in the place it belongs, with nothing lost (the optimise skill).
A project where nothing changed since every slice's last audit has no tidy to do.
Otherwise the last line is {"wakeAgent": false} and the night costs nothing.

  optimiser-gate.py              the pack (Hermes cron, optimiser profile, nightly)
  optimiser-gate.py --baseline   setup / hire: today's skills and model are the starting point
"""
import collections
import datetime
import hashlib
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import time

HOME = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home())
H = HOME / ".hermes"
STATE = pathlib.Path(os.environ.get("OPTIMISER_STATE") or H / "profiles" / "optimiser" / "scripts" / ".optimiser-state.json")
NOW = time.time()
ENV = {**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "")}
ENV.pop("HERMES_KANBAN_BOARD", None)
API = re.compile(r"API call #\d+.*?in=(\d+).*?out=(\d+).*?latency=([\d.]+)s")
TOOL = re.compile(r"tool (\w+) completed \(([\d.]+)s")
CHAT = re.compile(r"(?:tui|desktop) turn finished.*?duration=([\d.]+)s")
TURN = re.compile(r"conversation turn:.*?platform=(\w+).*?msg='(.{0,70})")
BUILD_WORDS = re.compile(r"^(build|add|fix|implement|land|wire|serve|make)\b", re.I)


def kanban(*args):
    r = subprocess.run(["hermes", "kanban", *args, "--json"], capture_output=True, text=True, env=ENV)
    try:
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except ValueError:
        return None


def ts(line):
    try:
        return datetime.datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def read_log(prof, since):
    """One bot's log since a time: model calls, tool calls, the owner's chat turns."""
    calls, tools, chats, last_msg = [], [], [], None
    for f in sorted((prof / "logs").glob("agent.log*")):
        try:
            fh = f.open(errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if line[:4] != "20" + line[2:4] or len(line) < 20:
                    continue
                t = ts(line)
                if t is None or t < since:
                    continue
                m = API.search(line)
                if m:
                    calls.append((t, int(m[1]), int(m[2]), float(m[3])))
                    continue
                m = TOOL.search(line)
                if m:
                    tools.append((t, m[1], float(m[2])))
                    continue
                m = TURN.search(line)
                if m:
                    last_msg = m[2] if m[1] in ("desktop", "tui", "discord", "telegram") else None
                    continue
                m = CHAT.search(line)
                if m and last_msg is not None:
                    chats.append((t, float(m[1]), last_msg))
    return calls, tools, chats


def shape(title):
    """A card's shape: its title without ids, numbers, quotes and the specific thing after a colon."""
    t = re.sub(r"\(.*?\)|t_[0-9a-f]+|\d+|['\"`].*?['\"`]", "", title or "").split(":")[0]
    return " ".join(re.findall(r"[A-Za-z]+", t)[:3]).lower()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


def main():
    try:
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
    except ValueError:
        state = {}
    since = state.get("last_run", NOW - 7 * 86400)

    # bot-written skills (template skills under project/ are the template's, changed by proposal only), memory, model
    skills, seen = [], {}
    known = state.get("skills")
    for prof in sorted((H / "profiles").glob("*")):
        root = prof / "skills"
        manifest = root / ".bundled_manifest"
        bundled = {l.split(":", 1)[0].strip() for l in manifest.read_text().splitlines()} if manifest.exists() else set()
        for sk in root.rglob("SKILL.md") if root.is_dir() else []:
            rel = sk.parent.relative_to(root)
            if any(part.startswith(".") for part in rel.parts) or sk.parent.name in bundled or rel.parts[0] == "project":
                continue
            key = f"{prof.name}: {rel}"
            seen[key] = hashlib.md5(sk.read_bytes()).hexdigest()
            if known is not None and known.get(key) != seen[key]:
                skills.append(key + (" (new)" if key not in known else " (changed)"))
    memory, full = [], False
    for prof in [H] + sorted((H / "profiles").glob("*")):
        for fn, cap in (("MEMORY.md", 2200), ("USER.md", 1375)):
            p = prof / "memories" / fn
            if p.exists():
                fill = int(100 * p.stat().st_size / cap)
                memory.append(f"{'default' if prof == H else prof.name} {fn} {fill}%")
                full |= fill > 85
    # tonight's tidy: the next slice (in rotation) whose files changed since its last audit
    tidy, tidied = None, dict(state.get("tidied") or {})
    try:
        sl = json.loads(subprocess.run(["/usr/bin/python3", str(H / "scripts" / "tidy.py"), "slices", "--json"],
                                       capture_output=True, text=True, timeout=60, env=ENV).stdout or "{}")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        sl = {}
    order = list(sl)
    start = int(state.get("tidy_next", 0)) % len(order) if order else 0
    for k in order[start:] + order[:start]:
        h = hashlib.md5("".join(f + ((HOME / f).read_text(errors="replace") if (HOME / f).exists() else "")
                                for f in sl[k]).encode()).hexdigest()
        if tidied.get(k) != h:
            tidy, tidied[k] = (k, sl[k]), h
            break
    tidy_next = (order.index(tidy[0]) + 1) if tidy else state.get("tidy_next", 0)

    # what every session loads: its size against the limit, and growth since the last run
    sizes, near = {}, []
    loaded = [("AGENTS.md", HOME / "workspace" / "AGENTS.md", 8192)] + [
        (f"{p.name} SOUL", p / "SOUL.md", 10000) for p in sorted((H / "profiles").glob("*")) if (p / "SOUL.md").exists()]
    for name, f, cap in loaded:
        if f.exists():
            n = f.stat().st_size
            sizes[name] = n
            if n >= 0.9 * cap:
                was = (state.get("sizes") or {}).get(name)
                near.append(f"{name}: {n}/{cap} bytes ({100 * n // cap}%)" + (f", {n - was:+d} since the last run" if was else ""))
    model = subprocess.run(["hermes", "config", "get", "model.default"], capture_output=True, text=True, env=ENV).stdout.strip().splitlines()
    model = model[-1].strip() if model else ""
    if "--baseline" in sys.argv:
        save({**state, "skills": seen, "model": model, "last_run": NOW, "sizes": sizes, "tidied": tidied})
        return 0
    model_changed = bool(model and state.get("model") and state["model"] != model)

    # the board
    tasks = kanban("list", "--archived") or []
    done = [t for t in tasks if t.get("status") in ("done", "archived") and (t.get("completed_at") or 0) > since
            and t.get("started_at")]
    troubled = []
    for t in tasks:
        if max(t.get("completed_at") or 0, t.get("started_at") or 0, t.get("created_at") or 0) < since:
            continue
        ev = (kanban("show", t["id"]) or {}).get("events", [])
        sb = sum(1 for e in ev if e.get("kind") == "changes_requested" and (e.get("created_at") or 0) > since)
        bl = sum(1 for e in ev if e.get("kind") == "blocked" and (e.get("created_at") or 0) > since
                 and not (t.get("title") or "").startswith("Owner:"))                 # an owner question waits by design
        if sb or bl:
            troubled.append(f"{t['id']} '{(t.get('title') or '')[:50]}' ({t.get('assignee')}): {sb} send-back(s), {bl} block(s)")

    # each card's cost, from its bot's log
    logs = {p.name: read_log(p, min(since, *(t["started_at"] for t in done)) - 60 if done else since)
            for p in sorted((H / "profiles").glob("*")) if (p / "logs").is_dir()}
    per_bot, rows, slow_tools = collections.defaultdict(list), [], collections.Counter()
    for t in done:
        calls, tools, _ = logs.get(t.get("assignee") or "", ([], [], []))
        s, e = t["started_at"] - 5, t["completed_at"] + 5
        cs = [c for c in calls if s <= c[0] <= e]
        tl = [x for x in tools if s <= x[0] <= e]
        r = {"id": t["id"], "who": t.get("assignee"), "title": (t.get("title") or "")[:60],
             "min": (t["completed_at"] - t["started_at"]) / 60, "steps": len(cs), "model_s": sum(c[3] for c in cs),
             "tool_s": sum(x[2] for x in tl), "ctx": max([c[1] for c in cs] or [0]), "tools": collections.Counter(x[1] for x in tl)}
        rows.append(r)
        per_bot[r["who"]].append(r)
        for x in tl:
            if x[2] > 20:
                slow_tools[(r["who"], x[1])] += 1
    outliers = []
    for rs in per_bot.values():
        med = statistics.median(r["min"] for r in rs)
        outliers += [r for r in rs if r["min"] > max(10, 2 * med)]
    big = [r for r in rows if r["ctx"] > 150000]
    shapes = collections.defaultdict(list)
    for r in rows:
        shapes[(r["who"], shape(r["title"]))].append(r)
    repeated = {k: v for k, v in shapes.items() if len(v) >= 3 and k[1]}
    wrong = [r for r in rows if r["who"] in ("tester", "researcher", "architect") and BUILD_WORDS.match(r["title"])]

    # the owner's chats
    chats = [c for (_, _, ch) in logs.values() for c in ch if c[0] > since]
    durs = [c[1] for c in chats]
    slow_chat = bool(durs) and pct(durs, 0.9) > 180

    # builds
    builds = []
    for p in sorted((H / "builds").glob("*.json")):
        try:
            b = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if (b.get("updated") or 0) < since:
            continue
        hist = b.get("history") or []
        stages = {}
        for a, z in zip(hist, hist[1:] + [{"t": b.get("updated") or NOW}]):
            stages[a["state"]] = stages.get(a["state"], 0) + (z["t"] - a["t"])
        builds.append({"slug": b["slug"], "state": b["state"], "fails": b.get("fails", 0),
                       "fix_cards": len(b.get("fix_cards") or []), "stages": {k: round(v / 60, 1) for k, v in stages.items()}})
    bad_builds = [b for b in builds if b["fails"] or b["state"] == "stuck"]

    state_now = {"last_run": NOW, "skills": seen, "model": model or state.get("model"), "sizes": sizes,
                 "tidied": tidied, "tidy_next": tidy_next}
    wake = (outliers or slow_tools or big or repeated or wrong or slow_chat or troubled or bad_builds or skills or full
            or model_changed or len(done) >= 10 or near or tidy)
    if not wake:
        save(state_now)
        print(json.dumps({"wakeAgent": False}))
        return 0

    day = lambda x: time.strftime("%Y-%m-%d %H:%M", time.localtime(x))
    print(f"Optimiser evidence since {day(since)}:")
    if tidy:
        print(f"- TONIGHT'S TIDY: {tidy[0]} (the optimise skill, 'Nightly tidy'): `tidy.py new {tidy[0]}`; files:")
        for f in tidy[1]:
            print(f"  - {f} ({(HOME / f).stat().st_size} bytes)")
    print(f"- cards done: {len(done)}")
    for who, rs in sorted(per_bot.items()):
        print(f"  - {who}: {len(rs)} cards, median {statistics.median(r['min'] for r in rs):.1f} min (max {max(r['min'] for r in rs):.1f}); "
              f"median {statistics.median(r['steps'] for r in rs):.0f} steps, model {statistics.median(r['model_s'] for r in rs):.0f} s, "
              f"tools {statistics.median(r['tool_s'] for r in rs):.0f} s; context up to {max(r['ctx'] for r in rs) // 1000}k")
    if outliers:
        print("- outlier cards (over twice their bot's median, over 10 min):")
        for r in outliers[:10]:
            print(f"  - {r['id']} {r['who']} '{r['title']}': {r['min']:.1f} min, {r['steps']} steps, model {r['model_s']:.0f} s, "
                  f"tools {r['tool_s']:.0f} s ({', '.join(f'{k} {v}' for k, v in r['tools'].most_common(3))})")
    if repeated:
        print("- repeated card shapes (3+; a step done per piece of work may belong once, or in a script):")
        for (who, sh), rs in sorted(repeated.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"  - {who} '{sh}…' x{len(rs)}, median {statistics.median(r['min'] for r in rs):.1f} min "
                  f"({', '.join(r['id'] for r in rs[:5])})")
    if wrong:
        print("- building done by a role that doesn't build:")
        for r in wrong[:8]:
            print(f"  - {r['id']} {r['who']} '{r['title']}'")
    if slow_tools:
        print("- tool calls over 20 s: " + ", ".join(f"{w} {t} x{n}" for (w, t), n in slow_tools.most_common(8)))
    if big:
        print("- cards with a context over 150k: " + ", ".join(f"{r['id']} {r['who']} {r['ctx'] // 1000}k" for r in big[:8]))
    if durs:
        print(f"- the owner's chat replies: {len(durs)}, median {statistics.median(durs):.0f} s, p90 {pct(durs, 0.9):.0f} s"
              + (" (slow)" if slow_chat else ""))
        for c in sorted(chats, key=lambda c: -c[1])[:3]:
            print(f"  - {c[1]:.0f} s at {day(c[0])}: '{c[2]}'")
    if builds:
        print("- builds:")
        for b in builds[:8]:
            print(f"  - {b['slug']}: {b['state']}, {b['fails']} failure(s), {b['fix_cards']} fix card(s); minutes per stage {b['stages']}")
    print("- cards with send-backs or blocks:" + ("" if troubled else " none"))
    for t in troubled[:10]:
        print(f"  - {t}")
    print("- bot-written skills new or changed:" + ("" if skills else " none"))
    for s in skills[:10]:
        print(f"  - {s}")
    print("- memory fill: " + ", ".join(memory))
    if near:
        print("- loaded every session and near its limit (propose what to move to a vault page or skill, or merge):")
        for x in near:
            print(f"  - {x}")
    lessons = HOME / "vault" / "system" / "lessons.md"
    n = len(re.findall(r"^\d{4}-\d{2}-\d{2}", lessons.read_text(errors="replace"), re.M)) if lessons.exists() else 0
    print(f"- lessons: {n}/40")
    if model_changed:
        print(f"- MODEL CHANGED: {state['model']} -> {model}. Re-check skills (the optimise skill's upkeep step) and run every bot's eval.")
    save(state_now)
    print(json.dumps({"wakeAgent": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
