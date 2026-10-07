#!/bin/bash
# Safety-net commit for the project memory repo. Run every 15 min by a Hermes script-only job (zero tokens).
# 0) logs finished cards (card-log.py), 1) regenerates vault/index.md, 2) commits whatever nobody checkpointed,
# 3) builds the commit message from the log.md lines added since the last commit.
# Silent on success (Hermes treats empty output as a quiet run); non-zero exit = error delivery.
set -euo pipefail
cd "$HOME"
exec 9>"$HOME/.git/vault-commit.lock"
flock -w 120 9 || { echo "vault-sweep: timed out waiting for lock" >&2; exit 1; }
/usr/bin/python3 "$HOME/.hermes/scripts/card-log.py" || echo "vault-sweep: card-log failed" >&2   # a log line per finished card
/usr/bin/python3 "$HOME/.hermes/scripts/vault-index.py" "$HOME/vault"
git add -A
git diff --cached --quiet && exit 0
COUNT=$(git diff --cached --name-only | wc -l)
BODY=$(git diff --cached -U0 -- vault/log.md \
  | grep -E '^\+[0-9]{4}-' | cut -c2- \
  | awk -F' \\| ' '{printf "%s: %s: %s\n", $2, $3, substr($4,1,100)}' | head -12 || true)
git commit -q -m "sweep: $COUNT file(s)" -m "${BODY:-No log entries since the last commit.}"
