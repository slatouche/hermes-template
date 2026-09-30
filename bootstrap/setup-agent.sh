#!/bin/bash
# Part 2 of new-project.sh, run as agent-<name> (never run it by hand as another user).
# Installs Hermes, asks for the keys, and sets up the default profile (plumbing), the Manager,
# the vault, both git repos, the housekeeping jobs and the gateway. Safe to re-run.
set -euo pipefail
B="$HOME/.bootstrap"
# shellcheck source=../host.conf
source "$B/host.conf"
# shellcheck disable=SC1091
source "$B/project.env"
T="$B/template"
H="$HOME/.hermes"
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME"

step() { printf '\n==> %s\n' "$*"; }
die()  { echo "setup-agent: $*" >&2; exit 1; }
TODAY="$(date +%F)"
render() {
  sed -e "s|{{PROJECT_NAME}}|$NAME|g" -e "s|{{OWNER}}|$OWNER_NAME|g" \
      -e "s|{{APP_PORTS}}|$APP_LO–$APP_HI|g" -e "s|{{API_PORT}}|$API|g" \
      -e "s|{{HOST}}|$HOST_LABEL ($HOST_ADDR)|g" -e "s|{{DATE}}|$TODAY|g" \
      -e "s|{{MAX_IN_PROGRESS}}|$KANBAN_MAX_IN_PROGRESS|g" \
      -e "s|{{MODELS}}|$MODEL_LABEL (effort $EFFORT) for every bot, via $PROVIDER|g" "$1"
}
has_env() { grep -q "^$2=." "$1" 2>/dev/null; }
set_env() {   # set_env <file> <KEY> <value>: replaces any existing line; never echoes the value
  local f="$1" k="$2" v="$3"
  touch "$f"; chmod 600 "$f"
  { grep -v "^$k=" "$f" || true; printf '%s=%s\n' "$k" "$v"; } > "$f.tmp"
  mv "$f.tmp" "$f"; chmod 600 "$f"
}
ask_secret() { local v; read -rsp "$1" v </dev/tty; echo >&2; printf '%s' "$v"; }
ask()        { local v; read -rp  "$1" v </dev/tty; printf '%s' "$v"; }

# ---------- Hermes ----------
step "Hermes"
if command -v hermes >/dev/null 2>&1; then
  hermes --version | head -1
else
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --non-interactive
  command -v hermes >/dev/null 2>&1 || die "Hermes did not install (see $H/logs/install.log)"
fi

# ---------- keys and settings (.env) ----------
step "Keys (.env)"
ENV="$H/.env"
if has_env "$ENV" "$KEY_VAR"; then
  echo "$KEY_VAR already set"
else
  K="$(ask_secret "Paste the $PROVIDER API key for $NAME (input hidden): ")"
  [ -n "$K" ] || die "an API key is required"
  set_env "$ENV" "$KEY_VAR" "$K"; unset K
fi
has_env "$ENV" API_SERVER_KEY || set_env "$ENV" API_SERVER_KEY "$(openssl rand -hex 32)"
set_env "$ENV" API_SERVER_ENABLED true
set_env "$ENV" API_SERVER_HOST 127.0.0.1
set_env "$ENV" API_SERVER_PORT "$API"
set_env "$ENV" OBSIDIAN_VAULT_PATH "$HOME/vault"
set_env "$ENV" WIKI_PATH "$HOME/vault"
echo "ok"

# ---------- default profile: stock Hermes plus the install's plumbing ----------
step "Default profile config"
hermes config set model.provider "$PROVIDER"
hermes config set model.default "$MODEL"
hermes config set model.base_url "$BASE_URL"
hermes config set model.api_mode chat_completions
hermes config set agent.reasoning_effort "$EFFORT"
hermes config set agent.max_turns "$AGENT_MAX_TURNS"
hermes config set kanban.orchestrator_profile manager
hermes config set kanban.max_in_progress "$KANBAN_MAX_IN_PROGRESS"
hermes config set kanban.max_in_progress_per_profile "$KANBAN_MAX_PER_PROFILE"
hermes config set kanban.failure_limit "$KANBAN_FAILURE_LIMIT"
hermes config set gateway.multiplex_profiles true

# ---------- files: vault, scripts, AGENTS.md ----------
step "Vault, scripts and AGENTS.md"
mkdir -p "$HOME/workspace" "$HOME/scratch" "$H/scripts"
if [ -f "$HOME/vault/SCHEMA.md" ]; then
  echo "vault exists; left as is"
else
  mkdir -p "$HOME/vault"
  cp -r "$T/vault/." "$HOME/vault/"
  while IFS= read -r -d '' f; do render "$f" > "$f.tmp" && mv "$f.tmp" "$f"; done \
    < <(find "$HOME/vault" -name '*.md' -print0)
  /usr/bin/python3 "$T/scripts/vault-index.py" "$HOME/vault" >/dev/null
  echo "vault created"
fi
cp "$T"/scripts/* "$H/scripts/"
chmod +x "$H"/scripts/*
render "$T/root-AGENTS.md" > "$HOME/AGENTS.md"

# ---------- git identity ----------
git config --global user.name "$NAME agent"
git config --global user.email "$AGENT@$HOST_LABEL.local"
git config --global init.defaultBranch main

# ---------- repo 1: the product workspace ----------
step "Workspace repo"
if [ -d "$HOME/workspace/.git" ]; then
  echo "exists"
else
  render "$T/workspace/AGENTS.md" > "$HOME/workspace/AGENTS.md"
  render "$T/workspace/README.md" > "$HOME/workspace/README.md"
  git -C "$HOME/workspace" init -q
  git -C "$HOME/workspace" add AGENTS.md README.md
  git -C "$HOME/workspace" commit -q -m "Initialise workspace from the project template"
  echo "created"
fi

# ---------- the Manager ----------
step "Manager profile"
P="$H/profiles/manager"
if [ -d "$P" ]; then
  echo "exists; SOUL left as is"
else
  hermes profile create manager --clone \
    --description "The owner's front door: intake, planning, hiring, card routing, status and approved system changes"
  render "$T/manager/SOUL.md" > "$P/SOUL.md"
  sed -i '/^API_SERVER_/d' "$P/.env"          # only the default profile serves the API
fi
grep -q '^display_name:' "$P/profile.yaml" 2>/dev/null || echo "display_name: Manager ($NAME)" >> "$P/profile.yaml"
hermes -p manager config set terminal.cwd "$HOME/workspace"
hermes -p manager config set agent.disabled_toolsets "$DISABLED_TOOLSETS"
hermes -p manager config set discord.require_mention false
if ! hermes -p manager project list 2>/dev/null | grep -q "$NAME"; then
  hermes -p manager project create "$NAME" "$HOME/workspace" --use
fi

# ---------- Discord (the Manager's bot) ----------
step "Discord"
if has_env "$P/.env" DISCORD_BOT_TOKEN; then
  echo "already set"
else
  echo "Paste this project's Discord bot token, or press Enter to skip (add it later; see README)."
  DT="$(ask_secret "Discord bot token (input hidden): ")"
  if [ -n "$DT" ]; then
    DU="${DISCORD_USER_ID:-}"
    [ -n "$DU" ] || DU="$(ask "Your Discord user ID (only this user may talk to the bots): ")"
    [[ "$DU" =~ ^[0-9]+$ ]] || die "the Discord user ID is a number"
    set_env "$P/.env" DISCORD_BOT_TOKEN "$DT"
    set_env "$P/.env" DISCORD_ALLOWED_USERS "$DU"
    echo "set"
  else
    echo "skipped"
  fi
  unset DT
fi

# ---------- kanban board ----------
step "Kanban board"
hermes kanban init

# ---------- housekeeping jobs (no model tokens) ----------
step "Cron jobs"
JOBS="$(hermes cron list 2>/dev/null || true)"
grep -q 'vault-sweep' <<<"$JOBS" || hermes cron create "*/15 * * * *" --name vault-sweep --script vault-sweep.sh --no-agent --deliver local
grep -q 'vault-lint'  <<<"$JOBS" || hermes cron create "15 2 * * *"   --name vault-lint  --script vault-lint-job.sh --no-agent --deliver local

# ---------- repo 2: project memory (vault + the bots' brains) ----------
step "Project memory repo"
if [ -d "$HOME/.git" ]; then
  echo "exists"
else
  cp "$T/memory.gitignore" "$HOME/.gitignore"
  git -C "$HOME" init -q
  git -C "$HOME" add -A
  git -C "$HOME" commit -q -m "Initialise project memory repo (vault + bot brains)"
  echo "created"
fi

# ---------- the gateway (messaging, cron, kanban dispatcher, API) ----------
step "Gateway"
if systemctl --user cat hermes-gateway >/dev/null 2>&1; then
  systemctl --user restart hermes-gateway
else
  hermes gateway install --start-on-login --start-now
fi
sleep 5
systemctl --user is-active hermes-gateway >/dev/null || die "the gateway is not running (journalctl --user -u hermes-gateway)"
echo "running"
