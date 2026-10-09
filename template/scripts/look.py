#!/usr/bin/python3
"""look: the Designer's eyes and its prototype kit. Every read goes through one warm browser (the feedback inbox keeps
it open), so it answers in about a second; `see --ask` has the model look at the screenshot and answer in about 3 s
(Hermes's vision_analyze is a slow second call on this provider).

  look see [<selector>] [--ask '<question>'] [--on '<route>'] [--demo 1|2] [--look <name>] [--size WxH] [--keep]
        a screenshot of the mockup (or a demo), cropped to <selector> if given, and with --ask the answer to your
        question about it, from the model looking at it (about 3 s): "Is the button under the title? Gaps even?".
        --on '#/deck/Burn' opens that screen; --keep looks at where the last click led instead of reloading.
  look map [<selector>] [--on ...] [--demo ...] [--depth N]
        the page's structure: every landmark, heading, control and named box with a short unique selector, its box
        [x,y wxh] and its text. Use those selectors in look-apply.py.
  look audit [<selector>] [--on ...] [--demo ...] [--draw]
        what a sharp eye catches: uneven gaps, edges and centres that almost line up, spacing off the 4 px grid,
        overflow, small targets, too many type sizes. --draw also saves a screenshot with the problems outlined.
  look click '<selector>'  |  look back  |  look go '<route>' [--demo ...]
        walk the app (or a prototype) like a user, then `look see --keep`.
  look proto new <name> [--title 'App name'] [--pages home,deck,settings]
        a navigable skeleton site in vault/design/<name>/: shell and nav, a page per screen, sample data, tokens on a
        4 px grid, and kit.js (links, lists from data, tabs, dialogs, toasts, forms: all simulated, no scripts to
        write). Serve it as the mockup (mockup.sh proto <name>) or on a demo (demo.sh show 1 <name> "...").
  look proto page <name> <page> [--title 'Page title']      add a screen
"""
import argparse
import json
import pathlib
import shutil
import sys
import urllib.request

HOME = pathlib.Path.home()
SCRIPTS = HOME / ".hermes" / "scripts"
DESIGN = HOME / "vault" / "design"


def call(body):
    port = next((l.split("=", 1)[1].strip() for l in (HOME / ".hermes" / ".env").read_text().splitlines()
                 if l.startswith("API_SERVER_PORT=")), "")
    req = urllib.request.Request(f"http://127.0.0.1:{int(port) + 99}/look", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=90).read())
    except Exception as e:
        return {"error": f"the inbox's browser didn't answer: {e}"}


def target(a):
    return f"demo{a.demo}" if getattr(a, "demo", None) else "mockup"


TOKENS = """/* Tokens: the one place colours, type and spacing are set. Spacing is a 4 px grid: use the --s-* steps only. */
:root {
  --bg: #0f1013; --surface: #17181c; --surface-2: #1e2026; --line: #2a2c33;
  --text: #e8e8ea; --muted: #9a9da6; --accent: #3d6bff; --accent-text: #fff; --danger: #ff4d5e;
  --font: system-ui, -apple-system, "Segoe UI", sans-serif; --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  --t-xs: 12px; --t-sm: 14px; --t-md: 16px; --t-lg: 20px; --t-xl: 28px;
  --s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px; --s-5: 24px; --s-6: 32px; --s-7: 48px;
  --r-sm: 6px; --r-md: 10px; --r-lg: 14px; --w-page: 1120px;
}
"""

STYLE = """/* Layout and components, built on tokens.css. Edit freely; keep to the --s-* steps. */
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: var(--t-md)/1.5 var(--font); }
a { color: inherit; }
[hidden] { display: none !important; }
.app-head { display: flex; align-items: center; gap: var(--s-5); height: 56px; padding: 0 var(--s-5);
  border-bottom: 1px solid var(--line); background: var(--surface); position: sticky; top: 0; z-index: 10; }
.brand { font-weight: 700; text-decoration: none; padding: var(--s-2) 0; }
.app-nav { display: flex; gap: var(--s-1); }
.app-nav a { text-decoration: none; color: var(--muted); padding: var(--s-2) var(--s-3); border-radius: var(--r-sm); }
.app-nav a:hover { color: var(--text); background: var(--surface-2); }
.app-nav a.is-active { color: var(--text); background: var(--surface-2); }
.app-main { max-width: var(--w-page); margin: 0 auto; padding: var(--s-6) var(--s-5); }
h1 { font-size: var(--t-xl); line-height: 1.2; margin: 0 0 var(--s-2); }
h2 { font-size: var(--t-lg); margin: var(--s-6) 0 var(--s-3); }
p { margin: 0 0 var(--s-4); }
.muted { color: var(--muted); }
.stack { display: flex; flex-direction: column; gap: var(--s-4); }
.row { display: flex; align-items: center; gap: var(--s-3); }
.row.spread { justify-content: space-between; margin-bottom: var(--s-2); }
.row > h1, .row > h2 { margin: 0; }
.back { display: inline-block; margin-bottom: var(--s-3); color: var(--muted); text-decoration: none; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--s-4); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-md); padding: var(--s-4); }
.card h3 { margin: 0 0 var(--s-1); font-size: var(--t-md); }
.btn { display: inline-flex; align-items: center; gap: var(--s-2); height: 36px; padding: 0 var(--s-4); border-radius: var(--r-sm);
  border: 1px solid var(--line); background: var(--surface-2); color: var(--text); font: inherit; font-size: var(--t-sm);
  cursor: pointer; text-decoration: none; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-text); font-weight: 600; }
input, select, textarea { height: 36px; padding: 0 var(--s-3); border-radius: var(--r-sm); border: 1px solid var(--line);
  background: var(--bg); color: var(--text); font: inherit; font-size: var(--t-sm); }
textarea { height: auto; padding: var(--s-2) var(--s-3); }
.tabs { display: flex; gap: var(--s-1); border-bottom: 1px solid var(--line); margin-bottom: var(--s-4); }
.tabs [data-tab] { background: none; border: 0; color: var(--muted); padding: var(--s-2) var(--s-3); cursor: pointer; font: inherit; }
.tabs [data-tab].is-active { color: var(--text); box-shadow: inset 0 -2px var(--accent); }
.modal { position: fixed; inset: 0; background: rgba(0, 0, 0, .55); display: grid; place-items: center; z-index: 50; }
.modal > .card { width: min(480px, calc(100vw - var(--s-6))); }
.toast { position: fixed; bottom: var(--s-5); left: 50%; transform: translateX(-50%); background: var(--surface-2);
  border: 1px solid var(--line); border-radius: var(--r-md); padding: var(--s-2) var(--s-4); z-index: 60; }
"""

INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="style.css"></head>
<body>
<header class="app-head"><a class="brand" href="#/">{title}</a>
  <nav class="app-nav">{nav}</nav></header>
<main class="app-main" data-outlet></main>
<div class="toast" hidden></div>
<script src="kit.js"></script>
</body></html>
"""

HOME_PAGE = """<div class="row spread"><h1>{title}</h1><button class="btn primary" data-open="#new-item">New item</button></div>
<p class="muted">The first screen. Items below come from data.json; click one to open its page.</p>
<div class="grid" data-each="items">
  <a class="card" href="#/item/{{{{name}}}}" style="text-decoration:none"><h3>{{{{name}}}}</h3><p class="muted">{{{{note}}}}</p></a>
</div>
<div class="modal" id="new-item" hidden data-panel-root><form class="card stack" data-toast="Item created (simulated)">
  <h2 style="margin:0">New item</h2><input placeholder="Name"><div class="row"><button class="btn primary">Create</button>
  <button class="btn" type="button" data-close>Cancel</button></div></form></div>
"""

ITEM_PAGE = """<section data-find="items name $1">
  <a href="#/" class="back">&larr; Back</a>
  <h1>{{name}}</h1><p class="muted">{{note}}</p>
  <div class="tabs"><button data-tab="item:overview" class="is-active">Overview</button><button data-tab="item:more">More</button></div>
  <div data-panel="item:overview"><p>Overview of {{name}}.</p></div>
  <div data-panel="item:more" hidden><p>More about {{name}}.</p></div>
</section>
"""

PAGE = """<h1>{title}</h1>
<p class="muted">What this screen holds.</p>
"""

DATA = {"app": {"name": ""}, "items": [{"name": "First", "note": "A sample item"}, {"name": "Second", "note": "Another one"},
                                       {"name": "Third", "note": "And a third"}]}


def proto_new(a):
    d = DESIGN / a.name
    if d.exists():
        print(f"look: {d} exists already", file=sys.stderr)
        return 2
    pages = [p.strip() for p in (a.pages or "home").split(",") if p.strip()]
    if "home" not in pages:
        pages.insert(0, "home")
    (d / "pages").mkdir(parents=True)
    title = a.title or a.name.replace("-", " ").title()
    nav = "".join(f'<a href="#/{"" if p == "home" else p}" data-route="{p}">{p.replace("-", " ").title()}</a>' for p in pages)
    (d / "index.html").write_text(INDEX.format(title=title, nav=nav), encoding="utf-8")
    (d / "tokens.css").write_text(TOKENS, encoding="utf-8")
    (d / "style.css").write_text(STYLE, encoding="utf-8")
    shutil.copyfile(SCRIPTS / "proto-kit.js", d / "kit.js")
    data = dict(DATA); data["app"] = {"name": title}
    (d / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (d / "pages" / "home.html").write_text(HOME_PAGE.format(title=title), encoding="utf-8")
    (d / "pages" / "item.html").write_text(ITEM_PAGE, encoding="utf-8")
    for p in pages:
        if p not in ("home",):
            (d / "pages" / f"{p}.html").write_text(PAGE.format(title=p.replace("-", " ").title()), encoding="utf-8")
    (d / "map.md").write_text(f"# {title}: prototype map\n\nScreens: {', '.join(pages)} (+ item, a detail page).\n"
                              "Files: index.html (shell, nav), pages/<screen>.html, data.json, tokens.css, style.css, kit.js (don't edit).\n",
                              encoding="utf-8")
    print(f"prototype {a.name}: vault/design/{a.name}/ with {', '.join(pages)} + item. "
          f"Serve it: mockup.sh proto {a.name}  (or demo.sh show 1 {a.name} \"{title} prototype\")")
    return 0


def proto_page(a):
    d = DESIGN / a.name
    f = d / "pages" / f"{a.page}.html"
    if not d.is_dir() or f.exists():
        print(f"look: no prototype {a.name}, or {f.name} exists", file=sys.stderr)
        return 2
    f.write_text(PAGE.format(title=a.title or a.page.replace("-", " ").title()), encoding="utf-8")
    idx = d / "index.html"
    t = idx.read_text(encoding="utf-8")
    link = f'<a href="#/{a.page}" data-route="{a.page}">{(a.title or a.page.replace("-", " ").title())}</a>'
    if "</nav>" in t and f'data-route="{a.page}"' not in t:
        idx.write_text(t.replace("</nav>", link + "</nav>", 1), encoding="utf-8")
    print(f"added pages/{a.page}.html and a nav link")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="look", description="The Designer's eyes (a warm browser) and prototype kit.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def common(p, sel=True):
        if sel:
            p.add_argument("selector", nargs="?", default="")
        p.add_argument("--on", default="/", help="the route to open, e.g. '#/deck/Burn' or '/settings'")
        p.add_argument("--demo", type=int, choices=(1, 2))
        p.add_argument("--look", default="", help="a look other than the mockup's working one")
        p.add_argument("--size", default="1440x900")
        p.add_argument("--keep", action="store_true", help="don't reload: look at where the last click led")
    se = sp.add_parser("see"); common(se); se.add_argument("--ask", default="", help="a question about how it looks")
    m = sp.add_parser("map"); common(m); m.add_argument("--depth", type=int, default=6)
    au = sp.add_parser("audit"); common(au); au.add_argument("--draw", action="store_true")
    c = sp.add_parser("click"); c.add_argument("selector")
    sp.add_parser("back")
    g = sp.add_parser("go"); g.add_argument("route"); g.add_argument("--demo", type=int, choices=(1, 2))
    g.add_argument("--size", default="1440x900")
    e = sp.add_parser("eval"); e.add_argument("js")
    pr = sp.add_parser("proto"); psp = pr.add_subparsers(dest="pcmd", required=True)
    pn = psp.add_parser("new"); pn.add_argument("name"); pn.add_argument("--title", default=""); pn.add_argument("--pages", default="")
    pp = psp.add_parser("page"); pp.add_argument("name"); pp.add_argument("page"); pp.add_argument("--title", default="")
    a = ap.parse_args()

    if a.cmd == "proto":
        return proto_new(a) if a.pcmd == "new" else proto_page(a)
    body = {"op": a.cmd}
    if a.cmd in ("see", "map", "audit"):
        w, _, h = a.size.partition("x")
        body.update(target=target(a), route=a.on, look=a.look, selector=a.selector, width=int(w), height=int(h or 900),
                    keep=a.keep)
        if a.cmd == "map":
            body["depth"] = a.depth
        if a.cmd == "see" and a.ask:
            body["ask"] = a.ask
        if a.cmd == "audit":
            body["draw"] = a.draw
    elif a.cmd == "go":
        w, _, h = a.size.partition("x")
        body.update(target=target(a), route=a.route, width=int(w), height=int(h or 900))
    elif a.cmd == "click":
        body["selector"] = a.selector
    elif a.cmd == "eval":
        body["js"] = a.js
    out = call(body)
    if out.get("error"):
        print(f"look: {out['error']}", file=sys.stderr)
        return 1
    if a.cmd == "map":
        print(out.get("text") or "")
    elif a.cmd == "audit":
        issues = out.get("issues") or []
        print("\n".join(f"- {i}" for i in issues) if issues else "no spacing or alignment problems found")
        if out.get("typeScale"):
            print(f"type sizes: {', '.join(str(s) for s in out['typeScale'])}")
        if out.get("path"):
            print(f"marked up: {out['path']}")
    elif a.cmd == "eval":
        print(json.dumps(out.get("value"))[:4000])
    if out.get("eye"):
        print(out["eye"])
    if out.get("path") and a.cmd == "see":
        print(f"see: {out['path']}" + ("" if out.get("eye") else "  (add --ask '<question>' to have it looked at)"))
    print(f"({out.get('url', '')}, {out.get('ms', 0) / 1000:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
