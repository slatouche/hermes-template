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
NOW="$(date +%H:%M)"
render() {
  sed -e "s|{{PROJECT_NAME}}|$NAME|g" -e "s|{{OWNER}}|$OWNER_NAME|g" -e "s|{{TIME}}|$NOW|g" \
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
elif [ -s "$B/provider.env" ]; then
  K="$(grep "^$KEY_VAR=" "$B/provider.env" | head -1 | cut -d= -f2-)"
  [ -n "$K" ] || die "the key file has no $KEY_VAR value"
  set_env "$ENV" "$KEY_VAR" "$K"; unset K
  echo "$KEY_VAR set from the key file"
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
# The host's shared SearXNG (install-searxng.sh) as web_search, when it answers; else Hermes' keyless fallback.
if curl -fs -o /dev/null "http://127.0.0.1:8888/search?q=test&format=json"; then set_env "$ENV" SEARXNG_URL "http://127.0.0.1:8888"; fi
# No WIKI_PATH: Hermes' bundled llm-wiki skill would treat the vault as its own wiki (different rules); it's
# switched off below. Remove it if an older setup wrote it.
sed -i '/^WIKI_PATH=/d' "$ENV"
echo "ok"

# ---------- default profile: stock Hermes plus the install's plumbing ----------
step "Default profile config"
hermes config set model.provider "$PROVIDER"
hermes config set model.default "$MODEL"
hermes config set model.base_url "$BASE_URL"
hermes config set model.api_mode chat_completions
hermes config set --force agent.reasoning_effort "$EFFORT"   # --force: the key checker wrongly flags this key
hermes config set agent.max_turns "$AGENT_MAX_TURNS"
hermes config set kanban.orchestrator_profile manager
hermes config set kanban.max_in_progress "$KANBAN_MAX_IN_PROGRESS"
hermes config set kanban.max_in_progress_per_profile "$KANBAN_MAX_PER_PROFILE"
hermes config set kanban.dispatch_interval_seconds 10        # a ready card starts within seconds (a cheap database check)
hermes config set kanban.failure_limit "$KANBAN_FAILURE_LIMIT"
hermes config set kanban.review_dispatch true
hermes config set kanban.auto_subscribe_on_create true
hermes config set gateway.multiplex_profiles true

# Context, learning and limits. Set on the default profile first (the Manager is cloned from it), then
# re-asserted on the Manager below, because a re-run skips creating an existing Manager.
apply_learning_settings() {   # apply_learning_settings <profile> <compression tokens>
  local p="$1" ctx="$2"
  hermes -p "$p" config set compression.threshold_tokens "$ctx"
  hermes -p "$p" config set compression.min_tail_user_messages "$COMPRESSION_MIN_TAIL_USER"
  # --force: Hermes reads these two keys but its key checker doesn't list them (verified in v0.21.5 source)
  hermes -p "$p" config set --force skills.creation_nudge_interval "$SKILL_NUDGE_INTERVAL"
  hermes -p "$p" config set --force auxiliary.background_review.max_input_tokens "$REVIEW_MAX_INPUT_TOKENS"
  hermes -p "$p" config set curator.stale_after_days "$CURATOR_STALE_DAYS"
  hermes -p "$p" config set curator.archive_after_days "$CURATOR_ARCHIVE_DAYS"
  hermes -p "$p" config set checkpoints.enabled true
  # The vault has its own rules (SCHEMA.md); the bundled llm-wiki skill's conflict with them.
  hermes -p "$p" config set --force skills.disabled '["llm-wiki"]' >/dev/null
  if grep -q '^SEARXNG_URL=' "$H/.env" 2>/dev/null; then hermes -p "$p" config set web.search_backend searxng >/dev/null; fi
  hermes -p "$p" config set delegation.max_concurrent_children "$DELEGATION_MAX_CHILDREN"
  hermes -p "$p" config set delegation.max_iterations "$DELEGATION_MAX_ITERATIONS"
  hermes -p "$p" config set --force delegation.reasoning_effort "$DELEGATION_EFFORT"
  # Card workers run unattended: approve what the scanner flags; the hardline floor and the deny globs still block.
  # Same for the other no-one-to-ask runs: cron (manager-watch waking the Manager) and API chats (Hermes treats
  # api_server as unattended, so a flagged command there is refused outright, not asked).
  for m in single_query_mode cron_mode unattended_mode; do
    hermes -p "$p" config set "approvals.$m" "${CARD_APPROVALS:-approve}" >/dev/null
  done
  hermes -p "$p" config set approvals.deny "${APPROVAL_DENY:-[]}" >/dev/null
  # Every bot needs the board tools in chats (CLI/Desktop and Discord); story-maker's Manager had them off.
  hermes -p "$p" tools enable kanban >/dev/null
  hermes -p "$p" tools enable --platform discord kanban >/dev/null
  hermes -p "$p" tools enable --platform api_server kanban >/dev/null   # chats through the local API
}
apply_learning_settings default "$COMPRESSION_MANAGER_TOKENS"

# ---------- files: vault, scripts, AGENTS.md ----------
step "Vault, scripts and AGENTS.md"
mkdir -p "$HOME/workspace" "$HOME/scratch" "$HOME/data" "$H/scripts/templates"
# import/: the drop folder for bringing a project in later (copy with the project's own SSH login).
install -d -m 750 "$HOME/import"
# side/: ad-hoc side tracks (reverse-engineering, data pulls, experiments), outside the product and git, cleaned up when done.
install -d -m 750 "$HOME/side"
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
cp "$T"/scripts/* "$H/scripts/" 2>/dev/null || true
chmod +x "$H"/scripts/*.sh "$H"/scripts/*.py
# Files import-project.sh needs later: the team rules (rendered) and the onboarding status page.
render "$T/workspace/AGENTS.md" > "$H/scripts/templates/team-rules.md"
render "$T/import/00-status.md" > "$H/scripts/templates/00-status-onboarding.md"
cp "$T/workspace/scripts/run-tests.sh" "$H/scripts/templates/run-tests.sh"
# Role defaults for hire.sh (host.conf isn't kept in the project). A role file's own settings win.
cat > "$H/scripts/hire-defaults.conf" <<EOF
COMPRESSION_ROLE_TOKENS="$COMPRESSION_ROLE_TOKENS"
ROLE_MAX_TURNS="$ROLE_MAX_TURNS"
ROLE_BUDGET_WARNING="$ROLE_BUDGET_WARNING"
EFFORT="$EFFORT"
ROLE_DISABLED_TOOLSETS='${ROLE_DISABLED_TOOLSETS:-$DISABLED_TOOLSETS}'
ROLE_SKILL_CATEGORIES_OFF="${ROLE_SKILL_CATEGORIES_OFF:-apple autonomous-ai-agents email media note-taking social-media productivity}"
CARD_APPROVALS="${CARD_APPROVALS:-approve}"
APPROVAL_DENY='${APPROVAL_DENY:-[]}'
EOF
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
  mkdir -p "$HOME/workspace/scripts"
  install -m 755 "$T/workspace/scripts/run-tests.sh" "$HOME/workspace/scripts/run-tests.sh"
  git -C "$HOME/workspace" init -q
  git -C "$HOME/workspace" add AGENTS.md README.md scripts/run-tests.sh
  git -C "$HOME/workspace" commit -q -m "Initialise workspace from the project template"
  echo "created"
fi

# Kanban worktrees live in workspace/.worktrees/: keep them out of git status without touching the repo's files.
grep -qxF '.worktrees/' "$HOME/workspace/.git/info/exclude" 2>/dev/null || echo '.worktrees/' >> "$HOME/workspace/.git/info/exclude"

# ---------- the Manager ----------
step "Manager profile"
P="$H/profiles/manager"
if [ -d "$P" ]; then
  echo "exists; SOUL left as is"
else
  hermes profile create manager --clone \
    --description "The owner's front door: intake, planning, hiring, card routing, status and approved system changes"
  render "$T/manager/SOUL.md" > "$P/SOUL.md"
  # The Manager's notes about the owner start from the owner profile's seed block, like every hire's.
  mkdir -p "$P/memories"
  sed -n '/<!-- user-seed:start -->/,/<!-- user-seed:end -->/p' "$HOME/vault/system/owner-profile.md" \
    | sed '1d;$d' | head -c 1375 > "$P/memories/USER.md"
  sed -i '/^API_SERVER_\(ENABLED\|HOST\|PORT\)=/d' "$P/.env"   # only the default profile serves the API
  { grep -q '^SEARXNG_URL=' "$ENV" && ! grep -q '^SEARXNG_URL=' "$P/.env" && grep '^SEARXNG_URL=' "$ENV" >> "$P/.env"; } || true
fi
# The API reaches the Manager at /p/manager/ with the Manager's own key (one per profile; hires copy it).
grep -q '^API_SERVER_KEY=.' "$P/.env" 2>/dev/null && ! cmp -s <(grep '^API_SERVER_KEY=' "$P/.env") <(grep '^API_SERVER_KEY=' "$ENV") \
  || set_env "$P/.env" API_SERVER_KEY "$(openssl rand -hex 32)"
grep -q '^display_name:' "$P/profile.yaml" 2>/dev/null || echo "display_name: Manager ($NAME)" >> "$P/profile.yaml"
hermes -p manager config set terminal.cwd "$HOME/workspace"
hermes -p manager config set agent.disabled_toolsets "$DISABLED_TOOLSETS"
hermes -p manager config set discord.require_mention false
hermes -p manager config set agent.max_turns "$AGENT_MAX_TURNS"
apply_learning_settings manager "$COMPRESSION_MANAGER_TOKENS"
# /vault-changes in a Manager chat: what the bots changed in the vault since you last looked (no model call).
hermes -p manager config set --force quick_commands '{"vault-changes": {"type": "exec", "command": "bash ~/.hermes/scripts/vault-changes.sh"}, "queue": {"type": "exec", "command": "/usr/bin/python3 ~/.hermes/scripts/owner-queue.py"}}' >/dev/null
# The Manager's template skills (intake-interview, project-takeover...). Refreshed on every run; the bot's
# own skills have other names and are left alone.
for d in "$T"/manager/skills/*/*/; do
  rel="${d#"$T"/manager/skills/}"; rel="${rel%/}"
  rm -rf "$P/skills/$rel"; mkdir -p "$P/skills/$(dirname "$rel")"; cp -r "$d" "$P/skills/$rel"
done
echo "template skills: $(cd "$T/manager/skills" && ls -d */*/ | tr '\n' ' ')"
# The Manager's own jobs' scripts live in its profile (cron runs a profile's scripts from there).
mkdir -p "$P/scripts"
cp "$T"/manager/scripts/*.py "$P/scripts/"; chmod +x "$P"/scripts/*.py
if ! hermes -p manager project list 2>/dev/null | grep -q "$NAME"; then
  hermes -p manager project create "$NAME" "$HOME/workspace" --use
fi

# ---------- Discord (the Manager's bot) ----------
step "Discord"
if has_env "$P/.env" DISCORD_BOT_TOKEN; then
  echo "already set"
elif [ "${NO_DISCORD:-0}" = 1 ]; then
  echo "skipped (--no-discord)"
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
# Cards created from a chat may carry no workspace path; without a board default their worker can't start.
hermes kanban boards set-default-workdir default "$HOME/workspace" >/dev/null
hermes -p manager project bind-board "$NAME" default >/dev/null 2>&1 || true

# ---------- housekeeping jobs (no model tokens) ----------
step "Cron jobs"
JOBS="$(hermes cron list 2>/dev/null || true)"
grep -q 'vault-sweep' <<<"$JOBS" || hermes cron create "*/15 * * * *" --name vault-sweep --script vault-sweep.sh --no-agent --deliver local
grep -q 'vault-lint'  <<<"$JOBS" || hermes cron create "15 2 * * *"   --name vault-lint  --script vault-lint-job.sh --no-agent --deliver local
grep -q 'workspace-tidy' <<<"$JOBS" || hermes cron create "40 * * * *" --name workspace-tidy --script workspace-tidy.sh --no-agent --deliver local
# The Manager's two jobs: a script decides whether there's anything to do, so quiet runs cost no tokens.
MJOBS="$(hermes -p manager cron list 2>/dev/null || true)"
grep -q 'manager-watch' <<<"$MJOBS" || hermes -p manager cron create "*/15 * * * *" \
  "manager-watch tick. The script output above lists new findings with card ids. Load the work-planning skill and act on each one (its 'When work comes back' and 'manager-watch wakes you' parts). Keep 00-status.md true, put owner questions in waiting_on_owner, log what you did with vault-log.sh, then stop. Be brief." \
  --name manager-watch --script manager-watch.py --interpreter /usr/bin/python3 --workdir "$HOME/workspace" --deliver local >/dev/null
grep -q 'weekly-retro' <<<"$MJOBS" || hermes -p manager cron create "0 8 * * 1" \
  "weekly-retro. The script output above is the evidence pack since the last retro. Load the retro skill and follow it: causes, upkeep cards, and at most 5 proposed changes in system/changes/, then add one line to waiting_on_owner and stop." \
  --name weekly-retro --script retro-gate.py --interpreter /usr/bin/python3 --workdir "$HOME/workspace" --deliver local >/dev/null
/usr/bin/python3 "$H/profiles/manager/scripts/retro-gate.py" --baseline    # today's skills are the starting point
echo "Manager jobs: manager-watch (every 15 min), weekly-retro (Mondays 08:00); both silent unless their script finds something"
grep -q 'host-facts' <<<"$JOBS" || hermes cron create "5 3 * * *" --name host-facts --script host-facts.sh --no-agent --deliver local
bash "$H/scripts/host-facts.sh" >/dev/null || true      # vault/system/host.md: where this runs, how apps are served

# ---------- the owner's feedback inbox (Mark overlay + review links), last port of the block ----------
step "Feedback inbox"
FEEDBACK_PORT=$((API + 99))
touch "$H/scripts/review-mirrors.conf"
mkdir -p "$HOME/.config/systemd/user"
# Card workers resume their topic session: the gateway launches workers through $HERMES_BIN (hermes-worker.py),
# which adds `--resume` for a card with a `Session:` topic and runs everything else unchanged.
GW_REAL="$(grep -o 'ExecStart="[^"]*"' "$HOME/.config/systemd/user/hermes-gateway.service" 2>/dev/null | cut -d'"' -f2 || true)"   # the unit is created later on a first install
GW_REAL="${GW_REAL:-$HOME/.local/bin/hermes}"
mkdir -p "$HOME/.config/systemd/user/hermes-gateway.service.d"
cat > "$HOME/.config/systemd/user/hermes-gateway.service.d/topic-sessions.conf" <<EOF
[Service]
Environment="HERMES_BIN=$H/scripts/hermes-worker.py"
Environment="HERMES_REAL_BIN=$GW_REAL"
EOF
systemctl --user daemon-reload 2>/dev/null || true
hermes -p manager config set compression.idle_compact_after_seconds 3600 >/dev/null 2>&1 || true
cat > "$HOME/.config/systemd/user/feedback-inbox.service" <<EOF
[Unit]
Description=Owner feedback inbox for $NAME (Mark overlay and review links)

[Service]
ExecStart=/usr/bin/python3 %h/.hermes/scripts/feedback-inbox.py $FEEDBACK_PORT
Restart=always

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
if systemctl --user enable --now feedback-inbox >/dev/null 2>&1; then echo "running on :$FEEDBACK_PORT"
else echo "warning: the feedback inbox didn't start (systemctl --user status feedback-inbox)"; fi

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

# ---------- import an existing project (optional) ----------
if [ -n "${IMPORT_SRC:-}" ] && [ "$(git -C "$HOME/workspace" rev-list --count HEAD 2>/dev/null)" = 1 ]; then
  step "Import $IMPORT_SRC"
  ARGS=("$IMPORT_SRC" --interactive)
  [ -z "${IMPORT_NOTES:-}" ] || ARGS+=(--notes "$IMPORT_NOTES")
  "$H/scripts/import-project.sh" "${ARGS[@]}"
elif [ -n "${IMPORT_NOTES:-}" ] && [ ! -f "$HOME/vault/raw/predecessor/.notes-imported" ]; then
  step "Import notes $IMPORT_NOTES"            # a re-run after the notes step failed: the code is already in
  /usr/bin/python3 "$H/scripts/import-survey.py" --notes "$IMPORT_NOTES"
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
