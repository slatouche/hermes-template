/* layer.js: the design layer, live inside the app (design-view.py adds it to the app's index.html in the mockup).
   It applies the layer's edits on top of the real app and keeps them true while the app redraws and the owner
   navigates; applies new edits the moment they stream in (with a flash on what changed); shows a choice of an
   option set; builds the compact screen map sent with each note; and lets the toolbar pick elements.
   Edits: token, css, move, text, insert, attr, repeat, remove, screen (see design-view.py). Every one is idempotent. */
(function () {
  "use strict";
  if (window.__dv) return;
  var ops = [], options = {}, cfg = { screen: "[data-ui=screen]", nav: "[data-ui=nav]" }, status = {};
  var active = null;                       // {set, choice} being previewed, or null for the mockup itself
  try { active = JSON.parse(sessionStorage.getItem("dv-opt") || "null"); } catch (e) { active = null; }
  // A side-by-side frame names its option in the URL (?dvopt=<set>:<choice>, or ?dvopt=none for the mockup itself)
  // and is left alone by everything else (it never takes over the shared choice).
  var fixed = /[?&]dvopt=([^&#]+)/.exec(location.search);
  if (fixed) { var fv = decodeURIComponent(fixed[1]).split(":"); active = fv[0] === "none" ? null : { set: fv[0], choice: fv[1] }; }
  var behaviors = window.__dvBehaviors = window.__dvBehaviors || {};
  var applying = false, timer = 0, ready = false;

  function q(sel) { try { return document.querySelector(sel); } catch (e) { return null; } }
  function qa(sel) { try { return Array.prototype.slice.call(document.querySelectorAll(sel)); } catch (e) { return []; } }
  function route() { return (location.hash.replace(/\?.*$/, "") || "#/"); }
  function routeOk(op) { return !op.on || op.on === route(); }

  function current() {                     // the mockup's edits, plus the option being previewed
    var list = ops.slice();
    if (active && options[active.set] && options[active.set].choices[active.choice])
      list = list.concat(options[active.set].choices[active.choice].ops);
    return list;
  }

  // ---- styles: tokens and rules, kept last in <head> so they win -------------------------------------------------
  function styles(list) {
    var tok = [], css = [], scr = [];
    list.forEach(function (o) {
      if (o.op === "token") tok.push(o.name + ": " + o.value + ";");
      else if (o.op === "css") css.push(o.on ? scopeRule(o.rule, o.on) : o.rule);
      else if (o.op === "remove") css.push(scopeRule(o.sel + " { display: none !important; }", o.on));
    });
    scr.push("[data-dv-screen]:not(.dv-on) { display: none !important; }");
    scr.push("[data-dv-hide] { display: none !important; }");
    scr.push(".dv-flash { outline: 2px solid #4da3ff !important; outline-offset: 2px; transition: outline-color .6s; }");
    scr.push(".dv-hover { outline: 2px dashed #4da3ff !important; outline-offset: 1px; cursor: crosshair !important; }");
    scr.push(".dv-picked { outline: 2px solid #ff9f1c !important; outline-offset: 1px; }");
    put("dv-tokens", tok.length ? ":root, :root[data-theme], html[data-theme] { " + tok.join(" ") + " }" : "");
    put("dv-css", css.join("\n"));
    put("dv-base", scr.join("\n"));
  }
  function scopeRule(rule, on) {
    if (!on) return rule;
    return rule.replace(/(^|\})\s*([^{}@]+)\{/g, function (m, b, sels) {
      return b + " " + sels.split(",").map(function (s) { return 'html[data-dv-route="' + on + '"] ' + s.trim(); }).join(", ") + " {";
    });
  }
  function put(id, text) {
    var el = document.getElementById(id);
    if (!el) { el = document.createElement("style"); el.id = id; }
    if (el.textContent !== text) el.textContent = text;
    var head = document.head || document.documentElement;
    if (el.parentNode !== head || head.lastElementChild !== el && id === "dv-base") head.appendChild(el);
  }

  // ---- DOM edits ------------------------------------------------------------------------------------------------
  function place(node, where, ref) {
    if (where === "before") ref.parentNode.insertBefore(node, ref);
    else if (where === "after") ref.parentNode.insertBefore(node, ref.nextSibling);
    else if (where === "start") ref.insertBefore(node, ref.firstChild);
    else ref.appendChild(node);
  }
  function inPlace(node, where, ref) {
    if (where === "before") return node.nextElementSibling === ref;
    if (where === "after") return ref.nextElementSibling === node;
    if (where === "start") return ref.firstElementChild === node;
    return node.parentNode === ref;
  }
  function screenBox(r) {                  // the container of a simulated screen, made on demand
    var host = q(cfg.screen) || document.body;
    var box = host.querySelector('[data-dv-screen="' + r + '"]');
    if (!box) { box = document.createElement("div"); box.setAttribute("data-dv-screen", r); host.appendChild(box); }
    return box;
  }
  function ref(sel) { return sel && sel.indexOf("@screen:") === 0 ? screenBox(sel.slice(8)) : q(sel); }

  function one(op) {
    if (op.op === "token" || op.op === "css" || op.op === "remove") return "ok";
    if (op.op === "screen") {
      var nav = q(cfg.nav);
      var linked = nav && Array.prototype.some.call(nav.querySelectorAll("a"), function (x) {
        return x.getAttribute("href") === op.route || (op.route === "#/" && x.getAttribute("href") === "#");
      });
      if (nav && !linked) {
        var a = document.createElement("a");
        a.href = op.route; a.textContent = op.label; a.setAttribute("data-dv-nav", op.route);
        var like = nav.querySelector("a");
        if (like) a.className = like.className;
        nav.appendChild(a);
      }
      var box = screenBox(op.route), on = route() === op.route, host = q(cfg.screen);
      box.classList.toggle("dv-on", on);
      if (host) Array.prototype.forEach.call(host.children, function (c) {
        if (c === box || c.hasAttribute("data-dv-screen")) return;
        if (on) c.setAttribute("data-dv-hide", op.route); else if (c.getAttribute("data-dv-hide") === op.route) c.removeAttribute("data-dv-hide");
      });
      return "ok";
    }
    if (!routeOk(op)) return "other screen";
    if (op.op === "move") {
      var done = q('[data-dv-op~="' + op.id + '"]'), n = q(op.sel), r = ref(op.ref);   // an element remembers every move
      if (done && (!n || n === done) && r && inPlace(done, op.where, r)) return "ok";
      if (done && !n) return "ok";                     // moved already, and a later edit has moved it on
      if (!n || !r) return "missing " + (!n ? op.sel : op.ref);
      if (n.contains(r)) return "can't move into itself";
      if (!inPlace(n, op.where, r)) place(n, op.where, r);
      var had = (n.getAttribute("data-dv-op") || "").split(" ").filter(function (x) { return x && x !== op.id; });
      n.setAttribute("data-dv-op", had.concat(op.id).join(" "));
      return "ok";
    }
    if (op.op === "text") {
      var t = q(op.sel);
      if (!t) return "missing " + op.sel;
      if (t.textContent !== op.text) t.textContent = op.text;
      return "ok";
    }
    if (op.op === "attr") {
      var el = q(op.sel);
      if (!el) return "missing " + op.sel;
      if (el.getAttribute(op.name) !== String(op.value)) el.setAttribute(op.name, op.value);
      return "ok";
    }
    if (op.op === "repeat") {
      // The list ends up with n items (copies of its first real one), then "fill" sets each item's parts in order, one
      // value per item: {"<part>": [...texts], "<part>@<attr>": [...values]}; "" or ":self" is the item itself. The
      // list's real items keep their real content (a real deck keeps its real cover): their values are left unused.
      // Copies count by selector, so several repeats of the same list share one set of copies.
      var items = qa(op.sel);
      var src = items.filter(function (e) { return !e.hasAttribute("data-dv-repeat"); })[0];
      if (!src) return "missing " + op.sel;
      var fill = op.fill || {};
      if (op.values) fill[op.child || ""] = op.values;
      var want = op.n || 0;
      Object.keys(fill).forEach(function (k) { if (fill[k] && fill[k].length > want) want = fill[k].length; });
      var last = items[items.length - 1];
      for (var i = items.length; i < want; i++) {
        var c = src.cloneNode(true);
        c.setAttribute("data-dv-repeat", op.id);
        c.removeAttribute("id");
        Array.prototype.forEach.call(c.querySelectorAll("[id]"), function (e) { e.removeAttribute("id"); });
        c.addEventListener("click", forward(src));   // a copy clicks like the original
        last.after(c); last = c; items.push(c);
      }
      Object.keys(fill).forEach(function (k) {
        var parts = k.split("@"), part = parts[0].trim(), attr = parts[1];
        (fill[k] || []).forEach(function (v, j) {
          var it = items[j];                     // one value per item, in order; a real item's value is left unused
          if (!it || v == null || !it.hasAttribute("data-dv-repeat")) return;
          var t = !part || part === ":self" ? it : it.querySelector(part);
          if (!t) return;
          if (!attr && t.tagName === "IMG") attr = "src";       // an image's "text" is its picture
          if (attr) { if (!/^on/i.test(attr) && !/^\s*javascript:/i.test(v) && t.getAttribute(attr) !== String(v)) t.setAttribute(attr, v); }
          else if (t.textContent !== String(v)) t.textContent = v;
        });
      });
      return "ok";
    }
    if (op.op === "behavior") {            // a ready-made interaction from the library, set up once per element
      var fn = behaviors[op.name];
      if (!fn) return "unknown behavior " + op.name;
      var els = qa(op.sel);
      if (!els.length) return "missing " + op.sel;
      els.forEach(function (el) {
        var key = "dvB" + op.id.replace(/\W/g, "");
        if (el.dataset[key]) return;
        el.dataset[key] = "1";
        fn(el, op);
      });
      return "ok";
    }
    if (op.op === "link") {                // clicking these goes to a screen: prototype navigation
      var hits = qa(op.sel);
      if (!hits.length) return "missing " + op.sel;
      hits.forEach(function (h) {
        if (h.getAttribute("data-dv-link") === op.to) return;
        h.setAttribute("data-dv-link", op.to);
        h.style.cursor = "pointer";
      });
      return "ok";
    }
    if (op.op === "insert") {
      if (q('[data-dv-insert="' + op.id + '"]')) return "ok";
      var at = ref(op.ref);
      if (!at) return "missing " + op.ref;
      var tpl = document.createElement("template");
      tpl.innerHTML = op.html;
      for (var k = 0; k < tpl.content.children.length; k++) tpl.content.children[k].setAttribute("data-dv-insert", op.id);
      place(tpl.content, op.where, at);
      return "ok";
    }
    return "unknown";
  }
  function forward(src) {
    return function (ev) {
      var path = [], n = ev.target;
      while (n && n !== ev.currentTarget) { path.unshift(Array.prototype.indexOf.call(n.parentNode.children, n)); n = n.parentNode; }
      var t = src;
      for (var k = 0; k < path.length && t; k++) t = t.children[path[k]];
      if (t) { ev.preventDefault(); ev.stopPropagation(); t.click(); }
    };
  }

  function apply() {
    if (applying || !ready) return;
    applying = true;
    obs.disconnect();
    if (document.documentElement.getAttribute("data-dv-route") !== route()) document.documentElement.setAttribute("data-dv-route", route());
    var list = current();
    styles(list);
    list.forEach(function (o) { try { status[o.id] = one(o); } catch (e) { status[o.id] = "error: " + e.message; } });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    applying = false;
    report();
  }
  // Tell the server how each edit fared on this screen, so whoever sent it (dv.py) knows it landed without a browser.
  var sent = {}, reportTimer = 0;
  function report() {
    if (fixed && !measuring) return;
    clearTimeout(reportTimer);
    reportTimer = setTimeout(function () {
      var changed = {}, any = false;
      Object.keys(status).forEach(function (id) {
        var st = effect[id] || status[id];
        if (sent[id] !== st) { changed[id] = st; sent[id] = st; any = true; }
      });
      if (any) fetch("/dv/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ route: route(), statuses: changed }) }).catch(function () {});
    }, 250);
  }
  var obs = new MutationObserver(function () { clearTimeout(timer); timer = setTimeout(apply, 30); });

  function flash(op) {
    var sels = [];
    if (op.sel) sels.push(op.sel);
    if (op.op === "insert") sels.push('[data-dv-insert="' + op.id + '"]');
    if (op.op === "css") { var m = /^\s*([^{]+)\{/.exec(op.rule); if (m) sels.push(m[1].split(",")[0].trim()); }
    if (op.op === "screen") sels.push('[data-dv-screen="' + op.route + '"]');
    sels.forEach(function (s) {
      qa(s).slice(0, 12).forEach(function (el) {
        el.classList.add("dv-flash");
        setTimeout(function () { el.classList.remove("dv-flash"); }, 1400);
      });
    });
    if (sels.length) { var first = q(sels[sels.length - 1]); if (first && first.scrollIntoView) first.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
  }

  // Load the layer, or catch up with it: edits the page missed (one that streamed in while it was reloading) are
  // applied; if an edit it already shows has gone (an undo it missed), only a fresh page is exact, so it reloads.
  var syncedV = null, measuredOnce = false;
  function load() {
    return fetch("/dv/ops", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      var now = {};
      (d.ops || []).forEach(function (o) { now[o.id] = 1; });
      Object.keys(d.options || {}).forEach(function (s) {
        Object.keys(d.options[s].choices || {}).forEach(function (c) { (d.options[s].choices[c].ops || []).forEach(function (o) { now[o.id] = 1; }); });
      });
      if (ready && current().some(function (o) { return !now[o.id]; })) { location.reload(); return; }
      syncedV = d.v;
      ops = d.ops || []; options = d.options || {}; cfg = Object.assign(cfg, d.config || {});
      if (active && !(options[active.set] && options[active.set].choices[active.choice])) { active = null; sessionStorage.removeItem("dv-opt"); }
      ready = true; apply(); postMap();
      tell({ dv: "loaded", options: options, active: active });
      if (measuring && !measuredOnce) { measuredOnce = true; setTimeout(measureAll, 900); }   // after the app has drawn
    }).catch(function () {});
  }
  function tell(msg) { try { if (window.parent !== window) window.parent.postMessage(msg, location.origin); } catch (e) {} }

  // ---- live events ------------------------------------------------------------------------------------------------
  // One live stream per page: the toolbar holds it and passes each event down (a browser allows only a few open
  // connections to one server, so frames don't open their own). A side-by-side frame takes no live events.
  if (window.parent === window) {
    new EventSource("/dv/events").onmessage = function (m) { try { onEvent(JSON.parse(m.data)); } catch (x) {} };
  } else if (!fixed) {
    addEventListener("message", function (ev) {
      if (ev.origin === location.origin && ev.source === window.parent && ev.data && ev.data.dvEvent) onEvent(ev.data.dvEvent);
    });
  }
  // Did a style edit take? Each property is compared, on the elements the rule matches, with what it would be if
  // nothing else interfered: the declaration is tried for an instant as the element's own top-priority style (with
  // whatever holds a size released), read, and the element put back exactly as it was. So %, calc(), var() and em
  // are judged in place, and sizes by layout (transforms don't count). When it didn't take, the page names what
  // holds it. Then: is the element still seen (not hidden, clipped by a parent or covered)? The result goes back to
  // the server, which repairs in the same note; the owner never sees a "done" that changed nothing.
  var effect = {};
  function cssTargets(op) {
    var m = /^\s*([^{]+)\{([^}]*)\}/.exec(op.rule || "");
    if (!m) return null;
    var props = m[2].split(";").map(function (d) { return d.split(":")[0].trim().toLowerCase(); }).filter(Boolean);
    return { sel: m[1].trim(), els: qa(m[1]).slice(0, 6), props: props };
  }
  function snap(t) {
    return t.els.map(function (el) { var cs = getComputedStyle(el); return t.props.map(function (p) { return cs.getPropertyValue(p); }).join("|"); }).join("§");
  }
  function decls(op) {
    var m = /\{([^}]*)\}/.exec(op.rule || ""), out = {};
    (m ? m[1] : "").split(";").forEach(function (d) {
      var i = d.indexOf(":"); if (i < 0) return;
      out[d.slice(0, i).trim().toLowerCase()] = d.slice(i + 1).replace(/!important/i, "").trim();
    });
    return out;
  }
  function label(el) {
    return el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") +
      ((typeof el.className === "string" && el.className.trim()) ? "." + el.className.trim().split(/\s+/).filter(function (c) { return c.indexOf("dv-") !== 0; }).slice(0, 2).join(".") : "");
  }
  // Try declarations on el for an instant and read the result; the element's style attribute is put back exactly.
  function trial(el, set, read) {
    var had = el.hasAttribute("style"), saved = el.getAttribute("style");
    Object.keys(set).forEach(function (p) { el.style.setProperty(p, set[p], "important"); });
    var r = read();
    if (had) el.setAttribute("style", saved); else el.removeAttribute("style");
    return r;
  }
  // Rules that match el and set prop: the app's stylesheets, and the layer's own earlier edits. What holds it.
  function rulesSetting(el, prop) {
    var out = [];
    Array.prototype.forEach.call(document.styleSheets, function (sh) {
      var owner = sh.ownerNode && sh.ownerNode.id;
      if (owner && owner.indexOf("dv-") === 0 && owner !== "dv-css") return;
      var src = owner === "dv-css" ? "a layer edit" : sh.href ? sh.href.split("/").pop().split("?")[0] : "page <style>", list;
      try { list = sh.cssRules; } catch (e) { return; }
      (function walk(rs) {
        Array.prototype.forEach.call(rs || [], function (r) {
          if (r.cssRules && !r.selectorText) return walk(r.cssRules);
          if (!r.selectorText || !r.style || !r.style.getPropertyValue(prop)) return;
          try { if (!el.matches(r.selectorText)) return; } catch (e) { return; }
          out.push(prop + ": " + r.style.getPropertyValue(prop) + (r.style.getPropertyPriority(prop) ? " !important" : "") + " (" + src + " " + r.selectorText.slice(0, 50) + ")");
        });
      })(list);
    });
    var own = el.style.getPropertyValue(prop);
    if (own) out.push(prop + ": " + own + " (the element's own style attribute)");
    return out;
  }
  function where(rules) { return rules.length ? " (" + rules[0].replace(/^[^(]*\(/, "").replace(/\)$/, "") + ")" : ""; }
  // Why a size didn't come out as asked: min/max, flex, grid stretch, aspect-ratio, box-sizing.
  function sizeHolds(el, prop) {
    var cs = getComputedStyle(el), ps = el.parentElement ? getComputedStyle(el.parentElement) : null, out = [];
    var mn = cs.getPropertyValue("min-" + prop), mx = cs.getPropertyValue("max-" + prop);
    if (mn && mn !== "0px" && mn !== "auto") out.push("min-" + prop + ": " + mn + where(rulesSetting(el, "min-" + prop)));
    if (mx && mx !== "none") out.push("max-" + prop + ": " + mx + where(rulesSetting(el, "max-" + prop)));
    if (ps && /flex/.test(ps.display)) {
      var row = !/column/.test(ps.flexDirection), main = row ? "width" : "height";
      if (prop === main && (parseFloat(cs.flexGrow) > 0 || parseFloat(cs.flexShrink) > 0))
        out.push("flex: " + cs.flexGrow + " " + cs.flexShrink + " " + cs.flexBasis + " in a flex " + (row ? "row" : "column") + where(rulesSetting(el, "flex").concat(rulesSetting(el, "flex-grow"))));
      if (prop !== main && /stretch|normal/.test(cs.alignSelf) && /stretch|normal/.test(ps.alignItems)) out.push("stretched across its flex line (align-items/align-self: stretch)");
    }
    if (ps && /grid/.test(ps.display) && /stretch|normal/.test(prop === "height" ? cs.alignSelf : cs.justifySelf)) out.push("stretched to its grid " + (prop === "height" ? "row" : "column") + " (" + (prop === "height" ? "align" : "justify") + "-self: stretch)");
    if (cs.aspectRatio && cs.aspectRatio !== "auto") out.push("aspect-ratio: " + cs.aspectRatio + where(rulesSetting(el, "aspect-ratio")));
    return out;
  }
  var SIZE = { height: "offsetHeight", width: "offsetWidth" };
  var FREE = { "min-height": "0px", "max-height": "none", "min-width": "0px", "max-width": "none", "flex": "none", "align-self": "start", "justify-self": "start" };
  // One property on one element: null when it took, else what it is and what holds it.
  function judgeProp(el, p, v) {
    if (/^(inherit|initial|unset|revert)$/i.test(v)) return null;
    if (SIZE[p]) {                                        // a size: by layout, against the size nothing holds back
      var free = {}; Object.keys(FREE).forEach(function (k) { free[k] = FREE[k]; }); free[p] = v;
      free["aspect-ratio"] = "auto";
      var want = trial(el, free, function () { return el[SIZE[p]]; }), got = el[SIZE[p]];
      if (Math.abs(want - got) <= 1) return null;
      return p + " asked " + v + " (" + want + "px here), is " + got + "px" + held(sizeHolds(el, p).concat(others(el, p, v)));
    }
    if (p === "aspect-ratio") {                           // judged by the height it gives at this width
      var fr = {}; Object.keys(FREE).forEach(function (k) { fr[k] = FREE[k]; }); fr[p] = v; fr.height = "auto";
      var wh = trial(el, fr, function () { return el.offsetHeight; }), gh = el.offsetHeight;
      if (Math.abs(wh - gh) <= 1) return null;
      return "aspect-ratio asked " + v + " (" + wh + "px tall here), is " + gh + "px tall" + held(sizeHolds(el, "height").concat(others(el, "height", "")));
    }
    var sw = {}; sw[p] = v;
    var wantV = trial(el, sw, function () { return getComputedStyle(el).getPropertyValue(p); });
    var gotV = getComputedStyle(el).getPropertyValue(p);
    if (wantV === gotV) return null;
    return p + " asked " + v + (wantV !== v ? " (" + wantV + " here)" : "") + ", is " + gotV + held(others(el, p, v));
  }
  function others(el, p, v) { return rulesSetting(el, p).filter(function (r) { return r.indexOf(": " + v) < 0; }).slice(0, 2); }
  function held(why) { return why.length ? ": held by " + why.slice(0, 4).join("; ") : ""; }
  // Is the element still seen? Hidden by an ancestor, clipped by one (overflow), or covered by another element.
  function seen(el, want) {
    if (want.display === "none" || want.visibility === "hidden" || want.opacity === "0") return null;   // meant to go
    for (var a = el; a && a !== document.documentElement; a = a.parentElement) {
      var s = getComputedStyle(a);
      if (s.display === "none") return "can't be seen: " + (a === el ? "it has" : label(a) + " has") + " display: none" + where(rulesSetting(a, "display"));
      if (s.visibility === "hidden" && a === el) return "can't be seen: visibility: hidden" + where(rulesSetting(a, "visibility"));
      if (parseFloat(s.opacity) === 0) return "can't be seen: " + (a === el ? "it has" : label(a) + " has") + " opacity: 0" + where(rulesSetting(a, "opacity"));
    }
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return null;
    var sized = want.height || want.width || want["aspect-ratio"] || want["min-height"] || want["min-width"];
    for (var c = sized ? el.parentElement : null; c && c !== document.body; c = c.parentElement) {   // a crop is fine unless this edit sized it
      var cs = getComputedStyle(c);
      if (/hidden|clip|scroll|auto/.test(cs.overflow + cs.overflowX + cs.overflowY)) {
        var cr = c.getBoundingClientRect();
        var vert = want.height || want["aspect-ratio"] || want["min-height"], horiz = want.width || want["min-width"];
        var cut = (vert ? Math.max(0, cr.top - r.top) + Math.max(0, r.bottom - cr.bottom) : 0) +
                  (horiz ? Math.max(0, cr.left - r.left) + Math.max(0, r.right - cr.right) : 0);   // only along what this edit sized
        if (cut > 2 && !/scroll|auto/.test(cs.overflowY + cs.overflowX)) return "clipped: " + label(c) + " (overflow: " + cs.overflow + where(rulesSetting(c, "overflow")) + ") cuts " + Math.round(cut) + "px of it";
        break;
      }
    }
    if (want["z-index"] || want.position || want.top || want.left || want.right || want.bottom || want.transform) {
      var x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
      var at = document.elementFromPoint(x, y);
      if (at && at !== el && !el.contains(at) && getComputedStyle(el).pointerEvents !== "none")   // a parent on top counts: it's painted over it
        return "covered by " + (at.contains(el) ? "its own " : "") + label(at) + " (z-index " + getComputedStyle(at).zIndex + ")";
    }
    return null;
  }
  function judge(op, t) {
    if (!t.els.length) return "missing: nothing on this screen matches " + t.sel;
    var shown = t.els.filter(function (el) { return el.getClientRects().length; });
    if (!shown.length) return "ok: matches only elements not on screen now (checked when they show)";
    var want = decls(op), wrong = [];
    shown.slice(0, 3).forEach(function (el) {
      Object.keys(want).forEach(function (p) {
        var w = judgeProp(el, p, want[p]);
        if (w && wrong.indexOf(w) < 0) wrong.push(w);
      });
      var s = seen(el, want);
      if (s && wrong.indexOf(s) < 0) wrong.push(s);
    });
    return wrong.length ? "didn't take: " + wrong.slice(0, 3).join(" | ") : null;
  }
  function measure(op, before, t) {
    setTimeout(function () {
      var bad = judge(op, t);
      effect[op.id] = bad || (snap(t) === before ? "ok: already so" : "ok: changed");
      report();
    }, 450);
  }
  // A measuring frame (?dvmeasure=1, opened hidden by the toolbar for each option choice): judge every style edit of
  // its choice once the page has settled, report, and tell the toolbar it's done.
  var measuring = fixed && /[?&]dvmeasure=1/.test(location.search);
  function measureAll() {
    var list = active && options[active.set] && options[active.set].choices[active.choice] ? options[active.set].choices[active.choice].ops : [];
    list.forEach(function (op) {
      if (op.op !== "css" || !routeOk(op)) return;
      var t = cssTargets(op);
      if (t) { status[op.id] = status[op.id] || "ok"; effect[op.id] = judge(op, t) || "ok: changed"; }
    });
    report();
    setTimeout(function () { tell({ dv: "measured", set: active && active.set, choice: active && active.choice }); }, 400);
  }

  function onEvent(e) {
    if (e.type === "op" && e.op) {
      if (e.option) {
        var s = options[e.option.set] = options[e.option.set] || { choices: {} };
        var ch = s.choices[e.option.choice] = s.choices[e.option.choice] || { name: e.option.choice, ops: [] };
        ch.ops.push(e.op);
        if (!active && !fixed) { active = { set: e.option.set, choice: e.option.choice }; sessionStorage.setItem("dv-opt", JSON.stringify(active)); tell({ dv: "active", active: active }); }
        if (!active || active.set !== e.option.set || active.choice !== e.option.choice) return;
      } else {
        ops.push(e.op);
      }
      var t = e.op.op === "css" && routeOk(e.op) ? cssTargets(e.op) : null, before = t && snap(t);
      apply(); flash(e.op); postMap();
      if (t) measure(e.op, before, t);
    } else if (e.type === "option") {
      var s2 = options[e.set] = options[e.set] || { choices: {} };
      s2.choices[e.choice] = s2.choices[e.choice] || { name: e.name, ops: [] };
      s2.choices[e.choice].name = e.name;
    } else if (e.type === "reload-ops" || e.type === "app-changed") {
      location.reload();
    }
  }

  // ---- the screen map sent with a note -----------------------------------------------------------------------------
  function sig(el) {
    var s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    var cls = (typeof el.className === "string" ? el.className : "").split(/\s+/).filter(function (c) { return c && c.indexOf("dv-") !== 0; });
    if (cls.length) s += "." + cls.slice(0, 3).join(".");
    if (el.getAttribute("data-ui")) s += "[data-ui=" + el.getAttribute("data-ui") + "]";
    if (el.getAttribute("href") && el.tagName === "A") s += "[href=" + el.getAttribute("href") + "]";
    return s;
  }
  function own(el) {
    var t = "";
    for (var i = 0; i < el.childNodes.length; i++) if (el.childNodes[i].nodeType === 3) t += el.childNodes[i].textContent;
    t = t.replace(/\s+/g, " ").trim();
    if (!t && /^(INPUT|TEXTAREA)$/.test(el.tagName)) t = el.getAttribute("placeholder") || "";
    return t.length > 40 ? t.slice(0, 40) + "…" : t;
  }
  function visible(el) {
    var st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0 || el.children.length > 0;
  }
  function holds(el) {
    var cs = getComputedStyle(el), ps = el.parentElement ? getComputedStyle(el.parentElement) : null, h = [];
    ["min-height", "min-width"].forEach(function (p) { var v = cs.getPropertyValue(p); if (v && v !== "0px" && v !== "auto") h.push(p + " " + v); });
    ["max-height", "max-width"].forEach(function (p) { var v = cs.getPropertyValue(p); if (v && v !== "none") h.push(p + " " + v); });
    if (ps && /flex/.test(ps.display) && parseFloat(cs.flexGrow) > 0) h.push("flex-grow " + cs.flexGrow + " (" + (/column/.test(ps.flexDirection) ? "column" : "row") + ")");
    if (cs.aspectRatio && cs.aspectRatio !== "auto") h.push("aspect-ratio " + cs.aspectRatio);
    if (el.tagName === "IMG" && el.naturalWidth) {                // the picture's own shape: "55% of the card" is computable
      h.push("image " + el.naturalWidth + "x" + el.naturalHeight + (cs.objectFit && cs.objectFit !== "fill" ? ", object-fit " + cs.objectFit : "")
             + (cs.objectPosition && cs.objectPosition !== "50% 50%" ? " " + cs.objectPosition : "")
             + ", src " + String(el.getAttribute("src") || "").slice(0, 120));      // where the real picture comes from
    }
    return h.join(", ");
  }
  function map(maxLines) {
    var out = [], max = maxLines || 220;
    function walk(el, depth) {
      if (out.length >= max || depth > 9) return;
      var kids = Array.prototype.filter.call(el.children, function (c) { return !/^(SCRIPT|STYLE|LINK|META|TEMPLATE|svg|SVG|NOSCRIPT)$/.test(c.tagName) && visible(c); });
      for (var i = 0; i < kids.length && out.length < max; i++) {
        var c = kids[i], s = sig(c), n = 1;
        while (i + n < kids.length && sig(kids[i + n]) === s) n++;
        var r = c.getBoundingClientRect();
        var line = new Array(depth + 1).join("  ") + s + (own(c) ? ' "' + own(c) + '"' : "") + (n > 1 ? " x" + n : "") +
          (depth < 5 ? "  (" + Math.round(r.width) + "x" + Math.round(r.height) + ")" : "");
        var inline = c.getAttribute("style");                 // its own style beats any css rule: show it
        if (inline) line += ' style="' + inline.replace(/\s+/g, " ").slice(0, 90) + '"';
        var hold = holds(c);                                  // what decides its size besides a width/height edit
        if (hold) line += " [" + hold + "]";
        out.push(line);
        walk(c, depth + 1);
        i += n - 1;
      }
    }
    walk(document.body, 0);
    return out.join("\n");
  }

  // ---- picking elements for a note ----------------------------------------------------------------------------------
  function selectorFor(el) {
    if (el.id && qa("#" + CSS.escape(el.id)).length === 1) return "#" + CSS.escape(el.id);
    var ui = el.getAttribute("data-ui");
    if (ui && qa('[data-ui="' + ui + '"]').length === 1) return '[data-ui="' + ui + '"]';
    var parts = [], n = el;
    while (n && n.nodeType === 1 && n !== document.body) {
      if (n.id) { parts.unshift("#" + CSS.escape(n.id)); break; }
      if (n.getAttribute("data-ui")) { parts.unshift('[data-ui="' + n.getAttribute("data-ui") + '"]'); break; }
      var p = n.tagName.toLowerCase();
      var cls = (typeof n.className === "string" ? n.className : "").split(/\s+/).filter(function (c) { return c && c.indexOf("dv-") !== 0; });
      if (cls.length) p += "." + cls.slice(0, 2).map(function (c) { return CSS.escape(c); }).join(".");
      var sib = n.parentNode ? Array.prototype.filter.call(n.parentNode.children, function (s) { return s.tagName === n.tagName; }) : [];
      if (sib.length > 1 && qa(parts.length ? p + " > " + parts.join(" > ") : p).length > 1) p += ":nth-of-type(" + (sib.indexOf(n) + 1) + ")";
      parts.unshift(p);
      if (qa(parts.join(" > ")).length === 1) break;
      n = n.parentNode;
    }
    return parts.join(" > ");
  }
  function describe(el) {
    var st = getComputedStyle(el), r = el.getBoundingClientRect();
    var keep = ["display", "font-size", "font-weight", "color", "background-color", "padding", "margin", "gap", "border-radius", "grid-template-columns", "flex-direction"];
    return {
      sel: selectorFor(el),
      html: el.outerHTML.replace(/\s+/g, " ").slice(0, 700),
      styles: keep.map(function (k) { return k + ": " + st.getPropertyValue(k); }).filter(function (s) { return !/: (normal|none|0px|auto)?$/.test(s); }).join("; "),
      rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }
    };
  }
  var picking = false, hover = null;
  function onMove(ev) {
    if (!picking) return;
    if (hover) hover.classList.remove("dv-hover");
    hover = ev.target; hover.classList.add("dv-hover");
  }
  function onClick(ev) {
    if (!picking) return;
    ev.preventDefault(); ev.stopPropagation();
    var el = ev.target;
    el.classList.remove("dv-hover");
    if (el.classList.contains("dv-picked")) {             // marked already: a second click takes the mark back
      el.classList.remove("dv-picked");
      tell({ dv: "unpicked", sel: selectorFor(el) });
      return;
    }
    if (!ev.shiftKey) qa(".dv-picked").forEach(function (e) { e.classList.remove("dv-picked"); });   // a plain click replaces
    el.classList.add("dv-picked");
    tell({ dv: "picked", mark: describe(el), add: ev.shiftKey });
  }
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") tell({ dv: "escape" }); });
  document.addEventListener("click", function (ev) {        // prototype links (after picking, which comes first)
    if (picking) return;
    var t = ev.target.closest && ev.target.closest("[data-dv-link]");
    if (t) { ev.preventDefault(); location.hash = t.getAttribute("data-dv-link"); }
  });
  document.addEventListener("mousemove", onMove, true);
  document.addEventListener("click", onClick, true);

  // The map of each screen the owner visits is kept by the server, so the Designer can read it without a browser.
  var mapTimer = 0;
  function postMap() {
    if (fixed) return;
    clearTimeout(mapTimer);
    mapTimer = setTimeout(function () {
      fetch("/dv/map", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ route: route(), map: map() }) }).catch(function () {});
    }, 900);
  }

  // ---- direct tools (the toolbar's Move and Text) ---------------------------------------------------------------------
  function at(x, y) {
    var el = document.elementFromPoint(x, y);
    while (el && el !== document.body && (el.closest("[data-dv-screen]") === el)) el = el.parentElement;
    return el && el !== document.documentElement && el !== document.body ? el : null;
  }
  function dropPlace(x, y, dragged) {      // where a dragged element would land: {ref, where, rect}
    var t = at(x, y);
    while (t && dragged && (t === dragged || dragged.contains(t))) t = null;
    if (!t) return null;
    // land beside the nearest look-alike of what is dragged (a card among cards), else beside an element that has
    // look-alike siblings, else climb past wrappers with a single child
    var like = function (a, b) { return a.tagName === b.tagName && a.className.replace(/\bdv-\S+/g, "").trim() === b.className.replace(/\bdv-\S+/g, "").trim(); };
    var n = t, hit = null;
    while (dragged && n && n !== document.body) { if (n !== dragged && like(n, dragged)) { hit = n; break; } n = n.parentElement; }
    if (!hit) {
      n = t;
      while (n && n !== document.body && n.parentElement) {
        if (Array.prototype.some.call(n.parentElement.children, function (s) { return s !== n && like(s, n); })) { hit = n; break; }
        n = n.parentElement;
      }
    }
    t = hit || t;
    while (!hit && t.parentElement && t.parentElement !== document.body && t.parentElement.children.length === 1) t = t.parentElement;
    var r = t.getBoundingClientRect(), ps = getComputedStyle(t.parentElement || t);
    var row = /flex/.test(ps.display) && !/column/.test(ps.flexDirection) || /grid/.test(ps.display);
    var before = row ? x < r.left + r.width / 2 : y < r.top + r.height / 2;
    return { ref: selectorFor(t), where: before ? "before" : "after", rect: { x: r.left, y: r.top, w: r.width, h: r.height }, row: row };
  }
  function editText(x, y, done) {
    var el = at(x, y);
    if (!el) return false;
    while (el.children.length && el.children.length === 1 && !own(el)) el = el.children[0];
    if (!own(el) && el.children.length) return false;
    var before = el.textContent;
    el.setAttribute("contenteditable", "plaintext-only");
    el.classList.add("dv-picked");
    el.focus();
    var range = document.createRange(); range.selectNodeContents(el);
    var s = getSelection(); s.removeAllRanges(); s.addRange(range);
    function finish(save) {
      el.removeEventListener("keydown", key); el.removeEventListener("blur", blur);
      el.removeAttribute("contenteditable"); el.classList.remove("dv-picked");
      var now = el.textContent.trim();
      if (!save) { el.textContent = before; return done(null); }
      done(now !== before.trim() ? { sel: selectorFor(el), text: now } : null);
    }
    function key(ev) { if (ev.key === "Enter") { ev.preventDefault(); finish(true); } else if (ev.key === "Escape") finish(false); }
    function blur() { finish(true); }
    el.addEventListener("keydown", key); el.addEventListener("blur", blur);
    return true;
  }

  window.__dv = {
    map: map,
    route: route,
    sync: load,
    at: at,
    selectorFor: selectorFor,
    describe: describe,
    dropPlace: dropPlace,
    editText: editText,
    report: function () { return current().map(function (o) { return { id: o.id, op: o.op, status: status[o.id] || "not run" }; }); },
    pick: function (on) {
      picking = !!on;
      if (!on) { if (hover) hover.classList.remove("dv-hover"); qa(".dv-picked").forEach(function (e) { e.classList.remove("dv-picked"); }); }
    },
    unpickAll: function () { qa(".dv-picked").forEach(function (e) { e.classList.remove("dv-picked"); }); },
    unpick: function (sel) { qa(sel).forEach(function (e) { e.classList.remove("dv-picked"); }); },
    setOption: function (set, choice) {
      active = set && choice ? { set: set, choice: choice } : null;
      if (active) sessionStorage.setItem("dv-opt", JSON.stringify(active)); else sessionStorage.removeItem("dv-opt");
      location.reload();
    },
    active: function () { return active; },
    options: function () { return options; }
  };
  addEventListener("hashchange", function () { setTimeout(apply, 0); tell({ dv: "route", route: route() }); postMap(); });
  addEventListener("load", postMap);
  setTimeout(function () { if (ready) load(); }, 1000);   // anything that landed while this page was loading
  document.addEventListener("visibilitychange", function () { if (!document.hidden && ready) load(); });   // back on the tab
  setInterval(function () {                               // a cheap check that nothing was missed since
    if (document.hidden || !ready) return;
    fetch("/dv/version", { cache: "no-store" }).then(function (r) { return r.json(); })
      .then(function (d) { if (syncedV !== null && d.v !== syncedV) load(); }).catch(function () {});
  }, 3000);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();
