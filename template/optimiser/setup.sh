#!/bin/bash
# The Optimiser's own setup, run by hire.sh after the profile exists (and by hire.sh optimiser --refresh): its nightly
# review job. The job's script (optimiser-gate.py) decides whether there's anything to look at, so a quiet night costs
# no tokens; when there is, the Optimiser works through the pack with its `optimise` skill and proposes, never applies.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
P="$HOME/.hermes/profiles/optimiser"
JOBS="$(hermes -p optimiser cron list 2>/dev/null || true)"
grep -q 'optimiser-review' <<<"$JOBS" || hermes -p optimiser cron create "40 2 * * *" \
  "optimiser-review. The script output above is the evidence pack since your last run. Load the optimise skill and follow it: find causes, test fixes on copies, write at most 5 proposals in system/changes/, give the Manager one card to screen them, update system/optimiser/, then stop. Change nothing live." \
  --name optimiser-review --script optimiser-gate.py --interpreter /usr/bin/python3 --workdir "$HOME/workspace" --deliver local >/dev/null
mkdir -p "$HOME/vault/system/optimiser"
echo "optimiser-review: nightly 02:40, silent unless its script finds something"
