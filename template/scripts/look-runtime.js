/* look-runtime.js: a look's structural edits (dom.json), kept true while the app redraws and the owner navigates.
   The inbox adds it to any page showing a look that has a dom.json (the mockup, a portfolio frame), next to the
   look's style.css. A look never ships its own script for moves: it lists them, and this applies them.

   Ops (written by look-apply.py, never by hand), each optionally limited to routes with "on" (a regex on
   location.pathname + location.hash):
     {"id":"e1","op":"move","sel":"<what>","where":"before|after|into|start","ref":"<where to>"}
     {"id":"e2","op":"text","sel":"<what>","text":"<new text>"}
     {"id":"e3","op":"insert","where":"before|after|into|start","ref":"<where>","html":"<markup>"}
     {"id":"e4","op":"attr","sel":"<what>","name":"<attribute>","value":"<value or null to remove>"}
   Moving a node keeps its click handlers, so a moved button or link still works. Every op is idempotent, re-applied
   after the app re-renders (a debounced MutationObserver) and on navigation; ops whose route doesn't match are
   left alone. window.__lookRuntime.report() says which ops applied and which found nothing. */
(function () {
  "use strict";
  if (window.__lookRuntime) return;
  var me = document.currentScript, src = (me && me.getAttribute("data-dom")) || "";
  var ops = [], status = {}, applying = false, timer = 0;

  function q(sel) { try { return document.querySelector(sel); } catch (e) { return null; } }
  function routeOk(op) {
    if (!op.on) return true;
    try { return new RegExp(op.on).test(location.pathname + location.hash); } catch (e) { return false; }
  }
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
    return node.parentNode === ref;                    // "into": inside it (later moves may follow it there)
  }
  function one(op) {
    if (!routeOk(op)) return "skipped (other screen)";
    if (op.op === "move") {
      var done = document.querySelector('[data-look-op="' + op.id + '"]'), n = q(op.sel), r = q(op.ref);
      if (done && (!n || n === done) && r && inPlace(done, op.where, r)) return "ok";   // moved already: its selector may
      if (!n || !r) return "missing " + (!n ? op.sel : op.ref);                     // no longer match where it is now
      if (n.contains(r)) return "can't move into itself";
      if (!inPlace(n, op.where, r)) place(n, op.where, r);
      n.setAttribute("data-look-op", op.id);
      return "ok";
    }
    if (op.op === "text") {
      var t = q(op.sel);
      if (!t) return "missing " + op.sel;
      if (t.textContent !== op.text) t.textContent = op.text;
      return "ok";
    }
    if (op.op === "attr") {
      var a = q(op.sel);
      if (!a) return "missing " + op.sel;
      if (op.value === null) a.removeAttribute(op.name);
      else if (a.getAttribute(op.name) !== String(op.value)) a.setAttribute(op.name, op.value);
      return "ok";
    }
    if (op.op === "insert") {
      if (document.querySelector('[data-look-insert="' + op.id + '"]')) return "ok";
      var ref = q(op.ref);
      if (!ref) return "missing " + op.ref;
      var tpl = document.createElement("template");
      tpl.innerHTML = op.html;
      var frag = tpl.content;
      for (var k = 0; k < frag.children.length; k++) frag.children[k].setAttribute("data-look-insert", op.id);
      place(frag, op.where, ref);                    // a fragment goes in as one piece, in order
      return "ok";
    }
    return "unknown op";
  }
  function apply() {
    if (applying) return;
    applying = true;
    obs.disconnect();
    for (var i = 0; i < ops.length; i++) {
      try { status[ops[i].id] = one(ops[i]); } catch (e) { status[ops[i].id] = "error: " + e.message; }
    }
    obs.observe(document.documentElement, { childList: true, subtree: true });
    applying = false;
  }
  var obs = new MutationObserver(function () { clearTimeout(timer); timer = setTimeout(apply, 40); });
  function load() {
    if (!src) return Promise.resolve();
    return fetch(src + (src.indexOf("?") < 0 ? "?" : "&") + "t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (list) {
        var old = ops.map(function (o) { return o.id + JSON.stringify(o); }).join("|");
        var keep = list.slice(0, ops.length).map(function (o) { return o.id + JSON.stringify(o); }).join("|");
        if (ops.length && keep !== old) { location.reload(); return; }   // an op changed or went: start clean
        ops = list; apply();
      }).catch(function () {});
  }
  window.__lookRuntime = {
    refresh: load,
    report: function () { return ops.map(function (o) { return { id: o.id, op: o.op, status: status[o.id] || "not run" }; }); }
  };
  addEventListener("hashchange", function () { setTimeout(apply, 0); });
  addEventListener("popstate", function () { setTimeout(apply, 0); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
})();
