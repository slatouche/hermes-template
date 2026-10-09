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
    .mzone{position:fixed;left:20px;bottom:20px;display:flex;flex-direction:column;align-items:flex-start;gap:6px;
      width:max-content;max-width:calc(50vw - 24px);pointer-events:auto;z-index:2;touch-action:none}
    .cbar{position:fixed;right:20px;bottom:20px;display:flex;gap:6px;align-items:center;justify-content:flex-end;flex-wrap:wrap;
      width:max-content;max-width:calc(50vw - 24px);box-shadow:0 8px 30px rgba(0,0,0,.45);pointer-events:auto;color:#e8e8ea;z-index:2;touch-action:none}
    .mtools{display:none;gap:6px;flex-wrap:wrap;box-shadow:0 8px 30px rgba(0,0,0,.45)}
    .mzone.tools .mtools{display:flex}
    button.mbadge{background:#15161a;color:#8fb0ff;font-weight:600;box-shadow:0 6px 20px rgba(0,0,0,.45)}
    button.mbadge:hover{background:#1d2029}
    button{border:0;border-radius:8px;padding:7px 11px;background:#23252c;color:#e8e8ea;cursor:pointer}
    button:hover{background:#2d3039}button.on{background:#3d6bff;color:#fff}
    .hl{position:fixed;border:2px solid #3d6bff;background:rgba(61,107,255,.12);border-radius:4px;pointer-events:none;display:none}
    .area{position:fixed;border:2px dashed #ffb02e;background:rgba(255,176,46,.10);pointer-events:none;display:none}
    .pin{position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:#ffb02e;color:#1a1300;
      font-weight:700;font-size:12px;display:flex;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;
      box-shadow:0 2px 8px rgba(0,0,0,.4)}
    button.send{background:#1e7d4f;color:#fff;font-weight:600;display:none}button.send:hover{background:#249760}
    button.send:disabled{opacity:.6;cursor:default}
    input.fb{border:1px solid #2a2c33;background:#0f1013;color:#e8e8ea;border-radius:8px;padding:6px 9px;width:170px;font:inherit}
    input.fb::placeholder{color:#7c828f}input.fb:focus{outline:none;border-color:#3d6bff}
    button.del{margin-right:auto;background:transparent;color:#ff8095}
    .pop{position:fixed;width:min(340px,calc(100vw - 24px));padding:10px;border-radius:12px;background:#15161a;
      border:1px solid #2a2c33;box-shadow:0 12px 40px rgba(0,0,0,.5);pointer-events:auto;color:#e8e8ea;display:none}
    .pop textarea{width:100%;min-height:90px;resize:vertical;border-radius:8px;border:1px solid #2a2c33;background:#0f1013;
      color:#e8e8ea;padding:8px}.pop .row{display:flex;gap:6px;justify-content:flex-end;margin-top:8px}
    .pop .what{color:#9aa0ad;margin-bottom:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .toast{position:fixed;left:50%;bottom:76px;transform:translateX(-50%);padding:8px 12px;border-radius:8px;background:#1e7d4f;
      color:#fff;display:none}
    .round{position:fixed;right:20px;bottom:74px;display:none;max-width:min(340px,calc(100vw - 40px));
      color:#cfd6ea;font-weight:600;pointer-events:auto;cursor:move;line-height:1.3;white-space:nowrap;overflow:hidden;
      text-overflow:ellipsis;box-shadow:0 8px 30px rgba(0,0,0,.45)}
    .round.on{display:block}
    .round.need{color:#ffe0a8}
    .round.done{color:#bdf0d2}
    button.qback{display:none;background:#7a3cff;color:#fff;font-weight:600;max-width:min(320px,44vw);overflow:hidden;
      text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
    button.qback.on{display:inline-block}button.qback:hover{background:#8a54ff}
    .rbar{position:fixed;right:16px;bottom:120px;width:min(380px,calc(100vw - 24px));padding:10px;border-radius:12px;
      background:#15161a;border:1px solid #2a2c33;box-shadow:0 12px 40px rgba(0,0,0,.5);pointer-events:auto;color:#e8e8ea;display:none}
    .rbar .q{color:#ffe0a8;font-weight:600;margin-bottom:4px;max-height:7.5em;overflow:auto}
    .rbar .to{color:#9aa0ad;margin-bottom:6px}
    .rbar textarea{width:100%;min-height:64px;resize:vertical;border-radius:8px;border:1px solid #2a2c33;background:#0f1013;
      color:#e8e8ea;padding:8px}
    .rbar .row{display:flex;gap:6px;justify-content:flex-end;margin-top:8px}
    .rbar button.post{background:#3d6bff;color:#fff;font-weight:600}
    .layer{position:absolute;left:0;top:0}
    .box{position:absolute;border:1.5px dashed #ffb02e;border-radius:4px;pointer-events:none}
    .fold{position:fixed;right:20px;bottom:20px;width:36px;height:36px;border-radius:50%;background:#3d6bff;color:#fff;
      font-weight:700;display:none;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;
      box-shadow:0 6px 20px rgba(0,0,0,.45)}
    :host(.folded) .cbar{display:none}:host(.folded) .round{display:none}:host(.folded) .fold{display:flex}:host(.folded) .layer{display:none}
    .pop{z-index:5}.toast{z-index:6}.rbar{z-index:5}.mzone,.cbar,.fold,.round{z-index:2;touch-action:none}
    button.mbadge.on{background:#3d6bff}
    .mtools{color:#e8e8ea}.mtools b{background:rgba(255,255,255,.22);padding:1px 7px;border-radius:999px}
    /* One look: every box on the overlay is the same dark surface — progress chip, note box, tools, left badge.
       Same border, radius, fill, type and padding, so they read as one family; only their content tells them apart. */
    .round,.cbar,.mtools,button.mbadge{border:1px solid #2a2c33;border-radius:12px;background:#15161a;font-size:13px;
      padding:8px;box-sizing:border-box}
    /* The design nav: Mockup · Demo 1 · Demo 2, the same three views in every project, top centre. */
    .nav{position:fixed;top:10px;left:50%;transform:translateX(-50%);display:none;gap:2px;z-index:3;
      border:1px solid #2a2c33;border-radius:999px;background:#15161a;padding:3px;font:12px/1.2 system-ui,sans-serif;
      box-shadow:0 6px 20px rgba(0,0,0,.45);pointer-events:auto;max-width:calc(100vw - 24px)}
    .nav a{color:#c9cbd2;text-decoration:none;padding:5px 11px;border-radius:999px;white-space:nowrap;overflow:hidden;
      text-overflow:ellipsis;max-width:260px}
    .nav a:hover{background:#23262f}.nav a.here{background:#3d6bff;color:#fff;font-weight:600}
    .nav a.empty{color:#5d606b}.nav a small{opacity:.75;margin-left:6px;font-size:11px}
    :host(.folded) .nav{display:none !important}
  </style>
  <nav class="nav"></nav>
  <div class="hl"></div><div class="area"></div><div class="layer"></div>
  <div class="pop"><div class="what"></div><textarea placeholder="What's wrong, or what should change?"></textarea>
    <div class="row"><button class="del">Delete</button><button class="cancel">Cancel</button><button class="save on">Save</button></div></div>
  <div class="toast"></div>
  <div class="rbar"><div class="q"></div><div class="to"></div>
    <textarea placeholder="Your answer to the Designer…"></textarea>
    <div class="row"><button class="later">later</button><button class="post on">Send answer</button></div></div>
  <div class="mzone"><div class="mtools"><button class="mark" title="Click an element to mark it">Mark</button>
    <button class="areab" title="Drag a box over an area">Area</button>
    <button class="pins" title="Show or hide your draft pins">Pins</button></div>
    <button class="mbadge" title="Marking tools — Mark, Area, Pins">Mark ▾</button></div>
  <span class="round"></span>
  <div class="cbar"><button class="qback" title="The Designer asked you something — click to bring the answer bar back"></button>
    <input class="fb" placeholder="Note about this page…" title="Feedback about the page itself — type and press Send">
    <button class="send" title="Send your notes to the team (no question asked)"></button>
    <button class="close" title="Fold the comms away (click M to bring them back)">×</button></div>
  <div class="fold" title="Open the Mark toolbar">M</div>`;
  const $ = (s) => root.querySelector(s);
  const hl = $(".hl"), area = $(".area"), pop = $(".pop"), layer = $(".layer"), toast = $(".toast");
  let mode = null, target = null, rect = null, start = null, open = [], showPins = true;
  let editing = null, drafts = 0;                    // editing: the draft whose pin was clicked
  const APP = "__APP__";
  let sayTimer = 0;
  const say = (msg, ms = 2600) => {
    toast.textContent = msg; toast.style.display = "block";
    clearTimeout(sayTimer); if (ms) sayTimer = setTimeout(() => (toast.style.display = "none"), ms);
  };
  const post = (path, body) => fetch(INBOX + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const store = (k, v) => { try { v === undefined ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch (_) {} };
  const recall = (k) => { try { return sessionStorage.getItem(k); } catch (_) { return null; } };

  // Drag a box out of the way of the app's own buttons (remembered for this tab). What is remembered is the gap to
  // the edge the owner dropped it nearest — not a pixel from the left — so at any window width the box keeps that
  // gap and reads as the same corner they put it in. Every drop is clamped fully on-screen, and a resize re-places
  // each dragged box the same way, so none can be stranded or half off the viewport.
  const EDGE = 20;                                   // the page's own inset: the chrome lines up with the app's bar
  const layoutW = () => document.documentElement.clientWidth, layoutH = () => document.documentElement.clientHeight;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
  const place = (el, a) => {                         // a = [hEdge, hGap, vEdge, vGap]
    const W = layoutW(), H = layoutH(), w = el.offsetWidth, h = el.offsetHeight;
    const [he, hg, ve, vg] = a;
    Object.assign(el.style, {
      left: he === "left" ? clamp(hg, EDGE, Math.max(EDGE, W - w - EDGE)) + "px" : "auto",
      right: he === "right" ? clamp(hg, EDGE, Math.max(EDGE, W - w - EDGE)) + "px" : "auto",
      top: ve === "top" ? clamp(vg, EDGE, Math.max(EDGE, H - h - EDGE)) + "px" : "auto",
      bottom: ve === "bottom" ? clamp(vg, EDGE, Math.max(EDGE, H - h - EDGE)) + "px" : "auto",
    });
  };
  const anchorOf = (el) => {                         // which edge it is nearest, and the gap to that edge
    const r = el.getBoundingClientRect(), W = layoutW(), H = layoutH();
    const he = r.left + r.width / 2 < W / 2 ? "left" : "right";
    const ve = r.top + r.height / 2 < H / 2 ? "top" : "bottom";
    return [he, he === "left" ? r.left : W - r.right, ve, ve === "top" ? r.top : H - r.bottom];
  };
  const anchors = new Map();                         // el -> its last edge anchor, so a resize can re-place it
  const draggable = (el, key) => {
    const remember = (a) => { anchors.set(el, a); store(key, a.join(",")); };
    const saved = recall(key);
    if (saved) {                                     // "x,y" keys from before read as a left/top drop
      const p = saved.split(",");
      const a = p.length === 4 ? p : ["left", p[0], "top", p[1]];
      anchors.set(el, a);
      requestAnimationFrame(() => place(el, a));
    }
    el.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button,input,textarea") && !el.classList.contains("small")) return;
      const r = el.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      let moved = false;
      const move = (m) => {
        moved = true;
        const W = layoutW(), H = layoutH(), w = el.offsetWidth, h = el.offsetHeight;
        const x = clamp(m.clientX - dx, EDGE, Math.max(EDGE, W - w - EDGE));
        const y = clamp(m.clientY - dy, EDGE, Math.max(EDGE, H - h - EDGE));
        Object.assign(el.style, { left: x + "px", top: y + "px", right: "auto", bottom: "auto" });
      };
      const up = () => {
        removeEventListener("pointermove", move); removeEventListener("pointerup", up);
        if (moved) { remember(anchorOf(el)); el.dataset.dragged = "1"; setTimeout(() => delete el.dataset.dragged, 0); }
      };
      addEventListener("pointermove", move); addEventListener("pointerup", up);
    });
  };
  addEventListener("resize", () => anchors.forEach((a, el) => place(el, a)));

  // One left control: a single marking badge. Tapping it opens the tools (Mark / Area / Pins); on the mockup the look
  // switcher rides in that same panel. The page name lives in the badge's own tooltip, never as a pill of its own.
  const badge = $(".mbadge"), cfg = window.__markBadge, mtools = $(".mtools");
  let pageName = "";
  if (cfg) {
    pageName = cfg.demo ? cfg.demo.replace(/^demo/i, "Demo")
      : cfg.mockup ? (/^prototype /.test(cfg.mockup) ? "Mockup · " + cfg.mockup.split(":")[0] + " · a copy of the app" : cfg.mockup + " · a copy of the app")
      : "";
    const add = (tag, text, fn) => { const n = document.createElement(tag); n.textContent = text; if (fn) n.onclick = fn; mtools.appendChild(n); return n; };
    if (cfg.mockup) add("button", "reset data", () => {
      if (confirm("Put the mockup's data back to a fresh copy of the real data?"))
        fetch(INBOX + "/mockup/reset", { method: "POST" }).then(() => location.reload());
    });
    if (cfg.looks && cfg.looks.length) {
      const sw = (v) => { const u = new URL(location.href); u.searchParams.set("__variant", v); location.href = u.pathname + u.search + u.hash; };
      add("span", "Look:");
      [["off", "current"], ...cfg.looks.map((n) => [n, n])].forEach(([key, label]) =>
        key === (cfg.variant || "off") ? add("b", label) : add("button", label, () => sw(key)));
      add("button", "compare", () => (location.href = "/__mark/variants"));
    }
  }
  // The nav badge: one tap between the mockup (the app in work, the main design view) and the two demos
  // (throwaway visuals: options to pick from, palettes, swatches). Each shows what it holds now.
  if (cfg && cfg.nav && cfg.nav.length) {
    const nav = $(".nav");
    cfg.nav.forEach((v) => {
      const a = document.createElement("a");
      a.href = `${location.protocol}//${location.hostname}:${v.port}/`;
      a.textContent = v.label;
      if (v.what) { const s = document.createElement("small"); s.textContent = v.what; a.appendChild(s); }
      a.title = v.what ? `${v.label}: ${v.what}` : `${v.label}: nothing here yet`;
      if (v.here) a.classList.add("here");
      if (!v.what && !v.here) a.classList.add("empty");
      nav.appendChild(a);
    });
    nav.style.display = "flex";
  }
  draggable($(".mzone"), "markZonePos");
  // The badge names the live mode, so one tap shows where the owner is: Mark or Area (blue while that mode is on),
  // with the page name and what the tools do in its tooltip.
  const updateBadge = () => {
    badge.classList.toggle("on", !!mode);
    badge.textContent = (mode === "area" ? "Area" : "Mark") + " \u25be";
    badge.title = "Marking tools — Mark, Area, Pins" + (mode ? ` · ${mode === "area" ? "Area" : "Mark"} mode is on` : "")
      + (pageName ? ` · ${pageName} · a demo of something new: nothing here touches your real data` : "");
  };
  updateBadge();

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
    updateBadge();
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
  // The overlay's own panels are UI: a pointer-down inside one must never start a mark, because the handler below
  // cancels the event to keep the page under it clean — and a cancelled pointer-down means the control never takes
  // focus, so anything the owner types into silently does nothing. Everything the overlay puts in its shadow root
  // counts, except the marking visuals that sit under the pointer on purpose and the toast, so a new panel is UI by
  // default and nobody has to remember to add it to a list. Pins live inside the marking layer, so they are named.
  const NOT_UI = new Set([hl, area, layer, toast]);
  const onUi = (e) => e.composedPath().some((n) => (n.parentNode === root && !NOT_UI.has(n)) || (n.classList && n.classList.contains("pin")));
  host.addEventListener("pointerdown", (e) => {
    if (onUi(e) || popOpen()) return;              // finish or cancel the open note before starting another
    e.preventDefault();
    if (mode === "area") start = { x: e.clientX, y: e.clientY };
  });
  host.addEventListener("pointerup", (e) => {
    if (onUi(e) || popOpen() || !mode) return;
    editing = null;                                  // a new mark is always a new note, never an edit
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
    $(".save").textContent = "Save";
    $("textarea").placeholder = placeholder;
    $("textarea").value = text;
    $("textarea").focus();
  };
  const closePop = () => { pop.style.display = "none"; area.style.display = "none"; hl.style.display = "none"; editing = null; };
  const ctxOf = (el) => {
    if (!el || !el.getBoundingClientRect) return null;
    const keys = ["display", "position", "width", "height", "font-size", "font-weight", "line-height", "color",
      "background-color", "margin", "padding", "gap", "grid-template-columns", "grid-column", "flex", "justify-content",
      "align-items", "border", "border-radius", "max-width", "overflow", "text-transform", "letter-spacing"];
    const style = {}, cs = getComputedStyle(el);
    keys.forEach((k) => { const v = cs.getPropertyValue(k); if (v && !["normal", "none", "auto", "0px", "visible", "static"].includes(v)) style[k] = v.slice(0, 120); });
    const par = el.parentElement, ps = par ? getComputedStyle(par) : null;
    return {
      style, html: (el.outerHTML || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").slice(0, 900),
      parent: par ? { selector: selectorOf(par), display: ps.display, "grid-template-columns": ps.gridTemplateColumns.slice(0, 120), width: ps.width } : null,
    };
  };
  const save = async () => {
    const note = $("textarea").value.trim();
    try {
      if (editing) {
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
        try {
          const anchor = !target && boxInfo && boxInfo.anchor && document.querySelector(boxInfo.anchor.selector);
          body.ctx = ctxOf(target || anchor);
        } catch (_) {}
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
  // Send is one press: any text in the toolbar's own box becomes a note about the page itself (no element), then every
  // draft left on this link goes to the team together. Send never asks a question — the notes just go.
  const handleSend = async (d) => {
    const q = d.quick;
    if (q && q.applied.length) {
      const rest = q.open.length ? ` The ${d.to || "Designer"} has ${q.open.length} more.` : "";
      say(`Changed ${q.applied.length} in ${q.secs}s: ${q.applied.map((a) => a.did).join(" · ")}.${rest}`, 9000);
      if (q.look !== ((cfg && cfg.variant) || "")) {           // the fixes went into a look this page isn't showing yet
        const u = new URL(location.href); u.searchParams.set("__variant", q.look); location.href = u.pathname + u.search + u.hash;
      } else checkLook(true);
    } else {
      say(d.sent ? `Sent ${d.sent} note${d.sent === 1 ? "" : "s"}. The ${d.to || "Manager"} has them now.` : "Nothing to send.", 5000);
    }
  };
  const sendNow = async () => {
    const box = $(".fb"), text = box.value.trim();
    if (!drafts && !text) { say("Type a note or mark something first, then Send.", 3200); box.focus(); return; }
    $(".send").disabled = true;
    try {
      if (text) {                                    // the toolbar's note is about the page itself: no element
        const r = await post("/notes", {
          page: location.href, app: APP || undefined, title: document.title, note: text, draft: true, kind: "page",
          selector: null, text: null, rect: null,
          viewport: { w: innerWidth, h: innerHeight }, scroll: { x: scrollX, y: scrollY }, ua: navigator.userAgent,
        });
        if (!r.ok) throw new Error(r.status);
        box.value = "";
      }
      say("Sending…", 0);
      const r = await post("/notes/send", { app: APP || undefined });
      if (!r.ok) throw new Error(r.status);
      handleSend(await r.json());
    } catch (err) { say("Couldn't send (" + err.message + "). Is the inbox running?", 5000); }
    $(".send").disabled = false;
    load();
  };
  $(".send").onclick = sendNow;
  // The toolbar's own box: Enter sends too, and its keys never reach the app's shortcuts.
  $(".fb").addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); sendNow(); }
  });
  ["keyup", "keypress", "input"].forEach((t) => $(".fb").addEventListener(t, (e) => e.stopPropagation()));
  $(".fb").addEventListener("input", () => draw());
  // Keys typed in a note never reach the app (its own shortcuts would fire).
  $("textarea").addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save(); });
  ["keyup", "keypress", "input"].forEach((t) => $("textarea").addEventListener(t, (e) => e.stopPropagation()));
  $(".mark").onclick = () => setMode("mark");
  $(".areab").onclick = () => setMode("area");
  $(".pins").onclick = () => { showPins = !showPins; $(".pins").classList.toggle("on", !showPins); draw(); };
  $(".mbadge").onclick = () => $(".mzone").classList.toggle("tools");   // the left badge: tap for Mark / Area / Pins
  // × folds the toolbar into a small "M" button (remembered for this tab); M opens it again. Nothing is lost.
  const fold = (on) => {
    if (on) { setMode(null); closePop(); }
    host.classList.toggle("folded", on);
    try { sessionStorage.setItem("markFolded", on ? "1" : ""); } catch (_) {}
  };
  $(".close").onclick = () => fold(true);
  $(".fold").onclick = () => { if (!$(".fold").dataset.dragged) fold(false); };
  draggable($(".cbar"), "markCbarPos");
  draggable($(".fold"), "markFoldPos");
  draggable($(".round"), "markRoundPos");          // the progress chip: its own element, movable anywhere
  try { if (sessionStorage.getItem("markFolded")) fold(true); } catch (_) {}
  addEventListener("keydown", (e) => { if (e.key === "Escape") { closePop(); if (mode) setMode(mode); } }, true);

  let drawn = "";
  const draw = () => {
    $(".send").textContent = drafts ? `Send ${drafts}` : "Send";
    $(".send").style.display = (drafts || $(".fb").value.trim()) ? "inline-block" : "none";
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
  // The round: what the Designer is doing with the notes you sent, on the page you sent them from. When it has a
  // question the answer bar opens, and the answer goes back to the same Designer session (/notes/answer). The 2 s
  // poll below is the transport: no second poll, no second service.
  const roundEl = $(".round"), rbar = $(".rbar"), rq = $(".rbar .q"), rto = $(".rbar .to"), rbox = $(".rbar textarea"),
        qback = $(".qback");
  let roundCard = null, roundQ = null, rbarHidden = null, roundBlk = null, roundAt = 0;
  // The way back: the question is the owner's to answer while it is live, even after "later" shut the bar — so the
  // toolbar keeps a button naming it, and one click brings the bar back with that same question. While there is no
  // live question (a round working or done, or one already answered) there is nothing to come back to and it is gone.
  const syncQback = () => {
    const on = !!roundQ;
    qback.classList.toggle("on", on);
    if (on) {
      qback.textContent = "Question: " + (roundQ.length > 40 ? roundQ.slice(0, 39) + "\u2026" : roundQ);
      qback.title = "The Designer asked: " + roundQ + " \u2014 click to bring the answer bar back";
    }
  };
  const hideRbar = () => { rbar.style.display = "none"; syncQback(); };
  const openRbar = () => {
    rq.textContent = roundQ || "";
    rto.textContent = roundCard ? `Round ${roundCard}: your answer goes back to the Designer who asked, in this page's session.` : "";
    rbar.style.display = "block";
    syncQback();
  };
  const fmtSpan = (s) => (s == null ? null
    : s >= 3600 ? `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`
    : s >= 60 ? `${Math.floor(s / 60)}m ${String(Math.floor(s % 60)).padStart(2, "0")}s` : `${Math.floor(s)}s`);
  // The chip: state, how long, and what the worker is on right now. While it works the count keeps moving — a local
  // repaint of the block the 2 s poll already fetched, so no extra request — and a step that has been quiet for more
  // than 90 s says so instead of looking hung. A question always wins the chip.
  const roundText = (b, late) => {
    const st = b.state || "working";
    if (st === "needs_you") return "Round needs you" + (b.question ? " \u00b7 " + b.question : "");
    if (st === "done") return "Round done" + (b.question ? " \u2014 question" : "");
    const drift = late ? Math.floor((Date.now() - roundAt) / 1000) : 0;
    const idle = b.idle == null ? null : b.idle + drift;
    let s = "Round working \u00b7 " + (fmtSpan(b.secs == null ? null : b.secs + drift) || "\u2014");
    if (b.step) s += " \u00b7 " + b.step;
    if (idle != null && idle > 90) s += ` \u2014 no movement for ${fmtSpan(idle)}`;
    return s;
  };
  const roundLine = (b, late) => {
    roundBlk = b;
    if (!b) { roundCard = null; roundQ = null; roundEl.className = "round"; roundEl.textContent = ""; roundEl.title = ""; hideRbar(); return; }
    if (!late) roundAt = Date.now();
    roundCard = b.card; roundQ = b.question || null;
    const st = b.state || "working";
    roundEl.className = "round on " + (st === "needs_you" ? "need" : st);
    roundEl.textContent = roundText(b, late);
    roundEl.title = roundQ || roundEl.textContent;
    if (anchors.has(roundEl)) place(roundEl, anchors.get(roundEl));   // a wider label never spills off-screen
    if (roundQ && rbarHidden !== b.card) openRbar(); else hideRbar();
  };
  setInterval(() => { if (roundBlk && (roundBlk.state || "working") === "working") roundLine(roundBlk, true); }, 1000);
  roundEl.onclick = () => { if (roundEl.dataset.dragged) return; if (roundQ) { rbarHidden = null; openRbar(); } };
  qback.onclick = () => { if (roundQ) { rbarHidden = null; openRbar(); } };
  $(".rbar .later").onclick = () => { rbarHidden = roundCard; hideRbar(); };
  $(".rbar .post").onclick = async () => {
    const text = rbox.value.trim();
    if (!text) { say("Type your answer first.", 2400); return; }
    if (!roundCard) { say("That round is gone — reload the page.", 3000); return; }
    $(".rbar .post").disabled = true;
    let d = {};
    try { d = await (await post("/notes/answer", { card: roundCard, text, page: location.href })).json(); } catch (_) {}
    $(".rbar .post").disabled = false;
    if (!d || (!d.card && !d.test)) { say("The answer didn't get through — try again.", 3200); return; }
    rbox.value = "";
    // A browser check's answer (`?test=1`) is recorded as evidence and never becomes work: the round stays unanswered
    // and its question stays live, so say so instead of claiming the Designer has it.
    if (d.test) { say("Check answer recorded — the round is not answered.", 4000); return; }
    rbarHidden = null; roundQ = null; hideRbar();
    say("Answer sent — the Designer is on it.", 3200);
    checkLook(true);
  };
  let lookSeen = null;
  const canPoll = !!(cfg && (cfg.variant || cfg.demo || cfg.mockup));   // a demo or the mockup carries a round as well
  const checkLook = async (now) => {
    const v = cfg && cfg.variant;
    if (!canPoll || (document.hidden && !now)) return;
    let d;
    try { d = await (await fetch(INBOX + "/look-version?v=" + encodeURIComponent(v || ""), { cache: "no-store" })).json(); } catch (_) { return; }
    if (!d) return;
    if (d.round || roundCard) roundLine(d.round || null);        // the page's round: state, and its question
    if (cfg && cfg.mockup && "look" in d && !/[?&]__variant=/.test(location.search) && (d.look || "") !== (v || "")) { location.reload(); return; }   // a new working look
    if (!v || d.css === undefined) return;
    if (lookSeen && d.js !== lookSeen.js) { location.reload(); return; }
    if (lookSeen && d.css !== lookSeen.css) {
      document.querySelectorAll(`link[href^="/__mark/v/${v}/style.css"]`).forEach((l) => (l.href = `/__mark/v/${v}/style.css?t=${d.css}`));
      if (!now) say("The look just changed: showing it.", 3000);
    }
    lookSeen = d;
  };
  if (canPoll) {                                   // every 2 s while you look; at once when you come back to the tab
    checkLook(); setInterval(checkLook, 2000);
    addEventListener("visibilitychange", () => { if (!document.hidden) checkLook(); });
  }
  load();
  // From the bookmarklet the owner clicked to mark something: start in Mark mode. On a review link the
  // toolbar just waits, so the app works normally until the owner presses Mark.
  if (!INBOX.startsWith("/")) setMode("mark");
})();
