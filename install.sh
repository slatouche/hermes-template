#!/bin/bash
# One command to create a Hermes project on this server:
#
#   curl -fsSL https://raw.githubusercontent.com/slatouche/hermes-template/main/install.sh | sudo bash
#
# Gets (or updates) this template into /opt/hermes-template, owned by root so no project can change what
# root runs, then starts new-project.sh, which asks for everything it needs. Pass its options after
# "bash -s --", e.g.  ... | sudo bash -s -- tcg-proxy --import https://github.com/you/repo.git
# Your own host settings go in /etc/hermes/host.conf (they override the template's host.conf and survive updates).
set -euo pipefail
REPO="${TEMPLATE_REPO:-https://github.com/slatouche/hermes-template.git}"
DIR="${TEMPLATE_DIR:-/opt/hermes-template}"
die() { echo "install: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run it with sudo"
command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq git >/dev/null; } || die "git is needed"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q --ff-only || die "could not update $DIR (local changes? put host settings in /etc/hermes/host.conf)"
elif [ -d "$REPO" ]; then
  rm -rf "$DIR"; cp -r "$REPO" "$DIR"            # a local copy (testing a template change before it's pushed)
else
  git clone -q "$REPO" "$DIR"
fi
chown -R root:root "$DIR"; chmod -R go-w "$DIR"
install -d -m 755 /etc/hermes
echo "Template ready in $DIR ($(git -C "$DIR" log --oneline -1 2>/dev/null || echo local copy))."
exec bash "$DIR/new-project.sh" "$@" </dev/tty
