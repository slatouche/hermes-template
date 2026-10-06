#!/usr/bin/python3
"""Card workers that resume a topic session instead of starting from nothing.

Hermes runs every kanban card as a fresh `hermes ... chat -q "work kanban task <id>"`, so each card re-learns the
project. The gateway launches workers through $HERMES_BIN when it's set; this script is that launcher. For a card
whose text has a line `Session: <topic>` (for example `Session: design:atlas-air`), it resumes the bot's last
session for that topic (`chat --resume <id>`), so the same bot on the same area carries on where it left off.
Everything else (other commands, cards without a topic, anything unexpected) runs the real `hermes` untouched.

Choosing the right session, per bot (each bot has its own topics file and session database):
  - topic -> the session recorded for it in <bot home>/topic-sessions.json; a topic first used by a card is recorded
    as "pending" and resolved on its next use from the session that card's worker started;
  - follow Hermes's own compression chain to the live continuation (a long session is condensed into a child);
  - resume only if that session exists in this bot's database, isn't a branch/delegate/tool child, was active in
    the last MAX_IDLE_DAYS, has had fewer than MAX_RUNS cards, and no live worker holds the topic (a lock file
    naming the worker's process and its start time, so a dead or finished worker never leaves it stuck);
  - a card whose last run by this bot failed (timed out, crashed, errored) starts fresh, since the resumed session
    may be what went wrong; a card sent back for changes, unblocked or reviewed resumes with its context;
  - `Session: new <topic>` starts the topic over; `Session: none` (or no line) is a fresh session as before.
Every decision is logged (<bot home>/logs/topic-sessions.log) and noted on the card.

  hermes-worker.py --topics [list | reset <topic>]     inspect or reset this bot's topics (run with HERMES_HOME set)
"""
import datetime
import fcntl
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import time

MAX_IDLE_DAYS = 3
MAX_RUNS = 40
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{0,79}$")
SESSION_LINE = re.compile(r"^\s*(?:\*\*)?Session:(?:\*\*)?\s*(.+?)\s*$", re.M | re.I)


def real_hermes():
    for cand in (os.environ.get("HERMES_REAL_BIN"), str(pathlib.Path.home() / ".local/bin/hermes")):
        if cand and os.access(cand, os.X_OK) and os.path.realpath(cand) != os.path.realpath(__file__):
            return cand
    return "hermes"


def run_real(argv):
    os.execv(real_hermes(), [real_hermes(), *argv])


def log(home, msg):
    try:
        d = home / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "topic-sessions.log", "a") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass
    print(f"[topic-session] {msg}", flush=True)       # lands in the card's worker log


def card_text(task, env):
    r = subprocess.run([real_hermes(), "kanban", "show", task, "--json"], capture_output=True, text=True, env=env, timeout=60)
    d = json.loads(r.stdout or "{}")
    t = d.get("task") or d
    return t.get("body") or ""


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, path)


def compression_tip(home, sid):
    """Hermes's own resolver (its runtime, its rules); a careful SQL fallback if that can't load."""
    launcher = pathlib.Path(real_hermes()).resolve()
    try:
        text = launcher.read_text(errors="replace")
        shim = re.search(r'^exec "?(/\S+/bin/hermes)"? "\$@"', text, re.M)   # ~/.local/bin/hermes is a one-line shim
        if shim and "python" not in text:
            text = pathlib.Path(shim.group(1)).read_text(errors="replace")
        py = re.search(r"exec (\S+/python3?\S*) -I", text)
        agent = re.search(r"sys\.path\.insert\(0, '+\"*'*([^'\"]+hermes-agent)", text)
        if py and agent:
            code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); import hermes_bootstrap; "
                    "from hermes_state import SessionDB; "
                    "print(SessionDB(pathlib.Path(sys.argv[2]), read_only=True).get_compression_tip(sys.argv[3]) or '')")
            r = subprocess.run([py.group(1), "-I", "-c", code, agent.group(1), str(home / "state.db"), sid],
                               capture_output=True, text=True, timeout=60)
            tip = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
            if tip:
                return tip
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    con = sqlite3.connect(f"file:{home / 'state.db'}?mode=ro", uri=True)
    cur, seen = sid, {sid}
    for _ in range(1000):
        row = con.execute(
            "SELECT c.id FROM sessions p JOIN sessions c ON c.parent_session_id = p.id WHERE p.id = ? "
            "AND p.end_reason = 'compression' AND COALESCE(c.source, '') != 'tool' "
            "AND COALESCE(json_extract(CASE WHEN json_valid(c.model_config) THEN c.model_config ELSE '{}' END, '$._branched_from'), "
            "json_extract(CASE WHEN json_valid(c.model_config) THEN c.model_config ELSE '{}' END, '$._delegate_from'), "
            "json_extract(CASE WHEN json_valid(c.model_config) THEN c.model_config ELSE '{}' END, '$._reset_from')) IS NULL "
            "ORDER BY CASE WHEN c.end_reason = 'compression' THEN 0 WHEN c.ended_at IS NULL THEN 1 ELSE 2 END, "
            "COALESCE(c.last_activity_at, c.started_at) DESC LIMIT 1", (cur,)).fetchone()
        if not row or row[0] in seen:
            break
        cur = row[0]
        seen.add(cur)
    return cur


def session_row(home, sid):
    con = sqlite3.connect(f"file:{home / 'state.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    return dict(row) if row else None


def session_of_task(home, task):
    """The session a card's worker started (its first message is `work kanban task <id>`), newest first."""
    con = sqlite3.connect(f"file:{home / 'state.db'}?mode=ro", uri=True)
    row = con.execute(
        "SELECT s.id FROM sessions s WHERE s.source = 'kanban' AND EXISTS (SELECT 1 FROM messages m WHERE "
        "m.session_id = s.id AND m.role = 'user' AND m.content = ?) ORDER BY s.started_at DESC LIMIT 1",
        (f"work kanban task {task}",)).fetchone()
    return row[0] if row else None


def is_fork(row):
    if row.get("source") == "tool":
        return True
    try:
        cfg = json.loads(row.get("model_config") or "{}")
    except ValueError:
        return False
    parent = row.get("parent_session_id")
    return isinstance(cfg, dict) and parent is not None and parent in (cfg.get("_branched_from"), cfg.get("_delegate_from"))


FAILED = {"timed_out", "crashed", "failed", "spawn_failed", "error", "errored", "killed", "gave_up",
          "protocol_violation", "reclaimed"}


def last_run_failed(task, env, profile):
    """This bot's most recent finished run on the card ended in a failure."""
    try:
        r = subprocess.run([real_hermes(), "kanban", "runs", task, "--json"], capture_output=True, text=True, env=env, timeout=60)
        d = json.loads(r.stdout or "[]")
        runs = d if isinstance(d, list) else d.get("runs", [])
        mine = [x for x in runs if x.get("profile") == profile and x.get("ended_at")]
        return bool(mine) and str(mine[-1].get("outcome") or "") in FAILED
    except Exception:
        return False


def proc_start(pid):
    try:
        return pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def take_topic(lockdir, topic):
    """Claim the topic for this process (whose pid the real worker keeps, via exec). A claim by a process that's
    gone, or whose pid now belongs to something else, is stale and taken over. Returns False if a live worker has it."""
    path = lockdir / (topic.replace(":", "__") + ".lock")
    fd = os.open(lockdir / ".guard", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            held = json.loads(path.read_text())
        except (OSError, ValueError):
            held = {}
        pid = held.get("pid")
        if pid and pid != os.getpid() and proc_start(pid) and proc_start(pid) == held.get("start"):
            return False
        path.write_text(json.dumps({"pid": os.getpid(), "start": proc_start(os.getpid()), "since": time.time()}))
        return True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def note_on_card(task, env, text):
    try:
        subprocess.Popen([real_hermes(), "kanban", "comment", task, text], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def topics_cli(args):
    home = pathlib.Path(os.environ.get("HERMES_HOME") or pathlib.Path.home() / ".hermes")
    path = home / "topic-sessions.json"
    data = load(path)
    if args[:1] == ["reset"] and len(args) > 1:
        data.pop(args[1], None)
        save(path, data)
        print(f"{args[1]}: reset (the next card starts a fresh session)")
        return 0
    for topic, e in sorted(data.items()):
        print(f"{topic:40} {e.get('session') or 'pending ' + str(e.get('pending_task'))}  runs {e.get('runs', 0)}  "
              f"last card {e.get('last_task')}  {e.get('updated', '')}")
    return 0


def main(argv):
    if argv[:1] == ["--topics"]:
        return topics_cli(argv[1:])
    # A card worker looks like: ... -p <profile> ... chat -q "work kanban task <id>"
    if "chat" not in argv or "-q" not in argv:
        run_real(argv)
    q = argv[argv.index("-q") + 1] if argv.index("-q") + 1 < len(argv) else ""
    m = re.fullmatch(r"work kanban task (\S+)", q)
    task = os.environ.get("HERMES_KANBAN_TASK") or (m.group(1) if m else None)
    if not (m and task) or "--resume" in argv or "-r" in argv or "--continue" in argv:
        run_real(argv)
    home = pathlib.Path(os.environ.get("HERMES_HOME") or "")
    if not (home / "state.db").exists():
        run_real(argv)
    env = dict(os.environ)
    try:
        lines = SESSION_LINE.findall(card_text(task, env))
    except Exception:
        lines = []
    if not lines:
        run_real(argv)
    want = lines[-1].strip().strip("`").lower()
    fresh_start = want.startswith("new ")
    topic = want[4:].strip() if fresh_start else want
    if topic in ("none", "-", "fresh") or not TOPIC_RE.match(topic):
        log(home, f"{task}: no usable topic ({want!r}): fresh session")
        run_real(argv)

    path = home / "topic-sessions.json"
    lockdir = home / "topic-locks"
    lockdir.mkdir(exist_ok=True)
    if not take_topic(lockdir, topic):
        log(home, f"{task}: topic {topic} is in use by another worker: fresh session, topic left as it is")
        note_on_card(task, env, f"Session `{topic}`: busy with another card, so this one started fresh.")
        run_real(argv)
    profile = home.name if home.parent.name == "profiles" else "default"

    data = load(path)
    entry = data.get(topic) or {}
    now = time.time()
    sid, why = None, ""
    if fresh_start:
        why = "the card asked to start the topic over"
    elif entry.get("last_task") == task and last_run_failed(task, env, profile):
        why = "this card's last run failed, so it starts fresh"
    else:
        sid = entry.get("session") or (session_of_task(home, entry["pending_task"]) if entry.get("pending_task") else None)
        if not sid:
            why = "first card on this topic"
        else:
            sid = compression_tip(home, sid)
            row = session_row(home, sid)
            if not row:
                why, sid = f"session {sid} is not in this bot's database", None
            elif is_fork(row):
                why, sid = f"session {sid} is a branch or delegate, not a conversation", None
            elif now - (row.get("last_activity_at") or row.get("started_at") or 0) > MAX_IDLE_DAYS * 86400:
                why, sid = f"session {sid} has been idle over {MAX_IDLE_DAYS} days", None
            elif entry.get("runs", 0) >= MAX_RUNS:
                why, sid = f"topic has run {MAX_RUNS} cards", None
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if sid:
        data[topic] = {"session": sid, "runs": entry.get("runs", 0) + 1, "last_task": task, "updated": stamp}
        save(path, data)
        log(home, f"{task}: topic {topic}: resuming session {sid} (card {data[topic]['runs']} on this topic)")
        note_on_card(task, env, f"Session `{topic}`: resumed `{sid}` (card {data[topic]['runs']} on this topic).")
        i = argv.index("chat") + 1
        run_real(argv[:i] + ["--resume", sid] + argv[i:])
    data[topic] = {"pending_task": task, "runs": 1, "last_task": task, "updated": stamp}
    save(path, data)
    log(home, f"{task}: topic {topic}: fresh session ({why})")
    note_on_card(task, env, f"Session `{topic}`: fresh ({why}); the next card on this topic continues it.")
    run_real(argv)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as e:                     # never stop a card from running because of this script
        print(f"[topic-session] error, running the card fresh: {e}", flush=True)
        os.execv(real_hermes(), [real_hermes(), *sys.argv[1:]])
