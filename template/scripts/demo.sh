#!/bin/bash
# The two demo slots: throwaway visuals beside the mockup. Options to pick from (a portfolio of looks), palettes,
# swatches, a page that doesn't exist yet. The mockup (mockup.sh) is the app in work; a demo is never the app.
# Each slot serves a folder of plain HTML from the vault with the Mark tool and the nav on it.
#
#   demo.sh show <1|2> <folder> "<what it is>"   serve ~/vault/design/<folder> on the slot (replaces what was there)
#   demo.sh portfolio <1|2> "<what it is>" <look> <look>...
#                        the looks side by side, each live on the mockup in a frame, with "Use this one": the owner's
#                        pick becomes the mockup's look at once. `off` is the app as built.
#   demo.sh clear <1|2>                          take the slot down (archive the folder separately, see the Designer role)
#   demo.sh list
#
# Demo 1 opens on <API port + 52>, demo 2 on <API port + 53> (served locally on <API port + 46/47>), beside the mockup
# on <API port + 51>: the same three ports in every project.
set -euo pipefail
MIRRORS="$HOME/.hermes/scripts/review-mirrors.conf"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
die() { echo "demo: $*" >&2; exit 1; }
api=$(grep -m1 '^API_SERVER_PORT=' "$HOME/.hermes/.env" 2>/dev/null | cut -d= -f2)
[ -n "$api" ] || die "can't find API_SERVER_PORT in ~/.hermes/.env"
slot_port() { echo $((api + 45 + $1)); }

view_port() { echo $((api + 51 + $1)); }
drop_mirror() { [ -f "$MIRRORS" ] && sed -i "/^$(view_port "$1") /d" "$MIRRORS" || true; }

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
    drop_mirror "$n"; echo "$(view_port "$n") $port demo $n: ${what//$'\n'/ }" >> "$MIRRORS"
    systemctl --user restart feedback-inbox
    echo "demo $n: $what → :$(view_port "$n") (serving $dir)" ;;
  portfolio)
    n="${2:?slot 1 or 2}"; what="${3:?what it is}"; shift 3; [ $# -ge 1 ] || die "name at least one look"
    [[ "$n" =~ ^[12]$ ]] || die "slot is 1 or 2"
    folder="portfolio-$n"; out="$HOME/vault/design/$folder"; mkdir -p "$out"
    /usr/bin/python3 - "$out/index.html" "$what" "$((api + 51))" "$@" <<'PY' || die "couldn't write the portfolio"
import html, json, pathlib, re, sys
out, what, mport, looks = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
V = pathlib.Path.home() / "vault" / "design" / "variants"
cards = []
for lk in looks:
    if lk != "off" and not (re.fullmatch(r"[\w-]+", lk) and (V / lk).is_dir()):
        sys.exit(f"demo: no look {lk} under vault/design/variants")
    note = V / lk / "note.md"
    lines = [l.strip("# ").strip() for l in note.read_text().splitlines() if l.strip() and not l.startswith("---")] if note.exists() else []
    page = (V / lk / "page.txt").read_text().strip() if (V / lk / "page.txt").exists() else "/"
    title = "As built" if lk == "off" else (lines[0] if lines else lk)
    why = "The app as it is now." if lk == "off" else " ".join(lines[1:3])
    cards.append({"look": lk, "title": title, "why": why, "page": page or "/"})
data = json.dumps({"mport": mport, "cards": cards}).replace("<", "\\u003c")
pathlib.Path(out).write_text(f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(what)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="style.css">
<style>
body{{margin:0;background:#0f1013;color:#e8e8ea;font:14px/1.45 system-ui,sans-serif}}
h1{{font-size:18px;margin:56px 24px 4px}} p.sub{{margin:0 24px 18px;color:#9a9da6}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:18px;padding:0 24px 40px}}
.card{{background:#17181c;border:1px solid #2a2c33;border-radius:12px;overflow:hidden}}
.frame{{position:relative;height:300px;overflow:hidden;background:#fff}}
.frame iframe{{position:absolute;left:0;top:0;width:1280px;height:880px;border:0;transform:scale(.34);transform-origin:0 0}}
.meta{{padding:12px 14px}} .meta b{{font-size:15px}} .meta p{{margin:4px 0 10px;color:#a6a9b2}}
.meta button{{background:#3d6bff;color:#fff;border:0;border-radius:8px;padding:7px 12px;font-weight:600;cursor:pointer}}
.meta .try{{background:none;color:#8fb0ff;padding:7px 4px;margin-left:8px;font-weight:500}} .done{{outline:2px solid #3d6bff}}
.live{{position:fixed;inset:0;z-index:2147483000;display:none;flex-direction:column;background:#0f1013}}
.live.on{{display:flex}} .live .bar{{display:flex;align-items:center;gap:10px;padding:8px 14px;border-bottom:1px solid #2a2c33}}
.live .bar b{{flex:1}} .live .bar button{{border:0;border-radius:8px;padding:6px 12px;font-weight:600;cursor:pointer}}
.live .use{{background:#3d6bff;color:#fff}} .live .x{{background:#23262f;color:#e8e8ea}} .live iframe{{flex:1;border:0;background:#fff}}
</style></head><body data-live="reload">
<h1>{html.escape(what)}</h1><p class="sub">Each one is the live mockup with that look. "Use this one" puts it on the mockup.</p>
<div class="grid" id="g"></div>
<div class="live"><div class="bar"><b></b><button class="use">Use this one</button><button class="x">Close (Esc)</button></div><iframe></iframe></div>
<script>
const D = {data};
const host = location.hostname, mk = `${{location.protocol}}//${{host}}:${{D.mport}}`;
const g = document.getElementById("g");
D.cards.forEach((c) => {{
  const el = document.createElement("div"); el.className = "card";
  const src = `${{mk}}${{c.page}}${{c.page.includes("?") ? "&" : "?"}}__variant=${{c.look}}&__shot=1&__nooverlay=1`;
  el.innerHTML = `<div class="frame"><iframe loading="lazy" tabindex="-1"></iframe></div><div class="meta"><b></b><p></p>
    <button class="pick">Use this one</button><button class="try">Try it live</button></div>`;
  el.querySelector("iframe").src = src; el.querySelector("b").textContent = c.title; el.querySelector("p").textContent = c.why;
  const pick = async (btn) => {{
    const r = await fetch("/__mark/pick-look", {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{look: c.look}})}});
    if (!r.ok) {{ btn.textContent = "Couldn't set it"; return; }}
    document.querySelectorAll(".card").forEach((x) => {{ x.classList.remove("done"); x.querySelector(".pick").textContent = "Use this one"; }});
    el.classList.add("done"); btn.textContent = "On the mockup now";
    setTimeout(() => {{ location.href = mk + "/"; }}, 400);       // straight to the mockup, now showing it
  }};
  el.querySelector(".pick").onclick = (e) => pick(e.target);
  // Try it live: the look full-window, right here on the demo (the app clickable inside it), so the nav and the
  // pick stay where they were. The mockup itself keeps showing the working look until "Use this one".
  el.querySelector(".try").onclick = () => {{
    live.querySelector("b").textContent = c.title;
    live.querySelector("iframe").src = src.replace("&__shot=1", "");
    live.querySelector(".use").textContent = "Use this one";
    live.querySelector(".use").onclick = (e) => pick(e.target);
    live.classList.add("on");
  }};
  g.appendChild(el);
}});
const live = document.querySelector(".live");
const closeLive = () => {{ live.classList.remove("on"); live.querySelector("iframe").src = "about:blank"; }};
live.querySelector(".x").onclick = closeLive;
addEventListener("keydown", (e) => {{ if (e.key === "Escape") closeLive(); }});
</script></body></html>""", encoding="utf-8")
PY
    exec "$0" show "$n" "$folder" "$what" ;;
  clear)
    n="${2:?slot 1 or 2}"; [[ "$n" =~ ^[12]$ ]] || die "slot is 1 or 2"
    systemctl --user disable -q --now "design-demo-$n" 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/design-demo-$n.service"; systemctl --user daemon-reload
    drop_mirror "$n"; systemctl --user restart feedback-inbox
    echo "demo $n cleared" ;;
  list)
    for n in 1 2; do
      p=$(slot_port "$n"); line=$(grep "^$(view_port "$n") $p " "$MIRRORS" 2>/dev/null | cut -d' ' -f3- || true)
      echo "demo $n  :$(view_port "$n")  ${line:-free}"
    done ;;
  *) sed -n '2,16p' "$0"; exit 1 ;;
esac
