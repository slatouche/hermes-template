#!/usr/bin/python3
"""Card workers that resume a topic session instead of starting from nothing.

Hermes runs every kanban card as a fresh `hermes ... chat -q "work kanban task <id>"`, so each card re-learns the
project. The gateway launches workers through $HERMES_BIN when it's set; this script is that launcher. It adds
`chat --resume <id>` so a bot carries on where it left off:
  - a card with a line `Session: <topic>` (for example `Session: design:atlas-air`) resumes the bot's last session
    for that topic, so the same bot on the same area keeps what it learned across cards;
  - any other card resumes the bot's own last session on that same card (topic `card:<id>`) when the bot picks it
    up again: sent back for changes, unblocked, or cut off by the turn cap. A card's first run is fresh.
Everything else (other commands, `Session: none`, anything unexpected) runs the real `hermes` untouched.

Choosing the right session, per bot (each bot has its own topics file and session database):
  - topic -> the session recorded for it in <bot home>/topic-sessions.json; a topic first used by a card is recorded
    as "pending" and resolved on its next use from the session that card's worker started;
  - follow Hermes's own compression chain to the live continuation (a long session is condensed into a child);
  - resume only if that session exists in this bot's database, isn't a branch/delegate/tool child, was active in
    the last MAX_IDLE_DAYS, has had fewer than MAX_RUNS cards, and no live worker holds the topic (a lock file
    naming the worker's process and its start time, so a dead or finished worker never leaves it stuck);
  - a card whose last run by this bot failed (crashed, errored, timed out on the clock) starts fresh, since the
    resumed session may be what went wrong; one that ran out of turns resumes (it stopped cleanly, mid-job), and so
    does a card sent back for changes, unblocked or reviewed;
  - `Session: new <topic>` starts the topic over; `Session: none` runs fresh and records nothing.
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
WAIT_FOR_PREVIOUS = 90     # seconds to let the card's previous worker finish writing before resuming its session
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{0,79}$")
CARD_TEXT_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   # control characters never go in a command
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


def card(task, env):
    """The card's text and its runs: straight from the board's database the dispatcher names (milliseconds), else
    through `hermes kanban show` (about a second)."""
    db = env.get("HERMES_KANBAN_DB")
    if db and os.path.isfile(db):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT body FROM tasks WHERE id = ?", (task,)).fetchone()
            if row is not None:
                runs = [dict(r) for r in con.execute(
                    "SELECT profile, outcome, error, ended_at FROM task_runs WHERE task_id = ? ORDER BY id", (task,))]
                return row["body"] or "", runs
        except sqlite3.Error:
            pass
    r = subprocess.run([real_hermes(), "kanban", "show", task, "--json"], capture_output=True, text=True, env=env, timeout=60)
    d = json.loads(r.stdout or "{}")
    t = d.get("task") or d
    return t.get("body") or "", d.get("runs") if isinstance(d.get("runs"), list) else None


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
    """Hermes's own resolver (its runtime, its rules); a careful SQL fallback if that can't load. A session that was
    never condensed is its own tip, so the common case costs one query, not a Python start-up."""
    try:
        con = sqlite3.connect(f"file:{home / 'state.db'}?mode=ro", uri=True)
        row = con.execute("SELECT end_reason FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None or row[0] != "compression":
            return sid
    except sqlite3.Error:
        pass
    launcher = pathlib.Path(real_hermes()).resolve()
    try:
        text = launcher.read_text(errors="replace")
        shim = re.search(r'^exec "?(/\S+/bin/hermes)"? "\$@"', text, re.M)   # ~/.local/bin/hermes is a one-line shim
        if shim and "python" not in text:
            text = pathlib.Path(shim.group(1)).read_text(errors="replace")
        py = re.search(r"exec (\S+/python3?\S*) -I", text)
        agent = re.search(r"""sys\.path\.insert\(0, ['"]+([^'"]+hermes-agent)""", text)
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
        "m.session_id = s.id AND m.role = 'user' AND (m.content = ? OR m.content LIKE ? ESCAPE '\\')) "
        "ORDER BY s.started_at DESC LIMIT 1",                      # a design round's message carries the card after it
        (f"work kanban task {task}", f"work kanban task {task}\n%".replace("_", "\\_"))).fetchone()
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
OUT_OF_TURNS = re.compile(r"iteration budget exhausted|max(imum)? (turns|iterations)", re.I)


def last_run_failed(task, env, profile, runs):
    """This bot's most recent finished run on the card failed. Running out of turns isn't a failure: the session
    stopped cleanly in the middle of the job, so resuming it is exactly right."""
    try:
        if runs is None:
            r = subprocess.run([real_hermes(), "kanban", "runs", task, "--json"], capture_output=True, text=True, env=env, timeout=60)
            d = json.loads(r.stdout or "[]")
            runs = d if isinstance(d, list) else d.get("runs", [])
        mine = [x for x in runs if x.get("profile") == profile and x.get("ended_at")]
        if not mine:
            return False
        outcome, error = str(mine[-1].get("outcome") or ""), str(mine[-1].get("error") or "")
        return outcome in FAILED and not OUT_OF_TURNS.search(error)
    except Exception:
        return False


def prune(data, now):
    """Per-card entries are only useful while the card is live: drop ones idle past MAX_IDLE_DAYS."""
    for k, e in list(data.items()):
        if k.startswith("card:"):
            try:
                age = now - time.mktime(time.strptime(e.get("updated", ""), "%Y-%m-%d %H:%M"))
            except (ValueError, TypeError, AttributeError):
                age = float("inf")
            if age > MAX_IDLE_DAYS * 86400:
                del data[k]


def proc_start(pid):
    """The process's start time (to tell a reused pid apart), or None if it's gone or a zombie waiting to be reaped."""
    try:
        fields = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] in ("Z", "X") else fields[19]
    except (OSError, IndexError):
        return None


def take_topic(lockdir, topic, task):
    """Claim the topic for this process (whose pid the real worker keeps, via exec). A claim by a process that's
    gone, whose pid now belongs to something else, or by an earlier run of this same card (the board runs one worker
    per card, so that run has ended even if its process is still exiting) is stale and taken over.
    Returns False if a live worker on another card has it."""
    path = lockdir / (topic.replace(":", "__") + ".lock")
    fd = os.open(lockdir / ".guard", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            held = json.loads(path.read_text())
        except (OSError, ValueError):
            held = {}
        pid = held.get("pid")
        alive = bool(pid and pid != os.getpid() and proc_start(pid) and proc_start(pid) == held.get("start"))
        if alive and held.get("task") != task:
            return False, None
        path.write_text(json.dumps({"pid": os.getpid(), "start": proc_start(os.getpid()), "task": task, "since": time.time()}))
        return True, (held if alive else None)       # an earlier run of this card that is still exiting
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def session_open_elsewhere(home, sid):
    """Hermes refuses to resume a session another live process has open (its runtime/active_sessions.json)."""
    for reg in {home / "runtime" / "active_sessions.json", home.parent.parent / "runtime" / "active_sessions.json"}:
        try:
            entries = json.loads(reg.read_text()).get("entries") or []
        except (OSError, ValueError, AttributeError):
            continue
        for e in entries:
            pid = e.get("pid") if isinstance(e, dict) else None
            if str(e.get("session_id") or "") == sid and isinstance(pid, int) and pid != os.getpid() and proc_start(pid):
                return True
    return False


def wait_until_free(home, sid, previous):
    """Wait for the card's previous worker (which may still be writing its last reply after moving the card on) to
    exit and let go of the session. True if it's free."""
    deadline = time.time() + WAIT_FOR_PREVIOUS
    while time.time() < deadline:
        busy = previous and proc_start(previous["pid"]) == previous.get("start")
        if not busy and not session_open_elsewhere(home, sid):
            return True
        time.sleep(1)
    return False


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
        body, runs = card(task, env)
    except Exception:
        body, runs = "", None
    lines = SESSION_LINE.findall(body)
    want = lines[-1].strip().strip("`").lower() if lines else ""
    fresh_start = want.startswith("new ")
    topic = want[4:].strip() if fresh_start else want
    if topic in ("none", "-", "fresh"):
        log(home, f"{task}: the card asks for a fresh session")
        run_real(argv)
    if topic and not TOPIC_RE.match(topic):
        log(home, f"{task}: {want!r} isn't a usable topic (a-z, 0-9, : . _ -), using the card's own session")
    if not TOPIC_RE.match(topic):
        topic, fresh_start = f"card:{task}", False
    per_card = topic == f"card:{task}"

    path = home / "topic-sessions.json"
    lockdir = home / "topic-locks"
    lockdir.mkdir(exist_ok=True)
    claimed, previous = take_topic(lockdir, topic, task)
    if not claimed:
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
    elif entry.get("last_task") == task and last_run_failed(task, env, profile, runs):
        why = "this card's last run failed, so it starts fresh"
    else:
        sid = entry.get("session") or (session_of_task(home, entry["pending_task"]) if entry.get("pending_task") else None)
        if not sid:
            why = "this card's first run" if per_card else "first card on this topic"
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
            elif not wait_until_free(home, sid, previous):
                why, sid = f"session {sid} is still open in another worker after {WAIT_FOR_PREVIOUS}s", None
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    prune(data, now)
    if topic.startswith("design:") and body:     # a design round starts working at once: the card is in the message
        qi = argv.index("-q") + 1
        argv = argv[:qi] + [f"{argv[qi]}\n\nThe card, so you can start at once (no need to call kanban_show):\n\n"
                            + CARD_TEXT_CTRL.sub("", body)[:30000]] + argv[qi + 1:]
    if sid:
        data[topic] = {"session": sid, "runs": entry.get("runs", 0) + 1, "last_task": task, "updated": stamp}
        save(path, data)
        if per_card:
            log(home, f"{task}: resuming this card's session {sid} (run {data[topic]['runs']})")
            note_on_card(task, env, f"Resumed this card's session `{sid}`.")
        else:
            log(home, f"{task}: topic {topic}: resuming session {sid} (card {data[topic]['runs']} on this topic)")
            note_on_card(task, env, f"Session `{topic}`: resumed `{sid}` (card {data[topic]['runs']} on this topic).")
        i = argv.index("chat") + 1
        run_real(argv[:i] + ["--resume", sid] + argv[i:])
    data[topic] = {"pending_task": task, "runs": 1, "last_task": task, "updated": stamp}
    save(path, data)
    log(home, f"{task}: topic {topic}: fresh session ({why})")
    if not per_card or why != "this card's first run":      # a card's first run is the normal case: no comment
        note_on_card(task, env, f"Session `{topic}`: fresh ({why})" + ("" if per_card else "; the next card on this topic continues it") + ".")
    run_real(argv)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as e:                     # never stop a card from running because of this script
        print(f"[topic-session] error, running the card fresh: {e}", flush=True)
        os.execv(real_hermes(), [real_hermes(), *sys.argv[1:]])
