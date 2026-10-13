#!/usr/bin/python3
"""build.py: one build = one branch, one worktree, the cards that make it, then ONE check and ONE landing.

The Manager plans a build (a feature, an agreed design, a lone fix) as a few cards that all work on one branch.
Each card runs only its own quick checks and commits. Nothing is reviewed, tested in full, merged or restarted per
card. When every card of the build is done, the build is checked once, as a whole, and goes live by script:

  planning -> building -> checking -> (reviewing) -> landing -> live
    checking:  main merged into the branch, the full suite (scripts/run-tests.sh), then every card's checks again;
               an agreed design's build also gets the look check (dv.py look: each screen of the build against the
               agreed mockup, by the design view's headless browser)
    reviewing: at most one Designer card (only when screens still differ from the agreed look) and one Tester card
               (only when a card says `Review: tester`), each for the whole build, each only if that role is hired
    landing:   main checkout clean -> merge --no-ff -> restart the app's services -> each card's (live) checks;
               a failure puts main back where it was (our own merge, seconds old) and restarts again
  A failure at any step: one fix card for the Engineer with every failing check, on the same branch; the build
  re-checks itself when it's done. The third failure goes to the Manager instead (state: stuck).

  build.py start <slug> [--design <stamp>] [--plan-card <id>] [--title "<what>"]
        a branch (build/<slug>, design/<stamp>) and its worktree (~/wt/<slug>) from main; prints the two lines every
        card of the build carries. Again with --plan-card: records the planning card (the build starts when it's done)
  build.py ready <slug>           planning is done (no plan card), or a stuck build may try again
  build.py status [<slug>] [--json]   open builds, their stage and their cards
  build.py checks <card> [--dir <path>] [--live]   run one card's Verification checks, print the table
  build.py tick                   advance every open build one stage (the build-tick timer, every 30 s)
  build.py abort <slug> ["<why>"] stop a build; its branch and worktree are kept

A card belongs to a build by one line in its body: `Build: <slug>`. Its workspace is the build's worktree
(`--workspace dir:<worktree>`). Checks in a card's `## Verification`, one per list item:
  - `<command>` -> `<expected>`          the expected text appears in the output (or `exit <n>`)
  - `<command>` -> `<expected>` (live)   run after landing, against the running app
Items without a command and an arrow are listed as not run, never guessed at.
"""
import fcntl
import shutil
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HOME = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home())
H = HOME / ".hermes"
BUILDS = H / "builds"
REPO = HOME / "workspace"
WT = HOME / "wt"
KANBAN = os.environ.get("BUILD_KANBAN") or "hermes"       # tests point this at a fake board
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
OPEN = ("planning", "building", "checking", "reviewing", "landing")
MAX_FAILS = 3
CHECK_TIMEOUT = 180
BUILD_LINE = re.compile(r"^\s*(?:\*\*)?Build:(?:\*\*)?\s*([a-z0-9][a-z0-9._-]*)\s*$", re.M | re.I)
PAIR = re.compile(r"`([^`]+)`\s+(?:→|->|=>)\s+(?:`([^`]*)`|([^`;(—]+?)(?=\s+\(|;|\s+—\s|$))")
REVIEW_LINE = re.compile(r"Review:(?:\*\*)?\s*tester\b", re.I)
ENV = dict(os.environ, PATH=f"{HOME}/.local/bin:" + os.environ.get("PATH", ""),
           XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
ENV.pop("HERMES_KANBAN_BOARD", None)


# ---- small helpers -------------------------------------------------------------------------------------------------
def run(cmd, cwd=None, timeout=600, shell=False):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=ENV, shell=shell,
                           executable="/bin/bash" if shell else None)
        return r.returncode, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out + f"\n(timed out after {timeout} s)"
    except OSError as e:
        return 127, str(e)


def git(*a, cwd=REPO, timeout=300):
    return run(["git", "-C", str(cwd), *a], timeout=timeout)


def kanban(*a):
    rc, out = run([KANBAN, "kanban", *a], timeout=60)
    if rc != 0:
        raise RuntimeError(f"kanban {a[0]} failed: {out.strip()[-300:]}")
    return out


def cards():
    try:
        return json.loads(kanban("list", "--archived", "--json") or "[]")
    except (RuntimeError, ValueError):
        return None


def create_card(title, who, body, wt=None, parent=None):
    a = ["create", title[:50], "--assignee", who, "--body", body, "--json"]
    if wt:
        a += ["--workspace", f"dir:{wt}"]
    if parent:
        a += ["--parent", parent]
    out = kanban(*a)
    m = re.search(r'"(?:id|task_id)"\s*:\s*"([^"]+)"', out)
    return m.group(1) if m else None


def comment(card, text):
    if card:
        try:
            kanban("comment", card, text[:3000])
        except RuntimeError:
            pass


def vault_log(text):
    run(["bash", str(H / "scripts" / "vault-log.sh"), "build", "handoff", text[:300]], timeout=30)


def path(slug):
    return BUILDS / f"{slug}.json"


def load(slug):
    try:
        return json.loads(path(slug).read_text())
    except (OSError, ValueError):
        return None


def save(b):
    BUILDS.mkdir(parents=True, exist_ok=True)
    b["updated"] = time.time()
    tmp = path(b["slug"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(b, indent=1))
    tmp.replace(path(b["slug"]))


def stage(b, state, step=""):
    """Move a build to a stage, keeping how long each one took (the Optimiser reads this)."""
    if state != b.get("state") or step != b.get("step"):
        b.setdefault("history", []).append({"t": round(time.time()), "state": state, "step": step[:200]})
    b["state"], b["step"] = state, step
    save(b)


def all_builds():
    return [b for b in (load(p.stem) for p in sorted(BUILDS.glob("*.json"))) if b] if BUILDS.is_dir() else []


# ---- checks --------------------------------------------------------------------------------------------------------
def parse_checks(body):
    """A card's Verification section as checks: [{cmd, expect, live}] plus the items that can't be run as written."""
    m = re.search(r"^#+\s*Verification\b.*?$(.*?)(?=^#+\s|\Z)", body or "", re.M | re.S)
    if not m:
        return [], []
    checks, manual = [], []
    for line in m.group(1).splitlines():
        item = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$", line)
        if not item:
            continue
        text = item.group(1).strip()
        live = bool(re.search(r"\(live\)", text, re.I))
        found = 0
        for m in PAIR.finditer(text):                            # one item may hold several: `a` → `x`; `b` → `y`
            expect = m.group(2) if m.group(2) is not None else m.group(3).strip().rstrip(".,;").strip('"').strip("'")
            if expect:
                checks.append({"cmd": m.group(1).strip(), "expect": expect, "live": live})
                found += 1
        if not found and text and not text.lower().startswith("not covered"):
            manual.append(text[:160])
    return checks, manual


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def run_check(c, cwd):
    """Pass: the expected text is in what the command printed (stdout, never an error message that happens to
    contain it), and the command succeeded unless its whole output is exactly the expected text; or `exit <n>`."""
    try:
        r = subprocess.run(c["cmd"], cwd=str(cwd), shell=True, executable="/bin/bash", capture_output=True,
                           text=True, timeout=CHECK_TIMEOUT, env=ENV)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", f"(timed out after {CHECK_TIMEOUT} s)"
    ex = re.fullmatch(r"exit\s*(?:code\s*)?(\d+)", c["expect"].strip(), re.I)
    exp, got = norm(c["expect"]), norm(out)
    if ex:
        ok = rc == int(ex.group(1))
    elif re.fullmatch(r"-?\d+(?:\.\d+)?", exp):                 # a number: the whole number, never 10 for 0
        ok = bool(re.search(r"(?<![\w.])" + re.escape(exp) + r"(?![\w.])", got)) and (rc == 0 or got == exp)
    else:
        ok = exp in got and (rc == 0 or got == exp)
    return ok, rc, (out + ("\n" + err if err.strip() else "")).strip()


def check_card(card, cwd, live=False, waived=()):
    """Run a card's checks (the pre-landing ones, or the live ones), less any a later card of the build made out of
    date on purpose (waived, and listed as such). -> rows of (ok, check, rc, output), the items not run."""
    checks, manual = parse_checks(card.get("body") or "")
    rows = []
    for c in checks:
        if c["live"] != live:
            continue
        if c["cmd"] in waived:
            manual.append(f"WAIVED (out of date: {waived[c['cmd']]}): {c['cmd'][:100]}")
            continue
        ok, rc, out = run_check(c, cwd)
        rows.append((ok, c, rc, out))
    return rows, manual


def outdated(text):
    """`outdated: <command> — <why>` lines in a fix card's result: checks a later card of the build changed on purpose."""
    out = {}
    for m in re.finditer(r"^\s*[-*]?\s*outdated:\s*`([^`]+)`\s*(?:[—:-]+\s*(.*))?$", text or "", re.M | re.I):
        out[m.group(1).strip()] = (m.group(2) or "no reason given").strip()[:160]
    return out


def table(card, rows, manual):
    lines = [f"{card['id']} {(card.get('title') or '')[:50]}"]
    for ok, c, rc, out in rows:
        lines.append(f"  {'PASS' if ok else 'FAIL'}  {c['cmd'][:90]}  -> expected {c['expect'][:60]!r}"
                     + ("" if ok else f"\n        got (exit {rc}): {norm(out)[-300:]}"))
    for m in manual:
        lines.append(f"  NOT RUN  {m}")
    return "\n".join(lines)


# ---- the stages ----------------------------------------------------------------------------------------------------
def members(b, board):
    """The build's cards: those naming it, in the order they were made (the plan card and review/fix cards apart)."""
    mine = [c for c in board if any(s == b["slug"] for s in BUILD_LINE.findall(c.get("body") or ""))]
    return sorted(mine, key=lambda c: c.get("created_at") or 0)


def rows_for(b, board):
    """The cards to show as the build's progress: plan card, members, the review card."""
    ids = [b.get("plan_card")] + [c["id"] for c in members(b, board)] + [b.get("review_card")]
    by = {c["id"]: c for c in board}
    out = []
    for i in ids:
        c = by.get(i or "")
        if c and not any(r["id"] == i for r in out):
            out.append({"id": i, "title": (c.get("title") or "")[:70], "who": c.get("assignee") or "",
                        "status": c.get("status") or "", "since": c.get("started_at") or c.get("created_at") or 0,
                        "created": c.get("created_at") or 0})
    return out


def finished(c):
    return (c.get("status") or "") in ("done", "archived")


def fail(b, why, detail, board):
    """A failing check: the Engineer gets one card with all of it; the third time, the Manager does."""
    b["fails"] = b.get("fails", 0) + 1
    if b["fails"] >= MAX_FAILS:
        card = create_card(f"Build {b['slug']} keeps failing", "manager",
                           f"The build `{b['slug']}` ({b.get('title') or b['branch']}) has failed {b['fails']} times; "
                           f"it stopped instead of looping.\n\nLast failure: {why}\n\n{detail[-3000:]}\n\n"
                           f"Decide: the check is wrong (fix the card's Verification, with the owner's OK if they approved "
                           f"it), the work needs re-slicing, or a new angle. Then `build.py ready {b['slug']}` to try again, "
                           f"or `build.py abort {b['slug']}`.\nWorktree: {b['worktree']}")
        b["stuck_card"] = card
        stage(b, "stuck", f"failed {b['fails']} times: {why}")
        vault_log(f"Build {b['slug']} stuck after {b['fails']} failures ({why}); Manager card {card}")
        return
    who = "engineer" if (H / "profiles" / "engineer").is_dir() else "manager"
    card = create_card(f"Fix build {b['slug']}: {why}"[:50], who,
                       f"Build: {b['slug']}\nSession: build:{b['slug']}\nShape: quick\nReview: none\n\n"
                       f"## Outcome\nThe build `{b['slug']}` passes its checks again: {why}.\n\n"
                       f"## What failed (all of it, from one run)\n```\n{detail[-6000:]}\n```\n\n"
                       f"## Constraints\nFix it on the build's branch `{b['branch']}` in `{b['worktree']}` and commit there. "
                       f"A failing check that a later card of this build made out of date on purpose (it changed that very "
                       f"thing as its own card asked) is not a defect: leave the code, and put one line in your result per "
                       f"such check: outdated: `<the exact command>` — <which card changed it, and why>. The build then "
                       f"skips it and lists it as waived. "
                       f"Don't merge, restart or re-run the whole build: when this card is done the build checks "
                       f"itself again and lands.\n\n## Stop when\nThe failing checks pass in the worktree and the fix is committed.",
                       wt=b["worktree"])
    b.setdefault("fix_cards", []).append(card)
    stage(b, "building", f"fixing: {why} (card {card})")


def do_checking(b, board):
    cwd = pathlib.Path(b["worktree"])
    stage(b, "checking", "merging main into the build")
    rc, out = git("merge", "--no-edit", b["base"], cwd=cwd)
    if rc != 0:
        git("merge", "--abort", cwd=cwd)
        return fail(b, f"main has moved on and conflicts", out, board)
    stage(b, "checking", "running the full test suite")
    suite = cwd / "scripts" / "run-tests.sh"
    report = []
    if suite.exists():
        rc, out = run(["bash", str(suite)], cwd=str(cwd), timeout=1800)
        report.append(out.strip())
        if rc != 0:
            return fail(b, "the test suite fails", out, board)
    else:
        report.append("(no scripts/run-tests.sh in this repo: no suite run)")
    stage(b, "checking", "re-running every card's checks")
    by = {c["id"]: c for c in board}
    for fid in b.get("fix_cards") or []:                         # checks a fix card says are out of date
        b.setdefault("waived", {}).update(outdated((by.get(fid) or {}).get("result")))
    bad, tables = False, []
    for c in members(b, board):
        rows, manual = check_card(c, cwd, waived=b.get("waived") or {})
        tables.append(table(c, rows, manual))
        bad |= any(not r[0] for r in rows)
    b["check_report"] = "\n".join(report + tables)
    if bad:
        return fail(b, "card checks fail", b["check_report"], board)
    ms = members(b, board)
    diff = git("log", "--oneline", f"{b['base']}..{b['branch']}", cwd=cwd)[1].strip()
    reviews = []
    if b.get("design"):                                          # an agreed design: does the build look like it?
        stage(b, "checking", "the look: each screen of the build against the agreed mockup")
        look = look_check(b)
        b["check_report"] += "\n\n" + look["text"]
        if look.get("differ") and (H / "profiles" / "designer").is_dir():
            decisions = "\n".join(f"- {c.get('title')}: {ln.strip()}" for c in ms
                                   for ln in re.findall(r"(?im)^.*look decisions?:.*$", c.get("result") or ""))
            reviews.append({"who": "designer", "title": f"Look review: build {b['slug']}", "body":
                f"Look-of: {b['slug']}\nShape: scoped\n\n## Outcome\nThe build `{b['slug']}` ({b.get('title') or ''}) passes its "
                f"checks; these screens still differ from the agreed mockup. For each, look at its overlay picture (the build, "
                f"with what differs in magenta), then the mockup and the build pictures beside it. Each difference is either a "
                f"defect (the build doesn't match the agreed look: say what, where, and what it should be) or expected (real "
                f"behaviour the design didn't show: real data, an empty or loading state, one of the Engineer's look "
                f"decisions below that fits the design's language). Judge only the look; the checks covered what it does.\n\n"
                f"## The look check\n```\n{look['text']}\n```\n\n## The Engineer's look decisions\n{decisions or '(none listed)'}\n\n"
                f"Run `dv.py look {b['worktree']}` again to see it after a change.\n\n## Stop when\nYour result's first line "
                f"is `APPROVED` (then a line per expected difference, for the owner) or `CHANGES: <each defect: the screen, "
                f"what differs, what it should be>` (they go to the Engineer as one card)."})
    if any(REVIEW_LINE.search(c.get("body") or "") for c in ms) and (H / "profiles" / "tester").is_dir():
        reviews.append({"who": "tester", "title": f"Review build {b['slug']}", "body":
            f"Review-of: {b['slug']}\nSession: review:{b['slug']}\nShape: scoped\n\n"
            f"## Outcome\nOne review of the whole build `{b['slug']}` ({b.get('title') or ''}) before it goes "
            f"live: its cards' behaviour against the test plan's cases (`vault/qa/`), on the branch "
            f"`{b['branch']}` in `{b['worktree']}` (run the app from there on a spare port in the project's "
            f"range; never the real app or its data).\n\n## Already checked by script (don't re-run)\n"
            f"```\n{b['check_report'][-4000:]}\n```\n\nCommits:\n```\n{diff[-2000:]}\n```\n\n"
            f"## Stop when\nYour result's first line is `APPROVED` (it then goes live by itself) or "
            f"`CHANGES: <the defects, each reproducible>` (they go to the Engineer as one card)."})
    if reviews:
        b["reviews"] = reviews
        return next_review(b)
    do_landing(b, board)


def next_review(b):
    """The next review the build waits for (a Designer's look review first, then a Tester's), one card each."""
    r = b["reviews"].pop(0)
    b["review_card"], b["review_by"] = create_card(r["title"], r["who"], r["body"], wt=b["worktree"]), r["who"]
    stage(b, "reviewing", f"{r['who'].capitalize()} reviewing (card {b['review_card']})")


def look_check(b):
    """dv.py look on the build's worktree: each screen of the agreed design against the mockup. Pictures go to
    ~/.hermes/builds/<slug>-look/ (removed when the build is live). -> {"text", "differ": [routes]}"""
    out = BUILDS / f"{b['slug']}-look"
    rc, txt = run([sys.executable, str(H / "scripts" / "dv.py"), "look", b["worktree"], "--out", str(out), "--json"], timeout=600)
    try:
        r = json.loads(txt.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {"error": txt.strip()[-300:] or f"exit {rc}"}
    if r.get("error"):
        return {"text": f"Look check: couldn't run ({r['error']}); not judged", "differ": []}
    rows = [f"{x['route']}: " + (f"couldn't compare ({x['error']})" if x.get("error") else f"{x['diff']}% differs"
            + (f"  overlay {x['overlay']} · mockup {x['mockup']} · build {x['built']}" if x["diff"] >= r["tolerance"] else ""))
            for x in r["screens"]]
    return {"text": f"Look check (the build against the agreed mockup at {r['view']['w']}x{r['view']['h']}, "
                    f"{r['tolerance']}% allowed):\n" + "\n".join(rows), "differ": r["differ"]}


def services():
    """The app's services: enabled user units that run from the main checkout (not the design view or the gateway)."""
    rc, out = run(["systemctl", "--user", "list-unit-files", "--type=service", "--state=enabled", "--no-legend"], timeout=30)
    units = []
    for line in out.splitlines() if rc == 0 else []:
        u = line.split()[0] if line.split() else ""
        if not u.endswith(".service") or u.startswith(("hermes-gateway", "design-view")):
            continue
        _, ex = run(["systemctl", "--user", "show", "-p", "ExecStart", "-p", "WorkingDirectory", "--value", u], timeout=15)
        text = ex
        for p in re.findall(r"(/\S+\.sh)\b", ex):                  # a wrapper script: what it starts
            try:
                text += pathlib.Path(p).read_text(errors="replace")[:4000]
            except OSError:
                pass
        if re.search(re.escape(str(REPO)) + r"(/|\b)", text):
            units.append(u)
    return units


def restart(units):
    for u in units:
        run(["systemctl", "--user", "restart", u], timeout=60)
    time.sleep(4)
    return [u for u in units if run(["systemctl", "--user", "is-active", "--quiet", u], timeout=15)[0] != 0]


def do_landing(b, board):
    stage(b, "landing", "merging into main")
    rc, cur = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no")[1].strip()
    if cur.strip() != b["base"] or dirty:
        why = f"the main checkout is on '{cur.strip()}'" if cur.strip() != b["base"] else "the main checkout has uncommitted changes"
        b["fails"] = MAX_FAILS - 1                             # not the Engineer's to fix: straight to the Manager
        return fail(b, why, dirty or cur, board)
    prev = git("rev-parse", "HEAD")[1].strip()
    rc, out = git("merge", "--no-ff", "--no-edit", "-m", f"Land build {b['slug']}: {b.get('title') or b['branch']}", b["branch"])
    if rc != 0:
        git("merge", "--abort")
        return fail(b, "merging into main failed", out, board)
    merged = git("rev-parse", "HEAD")[1].strip()
    stage(b, "landing", "restarting the app")
    units = services()
    down = restart(units)
    live_rows, tables = [], []
    if not down:
        stage(b, "landing", "checking the running app")
        for c in members(b, board):
            rows, manual = check_card(c, REPO, live=True, waived=b.get("waived") or {})
            if rows:
                tables.append(table(c, rows, []))
                live_rows += rows
    if down or any(not r[0] for r in live_rows):
        why = f"{', '.join(down)} didn't start" if down else "the running app fails its checks"
        detail = "\n".join(tables) or "\n".join(run(["journalctl", "--user", "-u", u, "-n", "30", "--no-pager"])[1] for u in down)
        if git("rev-parse", "HEAD")[1].strip() == merged:      # our own merge, seconds old: take it back
            git("reset", "--hard", prev)
            restart(units)
            detail += f"\n\nmain was put back to {prev[:10]} and the app restarted on it."
        return fail(b, why, detail, board)
    b["landed"] = {"commit": merged, "at": round(time.time()), "services": units}
    git("worktree", "remove", "--force", b["worktree"])
    git("branch", "-D", b["branch"])
    shutil.rmtree(BUILDS / f"{b['slug']}-look", ignore_errors=True)    # the look check's pictures: done with
    stage(b, "live", f"live at {merged[:10]}" + (f"; restarted {', '.join(units)}" if units else ""))
    comment(b.get("plan_card"), f"Build {b['slug']} is live: merged {merged[:10]} into {b['base']}"
            + (f", restarted {', '.join(units)}" if units else "") + "."
            + "".join(f"\nWaived (out of date): {k} — {v}" for k, v in (b.get("waived") or {}).items())
            + "".join(f"\nApproved with: {x}" for x in b.get("approved_notes") or []))
    vault_log(f"Build {b['slug']} is live ({merged[:10]}): {b.get('title') or b['branch']}")


def advance(b, board):
    by = {c["id"]: c for c in board}
    st = b["state"]
    if st == "planning":
        pc = by.get(b.get("plan_card") or "")
        if pc and finished(pc):
            stage(b, "building", "planned")
            st = "building"
        else:
            return stage(b, "planning", "the Manager is planning the build" if pc else "waiting for `build.py ready`")
    if st == "building":
        ms = members(b, board)
        if not ms:
            return stage(b, "building", "no cards yet")
        blocked = [c for c in ms if c.get("status") == "blocked"]
        if blocked:
            return stage(b, "building", f"waiting: '{blocked[0].get('title')}' is blocked")
        todo = [c for c in ms if not finished(c)]
        if todo:
            run_ = [c for c in todo if c.get("status") == "running"]
            c = (run_ or todo)[0]
            return stage(b, "building", f"{len(ms) - len(todo)}/{len(ms)} done; {c.get('assignee')}: {(c.get('title') or '')[:50]}")
        return do_checking(b, board)
    if st == "reviewing":
        rc_ = by.get(b.get("review_card") or "")
        if not rc_:
            return
        if rc_.get("status") == "blocked":
            return stage(b, "reviewing", f"waiting: the {(b.get('review_by') or 'tester').capitalize()}'s review is blocked")
        if not finished(rc_):
            return
        verdict = (rc_.get("result") or "").strip()
        b["review_card"], who = None, b.pop("review_by", None) or "tester"
        if re.match(r"^\**APPROVED\b", verdict, re.I):
            if verdict.count("\n"):
                b.setdefault("approved_notes", []).append(f"{who}: " + verdict.split("\n", 1)[1].strip()[:1500])
            return next_review(b) if b.get("reviews") else do_landing(b, board)
        b["reviews"] = []                                         # the fix is checked again from the start
        return fail(b, f"the {who.capitalize()} asked for changes", verdict or "(no result written)", board)
    if st in ("checking", "landing"):                           # interrupted mid-way (a restart): do it again
        return do_checking(b, board)


# ---- commands ------------------------------------------------------------------------------------------------------
def cmd_start(args):
    slug = args[0] if args else ""
    opts = dict(zip(args[1::2], args[2::2]))
    if not SLUG.match(slug):
        sys.exit("build.py start <slug>: lowercase letters, digits, '.', '_' and '-', up to 48")
    b = load(slug)
    if b:                                                      # again: record the plan card (or the title)
        if opts.get("--plan-card"):
            b["plan_card"] = opts["--plan-card"]
        if opts.get("--title"):
            b["title"] = opts["--title"]
        save(b)
    else:
        base = git("rev-parse", "--abbrev-ref", "HEAD")[1].strip() or "main"
        branch = f"design/{opts['--design']}" if opts.get("--design") else f"build/{slug}"
        wt = WT / slug
        WT.mkdir(parents=True, exist_ok=True)
        exists = git("rev-parse", "--verify", "--quiet", branch)[0] == 0
        rc, out = git("worktree", "add", *([str(wt), branch] if exists else ["-b", branch, str(wt), base]))
        if rc != 0 and not wt.is_dir():
            sys.exit(f"build.py: couldn't make the worktree: {out.strip()[-400:]}")
        b = {"slug": slug, "branch": branch, "base": base, "worktree": str(wt), "design": opts.get("--design"),
             "plan_card": opts.get("--plan-card"), "title": opts.get("--title", ""), "created": round(time.time()),
             "fails": 0}
        stage(b, "planning", "")
    print(json.dumps({"slug": slug, "branch": b["branch"], "worktree": b["worktree"],
                      "every card carries": [f"Build: {slug}", f"--workspace dir:{b['worktree']}"]}))


def cmd_ready(args):
    b = load(args[0]) if args else None
    if not b:
        sys.exit("build.py ready <slug>: no such build")
    if b["state"] in ("planning", "stuck", "aborted"):
        b["fails"] = 0 if b["state"] == "stuck" else b.get("fails", 0)
        stage(b, "building", "ready")
    print(json.dumps({"slug": b["slug"], "state": b["state"]}))


def status_of(b, board):
    return {k: b.get(k) for k in ("slug", "title", "state", "step", "branch", "worktree", "design", "fails",
                                  "plan_card", "created", "updated", "landed")} | {
        "cards": rows_for(b, board) if board is not None else []}


def cmd_status(args):
    want = [a for a in args if not a.startswith("--")]
    bs = [load(want[0])] if want else [b for b in all_builds() if b["state"] in OPEN + ("stuck",)]
    bs = [b for b in bs if b]
    board = cards() if bs else []
    out = [status_of(b, board) for b in bs]
    if "--json" in args:
        print(json.dumps(out[0] if want and out else out))
        return
    if not out:
        print("no open builds")
    for s in out:
        print(f"{s['slug']}: {s['state']} - {s['step']}  ({s['branch']})")
        for c in s["cards"]:
            print(f"    {c['status']:<8} {c['who']:<9} {c['title']}")


def cmd_checks(args):
    if not args:
        sys.exit("build.py checks <card> [--dir <path>] [--live]")
    opts = dict(zip(args[1::2], args[2::2])) if len(args) > 2 else {}
    board = cards() or []
    c = next((x for x in board if x["id"] == args[0] or x["id"].endswith(args[0])), None)
    if not c:
        sys.exit(f"build.py: no card {args[0]}")
    m = BUILD_LINE.search(c.get("body") or "")
    b = load(m.group(1)) if m else None
    cwd = opts.get("--dir") or (b["worktree"] if b and pathlib.Path(b["worktree"]).is_dir() else str(REPO))
    rows, manual = check_card(c, cwd, live="--live" in args)
    print(table(c, rows, manual))
    sys.exit(0 if all(r[0] for r in rows) else 1)


def cmd_tick(args):
    bs = [b for b in all_builds() if b["state"] in OPEN]
    if not bs:
        return                                                   # idle: costs nothing
    BUILDS.mkdir(parents=True, exist_ok=True)
    with open(BUILDS / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return                                               # a slow stage is still running
        board = cards()
        if board is None:
            return
        for b in bs:
            b = load(b["slug"])
            if b and b["state"] in OPEN:
                try:
                    advance(b, board)
                except Exception as e:                           # one build's trouble never stops the others
                    stage(b, b["state"], f"error: {e}"[:200])


def cmd_abort(args):
    b = load(args[0]) if args else None
    if not b:
        sys.exit("build.py abort <slug>: no such build")
    if b["state"] == "landing":
        sys.exit("build.py: it's landing right now; abort after it finishes")
    if b["state"] != "live":
        stage(b, "aborted", " ".join(args[1:]) or "aborted")
    shutil.rmtree(BUILDS / f"{b['slug']}-look", ignore_errors=True)
    print(json.dumps({"slug": b["slug"], "state": b["state"]}))


def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    fn = {"start": cmd_start, "ready": cmd_ready, "status": cmd_status, "checks": cmd_checks, "tick": cmd_tick,
          "abort": cmd_abort}.get(cmd)
    if not fn:
        print(__doc__)
        sys.exit(0 if cmd in ("", "-h", "--help", "help") else 2)
    fn(args)


if __name__ == "__main__":
    main()
