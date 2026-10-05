#!/bin/bash
# One shared web search for every project's bots: SearXNG (self-hosted metasearch, no keys, no cost) on
# 127.0.0.1:8888, under its own system user. Run by new-project.sh once per server (safe to re-run).
#
#   sudo bash install-searxng.sh
#
# Bots use it through Hermes' web_search (SEARXNG_URL) and directly with categories:
#   curl -s "http://127.0.0.1:8888/search?q=<terms>&categories=it&format=json"      GitHub, Stack Overflow, MDN
#   curl -s "http://127.0.0.1:8888/search?q=<terms>&categories=science&format=json" arXiv, Semantic Scholar, Scholar
# Some engines (DuckDuckGo, Brave) block automated use now and then; the others carry the results.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
if curl -fs -o /dev/null "http://127.0.0.1:8888/search?q=test&format=json"; then echo "SearXNG already running"; exit 0; fi
id searxng >/dev/null 2>&1 || useradd -r -m -d /opt/searxng -s /usr/sbin/nologin searxng
sudo -u searxng -H bash -c '
  set -e; cd /opt/searxng
  [ -d src ] || git clone -q --depth 1 https://github.com/searxng/searxng.git src
  [ -d venv ] || python3 -m venv venv
  ./venv/bin/pip install -q -U pip setuptools wheel pyyaml msgspec typing_extensions
  cd src && ../venv/bin/pip install -q --use-pep517 --no-build-isolation -e .'
install -d -o searxng -g searxng -m 750 /etc/searxng
if [ ! -f /etc/searxng/settings.yml ]; then
  umask 027
  cat > /etc/searxng/settings.yml <<EOF
use_default_settings: true
general:
  instance_name: "$(hostname -s) search"
server:
  bind_address: "127.0.0.1"
  port: 8888
  secret_key: "$(openssl rand -hex 32)"
  limiter: false
  image_proxy: false
search:
  safe_search: 0
  formats: [html, json]
engines:
  - name: bing
    disabled: false
  - name: startpage
    disabled: false
  - name: mojeek
    disabled: false
  - name: wikipedia
    disabled: false
  - name: github
    disabled: false
  - name: stackoverflow
    disabled: false
  - name: reddit
    disabled: false
  - name: arxiv
    disabled: false
EOF
  chown searxng:searxng /etc/searxng/settings.yml
fi
cat > /etc/systemd/system/searxng.service <<'EOF'
[Unit]
Description=SearXNG metasearch (local, shared by the projects' bots)
After=network-online.target

[Service]
User=searxng
Environment=SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml
WorkingDirectory=/opt/searxng/src
ExecStart=/opt/searxng/venv/bin/python -m searx.webapp
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now searxng >/dev/null
for _ in $(seq 1 20); do curl -fs -o /dev/null "http://127.0.0.1:8888/search?q=test&format=json" && break; sleep 1; done
curl -fs -o /dev/null "http://127.0.0.1:8888/search?q=test&format=json" && echo "SearXNG running on 127.0.0.1:8888" \
  || echo "warning: SearXNG didn't answer yet (journalctl -u searxng)"
