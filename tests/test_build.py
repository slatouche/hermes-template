#!/usr/bin/python3
"""Checks for template/scripts/build.py (one build: its cards, one check, one landing), without Hermes or a model.

  python3 tests/test_build.py      (Linux: a temporary project home, a throwaway git repo, a fake board and a stub
                                   systemctl on its PATH; nothing outside the temporary folder is touched)
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent / "template"
failures = []

FAKE_HERMES = r'''#!/usr/bin/python3
import json, os, sys, time, pathlib
f = pathlib.Path(os.environ["PROJECT_HOME"]) / "board.json"
board = json.loads(f.read_text()) if f.exists() else []
a = sys.argv[1:]
assert a[0] == "kanban", a
if a[1] == "list":
    print(json.dumps(board))
elif a[1] == "create":
    rest = [x for x in a[3:] if x != "--json"]
    o = dict(zip(rest[0::2], rest[1::2]))
    c = {"id": "t_%04d" % (len(board) + 1), "title": a[2], "assignee": o.get("--assignee"), "body": o.get("--body", ""),
         "status": "todo", "created_at": time.time() + len(board), "workspace": o.get("--workspace"), "result": None}
    board.append(c); f.write_text(json.dumps(board)); print(json.dumps({"id": c["id"]}))
elif a[1] == "comment":
    for c in board:
        if c["id"] == a[2]:
            c.setdefault("comments", []).append(" ".join(a[3:]))
    f.write_text(json.dumps(board))
'''
FAKE_SYSTEMCTL = r'''#!/bin/bash
echo "$*" >> "$PROJECT_HOME/systemctl.log"
case "$*" in
  *list-unit-files*) echo "myapp.service enabled enabled"; echo "design-view.service enabled enabled";
                     echo "other.service enabled enabled" ;;
  *"show"*myapp*) echo "/usr/bin/python3 $PROJECT_HOME/workspace/server.py --port 1"; echo "$PROJECT_HOME/workspace" ;;
  *"show"*) echo "/usr/bin/true"; echo "/" ;;
  *is-active*myapp*) [ -f "$PROJECT_HOME/app-down" ] && exit 3; exit 0 ;;
esac
exit 0
'''


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, executable="/bin/bash")


def main():
    home = pathlib.Path(tempfile.mkdtemp(prefix="build-"))
    os.environ["PROJECT_HOME"] = str(home)
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    for name, text in (("hermes", FAKE_HERMES), ("systemctl", FAKE_SYSTEMCTL)):
        (bindir / name).write_text(text)
        (bindir / name).chmod(0o755)
    (home / ".hermes" / "scripts").mkdir(parents=True)
    (home / ".hermes" / "scripts" / "vault-log.sh").write_text('#!/bin/bash\necho "$*" >> "$PROJECT_HOME/vault.log"\n')
    (home / ".hermes" / "profiles" / "engineer").mkdir(parents=True)
    repo = home / "workspace"
    repo.mkdir()
    (repo / "scripts").mkdir()
    (repo / "scripts" / "run-tests.sh").write_text('#!/bin/bash\n[ -f BROKEN ] && { echo "FAIL suite"; exit 1; }\necho "PASS suite"\n')
    sh("git init -q -b main && git config user.email t@t && git config user.name t && git add -A && git commit -qm init", repo)

    spec = importlib.util.spec_from_file_location("build", ROOT / "scripts" / "build.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    board_f = home / "board.json"

    def board():
        return json.loads(board_f.read_text()) if board_f.exists() else []

    def put(cards):
        board_f.write_text(json.dumps(cards))

    def card(title, body, who="engineer", status="todo"):
        cs = board()
        c = {"id": "t_%04d" % (len(cs) + 1), "title": title, "assignee": who, "body": body, "status": status,
             "created_at": 1000 + len(cs), "result": None}
        put(cs + [c])
        return c["id"]

    def setc(cid, **kw):
        cs = board()
        for c in cs:
            if c["id"] == cid:
                c.update(kw)
        put(cs)

    def state(slug):
        return b.load(slug)

    def tick():
        b.cmd_tick([])

    # ---- reading a card's checks ---------------------------------------------------------------------------------
    body = """Build: x
## Outcome
it works
## Verification
1. `curl -s localhost:1/a` → `{"ok": true}`
- `test -f a.txt && echo yes` -> yes (the file is there)
- `python3 -c 'print(2+2)'` → 4.
- `false` → exit 1
- `curl -s http://h:1/` → 200 (live)
- the button looks right
3. `grep -c a f.txt` → `8`; `grep -c b g.txt` → `23` (two on one line)
4. (live) `curl -s x/stats` → `"decks": 8`
Not covered: taste
## Constraints
- `rm -rf /` → nothing (not a check: outside Verification)
"""
    cs, manual = b.parse_checks(body)
    check("checks: every runnable check read from Verification only", len(cs) == 8, cs)
    check("checks: backticked expectation kept as written", cs[0]["expect"] == '{"ok": true}', cs[0])
    check("checks: plain expectation stops at a parenthesis", cs[1]["expect"] == "yes", cs[1])
    check("checks: trailing full stop dropped", cs[2]["expect"] == "4", cs[2])
    check("checks: (live) marks a running-app check", [c["live"] for c in cs] == [False] * 4 + [True, False, False, True], cs)
    check("checks: two checks on one line are both read", [c["expect"] for c in cs[5:7]] == ["8", "23"], cs[5:7])
    check("checks: a (live) item with a quoted expectation", cs[7] == {"cmd": "curl -s x/stats", "expect": '"decks": 8', "live": True}, cs[7])
    check("checks: an item with no command is listed, not run", manual == ["the button looks right"], manual)
    ok, rc, out = b.run_check({"cmd": "false", "expect": "exit 1"}, home)
    check("checks: `exit <n>` compares the exit code", ok and rc == 1)
    ok, *_ = b.run_check({"cmd": "echo '{\"ok\":   true}'", "expect": '{"ok": true}'}, home)
    check("checks: whitespace differences don't fail a check", ok)
    ok10, *_ = b.run_check({"cmd": "echo 10", "expect": "0"}, home)
    ok0, *_ = b.run_check({"cmd": "echo '  0'", "expect": "0"}, home)
    okin, *_ = b.run_check({"cmd": "echo 'decks: 8 total'", "expect": "8"}, home)
    check("checks: a number matches only as a whole number", not ok10 and ok0 and okin, (ok10, ok0, okin))
    w = b.outdated("Fixed the strip.\noutdated: `grep -c placehold.co x.html` — t_2 replaced the placeholders\n- OUTDATED: `wc -l y`")
    check("checks: outdated lines in a fix card's result are read", w == {"grep -c placehold.co x.html": "t_2 replaced the placeholders",
                                                                       "wc -l y": "no reason given"}, w)

    # ---- a build of two cards goes live in one check and one landing ---------------------------------------------
    b.cmd_start(["feat", "--title", "Two things"])
    s = state("feat")
    wt = pathlib.Path(s["worktree"])
    check("start: branch build/feat and its worktree", s["branch"] == "build/feat" and wt.is_dir()
          and sh("git rev-parse --abbrev-ref HEAD", wt).stdout.strip() == "build/feat", s)
    check("start: waits for planning", s["state"] == "planning")
    b.cmd_ready(["feat"])
    c1 = card("Part one", "Build: feat\n## Verification\n- `cat one.txt` → `one`\n- `curl -s app` → `up` (live)\n")
    c2 = card("Part two", "Build: feat\nReview: none\n## Verification\n- `cat two.txt` → two\n")
    (home / "live-check").write_text("")
    setc(c1, body=board()[0]["body"].replace("curl -s app", f"cat {home}/live-check; echo up"))
    tick()
    check("building: progress counts the cards", state("feat")["step"].startswith("0/2 done"), state("feat")["step"])
    (wt / "one.txt").write_text("one\n")
    sh("git add -A && git commit -qm one", wt)
    setc(c1, status="done")
    tick()
    check("building: one card done is not the end", state("feat")["state"] == "building" and "1/2" in state("feat")["step"])
    (wt / "two.txt").write_text("two\n")
    sh("git add -A && git commit -qm two", wt)
    setc(c2, status="done")
    log0 = (home / "systemctl.log").read_text() if (home / "systemctl.log").exists() else ""
    tick()
    s = state("feat")
    check("live: every card done -> checked once and landed", s["state"] == "live", s.get("step"))
    check("live: main has both cards' work", (repo / "one.txt").exists() and (repo / "two.txt").exists())
    check("live: one merge commit on main", "Land build feat" in sh("git log -1 --format=%s", repo).stdout)
    restarts = (home / "systemctl.log").read_text()[len(log0):]
    check("live: the app's service restarted, not the design view or others",
          "restart myapp.service" in restarts and "restart design-view" not in restarts and "restart other" not in restarts, restarts)
    check("live: worktree and branch removed", not wt.exists()
          and sh("git branch --list build/feat", repo).stdout.strip() == "")
    check("live: the history keeps each stage", [h["state"] for h in s["history"]][-2:] == ["landing", "live"]
          and any(h["state"] == "checking" for h in s["history"]), s["history"])
    check("live: logged to the vault", "Build feat is live" in (home / "vault.log").read_text())

    # ---- a failing check: one fix card with everything, then it goes live -----------------------------------------
    b.cmd_start(["fix1"])
    b.cmd_ready(["fix1"])
    wt = pathlib.Path(state("fix1")["worktree"])
    c3 = card("Thing", "Build: fix1\n## Verification\n- `cat three.txt` → three\n- `cat four.txt` → four\n")
    (wt / "three.txt").write_text("three\n")
    sh("git add -A && git commit -qm three", wt)
    setc(c3, status="done")
    tick()
    s = state("fix1")
    fixes = [c for c in board() if c["title"].startswith("Fix build fix1")]
    check("fail: a failing card check makes one Engineer fix card", len(fixes) == 1 and fixes[0]["assignee"] == "engineer"
          and s["state"] == "building", (s["state"], [c["title"] for c in board()]))
    check("fail: the fix card carries the build line, the failure, and the worktree",
          "Build: fix1" in fixes[0]["body"] and "four.txt" in fixes[0]["body"] and fixes[0]["workspace"] == f"dir:{wt}")
    check("fail: nothing reached main", not (repo / "three.txt").exists())
    (wt / "four.txt").write_text("four\n")
    sh("git add -A && git commit -qm four", wt)
    tick()
    check("fail: waits for the fix card", state("fix1")["state"] == "building")
    setc(fixes[0]["id"], status="done")
    tick()
    check("fail: fixed -> live", state("fix1")["state"] == "live" and (repo / "four.txt").exists(), state("fix1")["step"])

    # ---- a later card changed what an earlier card checked: the fix card says so, the build waives it -------------
    b.cmd_start(["waive"])
    b.cmd_ready(["waive"])
    wt = pathlib.Path(state("waive")["worktree"])
    ca = card("Fold", "Build: waive\n## Verification\n- `grep -c PLACEHOLDER strip.html` → `4`\n")
    cb = card("Wire", "Build: waive\n## Verification\n- `grep -c data-bind strip.html` → `4`\n")
    (wt / "strip.html").write_text("data-bind\n" * 4)
    sh("git add -A && git commit -qm strip", wt)
    setc(ca, status="done")
    setc(cb, status="done")
    tick()
    fx = [c for c in board() if c["title"].startswith("Fix build waive")]
    check("waive: the superseded check fails the build once", len(fx) == 1 and "outdated:" in fx[0]["body"])
    setc(fx[0]["id"], status="done", result="Nothing to fix.\noutdated: `grep -c PLACEHOLDER strip.html` — Wire replaced the placeholders")
    tick()
    s = state("waive")
    plan_comments = s.get("waived")
    check("waive: then it's skipped, recorded, and the build goes live", s["state"] == "live"
          and "grep -c PLACEHOLDER strip.html" in (s.get("waived") or {}) and "WAIVED" in s.get("check_report", ""), (s["state"], plan_comments))

    # ---- the running app fails after landing: main goes back, a fix card ------------------------------------------
    b.cmd_start(["bad-live"])
    b.cmd_ready(["bad-live"])
    wt = pathlib.Path(state("bad-live")["worktree"])
    before = sh("git rev-parse HEAD", repo).stdout.strip()
    c4 = card("Live", f"Build: bad-live\n## Verification\n- `cat five.txt` → five\n- `cat {home}/nope.txt` → hi (live)\n")
    (wt / "five.txt").write_text("five\n")
    sh("git add -A && git commit -qm five", wt)
    setc(c4, status="done")
    tick()
    s = state("bad-live")
    check("live fail: main put back where it was", sh("git rev-parse HEAD", repo).stdout.strip() == before
          and not (repo / "five.txt").exists(), s.get("step"))
    check("live fail: a fix card and back to building", s["state"] == "building"
          and any(c["title"].startswith("Fix build bad-live") for c in board()))

    # ---- the third failure goes to the Manager, not round again ---------------------------------------------------
    for i in range(2):
        fx = [c for c in board() if c["title"].startswith("Fix build bad-live") and c["status"] != "done"][0]
        setc(fx["id"], status="done")
        tick()
    s = state("bad-live")
    mgr = [c for c in board() if c["title"].startswith("Build bad-live keeps failing")]
    check("stuck: third failure -> Manager card, the build stops", s["state"] == "stuck" and len(mgr) == 1
          and mgr[0]["assignee"] == "manager", (s["state"], s.get("fails")))
    tick()
    check("stuck: nothing more happens on its own", len([c for c in board() if "bad-live" in c["title"]]) == 3)
    b.cmd_abort(["bad-live", "test"])
    check("abort: stops the build", state("bad-live")["state"] == "aborted")

    # ---- a review: one Tester card for the whole build -------------------------------------------------------------
    (home / ".hermes" / "profiles" / "tester").mkdir(parents=True)
    b.cmd_start(["rev"])
    b.cmd_ready(["rev"])
    wt = pathlib.Path(state("rev")["worktree"])
    c5 = card("Saves", "Build: rev\nReview: tester\n## Verification\n- `cat six.txt` → six\n")
    c6 = card("Loads", "Build: rev\nReview: tester\n## Verification\n- `cat six.txt` → six\n")
    (wt / "six.txt").write_text("six\n")
    sh("git add -A && git commit -qm six", wt)
    setc(c5, status="done")
    setc(c6, status="done")
    tick()
    revs = [c for c in board() if c["title"] == "Review build rev"]
    check("review: one Tester card for two cards that asked for it", len(revs) == 1 and state("rev")["state"] == "reviewing")
    check("review: it carries the script's check table", "PASS" in revs[0]["body"] and "Review-of: rev" in revs[0]["body"])
    setc(revs[0]["id"], status="done", result="CHANGES: saving twice loses the first")
    tick()
    check("review: changes -> a fix card with the Tester's words", state("rev")["state"] == "building" and any(
        "saving twice" in c["body"] for c in board() if c["title"].startswith("Fix build rev")))
    fx = [c for c in board() if c["title"].startswith("Fix build rev")][0]
    setc(fx["id"], status="done")
    tick()
    revs = [c for c in board() if c["title"] == "Review build rev"]
    check("review: re-reviewed after the fix", len(revs) == 2 and state("rev")["state"] == "reviewing")
    setc(revs[1]["id"], status="done", result="APPROVED: all cases pass")
    tick()
    check("review: approved -> live", state("rev")["state"] == "live" and (repo / "six.txt").exists())

    # ---- a plan card: the build waits for it ---------------------------------------------------------------------
    plan = card("Build the agreed design (x)", "body", who="manager", status="running")
    b.cmd_start(["design-x", "--design", "x", "--plan-card", plan])
    s = state("design-x")
    check("design: branch design/<stamp>", s["branch"] == "design/x" and s["design"] == "x")
    c7 = card("Fold", "Build: design-x\n## Verification\n- `true` → exit 0\n", who="designer", status="done")
    tick()
    check("plan card: still planning while it runs", state("design-x")["state"] == "planning")
    setc(plan, status="done")
    tick()
    check("plan card: done -> built -> live", state("design-x")["state"] == "live", state("design-x")["step"])
    st = b.status_of(state("design-x"), board())
    check("status: lists the plan card first, then the build's cards", [c["id"] for c in st["cards"]] == [plan, c7], st["cards"])
    check("status: live comment on the plan card", any("is live" in x for x in
                                                      [c for c in board() if c["id"] == plan][0].get("comments", [])))

    # ---- main checkout has uncommitted work: never merged over, straight to the Manager --------------------------
    b.cmd_start(["dirty"])
    b.cmd_ready(["dirty"])
    wt = pathlib.Path(state("dirty")["worktree"])
    c8 = card("D", "Build: dirty\n## Verification\n- `true` → exit 0\n")
    (wt / "d.txt").write_text("d\n")
    sh("git add -A && git commit -qm d", wt)
    (repo / "one.txt").write_text("someone's edit\n")
    setc(c8, status="done")
    tick()
    check("dirty main: not merged, the Manager gets it", state("dirty")["state"] == "stuck"
          and (repo / "one.txt").read_text() == "someone's edit\n" and not (repo / "d.txt").exists())
    sh("git checkout -q one.txt", repo)

    # ---- a failing suite stops the build before anything merges --------------------------------------------------
    b.cmd_start(["suite"])
    b.cmd_ready(["suite"])
    wt = pathlib.Path(state("suite")["worktree"])
    c9 = card("S", "Build: suite\n## Verification\n- `true` → exit 0\n")
    (wt / "BROKEN").write_text("x")
    sh("git add -A && git commit -qm broken", wt)
    setc(c9, status="done")
    tick()
    fx = [c for c in board() if c["title"].startswith("Fix build suite")]
    check("suite: a failing suite -> fix card with its output", len(fx) == 1 and "FAIL suite" in fx[0]["body"]
          and not (repo / "BROKEN").exists())

    # ---- idle tick costs nothing --------------------------------------------------------------------------------
    for s in b.all_builds():
        if s["state"] in b.OPEN:
            b.cmd_abort([s["slug"]])
    n = len((home / "systemctl.log").read_text())
    put([])
    tick()
    check("idle: no open builds -> no board read, no systemctl", len((home / "systemctl.log").read_text()) == n)

    shutil.rmtree(home, ignore_errors=True)
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
