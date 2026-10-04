#!/bin/bash
# Hire a bot: turn a role file in vault/system/roles/<role>.md into a working Hermes profile.
# Run by the Manager (as the project's agent user) only after the owner has approved the hire.
#
#   hire.sh <role> [--channel <discord-channel-id>] [--skill <folder>]...
#
# Creates the profile (cloned from the Manager: model, key, toolsets, working folder), then gives it a
# clean start: an empty MEMORY.md, USER.md from vault/system/owner-profile.md, and none of the
# Manager's own bot-written skills. Installs the SOUL, sets the display name and the role's settings
# (from the role file's header, else hire-defaults.conf), creates its Hermes Project on ~/workspace,
# adds it to the team table in the instructions file Hermes loads (workspace/AGENTS.md), optionally installs skill folders and routes a
# Discord channel to it, then logs and checkpoints.
# Re-running for an existing bot with --channel and/or --skill only adds those.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
die() { echo "hire.sh: $*" >&2; exit 1; }

ROLE="${1:-}"
if [ $# -gt 0 ]; then shift; fi
CHANNEL=""
SKILLS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL="${2:-}"; shift 2 ;;
    --skill)   SKILLS+=("${2:-}"); shift 2 ;;
    *) die "unknown option '$1'" ;;
  esac
done
[[ "$ROLE" =~ ^[a-z][a-z0-9]{1,20}$ ]] || die "usage: hire.sh <role> [--channel <discord-channel-id>] [--skill <folder>]...  (role: lowercase letters and digits)"
[ -z "$CHANNEL" ] || [[ "$CHANNEL" =~ ^[0-9]+$ ]] || die "the Discord channel ID is a number"
case "$ROLE" in default|manager) die "'$ROLE' is not a hireable role" ;; esac
for s in "${SKILLS[@]}"; do
  [ -f "$s/SKILL.md" ] || die "--skill $s: no SKILL.md in that folder"
  case "$(cd "$s" && pwd)" in "$HOME"/*) ;; *) die "--skill $s: the folder must be inside this project" ;; esac
done

PROJECT="$(basename "$HOME")"
RF="$HOME/vault/system/roles/$ROLE.md"
[ -f "$RF" ] || die "no role file $RF. Draft it from system/roles/_guide.md first."
P="$HOME/.hermes/profiles/$ROLE"
# The team table lives in the one instructions file Hermes loads: .hermes.md / HERMES.md win over AGENTS.md.
AG="$HOME/workspace/AGENTS.md"
for f in .hermes.md HERMES.md; do [ -s "$HOME/workspace/$f" ] && { AG="$HOME/workspace/$f"; break; }; done
grep -q '<!-- team:end -->' "$AG" 2>/dev/null   || die "no team table in workspace/$(basename "$AG"), the file every bot loads. On an imported project, finish the takeover first (it merges vault/system/team-rules.md into workspace/AGENTS.md)."
AGN="$(basename "$AG")"
OWNER_PROFILE="$HOME/vault/system/owner-profile.md"
LOG="$HOME/.hermes/scripts/vault-log.sh"
COMMIT="$HOME/.hermes/scripts/vault-commit.sh"
DEFAULTS="$HOME/.hermes/scripts/hire-defaults.conf"
COMPRESSION_ROLE_TOKENS=150000; ROLE_MAX_TURNS=90; ROLE_BUDGET_WARNING=0.8; EFFORT=medium
# shellcheck disable=SC1090
[ -f "$DEFAULTS" ] && source "$DEFAULTS"

fm() {   # fm <key>: a one-line frontmatter value, surrounding quotes removed
  awk -v k="$1" 'NR==1 && /^---$/ {f=1; next} f && /^---$/ {exit}
    f && index($0, k": ") == 1 { v = substr($0, length(k) + 3); gsub(/^"|"$/, "", v); print v; exit }' "$RF"
}
fmv() { fm "$1" | sed -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//'; }   # setting values may carry a trailing # comment
DNAME="$(fm display)"; DESC="$(fm description)"; OWNS="$(fm owns)"; ASK="$(fm ask_when)"; FMROLE="$(fm role)"
[ "$FMROLE" = "$ROLE" ] || die "$RF says role: '$FMROLE', expected '$ROLE'"
for v in DNAME DESC OWNS ASK; do [ -n "${!v}" ] || die "$RF is missing a frontmatter field (display, description, owns, ask_when)"; done
# Optional per-role settings in the role file's header; the defaults come from hire-defaults.conf.
R_CTX="$(fmv compression_tokens)"; R_CTX="${R_CTX:-$COMPRESSION_ROLE_TOKENS}"
R_TURNS="$(fmv max_turns)";        R_TURNS="${R_TURNS:-$ROLE_MAX_TURNS}"
R_EFFORT="$(fmv effort)";          R_EFFORT="${R_EFFORT:-$EFFORT}"
R_VERIFY="$(fmv verify_on_stop)";  R_VERIFY="${R_VERIFY:-false}"
[[ "$R_EFFORT" =~ ^(none|minimal|low|medium|high|xhigh|max|ultra)$ ]] || die "$RF: effort '$R_EFFORT' is not a Hermes effort level"
[[ "$R_CTX" =~ ^[0-9]+$ ]] && [[ "$R_TURNS" =~ ^[0-9]+$ ]] || die "$RF: compression_tokens and max_turns must be whole numbers"
[[ "$R_VERIFY" =~ ^(true|false)$ ]] || die "$RF: verify_on_stop must be true or false"

CHANGED=()
NEW_HIRE=0
if [ -d "$P" ]; then
  [ -n "$CHANNEL" ] || [ ${#SKILLS[@]} -gt 0 ] || die "$ROLE is already hired. To add a Discord channel or skills: hire.sh $ROLE --channel <id> | --skill <folder>"
  echo "$ROLE exists; adding only the requested channel/skills"
else
  echo "==> Creating profile $ROLE"
  NEW_HIRE=1
  hermes profile create "$ROLE" --clone-from manager --description "$DESC"

  echo "==> Clean start (no copy of the Manager's memory or its own skills)"
  # --clone-from copies the Manager's MEMORY.md, USER.md and its whole skills tree (Hermes v0.21.5).
  mkdir -p "$P/memories"
  : > "$P/memories/MEMORY.md"
  /usr/bin/python3 - "$OWNER_PROFILE" "$P/memories/USER.md" <<'EOF'
import sys, re, pathlib
src, dst = map(pathlib.Path, sys.argv[1:])
seed = ""
if src.exists():
    m = re.search(r"<!-- user-seed:start -->(.*?)<!-- user-seed:end -->", src.read_text(encoding="utf-8"), re.S)
    seed = m.group(1).strip() if m else ""
if not seed:
    print("hire.sh: warning: no USER.md seed in vault/system/owner-profile.md; USER.md left empty", file=sys.stderr)
if len(seed) > 1375:   # Hermes' user_char_limit
    seed = seed[:1375].rsplit("\n", 1)[0]
    print("hire.sh: warning: USER.md seed trimmed to Hermes' 1,375-character limit", file=sys.stderr)
dst.write_text(seed + ("\n" if seed else ""), encoding="utf-8")
EOF
  /usr/bin/python3 - "$P/skills" <<'EOF'
import sys, shutil, pathlib
root = pathlib.Path(sys.argv[1])
if root.is_dir():
    manifest = root / ".bundled_manifest"
    bundled = {l.split(":", 1)[0].strip() for l in manifest.read_text(encoding="utf-8").splitlines() if l.strip()} if manifest.exists() else set()
    removed = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        d = skill_md.parent
        if any(part.startswith(".") for part in d.relative_to(root).parts):
            continue                                   # hub/archive/backup internals stay as Hermes left them
        if d.name not in bundled and d.exists():
            shutil.rmtree(d); removed.append(d.name)
    for leftover in (".usage.json", ".usage.json.lock", ".curator_ledger.jsonl", ".curator_state"):
        (root / leftover).unlink(missing_ok=True)
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(d.iterdir()) and not any(part.startswith(".") for part in d.relative_to(root).parts):
            d.rmdir()
    print(f"removed {len(removed)} skill(s) copied from the Manager" + (f": {', '.join(removed)}" if removed else ""))
EOF

  # The SOUL is the role file's body (everything after the frontmatter).
  awk 'NR==1 && /^---$/ {f=1; next} f && /^---$/ {f=0; b=1; next} b' "$RF" | sed '/./,$!d' > "$P/SOUL.md"
  if grep -q '^display_name:' "$P/profile.yaml" 2>/dev/null; then
    sed -i "s|^display_name:.*|display_name: $DNAME ($PROJECT)|" "$P/profile.yaml"
  else
    echo "display_name: $DNAME ($PROJECT)" >> "$P/profile.yaml"
  fi

  echo "==> Settings: context $R_CTX tokens, $R_TURNS turns, effort $R_EFFORT, verify-on-stop $R_VERIFY"
  hermes -p "$ROLE" config set terminal.cwd "$HOME/workspace" >/dev/null
  hermes -p "$ROLE" config set compression.threshold_tokens "$R_CTX" >/dev/null
  hermes -p "$ROLE" config set agent.max_turns "$R_TURNS" >/dev/null
  hermes -p "$ROLE" config set agent.budget_warning_ratio "$ROLE_BUDGET_WARNING" >/dev/null
  hermes -p "$ROLE" config set --force agent.reasoning_effort "$R_EFFORT" >/dev/null
  hermes -p "$ROLE" config set agent.verify_on_stop "$R_VERIFY" >/dev/null
  hermes -p "$ROLE" tools enable kanban >/dev/null
  hermes -p "$ROLE" tools enable --platform discord kanban >/dev/null
  hermes -p "$ROLE" project create "$PROJECT" "$HOME/workspace" --use >/dev/null

  echo "==> Adding $DNAME to the team table"
  /usr/bin/python3 - "$AG" "$DNAME" "$OWNS" "$ASK" <<'EOF'
import sys
path, display, owns, ask = sys.argv[1:]
s = open(path, encoding="utf-8").read()
end = "<!-- team:end -->"
if end not in s:
    sys.exit(f"hire.sh: the team table markers are missing from {path}")
if f"| {display} |" not in s:
    clean = lambda t: t.replace("|", "/")
    s = s.replace(end, f"| {display} | {clean(owns)} | {clean(ask)} |\n{end}", 1)
    open(path, "w", encoding="utf-8").write(s)
EOF
  if ! git -C "$HOME/workspace" diff --quiet -- "$AGN"; then
    git -C "$HOME/workspace" commit -q -m "$AGN: $DNAME joins the team (hire.sh)" -- "$AGN"
  fi
  CHANGED+=(".hermes/profiles/$ROLE/SOUL.md" ".hermes/profiles/$ROLE/config.yaml" ".hermes/profiles/$ROLE/profile.yaml"
            ".hermes/profiles/$ROLE/memories/MEMORY.md" ".hermes/profiles/$ROLE/memories/USER.md")
fi

for s in "${SKILLS[@]}"; do
  NAME_="$(basename "$(cd "$s" && pwd)")"
  [ ! -e "$P/skills/$NAME_" ] || die "$ROLE already has a skill named $NAME_"
  echo "==> Installing skill $NAME_"
  mkdir -p "$P/skills"
  cp -r "$s" "$P/skills/$NAME_"
  CHANGED+=(".hermes/profiles/$ROLE/skills/$NAME_")
done

if [ -n "$CHANNEL" ]; then
  echo "==> Routing Discord channel $CHANNEL to $ROLE"
  CUR="$(hermes -p default config get --json gateway.profile_routes 2>/dev/null || true)"
  NEW="$(/usr/bin/python3 - "$CUR" "$ROLE" "$CHANNEL" <<'EOF'
import json, sys
raw, role, ch = sys.argv[1:]
try:
    cur = json.loads(raw) if raw.strip() else []
except ValueError:
    sys.exit("hire.sh: could not read gateway.profile_routes as JSON")
cur = [r for r in (cur or []) if not (r.get("platform") == "discord" and str(r.get("chat_id")) == ch)]
cur.append({"name": f"{role}-channel", "platform": "discord", "bot_profile": "manager",
            "chat_id": ch, "profile": role})
print(json.dumps(cur))
EOF
)"
  hermes -p default config set gateway.profile_routes "$NEW" >/dev/null
  hermes -p default config get --json gateway.profile_routes | grep -q "\"$CHANNEL\"" || die "the Discord route did not save"
  CHANGED+=(".hermes/config.yaml")
fi

if [ "$NEW_HIRE" = 1 ]; then MSG="Hired $DNAME ($ROLE) from system/roles/$ROLE.md"; else MSG="Updated $DNAME ($ROLE)"; fi
[ ${#SKILLS[@]} -eq 0 ] || MSG="$MSG; skills added: ${#SKILLS[@]}"
[ -z "$CHANNEL" ] || MSG="$MSG; Discord channel $CHANNEL routed to it"
"$LOG" manager decision "$MSG" "system/roles/$ROLE" >/dev/null
CHANGED+=("vault/log.md" "vault/system/roles/$ROLE.md")
"$COMMIT" manager "hire: $ROLE" "${CHANGED[@]}" >/dev/null || true

echo
echo "Done: $DNAME ($PROJECT) is on the team."
[ -z "$CHANNEL" ] || echo "The Discord route takes effect after the owner restarts the gateway (see system/overview.md)."
echo "Next: $DNAME proposes its domain to the owner; once agreed it writes team/$ROLE.md."
