/* kit.js: a prototype's engine. Pages, navigation, sample data and simulated behaviour, all declared in plain HTML,
   so a skeleton site is navigable from the first minute and the Designer never writes a script.
   `look.py proto new <name>` copies this into the prototype's folder; don't edit the copy.

   Pages     pages/<page>.html is shown in [data-outlet] for #/<page>[/<arg>...]; #/ is pages/home.html.
             Links: href="#/deck/Burn". The nav link whose data-route matches the page gets .is-active.
   Data      data.json. {{path}} in a page fills from it ({{app.name}}), {{$1}} is the first route arg.
             <ul data-each="decks"><li>{{name}}</li></ul> repeats its contents per item ({{name}}, {{$i}}).
             <section data-find="decks name $1"> fills its contents from the item whose name is the route arg.
   Behaviour (simulated: nothing is saved)
             data-goto="#/deck/{{name}}"   click navigates          data-toggle="<sel>"   show/hide
             data-open="<sel>" / data-close  a dialog or a panel      data-tab="g:a" + data-panel="g:a"  tabs
             data-toast="Saved"            a toast on click         a <form> submit: its data-toast, no reload
   Live      the open page follows the files: a page, data.json or a stylesheet changes and it redraws in place
             (scroll kept); index.html changes and it reloads. */
(function () {
  "use strict";
  if (window.__kit) return;
  window.__kit = true;
  window.__liveReload = true;                          // this page keeps itself live; the demo's watcher stands down
  var outlet = document.querySelector("[data-outlet]"), data = {}, seen = {}, cur = null;

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function get(obj, path) { return path.split(".").reduce(function (o, k) { return o == null ? o : o[k]; }, obj); }
  function route() {
    var parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
    return { page: parts[0] || "home", args: parts.slice(1) };
  }
  function val(k, ctx, args) {
    if (k[0] === "$") return k === "$i" ? ctx.$i : args[+k.slice(1) - 1];
    var v = get(ctx, k); return v === undefined ? get(data, k) : v;
  }
  function fill(text, ctx, args) {
    return text.replace(/\{\{\s*([$\w.]+)\s*\}\}/g, function (_, k) { var v = val(k, ctx, args); return v == null ? "" : String(v); });
  }
  // Walks the page once, outside in: a data-find or data-each gives its contents their own item, so a list inside a
  // detail section fills from that item ({{name}} in a deck's card list is the card's name, not the deck's).
  function expand(node, ctx, args) {
    Array.prototype.slice.call(node.childNodes).forEach(function (el) {
      if (el.nodeType === 3) { if (el.nodeValue.indexOf("{{") >= 0) el.nodeValue = fill(el.nodeValue, ctx, args); return; }
      if (el.nodeType !== 1) return;
      Array.prototype.slice.call(el.attributes).forEach(function (a) { if (a.value.indexOf("{{") >= 0) a.value = fill(a.value, ctx, args); });
      if (el.hasAttribute("data-find")) {
        var p = el.getAttribute("data-find").split(/\s+/), list = val(p[0], ctx, args) || [], want = p[2] || "";
        if (want[0] === "$") want = args[+want.slice(1) - 1];
        var item = list.find(function (x) { return String(get(x, p[1])) === String(want); });
        el.removeAttribute("data-find");
        if (!item) { el.innerHTML = '<p class="muted">Nothing called "' + esc(want) + '" in the sample data.</p>'; return; }
        expand(el, Object.assign({}, ctx, item), args);
        return;
      }
      if (el.hasAttribute("data-each")) {
        var items = val(el.getAttribute("data-each"), ctx, args) || [], tpl = Array.prototype.slice.call(el.childNodes);
        el.removeAttribute("data-each");
        el.textContent = "";
        items.forEach(function (item, i) {
          var box = document.createElement("div");
          tpl.forEach(function (t) { box.appendChild(t.cloneNode(true)); });
          expand(box, Object.assign({}, ctx, item, { $i: i + 1 }), args);
          while (box.firstChild) el.appendChild(box.firstChild);
        });
        return;
      }
      expand(el, ctx, args);
    });
  }
  function grab(path) {
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) { return r.ok ? r.text() : null; });
  }
  function render(keepScroll) {
    var r = route(), y = scrollY;
    return grab("pages/" + r.page + ".html").then(function (html) {
      seen["pages/" + r.page + ".html"] = html;
      var box = document.createElement("div");
      box.innerHTML = html == null ? '<h1>' + esc(r.page) + '</h1><p class="muted">No page yet: pages/' + esc(r.page) + '.html</p>' : html;
      expand(box, {}, r.args);
      outlet.replaceChildren.apply(outlet, Array.prototype.slice.call(box.childNodes));
      document.querySelectorAll("[data-route]").forEach(function (a) { a.classList.toggle("is-active", a.getAttribute("data-route") === r.page); });
      var h = outlet.querySelector("h1"); if (h && !keepScroll) document.title = h.textContent + " · " + (data.app && data.app.name || "");
      cur = r.page;
      if (keepScroll) scrollTo(0, y); else scrollTo(0, 0);
    });
  }
  function toast(msg) {
    var t = document.querySelector(".toast"); if (!t) return;
    t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(function () { t.hidden = true; }, 1800);
  }
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-goto],[data-toggle],[data-open],[data-close],[data-tab],[data-toast]");
    if (!el) return;
    if (el.hasAttribute("data-goto")) { location.hash = el.getAttribute("data-goto"); }
    if (el.hasAttribute("data-toggle")) { document.querySelectorAll(el.getAttribute("data-toggle")).forEach(function (t) { t.hidden = !t.hidden; }); }
    if (el.hasAttribute("data-open")) { document.querySelectorAll(el.getAttribute("data-open")).forEach(function (t) { t.hidden = false; }); }
    if (el.hasAttribute("data-close")) { var c = el.closest("[data-panel-root],dialog,.modal,[role=dialog]"); if (c) c.hidden = true; }
    if (el.hasAttribute("data-tab")) {
      var v = el.getAttribute("data-tab"), g = v.split(":")[0];
      document.querySelectorAll('[data-tab^="' + g + ':"]').forEach(function (t) { t.classList.toggle("is-active", t === el); });
      document.querySelectorAll('[data-panel^="' + g + ':"]').forEach(function (p) { p.hidden = p.getAttribute("data-panel") !== v; });
    }
    if (el.hasAttribute("data-toast")) toast(el.getAttribute("data-toast"));
    if (el.tagName === "A" && el.getAttribute("href") === "#") e.preventDefault();
  });
  document.addEventListener("submit", function (e) { e.preventDefault(); toast(e.target.getAttribute("data-toast") || "Saved (simulated)"); });
  addEventListener("hashchange", function () { render(false); });

  function poll() {                                    // the page follows its files while the owner looks
    var files = ["pages/" + cur + ".html", "data.json", "style.css", "tokens.css", "index.html"];
    Promise.all(files.map(grab)).then(function (got) {
      var redraw = false;
      got.forEach(function (text, i) {
        var f = files[i];
        if (text == null || seen[f] === undefined) { seen[f] = text; return; }
        if (seen[f] === text) return;
        seen[f] = text;
        if (f === "index.html") { location.reload(); return; }
        if (/\.css$/.test(f)) {
          document.querySelectorAll('link[rel="stylesheet"]').forEach(function (l) {
            if (l.getAttribute("href").split("?")[0] === f) l.href = f + "?t=" + Date.now();
          });
          return;
        }
        if (f === "data.json") { try { data = JSON.parse(text); } catch (err) { return; } }
        redraw = true;
      });
      if (redraw) render(true);
    }).catch(function () {});
  }
  grab("data.json").then(function (t) {
    try { data = t ? JSON.parse(t) : {}; } catch (e) { data = {}; }
    seen["data.json"] = t;
    return render(false);
  }).then(function () { setInterval(poll, 1000); });
  window.kit = { render: render, toast: toast, data: function () { return data; } };
})();
