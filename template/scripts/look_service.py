"""The Designer's eyes: one warm headless browser the feedback inbox keeps open, so seeing, mapping and auditing a page
takes a fraction of a second instead of starting Chrome every time. Imported by feedback-inbox.py (POST /look,
localhost only); `look.py` is the command the bots call.

  {"op": "see",   target, route, look, selector, width, height, ask} -> {"path", "eye", "url"} a screenshot, and with
                                                                     "ask" the model's short answer about it (seconds)
  {"op": "map",   target, route, selector, depth}                 -> {"text": outline}        the page's structure
  {"op": "audit", target, route, selector, draw}                  -> {"issues": [...], "path"} spacing and alignment
  {"op": "click", selector} / {"op": "go", route} / {"op": "back"} -> {"url"}                  walk the app like a user
  {"op": "eval",  js}                                              -> {"value"}
target: mockup | demo1 | demo2 | an http://127.0.0.1 URL. Every op but click/back/eval opens the page fresh (a design
edit has to show), unless "keep": true (to look at where a click led).
"""
import json
import pathlib
import threading
import time

HOME = pathlib.Path.home()
SHOTS = HOME / "scratch" / "look"
LOCK = threading.Lock()
STATE = {"url": None, "size": None}
SESSION = "look"

# The page's structure, compact: landmarks, headings, controls, images and named boxes, each with a short unique
# selector, its box and its text. Enough to edit by selector without reading the HTML.
MAP_JS = r"""
((scope, depth) => {
  const root = scope ? document.querySelector(scope) : document.body;
  if (!root) return 'no element matches ' + scope;
  const uniq = (el) => {
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id);
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      let p = e.tagName.toLowerCase();
      if (e.id) { parts.unshift('#' + CSS.escape(e.id)); break; }
      const cls = [...e.classList].filter(c => !/^(is-|has-|active|hover|focus|look-)/.test(c)).slice(0, 2);
      if (cls.length) p += '.' + cls.map(c => CSS.escape(c)).join('.');
      const same = e.parentElement ? [...e.parentElement.children].filter(c => c.tagName === e.tagName &&
        (!cls.length || cls.every(k => c.classList.contains(k)))) : [];
      if (same.length > 1) p += ':nth-child(' + ([...e.parentElement.children].indexOf(e) + 1) + ')';
      parts.unshift(p);
      if (document.querySelectorAll(parts.join(' > ')).length === 1) break;
    }
    return parts.join(' > ');
  };
  const KEEP = /^(header|nav|main|section|aside|footer|form|dialog|h[1-6]|button|a|input|select|textarea|img|svg|label|ul|ol|table)$/;
  const lines = [];
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const own = (el) => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
  const walk = (el, d) => {
    if (lines.length > 160 || d > depth) return;
    for (const c of el.children) {
      if (c.shadowRoot && c !== root) continue;
      if (/^(script|style|link|template|noscript)$/i.test(c.tagName) || !vis(c)) continue;
      const tag = c.tagName.toLowerCase();
      const named = c.id || (c.classList.length && c.children.length > 0);
      if (KEEP.test(tag) || named || own(c)) {
        const r = c.getBoundingClientRect();
        const txt = (own(c) || (/^(button|a|label|h[1-6])$/.test(tag) ? c.textContent.trim() : '') ||
                     c.getAttribute('placeholder') || c.getAttribute('aria-label') || c.getAttribute('alt') || '').replace(/\s+/g, ' ').slice(0, 48);
        lines.push('  '.repeat(d) + uniq(c) + `  [${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}]` + (txt ? '  "' + txt + '"' : ''));
        walk(c, d + 1);
      } else walk(c, d);
    }
  };
  walk(root, 0);
  return location.pathname + location.hash + '  ' + innerWidth + 'x' + innerHeight + '\n' + lines.join('\n');
})
"""

# What a sharp eye catches: gaps that differ between siblings, edges and centres that almost line up, spacing off the
# 4 px grid, overflow and overlap, too many type sizes. Returns issues, and with draw=true marks them on the page.
AUDIT_JS = r"""
((scope, draw) => {
  const root = scope ? document.querySelector(scope) : document.body;
  if (!root) return {issues: ['no element matches ' + scope]};
  const issues = [], marks = [];
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && s.position !== 'fixed'; };
  const name = (el) => { if (el.id) return '#' + el.id; const c = [...el.classList].slice(0, 2).join('.');
    return el.tagName.toLowerCase() + (c ? '.' + c : ''); };
  const add = (msg, els) => { issues.push(msg); els.forEach(e => marks.push([e.getBoundingClientRect(), msg])); };
  const all = [root, ...root.querySelectorAll('*')].filter(e => !e.shadowRoot && !/^(script|style|svg|path|br|option)$/i.test(e.tagName) && vis(e));
  for (const box of all) {
    const kids = [...box.children].filter(vis);
    if (kids.length < 2 || kids.length > 40) continue;
    const rs = kids.map(k => k.getBoundingClientRect());
    const row = rs.every(r => Math.abs(r.top - rs[0].top) < 4 || Math.abs((r.top + r.height / 2) - (rs[0].top + rs[0].height / 2)) < 10);
    if (row) {
      const gaps = rs.slice(1).map((r, i) => Math.round(r.left - rs[i].right)).filter(g => g >= 0);
      if (gaps.length > 1 && Math.max(...gaps) - Math.min(...gaps) > 2) add(`${name(box)}: uneven gaps in a row (${gaps.join(', ')} px)`, kids);
      const mids = rs.map(r => r.top + r.height / 2), off = Math.max(...mids) - Math.min(...mids);
      if (off > 1.5 && off < 12) add(`${name(box)}: items in a row not vertically centred (off by ${off.toFixed(1)} px)`, kids);
    } else {
      const gaps = rs.slice(1).map((r, i) => Math.round(r.top - rs[i].bottom)).filter(g => g >= 0 && g < 200);
      if (gaps.length > 1 && Math.max(...gaps) - Math.min(...gaps) > 2) add(`${name(box)}: uneven vertical gaps (${gaps.join(', ')} px)`, kids);
      const lefts = rs.map(r => Math.round(r.left)), spread = Math.max(...lefts) - Math.min(...lefts);
      if (spread > 0.5 && spread <= 8) add(`${name(box)}: left edges almost aligned (off by ${spread} px)`, kids);
    }
  }
  const off = new Map();
  for (const el of all) {
    const s = getComputedStyle(el);
    for (const p of ['marginTop', 'marginBottom', 'paddingTop', 'paddingLeft', 'gap']) {
      const v = parseFloat(s[p]); if (v > 0 && v % 4 !== 0 && v % 2 !== 0) off.set(name(el) + ' ' + p, v);
    }
    if (el.scrollWidth > el.clientWidth + 1 && !/(auto|scroll)/.test(s.overflowX) && s.textOverflow !== 'ellipsis' && el.clientWidth > 0)
      add(`${name(el)}: content overflows its box by ${el.scrollWidth - el.clientWidth} px`, [el]);
    if (/^(button|a)$/i.test(el.tagName) && el.getBoundingClientRect().height < 28 && el.textContent.trim())
      issues.push(`${name(el)}: small target (${Math.round(el.getBoundingClientRect().height)} px tall)`);
  }
  if (off.size) issues.push('off the 4 px grid: ' + [...off].slice(0, 8).map(([k, v]) => `${k} ${v}`).join('; ') + (off.size > 8 ? ` (+${off.size - 8})` : ''));
  if (document.documentElement.scrollWidth > innerWidth + 1) issues.push(`the page scrolls sideways (${document.documentElement.scrollWidth - innerWidth} px too wide)`);
  const sizes = new Set(all.filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())).map(e => getComputedStyle(e).fontSize));
  const scale = [...sizes].map(parseFloat).sort((a, b) => a - b);
  if (scale.length > 6) issues.push(`${scale.length} type sizes in use: ${scale.join(', ')} px`);
  if (draw && marks.length) {
    const layer = document.createElement('div'); layer.id = '__look_audit';
    layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483646';
    marks.slice(0, 40).forEach(([r, msg], i) => { const b = document.createElement('div');
      b.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;outline:2px solid rgba(255,40,80,.9);background:rgba(255,40,80,.08)`;
      layer.appendChild(b); });
    document.body.appendChild(layer);
  }
  return {issues: issues.slice(0, 30), count: issues.length, typeScale: scale};
})
"""


# One screen of the running app as static markup: the body without scripts or handlers, every same-origin image
# and stylesheet listed (the caller copies them), form values kept as attributes so the page looks as it was.
CAPTURE_JS = r"""
(() => {
  const body = document.body.cloneNode(true);
  body.querySelectorAll('script,noscript,template,iframe').forEach(e => e.remove());
  const live = document.body.querySelectorAll('input,textarea,select');
  const copy = body.querySelectorAll('input,textarea,select');
  live.forEach((el, i) => { const c = copy[i]; if (!c) return;
    if (el.tagName === 'TEXTAREA') c.textContent = el.value;
    else if (el.tagName === 'SELECT') [...c.options].forEach((o, k) => o.toggleAttribute('selected', k === el.selectedIndex));
    else if (el.type === 'checkbox' || el.type === 'radio') c.toggleAttribute('checked', el.checked);
    else c.setAttribute('value', el.value); });
  const canv = document.body.querySelectorAll('canvas'), ccopy = body.querySelectorAll('canvas');
  canv.forEach((c, i) => { try { const img = document.createElement('img'); img.src = c.toDataURL('image/png');
    img.width = c.width; img.height = c.height; img.className = c.className; ccopy[i].replaceWith(img); } catch (e) {} });
  const imgs = new Set(), clickable = [];
  body.querySelectorAll('*').forEach(el => {
    for (const a of [...el.attributes]) {
      if (/^on/i.test(a.name)) { if (!clickable.includes(el)) clickable.push(el); el.removeAttribute(a.name); }
      else if ((a.name === 'href' || a.name === 'src' || a.name === 'action') && /^\s*javascript:/i.test(a.value)) el.setAttribute(a.name, '#');
    }
    if (el.tagName === 'IMG' && el.getAttribute('src') && !el.src.startsWith('data:')) { imgs.add(el.src); el.setAttribute('src', el.src); }
    const bg = el.getAttribute('style') || '';
    (bg.match(/url\((['"]?)([^'")]+)\1\)/g) || []).forEach(u => { const m = /url\((['"]?)([^'")]+)\1\)/.exec(u);
      if (m && !m[2].startsWith('data:')) imgs.add(new URL(m[2], location.href).href); });
  });
  clickable.forEach(el => el.setAttribute('data-was-clickable', ''));
  const sheets = [...document.styleSheets].map(s => s.href).filter(h => h && h.startsWith(location.origin));
  const inline = [...document.querySelectorAll('style')].map(s => s.textContent).join('\n');
  return {html: body.innerHTML, bodyClass: document.body.className, htmlClass: document.documentElement.className,
          htmlAttrs: [...document.documentElement.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value]),
          title: document.title, sheets, inline, imgs: [...imgs].filter(u => u.startsWith(location.origin)).slice(0, 120),
          origin: location.origin, clickable: clickable.length};
})()
"""

# A prototype page's structure, edited in the browser and handed back as the page's markup (look-apply --dir with
# --move/--text/--insert/--attr/--link): the same edits as on the app, saved into the page file.
EDIT_JS = r"""
((ops) => {
  const out = document.querySelector('[data-outlet]');
  if (!out) return {error: 'not a prototype page (no [data-outlet])'};
  const q = s => { try { return out.querySelector(s); } catch (e) { return null; } };
  const put = (node, where, ref) => { if (where === 'before') ref.before(node); else if (where === 'after') ref.after(node);
    else if (where === 'start') ref.prepend(node); else ref.append(node); };
  const status = [];
  for (const op of ops) {
    if (op.op === 'move') { const n = q(op.sel), r = q(op.ref); if (!n || !r) { status.push('missing ' + (!n ? op.sel : op.ref)); continue; } put(n, op.where, r); }
    else if (op.op === 'text') { const n = q(op.sel); if (!n) { status.push('missing ' + op.sel); continue; } n.textContent = op.text; }
    else if (op.op === 'attr') { const n = q(op.sel); if (!n) { status.push('missing ' + op.sel); continue; }
      if (op.value === null) n.removeAttribute(op.name); else n.setAttribute(op.name, op.value); }
    else if (op.op === 'repeat') { const all = out.querySelectorAll(op.sel); if (!all.length) { status.push('missing ' + op.sel); continue; }
      let last = all[all.length - 1]; const want = (op.values && op.values.length) || op.n;
      for (let i = 0; i < want; i++) { const c = all[0].cloneNode(true); c.removeAttribute('id');
        if (op.values && op.values[i] != null) { const t = op.child ? c.querySelector(op.child) : c; if (t) t.textContent = op.values[i]; }
        last.after(c); last = c; } }
    else if (op.op === 'insert') { const r = q(op.ref); if (!r) { status.push('missing ' + op.ref); continue; }
      const t = document.createElement('template'); t.innerHTML = op.html; put(t.content, op.where, r); }
    status.push('ok');
  }
  return {html: out.innerHTML, status};
})
"""


def _fetch(url, limit=8_000_000):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "look-clone"}), timeout=20) as r:
        data = r.read(limit + 1)
    return None if len(data) > limit else data


def clone(d, browse, base, ev):
    """Capture the app's screens from the mockup into a prototype folder (look.py proto clone)."""
    import hashlib
    import re as _re
    folder = pathlib.Path(d["folder"])
    screens = d["screens"]                                   # [[name, route], ...]
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    (folder / "assets").mkdir(exist_ok=True)
    routes, report, first = {}, [], None
    for name, route in screens:
        routes[route] = name
    css_seen, css_parts, assets = set(), [], {}
    for name, route in screens:
        dd = dict(d, route=route, look=d.get("look") or "off")
        browse(SESSION, "open", _target_url(dd, base))
        browse(SESSION, "wait", str(int(d.get("settle") or 1500)))
        cap = ev(CAPTURE_JS)
        if not isinstance(cap, dict) or "html" not in cap:
            report.append(f"{name}: couldn't capture ({str(cap)[:120]})")
            continue
        first = first or cap
        html = cap["html"]
        for href in cap.get("sheets") or []:
            if href in css_seen:
                continue
            css_seen.add(href)
            try:
                css = (_fetch(href) or b"").decode("utf-8", "replace")
            except Exception as e:
                report.append(f"stylesheet {href}: {e}")
                continue
            css_parts.append(f"/* from {href.split('?')[0]} */\n{css}")
        if cap.get("inline"):
            css_parts.append("/* inline styles */\n" + cap["inline"])
        for u in cap.get("imgs") or []:
            if u not in assets and len(assets) < 120:
                try:
                    data = _fetch(u, 3_000_000)
                except Exception:
                    data = None
                if data:
                    ext = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"GIF8": ".gif", b"RIFF": ".webp", b"<svg": ".svg"}
                    e = next((x for k, x in ext.items() if data.startswith(k)), ".img")
                    fn = "assets/" + hashlib.sha1(u.encode()).hexdigest()[:12] + e
                    (folder / fn).write_bytes(data)
                    assets[u] = fn
            if u in assets:                                      # markup writes & as &amp; inside attributes
                html = html.replace(u.replace("&", "&amp;"), assets[u]).replace(u, assets[u])
        html = html.replace(cap["origin"] + "/", "")             # what's left same-origin: relative to the prototype
        for rt, nm in sorted(routes.items(), key=lambda x: -len(x[0])):   # links between captured screens
            html = _re.sub(r'href="' + _re.escape(rt) + r'"', f'href="#/{"" if nm == "home" else nm}"', html)
        (folder / "pages" / f"{name}.html").write_text(html, encoding="utf-8")
        report.append(f"{name} ({route}): {len(html) // 1024} KB, {cap.get('clickable', 0)} clickable elements to wire")
    (folder / "app.css").write_text("\n\n".join(css_parts), encoding="utf-8")
    if first:
        attrs = " ".join(f'{k}="{v}"' for k, v in first.get("htmlAttrs") or [])
        (folder / "index.html").write_text(
            f'<!doctype html>\n<html lang="en" class="{first.get("htmlClass", "")}" {attrs}><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{first.get("title", "")}</title>\n'
            '<link rel="stylesheet" href="app.css"><link rel="stylesheet" href="style.css">\n'
            '<script src="kit.js" defer></script></head>\n'
            f'<body class="{first.get("bodyClass", "")}" data-outlet></body></html>\n', encoding="utf-8")
    return {"report": report, "assets": len(assets), "css_kb": sum(len(c) for c in css_parts) // 1024}


def _target_url(d, base):
    t = str(d.get("target") or "mockup")
    port = {"mockup": base + 51, "demo1": base + 52, "demo2": base + 53}.get(t)
    if port is None:
        if not t.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("target is mockup, demo1, demo2 or a local URL")
        return t
    route = str(d.get("route") or "/")
    if not route.startswith(("/", "#")):
        route = "/" + route
    path, _, frag = route.partition("#")
    q = "__nooverlay=1"
    if d.get("look") and t == "mockup":
        q += "&__variant=" + str(d["look"])
    return f"http://127.0.0.1:{port}{path or '/'}?{q}" + (f"#{frag}" if frag else "")


def _shot_path():
    SHOTS.mkdir(parents=True, exist_ok=True)
    old = sorted(SHOTS.glob("*.jpg"))
    for f in old[:-40]:                                  # keep the last 40
        f.unlink(missing_ok=True)
    return SHOTS / f"{time.strftime('%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.jpg"


def _res(r):
    """agent-browser's eval answers {"origin": ..., "result": value}: the value."""
    return r.get("result") if isinstance(r, dict) and "result" in r else r


def handle(d, browse, base, eye=None):
    """browse(session, *args) runs agent-browser (feedback-inbox.browser_tools); eye(path, question) asks the model
    about a screenshot (feedback-inbox.eye) when the caller passes "ask"."""
    if browse is None:
        return {"error": "the headless browser isn't installed yet (the browser tool installs it on first use)"}
    op = d.get("op")
    ev = lambda js: _res(browse(SESSION, "eval", js))
    with LOCK:
        t0 = time.time()
        size = (int(d.get("width") or 1440), int(d.get("height") or 900))
        if STATE["size"] != size:
            browse(SESSION, "set", "viewport", str(size[0]), str(size[1]))
            STATE["size"] = size
        if op in ("see", "map", "audit", "go", "edit") and not d.get("keep"):
            url = _target_url(d, base)
            # The same address again (or one that differs only after #) doesn't reload in Chrome: reload it, so a
            # look always starts from a fresh page, not from whatever the last click left open.
            if STATE["url"] and STATE["url"].split("#")[0] == url.split("#")[0]:
                browse(SESSION, "open", url)
                browse(SESSION, "reload")
            else:
                browse(SESSION, "open", url)
            browse(SESSION, "wait", str(int(d.get("settle") or 450)))
            STATE["url"] = url
        out = {}
        if op == "clone":
            out.update(clone(d, browse, base, ev))
        elif op == "edit":
            res = ev(f"{EDIT_JS}({json.dumps(d.get('ops') or [])})")
            out.update(res if isinstance(res, dict) else {"error": str(res)[:300]})
        elif op == "click":
            browse(SESSION, "click", str(d["selector"]))
            browse(SESSION, "wait", "400")
        elif op == "back":
            browse(SESSION, "back")
            browse(SESSION, "wait", "400")
        elif op == "eval":
            out["value"] = ev(str(d["js"]))
        elif op == "map":
            out["text"] = ev(f"{MAP_JS}({json.dumps(d.get('selector') or '')}, {int(d.get('depth') or 6)})")
        elif op == "audit":
            res = ev(f"{AUDIT_JS}({json.dumps(d.get('selector') or '')}, {json.dumps(bool(d.get('draw')))})")
            out.update(res if isinstance(res, dict) else {"issues": [str(res)]})
            if d.get("draw"):
                p = _shot_path()
                browse(SESSION, "screenshot", str(p), "--screenshot-format", "jpeg", "--screenshot-quality", "72")
                ev("document.getElementById('__look_audit')?.remove()")
                out["path"] = str(p) if p.exists() else None
        if op == "see":
            p = _shot_path()
            args = ["screenshot"] + ([str(d["selector"])] if d.get("selector") else []) + [str(p)]
            browse(SESSION, *args, "--screenshot-format", "jpeg", "--screenshot-quality", "72")
            out["path"] = str(p) if p.exists() else None
            if not out["path"]:
                out["error"] = "no screenshot (does the selector match?)"
            elif d.get("ask") and eye:
                t1 = time.time()
                out["eye"] = eye(out["path"], str(d["ask"]))
                out["eye_ms"] = int((time.time() - t1) * 1000)
        if d.get("report"):
            out["report"] = ev("window.__lookRuntime ? window.__lookRuntime.report() : []") or []
        out["url"] = ev("location.pathname + location.hash") or ""
        out["ms"] = int((time.time() - t0) * 1000)
        return out
