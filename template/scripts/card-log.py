#!/usr/bin/python3
"""Log every finished card run in vault/log.md, so bots don't spend turns on it. Run by vault-sweep.sh (every 15 min).

The board already records each run's outcome and summary; this appends one `handoff` line per run that ended since the
last pass: `<card> <outcome>: <title>: <first line of the summary>`. A card whose bot already logged a line naming it
since the run started is skipped. The first pass only remembers where the board is (no backfill).
State: ~/.hermes/card-log.state (the last run id seen).
"""
import pathlib
import sqlite3
import subprocess
import time

HOME = pathlib.Path.home()
DB = HOME / ".hermes" / "kanban.db"
STATE = HOME / ".hermes" / "card-log.state"
LOG = HOME / "vault" / "log.md"
VAULT_LOG = HOME / ".hermes" / "scripts" / "vault-log.sh"
OUTCOMES = {"completed", "review_requested", "changes_requested", "blocked"}


def main() -> int:
    if not DB.exists():
        return 0
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    top = con.execute("SELECT COALESCE(MAX(id), 0) FROM task_runs WHERE ended_at IS NOT NULL").fetchone()[0]
    try:
        last = int(STATE.read_text().strip())
    except (OSError, ValueError):
        STATE.write_text(str(top))
        return 0
    rows = con.execute(
        "SELECT r.id, r.task_id, r.profile, r.outcome, r.started_at, r.summary, t.title FROM task_runs r "
        "JOIN tasks t ON t.id = r.task_id WHERE r.id > ? AND r.ended_at IS NOT NULL ORDER BY r.id", (last,)).fetchall()
    try:
        log_lines = LOG.read_text(errors="replace").splitlines()[-400:]
    except OSError:
        log_lines = []
    for rid, task, profile, outcome, started, summary, title in rows:
        if outcome not in OUTCOMES:
            continue
        since = time.strftime("%Y-%m-%d %H:%M", time.localtime(started or 0))
        if any(task in ln and ln[:16] >= since for ln in log_lines):
            continue                                   # the bot logged it itself
        first = next((ln.strip() for ln in (summary or "").splitlines() if ln.strip()), "no summary")
        text = f"{task} {outcome.replace('_', ' ')}: {title}: {first}"
        text = text if len(text) <= 300 else text[:297] + "..."
        subprocess.run([str(VAULT_LOG), profile or "bot", "handoff", text], capture_output=True, timeout=60)
    STATE.write_text(str(max([top, last])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
