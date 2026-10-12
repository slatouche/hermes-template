"""state-pack: the project's state, added to the Manager's chat messages, so a reply starts already knowing it.

Before each chat turn (pre_llm_call) it runs ~/.hermes/scripts/state-pack.py (about a second, no model) and adds the
pack to the owner's message, only when it differs from the last pack this session saw (the session's history keeps
the earlier one, so an unchanged board costs nothing). Card workers and cron runs get nothing: they read what their
card needs.
"""
import hashlib
import os
import pathlib
import subprocess
import sys

_seen = {}                     # session id -> hash of the last pack added there
SCRIPT = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home()) / ".hermes" / "scripts" / "state-pack.py"
CHATS = {"desktop", "tui", "cli", "discord", "telegram", "slack", "signal", "whatsapp", "api", "web", "dashboard"}


def pack(session_id=None, platform="", **kwargs):
    if os.environ.get("HERMES_KANBAN_TASK") or str(platform).lower() not in CHATS:
        return None
    try:
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = r.stdout.strip()
    if r.returncode != 0 or not text:
        return None
    body = text.split("\n", 1)[1] if "\n" in text else text          # the first line carries the time: not a change
    h = hashlib.sha1(body.encode()).hexdigest()
    if _seen.get(session_id) == h:
        return None
    _seen[session_id] = h
    return {"context": text}


def register(ctx):
    ctx.register_hook("pre_llm_call", pack)
