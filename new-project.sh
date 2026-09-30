#!/bin/bash
# Create a new Hermes project on this host: one Linux user, one Hermes install, one vault, and a Manager.
#
#   sudo bash new-project.sh <name> [--num N]
#
# Run it as the admin user from a clone of this repo. It is safe to re-run: finished steps are skipped.
# Part 1 (root): user, folder, linger, SSH keys, registry entry, firewall.
# Part 2 (as agent-<name>): bootstrap/setup-agent.sh installs Hermes and sets up the Manager.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host.conf
source "$HERE/host.conf"

die()  { echo "new-project: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "run with sudo:  sudo bash new-project.sh <name>"
NAME="${1:-}"
if [ $# -gt 0 ]; then shift; fi
NUM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --num) NUM="${2:-}"; shift 2 ;;
    *) die "unknown option '$1'" ;;
  esac
done
[[ "$NAME" =~ ^[a-z][a-z0-9-]{1,24}$ ]] || die "name must be 2-25 chars: lowercase letters, digits and '-', starting with a letter"
AGENT="$USER_PREFIX$NAME"
HOME_DIR="$ROOT/$NAME"
OWNER_USER="${OWNER_USER:-${SUDO_USER:-}}"
[ -n "$OWNER_USER" ] && [ "$OWNER_USER" != root ] || die "run it with sudo from your admin user (or set OWNER_USER in host.conf)"
id "$OWNER_USER" >/dev/null 2>&1 || die "owner user '$OWNER_USER' does not exist"
HOST_LABEL="${HOST_LABEL:-$(hostname -s)}"
HOST_ADDR="${HOST_ADDR:-$(hostname -I | awk '{print $1}')}"

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
/usr/bin/python3 -c 'import yaml' 2>/dev/null || die "python3-yaml is required and could not be installed"

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
if command -v ufw >/dev/null 2>&1; then
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
cp -r "$HERE/template" "$HERE/bootstrap" "$HERE/host.conf" "$B/"
cat > "$B/project.env" <<EOF
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
  2. Discord: DM the bot (or use your project channel). The Manager starts the intake interview.
  3. $OWNER_USER was added to group $AGENT: log out and in again to read the project folder.
EOF
