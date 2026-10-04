#!/bin/bash
# Keep workspace/ tidy, with no model tokens. Run hourly by the Hermes `workspace-tidy` job (no-agent).
# Deletes kanban card branches (<project>/t_<id>-...) that are fully merged into main and no longer
# checked out, and prunes worktree records whose folders are gone. Never touches unmerged work.
# Silent when there's nothing to do; prints one line per removal otherwise.
set -uo pipefail
W="$HOME/workspace"
[ -d "$W/.git" ] || exit 0
git -C "$W" worktree prune
MAIN="$(git -C "$W" symbolic-ref --quiet --short HEAD 2>/dev/null || echo main)"
git -C "$W" show-ref -q --verify "refs/heads/main" && MAIN=main
# Card worktrees whose branch is merged into main and that hold no uncommitted changes are finished: remove them.
git -C "$W" worktree list --porcelain | awk '/^worktree /{p=$2} /^branch /{print p" "$2}' | while read -r wt ref; do
  br="${ref#refs/heads/}"
  [ "$wt" != "$W" ] && [[ "$br" =~ ^[^/]+/t_[0-9a-f]+ ]] || continue
  git -C "$W" merge-base --is-ancestor "$br" "$MAIN" 2>/dev/null || continue
  [ -z "$(git -C "$wt" status --porcelain 2>/dev/null)" ] || continue
  git -C "$W" worktree remove "$wt" && echo "workspace-tidy: removed finished worktree $wt"
done
in_use="$(git -C "$W" worktree list --porcelain | sed -n 's#^branch refs/heads/##p')"
git -C "$W" branch --merged "$MAIN" --format='%(refname:short)' | grep -E '^[^/]+/t_[0-9a-f]+' | while read -r br; do
  grep -qxF "$br" <<<"$in_use" && continue
  git -C "$W" branch -q -d "$br" && echo "workspace-tidy: deleted merged card branch $br"
done
exit 0
