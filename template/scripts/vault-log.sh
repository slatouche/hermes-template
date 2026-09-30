#!/bin/bash
# Append one line to vault/log.md, safely, even when several bots log at once.
# Usage: vault-log.sh <bot> <ingest|decision|gate|handoff|lint|note> "<one line>" [link-target]
# Example: vault-log.sh architect decision "ADR-0007 accepted: auth via reverse proxy" architecture/decisions/0007-auth
set -euo pipefail
[ $# -ge 3 ] || { echo "usage: vault-log.sh <bot> <kind> \"<text>\" [link]" >&2; exit 2; }
BOT="$1"; KIND="$2"; TEXT="$3"; LINK="${4:-}"
LINK="${LINK#\[\[}"; LINK="${LINK%\]\]}"; LINK="${LINK#\[\[}"; LINK="${LINK%\]\]}"   # accept "page" or "[[page]]"
case "$KIND" in ingest|decision|gate|handoff|lint|note) ;; *) echo "vault-log: bad kind '$KIND'" >&2; exit 2 ;; esac
TEXT="${TEXT//$'\n'/ }"      # always one line
TEXT="${TEXT//|//}"          # '|' is the field separator
TEXT="${TEXT//\[\[/[}"; TEXT="${TEXT//\]\]/]}"   # neutralise [[..]] in text: only the link field is a link
LINE="$(date '+%Y-%m-%d %H:%M') | $BOT | $KIND | $TEXT | ${LINK:+[[$LINK]]}"
LOG="$HOME/vault/log.md"
exec 9>>"$HOME/vault/.log.lock"
flock -w 30 9 || { echo "vault-log: timed out waiting for lock" >&2; exit 1; }
printf '%s\n' "$LINE" >> "$LOG"
echo "$LINE"
