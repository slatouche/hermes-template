#!/bin/bash
# The design view: the owner's one design page for this project, on <API port + 51> (e.g. 15051).
#
#   design-view.sh up [--app <frontend dir>] [--api-cmd '<start command>' --data <folder>] [--fresh-data]
#   design-view.sh reset-data | down | restart | status | log [n]
#
# The app's front end defaults to ~/workspace/frontend; when that folder doesn't exist yet, the starter front end is
# copied there (a blank app with a top bar and one screen), so design can start from nothing. The design layer is
# ~/vault/design/layer. See design-view.py for what is served.
#
# An app with a real back end: --api-cmd runs a copy of it on <API port + 26> (the design-api user service) on a COPY
# of its data (--data, copied once to ~/design-data; --fresh-data or reset-data copies it again), and the design view
# passes /api calls to it. The real app and its data are never touched. The command may use {port}, {data} and
# {repo} (~/workspace), e.g. --api-cmd '.venv/bin/python -m myapp --port {port} --root {data}'. Without --api-cmd,
# /api answers from the layer's mock data (vault/design/layer/data/).
# Settings are kept in ~/.hermes/design-view.conf, so a later 'up' with no options keeps them.
set -euo pipefail
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
die() { echo "design-view: $*" >&2; exit 1; }
H="$HOME/.hermes"
api=$(grep -m1 '^API_SERVER_PORT=' "$H/.env" 2>/dev/null | cut -d= -f2)
[ -n "$api" ] || die "can't find API_SERVER_PORT in ~/.hermes/.env"
PORT=$((api + 51)); API_PORT=$((api + 26))
PROJECT="${HERMES_PROJECT:-$(id -un | sed 's/^agent-//')}"
UNITS="$HOME/.config/systemd/user"
CONF="$H/design-view.conf"
DATA_COPY="$HOME/design-data"
APP=""; API_CMD=""; DATA=""
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"

copy_data() {        # a fresh copy of the app's data for the design copy; the original is only read
  [ -n "$DATA" ] && [ -e "$DATA" ] || die "no data folder to copy ($DATA)"
  rm -rf "$DATA_COPY.new"; cp -a "$DATA" "$DATA_COPY.new"; rm -rf "$DATA_COPY"; mv "$DATA_COPY.new" "$DATA_COPY"
  echo "copied $DATA -> $DATA_COPY"
}
api_up() {           # the copy of the app's back end the design view passes /api calls to
  [ -e "$DATA_COPY" ] || copy_data
  local cmd="${API_CMD//\{port\}/$API_PORT}"; cmd="${cmd//\{data\}/$DATA_COPY}"; cmd="${cmd//\{repo\}/$HOME/workspace}"
  printf '#!/bin/bash\ncd %q\nexec %s\n' "$HOME/workspace" "$cmd" > "$H/design-api.sh"; chmod +x "$H/design-api.sh"
  cat > "$UNITS/design-api.service" <<EOF
[Unit]
Description=Design copy of $PROJECT's back end for the design view (port $API_PORT, data $DATA_COPY)

[Service]
ExecStart=$H/design-api.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload; systemctl --user enable -q design-api; systemctl --user restart design-api
}

case "${1:-status}" in
  up)
    shift; FRESH=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --app) APP="${2:?--app needs a folder}"; shift 2 ;;
        --api-cmd) API_CMD="${2:?--api-cmd needs a command}"; shift 2 ;;
        --data) DATA="${2:?--data needs a folder}"; shift 2 ;;
        --fresh-data) FRESH=1; shift ;;
        *) die "unknown option $1" ;;
      esac
    done
    APP="${APP:-$HOME/workspace/frontend}"
    [ -z "$API_CMD" ] || [ -n "$DATA" ] || die "--api-cmd needs --data <the app's data folder> (it runs on a copy)"
    if ! systemctl --user is-active -q design-view 2>/dev/null && ss -ltn 2>/dev/null | grep -q ":$PORT "; then
      die "port $PORT is already in use (something else holds the design view's port)"
    fi
    if [ ! -e "$APP" ]; then
      [ -d "$H/starter/frontend" ] || die "no starter front end in $H/starter"
      mkdir -p "$(dirname "$APP")"; cp -a "$H/starter/frontend" "$APP"
      echo "started the app from the starter front end: $APP"
    fi
    mkdir -p "$HOME/vault/design/layer" "$HOME/.local/bin" "$UNITS"
    ln -sf "$H/scripts/dv.py" "$HOME/.local/bin/dv.py"        # on every bot's PATH
    printf 'APP=%q\nAPI_CMD=%q\nDATA=%q\n' "$APP" "$API_CMD" "$DATA" > "$CONF"
    PROXY=""
    if [ -n "$API_CMD" ]; then
      [ -n "$FRESH" ] && copy_data
      api_up; PROXY="--api-proxy http://127.0.0.1:$API_PORT"
    fi
    cat > "$UNITS/design-view.service" <<EOF
[Unit]
Description=Design view for $PROJECT (port $PORT)
After=network.target

[Service]
ExecStart=/usr/bin/python3 $H/scripts/design-view.py --project $PROJECT --port $PORT --app $APP --layer $HOME/vault/design/layer $PROXY
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
  reset-data)
    [ -n "$API_CMD" ] || die "this design view has no back-end copy (it uses mock data)"
    copy_data; systemctl --user restart design-api; echo "data reset" ;;
  down)    systemctl --user disable -q --now design-view design-api 2>/dev/null || true; echo "stopped" ;;
  restart) systemctl --user restart design-view; [ -n "$API_CMD" ] && systemctl --user restart design-api; echo "restarted" ;;
  status)  systemctl --user is-active design-view 2>/dev/null || true; [ -f "$CONF" ] && cat "$CONF" ;;
  log)     journalctl --user -u design-view -n "${2:-40}" --no-pager ;;
  *) die "usage: design-view.sh up [--app <dir>] [--api-cmd '<cmd>' --data <dir>] [--fresh-data] | reset-data | down | restart | status | log" ;;
esac
