#!/usr/bin/python3
"""Edge cases for template/scripts/hermes-worker.py (card workers that resume a topic session).

  python3 tests/test_hermes_worker.py      (Linux; a fake `hermes` and a fake session database in a temp folder)
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

WRAPPER = pathlib.Path(__file__).resolve().parent.parent / "template" / "scripts" / "hermes-worker.py"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


FAKE = r'''#!/usr/bin/python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["kanban", "show"]:
    print(json.dumps({"task": {"id": a[2], "body": os.environ.get("FAKE_BODY", "")},
                      "runs": json.loads(os.environ.get("FAKE_RUNS", "[]"))})); sys.exit(0)
if a[:2] == ["kanban", "runs"]:
    open(os.environ["FAKE_OUT"] + ".runs-called", "w").write("1")
    print(os.environ.get("FAKE_RUNS", "[]")); sys.exit(0)
if a[:2] == ["kanban", "comment"]:
    open(os.environ["FAKE_OUT"] + ".comments", "a").write(a[3] + "\n"); sys.exit(0)
open(os.environ["FAKE_OUT"], "w").write(json.dumps(a)); sys.exit(0)
'''


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="hwtest-"))
    home = tmp / "profiles" / "designer"
    home.mkdir(parents=True)
    fake = tmp / "hermes"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    out = tmp / "out.json"
    db = sqlite3.connect(home / "state.db")
    db.executescript("""
      CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT, end_reason TEXT, ended_at REAL,
                             started_at REAL, last_activity_at REAL, model_config TEXT);
      CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT);""")
    now = time.time()

    def add_session(sid, task=None, parent=None, end_reason=None, ended=None, active=None, cfg=None, source="kanban"):
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)", (sid, source, parent, end_reason, ended, now - 100,
                                                                      active or now - 50, json.dumps(cfg or {})))
        if task:
            db.execute("INSERT INTO messages (session_id, role, content) VALUES (?,?,?)", (sid, "user", f"work kanban task {task}"))
        db.commit()

    def run(task, body, runs="[]", argv=None):
        if out.exists():
            out.unlink()
        env = {**os.environ, "HERMES_HOME": str(home), "HERMES_REAL_BIN": str(fake), "HERMES_KANBAN_TASK": task,
               "FAKE_BODY": body, "FAKE_RUNS": runs, "FAKE_OUT": str(out)}
        argv = argv or ["-p", "designer", "--cli", "--accept-hooks", "chat", "-q", f"work kanban task {task}"]
        r = subprocess.run([sys.executable, str(WRAPPER), *argv], env=env, capture_output=True, text=True, timeout=60)
        got = json.loads(out.read_text()) if out.exists() else None
        return got, r.stdout + r.stderr

    def resumed(got):
        return got[got.index("--resume") + 1] if got and "--resume" in got else None

    topics = home / "topic-sessions.json"

    comments = out.with_suffix(".json.comments")
    got, log = run("t_1", "Context: no topic here.")
    check("no Session line, first run: the card runs as before", got == ["-p", "designer", "--cli", "--accept-hooks", "chat", "-q", "work kanban task t_1"], got)
    check("...recorded under the card's own topic", json.loads(topics.read_text()).get("card:t_1", {}).get("pending_task") == "t_1", log)
    check("...and no comment on the card for a normal first run", not comments.exists())
    add_session("C1", task="t_1")
    got, log = run("t_1", "Context: no topic here.", runs=json.dumps([{"profile": "designer", "outcome": "changes_requested", "ended_at": now}]))
    check("the same card back for changes resumes its own session", resumed(got) == "C1", log)
    got, log = run("t_1", "Context: no topic here.", runs=json.dumps([{"profile": "designer", "outcome": "timed_out", "ended_at": now,
                                                                      "error": "Iteration budget exhausted (90/90) - task could not complete"}]))
    check("a card that ran out of turns resumes its session", resumed(got) == "C1", log)
    check("the card's runs come from the one `show` call", not out.with_suffix(".json.runs-called").exists())
    got, log = run("t_1", "Context: no topic here.", runs=json.dumps([{"profile": "designer", "outcome": "crashed", "ended_at": now}]))
    check("a card whose run crashed starts fresh", resumed(got) is None, log)
    got, log = run("t_1b", "Context: another card.")
    check("a different card doesn't get another card's session", resumed(got) is None, log)
    got, _ = run("t_x", "", argv=["gateway", "run"])
    check("other commands pass straight through", got == ["gateway", "run"], got)

    got, log = run("t_2", "Context: a round.\nSession: design:atlas-air\n")
    check("first card on a topic: fresh, recorded as pending", resumed(got) is None
          and json.loads(topics.read_text())["design:atlas-air"].get("pending_task") == "t_2", log)
    add_session("S1", task="t_2")
    got, log = run("t_3", "Session: design:atlas-air")
    check("next card on the topic resumes the first card's session", resumed(got) == "S1", log)
    check("--resume goes right after chat", got and got[got.index("chat") + 1] == "--resume", got)
    check("the decision is noted on the card", "resumed `S1`" in (out.with_suffix(".json.comments").read_text()
                                                                    if out.with_suffix(".json.comments").exists() else ""))

    db.execute("UPDATE sessions SET end_reason='compression', ended_at=? WHERE id='S1'", (now - 40,))
    add_session("S1b", parent="S1", ended=now - 10, active=now - 10)
    add_session("S1-delegate", parent="S1", cfg={"_delegate_from": "S1"}, active=now)
    got, log = run("t_4", "Session: design:atlas-air")
    check("a condensed session resumes at its continuation, not a delegate", resumed(got) == "S1b", log)

    got, log = run("t_4", "Session: design:atlas-air", runs=json.dumps([{"profile": "designer", "outcome": "changes_requested", "ended_at": now}]))
    check("a card sent back for changes resumes", resumed(got) == "S1b", log)
    got, log = run("t_4", "Session: design:atlas-air", runs=json.dumps([{"profile": "designer", "outcome": "timed_out", "ended_at": now}]))
    check("a card whose last run timed out starts fresh", resumed(got) is None, log)
    add_session("S2", task="t_4")
    got, log = run("t_5", "Session: design:atlas-air", runs=json.dumps([{"profile": "tester", "outcome": "timed_out", "ended_at": now}]))
    check("another bot's failed run doesn't count", resumed(got) == "S2", log)

    sleeper = subprocess.Popen(["sleep", "30"])
    start = pathlib.Path(f"/proc/{sleeper.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    lock = home / "topic-locks" / "design__atlas-air.lock"
    lock.write_text(json.dumps({"pid": sleeper.pid, "start": start}))
    before = json.loads(topics.read_text())["design:atlas-air"]
    got, log = run("t_6", "Session: design:atlas-air")
    check("a topic held by a live worker: this card starts fresh", resumed(got) is None, log)
    check("...and the topic's session is left as it was", json.loads(topics.read_text())["design:atlas-air"] == before)
    sleeper.kill(); sleeper.wait()
    got, log = run("t_7", "Session: design:atlas-air")
    check("a lock left by a finished worker is taken over", resumed(got) == "S2", log)
    lock.write_text(json.dumps({"pid": os.getpid(), "start": "0"}))
    got, log = run("t_8", "Session: design:atlas-air")
    check("a lock whose pid was reused by another process is taken over", resumed(got) == "S2", log)
    sleeper = subprocess.Popen(["sleep", "30"])
    start = pathlib.Path(f"/proc/{sleeper.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    lock.write_text(json.dumps({"pid": sleeper.pid, "start": start, "task": "t_8"}))
    got, log = run("t_8", "Session: design:atlas-air", runs=json.dumps([{"profile": "designer", "outcome": "review_requested", "ended_at": now}]))
    check("the same card's earlier run, still exiting, doesn't block its rerun", resumed(got) == "S2", log)
    sleeper.kill()
    sleeper.wait()
    sleeper = subprocess.Popen(["sleep", "3"])        # the card's previous worker, still writing its last reply
    start = pathlib.Path(f"/proc/{sleeper.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    lock.write_text(json.dumps({"pid": sleeper.pid, "start": start, "task": "t_8"}))
    t0 = time.time()
    got, log = run("t_8", "Session: design:atlas-air", runs=json.dumps([{"profile": "designer", "outcome": "review_requested", "ended_at": now}]))
    check("a rerun waits for the card's previous worker to exit, then resumes", resumed(got) == "S2" and time.time() - t0 >= 2, (time.time() - t0, log))
    sleeper.wait()
    (home / "runtime").mkdir(exist_ok=True)
    holder = subprocess.Popen(["sleep", "3"])
    (home / "runtime" / "active_sessions.json").write_text(json.dumps({"entries": [{"session_id": "S2", "pid": holder.pid}]}))
    t0 = time.time()
    got, log = run("t_8c", "Session: design:atlas-air")
    check("a session Hermes has open in another process is waited for", resumed(got) == "S2" and time.time() - t0 >= 2, (time.time() - t0, log))
    holder.wait()
    (home / "runtime" / "active_sessions.json").write_text(json.dumps({"entries": []}))
    sleeper = subprocess.Popen(["sleep", "30"])
    start = pathlib.Path(f"/proc/{sleeper.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    sleeper.kill()
    lock.write_text(json.dumps({"pid": sleeper.pid, "start": start, "task": "t_other"}))   # killed, not yet reaped: a zombie
    got, log = run("t_8b", "Session: design:atlas-air")
    check("a lock held by a zombie (finished, not yet reaped) is taken over", resumed(got) == "S2", log)
    sleeper.wait()

    db.execute("UPDATE sessions SET last_activity_at=? WHERE id='S2'", (now - 5 * 86400,))
    db.commit()
    got, log = run("t_9", "Session: design:atlas-air")
    check("a session idle over 3 days starts fresh", resumed(got) is None, log)

    data = json.loads(topics.read_text())
    data["research:x"] = {"session": "GONE", "runs": 3, "last_task": "t_0"}
    topics.write_text(json.dumps(data))
    got, log = run("t_10", "Session: research:x")
    check("a session missing from this bot's database starts fresh", resumed(got) is None, log)

    add_session("S3", task="t_11")
    data = json.loads(topics.read_text())
    data["eng:ui"] = {"session": "S3", "runs": 2, "last_task": "t_11"}
    topics.write_text(json.dumps(data))
    got, log = run("t_12", "Session: new eng:ui")
    check("`Session: new <topic>` starts the topic over", resumed(got) is None, log)
    data = json.loads(topics.read_text())
    data["eng:ui"] = {"session": "S3", "runs": 40, "last_task": "t_11"}
    topics.write_text(json.dumps(data))
    got, log = run("t_13", "Session: eng:ui")
    check("a topic at its run limit starts fresh", resumed(got) is None, log)
    before = json.loads(topics.read_text())
    got, log = run("t_14", "Session: none")
    check("'Session: none': fresh, nothing recorded", resumed(got) is None and json.loads(topics.read_text()) == before, log)
    for body in ("Session: Not A Topic!", "Session: ../../etc"):
        got, log = run("t_14b", body)
        check(f"{body!r}: fresh, under the card's own topic only", resumed(got) is None and "card:t_14b" in json.loads(topics.read_text())
              and not any(".." in k or "!" in k for k in json.loads(topics.read_text())), log)
    data = json.loads(topics.read_text())
    data["card:t_old"] = {"session": "OLD", "runs": 1, "last_task": "t_old", "updated": "2020-01-01 00:00"}
    data["card:t_bad"] = {"session": "BAD", "runs": 1, "last_task": "t_bad", "updated": "garbage"}
    data["eng:old"] = {"session": "S9", "runs": 1, "last_task": "t_9", "updated": "2020-01-01 00:00"}
    topics.write_text(json.dumps(data))
    run("t_14c", "Context: anything.")
    data = json.loads(topics.read_text())
    check("idle per-card entries are pruned, named topics kept", "card:t_old" not in data and "card:t_bad" not in data and "eng:old" in data, data.keys())
    got, log = run("t_15", "Line one\n**Session:** `design:demo-1`\n")
    check("a bold or backticked Session line is read", "design:demo-1" in json.loads(topics.read_text()), log)
    got, log = run("t_16", "Session: design:atlas-air", argv=["-p", "designer", "--cli", "chat", "--resume", "X", "-q", "work kanban task t_16"])
    check("a worker that already resumes is left alone", resumed(got) == "X", got)
    kdb = tmp / "kanban.db"
    k = sqlite3.connect(kdb)
    k.executescript("""CREATE TABLE tasks (id TEXT PRIMARY KEY, body TEXT);
      CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id TEXT, profile TEXT, outcome TEXT, error TEXT, ended_at REAL);""")
    k.execute("INSERT INTO tasks VALUES ('t_20', 'Session: design:fromdb')")
    k.commit()
    os.environ["HERMES_KANBAN_DB"] = str(kdb)
    got, log = run("t_20", "Session: design:fromcli")
    check("the card is read from the board's database when the dispatcher names it", "design:fromdb" in json.loads(topics.read_text())
          and "design:fromcli" not in json.loads(topics.read_text()), log)
    add_session("D1", task="t_20")
    k.execute("INSERT INTO task_runs (task_id, profile, outcome, error, ended_at) VALUES ('t_20', 'designer', 'timed_out', 'Iteration budget exhausted (90/90)', ?)", (now,))
    k.commit()
    got, log = run("t_20", "")
    check("...and its runs too (out of turns: resumes)", resumed(got) == "D1", log)
    got, log = run("t_21", "Session: design:fromcli")
    check("a card missing from that database falls back to the hermes command", "design:fromcli" in json.loads(topics.read_text()), log)
    os.environ.pop("HERMES_KANBAN_DB", None)
    os.environ.pop("HERMES_KANBAN_TASK", None)
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
