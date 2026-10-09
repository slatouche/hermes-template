#!/bin/bash
# The mockup: the owner's main design view, always on <API port + 51> (e.g. 10151). A live copy of the app with the
# Designer's working look on it (vault/design/mockup-look names it) and the Mark toolbar, where the owner clicks
# around, marks things up and watches the changes land. Nothing done there touches the real app's data, and nothing
# the Engineer is half-way through changes under it. Options to choose between go on a demo (demo.sh portfolio), never
# on the mockup. One mockup per project: the main app.
#
#   mockup.sh add <name> <app port> <data path> -- <command>   once per app (the Engineer, when the app is first served)
#   mockup.sh refresh <name> [--ref <branch>]   take a new snapshot: the code on `main` (or a prototype branch, so the
#                               owner can try it; the badge says so) and a fresh copy of the data, then (re)start
#   mockup.sh reset <name>      a fresh copy of the data only (the owner's "reset data" on the badge)
#   mockup.sh look <look|off>   the look the mockup shows from now on (off: the app as built); open pages reload
#   mockup.sh proto <folder>    the mockup is a prototype (look.py proto new) instead of a copy of the app: a navigable
#                               skeleton site on the same port, before the app exists or for a screen it doesn't have
#   mockup.sh list
#
# <command> starts the app from the snapshot; {port}, {data} and {repo} are filled in (the mockup's port, the copied
# data folder, ~/workspace for things git doesn't hold such as .venv). Example:
#   mockup.sh add tcg-proxy 10301 ProxyDecks -- '{repo}/.venv/bin/python -m tcgproxy --host 127.0.0.1 --port {port} --root {data} --no-browser'
# The mockup listens on <app port + 25>, local only; the owner opens it on <API port + 51> (with Mark and the nav).
# Code lives in ~/mockup/<name>/code (a git worktree, detached at main), data in ~/mockup/<name>/data.
set -euo pipefail
CONF="$HOME/.hermes/scripts/mockups.conf"
MIRRORS="$HOME/.hermes/scripts/review-mirrors.conf"
REPO="$HOME/workspace"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
die() { echo "mockup: $*" >&2; exit 1; }
row() { grep -v '^\s*#' "$CONF" 2>/dev/null | awk -F'|' -v n="$1" '$1==n' | head -1; }
api=$(grep -m1 '^API_SERVER_PORT=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2)
[ -n "$api" ] || die "can't find API_SERVER_PORT in ~/.hermes/.env"
VIEW=$((api + 51))     # the mockup's link: the same port in every project

copy_data() {   # $1 data path (relative to ~/workspace or absolute), $2 mockup dir
  local src="$1"; [[ "$src" = /* ]] || src="$REPO/$src"
  [ -e "$src" ] || die "no data at $src"
  rm -rf "$2/data.new"; cp -a "$src" "$2/data.new"; rm -rf "$2/data"; mv "$2/data.new" "$2/data"
}

case "${1:-}" in
  add)
    name="${2:?name}"; aport="${3:?app port}"; data="${4:?data path}"; [ "${5:-}" = "--" ] || die "usage: add <name> <app port> <data> -- <command>"
    shift 5; cmd="$*"; [ -n "$cmd" ] || die "no command"
    [[ "$name" =~ ^[a-z0-9-]+$ ]] || die "name: lowercase letters, digits and dashes"
    other=$(grep -v '^\s*#' "$CONF" 2>/dev/null | cut -d'|' -f1 | grep -vx "$name" | head -1 || true)
    [ -z "$other" ] || die "this project already has its mockup ($other); there is one, of the main app"
    touch "$CONF"; grep -v "^$name|" "$CONF" > "$CONF.tmp" || true
    echo "$name|$((aport + 25))|$data|$cmd" >> "$CONF.tmp"; mv "$CONF.tmp" "$CONF"
    exec "$0" refresh "$name" ;;
  proto)
    folder="${2:?prototype folder under ~/vault/design}"; src="$HOME/vault/design/${folder#/}"
    [ -f "$src/index.html" ] || die "no prototype at $src (look.py proto new <name>)"
    [ -n "$api" ] || die "no API port"
    touch "$CONF"; old=$(grep -v '^\s*#' "$CONF" | cut -d'|' -f1 | head -1 || true)
    if [ -n "$old" ] && [ "$old" != proto ]; then           # the app's mockup steps aside (mockup.sh add brings it back)
      cp "$CONF" "$CONF.before-proto"; systemctl --user disable -q --now "$old-mockup" 2>/dev/null || true; fi
    echo "proto|$((api + 26))|-|/usr/bin/python3 -m http.server {port} --bind 127.0.0.1 --directory $src" > "$CONF"
    exec "$0" refresh proto ;;
  refresh|reset)
    r="$(row "${2:?name}")"; [ -n "$r" ] || die "no mockup called $2 (mockup.sh list)"
    IFS='|' read -r name port data cmd <<<"$r"
    dir="$HOME/mockup/$name"; mkdir -p "$dir"
    if [ "$data" = - ]; then                             # a prototype: its files are the mockup, nothing to snapshot
      printf 'prototype %s' "$(basename "${cmd##* }")" > "$dir/SNAPSHOT"; mkdir -p "$dir/code" "$dir/data"
    elif [ "$1" = refresh ]; then
      main=$(git -C "$REPO" rev-parse --verify -q main >/dev/null && echo main || echo master)
      ref="$main"; [ "${3:-}" = "--ref" ] && ref="${4:?branch}"
      git -C "$REPO" rev-parse --verify -q "$ref" >/dev/null || die "no branch $ref in ~/workspace"
      if [ -d "$dir/code" ]; then git -C "$dir/code" checkout -q --detach "$ref"
      else git -C "$REPO" worktree add -q --detach "$dir/code" "$ref"; fi
      label=""; [ "$ref" != "$main" ] && label="prototype $ref: "
      printf '%s%s · snapshot %s' "$label" "$(git -C "$dir/code" log -1 --format='%h %s' | cut -c1-70)" "$(date '+%-d %b %H:%M')" > "$dir/SNAPSHOT"
    fi
    systemctl --user stop "$name-mockup" 2>/dev/null || true
    [ "$data" = - ] || copy_data "$data" "$dir"
    run="${cmd//\{port\}/$port}"; run="${run//\{data\}/$dir/data}"; run="${run//\{repo\}/$REPO}"
    unit="$HOME/.config/systemd/user/$name-mockup.service"; mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<EOF
[Unit]
Description=$name mockup (a snapshot of main with a copy of the data; the owner's view :$VIEW)

[Service]
WorkingDirectory=$dir/code
ExecStart=/bin/bash -c 'exec $run'
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload; systemctl --user enable -q --now "$name-mockup"
    if ! grep -q "^$VIEW $port " "$MIRRORS" 2>/dev/null; then      # anything else on the view port gives way
      { grep -v "^$VIEW " "$MIRRORS" 2>/dev/null || true; echo "$VIEW $port $name mockup"; } > "$MIRRORS.tmp"
      mv "$MIRRORS.tmp" "$MIRRORS"
      systemctl --user restart feedback-inbox 2>/dev/null || true
    fi
    for _ in $(seq 1 20); do curl -fs -o /dev/null "http://127.0.0.1:$port/" && break; sleep 1; done
    curl -fs -o /dev/null "http://127.0.0.1:$port/" || die "the mockup didn't answer on :$port (journalctl --user -u $name-mockup)"
    echo "$name mockup: $(cat "$dir/SNAPSHOT"); the owner's view :$VIEW" ;;
  look)
    lk="${2:?look name, or off}"; f="$HOME/vault/design/mockup-look"
    if [ "$lk" = off ]; then rm -f "$f"; echo "mockup: the app as built"
    else [ -d "$HOME/vault/design/variants/$lk" ] || die "no look $lk under vault/design/variants"
      echo "$lk" > "$f"; echo "mockup: look $lk (open pages switch to it within 2 s)"; fi ;;
  list)
    grep -v '^\s*#' "$CONF" 2>/dev/null | while IFS='|' read -r name port data cmd; do
      echo "$name  :$port (the owner's view :$VIEW, look: $(cat "$HOME/vault/design/mockup-look" 2>/dev/null || echo 'as built'))  $(cat "$HOME/mockup/$name/SNAPSHOT" 2>/dev/null || echo 'not started')"
    done ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac
