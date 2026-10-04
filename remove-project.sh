#!/bin/bash
# Remove a project completely: its services, Linux user, folder (vault, repos, bots, keys),
# registry entry and firewall rules. There is no undo, so it asks you to type the name.
#
#   sudo bash remove-project.sh <name> [--yes]     (--yes skips typing the name: for scripted tests)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=host.conf
source "$HERE/host.conf"
# Host-specific settings that survive template updates
# shellcheck disable=SC1091
[ -f /etc/hermes/host.conf ] && source /etc/hermes/host.conf
die() { echo "remove-project: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo:  sudo bash remove-project.sh <name>"
NAME="${1:-}"
YES=0; [ "${2:-}" = "--yes" ] && YES=1
[[ "$NAME" =~ ^[a-z][a-z0-9-]{1,24}$ ]] || die "usage: sudo bash remove-project.sh <name>"
AGENT="$USER_PREFIX$NAME"
HOST_LABEL="${HOST_LABEL:-$(hostname -s)}"
HOME_DIR="$ROOT/$NAME"
NUM="$(awk -v key="  $NAME:" '$0==key{f=1;next} f&&/^  [^ ]/{f=0} f&&/^    num:/{print $2; exit}' "$REGISTRY" 2>/dev/null || true)"

echo "This permanently deletes project '$NAME':"
echo "  - user $AGENT and everything in $HOME_DIR (vault, repos, bots, keys, sessions)"
[ -n "$NUM" ] && echo "  - registry entry (num $NUM) and its firewall rules"
if [ "$YES" = 1 ]; then
  CONFIRM="$NAME"
else
  read -rp "Type the project name to confirm: " CONFIRM </dev/tty
fi
[ "$CONFIRM" = "$NAME" ] || die "not confirmed; nothing changed"

if id "$AGENT" >/dev/null 2>&1; then
  AUID="$(id -u "$AGENT")"
  loginctl disable-linger "$AGENT" || true
  systemctl stop "user@$AUID.service" 2>/dev/null || true
  pkill -KILL -u "$AGENT" 2>/dev/null || true
  sleep 1
  userdel "$AGENT" 2>/dev/null || true
  getent group "$AGENT" >/dev/null && { groupdel "$AGENT" || true; }
  echo "user removed"
fi
rm -rf -- "$HOME_DIR"
echo "folder removed"

if [ -n "$NUM" ]; then
  API=$((10000 + NUM * 100)); APP_LO=$((API + 1)); APP_HI=$((API + 99))
  if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    for NET in $LAN_SUBNETS; do
      ufw delete allow from "$NET" to any port "$APP_LO:$APP_HI" proto tcp >/dev/null 2>&1 || true
    done
    echo "firewall rules removed"
  fi
  awk -v key="  $NAME:" '$0==key{skip=1;next} skip&&/^  [^ ]/{skip=0} !skip' "$REGISTRY" > "$REGISTRY.tmp"
  mv "$REGISTRY.tmp" "$REGISTRY"; chmod 644 "$REGISTRY"
  echo "registry entry removed"
fi
echo "Done. Remove the '$HOST_LABEL-$NAME' block from ~/.ssh/config on your PC, and the connection in Hermes Desktop."
