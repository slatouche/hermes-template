/* Mark overlay: the owner marks things on a page and the notes go to the project's feedback inbox.
   Loaded by the "Mark" bookmarklet from the inbox (__INBOX__ is filled in when it's served).
   Mark = click an element; Area = drag a box. Type what's wrong, Save (Ctrl+Enter). Esc stops.
   Saved notes are drafts (amber pins: click one to change or delete it) until Send hands them all to the team at once.
   Everything lives in a shadow root so the page's styles can't touch it, and it never changes the page. */
(() => {
  if (window.__markLoaded) return;
  window.__markLoaded = true;
  const INBOX = "__INBOX__";
  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647";
  document.documentElement.appendChild(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>
    :host{all:initial}*{box-sizing:border-box;font:13px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
    .bar{position:fixed;right:16px;bottom:16px;display:flex;gap:6px;padding:6px;border-radius:12px;background:#15161a;
      border:1px solid #2a2c33;box-shadow:0 8px 30px rgba(0,0,0,.45);pointer-events:auto;color:#e8e8ea;align-items:center}
    button{border:0;border-radius:8px;padding:7px 11px;background:#23252c;color:#e8e8ea;cursor:pointer}
    button:hover{background:#2d3039}button.on{background:#3d6bff;color:#fff}.count{padding:0 6px;color:#9aa0ad}
    .hl{position:fixed;border:2px solid #3d6bff;background:rgba(61,107,255,.12);border-radius:4px;pointer-events:none;display:none}
    .area{position:fixed;border:2px dashed #ffb02e;background:rgba(255,176,46,.10);pointer-events:none;display:none}
    .pin{position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:#ff4d6d;color:#fff;
      font-weight:700;font-size:12px;display:flex;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;
      box-shadow:0 2px 8px rgba(0,0,0,.4)}.pin.draft{background:#ffb02e;color:#1a1300}
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
    .fold{position:fixed;right:16px;bottom:16px;width:36px;height:36px;border-radius:50%;background:#3d6bff;color:#fff;
      font-weight:700;display:none;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;
      box-shadow:0 6px 20px rgba(0,0,0,.45)}
    :host(.folded) .bar{display:none}:host(.folded) .fold{display:flex}:host(.folded) .layer{display:none}
  </style>
  <div class="hl"></div><div class="area"></div><div class="layer"></div>
  <div class="pop"><div class="what"></div><textarea placeholder="What's wrong, or what should change?"></textarea>
    <div class="row"><button class="del">Delete</button><button class="cancel">Cancel</button><button class="save on">Save</button></div></div>
  <div class="toast"></div>
  <div class="bar"><button class="mark" title="Click an element to mark it">Mark</button>
    <button class="areab" title="Drag a box over an area">Area</button><span class="count"></span>
    <button class="send" title="Send your draft notes to the team as one piece of feedback"></button>
    <button class="pins" title="Show or hide the numbered notes">Pins</button><button class="close" title="Fold away (click M to bring it back)">×</button></div>
  <div class="fold" title="Open the Mark toolbar">M</div>`;
  const $ = (s) => root.querySelector(s);
  const hl = $(".hl"), area = $(".area"), pop = $(".pop"), layer = $(".layer"), toast = $(".toast");
  let mode = null, target = null, rect = null, start = null, open = [], showPins = true;
  let editing = null, sending = false, drafts = 0;   // editing: the draft whose pin was clicked; sending: the Send box
  const APP = "__APP__";
  const say = (msg) => { toast.textContent = msg; toast.style.display = "block"; setTimeout(() => (toast.style.display = "none"), 2600); };
  const post = (path, body) => fetch(INBOX + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

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

  host.addEventListener("mousemove", (e) => {
    if (pop.style.display === "block") return;
    if (mode === "mark") { const el = underPointer(e.clientX, e.clientY); if (el && el !== host) boxAt(el.getBoundingClientRect()); }
    if (mode === "area" && start) {
      const x = Math.min(start.x, e.clientX), y = Math.min(start.y, e.clientY);
      area.style.cssText += `;display:block;left:${x}px;top:${y}px;width:${Math.abs(e.clientX - start.x)}px;height:${Math.abs(e.clientY - start.y)}px`;
    }
  });
  host.addEventListener("mousedown", (e) => {
    if (e.composedPath().some((n) => n === pop || n === $(".bar"))) return;
    e.preventDefault();
    if (mode === "area") start = { x: e.clientX, y: e.clientY };
  });
  host.addEventListener("mouseup", (e) => {
    if (e.composedPath().some((n) => n === pop || n === $(".bar"))) return;
    if (mode === "mark") {
      target = underPointer(e.clientX, e.clientY);
      const r = target.getBoundingClientRect();
      rect = { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height };
      ask(`${target.tagName.toLowerCase()}: ${(target.innerText || target.alt || "").trim().slice(0, 60)}`, e.clientX, e.clientY);
    } else if (mode === "area" && start) {
      const x = Math.min(start.x, e.clientX), y = Math.min(start.y, e.clientY);
      rect = { x: x + scrollX, y: y + scrollY, w: Math.abs(e.clientX - start.x), h: Math.abs(e.clientY - start.y) };
      start = null; target = null;
      if (rect.w < 6 || rect.h < 6) { area.style.display = "none"; return; }
      ask(`area ${Math.round(rect.w)}×${Math.round(rect.h)}`, e.clientX, e.clientY);
    }
  });
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
        closePop(); say(d.sent ? `Sent ${d.sent} note${d.sent === 1 ? "" : "s"}. The Manager has them now.` : "Nothing to send.");
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
    await post(`/notes/${editing}/withdraw`, {});
    closePop(); say("Draft deleted."); load();
  };
  $(".send").onclick = () => {
    if (!drafts) return;
    setMode(null); closePop(); sending = true;
    ask(`Send ${drafts} note${drafts === 1 ? "" : "s"} to the team as one piece of feedback?`, innerWidth - 360, innerHeight - 260,
        "", "Anything to say about them overall? (optional)");
  };
  $("textarea").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save(); });
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
  $(".fold").onclick = () => fold(false);
  try { if (sessionStorage.getItem("markFolded")) fold(true); } catch (_) {}
  addEventListener("keydown", (e) => { if (e.key === "Escape") { closePop(); if (mode) setMode(mode); } }, true);

  const draw = () => {
    layer.innerHTML = "";
    layer.style.transform = `translate(${-scrollX}px,${-scrollY}px)`;
    const sent = open.filter((n) => n.status === "open").length;
    $(".count").textContent = sent ? `${sent} sent` : "";
    $(".send").textContent = `Send ${drafts}`;
    $(".send").style.display = drafts ? "inline-block" : "none";
    if (!showPins) return;
    open.forEach((n, i) => {
      let x = n.rect && n.rect.x, y = n.rect && n.rect.y;
      try { const el = n.selector && document.querySelector(n.selector); if (el) { const r = el.getBoundingClientRect(); x = r.left + scrollX; y = r.top + scrollY; } } catch (_) {}
      if (x == null) return;
      const p = document.createElement("div");
      const draft = n.status === "draft";
      p.className = "pin" + (draft ? " draft" : ""); p.textContent = i + 1;
      p.title = (draft ? "Draft (click to change): " : "Sent: ") + n.note;
      p.style.left = x + "px"; p.style.top = y + "px";
      if (draft) p.onclick = (e) => { e.stopPropagation(); setMode(null); closePop(); editing = n.id; ask("Your draft note", e.clientX, e.clientY, n.note); };
      layer.appendChild(p);
    });
  };
  const load = async () => {
    try { open = await (await fetch(INBOX + "/notes?status=draft,open&page=" + encodeURIComponent(location.href))).json(); } catch (_) { open = []; }
    try { drafts = (await (await fetch(INBOX + "/notes?status=draft" + (APP ? "&app=" + encodeURIComponent(APP) : ""))).json()).length; } catch (_) { drafts = 0; }
    draw();
  };
  addEventListener("hashchange", load);           // single-page apps: each #route has its own pins
  addEventListener("scroll", draw, { passive: true });
  addEventListener("resize", draw);
  load();
  // From the bookmarklet the owner clicked to mark something: start in Mark mode. On a review link the
  // toolbar just waits, so the app works normally until the owner presses Mark.
  if (!INBOX.startsWith("/")) setMode("mark");
})();
