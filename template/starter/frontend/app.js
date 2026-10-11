/* Logic only: routes to screens/<name>.html, fills [data-each] lists and [data-bind] fields from the API.
   No markup lives here: screens are plain HTML in screens/, styled by theme.css and ui.css. */
(function () {
  "use strict";
  var screen = document.querySelector("[data-ui=screen]");
  function name() { return (location.hash.replace(/^#\/?/, "").split(/[?/]/)[0]) || "home"; }
  function fill(root, item) {
    root.querySelectorAll("[data-bind]").forEach(function (el) {
      var v = item[el.getAttribute("data-bind")];
      if (v == null) return;
      if (el.tagName === "IMG") el.src = v; else el.textContent = v;
    });
  }
  function bind(root) {
    root.querySelectorAll("[data-each]").forEach(function (list) {
      var tpl = list.querySelector("template");
      if (!tpl) return;
      api.get(list.getAttribute("data-each")).then(function (items) {
        (items || []).forEach(function (it) {
          var node = tpl.content.cloneNode(true);
          Array.prototype.forEach.call(node.children, function (c) { fill(c, it); });
          list.appendChild(node);
        });
      });
    });
  }
  function show() {
    var n = name();
    document.querySelectorAll("[data-ui=nav] a").forEach(function (a) { a.classList.toggle("active", a.getAttribute("href") === (location.hash || "#/")); });
    fetch("screens/" + n + ".html", { cache: "no-store" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (html) {
      screen.innerHTML = html;
      bind(screen);
    });
  }
  addEventListener("hashchange", show);
  show();
})();
