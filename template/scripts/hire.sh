#!/bin/bash
# Hire a bot: turn a role file in vault/system/roles/<role>.md into a working Hermes profile.
# Run by the Manager (as the project's agent user) only after the owner has approved the hire.
#
#   hire.sh <role> [--channel <discord-channel-id>]
#
# Creates the profile (cloned from the Manager: model, key, toolsets, working folder), installs the
# SOUL, sets the display name, creates its Hermes Project on ~/workspace, adds it to the team table in
# workspace/AGENTS.md, optionally routes a Discord channel to it, then logs and checkpoints.
# Re-running for an existing bot with --channel only adds or updates the Discord route.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
die() { echo "hire.sh: $*" >&2; exit 1; }

ROLE="${1:-}"
if [ $# -gt 0 ]; then shift; fi
CHANNEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --channel) CHANNEL="${2:-}"; shift 2 ;;
    *) die "unknown option '$1'" ;;
  esac
done
[[ "$ROLE" =~ ^[a-z][a-z0-9]{1,20}$ ]] || die "usage: hire.sh <role> [--channel <discord-channel-id>]  (role: lowercase letters and digits)"
[ -z "$CHANNEL" ] || [[ "$CHANNEL" =~ ^[0-9]+$ ]] || die "the Discord channel ID is a number"
case "$ROLE" in default|manager) die "'$ROLE' is not a hireable role" ;; esac

PROJECT="$(basename "$HOME")"
RF="$HOME/vault/system/roles/$ROLE.md"
[ -f "$RF" ] || die "no role file $RF. Draft it from system/roles/_guide.md first."
P="$HOME/.hermes/profiles/$ROLE"
AG="$HOME/workspace/AGENTS.md"
LOG="$HOME/.hermes/scripts/vault-log.sh"
COMMIT="$HOME/.hermes/scripts/vault-commit.sh"

fm() {   # fm <key>: a one-line frontmatter value, surrounding quotes removed
  awk -v k="$1" 'NR==1 && /^---$/ {f=1; next} f && /^---$/ {exit}
    f && index($0, k": ") == 1 { v = substr($0, length(k) + 3); gsub(/^"|"$/, "", v); print v; exit }' "$RF"
}
DNAME="$(fm display)"; DESC="$(fm description)"; OWNS="$(fm owns)"; ASK="$(fm ask_when)"; FMROLE="$(fm role)"
[ "$FMROLE" = "$ROLE" ] || die "$RF says role: '$FMROLE', expected '$ROLE'"
for v in DNAME DESC OWNS ASK; do [ -n "${!v}" ] || die "$RF is missing a frontmatter field (display, description, owns, ask_when)"; done

CHANGED=()
if [ -d "$P" ]; then
  [ -n "$CHANNEL" ] || die "$ROLE is already hired. To give it a Discord channel: hire.sh $ROLE --channel <id>"
  echo "$ROLE exists; updating its Discord route only"
else
  echo "==> Creating profile $ROLE"
  hermes profile create "$ROLE" --clone-from manager --description "$DESC"
  # The SOUL is the role file's body (everything after the frontmatter).
  awk 'NR==1 && /^---$/ {f=1; next} f && /^---$/ {f=0; b=1; next} b' "$RF" | sed '/./,$!d' > "$P/SOUL.md"
  if grep -q '^display_name:' "$P/profile.yaml" 2>/dev/null; then
    sed -i "s|^display_name:.*|display_name: $DNAME ($PROJECT)|" "$P/profile.yaml"
  else
    echo "display_name: $DNAME ($PROJECT)" >> "$P/profile.yaml"
  fi
  hermes -p "$ROLE" config set terminal.cwd "$HOME/workspace" >/dev/null
  hermes -p "$ROLE" project create "$PROJECT" "$HOME/workspace" --use >/dev/null

  echo "==> Adding $DNAME to the team table"
  /usr/bin/python3 - "$AG" "$DNAME" "$OWNS" "$ASK" <<'EOF'
import sys
path, display, owns, ask = sys.argv[1:]
s = open(path, encoding="utf-8").read()
end = "<!-- team:end -->"
if end not in s:
    sys.exit("hire.sh: the team table markers are missing from workspace/AGENTS.md")
if f"| {display} |" not in s:
    clean = lambda t: t.replace("|", "/")
    s = s.replace(end, f"| {display} | {clean(owns)} | {clean(ask)} |\n{end}", 1)
    open(path, "w", encoding="utf-8").write(s)
EOF
  if ! git -C "$HOME/workspace" diff --quiet -- AGENTS.md; then
    git -C "$HOME/workspace" commit -q -m "AGENTS.md: $DNAME joins the team (hire.sh)" -- AGENTS.md
  fi
  CHANGED+=(".hermes/profiles/$ROLE/SOUL.md" ".hermes/profiles/$ROLE/config.yaml" ".hermes/profiles/$ROLE/profile.yaml")
fi

if [ -n "$CHANNEL" ]; then
  echo "==> Routing Discord channel $CHANNEL to $ROLE"
  CUR="$(hermes config get --json gateway.profile_routes 2>/dev/null || true)"
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
  hermes config set gateway.profile_routes "$NEW" >/dev/null
  hermes config get --json gateway.profile_routes | grep -q "\"$CHANNEL\"" || die "the Discord route did not save"
  CHANGED+=(".hermes/config.yaml")
fi

MSG="Hired $DNAME ($ROLE) from system/roles/$ROLE.md"
[ -z "$CHANNEL" ] || MSG="$MSG; Discord channel $CHANNEL routed to it"
"$LOG" manager decision "$MSG" "system/roles/$ROLE" >/dev/null
CHANGED+=("vault/log.md" "vault/system/roles/$ROLE.md")
"$COMMIT" manager "hire: $ROLE" "${CHANGED[@]}" >/dev/null || true

echo
echo "Done: $DNAME ($PROJECT) is on the team."
[ -z "$CHANNEL" ] || echo "Needs a gateway restart for the Discord route (the owner runs: systemctl --user restart hermes-gateway)."
echo "Next: $DNAME proposes its domain to the owner; once agreed it writes team/$ROLE.md."
