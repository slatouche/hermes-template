#!/bin/bash
# The design view: the owner's one design page for this project, on <API port + 51> (e.g. 15051).
#
#   design-view.sh up [--app <frontend dir>]   start it (a user service); new projects get the starter front end
#   design-view.sh down | restart | status | log
#
# The app's front end defaults to ~/workspace/frontend; when that folder doesn't exist yet, the starter front end is
# copied there (a blank app with a top bar and one screen), so design can start from nothing. The design layer is
# ~/vault/design/layer. See design-view.py for what is served.
set -euo pipefail
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
die() { echo "design-view: $*" >&2; exit 1; }
H="$HOME/.hermes"
api=$(grep -m1 '^API_SERVER_PORT=' "$H/.env" 2>/dev/null | cut -d= -f2)
[ -n "$api" ] || die "can't find API_SERVER_PORT in ~/.hermes/.env"
PORT=$((api + 51))
PROJECT="${HERMES_PROJECT:-$(id -un | sed 's/^agent-//')}"
UNIT="$HOME/.config/systemd/user/design-view.service"
CONF="$H/design-view.conf"
case "${1:-status}" in
  up)
    APP="$HOME/workspace/frontend"
    [ "${2:-}" = "--app" ] && APP="${3:?--app needs a folder}"
    if ! systemctl --user is-active -q design-view 2>/dev/null && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
      die "port $PORT is already in use (an older project's mockup? mockup.sh rm it first)"
    fi
    if [ ! -e "$APP" ]; then
      [ -d "$H/starter/frontend" ] || die "no starter front end in $H/starter"
      mkdir -p "$(dirname "$APP")"; cp -a "$H/starter/frontend" "$APP"
      echo "started the app from the starter front end: $APP"
    fi
    mkdir -p "$HOME/vault/design/layer" "$HOME/.local/bin"
    ln -sf "$H/scripts/dv.py" "$HOME/.local/bin/dv.py"        # on every bot's PATH
    printf 'APP=%s\nPORT=%s\n' "$APP" "$PORT" > "$CONF"
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<EOF
[Unit]
Description=Design view for $PROJECT (port $PORT)
After=network.target

[Service]
ExecStart=/usr/bin/python3 $H/scripts/design-view.py --project $PROJECT --port $PORT --app $APP --layer $HOME/vault/design/layer
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable -q design-view
    systemctl --user restart design-view
    sleep 1
    systemctl --user is-active -q design-view || { journalctl --user -u design-view -n 20 --no-pager; die "it didn't start"; }
    echo "design view: http://$(hostname -I | awk '{print $1}'):$PORT/"
    ;;
  down)    systemctl --user disable -q --now design-view 2>/dev/null || true; echo "stopped" ;;
  restart) systemctl --user restart design-view; echo "restarted" ;;
  status)  systemctl --user is-active design-view 2>/dev/null || true; [ -f "$CONF" ] && cat "$CONF" ;;
  log)     journalctl --user -u design-view -n "${2:-40}" --no-pager ;;
  *) die "usage: design-view.sh up [--app <dir>] | down | restart | status | log" ;;
esac
