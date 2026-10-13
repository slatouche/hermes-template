/* mirror.js: the design view's eyes. One headless Chromium, kept running beside design-view.py, showing the app as the
   owner has it (the screen, window size, scroll, the option being looked at, the edits so far), so every picture is a
   real screenshot: pixel-true (pinned bars stay pinned), taken in a fraction of a second, and nothing is saved.
   The owner's own browser draws nothing, so marking stays smooth.
   design-view.py starts it (node mirror.js <chrome> <base url>) and talks in JSON lines on stdin/stdout; it talks to
   Chromium over the DevTools pipe (no port, no packages). It exits when design-view.py does, and takes Chromium along.
   Requests, one at a time in order (a "follow" is dropped when a newer request is waiting):
     follow {view}                    get the page into the owner's state ahead of time (nothing comes back)
     shot   {view, marks, zoom, close, scrolled}  -> {image, zoom: [...], close: [{label, what, image}], scrolled: [{label, image}], missing}
     inspect {view, spec}             -> {value: the layer's measurements of the elements in spec}
     measure {view}                   load a choice of an option set (view.opt) and have the layer judge its edits:
                                      it reports them to design-view.py (/dv/report), as the owner's page would
   It looks after itself: a crashed run's leftovers are cleared at start, it shuts down after 20 idle minutes (and
   starts again, in about a second, on the next request) and after 400 requests (so it never slowly grows).
     eval   {view, expr}              -> {value} (tests)
   view: {route, key, w, h, scroll, scrollers: [{sel, top, left}], opt: "<set>:<choice>" | "none"} */
"use strict";
const { spawn } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path");

const [chrome, base] = process.argv.slice(2);
const IDLE_MS = +process.env.DV_MIRROR_IDLE_MS || 20 * 60 * 1000, RECYCLE = +process.env.DV_MIRROR_RECYCLE || 400;   // (shorter in tests)
// A run that died without cleaning up (the machine lost power, a kill -9) left its profile folder: remove those whose
// process is gone. Each folder carries its run's process id.
for (const name of (() => { try { return fs.readdirSync(os.tmpdir()); } catch (e) { return []; } })()) {
  if (!name.startsWith("dv-mirror-")) continue;
  const m = /^dv-mirror-(\d+)-/.exec(name);
  if (m) { try { process.kill(+m[1], 0); continue; } catch (e) { if (e.code === "EPERM") continue; } }   // alive (or not ours)
  else { try { if (Date.now() - fs.statSync(path.join(os.tmpdir(), name)).mtimeMs < 600000) continue; } catch (e) { continue; } }   // (an older run's, unlabelled)
  try { fs.rmSync(path.join(os.tmpdir(), name), { recursive: true, force: true }); } catch (e) {}
}
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dv-mirror-" + process.pid + "-"));
const cr = spawn(chrome, ["--headless", "--no-sandbox", "--disable-gpu", "--remote-debugging-pipe", "--user-data-dir=" + dir,
  "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--mute-audio",
  "--disable-background-networking", "--font-render-hinting=none", "about:blank"], { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] });
let leaving = false;
function bye() {
  if (leaving) return;
  leaving = true;
  let done = false;
  const finish = () => {                                 // once Chromium has stopped writing to its folder
    if (done) return;
    done = true;
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {}
    setTimeout(() => process.exit(0), 3000);             // the last answer goes out in full first (a picture is big)
    process.stdout.end(() => process.exit(0));
  };
  if (cr.exitCode !== null || cr.signalCode) finish();
  else { cr.once("exit", () => setTimeout(finish, 100)); setTimeout(finish, 2000); }
  try { cr.kill("SIGKILL"); } catch (e) {}
}
cr.on("exit", bye);
process.stdin.on("end", bye);
process.on("SIGTERM", bye);
process.on("SIGINT", bye);
process.on("SIGHUP", bye);
process.on("uncaughtException", bye);

// ---- the DevTools pipe: JSON messages, each ended by a NUL ----------------------------------------------------------
let seq = 0, buf = "", sid = null;
const waiting = new Map(), listeners = [];
cr.stdio[4].on("data", (d) => {
  buf += d.toString("utf8");
  let i;
  while ((i = buf.indexOf("\0")) >= 0) {
    const m = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
    if (m.id && waiting.has(m.id)) { const w = waiting.get(m.id); waiting.delete(m.id); m.error ? w.no(new Error(m.error.message)) : w.ok(m.result); }
    else if (m.method) listeners.slice().forEach((l) => l(m));
  }
});
function cdp(method, params, session) {
  const id = ++seq;
  const msg = { id, method, params: params || {} };
  if (session !== null) msg.sessionId = session === undefined ? sid : session;
  return new Promise((ok, no) => { waiting.set(id, { ok, no }); cr.stdio[3].write(JSON.stringify(msg) + "\0"); });
}
function once(method, ms) {
  return new Promise((ok) => {
    const l = (m) => { if (m.method === method && m.sessionId === sid) { done(); ok(true); } };
    const t = setTimeout(() => { done(); ok(false); }, ms);
    const done = () => { clearTimeout(t); const i = listeners.indexOf(l); if (i >= 0) listeners.splice(i, 1); };
    listeners.push(l);
  });
}
async function js(expr, arg) {
  const src = arg === undefined ? expr : "(" + expr + ")(" + JSON.stringify(arg) + ")";
  const r = await cdp("Runtime.evaluate", { expression: src, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
  return r.result.value;
}

// ---- the owner's state ------------------------------------------------------------------------------------------------
let cur = {};
async function start() {
  const { targetId } = await cdp("Target.createTarget", { url: "about:blank" }, null);
  sid = (await cdp("Target.attachToTarget", { targetId, flatten: true }, null)).sessionId;
  await cdp("Page.enable");
  await cdp("Runtime.enable");
}
// Quiet: the layer has loaded and applied its edits, the app has stopped redrawing for a moment, the pictures on screen
// have arrived and the fonts are in. At most 5 s: then it's as good as it gets.
const SETTLE = `new Promise(function (done) {
  var t0 = Date.now(), last = Date.now();
  var mo = new MutationObserver(function () { last = Date.now(); });
  mo.observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
  (function tick() {
    var shown = Array.prototype.every.call(document.images, function (i) {
      var r = i.getBoundingClientRect(); return i.complete || r.bottom < 0 || r.top > innerHeight || !r.width; });
    var ok = window.__dv && window.__dv.ready && window.__dv.ready() && shown && Date.now() - last > 250;
    if (ok || Date.now() - t0 > 5000) {
      mo.disconnect();
      document.fonts.ready.then(function () { requestAnimationFrame(function () { requestAnimationFrame(function () { done(ok); }); }); });
    } else setTimeout(tick, 50);
  })();
})`;
async function follow(v) {
  const w = Math.max(320, Math.round(v.w || 1440)), h = Math.max(240, Math.round(v.h || 900));
  if (cur.w !== w || cur.h !== h) {
    await cdp("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    cur.w = w; cur.h = h; cur.moved = true;
  }
  const route = v.route || "#/";
  // the key changes with every edit (and when the app's own files change): a fresh page then, like the owner's reload
  const doc = base + "/app/?dvopt=" + encodeURIComponent(v.opt || "none") + "&dvmirror=1" + (v.measure ? "&dvmeasure=1" : "")
    + "&k=" + encodeURIComponent(v.key || "");
  if (cur.doc !== doc) {
    const loaded = once("Page.loadEventFired", 10000);
    await cdp("Page.navigate", { url: doc + route });
    await loaded;
    cur.doc = doc; cur.route = route; cur.moved = true;
  } else if (cur.route !== route) {
    await js("function (r) { location.hash = r; }", route);
    cur.route = route; cur.moved = true;
  }
  if (cur.moved) { await js(SETTLE); cur.moved = false; }
  await js(`function (v) {
    scrollTo(0, v.scroll || 0);
    (v.scrollers || []).forEach(function (s) { try { var e = document.querySelector(s.sel); if (e) { e.scrollTop = s.top || 0; e.scrollLeft = s.left || 0; } } catch (x) {} });
    return new Promise(function (ok) { requestAnimationFrame(function () { requestAnimationFrame(ok); }); });
  }`, { scroll: v.scroll, scrollers: v.scrollers });
}

// ---- pictures ---------------------------------------------------------------------------------------------------------
// The owner's marks, outlined in magenta and lettered A, B, … on top of everything, for the moment of the picture.
const MARKS = `function (marks) {
  var q = function (s) { try { return s ? document.querySelector(s) : null; } catch (e) { return null; } };
  var top = document.createElement("div"), missing = [];
  top.id = "dv-mirror-marks";
  top.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647";
  marks.forEach(function (m, i) {
    var k = String.fromCharCode(65 + i), r = null;
    if (m.kind === "area" && m.rect) {
      var ax = m.rect.x + (m.sx || 0) - scrollX, ay = m.rect.y + (m.sy || 0) - scrollY;
      r = { left: ax, top: ay, right: ax + m.rect.w, bottom: ay + m.rect.h };
    }
    else {
      var els = [q(m.sel), q(m.from), q(m.to)].filter(function (e) { return e && e.getClientRects().length; });
      if (!els.length) { missing.push(k + " " + (m.sel || m.from || "")); return; }
      r = els.map(function (e) { return e.getBoundingClientRect(); }).reduce(function (a, b) {
        return { left: Math.min(a.left, b.left), top: Math.min(a.top, b.top), right: Math.max(a.right, b.right), bottom: Math.max(a.bottom, b.bottom) }; });
    }
    var b = document.createElement("div");
    b.style.cssText = "position:absolute;border:3px solid #ff00d4;left:" + (r.left - 3) + "px;top:" + (r.top - 3) + "px;width:" + (r.right - r.left) + "px;height:" + (r.bottom - r.top) + "px";
    var l = document.createElement("div");
    l.textContent = k;
    l.style.cssText = "position:absolute;background:#ff00d4;color:#fff;font:bold 15px sans-serif;padding:1px 6px;left:" + (r.left - 3) + "px;top:" + Math.max(0, r.top - 24) + "px";
    top.appendChild(b); top.appendChild(l);
  });
  document.documentElement.appendChild(top);
  return missing;
}`;
const UNMARK = `(function () { var e = document.getElementById("dv-mirror-marks"); if (e) e.remove(); })()`;
async function screenshot(clip) {
  const p = { format: "jpeg", quality: 85, captureBeyondViewport: false };
  if (clip) { p.clip = clip; p.format = "png"; }
  return "data:image/" + p.format + ";base64," + (await cdp("Page.captureScreenshot", p)).data;
}
// Two big things compared (a list and a sidebar): their top edges side by side, with what's above them, so a gap or a
// line-up is seen directly. -> {label, what, image} or null
async function edges(boxes, said) {
  const big = boxes.filter((b) => b.h > 150 && b.w > 120);
  if (big.length < 2) return null;
  const top = Math.min(...big.map((b) => b.y)), x = Math.max(0, Math.min(...big.map((b) => b.x)) - 12);
  const w = Math.min(cur.w, Math.max(...big.map((b) => b.x + b.w)) + 12) - x, y = Math.max(0, top - 50), h = Math.min(cur.h - y, 140);
  if (Math.max(...big.map((b) => b.y)) - top > 100 || w < 40) return null;    // not side by side
  const sxy = await js("[scrollX, scrollY]");
  return { label: big.map((b) => b.label).join(" and "), what: "their top edges side by side" + (said || "") + ", with what's above them",
           image: await screenshot({ x: x + sxy[0], y: y + sxy[1], width: w, height: h, scale: Math.max(1, Math.min(2, 1400 / w)) }) };
}
// Close-ups of boxes on screen ({label, what, x, y, w, h}): a little of what's around each, lossless, small things drawn
// up to 4 times their size, all at the SAME zoom so sizes compare. -> [{label, what, image}]
async function closeUps(boxes) {
  const crops = boxes.map((b) => {
    const pad = Math.max(16, Math.min(60, Math.round(Math.max(b.w, b.h) / 2)));
    const x = Math.max(0, b.x - pad), y = Math.max(0, b.y - pad);
    return { b, x, y, w: Math.min(cur.w, b.x + b.w + pad) - x, h: Math.min(cur.h, b.y + b.h + pad) - y };
  }).filter((c) => c.w >= 4 && c.h >= 4);           // (not on screen now)
  const scale = Math.max(1, Math.min(4, ...crops.map((c) => Math.min(1400 / c.w, 800 / c.h))));
  const sxy = await js("[scrollX, scrollY]"), out = [];
  for (const c of crops) {
    out.push({ label: c.b.label, what: c.b.what + (scale > 1 ? " (drawn " + Math.round(scale * 10) / 10 + "x)" : ""),
               image: await screenshot({ x: c.x + sxy[0], y: c.y + sxy[1], width: c.w, height: c.h, scale }) });
  }
  return out;
}
// Where each of the owner's marks is on screen: the element, an arrow's two ends together, or the area drawn.
const MARKED = `function (marks) {
  var q = function (s) { try { return s ? document.querySelector(s) : null; } catch (e) { return null; } }, out = [];
  marks.forEach(function (m, i) {
    var k = String.fromCharCode(65 + i), r = null;
    if (m.kind === "area" && m.rect) {
      var ax = m.rect.x + (m.sx || 0) - scrollX, ay = m.rect.y + (m.sy || 0) - scrollY;
      r = { left: ax, top: ay, right: ax + m.rect.w, bottom: ay + m.rect.h };
    }
    else {
      var els = [q(m.sel), q(m.from), q(m.to)].filter(function (e) { return e && e.getClientRects().length; });
      if (!els.length) return;
      r = els.map(function (e) { return e.getBoundingClientRect(); }).reduce(function (a, b) {
        return { left: Math.min(a.left, b.left), top: Math.min(a.top, b.top), right: Math.max(a.right, b.right), bottom: Math.max(a.bottom, b.bottom) }; });
    }
    var x = Math.max(0, r.left), y = Math.max(0, r.top), w = Math.min(innerWidth, r.right) - x, h = Math.min(innerHeight, r.bottom) - y;
    if (w > 0 && h > 0) out.push({ label: k, what: m.kind === "area" ? "the area drawn" : m.kind === "arrow" ? "the arrow's two ends" : m.sel,
                                   x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h), el: m.kind !== "area" });
  });
  // Two marked things side by side or one above the other: where they meet is a spot of its own (what's "between" them)
  var els = out.filter(function (b) { return b.el; }), meet = [];
  els.forEach(function (a, i) {
    els.slice(i + 1).forEach(function (b) {
      var L = a.x <= b.x ? a : b, R = L === a ? b : a, T = a.y <= b.y ? a : b, B = T === a ? b : a;
      var gx = R.x - (L.x + L.w), oy0 = Math.max(a.y, b.y), oy1 = Math.min(a.y + a.h, b.y + b.h);
      var gy = B.y - (T.y + T.h), ox0 = Math.max(a.x, b.x), ox1 = Math.min(a.x + a.w, b.x + b.w);
      if (gx > -6 && gx < 80 && oy1 - oy0 > 6)
        meet.push({ label: L.label + "|" + R.label, what: "where " + L.label + " (left) and " + R.label + " (right) meet", x: L.x + L.w - 28, y: oy0, w: Math.max(0, gx) + 56, h: oy1 - oy0 });
      else if (gy > -6 && gy < 80 && ox1 - ox0 > 6)
        meet.push({ label: T.label + "|" + B.label, what: "where " + T.label + " (above) and " + B.label + " (below) meet", x: ox0, y: T.y + T.h - 28, w: ox1 - ox0, h: Math.max(0, gy) + 56 });
    });
  });
  return meet.concat(out).map(function (b) {
    b.drawn = window.__dv && __dv.drawn ? __dv.drawn(b) : "";
    delete b.el;
    return b;
  });
}`;
async function shot(r) {
  await follow(r.view || {});
  const out = { missing: [] };
  if (r.whole !== false) {
    out.missing = await js(MARKS, r.marks || []);
    try { out.image = await screenshot(); } finally { await js(UNMARK); }
  }
  if (r.zoom) {              // a close-up of each spot the owner pointed at (a mark, the area they drawn, where two marks
    // meet), clean so fine detail shows, with what's drawn there as text; small spots at their own zoom, big ones together
    const spots = (await js(MARKED, r.marks || [])) || [];
    const small = spots.filter((b) => b.w * b.h < 160 * 120), big = spots.filter((b) => b.w * b.h >= 160 * 120);
    out.zoom = (await closeUps(small)).concat(await closeUps(big)).map((z) => {
      const b = spots.find((x) => x.label === z.label);
      return Object.assign(z, { drawn: b ? b.drawn : "" });
    });
  }
  if (r.close) {             // a close-up of each element the change is about, sharp, as on screen
    const boxes = (await js("function (s) { return window.__dv && __dv.rects ? __dv.rects(s) : []; }", r.close)) || [];
    out.close = await closeUps(boxes);
    const band = await edges(boxes);
    if (band) out.close.push(band);
  }
  if (r.scrolled) {          // what it looks like while scrolling: the page down, and the element's own list down
    out.scrolled = [];
    const how = (await js("function (s) { return window.__dv && __dv.scrolling ? __dv.scrolling(s) : {}; }", r.scrolled)) || {};
    if (how.page) {
      await js("function (y) { scrollTo(0, y); return new Promise(function (ok) { requestAnimationFrame(function () { requestAnimationFrame(ok); }); }); }", how.page);
      out.scrolled.push({ label: "the whole screen with the page scrolled down " + how.page + " px", image: await screenshot() });
    }
    if (how.box) {
      await js(`function (b) { scrollTo(0, 0); var e = document.querySelector(b.sel); if (e) e.scrollTop += b.by;
        return new Promise(function (ok) { requestAnimationFrame(function () { requestAnimationFrame(ok); }); }); }`, how.box);
      const said = " while " + how.box.what + " is scrolled down " + how.box.by + " px";
      out.scrolled.push({ label: "the whole screen" + said, image: await screenshot() });
      const band = await edges((await js("function (s) { return window.__dv && __dv.rects ? __dv.rects(s) : []; }", r.scrolled)) || [], said);
      if (band) out.scrolled.push({ label: "close-up of " + band.label + ": " + band.what, image: band.image });
    }
    await follow(Object.assign({}, r.view, {})); // back to the owner's state
  }
  return out;
}

// A choice of an option set, judged by the layer as the owner's page would: loaded with its edits, each edit measured,
// and the verdicts reported to design-view.py. Done when no edit is still unjudged and the report has gone (at most 6 s).
async function measure(v) {
  await follow(Object.assign({}, v, { measure: true }));
  const left = await js(`new Promise(function (done) {
    var t0 = Date.now();
    (function tick() {
      var r = window.__dv && __dv.report ? __dv.report() : [], open = r.filter(function (o) { return o.status === "not run"; }).length;
      if ((r.length && !open) || Date.now() - t0 > 6000) setTimeout(function () { done(open); }, 600);   // (the report goes after 250 ms)
      else setTimeout(tick, 100);
    })();
  })`);
  return { unjudged: left };
}

// ---- requests from design-view.py, one at a time ----------------------------------------------------------------------
const queue = [];
let busy = false, started = null, served = 0, idle = null;
function reply(o) { process.stdout.write(JSON.stringify(o) + "\n"); }
async function pump() {
  if (busy) return;
  busy = true;
  while (queue.length) {
    const r = queue.shift();
    if (r.cmd === "follow" && queue.length) continue;    // something newer is waiting: no need
    const t0 = Date.now();
    try {
      await (started = started || start());
      const out = r.cmd === "shot" ? await shot(r)
        : r.cmd === "inspect" ? (await follow(r.view || {}), { value: await js("function (s) { return window.__dv && __dv.inspect ? __dv.inspect(s) : null; }", r.spec || {}) })
        : r.cmd === "eval" ? (await follow(r.view || {}), { value: await js(r.expr) })   // for tests: read something off the page
        : r.cmd === "measure" ? await measure(r.view || {})
        : (await follow(r.view || {}), {});
      reply(Object.assign({ id: r.id, ms: Date.now() - t0 }, out));
    } catch (e) {
      cur = {};                                          // start the next one from a fresh page
      reply({ id: r.id, error: String(e && e.message || e).slice(0, 300) });
    }
    served++;
  }
  busy = false;
  if (served >= RECYCLE) bye();                          // a fresh start now and then: it never slowly grows
  clearTimeout(idle);
  idle = setTimeout(bye, IDLE_MS);                       // nothing to do for a while: free the memory until needed
}
idle = setTimeout(bye, IDLE_MS);
let line = "";
process.stdin.on("data", (d) => {
  line += d.toString("utf8");
  let i;
  while ((i = line.indexOf("\n")) >= 0) {
    const s = line.slice(0, i); line = line.slice(i + 1);
    if (s.trim()) { try { queue.push(JSON.parse(s)); } catch (e) {} }
  }
  pump();
});
