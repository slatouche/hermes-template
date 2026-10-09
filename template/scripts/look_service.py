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
        if op in ("see", "map", "audit", "go") and not d.get("keep"):
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
        if op == "click":
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
