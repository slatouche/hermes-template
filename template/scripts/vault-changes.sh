#!/bin/bash
# What changed in the vault since you last looked: a short, pull-request-style digest of what the bots wrote.
# Run it as the quick command /vault-changes in a Manager chat (no model call), or in a terminal.
#
#   vault-changes.sh            changes since the last time you ran it (then marks them seen)
#   vault-changes.sh 7          the last 7 days (doesn't move the "seen" mark)
#   vault-changes.sh --peek     since last time, without marking them seen
# Then open a page in Obsidian or ask the Manager about it; anything wrong is rolled back from git.
set -uo pipefail
cd "$HOME" || exit 1
SEEN="$HOME/.hermes/profiles/manager/scripts/.vault-seen"
ARG="${1:-}"
if [[ "$ARG" =~ ^[0-9]+$ ]]; then
  RANGE=(--since="$ARG days ago"); LABEL="the last $ARG days"; MARK=0
else
  LAST="$(cat "$SEEN" 2>/dev/null || true)"
  if [ -n "$LAST" ] && git cat-file -e "$LAST" 2>/dev/null; then RANGE=("$LAST..HEAD"); LABEL="since you last looked"
  else RANGE=(--since="7 days ago"); LABEL="the last 7 days (first look)"; fi
  MARK=1; [ "$ARG" = "--peek" ] && MARK=0
fi
N="$(git log --oneline "${RANGE[@]}" -- vault/ | wc -l)"
echo "Vault changes $LABEL: $N commit(s)"
git log "${RANGE[@]}" --date=format:'%m-%d %H:%M' --format='%h|%ad|%s' --name-status -- vault/ \
  | awk -F'|' '
      NF>=3 { printf "\n%s  %s\n", $2, $3; next }
      /^[AMDR]/ { split($0, a, "\t"); f=a[length(a)]; if (f ~ /vault\/(index|log)\.md$/) next;
                  k=substr($0,1,1); w=(k=="A"?"new":(k=="D"?"deleted":(k=="R"?"moved":"edited")));
                  sub(/^vault\//, "", f); printf "   %-8s %s\n", w, f }' | head -80
[ "$MARK" = 1 ] && git rev-parse HEAD > "$SEEN"
echo
echo "Roll back a page: git -C ~ checkout <commit>~1 -- vault/<page>   (or ask the Manager)"
