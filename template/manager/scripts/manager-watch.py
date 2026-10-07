#!/usr/bin/python3
"""manager-watch: the Manager's zero-token sweep (Hermes cron, every 15 minutes, Manager profile; no model call unless it finds something).

Reads the board, the status page, the log and a few hygiene signals, with no model. Prints only NEW findings
(or ones still open a day later) and lets the Manager wake for those; otherwise its last line is
{"wakeAgent": false} and the tick costs nothing. A crash prints the error, which still wakes the Manager.

Findings: board diagnostics; cards blocked or in triage over a day; cards sent back 2+ times; cards running
past their runtime limit; ready cards nobody picked up for 6 hours; owner items waiting over 48 hours;
specialists' log lines with no card id; and upkeep: memory files over 90% full, AGENTS.md over 8 KB, a SOUL
over 10 KB, lessons over 40 lines, vault lint problems, an import left in ~/import for 3+ days, unmerged
card branches untouched for 7 days. Cards waiting on the owner (needs_input, capability, triage) are never findings.
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HOME = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home())
ROOT_H = HOME / ".hermes"
STATE = ROOT_H / "profiles" / "manager" / "scripts" / ".watch-state.json"
NOW = time.time()
DAY = 86400
REMIND_AFTER = DAY            # an unresolved finding is raised again after a day


def sh(*args, cwd=None):
    r = subprocess.run(list(args), capture_output=True, text=True, cwd=cwd,
                       env={**os.environ, "PATH": f"{HOME}/.local/bin:" + os.environ.get("PATH", "")})
    return r.stdout if r.returncode == 0 else ""


def kanban(*args):
    out = sh("hermes", "kanban", *args, "--json")
    try:
        return json.loads(out) if out.strip() else None
    except ValueError:
        return None


def findings():
    f = {}   # key -> text
    tasks = kanban("list") or []
    diags = kanban("diagnostics") or []
    for d in diags:
        for item in d.get("diagnostics") or []:
            f[f"diag:{d.get('task_id')}:{str(item)[:60]}"] = f"board diagnostic on {d.get('task_id') or 'the board'}: {str(item)[:200]}"
    for t in tasks:
        tid, st, title = t.get("id"), t.get("status"), (t.get("title") or "")[:60]
        if st == "done" or st == "archived":
            continue
        detail = None
        if st in ("blocked", "triage", "running", "review") or st == "ready":
            detail = kanban("show", tid) or {}
        events = detail.get("events", []) if detail else []
        last = max([e.get("created_at") or 0 for e in events] + [t.get("created_at") or 0])
        sendbacks = sum(1 for e in events if e.get("kind") == "changes_requested")
        last_block = next((e.get("payload") or {} for e in reversed(events) if e.get("kind") == "blocked"), {})
        owners = st == "triage" or last_block.get("kind") in ("needs_input", "capability")
        # Waiting on the owner is not stuck: it waits as long as it takes (owner-queue.py, /queue), no nagging.
        if st in ("blocked", "triage") and not owners and NOW - last > DAY:
            reason = last_block.get("reason") or ""
            f[f"stuck:{tid}"] = f"{tid} '{title}' has been {st} for {int((NOW - last) // 3600)} h: {reason[:150]}"
        # A bot asked the owner something: screen it once, fast. Most such questions are the team's to settle (a
        # technical or testing call, a conflict between a card's own constraints, something the lessons already
        # answer), and the work behind it waits until someone answers.
        if st == "blocked" and last_block.get("kind") == "needs_input" and t.get("assignee") not in ("manager", None) \
                and not title.startswith("Owner:"):
            f[f"ask:{tid}:{int(last)}"] = (f"{t.get('assignee')} blocked {tid} '{title}' for the owner: "
                                           f"{(last_block.get('reason') or '')[:300]} -- is it really the owner's? If not, "
                                           "answer it yourself, comment why and unblock (work-planning: What needs the owner)")
        if sendbacks >= 2:
            f[f"sendback:{tid}:{sendbacks}"] = f"{tid} '{title}' was sent back {sendbacks} times"
        if st == "running" and t.get("started_at"):
            limit = t.get("max_runtime_seconds") or 3600
            if NOW - t["started_at"] > limit + 600:
                f[f"overrun:{tid}"] = f"{tid} '{title}' has run {int((NOW - t['started_at']) // 60)} min (limit {limit // 60})"
        if st == "ready" and NOW - last > 6 * 3600:
            f[f"idle:{tid}"] = f"{tid} '{title}' has been ready for {int((NOW - last) // 3600)} h with nobody on it (assignee: {t.get('assignee') or 'none'})"

    status = HOME / "vault" / "00-status.md"
    if status.exists():
        items = []
        head = status.read_text(errors="replace").split("---", 2)[1]
        try:
            import yaml                               # /usr/bin/python3 has it; Hermes' own python doesn't
            fm = yaml.safe_load(head) or {}
            items = [str(i) for i in (fm.get("waiting_on_owner") or [])][:5]
        except ImportError:
            m = re.search(r"^waiting_on_owner:[ \t]*(\[\])?[ \t]*\n((?:[ \t]+-.*\n?)*)", head, re.M)
            items = [l.strip()[1:].strip() for l in (m.group(2) if m else "").splitlines() if l.strip()][:5]
        except Exception as exc:                      # a broken status page is itself worth a look
            f["status:parse"] = f"00-status.md frontmatter does not parse: {exc}"
        # Owner items wait at the owner's pace; they're listed by /queue, never escalated.

    log = HOME / "vault" / "log.md"
    if log.exists():
        cutoff = dt.datetime.fromtimestamp(NOW - 2 * 3600).strftime("%Y-%m-%d %H:%M")
        for line in log.read_text(errors="replace").splitlines()[-200:]:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[0] >= cutoff and parts[1] not in ("manager", "default", "admin") \
                    and parts[2] == "handoff" and not re.search(r"\bt_[0-9a-f]{6,}", line):
                f[f"nocard:{parts[0]}:{parts[1]}"] = f"{parts[1]} logged work with no card id: {parts[3][:120]}"

    fb = HOME / "vault" / "raw" / "feedback"
    if fb.is_dir():
        waiting, batches = [], []
        for p in fb.glob("*.md"):
            t = p.read_text(errors="replace")
            if re.search(r"^status:\s*open", t, re.M) and re.search(r"^card:\s*none", t, re.M):
                if p.stem.endswith("-batch"):
                    batches.append(p.stem)
                elif not re.search(r"^batch:", t, re.M):   # notes in a batch are handled through their batch page
                    waiting.append(p.stem)
        # Paperwork nobody should do by hand: a batch whose card is done closes, with every note in it (silent).
        done_ids = {t.get("id") for t in tasks if t.get("status") == "done"}
        for p in fb.glob("*-batch.md"):
            t = p.read_text(errors="replace")
            m = re.search(r"^card:\s*(t_\w+)", t, re.M)
            if m and m.group(1) in done_ids and re.search(r"^status:\s*open", t, re.M):
                for page in [p] + [fb / f"{n}.md" for n in re.findall(r"\[\[raw/feedback/([\w-]+)\]\]", t)]:
                    if page.exists():
                        s = page.read_text(errors="replace")
                        s = re.sub(r"^status:\s*open", "status: done", s, count=1, flags=re.M)
                        s = re.sub(r"^card:\s*none", f"card: {m.group(1)}", s, count=1, flags=re.M)
                        page.write_text(s)
        for b in sorted(batches):
            f["feedback-batch:" + b] =(f"the owner sent a batch of feedback: raw/feedback/{b}.md (one review pass: "
                                         "ONE card for the whole batch, never one per note; all on one variant = the owner picked it)")
        if waiting:
            waiting.sort()
            f["feedback:" + waiting[-1]] = (f"{len(waiting)} owner note(s) from the Mark overlay without a card "
                                            f"(raw/feedback/): " + ", ".join(waiting[:5]))

    for n in (1, 2):   # a demo slot left showing the same thing for two weeks: pick, move it into the mockup, or clear it
        unit = HOME / ".config" / "systemd" / "user" / f"design-demo-{n}.service"
        if unit.exists() and NOW - unit.stat().st_mtime > 14 * DAY:
            what = next((ln.split(":", 1)[1].strip() for ln in unit.read_text().splitlines() if ln.startswith("Description=")), "")
            f[f"demo-stale:{n}:{int(unit.stat().st_mtime)}"] = (f"demo {n} has shown '{what}' for 14+ days: ask the owner to pick, "
                                                              "or bring it into the mockup, then demo.sh clear")
    va = HOME / "vault" / "design" / "variants"
    if va.is_dir():
        for d in va.iterdir():
            if d.is_dir() and d.name != "current" and NOW - max((p.stat().st_mtime for p in d.rglob("*")), default=d.stat().st_mtime) > 14 * DAY:
                f[f"variant-stale:{d.name}"] = f"design variant {d.name} unpicked for 14+ days: archive it or ask the owner to pick"
            size = sum(p.stat().st_size for p in d.glob("*.js")) + sum(p.stat().st_size for p in d.glob("*.css"))
            if d.is_dir() and size > 40_000:   # a look should be styles and a short script; a patch layer re-learned every round
                f[f"look-size:{d.name}:{size // 20_000}"] = (f"design look {d.name} is {size // 1000} KB of CSS and script: too big to stay "
                                                           "quick. Card the Designer: fold built parts out, prototype the structural ones")
    side = HOME / "side"
    if side.is_dir():
        for d in side.iterdir():
            if d.is_dir() and NOW - d.stat().st_ctime > 21 * DAY:
                f[f"side:{d.name}"] = f"side track ~/side/{d.name} is 21+ days old: check its cap and exit condition in product/roadmap.md, or run its clean-up card"

    # ---- upkeep ----
    for prof in [ROOT_H] + sorted((ROOT_H / "profiles").glob("*")):
        name = "default" if prof == ROOT_H else prof.name
        for fn, cap in (("MEMORY.md", 2200), ("USER.md", 1375)):
            p = prof / "memories" / fn
            if p.exists() and p.stat().st_size > 0.9 * cap:
                f[f"mem:{name}:{fn}"] = f"{name}'s {fn} is {p.stat().st_size}/{cap} characters: merge it before it fills"
        soul = prof / "SOUL.md"
        if name != "default" and soul.exists() and soul.stat().st_size > 10_000:
            f[f"soul:{name}"] = f"{name}'s SOUL.md is {soul.stat().st_size // 1000} KB (keep under 10)"
    try:
        phase = re.search(r"^phase:\s*(\S+)", (HOME / "vault" / "00-status.md").read_text(errors="replace"), re.M).group(1)
    except (OSError, AttributeError):
        phase = ""
    for agents in (HOME / "workspace" / "AGENTS.md",):
        # While onboarding, AGENTS.md is still the imported project's own: the takeover rewrites it.
        if phase != "onboarding" and agents.exists() and agents.stat().st_size > 8_500:
            f["agents:size"] = f"workspace/AGENTS.md is {agents.stat().st_size // 100 / 10} KB (keep under about 8; move detail to the vault or per-folder AGENTS.md files)"
    lessons = HOME / "vault" / "system" / "lessons.md"
    if lessons.exists():
        n = len(re.findall(r"^\d{4}-\d{2}-\d{2}", lessons.read_text(errors="replace"), re.M))
        if n > 40:
            f["lessons:size"] = f"system/lessons.md has {n} lessons (cap 40): merge or retire some"
    lint = sh("/usr/bin/python3", str(ROOT_H / "scripts" / "vault-lint.py"), str(HOME / "vault"))
    probs = lint.split("--- problems ---", 1)[-1].split("--- advisories ---", 1)[0].strip() if lint else ""
    if probs and probs != "none":
        f["lint:" + hashlib.md5(probs.encode()).hexdigest()[:10]] = "vault lint problems: " + "; ".join(probs.splitlines()[:5])
    imp = HOME / "import"
    if imp.is_dir():
        for e in imp.iterdir():
            if NOW - e.stat().st_mtime > 3 * DAY:
                f[f"import:{e.name}"] = f"~/import/{e.name} has sat there {int((NOW - e.stat().st_mtime) // DAY)} days: finish the takeover or ask the owner"
    ws = HOME / "workspace"
    if (ws / ".git").is_dir():
        live = {t.get("branch_name") for t in tasks if t.get("status") not in ("done", "archived")}
        main = "main" if sh("git", "-C", str(ws), "show-ref", "--verify", "refs/heads/main") else \
               (sh("git", "-C", str(ws), "symbolic-ref", "--short", "HEAD").strip() or "master")
        out = sh("git", "-C", str(ws), "for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads/", "--no-merged", main)
        for line in out.splitlines():
            br, _, ts = line.rpartition(" ")
            if re.match(r"^[^/]+/t_[0-9a-f]+", br) and br not in live and ts.isdigit() and NOW - int(ts) > 7 * DAY:
                f[f"branch:{br}"] = f"unmerged branch {br} untouched for {int((NOW - int(ts)) // DAY)} days and no open card: land it or delete it (owner's call)"
    return f


def main():
    try:
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
    except ValueError:
        state = {}
    found = findings()
    new = {k: v for k, v in found.items() if NOW - state.get(k, 0) > REMIND_AFTER}
    state = {k: (NOW if k in new else state.get(k, NOW)) for k in found}   # forget resolved findings
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))
    if not new:
        print(json.dumps({"wakeAgent": False}))
        return 0
    print(f"manager-watch found {len(new)} thing(s) to act on ({len(found) - len(new)} older ones already raised):")
    for v in new.values():
        print(f"- {v}")
    print(json.dumps({"wakeAgent": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
