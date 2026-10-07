#!/bin/bash
# Create a new Hermes project on this host: one Linux user, one Hermes install, one vault, and a Manager.
#
#   sudo bash new-project.sh                     (asks for everything it needs)
#   sudo bash new-project.sh <name> [--import <source>] [--notes <folder>] [--key-file <file>] [--no-discord] [--num N]
#
# --import    adopt an existing project: a git URL, a repo folder, a plain folder or a .bundle file. Its history
#             goes into workspace/ (committed files only for a repo) and the Manager takes it over: it reads
#             everything, asks what it can't work out, keeps the know-how, then cleans up. You can also import
#             later: copy the project into the project's ~/import/ folder and tell the Manager.
# --notes     a folder of an old bot's notes (memory, owner notes, skills), kept as evidence.
# --key-file  a root-only file with the provider key line (e.g. OPENCODE_GO_API_KEY=...), so it isn't typed.
#             host.conf PROVIDER_KEY_FILE sets a default. The key is never printed.
# --no-discord  don't ask for a Discord bot token (add one later; see README).
#
# Safe to re-run: finished steps are skipped.
# Part 1 (root): user, folder, linger, SSH keys, registry entry, firewall.
# Part 2 (as agent-<name>): bootstrap/setup-agent.sh installs Hermes, sets up the Manager, and imports.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host.conf
source "$HERE/host.conf"
# Host-specific settings that survive template updates
# shellcheck disable=SC1091
[ -f /etc/hermes/host.conf ] && source /etc/hermes/host.conf

die()  { echo "new-project: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }
trap 'echo "new-project: stopped on an error (above). Fix it and run the same command again: finished steps are skipped." >&2' ERR

[ "$(id -u)" -eq 0 ] || die "run with sudo:  sudo bash new-project.sh"
NAME=""
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then NAME="$1"; shift; fi
NUM=""; IMPORT=""; NOTES=""; KEY_FILE=""; NO_DISCORD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --num)        NUM="${2:-}"; shift 2 ;;
    --import)     IMPORT="${2:-}"; shift 2 ;;
    --notes)      NOTES="${2:-}"; shift 2 ;;
    --key-file)   KEY_FILE="${2:-}"; shift 2 ;;
    --no-discord) NO_DISCORD=1; shift ;;
    *) die "unknown option '$1'" ;;
  esac
done
ask() { local v; read -rp "$1" v </dev/tty; printf '%s' "$v"; }
if [ -z "$NAME" ]; then
  echo "New Hermes project. Press Ctrl+C at any point to stop; nothing is half-done that a re-run can't finish."
  NAME="$(ask "Project name (lowercase, digits, '-'; e.g. tcg-proxy): ")"
  if [ -z "$IMPORT" ]; then
    echo "Bring in an existing project? Give a git URL, or a folder or .bundle path on this server."
    echo "Press Enter to start from scratch (you can still import later via the project's ~/import folder)."
    IMPORT="$(ask "Import from: ")"
  fi
fi
[[ "$NAME" =~ ^[a-z][a-z0-9-]{1,24}$ ]] || die "name must be 2-25 chars: lowercase letters, digits and '-', starting with a letter"
AGENT="$USER_PREFIX$NAME"
HOME_DIR="$ROOT/$NAME"
OWNER_USER="${OWNER_USER:-${SUDO_USER:-}}"
[ -n "$OWNER_USER" ] && [ "$OWNER_USER" != root ] || die "run it with sudo from your admin user (or set OWNER_USER in host.conf)"
id "$OWNER_USER" >/dev/null 2>&1 || die "owner user '$OWNER_USER' does not exist"
HOST_LABEL="${HOST_LABEL:-$(hostname -s)}"
HOST_ADDR="${HOST_ADDR:-$(hostname -I | awk '{print $1}')}"

# ---------- WSL2 (Windows): the same install, with three differences ----------
# Services need systemd; the firewall is Windows'; and the address the owner reaches depends on WSL's networking:
# "mirrored" shares the PC's own LAN address, the default NAT mode is reachable from this PC only, as localhost.
WSL=0
if grep -qiE "microsoft|wsl" /proc/sys/kernel/osrelease 2>/dev/null; then
  WSL=1
  [ "$(ps -p 1 -o comm= 2>/dev/null)" = systemd ] || die "this is WSL without systemd. Add these lines to /etc/wsl.conf:
    [boot]
    systemd=true
  then run 'wsl --shutdown' in Windows PowerShell, open Ubuntu again and re-run this command."
  case "$HOST_ADDR" in
    172.1[6-9].*|172.2[0-9].*|172.3[01].*)        # WSL's private NAT network: only this PC can reach it
      WSL_NAT=1
      HOST_ADDR=localhost ;;
  esac
fi
IMPORT="${IMPORT/#\~/$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)}"     # allow ~/path
NOTES="${NOTES/#\~/$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)}"
if [ -n "$IMPORT" ]; then
  if [[ "$IMPORT" =~ ^https://[^/]*@ ]]; then die "--import: no credentials in the URL; a private repo asks for a token"
  elif [[ "$IMPORT" =~ ^(https://|ssh://|git@) ]]; then :
  elif [ -e "$IMPORT" ]; then IMPORT="$(readlink -f "$IMPORT")"
  else die "--import: '$IMPORT' is not a git URL, a folder or a .bundle file"; fi
fi
KEY_FILE="${KEY_FILE:-${PROVIDER_KEY_FILE:-}}"
[ -z "$NOTES" ] || [ -d "$NOTES" ] || die "--notes: '$NOTES' is not a folder"
if [ -n "$KEY_FILE" ]; then
  [ -f "$KEY_FILE" ] || die "--key-file: '$KEY_FILE' not found"
  grep -q "^$KEY_VAR=." "$KEY_FILE" || die "--key-file: no $KEY_VAR= line in it"
fi

# ---------- host packages (once per server; only what's missing) ----------
step "Host packages"
MISSING=()
for p in $HOST_PACKAGES; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed" || MISSING+=("$p")
done
if [ ${#MISSING[@]} -eq 0 ]; then
  echo "all present"
else
  echo "installing: ${MISSING[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  if ! apt-get install -y -qq "${MISSING[@]}" >/dev/null; then
    for p in "${MISSING[@]}"; do apt-get install -y -qq "$p" >/dev/null || echo "warning: could not install $p"; done
  fi
fi
for c in git curl openssl /usr/bin/python3; do command -v "$c" >/dev/null 2>&1 || die "$c is required and could not be installed"; done
if [ "$WSL" = 1 ]; then            # Hermes Desktop reaches a project over SSH; Ubuntu on WSL doesn't run a server by default
  if ! dpkg-query -W -f='${Status}' openssh-server 2>/dev/null | grep -q "ok installed"; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server >/dev/null || echo "warning: couldn't install openssh-server"
  fi
  systemctl enable --now ssh >/dev/null 2>&1 || echo "warning: the SSH server didn't start (systemctl status ssh): Hermes Desktop needs it"
fi
/usr/bin/python3 -c 'import yaml' 2>/dev/null || die "python3-yaml is required and could not be installed"
if [ "${SEARXNG:-yes}" = yes ]; then
  step "Web search for the bots (SearXNG, shared by all projects)"
  bash "$HERE/install-searxng.sh" || echo "warning: SearXNG install failed; bots fall back to Hermes' keyless search"
fi

# ---------- registry: find or assign the project number ----------
step "Registry"
install -d -m 755 "$ROOT"
if [ ! -f "$REGISTRY" ]; then
  cat > "$REGISTRY" <<'EOF'
# Project registry: name -> number, Linux user, port block
# Ports: project num NN gets 1NN00-1NN99. 1NN00 = Hermes API server (localhost only), 1NN01-1NN99 = apps.
projects:
EOF
fi
chmod 644 "$REGISTRY"
reg_num() { awk -v key="  $1:" '$0==key{f=1;next} f&&/^  [^ ]/{f=0} f&&/^    num:/{print $2; exit}' "$REGISTRY"; }
EXISTING="$(reg_num "$NAME")"
if [ -n "$EXISTING" ]; then
  [ -z "$NUM" ] || [ "$NUM" = "$EXISTING" ] || die "$NAME is already registered as num $EXISTING"
  NUM="$EXISTING"; echo "already registered: num $NUM"
else
  if [ -z "$NUM" ]; then
    NUM="$(awk '/^    num:/{if($2+0>m)m=$2+0} END{print m+1}' "$REGISTRY")"
  fi
  [[ "$NUM" =~ ^[0-9]+$ ]] && [ "$NUM" -ge 1 ] && [ "$NUM" -le 99 ] || die "num must be 1-99"
  if awk -v n="$NUM" '/^    num:/ && $2==n {found=1} END{exit !found}' "$REGISTRY"; then
    die "num $NUM is already taken in $REGISTRY"
  fi
fi
API=$((10000 + NUM * 100)); APP_LO=$((API + 1)); APP_HI=$((API + 99))
echo "project $NAME: num $NUM, API port $API (localhost), apps $APP_LO-$APP_HI"
if [ -z "$EXISTING" ]; then
  if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq ":($API)\$"; then
    die "port $API is already in use"
  fi
  cat >> "$REGISTRY" <<EOF
  $NAME:
    num: $NUM
    user: $AGENT
    ports: $API-$APP_HI
    api_port: $API
    status: active
EOF
  echo "added to $REGISTRY"
fi

# ---------- the Linux user and its home (the project folder) ----------
step "User $AGENT"
if id "$AGENT" >/dev/null 2>&1; then
  echo "exists"
else
  useradd --create-home --home-dir "$HOME_DIR" --shell /bin/bash --user-group "$AGENT"
  echo "created, home $HOME_DIR"
fi
chmod 750 "$HOME_DIR"
usermod -aG "$AGENT" "$OWNER_USER"          # the owner can read the project (log in again to take effect)
# The owner reads the project's two git repos, which belong to another user: mark them safe for the
# owner, or git refuses with "dubious ownership".
OWNER_SAFE="$(sudo -u "$OWNER_USER" -H git config --global --get-all safe.directory 2>/dev/null || true)"
for R in "$HOME_DIR" "$HOME_DIR/workspace"; do
  grep -qxF "$R" <<<"$OWNER_SAFE" || sudo -u "$OWNER_USER" -H git config --global --add safe.directory "$R"
done
install -d -m 700 -o "$AGENT" -g "$AGENT" "$HOME_DIR/.ssh"
OWNER_HOME="$(getent passwd "$OWNER_USER" | cut -d: -f6)"
if [ ! -s "$HOME_DIR/.ssh/authorized_keys" ]; then
  if [ -s "$OWNER_HOME/.ssh/authorized_keys" ]; then
    install -m 600 -o "$AGENT" -g "$AGENT" "$OWNER_HOME/.ssh/authorized_keys" "$HOME_DIR/.ssh/authorized_keys"
    echo "copied $OWNER_USER's authorized_keys (Hermes Desktop connects over SSH as $AGENT)"
  else
    echo "warning: $OWNER_USER has no ~/.ssh/authorized_keys, so Hermes Desktop can't log in as $AGENT yet"
  fi
fi

step "Linger (services run without anyone logged in)"
loginctl enable-linger "$AGENT"
AUID="$(id -u "$AGENT")"
systemctl start "user@$AUID.service"
for _ in $(seq 1 40); do [ -S "/run/user/$AUID/bus" ] && break; sleep 0.5; done
[ -S "/run/user/$AUID/bus" ] || die "the user service manager for $AGENT did not start"
echo "ok"

# ---------- firewall: app ports to the LAN only ----------
step "Firewall"
if [ "$WSL" = 1 ]; then
  echo "WSL: Windows' firewall decides who reaches these ports (ufw inside WSL doesn't apply)."
  if [ "${WSL_NAT:-0}" = 1 ]; then
    echo "  WSL is in NAT mode: the apps are reachable from this PC only, as http://localhost:<port>."
    echo "  For other devices on your network: networkingMode=mirrored in %UserProfile%\\.wslconfig (see README, WSL2)."
  else
    echo "  For other devices on your network, allow the ports once in Windows PowerShell (as administrator):"
    echo "    New-NetFirewallRule -DisplayName 'Hermes $NAME' -Direction Inbound -Protocol TCP -LocalPort $APP_LO-$APP_HI -Action Allow"
  fi
elif command -v ufw >/dev/null 2>&1; then
  for NET in $LAN_SUBNETS; do
    ufw allow from "$NET" to any port "$APP_LO:$APP_HI" proto tcp comment "$NAME apps"
  done
  if ! ufw status | grep -q "Status: active"; then
    echo "note: ufw is installed but OFF, so these rules aren't enforced yet. To turn it on safely:"
    echo "      sudo ufw allow OpenSSH && sudo ufw enable"
  fi
else
  echo "ufw not available; skipped"
fi

# ---------- part 2, as the agent user ----------
step "Staging the template for $AGENT"
B="$HOME_DIR/.bootstrap"
rm -rf "$B"; install -d -m 700 -o "$AGENT" -g "$AGENT" "$B"
trap 'rm -rf "$B"' EXIT                     # the staged key and bundle never outlive this run
cp -r "$HERE/template" "$HERE/bootstrap" "$HERE/host.conf" "$B/"
[ ! -f /etc/hermes/host.conf ] || cat /etc/hermes/host.conf >> "$B/host.conf"
# The import source: handed over where it is if the project user can read it (so the takeover can also list
# what git leaves behind), else copied into the project's ~/import/ drop folder first.
stage_for_agent() {   # stage_for_agent <path> -> prints the path the agent should use
  local src="$1" dst
  # Used in place only when the project user can read all of it (a folder copied in with sudo often can't).
  if sudo -u "$AGENT" test -r "$src" && { [ -f "$src" ] || { sudo -u "$AGENT" test -x "$src" &&
       [ -z "$(sudo -u "$AGENT" find "$src" \( ! -readable -o \( -type d ! -executable \) \) -print -quit 2>&1)" ]; }; }; then
    echo "$src"; return
  fi
  dst="$HOME_DIR/import/$(basename "$src")"
  install -d -m 750 -o "$AGENT" -g "$AGENT" "$HOME_DIR/import"
  rm -rf "$dst"
  if [ -e "$src/.git" ]; then git -c safe.directory='*' clone -q --no-hardlinks "$src" "$dst"; else cp -r "$src" "$dst"; fi
  chown -R "$AGENT:$AGENT" "$dst"
  echo "$dst"
}
IMPORT_SRC="$IMPORT"; IMPORT_NOTES=""
if [ -n "$IMPORT" ] && [[ ! "$IMPORT" =~ ^(https://|ssh://|git@) ]]; then IMPORT_SRC="$(stage_for_agent "$IMPORT")"; fi
[ -z "$NOTES" ] || IMPORT_NOTES="$(stage_for_agent "$(readlink -f "$NOTES")")"
if [ -n "$KEY_FILE" ]; then
  grep "^$KEY_VAR=." "$KEY_FILE" | head -1 > "$B/provider.env"; chmod 600 "$B/provider.env"; chown "$AGENT:$AGENT" "$B/provider.env"
fi
cat > "$B/project.env" <<EOF
IMPORT_SRC="$IMPORT_SRC"
IMPORT_NOTES="$IMPORT_NOTES"
NO_DISCORD="$NO_DISCORD"
NAME="$NAME"
NUM="$NUM"
AGENT="$AGENT"
API="$API"
APP_LO="$APP_LO"
APP_HI="$APP_HI"
HOST_LABEL="$HOST_LABEL"
HOST_ADDR="$HOST_ADDR"
EOF
chown -R "$AGENT:$AGENT" "$B"

step "Part 2: Hermes and the Manager (as $AGENT)"
cd "$HOME_DIR"
sudo -u "$AGENT" -H env \
  XDG_RUNTIME_DIR="/run/user/$AUID" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$AUID/bus" \
  bash "$B/bootstrap/setup-agent.sh"

rm -rf "$B"

cat <<EOF

============================================================
 $NAME is ready.   num $NUM · API $API (localhost) · apps $APP_LO-$APP_HI
============================================================
On your PC, add this to ~/.ssh/config (same key as the other projects):

  Host $HOST_LABEL-$NAME
      HostName $HOST_ADDR
      User $AGENT
      IdentityFile ~/.ssh/id_ed25519_homelab

Then:
  1. Hermes Desktop: add an SSH connection to $HOST_LABEL-$NAME and open the Manager.
  2. Say hello. $([ -n "$IMPORT_SRC" ] && echo "The Manager takes the imported project over (it reads it, then asks questions)." || echo "The Manager starts the interview.")
  Feedback: http://$HOST_ADDR:$((API + 99))/ (review links with the Mark toolbar, once an app is running)
  To import a project later: copy it into the project's import folder with the project's own login,
     scp -r <folder> $HOST_LABEL-$NAME:import/
  then tell the Manager "take over the project in ~/import/<folder>" (or just give it a git URL).
  3. $OWNER_USER was added to group $AGENT: log out and in again to read the project folder.
EOF
