#!/bin/bash
# The two demo slots: where the Designer shows the owner something that doesn't exist in the app yet (a new page, a
# few options to choose from) before it goes into the mockup. Each slot serves a folder of plain HTML from the vault
# with the Mark tool on it, so the owner's notes say which demo and which option they're about.
#
#   demo.sh show <1|2> <folder> "<what it is>"   serve ~/vault/design/<folder> on the slot (replaces what was there)
#   demo.sh clear <1|2>                          take the slot down (archive the folder separately, see the Designer role)
#   demo.sh list
#
# Slot 1 serves on <API port + 46> (review link + 50 = <API port + 96>); slot 2 on <API port + 47> (review <API port + 97>).
# Both bind to localhost; the owner opens the review link, which carries the Mark tool.
set -euo pipefail
MIRRORS="$HOME/.hermes/scripts/review-mirrors.conf"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
die() { echo "demo: $*" >&2; exit 1; }
api=$(grep -m1 '^API_SERVER_PORT=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2)
[ -n "$api" ] || die "can't find API_SERVER_PORT in ~/.hermes/.env"
slot_port() { echo $((api + 45 + $1)); }

drop_mirror() { [ -f "$MIRRORS" ] && sed -i "/^$(( $(slot_port "$1") + 50 )) /d" "$MIRRORS" || true; }

case "${1:-}" in
  show)
    n="${2:?slot 1 or 2}"; folder="${3:?folder under ~/vault/design}"; what="${4:?what it is}"
    [[ "$n" =~ ^[12]$ ]] || die "slot is 1 or 2"
    dir="$HOME/vault/design/${folder#/}"; [ -d "$dir" ] || die "no folder $dir"
    port=$(slot_port "$n"); unit="$HOME/.config/systemd/user/design-demo-$n.service"; mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<EOF
[Unit]
Description=Design demo $n: $what

[Service]
ExecStart=/usr/bin/python3 -m http.server $port --bind 127.0.0.1 --directory $dir
Restart=always

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload; systemctl --user enable -q "design-demo-$n"; systemctl --user restart "design-demo-$n"
    drop_mirror "$n"; echo "$((port + 50)) $port demo $n: ${what//$'\n'/ }" >> "$MIRRORS"
    systemctl --user restart feedback-inbox
    echo "demo $n: $what → review link :$((port + 50)) (serving $dir)" ;;
  clear)
    n="${2:?slot 1 or 2}"; [[ "$n" =~ ^[12]$ ]] || die "slot is 1 or 2"
    systemctl --user disable -q --now "design-demo-$n" 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/design-demo-$n.service"; systemctl --user daemon-reload
    drop_mirror "$n"; systemctl --user restart feedback-inbox
    echo "demo $n cleared" ;;
  list)
    for n in 1 2; do
      p=$(slot_port "$n"); line=$(grep "^$((p + 50)) $p " "$MIRRORS" 2>/dev/null | cut -d' ' -f3- || true)
      echo "demo $n  review :$((p + 50))  ${line:-free}"
    done ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
