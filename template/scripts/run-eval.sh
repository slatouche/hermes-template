#!/bin/bash
# Run a bot's fixed eval: each prompt in vault/system/evals/<bot>.md, asked fresh, answers saved side by side
# with what was expected. Run it before and after changing that bot's SOUL or skills, and compare.
#
#   run-eval.sh <bot>                          -> vault/system/evals/results/<bot>-<date>-<time>.md
#   run-eval.sh <bot> --trial <staging folder> -> ...<bot>-trial-<date>-<time>.md: the same prompts, asked of a
#        temporary copy of the bot carrying a staged tidy's version of what it loads (its SOUL, from the staged
#        role page or SOUL; its memory; the team rules), so a change is judged before it's applied. The copy is
#        deleted afterwards; the real bot is never touched.
#
# Prompts are lines starting "Q: ", each followed by an "Expect: " line. Each runs as a one-shot, read-only
# chat: only harmless toolsets (skills, session search, to-do), so the bot can't change files, the board or
# memory, and a short preface tells it to say what it would do rather than do it. It checks rules and
# judgement, not the project's state. Costs one model call per prompt.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
BOT="${1:-}"; [ -n "$BOT" ] || { echo "usage: run-eval.sh <bot> [--trial <staging folder>]" >&2; exit 2; }
TRIAL=""; [ "${2:-}" = "--trial" ] && TRIAL="${3:?--trial needs the staging folder}"
E="$HOME/vault/system/evals/$BOT.md"; [ -f "$E" ] || { echo "run-eval: no $E" >&2; exit 2; }
OUT_DIR="$HOME/vault/system/evals/results"; mkdir -p "$OUT_DIR"
STAMP="$(date +%F-%H%M)"; RUN_AS="$BOT"; WORKDIR="$HOME/workspace"; TAG="$BOT"

if [ -n "$TRIAL" ]; then
  case "$TRIAL" in /*) ;; *) TRIAL="$HOME/$TRIAL" ;; esac
  [ -d "$TRIAL/new" ] || { echo "run-eval: no $TRIAL/new" >&2; exit 2; }
  RUN_AS="${BOT}trial"; TAG="$BOT-trial"
  WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/eval-trial-XXXXXX")"
  cleanup() { hermes profile delete -y "$RUN_AS" >/dev/null 2>&1 || true; rm -rf "$WORKDIR"; }
  trap cleanup EXIT
  hermes profile delete -y "$RUN_AS" >/dev/null 2>&1 || true
  hermes profile create "$RUN_AS" --clone-from "$BOT" >/dev/null
  TP="$HOME/.hermes/profiles/$RUN_AS"; N="$TRIAL/new"
  # its SOUL: the staged source's body (role page or working file), or a staged SOUL (the Manager's own)
  for src in "vault/system/roles/$BOT.working.md" "vault/system/roles/$BOT.md"; do
    if [ -f "$HOME/$src" ]; then
      [ -f "$N/$src" ] && awk 'NR==1 && /^---$/ {f=1; next} f && /^---$/ {f=0; b=1; next} b' "$N/$src" | sed '/./,$!d' > "$TP/SOUL.md"
      break
    fi
  done
  [ ! -f "$N/.hermes/profiles/$BOT/SOUL.md" ] || cp "$N/.hermes/profiles/$BOT/SOUL.md" "$TP/SOUL.md"
  for m in MEMORY.md USER.md; do
    [ ! -f "$N/.hermes/profiles/$BOT/memories/$m" ] || cp "$N/.hermes/profiles/$BOT/memories/$m" "$TP/memories/$m"
  done
  if [ -f "$N/workspace/AGENTS.md" ]; then cp "$N/workspace/AGENTS.md" "$WORKDIR/AGENTS.md"
  else cp "$HOME/workspace/AGENTS.md" "$WORKDIR/AGENTS.md"; fi
fi

OUT="$OUT_DIR/$TAG-$STAMP.md"
{ printf -- '---\ntitle: "Eval %s %s"\ntype: system\nstatus: archived\nowner: manager\nupdated: %s\nsummary: "Eval answers for %s on %s, next to what was expected."\ntags: [eval]\n---\n# Eval: %s, %s\n\n' \
    "$TAG" "$STAMP" "$(date +%F)" "$TAG" "$STAMP" "$TAG" "$STAMP"; } > "$OUT"
[ -z "$TRIAL" ] || printf 'Trial of the staged change in `%s`.\n\n' "${TRIAL#$HOME/}" >> "$OUT"
n=0; Q=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "Q: "*) Q="${line#Q: }" ;;
    "Expect: "*)
      [ -n "$Q" ] || continue
      n=$((n+1)); TMP="$(mktemp)"
      printf '%s

%s' "[Read-only evaluation of how you work: reply to the owner as you would in a real chat, saying what you would do. You can't change anything here, so don't claim you did.]" "$Q" > "$TMP"
      A="$(cd "$WORKDIR" && timeout 600 hermes -p "$RUN_AS" chat -Q -t skills,session_search,todo --query-file "$TMP" 2>/dev/null | grep -v '^session_id:' || echo '(no answer: timed out or failed)')"
      rm -f "$TMP"
      printf '## %d. %s\n**Expected:** %s\n\n**Answer:**\n\n%s\n\n' "$n" "$Q" "${line#Expect: }" "$A" >> "$OUT"
      Q="" ;;
  esac
done < "$E"
echo "run-eval: $n prompt(s) -> ${OUT#$HOME/}"
