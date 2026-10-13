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
  // The design view's own headless browser (mirror.js) showing the owner's screen for its pictures: a fixed frame that
  // takes no live events either (it gets a fresh page whenever the edits change).
  var mirror = /[?&]dvmirror=1/.test(location.search);
  // A build's own front end shown bare (the look check: the build against the agreed mockup): no design edits at all.
  var bare = /[?&]dvbare=1/.test(location.search);
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
      if (op.each && op.ref.indexOf("@screen:") !== 0) {    // into every match (each row of a list), once each
        var all = qa(op.ref).filter(function (t) { return !t.closest('[data-dv-insert="' + op.id + '"]'); });
        if (!all.length) return "missing " + op.ref;
        all.forEach(function (t) {
          var got = (t.getAttribute("data-dv-at") || "").split(" ");
          if (got.indexOf(op.id) >= 0) return;
          var tp = document.createElement("template");
          tp.innerHTML = op.html;
          for (var j = 0; j < tp.content.children.length; j++) tp.content.children[j].setAttribute("data-dv-insert", op.id);
          place(tp.content, op.where, t);
          t.setAttribute("data-dv-at", got.concat(op.id).join(" ").trim());
        });
        return "ok";
      }
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
      ops = bare ? [] : d.ops || []; options = bare ? {} : d.options || {}; cfg = Object.assign(cfg, d.config || {});
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
  if (window.parent === window && !mirror) {
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
    var state = /:(hover|active|focus|focus-visible|focus-within)/.exec(m[1]);   // a hover/press/focus rule: on screen only then
    if (state) return { sel: m[1].trim(), els: [], props: props, state: state[1] };
    var pe = /::?(before|after)\b/.exec(m[1]);                   // a decoration drawn by CSS: found through its element
    if (pe) return { sel: m[1].trim(), els: qa(m[1].replace(/::?(before|after)\b/g, "")).slice(0, 6), props: props, pseudo: "::" + pe[1] };
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
  // A selector's specificity as one comparable number: ids, then classes / attributes / pseudo-classes, then elements.
  function specificity(sel) {
    var s = sel.replace(/::?(before|after|first-line|first-letter|placeholder|selection|marker)\b/g, " x")
      .replace(/:(not|is|has)\(([^)]*)\)/g, " $2").replace(/:where\([^)]*\)/g, "");
    var ids = (s.match(/#[\w-]+/g) || []).length, cls = (s.match(/\.[\w-]+|\[[^\]]+\]|:[\w-]+(\([^)]*\))?/g) || []).length;
    var els = (s.replace(/#[\w-]+|\.[\w-]+|\[[^\]]+\]|:[\w-]+(\([^)]*\))?/g, " ").match(/(^|[\s>+~])[a-z][\w-]*/gi) || []).length;
    return ids * 1e6 + cls * 1e3 + els;
  }
  // Rules that match el and set prop: the app's stylesheets and the layer's own earlier edits, the one that wins first
  // (the browser's order: !important, then the more specific selector, then the later rule). What holds it.
  function rulesSetting(el, prop) {
    var found = [], n = 0;
    Array.prototype.forEach.call(document.styleSheets, function (sh) {
      var owner = sh.ownerNode && sh.ownerNode.id;
      if (owner && owner.indexOf("dv-") === 0 && owner !== "dv-css") return;
      var src = owner === "dv-css" ? "a layer edit" : sh.href ? sh.href.split("/").pop().split("?")[0] : "page <style>", list;
      try { list = sh.cssRules; } catch (e) { return; }
      (function walk(rs) {
        Array.prototype.forEach.call(rs || [], function (r) {
          if (r.cssRules && !r.selectorText) return (r.media && r.media.mediaText && !matchMedia(r.media.mediaText).matches) ? null : walk(r.cssRules);   // a media rule only when it applies now
          if (!r.selectorText || !r.style || !r.style.getPropertyValue(prop)) return;
          var best = -1;
          r.selectorText.split(",").forEach(function (one) {
            try { if (el.matches(one)) best = Math.max(best, specificity(one)); } catch (e) { /* not a selector this browser reads */ }
          });
          if (best < 0) return;
          var imp = !!r.style.getPropertyPriority(prop);
          found.push({ imp: imp, spec: best, order: n++,
                       text: prop + ": " + r.style.getPropertyValue(prop) + (imp ? " !important" : "") + " (" + src + " " + r.selectorText.slice(0, 60) + ")" });
        });
      })(list);
    });
    var own = el.style.getPropertyValue(prop);
    if (own) found.push({ imp: !!el.style.getPropertyPriority(prop), spec: 1e9, order: n++, text: prop + ": " + own + " (the element's own style attribute)" });
    found.sort(function (a, b) { return (b.imp - a.imp) || (b.spec - a.spec) || (b.order - a.order); });
    return found.map(function (f) { return f.text; });
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
    if (t.state) return null;
    if (t.pseudo) {
      if (!t.els.length) return "missing: nothing on this screen matches " + t.sel.replace(/::?(before|after)\b/g, "");
      var pc = getComputedStyle(t.els[0], t.pseudo);
      return pc.content && pc.content !== "none" && pc.content !== "normal" ? null
        : "didn't take: the " + t.pseudo + " isn't drawn (content: " + pc.content + "; it needs content: \"\")";
    }
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
      effect[op.id] = t.state ? "ok: applies on " + t.state : bad || (snap(t) === before ? "ok: already so" : "ok: changed");
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
    if (e.type === "page-call") {          // the designer asks the owner's page to measure or take a picture
      if (fixed || (e.route && e.route !== route())) return;
      var reply = function (result) {
        fetch("/dv/page-reply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ req: e.req, result: result }) }).catch(function () {});
      };
      if (e.what === "inspect") reply(inspect(e.spec || {}));
      return;
    }
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
      if (e.op.op === "remove" && routeOk(e.op)) {          // a remove that matched nothing changed nothing: say so
        var rop = e.op;
        setTimeout(function () {
          effect[rop.id] = qa(rop.sel).length ? "ok: changed" : "missing: nothing on this screen matches " + rop.sel;
          report();
        }, 450);
      }
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
      rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
      facts: facts(el)
    };
  }
  // Measured facts about a marked element, exact where a picture is only roughly right: where it is, its spacing, where
  // its text starts, the gaps to what's above it and to its container, and what it scrolls with.
  function textAt(el) {                    // where an element's first text starts inside it, and its font
    var r = el.getBoundingClientRect();
    var tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: function (n) {
      if (!n.textContent.trim() || !n.parentElement || !n.parentElement.getClientRects().length) return 3;   // hidden text doesn't count
      var rr = document.createRange(); rr.selectNodeContents(n);
      var b = rr.getBoundingClientRect();
      return b.width && b.bottom >= r.top && b.top <= r.bottom ? 1 : 3;
    } }), tn = tw.nextNode();
    if (!tn) return "";
    var rg = document.createRange(); rg.selectNodeContents(tn);
    var tr = rg.getBoundingClientRect(), ts = getComputedStyle(tn.parentElement);
    return "text \"" + tn.textContent.trim().slice(0, 24) + "\" starts " + Math.round(tr.left - r.left) + " px in and " + Math.round(tr.top - r.top) + " px down (" + ts.fontSize + " " + ts.fontWeight + ")";
  }
  function facts(el) {
    var r = el.getBoundingClientRect(), st = getComputedStyle(el), out = [];
    out.push("box at x " + Math.round(r.left) + ", y " + Math.round(r.top) + ", " + Math.round(r.width) + "×" + Math.round(r.height) + " px");
    out.push("margin " + st.margin + ", padding " + st.padding);
    var ta = textAt(el);
    if (ta) out.push("its " + ta);
    // its look-alikes elsewhere on screen (the same kind of element in the same kind of parent), measured the same way,
    // so "match the others" has something exact to compare with
    var kind = function (e) { var c = (typeof e.className === "string" ? e.className : "").split(/\s+/).filter(function (x) { return x && x.indexOf("dv-") !== 0; })[0]; return e.tagName.toLowerCase() + (c ? "." + CSS.escape(c) : ""); };
    var like = el.parentElement ? qa(kind(el.parentElement) + " > " + kind(el)) : [];
    like = like.filter(function (e) { return e !== el && e.getClientRects().length; }).slice(0, 3);
    like.forEach(function (e) {
      var er = e.getBoundingClientRect(), es = getComputedStyle(e);
      out.push("look-alike " + label(e) + ": " + Math.round(er.width) + "×" + Math.round(er.height) + " px, padding " + es.padding + (textAt(e) ? ", " + textAt(e) : ""));
    });
    var prev = el.previousElementSibling;
    while (prev && !prev.getClientRects().length) prev = prev.previousElementSibling;
    if (prev) out.push("gap above it to " + label(prev) + ": " + Math.round(r.top - prev.getBoundingClientRect().bottom) + " px");
    var p = el.parentElement;
    if (p && p !== document.body) {
      var pr = p.getBoundingClientRect();
      out.push("inside " + label(p) + ": " + Math.round(r.top - pr.top) + " px from its top, " + Math.round(r.left - pr.left) + " px from its left, " + Math.round(pr.right - r.right) + " px from its right");
    }
    if (/sticky|fixed/.test(st.position)) out.push("position " + st.position + ", top " + st.top);
    for (var s = el.parentElement; s && s !== document.body; s = s.parentElement) {
      var ss = getComputedStyle(s);
      if (/auto|scroll/.test(ss.overflowY) && s.scrollHeight > s.clientHeight) { out.push("scrolls inside " + label(s)); break; }
      if (/sticky|fixed/.test(ss.position)) { out.push("inside a " + ss.position + " " + label(s) + " (top " + ss.top + ")"); break; }
    }
    return out.join("; ");
  }

  // ---- inspect: exact numbers for the elements a note is about, what differs between them, and the rule behind it --------
  // spec: {marked: [selector], refers: [{selector, what}]}. An element is found by its selector, else by the words it
  // shows (a quoted 'label' in "what", or the words themselves). One profile per element, then marked vs each referent.
  function byText(what) {
    var m = /['"‘“]([^'"’”]{2,60})['"’”]/.exec(what || "");
    if (!m) {                                // no quoted label: try each item named in brackets or a list ("A, B and C")
      var inner = /\(([^)]+)\)/.exec(what || ""), parts = (inner ? inner[1] : what || "").split(/,|\band\b|\bor\b/);
      for (var i = 0; i < parts.length; i++) { var hit = parts[i].trim().length > 2 && byText("'" + parts[i].trim().replace(/^the\s+/i, "") + "'"); if (hit) return hit; }
      return null;
    }
    var want = m[1].replace(/…|\.\.\./g, "").trim().toLowerCase();
    if (!want) return null;
    var best = null;
    qa("button, a, summary, h1, h2, h3, h4, label, [role=button], li, span, div").forEach(function (e) {
      if (!e.getClientRects().length || best && best.children.length === 0) return;
      var t = e.textContent.replace(/\s+/g, " ").trim().toLowerCase();
      if (t && t.indexOf(want) === 0 && t.length < want.length + 40 && (!best || e.textContent.length <= best.textContent.length)) best = e;
    });
    return best;
  }
  function find(ref) {
    var el = null;
    if (ref && ref.selector) qa(ref.selector).some(function (e) { if (e.getClientRects().length) { el = e; return true; } return false; });
    return el || byText(ref && (ref.what || ref.text));
  }
  var PROPS = ["width", "height", "margin", "padding", "border-radius", "border", "background-color", "color", "font-size",
               "font-weight", "line-height", "text-align", "display", "order", "margin-left", "margin-right"];
  // What sits in a container, left to right (bare text too: a title that is plain text is part of the row)
  function rowOf(p, mark, pr) {
    var out = [];
    Array.prototype.forEach.call(p.childNodes, function (c) {
      if (out.length >= 8) return;
      if (c.nodeType === 3) {
        if (!c.textContent.trim()) return;
        var rg = document.createRange(); rg.selectNodeContents(c);
        var b = rg.getBoundingClientRect();
        if (b.width) out.push("text «" + c.textContent.trim().slice(0, 14) + "» @" + Math.round(b.left - pr.left) + "–" + Math.round(b.right - pr.left));
        return;
      }
      if (c.nodeType !== 1 || !c.getClientRects().length) return;
      var cr = c.getBoundingClientRect();
      out.push((c === mark ? "▶" : "") + (c.textContent.replace(/\s+/g, " ").trim().slice(0, 14) || label(c)) + " @" + Math.round(cr.left - pr.left) + "–" + Math.round(cr.right - pr.left));
    });
    return out;
  }
  function profile(el) {
    var r = el.getBoundingClientRect(), cs = getComputedStyle(el), p = el.parentElement, pr = p.getBoundingClientRect(), ps = getComputedStyle(p);
    var prev = el.previousElementSibling; while (prev && !prev.getClientRects().length) prev = prev.previousElementSibling;
    var next = el.nextElementSibling; while (next && !next.getClientRects().length) next = next.nextElementSibling;
    var o = { el: el, label: label(el), text: el.textContent.replace(/\s+/g, " ").trim().slice(0, 30),
              box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
              in: label(p), fromTop: Math.round(r.top - pr.top), fromLeft: Math.round(r.left - pr.left),
              fromRight: Math.round(pr.right - r.right), fromBottom: Math.round(pr.bottom - r.bottom),
              gapBefore: prev ? Math.round(/column|block/.test(ps.display + ps.flexDirection) && !/row/.test(ps.flexDirection) ? r.top - prev.getBoundingClientRect().bottom : r.left - prev.getBoundingClientRect().right) : null,
              gapAfter: next ? Math.round(/column|block/.test(ps.display + ps.flexDirection) && !/row/.test(ps.flexDirection) ? next.getBoundingClientRect().top - r.bottom : next.getBoundingClientRect().left - r.right) : null,
              parent: ps.display + (/flex/.test(ps.display) ? " " + ps.flexDirection + ", justify " + ps.justifyContent + ", align " + ps.alignItems + ", gap " + ps.gap : "")
                      + ", padding " + ps.padding,
              row: rowOf(p, el, pr),
              inside: Array.prototype.filter.call(el.children, function (c) { return c.getClientRects().length; }).length > 1 ? rowOf(el, null, r) : null,
              css: {}, text_at: textAt(el) };
    PROPS.forEach(function (k) { o.css[k] = cs.getPropertyValue(k); });
    o.own = el.getAttribute("style") || "";                       // its own style attribute (set by the app's code)
    o.deco = ["::before", "::after"].map(function (pe) {          // decorations drawn by CSS
      var ps2 = getComputedStyle(el, pe);
      return ps2.content && ps2.content !== "none" && ps2.content !== "normal"
        ? pe + " " + ps2.content.slice(0, 20) + " " + ps2.width + "×" + ps2.height + (ps2.backgroundColor !== "rgba(0, 0, 0, 0)" ? " bg " + ps2.backgroundColor : "") + " margin " + ps2.margin : "";
    }).filter(Boolean);
    o.states = stateRules(el);
    o.scrolls = scrollHow(el);
    return o;
  }
  // How an element behaves while scrolling: with the page, inside its own scroll area, or held in place by a sticky or
  // fixed container (with its offset) — the setup to copy when something should behave like it.
  function scrollHow(el) {
    var inner = null, held = null;
    for (var s = el; s && s !== document.body; s = s.parentElement) {
      var cs = getComputedStyle(s);
      if (!held && /sticky|fixed/.test(cs.position)) held = (s === el ? "itself" : label(s)) + " is " + cs.position + " (top " + cs.top + ", selector " + selectorFor(s) + ")";
      if (!inner && s !== el && /auto|scroll/.test(cs.overflowY) && s.scrollHeight > s.clientHeight + 4)
        inner = label(s) + " (selector " + selectorFor(s) + ", " + s.clientHeight + " px high, overflow-y " + cs.overflowY + ", max-height " + cs.maxHeight + ")";
    }
    var own = null;                                         // its content may scroll in an area of its own inside it
    if (!inner) qa("*").some(function (c) {
      if (!el.contains(c) || c === el) return false;
      var cs2 = getComputedStyle(c);
      if (/auto|scroll/.test(cs2.overflowY) && c.scrollHeight > c.clientHeight + 4) {
        own = label(c) + " (selector " + selectorFor(c) + ", " + c.clientHeight + " px high, overflow-y " + cs2.overflowY + ", max-height " + cs2.maxHeight + ")";
        return true;
      }
      return false;
    });
    return "while scrolling: " + (inner ? "scrolls inside its own area " + inner : own ? "its content scrolls inside " + own : "scrolls with the page")
      + (held ? "; stays in place because " + held : "");
  }
  // Rules that apply only on hover, focus or press: the states inspect can't see on screen right now.
  function stateRules(el) {
    var out = [];
    Array.prototype.forEach.call(document.styleSheets, function (sh) {
      var list;
      try { list = sh.cssRules; } catch (e) { return; }
      (function walk(rs) {
        Array.prototype.forEach.call(rs || [], function (r) {
          if (out.length >= 4) return;
          if (r.cssRules && !r.selectorText) return (r.media && r.media.mediaText && !matchMedia(r.media.mediaText).matches) ? null : walk(r.cssRules);   // a media rule only when it applies now
          if (!r.selectorText || !/:(hover|focus|focus-visible|focus-within|active)\b/.test(r.selectorText)) return;
          r.selectorText.split(",").some(function (sel) {
            var m = /:(hover|focus-visible|focus-within|focus|active)\b/.exec(sel);
            if (!m) return false;
            var bare = sel.replace(/:(hover|focus-visible|focus-within|focus|active)\b/g, "").trim();
            try { if (!bare || !el.matches(bare)) return false; } catch (e) { return false; }
            out.push("on " + m[1] + ": " + r.style.cssText.slice(0, 90));
            return true;
          });
        });
      })(list);
    });
    return out;
  }
  // The full-width bars held at the top of the screen (header, toolbars): where the content area starts.
  function topBars() {
    return qa("body *").filter(function (e) {
      var p = getComputedStyle(e).position, r = e.getBoundingClientRect();
      return (p === "sticky" || p === "fixed") && r.width > innerWidth * 0.85 && r.top < 200;
    }).reduce(function (m, e) { return Math.max(m, Math.round(e.getBoundingClientRect().bottom)); }, 0);
  }
  // The area an element's content scrolls in: itself, or the first scrolling area inside it.
  function ownScroller(el) {
    var cs = getComputedStyle(el);
    if (/auto|scroll/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 4) return el;
    var hit = null;
    qa("*").some(function (c) {
      if (c === el || !el.contains(c)) return false;
      var c2 = getComputedStyle(c);
      if (/auto|scroll/.test(c2.overflowY) && c.scrollHeight > c.clientHeight + 4) { hit = c; return true; }
      return false;
    });
    return hit;
  }
  // The relation the owner sees, measured in every state: each element's gap under the top bars at rest, with the page
  // scrolled, and with its own content scrolled. Scrolls are put straight back before the browser paints.
  // What the owner sees right under the top bars, above an element: how many px down its own pixels start (a strip or
  // the page between them counts as gap; something else's pixels count as gap too, and are named). -> number or null
  function seenGap(el, bars) {
    var r = el.getBoundingClientRect(), x = Math.round(Math.min(Math.max(r.left + Math.min(r.width / 2, 120), 1), innerWidth - 2));
    for (var y = bars; y < Math.min(bars + 80, innerHeight); y++) {
      var at = document.elementFromPoint(x, y);
      if (at && (at === el || el.contains(at))) return y - bars;
    }
    return null;
  }
  // The relation the owner sees, measured in every state, the same way each time: with the page at the top ("at
  // rest"), scrolled down 600 px, and with the element's own content scrolled. For each: how far down under the top
  // bars the element's own pixels show (what the owner sees), and where its box is. Everything is put back before the
  // browser paints.
  function relation(els, names) {
    var was = scrollY, max = document.documentElement.scrollHeight - innerHeight, rows = [];
    var take = function (label) {
      var bars = topBars();
      rows.push(label + " (bars end at " + bars + "): " + els.map(function (e, i) {
        var g = seenGap(e, bars);
        return names[i] + " shows " + (g === null ? "nothing in the first 80 px under the bars" : g + " px under the bars")
          + " (its box top " + (Math.round(e.getBoundingClientRect().top) - bars) + ")";
      }).join(" · "));
    };
    scrollTo(scrollX, 0); take("At rest, page at the top");
    if (max >= 40) { scrollTo(scrollX, Math.min(600, max)); take("Page scrolled " + Math.min(600, max) + " px"); }
    else rows.push("(the page itself doesn't scroll)");
    scrollTo(scrollX, 0);
    els.forEach(function (e, i) {
      var box = ownScroller(e);
      if (!box) return;
      var t0 = box.scrollTop; box.scrollTop = Math.min(t0 + 300, box.scrollHeight - box.clientHeight);
      var bars = topBars(), g = seenGap(e, bars);
      rows.push("With " + names[i] + "'s own content scrolled: it shows " + (g === null ? "nothing in the first 80 px" : g + " px under the bars"));
      box.scrollTop = t0;
    });
    scrollTo(scrollX, was);
    return "Gaps as the owner sees them (an element whose box scrolls away under the bars can still show a gap: what "
      + "counts is where its pixels start):\n" + rows.join("\n");
  }
  // How an element is set up to behave while scrolling, and what to copy to make another behave like it.
  function setupOf(el) {
    var o = { box: ownScroller(el), sticky: null };
    for (var s = el; s && s !== document.body; s = s.parentElement) {
      var cs = getComputedStyle(s);
      if (/sticky|fixed/.test(cs.position)) { o.sticky = { el: s, top: cs.top }; break; }
    }
    if (o.box) {
      var mh = rulesSetting(o.box, "max-height")[0] || rulesSetting(o.box, "height")[0];
      o.limit = mh ? mh.slice(0, mh.lastIndexOf(" (") > 0 ? mh.lastIndexOf(" (") : mh.length) : "max-height: " + o.box.clientHeight + "px";   // the value as written, its source dropped
      o.ovf = getComputedStyle(o.box).overflowY;
    }
    return o;
  }
  function recipe(a, ka, b, kb) {
    var sa = setupOf(a), sb = setupOf(b), out = [];
    if (sb.box && !sa.box)
      out.push("its content scrolls inside " + label(sb.box) + " (" + sb.limit + "; overflow-y: " + sb.ovf + "), so its box stays put while "
        + "the content moves: give " + ka + " (" + selectorFor(a) + ") the same: " + sb.limit + "; overflow-y: " + sb.ovf + "; the page then "
        + "no longer needs to scroll it");
    if (sb.sticky && !sa.sticky) out.push(kb + " is held by position: sticky; top: " + sb.sticky.top + " on " + label(sb.sticky.el) + "; " + ka + " isn't");
    if (!sb.box && sa.box) out.push(ka + " scrolls inside its own area and " + kb + " doesn't: remove " + ka + "'s scroll area (max-height/overflow) to match");
    return out.length ? "To behave like " + kb + " while scrolling: " + out.join("; ") : "";
  }

  function inspect(spec) {
    var marked = (spec.marked || []).map(function (s) { return find({ selector: s }); });
    var refs = (spec.refers || []).map(function (r) { return { ref: r, el: find(r) }; });
    var lines = [], profs = [];
    var all = [], names = [];
    marked.forEach(function (e, i) { if (e) { all.push(e); names.push(String.fromCharCode(65 + i)); } });
    refs.forEach(function (x, j) { if (x.el) { all.push(x.el); names.push("R" + (j + 1)); } });
    if (all.length) lines.push(relation(all, names));
    marked.forEach(function (el, i) {
      if (!el) return lines.push(String.fromCharCode(65 + i) + ": not found on screen (" + spec.marked[i] + ")");
      var pa = profile(el); profs.push(pa);
      lines.push(describeProfile(String.fromCharCode(65 + i), pa));
      refs.forEach(function (rf, j) {
        if (!rf.el) return lines.push("Referent " + (j + 1) + " (" + (rf.ref.what || rf.ref.selector) + "): not found on screen");
        if (rf.el === el) return;
        var pb = profile(rf.el);
        lines.push(describeProfile("R" + (j + 1) + " (" + (rf.ref.what || "").slice(0, 40) + ")", pb));
        lines.push(compare(String.fromCharCode(65 + i), pa, "R" + (j + 1), pb));
        var how = recipe(el, String.fromCharCode(65 + i), rf.el, "R" + (j + 1));
        if (how) lines.push(how);
      });
    });
    return lines.join("\n");
  }
  function describeProfile(k, o) {
    return k + " = " + o.label + (o.text ? " «" + o.text + "»" : "") + " [selector: " + selectorFor(o.el) + "; its container: " + selectorFor(o.el.parentElement) + "]"
      + ": box x" + o.box[0] + " y" + o.box[1] + " " + o.box[2] + "×" + o.box[3]
      + "; in " + o.in + ": " + o.fromTop + " from top, " + o.fromLeft + " from left, " + o.fromRight + " from right, " + o.fromBottom + " from bottom"
      + (o.gapBefore !== null ? "; gap to the item before " + o.gapBefore : "") + (o.gapAfter !== null ? ", after " + o.gapAfter : "")
      + "; its row: " + o.row.join(" | ") + (o.inside ? "; inside it: " + o.inside.join(" | ") : "") + "; container: " + o.parent
      + "; font " + o.css["font-size"] + " " + o.css["font-weight"] + ", colour " + o.css.color + ", background " + o.css["background-color"]
      + ", padding " + o.css.padding + ", margin " + o.css.margin + ", radius " + o.css["border-radius"] + (o.text_at ? "; " + o.text_at : "")
      + (o.own ? "; its own style attribute: " + o.own.slice(0, 120) : "") + (o.deco.length ? "; " + o.deco.join("; ") : "")
      + (o.states.length ? "; " + o.states.join("; ") : "") + "; " + o.scrolls;
  }
  function compare(ka, a, kb, b) {
    var d = [];
    [["fromTop", "from container top"], ["fromLeft", "from container left"], ["fromRight", "from container right"], ["fromBottom", "from container bottom"],
     ["gapBefore", "gap to the item before"]].forEach(function (x) {
      if (a[x[0]] !== null && b[x[0]] !== null && Math.abs(a[x[0]] - b[x[0]]) > 1) d.push(x[1] + ": " + a[x[0]] + " vs " + b[x[0]]);
    });
    if (Math.abs(a.box[2] - b.box[2]) > 1 && a.label.split(".")[0] === b.label.split(".")[0]) d.push("width: " + a.box[2] + " vs " + b.box[2]);
    if (Math.abs(a.box[3] - b.box[3]) > 1) d.push("height: " + a.box[3] + " vs " + b.box[3]);
    if (a.parent !== b.parent) d.push("container layout: " + a.parent + " vs " + b.parent);
    PROPS.forEach(function (k) {
      if (k === "width" || k === "height" || a.css[k] === b.css[k]) return;
      var why = function (o) {                // the rule behind it: the property itself, else its long forms (margin-top …)
        if (o.el.style.getPropertyValue(k)) return "(its own style attribute)";
        var rs = rulesSetting(o.el, k);
        if (rs.length) return rs[0].replace(/^[^(]*/, "");
        var longs = k === "border-radius" ? ["border-top-left-radius", "border-top-right-radius", "border-bottom-left-radius", "border-bottom-right-radius"]
          : /^(margin|padding)$/.test(k) ? [k + "-top", k + "-right", k + "-bottom", k + "-left"] : [];
        longs.forEach(function (key) { rs = rs.concat(rulesSetting(o.el, key)); });
        return rs.length ? "[" + rs.slice(0, 2).join("; ") + "]" : "(default)";
      };
      d.push(k + ": " + a.css[k] + " " + why(a) + " vs " + b.css[k] + " " + why(b));
    });
    var place = ["margin-left", "margin-right", "order"].map(function (k) { return [k, rulesSetting(a.el, k), rulesSetting(b.el, k)]; })
      .filter(function (x) { return x[1].length || x[2].length; });
    place.forEach(function (x) { d.push("rules for " + x[0] + ": " + (x[1][0] || "none") + " vs " + (x[2][0] || "none")); });
    return "Differs " + ka + " vs " + kb + ": " + (d.length ? d.join("; ") : "nothing measurable");
  }

  // ---- what the design view's headless browser asks of the page (mirror.js takes the pictures; this page draws none) ---
  // Where each element a change is about is on screen (what changed, then what it was compared with), for the
  // headless browser's close-ups: [{label, what, x, y, w, h}].
  function rects(spec) {
    var list = [];
    (spec.marked || []).forEach(function (sl, i) { var el = find({ selector: sl }); if (el) list.push({ el: el, label: String.fromCharCode(65 + i), what: sl }); });
    (spec.refers || []).forEach(function (r, i) { var el = find(r); if (el && !list.some(function (x) { return x.el === el; })) list.push({ el: el, label: "R" + (i + 1), what: r.what || r.selector }); });
    return list.slice(0, 4).map(function (x) {
      var b = x.el.getBoundingClientRect();
      return { label: x.label, what: x.what, x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) };
    });
  }
  // How the screen scrolls around the first element a change is about: how far the page goes, and the list that scrolls
  // it (its own, or the one it sits in).
  function scrolling(spec) {
    var el = null;
    (spec.marked || []).concat((spec.refers || []).map(function (r) { return r.selector; })).some(function (sl) { el = find({ selector: sl }); return !!el; });
    var max = document.documentElement.scrollHeight - innerHeight, out = { page: max >= 40 ? Math.min(600, max) : 0 };
    var box = el && ownScroller(el);
    for (var p = el && el.parentElement; !box && p && p !== document.body; p = p.parentElement) {
      var cs = getComputedStyle(p);
      if (/auto|scroll/.test(cs.overflowY) && p.scrollHeight > p.clientHeight + 4) box = p;
    }
    if (box) out.box = { sel: selectorFor(box), what: label(box), by: Math.min(300, box.scrollHeight - box.clientHeight) };
    return out;
  }
  // What is drawn in a spot of the screen ({x, y, w, h}), as text the designer reads exactly (a model reads text far
  // better than fine pixels): each line (a border's edge), filled box, piece of text, picture or icon, decoration and
  // scrollbar that shows there, placed from the spot's top-left. -> lines of text
  function drawn(r) {
    var R = { l: r.x, t: r.y, r: r.x + r.w, b: r.y + r.h }, lines = [], boxes = [], texts = [], other = [], holder = null;
    var px = Math.round, X = function (v) { return px(v - R.l); }, Y = function (v) { return px(v - R.t); };
    var hex = function (c) {
      var m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/.exec(c || "");
      if (!m || m[4] === "0") return null;
      return "#" + [m[1], m[2], m[3]].map(function (x) { return ("0" + (+x | 0).toString(16)).slice(-2); }).join("")
        + (m[4] && +m[4] < 1 ? " at " + px(m[4] * 100) + "%" : "");
    };
    var name = function (el) {
      var t = (el.getAttribute("aria-label") || el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 24);
      return label(el) + (t ? ' "' + t + '"' : "");
    };
    qa("body *").forEach(function (el) {
      if (el.closest("#dv-mirror-marks")) return;
      var b = el.getBoundingClientRect();
      if (!b.width || !b.height || b.right <= R.l || b.left >= R.r || b.bottom <= R.t || b.top >= R.b) return;
      var cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || +cs.opacity === 0) return;
      var covers = b.left <= R.l && b.top <= R.t && b.right >= R.r && b.bottom >= R.b;
      if (covers) holder = el;                               // the deepest one holding the whole spot: its backdrop
      // A border all round a thing that sits wholly in the spot is its outline (a box, said once below); a border on one
      // or two sides, or an edge running through the spot, is a line (a divider), as a person would describe it.
      var sideOn = function (sd) { return parseFloat(cs["border" + sd + "Width"]) && cs["border" + sd + "Style"] !== "none" && hex(cs["border" + sd + "Color"]); };
      var outlined = ["Left", "Right", "Top", "Bottom"].every(sideOn), whole = b.left >= R.l && b.top >= R.t && b.right <= R.r && b.bottom <= R.b;
      if (!(outlined && whole)) [["Left", "vertical", b.left, 1], ["Right", "vertical", b.right - 1, 1], ["Top", "horizontal", b.top, 0], ["Bottom", "horizontal", b.bottom - 1, 0]].forEach(function (e) {
        var w = parseFloat(cs["border" + e[0] + "Width"]), c = hex(cs["border" + e[0] + "Color"]), at = e[2], v = e[3];
        if (!w || cs["border" + e[0] + "Style"] === "none" || !c) return;
        if (v ? (at < R.l || at > R.r) : (at < R.t || at > R.b)) return;
        var from = v ? Math.max(b.top, R.t) : Math.max(b.left, R.l), to = v ? Math.min(b.bottom, R.b) : Math.min(b.right, R.r);
        lines.push({ v: v, at: v ? X(at) : Y(at), t: e[1] + " line at " + (v ? "x " + X(at) + " (from y " + Y(from) + " to " + Y(to) : "y " + Y(at) + " (from x " + X(from) + " to " + X(to))
          + "), " + w + "px " + c + ": the " + e[0].toLowerCase() + " border of " + name(el) });
      });
      if (!covers) {
        var bg = hex(cs.backgroundColor);
        if (bg || cs.backgroundImage !== "none" || cs.boxShadow !== "none" || (outlined && whole))
          boxes.push(name(el) + ": a box x " + X(b.left) + "–" + X(b.right) + ", y " + Y(b.top) + "–" + Y(b.bottom) + (bg ? ", fill " + bg : "")
            + (outlined && whole ? ", outlined " + cs.borderTopWidth + " " + hex(cs.borderTopColor) : "")
            + (cs.backgroundImage !== "none" ? ", a background image" : "") + (parseFloat(cs.borderTopLeftRadius) ? ", rounded " + cs.borderTopLeftRadius : "")
            + (cs.boxShadow !== "none" ? ", a shadow" : ""));
      }
      Array.prototype.forEach.call(el.childNodes, function (n) {
        if (n.nodeType !== 3 || !n.textContent.trim()) return;
        var rg = document.createRange(); rg.selectNodeContents(n);
        var tb = rg.getBoundingClientRect(), rows = rg.getClientRects().length;
        if (!tb.width || tb.right <= R.l || tb.left >= R.r || tb.bottom <= R.t || tb.top >= R.b) return;
        texts.push('text "' + n.textContent.trim().replace(/\s+/g, " ").slice(0, 40) + '" x ' + X(tb.left) + "–" + X(tb.right) + ", y " + Y(tb.top) + "–" + Y(tb.bottom)
          + " (" + cs.fontSize + " " + (hex(cs.color) || cs.color) + (rows > 1 ? ", on " + rows + " rows" : "") + ", in " + label(el) + ")");
      });
      if (/^(img|svg|canvas|video)$/i.test(el.tagName))
        other.push((/^img$/i.test(el.tagName) ? "picture " : "icon/graphic ") + name(el) + " x " + X(b.left) + "–" + X(b.right) + ", y " + Y(b.top) + "–" + Y(b.bottom));
      ["::before", "::after"].forEach(function (p) {
        var pc = getComputedStyle(el, p);
        if (pc.content && pc.content !== "none" && pc.content !== "normal" && pc.display !== "none")
          other.push("decoration " + p + " of " + name(el) + " (content " + pc.content.slice(0, 20) + (hex(pc.backgroundColor) ? ", fill " + hex(pc.backgroundColor) : "")
            + (parseFloat(pc.borderLeftWidth) || parseFloat(pc.borderTopWidth) ? ", with a border" : "") + ", " + pc.width + "×" + pc.height + ")");
      });
      var sbw = el.offsetWidth - el.clientWidth - parseFloat(cs.borderLeftWidth || 0) - parseFloat(cs.borderRightWidth || 0);
      if (/auto|scroll/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 4 && sbw > 1 && b.right >= R.l && b.right - sbw <= R.r)
        other.push("a scrollbar of " + name(el) + " at x " + X(b.right - sbw) + "–" + X(b.right));
    });
    lines.sort(function (a, b) { return a.v === b.v ? a.at - b.at : b.v - a.v; });   // vertical lines first, left to right
    var hb = holder && hex(getComputedStyle(holder).backgroundColor);
    return ["The spot is " + px(r.w) + "×" + px(r.h) + " px" + (holder ? ", on " + name(holder) + (hb ? " (fill " + hb + ")" : "") : "") + "; positions are px from its top-left."]
      .concat(lines.slice(0, 24).map(function (l) { return l.t; }), texts.slice(0, 16), boxes.slice(0, 12), other.slice(0, 10)).join("\n");
  }
  // The owner's screen as it is now, for the headless browser to show the same: window size, scroll, the lists
  // scrolled inside it, the option being looked at.
  function view() {
    var sc = [];
    qa("body *").forEach(function (e) {
      if (sc.length < 8 && (e.scrollTop > 0 || e.scrollLeft > 0)) sc.push({ sel: selectorFor(e), top: e.scrollTop, left: e.scrollLeft });
    });
    return { route: route(), w: innerWidth, h: innerHeight, scroll: Math.round(scrollY), scrollers: sc,
             opt: active ? active.set + ":" + active.choice : "none" };
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

  // ---- what the page saw, kept with a build note: the owner's last actions on the page and the errors it
  // logged (a failed picture or script too), sent with each note. Not in a side-by-side or measuring frame.
  var trail = [], errs = [];
  function keep(list, item) { item.t = Date.now() / 1000; list.push(item); if (list.length > 12) list.shift(); }
  if (!fixed) {
    document.addEventListener("click", function (ev) {
      if (picking || !ev.target || !ev.target.closest) return;
      var el = ev.target.closest("button, a, input, select, textarea, label, summary, [role=button], [data-dv-link]") || ev.target;
      keep(trail, { did: "click", on: selectorFor(el), text: (el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 40), route: route() });
    }, true);
    document.addEventListener("change", function (ev) {
      var el = ev.target; if (!el || !el.tagName || picking) return;
      var file = el.type === "file", v = file ? Array.prototype.map.call(el.files || [], function (f) { return f.name + " (" + f.size + " B)"; }).join(", ")
        : el.type === "password" ? "(hidden)" : String(el.value == null ? "" : el.value).slice(0, 60);
      keep(trail, { did: file ? "chose file" : "set", on: selectorFor(el), text: v, route: route() });
    }, true);
    addEventListener("error", function (ev) {
      var t = ev.target;
      if (t && t !== window && t.tagName) {                // a picture, script or stylesheet that didn't load
        var src = (t.currentSrc || t.src || t.href || "").replace(location.origin, "");
        if (!/\/dv\//.test(src)) keep(errs, { kind: "didn't load", text: t.tagName.toLowerCase() + " " + src.slice(0, 200) });
        return;
      }
      var f = (ev.filename || "").replace(location.origin, "");
      if (!/\/dv\//.test(f)) keep(errs, { kind: "error", text: (ev.message || "error") + (f ? " at " + f + ":" + ev.lineno : "") });
    }, true);
    addEventListener("unhandledrejection", function (ev) {
      var r = ev.reason; keep(errs, { kind: "promise", text: String(r && (r.message || r) || "rejected").slice(0, 300) });
    });
    var consoleError = console.error;
    console.error = function () {
      try {
        keep(errs, { kind: "console", text: Array.prototype.map.call(arguments, function (a) {
          return a instanceof Error ? a.message : typeof a === "object" ? JSON.stringify(a) : String(a);
        }).join(" ").slice(0, 300) });
      } catch (e) {}
      return consoleError.apply(console, arguments);
    };
  }

  window.__dv = {
    ready: function () { return ready; },
    view: view,
    rects: rects,
    drawn: drawn,
    scrolling: scrolling,
    inspect: inspect,
    trail: function () { return trail.slice(); },
    errors: function () { return errs.slice(); },
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
