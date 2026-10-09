/* live-reload.js: a demo page updates itself while the owner looks at it.
   The inbox adds it to every demo slot's review link (feedback-inbox.py), so no page needs its own copy.
   Polls the page's own files with cache:"no-store" every second:
     CSS  -> swap the stylesheet in place (restyle, no reload)
     HTML -> morph only the changed nodes into the live body (keeps scroll, focus and the Mark overlay)
   If a fetch or a morph fails, it reloads once as the fallback and says why on the page; never silently.
   A page can name other files to watch: <body data-live-watch="index.html style.css">. */
(function () {
  "use strict";
  if (window.__liveReload) return;
  window.__liveReload = true;

  // The page's own <body data-live-watch="..."> can name the files to watch (re-read every poll). Default:
  // the page itself (index.html for a folder's root) and the folder's stylesheet.
  var PAGE = (location.pathname.split("/").pop() || "index.html");
  var DEFAULT = [PAGE, "style.css"];
  var POLL_MS = 1000;
  var RELOAD_WINDOW_MS = 15000;

  function watchList() {
    var a = document.body && document.body.getAttribute("data-live-watch");
    var list = a ? a.trim().split(/\s+/).filter(Boolean) : DEFAULT;
    return list.length ? list : DEFAULT;
  }

  var seen = {};   // path -> last seen text
  var first = true; // first pass only records the baseline

  /* ---- the notice: never fail silently ---- */
  var noticeKind = null, noticeTimer = 0;
  function hideNotice() {
    var n = document.getElementById("__live_notice");
    if (n && n.parentNode) n.parentNode.removeChild(n);
    noticeKind = null;
  }
  function notice(msg, kind) {
    var el = document.getElementById("__live_notice");
    if (!el) {
      el = document.createElement("div");
      el.id = "__live_notice";
      el.setAttribute("role", "status");
      el.style.cssText = [
        "position:fixed", "left:12px", "right:12px", "bottom:12px",
        "z-index:2147483647", "max-width:640px", "margin:0 auto",
        "padding:10px 14px", "border-radius:10px",
        "font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace",
        "color:#F4F3F0", "background:#1b1d22",
        "border:1px solid #343841", "box-shadow:0 10px 30px rgba(0,0,0,.5)"
      ].join(";");
      (document.body || document.documentElement).appendChild(el);
    }
    el.textContent = "Live update: " + msg;
    noticeKind = kind || "info";
    clearTimeout(noticeTimer);
    if (noticeKind !== "fault") noticeTimer = setTimeout(hideNotice, 8000); // a fallback reload fades; a fault stays
  }

  function once(key, msg, text) {
    var now = Date.now(), last = 0;
    try { last = +sessionStorage.getItem(key + "_at") || 0; } catch (e) {}
    try {
      sessionStorage.setItem(key, msg);
      sessionStorage.setItem(key + "_at", String(now));
    } catch (e) {}
    if (now - last > RELOAD_WINDOW_MS) { location.reload(); return; }
    notice(text + " — reloaded once, not reloading again.", "fault");
  }

  function fault(msg) {
    once("__live_fault", msg, msg);
  }

  function reloadFor(msg) {
    once("__live_reload", msg, msg);
  }

  // Show, after a fallback reload, why we reloaded.
  try {
    var fm = sessionStorage.getItem("__live_fault");
    if (fm) {
      sessionStorage.removeItem("__live_fault");
      notice(fm + " — reloaded once as a fallback.", "fault");
    }
    var rm = sessionStorage.getItem("__live_reload");
    if (rm) {
      sessionStorage.removeItem("__live_reload");
      notice(rm + " — reloaded once.", "info");
    }
  } catch (e) {}

  /* ---- fetch: always fresh ---- */
  function grab(path) {
    return fetch(path + "?__live=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        if (r.status === 404) return null;   // a file the page doesn't have (no style.css): nothing to watch
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      });
  }

  /* ---- CSS: swap in place, keep the running DOM ---- */
  function applyCss(text) {
    var s = document.getElementById("__live_css");
    if (!s) {
      s = document.createElement("style");
      s.id = "__live_css";
      document.head.appendChild(s);
      var link = document.querySelector('link[rel="stylesheet"][href$="style.css"]');
      if (link) link.disabled = true; // the old copy must stop fighting the new one
    }
    s.textContent = text;
  }

  /* ---- HTML: morph changed nodes only; never touch scripts/overlay ---- */
  function keep(n) {
    if (n.nodeType !== 1) return false;
    var t = n.tagName;
    if (t === "SCRIPT" || t === "STYLE" || t === "LINK") return true;
    var id = n.id || "";
    if (id.indexOf("__live") === 0 || id.indexOf("mark") !== -1) return true;
    return n.hasAttribute && (n.hasAttribute("data-mark") || n.hasAttribute("data-live-keep"));
  }

  function matchNode(live, src) {
    if (src.nodeType === 3) return live.nodeType === 3;
    if (src.nodeType === 8) return live.nodeType === 8;
    if (src.nodeType !== 1 || live.nodeType !== 1) return false;
    if (live.tagName !== src.tagName) return false;
    if (src.id) return live.id === src.id;
    return true;
  }

  function syncAttrs(live, src) {
    var i, a = src.attributes;
    for (i = 0; i < a.length; i++) {
      if (live.getAttribute(a[i].name) !== a[i].value) {
        live.setAttribute(a[i].name, a[i].value);
      }
    }
    var names = [], la = live.attributes;
    for (i = 0; i < la.length; i++) names.push(la[i].name);
    names.forEach(function (nm) { if (!src.hasAttribute(nm)) live.removeAttribute(nm); });
  }

  function morph(live, src) {
    if (live.nodeType === 3 || live.nodeType === 8) {
      if (live.nodeValue !== src.nodeValue) live.nodeValue = src.nodeValue;
      return;
    }
    if (live.nodeType !== 1 || live.tagName !== src.tagName) {
      live.parentNode.replaceChild(document.importNode(src, true), live);
      return;
    }
    if (live.tagName === "SCRIPT" || live.tagName === "STYLE" || live.tagName === "LINK") return;
    syncAttrs(live, src);
    morphChildren(live, src);
  }

  function morphChildren(liveParent, srcParent) {
    var src = Array.prototype.slice.call(srcParent.childNodes);
    var kids = function () { return Array.prototype.slice.call(liveParent.childNodes); };
    var idx = 0;
    for (var s = 0; s < src.length; s++) {
      var sc = src[s], list = kids(), lc = list[idx];
      if (lc && matchNode(lc, sc)) {
        morph(lc, sc);
        idx++;
        continue;
      }
      var found = -1;
      for (var k = idx + 1; k < list.length; k++) {
        if (matchNode(list[k], sc)) { found = k; break; }
      }
      if (found > -1) {
        for (var j = found - 1; j >= idx; j--) {
          if (!keep(list[j])) list[j].parentNode.removeChild(list[j]);
        }
        morph(list[found], sc);
        idx = kids().indexOf(list[found]) + 1;
      } else {
        liveParent.insertBefore(document.importNode(sc, true), kids()[idx] || null);
        idx++;
      }
    }
    var rest = kids();
    for (var r = idx; r < rest.length; r++) {
      if (!keep(rest[r])) rest[r].parentNode.removeChild(rest[r]);
    }
  }

  function applyHtml(text) {
    var doc = new DOMParser().parseFromString(text, "text/html");
    if (doc.title && doc.title !== document.title) document.title = doc.title;
    syncAttrs(document.body, doc.body);
    morphChildren(document.body, doc.body);
  }

  /* ---- the loop ---- */
  function changed(path, text) {
    seen[path] = text;
    if (path === "style.css") applyCss(text);
    else if (/\.js$/.test(path)) reloadFor(path + " changed");
    else if (/\.html?$/.test(path)) applyHtml(text);
  }

  function poll() {
    Promise.all(watchList().map(function (p) {
      return grab(p).then(
        function (t) { return { p: p, t: t, ok: true }; },
        function (e) { return { p: p, e: e, ok: false }; }
      );
    })).then(function (res) {
      var why = null;
      if (first) {
        res.forEach(function (r) { if (r.ok) seen[r.p] = r.t; });
        first = false;
      } else {
        // Apply every healthy change even when a sibling file failed. The watch list is delivered by a
        // watched file (index.html), so bailing on the first error deadlocks: fix index.html and the fix
        // never lands because a stale entry still 404s. Each file is independent here.
        res.forEach(function (r) {
          if (!r.ok || r.t === null || seen[r.p] === r.t) return;
          try { changed(r.p, r.t); }
          catch (err) { if (!why) why = "couldn't apply " + r.p + " (" + err.message + ")"; }
        });
      }
      res.forEach(function (r) {
        if (!r.ok && !why) why = "can't fetch " + r.p + " (" + r.e.message + ")";
      });
      if (why) { fault(why); return; }
      // Every file fetched and every change applied this pass: a fault notice is stale now, clear it.
      if (noticeKind === "fault") {
        hideNotice();
        try {
          sessionStorage.removeItem("__live_fault");
          sessionStorage.removeItem("__live_fault_at");
        } catch (e) {}
      }
    }, function (err) { fault("watcher error (" + err.message + ")"); });
  }

  setInterval(poll, POLL_MS);
  poll();
})();
