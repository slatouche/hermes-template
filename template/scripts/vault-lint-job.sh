#!/bin/bash
# Nightly vault health check, run by the Hermes `vault-lint` job (no-agent, zero tokens).
# Silent when the vault is clean. When lint finds problems, prints them and exits 1,
# so the run shows as failed in Desktop > Scheduled jobs. Advisories alone stay silent.
set -uo pipefail
OUT=$(/usr/bin/python3 "$HOME/.hermes/scripts/vault-lint.py" "$HOME/vault" 2>&1) || true
PROBLEMS=$(printf '%s\n' "$OUT" | sed -n '/^--- problems ---$/,/^--- advisories ---$/p' | sed '1d;$d')
if [ -z "$PROBLEMS" ] && ! printf '%s\n' "$OUT" | grep -q '^pages:'; then
  printf 'vault-lint did not run properly:\n%s\n' "$OUT"; exit 1
fi
if [ -n "$PROBLEMS" ] && [ "$PROBLEMS" != "none" ]; then
  printf 'Vault lint found problems:\n%s\n' "$PROBLEMS"; exit 1
fi
