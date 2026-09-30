#!/bin/bash
# Commit named files to the project memory repo (vault + bot brain) as a checkpoint.
# Safe with several bots: one commit at a time (lock), and ONLY the listed files are committed,
# so another bot's half-finished work is never swept up.
# Usage: vault-commit.sh <bot> "<message>" <path> [path...]   (paths relative to the project root)
# Example: vault-commit.sh architect "ADR-0004 accepted" vault/architecture/decisions/0004-source-adapters.md
set -euo pipefail
[ $# -ge 3 ] || { echo "usage: vault-commit.sh <bot> \"<message>\" <path>..." >&2; exit 2; }
BOT="$1"; MSG="$2"; shift 2
cd "$HOME"
for p in "$@"; do
  case "$p" in
    *.env|*/.env|*.db|*.db-*|*token*|*.key|workspace/*)
      echo "vault-commit: refusing '$p' (secret, database, or product repo)" >&2; exit 2 ;;
  esac
done
exec 9>"$HOME/.git/vault-commit.lock"
flock -w 120 9 || { echo "vault-commit: timed out waiting for lock" >&2; exit 1; }
git add -- "$@"
if git diff --cached --quiet -- "$@"; then
  echo "vault-commit: nothing to commit"; exit 0
fi
git commit -q -m "$BOT: $MSG" -- "$@"
git log --oneline -n 1
