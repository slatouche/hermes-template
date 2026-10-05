#!/bin/bash
# Run a bot's fixed eval: each prompt in vault/system/evals/<bot>.md, asked fresh, answers saved side by side
# with what was expected. Run it before and after changing that bot's SOUL or skills, and compare.
#
#   run-eval.sh <bot>      -> vault/system/evals/results/<bot>-<date>-<time>.md
#
# Prompts are lines starting "Q: ", each followed by an "Expect: " line. Each runs as a one-shot, read-only
# chat: only harmless toolsets (skills, session search, to-do), so the bot can't change files, the board or
# memory, and a short preface tells it to say what it would do rather than do it. It checks rules and
# judgement, not the project's state. Costs one model call per prompt.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
BOT="${1:-}"; [ -n "$BOT" ] || { echo "usage: run-eval.sh <bot>" >&2; exit 2; }
E="$HOME/vault/system/evals/$BOT.md"; [ -f "$E" ] || { echo "run-eval: no $E" >&2; exit 2; }
OUT_DIR="$HOME/vault/system/evals/results"; mkdir -p "$OUT_DIR"
STAMP="$(date +%F-%H%M)"; OUT="$OUT_DIR/$BOT-$STAMP.md"
{ printf -- '---\ntitle: "Eval %s %s"\ntype: system\nstatus: archived\nowner: manager\nupdated: %s\nsummary: "Eval answers for %s on %s, next to what was expected."\ntags: [eval]\n---\n# Eval: %s, %s\n\n' \
    "$BOT" "$STAMP" "$(date +%F)" "$BOT" "$STAMP" "$BOT" "$STAMP"; } > "$OUT"
n=0; Q=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "Q: "*) Q="${line#Q: }" ;;
    "Expect: "*)
      [ -n "$Q" ] || continue
      n=$((n+1)); TMP="$(mktemp)"
      printf '%s

%s' "[Read-only evaluation of how you work: reply to the owner as you would in a real chat, saying what you would do. You can't change anything here, so don't claim you did.]" "$Q" > "$TMP"
      A="$(cd "$HOME/workspace" && timeout 600 hermes -p "$BOT" chat -Q -t skills,session_search,todo --query-file "$TMP" 2>/dev/null | grep -v '^session_id:' || echo '(no answer: timed out or failed)')"
      rm -f "$TMP"
      printf '## %d. %s\n**Expected:** %s\n\n**Answer:**\n\n%s\n\n' "$n" "$Q" "${line#Expect: }" "$A" >> "$OUT"
      Q="" ;;
  esac
done < "$E"
echo "run-eval: $n prompt(s) -> ${OUT#$HOME/}"
