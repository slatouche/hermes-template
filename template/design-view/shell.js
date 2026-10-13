/* shell.js: the toolbar above the app.
   Notes: type, optionally with marks (Mark = click elements; Box = draw round an area; Arrow = from this to there).
   Direct tools, no designer and no wait: Move (drag an element somewhere) and Text (click text and type).
   Shows what the designer is doing as it happens; the options on show (switch live, or side by side); undo;
   and the build: Agreed (freezes the mockup; it's built and goes live on the main app by itself), with its progress. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var frame = $("app"), ov = $("ov"), marks = [], tool = null, busy = {}, t0 = {}, tick = 0, counts = {};
  var optsState = {}, active = null, build = { frozen: null };
  var SVG = "http://www.w3.org/2000/svg";

  function dv() { try { return frame.contentWindow.__dv; } catch (e) { return null; } }
  function say(text, mode) { $("status").textContent = text; $("dot").className = mode || ""; }
  function post(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); });
  }

  // ---- tools --------------------------------------------------------------------------------------------------------
  function setTool(t) {
    tool = tool === t ? null : t;
    Array.prototype.forEach.call(document.querySelectorAll("[data-tool]"), function (b) { b.classList.toggle("on", b.getAttribute("data-tool") === tool); });
    var d = dv(); if (d) d.pick(tool === "mark");
    ov.setAttribute("class", tool && tool !== "mark" ? "active " + tool : "");
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-tool]"), function (b) {
    b.onclick = function () { setTool(b.getAttribute("data-tool")); };
  });
  function clearDrawn(cls) { Array.prototype.forEach.call(ov.querySelectorAll(cls || "rect, line"), function (n) { n.remove(); }); }
  function shape(name, attrs) { var n = document.createElementNS(SVG, name); for (var k in attrs) n.setAttribute(k, attrs[k]); ov.appendChild(n); return n; }
  function local(ev) { var r = ov.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; }
  function sel(el) { var d = dv(); return el && d ? d.selectorFor(el) : null; }

  var drag = null;
  ov.addEventListener("mousedown", function (ev) {
    var d = dv(); if (!d || !tool) return;
    var p = local(ev);
    if (tool === "text") {
      ov.setAttribute("class", "");                       // let the click and typing reach the page
      var ok = d.editText(p.x, p.y, function (r) {
        setTool("text"); setTool("text");                  // back on, ready for the next
        if (r) direct({ op: "text", sel: r.sel, text: r.text }, "Text: " + r.text.slice(0, 40));
      });
      if (!ok) { setTool("text"); setTool("text"); say("Text: click right on some text"); }
      ev.preventDefault(); return;
    }
    var el = null;
    if (tool === "move") {
      el = movable(d.at(p.x, p.y));
      clearDrawn("rect.hover");
      if (!el) return;
      var r = el.getBoundingClientRect();
      drag = { tool: "move", el: el, ghost: shape("rect", { "class": "drag", x: r.left, y: r.top, width: r.width, height: r.height }), dx: p.x - r.left, dy: p.y - r.top, w: r.width, h: r.height };
    } else if (tool === "box") {
      drag = { tool: "box", x: p.x, y: p.y, shape: shape("rect", { "class": "box", x: p.x, y: p.y, width: 1, height: 1 }) };
    } else if (tool === "arrow") {
      drag = { tool: "arrow", x: p.x, y: p.y, from: d.at(p.x, p.y), shape: shape("line", { "class": "arrow", x1: p.x, y1: p.y, x2: p.x, y2: p.y, "marker-end": "url(#head)" }) };
    }
    ev.preventDefault();
  });
  // What Move picks up: the nearest list item around the pointer (an element with look-alike siblings: a card, a row,
  // a button in a bar), else the element itself.
  function movable(el) {
    var body = frame.contentDocument.body, n = el;
    function like(a, b) { return a.tagName === b.tagName && a.className === b.className; }
    while (n && n !== body && n.parentElement) {
      var sibs = Array.prototype.filter.call(n.parentElement.children, function (s) { return s !== n && like(s, n); });
      if (sibs.length) return n;
      n = n.parentElement;
    }
    return el;
  }
  ov.addEventListener("mousemove", function (ev) {
    if (!drag && tool === "move") {                        // show what would be picked up
      var hp = local(ev), hd = dv(), he = hd && movable(hd.at(hp.x, hp.y));
      clearDrawn("rect.hover");
      if (he) { var hr = he.getBoundingClientRect(); shape("rect", { "class": "drag hover", x: hr.left, y: hr.top, width: hr.width, height: hr.height }); }
      return;
    }
    if (!drag) return;
    var p = local(ev), d = dv();
    if (drag.tool === "box") {
      drag.shape.setAttribute("x", Math.min(p.x, drag.x)); drag.shape.setAttribute("y", Math.min(p.y, drag.y));
      drag.shape.setAttribute("width", Math.abs(p.x - drag.x)); drag.shape.setAttribute("height", Math.abs(p.y - drag.y));
    } else if (drag.tool === "arrow") {
      drag.shape.setAttribute("x2", p.x); drag.shape.setAttribute("y2", p.y);
    } else if (drag.tool === "move") {
      drag.ghost.setAttribute("x", p.x - drag.dx); drag.ghost.setAttribute("y", p.y - drag.dy);
      clearDrawn("line.drop");
      var place = d.dropPlace(p.x, p.y, drag.el);
      drag.place = place;
      if (place) {
        var q = place.rect, before = place.where === "before";
        if (place.row) shape("line", { "class": "drop", x1: before ? q.x - 3 : q.x + q.w + 3, x2: before ? q.x - 3 : q.x + q.w + 3, y1: q.y, y2: q.y + q.h });
        else shape("line", { "class": "drop", x1: q.x, x2: q.x + q.w, y1: before ? q.y - 3 : q.y + q.h + 3, y2: before ? q.y - 3 : q.y + q.h + 3 });
      }
    }
  });
  ov.addEventListener("mouseup", function (ev) {
    if (!drag) return;
    var p = local(ev), d = dv(), g = drag; drag = null;
    if (g.tool === "move") {
      g.ghost.remove(); clearDrawn("line.drop");
      if (g.place && g.place.ref) direct({ op: "move", sel: sel(g.el), where: g.place.where, ref: g.place.ref }, "Moved " + sel(g.el));
      return;
    }
    if (g.tool === "box") {
      var x1 = Math.min(p.x, g.x), y1 = Math.min(p.y, g.y), x2 = Math.max(p.x, g.x), y2 = Math.max(p.y, g.y);
      if (x2 - x1 < 6 || y2 - y1 < 6) { g.shape.remove(); return; }
      var doc = frame.contentDocument, inside = [];
      Array.prototype.forEach.call(doc.body.querySelectorAll("*"), function (el) {
        var r = el.getBoundingClientRect();
        if (r.width && r.height && r.left >= x1 - 2 && r.top >= y1 - 2 && r.right <= x2 + 2 && r.bottom <= y2 + 2 &&
            !inside.some(function (o) { return o.contains(el); })) inside.push(el);
      });
      var host = d.at((x1 + x2) / 2, (y1 + y2) / 2);
      while (host && host.parentElement) { var hr = host.getBoundingClientRect(); if (hr.left <= x1 && hr.top <= y1 && hr.right >= x2 && hr.bottom >= y2) break; host = host.parentElement; }
      addMark({ kind: "area", sel: sel(host) || "body", rect: { x: Math.round(x1), y: Math.round(y1), w: Math.round(x2 - x1), h: Math.round(y2 - y1) },
                inside: inside.slice(0, 12).map(sel), label: "area" }, g.shape);
    } else if (g.tool === "arrow") {
      if (Math.hypot(p.x - g.x, p.y - g.y) < 12) { g.shape.remove(); return; }
      var to = d.at(p.x, p.y);
      addMark({ kind: "arrow", from: sel(g.from), to: sel(to), label: "arrow" }, g.shape);
    }
  });
  ov.addEventListener("wheel", function (ev) { try { frame.contentWindow.scrollBy(ev.deltaX, ev.deltaY); } catch (e) {} ev.preventDefault(); }, { passive: false });

  function direct(op, label) {
    var d = dv();
    post("/dv/op", { op: op, label: label, route: d ? d.route() : "#/" }).then(function (r) {
      say(r.error ? "Not applied: " + r.error : label + " · instant", r.error ? "err" : "");
    });
  }

  // ---- marks and notes ----------------------------------------------------------------------------------------------
  function addMark(m, drawn, add) {
    if (!add && m.kind === undefined) { marks = marks.filter(function (x) { return x.kind; }); }
    m.drawn = drawn || null;
    marks.push(m); drawMarks(); $("note").focus();
  }
  function drawMarks() {
    var box = $("marks"); box.innerHTML = "";
    marks.forEach(function (m, i) {
      var c = document.createElement("span"); c.className = "chip";
      c.textContent = m.kind === "area" ? "▭ area" : m.kind === "arrow" ? "➚ " + (m.from || "?") : m.sel;
      c.title = "click to remove\n" + JSON.stringify({ sel: m.sel, from: m.from, to: m.to });
      c.onclick = function () {
        if (m.drawn) m.drawn.remove();
        if (m.sel && !m.kind) { var d = dv(); if (d) d.unpick(m.sel); }
        marks.splice(i, 1); drawMarks();
      };
      box.appendChild(c);
    });
    if (marks.length) {
      var x = document.createElement("span"); x.className = "chip clear"; x.textContent = "✕ Clear";
      x.title = "Clear every mark, box and arrow (Esc)";
      x.onclick = clearMarks;
      box.insertBefore(x, box.firstChild);                 // first, so it's never cut off by many marks
    }
  }
  // Start the pointing over: every mark, box and arrow goes. Esc does the same; a second Esc leaves the tool.
  function clearMarks() {
    marks = []; drawMarks(); clearDrawn("rect, line");
    var d = dv(); if (d) d.unpickAll();
  }
  function escape() {
    if (question) { closeQuestion(); $("answer").hidden = true; }
    else if (marks.length || ov.querySelector("rect, line")) clearMarks();
    else if (tool) setTool(tool);
  }
  addEventListener("keydown", function (ev) { if (ev.key === "Escape" && document.activeElement !== $("note")) escape(); });
  $("note").addEventListener("keydown", function (ev) { if (ev.key === "Escape") { ev.preventDefault(); escape(); } });
  addEventListener("message", function (ev) {
    if (ev.origin !== location.origin || !ev.data || !ev.data.dv || ev.source !== frame.contentWindow) return;
    var m = ev.data;
    if (m.dv === "picked") {
      if (!m.add) marks = marks.filter(function (x) { return x.kind; });   // the page already swapped the highlight
      marks.push(m.mark); drawMarks(); $("note").focus();
    } else if (m.dv === "unpicked") {
      marks = marks.filter(function (x) { return x.kind || x.sel !== m.sel; }); drawMarks();
    } else if (m.dv === "escape") {
      escape();
    } else if (m.dv === "loaded" || m.dv === "active") {
      if (m.options) optsState = m.options;
      active = m.active; drawOpts();
      var d2 = dv(); if (d2 && tool === "mark") d2.pick(true);
    }
  });
  // One box for everything: a change, a problem, a question, a reaction, an undo in words. The designer splits it into
  // parts and sends each the fast or the thinking way; while it has asked you something, Enter answers it.
  function send() {
    var text = $("note").value.trim(), replyTo = question ? question.note : null;
    if (!text) return;
    var d = dv();
    var body = { note: text, marks: marks.map(function (m) { var c = Object.assign({}, m); delete c.drawn; return c; }),
                 map: d ? d.map() : "", route: d ? d.route() : "#/", reply_to: replyTo };
    if (replyTo) { showAnswer("Answered: " + question.question, "Your answer: " + text, []); }
    if (question) closeQuestion();                           // answered, or moved on to something else
    $("note").value = "";
    post("/dv/note", body).then(function (r) { if (r.error) say("Not sent: " + r.error, "err"); })
      .catch(function () { say("Not sent: the design view didn't answer", "err"); });
    marks = []; drawMarks(); clearDrawn(); if (tool === "mark") setTool("mark");
    var d3 = dv(); if (d3) d3.unpickAll();
  }
  $("send").onclick = function () { send(); };

  // ---- the answer panel: the Ask button's answer, and a review's reasoning ("why") ------------------------------------
  function showAnswer(title, text, sugg, append) {
    $("answer").hidden = false;
    $("answer-title").textContent = title;
    if (append) {
      var div = document.createElement("div"); div.className = "why"; div.textContent = text; $("answer-text").appendChild(div);
    } else $("answer-text").textContent = text;
    var box = $("answer-sugg"); box.innerHTML = "";
    (sugg || []).forEach(function (sg) {
      var b = document.createElement("button"); b.textContent = "Do it: " + sg; b.title = "Send this as a note";
      b.onclick = function () { $("note").value = sg; send(); };
      box.appendChild(b);
    });
  }
  $("answer-close").onclick = function () { $("answer").hidden = true; if (question) closeQuestion(); };

  // ---- a question from the designer: shown in the panel; answer with a choice or in the note box ----------------------
  var question = null;
  function showQuestion(e) {
    question = { note: e.note, question: e.question };
    showAnswer("Question from the designer", e.question + (e.about ? "\n\nAbout your note: " + e.about : ""), []);
    $("answer").classList.add("asking");
    var box = $("answer-sugg"); box.innerHTML = "";
    (e.choices || []).forEach(function (c) {
      var b = document.createElement("button"); b.textContent = c; b.title = "Answer with this";
      b.onclick = function () { $("note").value = c; send(); };
      box.appendChild(b);
    });
    $("note").classList.add("answering");
    $("note").placeholder = "Answering: " + e.question + "  (Enter sends your answer · Esc dismisses)";
    $("note").focus();
  }
  function closeQuestion() {
    question = null;
    $("answer").classList.remove("asking");
    $("note").classList.remove("answering");
    $("note").placeholder = notePlaceholder;
  }
  $("note").addEventListener("keydown", function (e) {     // Enter sends
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  var notePlaceholder = $("note").placeholder;
  // Undo and Redo are one click: the last change, or the last undone one (no model). Anything more specific is written
  // in the box ("undo the colour change", "bring back the glow").
  function undoLast() {
    post("/dv/undo", { last: true }).then(function (r) { say(r.error ? r.error : r.undone && r.undone.length ? "Undid " + r.undone.join(", ") : "Nothing to undo", r.error ? "err" : ""); });
  }
  function redoLast() {
    post("/dv/redo", {}).then(function (r) { say(r.error ? r.error : r.redone && r.redone.length ? "Brought back " + r.redone.join(", ") : "Nothing to redo", r.error ? "err" : ""); });
  }
  $("undo").onclick = undoLast;
  $("redo").onclick = redoLast;

  // ---- options: live switch, or side by side --------------------------------------------------------------------------
  function drawOpts() {
    var box = $("opts"), sets = Object.keys(optsState || {});
    box.innerHTML = "";
    if (!sets.length) { box.hidden = true; return; }
    box.hidden = false;
    var set = active ? active.set : sets[sets.length - 1], s = optsState[set];
    var lbl = document.createElement("span"); lbl.className = "lbl"; lbl.textContent = "Options:"; box.appendChild(lbl);
    function btn(text, on, fn, cls) {
      var b = document.createElement("button"); b.title = text;
      b.textContent = text.length > 24 ? text.slice(0, 23) + "…" : text;
      b.className = (on ? "on " : "") + (cls || ""); b.onclick = fn; box.appendChild(b);
    }
    btn("Current", !active, function () { var d = dv(); if (d) d.setOption(null, null); });
    Object.keys(s.choices || {}).sort().forEach(function (k) {
      btn(k + " · " + (s.choices[k].name || k).replace(/\s*\(.*$/, ""), active && active.set === set && active.choice === k,
          function () { var d = dv(); if (d) d.setOption(set, k); });
    });
    btn("⧉ Side by side", false, function () { compare(set); });
    if (active) btn("✓ Use " + active.choice, false, function () { pick(active.set, active.choice); }, "go");
    btn("✕ Discard", false, function () {                  // none of these: the set goes, the page shows the design
      post("/dv/discard", { set: set }).then(function (r) {
        if (r.error) { say(r.error, "err"); return; }
        $("compare").hidden = true; optsState = {}; var d = dv(); if (d) d.setOption(null, null); drawOpts();
        say("Options discarded: none of them were kept");
      });
    });
  }
  function pick(set, choice) {
    post("/dv/pick", { set: set, choice: choice }).then(function () { $("compare").hidden = true; var d = dv(); if (d) d.setOption(null, null); });
  }
  function compare(set) {
    var s = optsState[set], box = $("compare"), d = dv();
    var keys = ["none"].concat(Object.keys(s.choices || {}).sort());
    box.innerHTML = ""; box.hidden = false;
    box.style.gridTemplateColumns = "repeat(" + Math.min(keys.length, 2) + ", 1fr)";
    var close = document.createElement("button"); close.className = "close"; close.textContent = "✕ Close";
    close.onclick = function () { box.hidden = true; box.innerHTML = ""; };
    box.appendChild(close);
    var hash = d ? d.route() : "#/", y = 0;
    try { y = frame.contentWindow.scrollY; } catch (e) {}
    var fullW = frame.clientWidth, fullH = frame.clientHeight;
    keys.forEach(function (k) {
      var tile = document.createElement("div"); tile.className = "tile" + (active && active.choice === k ? " on" : "");
      var head = document.createElement("header"), name = document.createElement("span");
      name.textContent = k === "none" ? "Current" : k + " · " + (s.choices[k].name || "");
      head.appendChild(name);
      if (k !== "none") { var use = document.createElement("button"); use.textContent = "✓ Use this"; use.onclick = function () { pick(set, k); }; head.appendChild(use); }
      var view = document.createElement("div"); view.className = "view";
      var f = document.createElement("iframe");
      f.src = "/app/?dvopt=" + encodeURIComponent(k === "none" ? "none" : set + ":" + k) + hash;
      f.width = fullW; f.height = fullH;
      view.appendChild(f); tile.appendChild(head); tile.appendChild(view); box.appendChild(tile);
      f.onload = function () {
        var scale = view.clientWidth / fullW;
        f.style.transform = "scale(" + scale + ")";
        view.style.height = Math.round(fullH * scale) + "px";
        setTimeout(function () { try { f.contentWindow.scrollTo(0, y); } catch (e) {} }, 300);
      };
    });
  }

  // ---- checking every choice of an option set: a hidden frame per choice, at the main view's size, judges that
  // choice's edits and reports them (the choice on show is checked in the main view as it lands) ------------------------
  var measureFrames = {};
  function measureOptions(e) {
    var box = document.getElementById("dv-measure");
    if (!box) { box = document.createElement("div"); box.id = "dv-measure"; box.style.cssText = "position:fixed;left:-20000px;top:0;width:0;height:0;overflow:hidden;visibility:hidden"; document.body.appendChild(box); }
    var w = frame.clientWidth, h = frame.clientHeight, hash = e.route || (dv() ? dv().route() : "#/");
    (e.choices || []).forEach(function (c) {
      var key = e.set + ":" + c, f = document.createElement("iframe");
      if (measureFrames[key]) measureFrames[key].remove();
      f.width = w; f.height = h; f.src = "/app/?dvopt=" + encodeURIComponent(key) + "&dvmeasure=1" + hash;
      measureFrames[key] = f; box.appendChild(f);
      setTimeout(function () { if (measureFrames[key] === f) { f.remove(); delete measureFrames[key]; } }, 15000);
    });
  }
  addEventListener("message", function (ev) {
    if (ev.origin !== location.origin || !ev.data || ev.data.dv !== "measured") return;
    var key = ev.data.set + ":" + ev.data.choice, f = measureFrames[key];
    if (f && ev.source === f.contentWindow) { f.remove(); delete measureFrames[key]; }
  });

  // ---- the build: Agreed -> planned -> built -> checked -> live on the main app (build.py does it, no button) ------------
  var STAGES = { planning: "Agreed · the Manager is planning the build", checking: "Checking the whole build",
                 reviewing: "The Tester is reviewing the build", landing: "Going live", live: "Live ✓",
                 stuck: "⚠ The build is stuck · the Manager has it", aborted: "Build stopped" };
  function drawBuild() {
    var box = $("build"); box.innerHTML = "";
    function btn(text, cls, fn, title) { var b = document.createElement("button"); b.textContent = text; b.className = cls || ""; b.onclick = fn; if (title) b.title = title; box.appendChild(b); return b; }
    function lbl(t, title) { var s = document.createElement("span"); s.className = "lbl"; s.textContent = t; if (title) s.title = title; box.appendChild(s); }
    if (build.data) btn("↻ Data", "", function () {        // the design copy's data, made the app's real data again
      if (!confirm("Refresh the design view's data from the app's real data?\n\nAnything created, changed or deleted in the design view's copy is lost. Your real data is only read.")) return;
      post("/dv/reset-data").then(function (r) { if (r.error) say(r.error, "err"); });
    }, "Refresh the design copy's data from the app's real data (your real data is only read)");
    var frozen = !!build.frozen;
    $("note").disabled = frozen; $("send").disabled = frozen;
    $("note").placeholder = frozen ? "Agreed — the mockup is frozen while it's built and put live" : (question ? $("note").placeholder : notePlaceholder);
    if (frozen) {
      var rows = build.rows || [], st = build.state || "planning";
      var doneN = rows.filter(function (r) { return r.status === "done" || r.status === "archived"; }).length;
      lbl(st === "building" ? "Building " + doneN + "/" + rows.length + ":" : (STAGES[st] || st) + (build.step && st !== "planning" && st !== "live" ? ": " + build.step : ""),
          build.step || "");
      if (st === "planning" || st === "building" || st === "reviewing") rows.forEach(function (r) {   // one chip per card: who, state, how long
        var mins = r.since ? Math.max(0, Math.round((Date.now() / 1000 - r.since) / 60)) : 0;
        var cs = { done: "✓", archived: "✓", running: "◐ " + mins + "m", blocked: "⚠ blocked", review: "◑ review", ready: "○ next", todo: "○ waiting", triage: "○ waiting" }[r.status] || r.status;
        var c = document.createElement("span"); c.className = "bchip " + r.status;
        c.textContent = r.who + " " + cs; c.title = r.id + " · " + r.title + " (" + r.who + ", " + r.status + ")";
        box.appendChild(c);
      });
      if (st !== "landing" && st !== "live") btn("Unfreeze", "", function () {
        if (confirm("Unfreeze the mockup and stop the build? Nothing goes live; the build's branch is kept for the Manager.")) post("/dv/unfreeze").then(function (r) { if (r.error) say(r.error, "err"); });
      }, "Stop the build and go back to designing");
    } else {
      btn("✓ Agreed", "go", function () {
        if (!confirm("Agree the whole mockup? It's built and goes live on the main app by itself once its checks pass. Notes pause until then.")) return;
        post("/dv/agree").then(function (r) { if (r.error) say(r.error, "err"); });
      }, "The whole mockup is right: build it into the main app");
    }
  }
  function setBuild(b) {
    b = b || {};
    build.state = b.state; build.step = b.step || ""; build.rows = b.rows || [];
  }
  function loadState() {
    fetch("/dv/ops", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      build.frozen = d.frozen; build.data = d.data; setBuild(d.build);
      drawBuild();
    }).catch(function () {});
  }
  loadState();
  setInterval(function () { if (build.frozen) drawBuild(); }, 30000);   // the minutes on the chips

  // ---- live status --------------------------------------------------------------------------------------------------
  function elapsed(id) { return ((Date.now() - (t0[id] || Date.now())) / 1000).toFixed(1) + " s"; }
  function liveTick() {
    clearInterval(tick);
    tick = setInterval(function () {
      var ids = Object.keys(busy);
      if (!ids.length) { clearInterval(tick); return; }
      say(busy[ids[0]] + " · " + elapsed(ids[0]) + (ids.length > 1 ? " · " + (ids.length - 1) + " more waiting" : ""), "busy");
    }, 200);
  }
  // A note in several parts: one line showing each part's kind and where it is.
  var parts = {};
  // Each part's route: ⚡ fast (one quick call), 🧠 thinking (worked out first), 💬 an answer, and the rest.
  var ROUTE = { quick: "⚡", options: "⚡", screen: "⚡", think: "🧠", review: "🧠", background: "🧠", answer: "💬",
                ask: "❓", prefer: "📌", ack: "👍", function: "→" };
  function routed(kind) { return (ROUTE[kind] || "") + " " + kind; }
  function partLine(id) {
    var ps = parts[id] || {}, marks = { doing: "…", starting: "…", done: "✓", card: "→ card", asked: "? question", failed: "✗" };
    return Object.keys(ps).length + " parts: " + Object.keys(ps).map(function (k) {
      var p = ps[k];
      var tail = p.state === "asked" ? " " + p.text : "";
      return routed(p.kind) + " " + (marks[p.state] || p.state) + tail;
    }).join(" · ");
  }
  function countUp(id) { counts[id] = (counts[id] || 0) + 1; return counts[id] + (counts[id] === 1 ? " edit" : " edits"); }
  var es = new EventSource("/dv/events");
  es.onmessage = function (m) {
    var e; try { e = JSON.parse(m.data); } catch (x) { return; }
    try { frame.contentWindow.postMessage({ dvEvent: e }, location.origin); } catch (x) {}
    if (e.type === "received") { t0[e.note] = Date.now(); busy[e.note] = (e.queued ? "Queued: " : "Received: ") + e.text; liveTick(); }
    else if (e.type === "doing") { t0[e.note] = t0[e.note] || Date.now(); busy[e.note] = "Reading: " + e.text; liveTick(); }
    else if (e.type === "plan" && e.parts && e.parts.length > 1) {
      parts[e.note] = {};
      e.parts.forEach(function (p) { parts[e.note][p.k] = { kind: p.kind, text: p.text, state: p.kind === "quick" ? "doing" : "starting" }; });
      busy[e.note] = partLine(e.note);
    }
    else if (e.type === "part" && parts[e.note]) {
      if (e.k === 0) { busy[e.note] = partLine(e.note) + " · " + e.text; }
      else if (parts[e.note][e.k]) {
        parts[e.note][e.k].state = e.state; if (e.card) parts[e.note][e.k].card = e.card;
        busy[e.note] = partLine(e.note);
      }
    }
    else if (e.type === "verdict") { if (!parts[e.note]) busy[e.note] = routed(e.verdict) + ": " + e.plan; }
    else if (e.type === "op" && busy[e.note]) { busy[e.note] = busy[e.note].replace(/ \(\d+ edits?\)$/, "") + " (" + countUp(e.note) + ")"; }
    else if (e.type === "option") { optsState[e.set] = optsState[e.set] || { choices: {} }; optsState[e.set].choices[e.choice] = { name: e.name, ops: [] }; if (!active) active = { set: e.set, choice: e.choice }; drawOpts(); }
    else if (e.type === "done") {
      if (!busy[e.note] && e.verdict === "direct") return;
      delete busy[e.note];
      var cs = e.cards && e.cards.length ? e.cards : (e.card ? [e.card] : []);
      var extra = cs.map(function (c) { return " → card for the " + c.to + (c.id ? " (" + c.id + ")" : ""); }).join("");
      if (parts[e.note]) {
        Object.keys(parts[e.note]).forEach(function (k) { var p = parts[e.note][k]; if (p.state === "doing" || p.state === "starting") p.state = "done"; });
        e.plan = partLine(e.note); delete parts[e.note];
      }
      var bad = e.refused && e.refused.length ? " · " + e.refused.length + " edit(s) refused" : "";
      say((e.s ? "Done in " + e.s + " s · " : "Done · ") + routed(e.verdict) + ": " + (e.plan || "") + (e.edits ? " · " + e.edits + " edits" : "") + extra + bad,
          e.refused && e.refused.length ? "err" : "");
    }
    else if (e.type === "question") { showQuestion(e); }
    else if (e.type === "build") { setBuild(e); drawBuild(); }
    else if (e.type === "measure-options") { measureOptions(e); }
    else if (e.type === "data") {
      if (e.state === "started") { t0.data = Date.now(); busy.data = "Refreshing the data from the app's real data (" + (e.why || "asked") + ")"; liveTick(); }
      else { delete busy.data; say(e.state === "done" ? "Data refreshed in " + e.s + " s: the page shows the app's current data" : "Data refresh failed: " + (e.text || ""), e.state === "done" ? "" : "err"); }
    }
    else if (e.type === "answer") {
      if (e.kind === "review") showAnswer(e.title, e.text, [], !$("answer").hidden && $("answer-title").textContent.indexOf("Why") === 0);
      else showAnswer(e.title, e.text, e.suggest);
    }
    else if (e.type === "error") { delete busy[e.note]; say("Failed: " + e.message, "err"); }
    else if (e.type === "frozen" || e.type === "reload-ops" || e.type === "live") {
      loadState();
      if (e.type === "live") say("Live: the agreed design is in the main app, and the mockup starts from it again.");
    }
  };
  es.onerror = function () { say("Lost the design view — retrying…", "err"); };
  es.onopen = function () { if ($("status").textContent.indexOf("Lost") === 0) say("Ready"); };
})();
