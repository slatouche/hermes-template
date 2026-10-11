/* behaviors.js: ready-made interactions for the mockup, used by the "behavior" edit:
     {"op":"behavior","name":"<name>","sel":"<elements>", ...options}
   Each is set up once per element (layer.js marks it) and works on whatever the layer has built. New ones are not
   written in a round: the Designer proposes one (vault/design/behaviors/proposed/<name>.js), the Manager reviews it,
   and an approved one (vault/design/behaviors/<name>.js) is served after these, under the same rules:
   window.__dvBehaviors.<name> = function (el, op) { ... }   no network calls, no storage, no eval. */
(function () {
  "use strict";
  var B = window.__dvBehaviors = window.__dvBehaviors || {};
  function all(sel, root) { try { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); } catch (e) { return []; } }

  function flip(nodes, change) {           // animate nodes from where they were to where change() puts them
    var first = nodes.map(function (n) { return n.getBoundingClientRect(); });
    change();
    nodes.forEach(function (n, i) {
      var last = n.getBoundingClientRect(), dx = first[i].left - last.left, dy = first[i].top - last.top;
      if (!dx && !dy) return;
      n.animate([{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }], { duration: 180, easing: "ease-out" });
    });
  }

  // sortable: drag items to reorder them, and between every list matching sel (main deck <-> sideboard).
  //   {"name":"sortable","sel":"<the lists>","item":"<an item, inside a list>"}
  var dragging = null;
  B.sortable = function (list, op) {
    function items() { return op.item ? all(op.item, list) : Array.prototype.slice.call(list.children); }
    function itemOf(n) {
      if (op.item) return n.closest ? n.closest(op.item) : null;
      while (n && n.parentElement !== list) n = n.parentElement;
      return n;
    }
    function arm() { items().forEach(function (n) { if (!n.draggable) { n.draggable = true; n.style.cursor = "grab"; } }); }
    arm();
    new MutationObserver(arm).observe(list, { childList: true });
    list.addEventListener("dragstart", function (ev) {
      var it = itemOf(ev.target);
      if (!it || !list.contains(it)) return;
      dragging = it; it.style.opacity = "0.4";
      ev.dataTransfer.effectAllowed = "move";
      try { ev.dataTransfer.setData("text/plain", ""); } catch (e) {}
    });
    list.addEventListener("dragend", function () { if (dragging) dragging.style.opacity = ""; dragging = null; });
    list.addEventListener("dragover", function (ev) {
      if (!dragging) return;
      ev.preventDefault();
      var others = items().filter(function (n) { return n !== dragging; });
      var after = null;
      for (var i = 0; i < others.length; i++) {
        var r = others[i].getBoundingClientRect();
        if (ev.clientY < r.top + r.height / 2 && (ev.clientX < r.right || r.width > list.clientWidth / 2)) { after = others[i]; break; }
      }
      var host = after ? after.parentElement : list;
      if ((after && dragging.nextElementSibling === after) || (!after && dragging.parentElement === list && !dragging.nextElementSibling)) return;
      flip(items().concat(dragging), function () { if (after) host.insertBefore(dragging, after); else list.appendChild(dragging); });
    });
    list.addEventListener("drop", function (ev) { ev.preventDefault(); });
  };

  // toggle: clicking el shows/hides target (or toggles a class on it).
  //   {"name":"toggle","sel":"<button>","target":"<what shows>","class":"<optional class>"}
  B.toggle = function (el, op) {
    el.style.cursor = "pointer";
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      all(op.target).forEach(function (t) {
        if (op["class"]) t.classList.toggle(op["class"]);
        else t.hidden = !t.hidden;
      });
    });
  };

  // dialog: clicking el opens target as a modal over the page; the backdrop, Escape or [data-close] close it.
  //   {"name":"dialog","sel":"<button>","target":"<the dialog's markup, inserted hidden>"}
  B.dialog = function (el, op) {
    el.style.cursor = "pointer";
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      var t = document.querySelector(op.target);
      if (!t) return;
      var back = document.createElement("div");
      back.setAttribute("data-dv-backdrop", "");
      back.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9998;display:flex;align-items:center;justify-content:center";
      var home = t.parentNode, next = t.nextSibling, wasHidden = t.hidden;
      t.hidden = false; t.style.zIndex = 9999; t.style.maxHeight = "90vh"; t.style.overflow = "auto";
      back.appendChild(t); document.body.appendChild(back);
      function close() { t.hidden = wasHidden; home.insertBefore(t, next); back.remove(); removeEventListener("keydown", esc); }
      function esc(e) { if (e.key === "Escape") close(); }
      back.addEventListener("click", function (e) { if (e.target === back || (e.target.closest && e.target.closest("[data-close]"))) close(); });
      addEventListener("keydown", esc);
    });
  };

  // tabs: the children of el are tabs; clicking the nth shows the nth of panels and hides the rest.
  //   {"name":"tabs","sel":"<the tab row>","panels":"<the panels>","class":"active"}
  B.tabs = function (el, op) {
    var cls = op["class"] || "active";
    function show(i) {
      Array.prototype.forEach.call(el.children, function (t, j) { t.classList.toggle(cls, i === j); });
      all(op.panels).forEach(function (p, j) { p.hidden = i !== j; });
    }
    Array.prototype.forEach.call(el.children, function (t, i) { t.style.cursor = "pointer"; t.addEventListener("click", function (e) { e.preventDefault(); show(i); }); });
    show(0);
  };

  // toast: clicking el shows a short message at the bottom of the screen (a simulated save, export, ...).
  //   {"name":"toast","sel":"<button>","text":"Saved"}
  B.toast = function (el, op) {
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      var t = document.createElement("div");
      t.textContent = op.text || "Done";
      t.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--text,#222);color:var(--bg,#fff);padding:10px 16px;border-radius:8px;z-index:9999;box-shadow:0 6px 24px rgba(0,0,0,.3);font:inherit";
      document.body.appendChild(t);
      t.animate([{ opacity: 0, transform: "translate(-50%,8px)" }, { opacity: 1, transform: "translate(-50%,0)" }], { duration: 160 });
      setTimeout(function () { t.remove(); }, 1800);
    });
  };
})();
