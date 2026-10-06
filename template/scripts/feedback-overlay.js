/* Mark overlay: the owner marks things on a page and the notes go to the project's feedback inbox.
   Loaded by the "Mark" bookmarklet from the inbox (__INBOX__ is filled in when it's served).
   Mark = click an element; Area = drag a box. Type what's wrong, Save (Ctrl+Enter). Esc stops.
   Saved notes are drafts (amber pins: click one to change or delete it) until Send hands this link's drafts to the team;
   sent notes leave no pins. Works with a mouse, a pen or a finger.
   Everything lives in a shadow root so the page's styles can't touch it, and it never changes the page. */
(() => {
  if (window.__markLoaded) return;
  window.__markLoaded = true;
  const INBOX = "__INBOX__";
  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647;touch-action:none";
  document.documentElement.appendChild(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>
    :host{all:initial}*{box-sizing:border-box;font:13px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
    .bar{position:fixed;right:16px;bottom:16px;display:flex;gap:6px;padding:6px;border-radius:12px;background:#15161a;
      border:1px solid #2a2c33;box-shadow:0 8px 30px rgba(0,0,0,.45);pointer-events:auto;color:#e8e8ea;align-items:center}
    button{border:0;border-radius:8px;padding:7px 11px;background:#23252c;color:#e8e8ea;cursor:pointer}
    button:hover{background:#2d3039}button.on{background:#3d6bff;color:#fff}
    .hl{position:fixed;border:2px solid #3d6bff;background:rgba(61,107,255,.12);border-radius:4px;pointer-events:none;display:none}
    .area{position:fixed;border:2px dashed #ffb02e;background:rgba(255,176,46,.10);pointer-events:none;display:none}
    .pin{position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:#ffb02e;color:#1a1300;
      font-weight:700;font-size:12px;display:flex;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;
      box-shadow:0 2px 8px rgba(0,0,0,.4)}
    button.send{background:#1e7d4f;color:#fff;font-weight:600;display:none}button.send:hover{background:#249760}
    button.del{margin-right:auto;background:transparent;color:#ff8095}
    .pop{position:fixed;width:min(340px,calc(100vw - 24px));padding:10px;border-radius:12px;background:#15161a;
      border:1px solid #2a2c33;box-shadow:0 12px 40px rgba(0,0,0,.5);pointer-events:auto;color:#e8e8ea;display:none}
    .pop textarea{width:100%;min-height:90px;resize:vertical;border-radius:8px;border:1px solid #2a2c33;background:#0f1013;
      color:#e8e8ea;padding:8px}.pop .row{display:flex;gap:6px;justify-content:flex-end;margin-top:8px}
    .pop .what{color:#9aa0ad;margin-bottom:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .toast{position:fixed;left:50%;bottom:76px;transform:translateX(-50%);padding:8px 12px;border-radius:8px;background:#1e7d4f;
      color:#fff;display:none}
    .layer{position:absolute;left:0;top:0}
    .box{position:absolute;border:1.5px dashed #ffb02e;border-radius:4px;pointer-events:none}
    .fold{position:fixed;right:16px;bottom:16px;width:36px;height:36px;border-radius:50%;background:#3d6bff;color:#fff;
      font-weight:700;display:none;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;
      box-shadow:0 6px 20px rgba(0,0,0,.45)}
    :host(.folded) .bar{display:none}:host(.folded) .fold{display:flex}:host(.folded) .layer{display:none}
    .pop{z-index:5}.toast{z-index:6}.bar,.fold,.look{z-index:2;touch-action:none}
    .look{position:fixed;left:16px;bottom:16px;display:none;align-items:center;gap:6px;flex-wrap:wrap;max-width:calc(100vw - 32px);
      padding:5px 6px 5px 12px;border-radius:999px;background:#2d5bff;color:#fff;font-weight:600;font-size:12px;
      box-shadow:0 6px 20px rgba(0,0,0,.45);pointer-events:auto;cursor:grab}
    .look.sb{background:#7a3cff}.look button{all:unset;cursor:pointer;text-decoration:underline;font:inherit;color:#fff}
    .look b{font:inherit;text-decoration:none;background:rgba(255,255,255,.22);padding:1px 7px;border-radius:999px}
    .look .min{text-decoration:none;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.25);text-align:center;line-height:20px}
    .look.small{padding:0;width:32px;height:32px;justify-content:center}.look.small>*{display:none}.look.small>.min{display:block;background:none;width:32px;height:32px;line-height:32px}
  </style>
  <div class="look"></div>
  <div class="hl"></div><div class="area"></div><div class="layer"></div>
  <div class="pop"><div class="what"></div><textarea placeholder="What's wrong, or what should change?"></textarea>
    <div class="row"><button class="del">Delete</button><button class="cancel">Cancel</button><button class="save on">Save</button></div></div>
  <div class="toast"></div>
  <div class="bar"><button class="mark" title="Click an element to mark it">Mark</button>
    <button class="areab" title="Drag a box over an area">Area</button>
    <button class="send" title="Send your draft notes to the team as one piece of feedback"></button>
    <button class="pins" title="Show or hide your draft pins">Pins</button><button class="close" title="Fold away (click M to bring it back)">×</button></div>
  <div class="fold" title="Open the Mark toolbar">M</div>`;
  const $ = (s) => root.querySelector(s);
  const hl = $(".hl"), area = $(".area"), pop = $(".pop"), layer = $(".layer"), toast = $(".toast");
  let mode = null, target = null, rect = null, start = null, open = [], showPins = true;
  let editing = null, sending = false, drafts = 0;   // editing: the draft whose pin was clicked; sending: the Send box
  const APP = "__APP__";
  const say = (msg) => { toast.textContent = msg; toast.style.display = "block"; setTimeout(() => (toast.style.display = "none"), 2600); };
  const post = (path, body) => fetch(INBOX + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const store = (k, v) => { try { v === undefined ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch (_) {} };
  const recall = (k) => { try { return sessionStorage.getItem(k); } catch (_) { return null; } };

  // Drag the toolbar, the M button and the look badge out of the way of the app's own buttons (remembered for this tab).
  const draggable = (el, key) => {
    const put = (x, y) => {
      x = Math.max(4, Math.min(x, innerWidth - el.offsetWidth - 4)); y = Math.max(4, Math.min(y, innerHeight - el.offsetHeight - 4));
      Object.assign(el.style, { left: x + "px", top: y + "px", right: "auto", bottom: "auto" });
    };
    const saved = recall(key);
    if (saved) { const [x, y] = saved.split(",").map(Number); requestAnimationFrame(() => put(x, y)); }
    el.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button") && !el.classList.contains("small")) return;
      const r = el.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      let moved = false;
      const move = (m) => { moved = true; put(m.clientX - dx, m.clientY - dy); };
      const up = () => {
        removeEventListener("pointermove", move); removeEventListener("pointerup", up);
        if (moved) { const q = el.getBoundingClientRect(); store(key, `${q.left},${q.top}`); el.dataset.dragged = "1"; setTimeout(() => delete el.dataset.dragged, 0); }
      };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
    });
  };

  // The badge: on the mockup, its snapshot and which look is on (one click switches it, on the same screen); on a
  // demo slot, which demo this is.
  const look = $(".look"), cfg = window.__markBadge;
  if (cfg) {
    const sw = (v) => { const u = new URL(location.href); u.searchParams.set("__variant", v); location.href = u.pathname + u.search + u.hash; };
    const add = (tag, text, fn) => { const n = document.createElement(tag); n.textContent = text; if (fn) n.onclick = fn; look.appendChild(n); return n; };
    look.classList.toggle("sb", !!(cfg.mockup || cfg.demo));
    if (cfg.demo) add("span", cfg.demo.replace(/^demo/i, "Demo")).title = "A demo of something new: nothing here touches your real data";
    if (cfg.mockup) {
      add("span", "Mockup").title = cfg.mockup + " · a copy of the app: nothing here touches your real data";
      add("button", "reset data", () => {
        if (confirm("Put the mockup's data back to a fresh copy of the real data?"))
          fetch(INBOX + "/mockup/reset", { method: "POST" }).then(() => location.reload());
      });
    }
    if (cfg.looks.length) {
      add("span", "Look:");
      [["off", "current"], ...cfg.looks.map((n) => [n, n])].forEach(([key, label]) =>
        key === (cfg.variant || "off") ? add("b", label) : add("button", label, () => sw(key)));
      add("button", "compare", () => (location.href = "/__mark/variants"));
    }
    const min = add("button", "–", () => {
      if (look.dataset.dragged) return;
      const small = !look.classList.contains("small");
      look.classList.toggle("small", small); min.textContent = small ? (cfg.demo ? "D" + (cfg.demo.match(/\d/) || [""])[0] : cfg.mockup ? "Mo" : "V") : "–";
      min.title = small ? "Show the look badge" : "Make it small"; store("markLookSmall", small ? "1" : undefined);
    });
    min.className = "min"; min.title = "Make it small";
    look.style.display = "flex";
    if (recall("markLookSmall")) min.onclick();
    draggable(look, "markLookPos");
  }

  const selectorOf = (el) => {
    if (!el || el === document.body) return "body";
    if (el.id && document.querySelectorAll("#" + CSS.escape(el.id)).length === 1) return "#" + CSS.escape(el.id);
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 6; e = e.parentElement) {
      let p = e.tagName.toLowerCase();
      if (e.id) { parts.unshift("#" + CSS.escape(e.id)); break; }
      const cls = [...e.classList].filter((c) => !/^(is-|has-|active|hover|focus)/.test(c)).slice(0, 2);
      if (cls.length) p += "." + cls.map((c) => CSS.escape(c)).join(".");
      const sib = e.parentElement ? [...e.parentElement.children].filter((c) => c.tagName === e.tagName) : [];
      if (sib.length > 1) p += `:nth-of-type(${sib.indexOf(e) + 1})`;
      parts.unshift(p);
    }
    return parts.join(" > ");
  };
  const setMode = (m) => {
    mode = mode === m ? null : m;
    $(".mark").classList.toggle("on", mode === "mark");
    $(".areab").classList.toggle("on", mode === "area");
    host.style.pointerEvents = mode ? "auto" : "none";
    host.style.cursor = mode === "area" ? "crosshair" : mode ? "pointer" : "";
    hl.style.display = "none";
  };
  window.__markToggle = () => setMode("mark");
  const boxAt = (r) => { hl.style.cssText += `;display:block;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px`; };
  const underPointer = (x, y) => { host.style.pointerEvents = "none"; const el = document.elementFromPoint(x, y); host.style.pointerEvents = "auto"; return el; };

  const popOpen = () => pop.style.display === "block";
  host.addEventListener("pointermove", (e) => {
    if (popOpen()) return;
    if (mode === "mark") { const el = underPointer(e.clientX, e.clientY); if (el && el !== host) boxAt(el.getBoundingClientRect()); }
    if (mode === "area" && start) {
      const x = Math.min(start.x, e.clientX), y = Math.min(start.y, e.clientY);
      area.style.cssText += `;display:block;left:${x}px;top:${y}px;width:${Math.abs(e.clientX - start.x)}px;height:${Math.abs(e.clientY - start.y)}px`;
    }
  });
  const onUi = (e) => e.composedPath().some((n) => n === pop || n === $(".bar") || n === look || (n.classList && n.classList.contains("pin")));
  host.addEventListener("pointerdown", (e) => {
    if (onUi(e) || popOpen()) return;              // finish or cancel the open note before starting another
    e.preventDefault();
    if (mode === "area") start = { x: e.clientX, y: e.clientY };
  });
  host.addEventListener("pointerup", (e) => {
    if (onUi(e) || popOpen() || !mode) return;
    editing = null; sending = false;                 // a new mark is always a new note, never an edit or a Send
    if (mode === "mark") {
      target = underPointer(e.clientX, e.clientY);
      if (!target || target === host || target === document.documentElement) return;
      const r = target.getBoundingClientRect();
      rect = { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height };
      ask(`${target.tagName.toLowerCase()}: ${(target.innerText || target.alt || "").trim().slice(0, 60)}`, e.clientX, e.clientY);
    } else if (mode === "area" && start) {
      const x = Math.min(start.x, e.clientX), y = Math.min(start.y, e.clientY);
      rect = { x: x + scrollX, y: y + scrollY, w: Math.abs(e.clientX - start.x), h: Math.abs(e.clientY - start.y) };
      start = null; target = null;
      if (rect.w < 6 || rect.h < 6) { area.style.display = "none"; return; }
      boxInfo = describeArea({ left: x, top: y, width: rect.w, height: rect.h });
      const names = boxInfo.elements.slice(0, 3).map((el) => el.text || el.selector.split(" > ").pop()).join(", ");
      ask(`area: ${boxInfo.elements.length} element${boxInfo.elements.length === 1 ? "" : "s"}${names ? " (" + names + ")" : ""}`, e.clientX, e.clientY);
    }
  });
  // An area note keeps what's in it (the elements mostly inside the box) and an anchor, so the box and its pin follow
  // the page as it scrolls or reflows: the first element inside the box (the box kept as a pixel offset from it, so it
  // moves with content that scrolls inside a panel), or for an empty area the smallest element containing it (the
  // box kept as fractions of it).
  let boxInfo = null;
  const describeArea = (b) => {
    const inside = [], seen = new Set();
    let first = null;
    host.style.pointerEvents = "none";
    for (const el of document.body.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();         // geometry first (cheap); text only for what's inside the box
      if (!r.width || !r.height || r.width * r.height < 64) continue;
      const ix = Math.max(0, Math.min(r.right, b.left + b.width) - Math.max(r.left, b.left));
      const iy = Math.max(0, Math.min(r.bottom, b.top + b.height) - Math.max(r.top, b.top));
      if ((ix * iy) / (r.width * r.height) < 0.8) continue;
      if ([...seen].some((p) => p.contains(el))) continue;       // keep the outermost element of each group
      const label = (el.innerText || el.alt || el.getAttribute("aria-label") || el.title || "").trim();
      if (!label && !/^(IMG|SVG|CANVAS|VIDEO|INPUT|SELECT|TEXTAREA)$/i.test(el.tagName)) continue;   // skip empty wrappers and handles
      seen.add(el);
      first = first || el;
      inside.push({ selector: selectorOf(el), text: label.replace(/\s+/g, " ").slice(0, 60) });
      if (inside.length >= 12) break;
    }
    host.style.pointerEvents = "auto";
    if (first) {
      const fr = first.getBoundingClientRect();
      return { elements: inside, anchor: { selector: selectorOf(first), off: { x: b.left - fr.left, y: b.top - fr.top, w: b.width, h: b.height } } };
    }
    host.style.pointerEvents = "none";
    let a = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    host.style.pointerEvents = "auto";
    while (a && a !== document.body) {
      const r = a.getBoundingClientRect();
      if (r.left <= b.left + 1 && r.top <= b.top + 1 && r.right >= b.left + b.width - 1 && r.bottom >= b.top + b.height - 1) break;
      a = a.parentElement;
    }
    a = a || document.body;
    const ar = a.getBoundingClientRect();
    const rel = { x: (b.left - ar.left) / ar.width, y: (b.top - ar.top) / ar.height, w: b.width / ar.width, h: b.height / ar.height };
    return { elements: inside, anchor: { selector: selectorOf(a), rel } };
  };
  // Where a note is on screen now (viewport coordinates), or null if its element isn't on this screen.
  const placeOf = (n) => {
    try {
      if (n.anchor && n.anchor.selector) {
        const a = document.querySelector(n.anchor.selector);
        if (a) {
          const r = a.getBoundingClientRect(), o = n.anchor.off, q = n.anchor.rel;
          if (o) return { x: r.left + o.x, y: r.top + o.y, w: o.w, h: o.h };
          if (q) return { x: r.left + q.x * r.width, y: r.top + q.y * r.height, w: q.w * r.width, h: q.h * r.height };
        }
      }
      const el = n.selector && document.querySelector(n.selector);
      if (el) { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }
    } catch (_) {}
    return n.rect ? { x: n.rect.x - scrollX, y: n.rect.y - scrollY, w: n.rect.w, h: n.rect.h } : null;
  };
  const ask = (what, x, y, text = "", placeholder = "What's wrong, or what should change?") => {
    $(".what").textContent = what;
    pop.style.display = "block";
    pop.style.left = Math.max(12, Math.min(x, innerWidth - pop.offsetWidth - 12)) + "px";
    pop.style.top = Math.max(12, Math.min(y + 12, innerHeight - pop.offsetHeight - 12)) + "px";
    $(".del").style.display = editing ? "" : "none";
    $(".save").textContent = sending ? "Send" : "Save";
    $("textarea").placeholder = placeholder;
    $("textarea").value = text;
    $("textarea").focus();
  };
  const closePop = () => { pop.style.display = "none"; area.style.display = "none"; hl.style.display = "none"; editing = null; sending = false; };
  const save = async () => {
    const note = $("textarea").value.trim();
    try {
      if (sending) {                                  // Send: every draft goes to the team as one batch
        const r = await post("/notes/send", { app: APP || undefined, summary: note });
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        closePop(); say(d.sent ? `Sent ${d.sent} note${d.sent === 1 ? "" : "s"}. The ${d.to || "Manager"} has them now.` : "Nothing to send.");
      } else if (editing) {
        if (!note) return;
        const r = await post(`/notes/${editing}/edit`, { note });
        if (!r.ok) throw new Error(r.status);
        closePop(); say("Draft updated.");
      } else {
        if (!note) return;
        const body = {
          page: location.href, app: APP || undefined, title: document.title, note, draft: true, kind: target ? "element" : "area",
          selector: target ? selectorOf(target) : null, text: target ? (target.innerText || target.alt || "").trim().slice(0, 300) : null,
          rect, viewport: { w: innerWidth, h: innerHeight }, scroll: { x: scrollX, y: scrollY }, ua: navigator.userAgent,
          ...(target ? {} : boxInfo || {}),
        };
        const r = await post("/notes", body);
        if (!r.ok) throw new Error(r.status);
        closePop(); say("Saved as a draft. Press Send when you're done.");
      }
      load();
    } catch (err) { $(".what").textContent = "Couldn't save (" + err.message + "). Is the inbox running?"; }
  };
  $(".save").onclick = save;
  $(".cancel").onclick = closePop;
  $(".del").onclick = async () => {
    if (!editing) return;
    try {
      const r = await post(`/notes/${editing}/withdraw`, {});
      if (!r.ok) throw new Error(r.status);
      closePop(); say("Draft deleted."); load();
    } catch (err) { $(".what").textContent = "Couldn't delete (" + err.message + ")."; }
  };
  $(".send").onclick = () => {
    if (!drafts) return;
    setMode(null); closePop(); sending = true;
    const from = cfg && cfg.demo ? ` from ${cfg.demo.replace(/^demo/i, "demo")}` : cfg && cfg.mockup ? " from the mockup" : "";
    ask(`Send ${drafts} note${drafts === 1 ? "" : "s"}${from} to the team as one piece of feedback?`, innerWidth - 360, innerHeight - 260,
        "", "Anything to say about them overall? (optional)");
  };
  // Keys typed in a note never reach the app (its own shortcuts would fire).
  $("textarea").addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save(); });
  ["keyup", "keypress", "input"].forEach((t) => $("textarea").addEventListener(t, (e) => e.stopPropagation()));
  $(".mark").onclick = () => setMode("mark");
  $(".areab").onclick = () => setMode("area");
  $(".pins").onclick = () => { showPins = !showPins; draw(); };
  // × folds the toolbar into a small "M" button (remembered for this tab); M opens it again. Nothing is lost.
  const fold = (on) => {
    if (on) { setMode(null); closePop(); }
    host.classList.toggle("folded", on);
    try { sessionStorage.setItem("markFolded", on ? "1" : ""); } catch (_) {}
  };
  $(".close").onclick = () => fold(true);
  $(".fold").onclick = () => { if (!$(".fold").dataset.dragged) fold(false); };
  draggable($(".bar"), "markBarPos");
  draggable($(".fold"), "markFoldPos");
  try { if (sessionStorage.getItem("markFolded")) fold(true); } catch (_) {}
  addEventListener("keydown", (e) => { if (e.key === "Escape") { closePop(); if (mode) setMode(mode); } }, true);

  let drawn = "";
  const draw = () => {
    $(".send").textContent = `Send ${drafts}`;
    $(".send").style.display = drafts ? "inline-block" : "none";
    const spots = showPins ? open.map((n) => [n, placeOf(n)])
      .filter(([, at]) => at && at.y + at.h >= 0 && at.y <= innerHeight && at.x + at.w >= 0 && at.x <= innerWidth) : [];
    const sig = spots.map(([n, a]) => `${n.id}:${a.x | 0},${a.y | 0},${a.w | 0},${a.h | 0}`).join("|");
    if (sig === drawn) return;                       // nothing moved: leave the pins alone
    drawn = sig;
    layer.innerHTML = "";
    spots.forEach(([n, at]) => {
      if (n.kind === "area") {                       // the box the owner drew, following the page
        const b = document.createElement("div");
        b.className = "box";
        Object.assign(b.style, { left: at.x + "px", top: at.y + "px", width: at.w + "px", height: at.h + "px" });
        layer.appendChild(b);
      }
      const p = document.createElement("div");
      p.className = "pin"; p.textContent = open.indexOf(n) + 1;
      p.title = "Your draft (click to change or delete): " + n.note;
      p.style.left = at.x + "px"; p.style.top = at.y + "px";
      p.onclick = (e) => { e.stopPropagation(); setMode(null); closePop(); editing = n.id; ask("Your draft note", e.clientX, e.clientY, n.note); };
      layer.appendChild(p);
    });
  };
  const load = async () => {
    // Only your unsent drafts have pins: once sent, a note is the team's and leaves the page.
    try { open = await (await fetch(INBOX + "/notes?status=draft&page=" + encodeURIComponent(location.href))).json(); } catch (_) { open = []; }
    drawn = null;                                    // always redraw after a load, even down to no pins
    try { drafts = (await (await fetch(INBOX + "/notes?status=draft&scope=mine")).json()).length; } catch (_) { drafts = 0; }
    draw();
  };
  addEventListener("hashchange", load);           // single-page apps: each #route has its own pins
  // Redraw on any scroll (panels that scroll on their own too), resize, and now and then for layout changes.
  let queued = false;
  const redraw = () => {
    if (queued) return;
    queued = true;
    (document.hidden ? setTimeout : requestAnimationFrame)(() => { queued = false; draw(); });
  };
  addEventListener("scroll", redraw, { passive: true, capture: true });
  addEventListener("resize", redraw);
  let href = location.href;                        // apps that change screen without a #route change (pushState)
  setInterval(() => {
    if (location.href !== href) { href = location.href; load(); } else if (open.length && showPins) redraw();
  }, 700);
  addEventListener("popstate", load);
  load();
  // From the bookmarklet the owner clicked to mark something: start in Mark mode. On a review link the
  // toolbar just waits, so the app works normally until the owner presses Mark.
  if (!INBOX.startsWith("/")) setMode("mark");
})();
