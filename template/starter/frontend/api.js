/* The only door to the back end: JSON over /api/. In the mockup the same calls get mock data. */
window.api = {
  get: function (path) { return fetch("/api/" + path, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }); },
  send: function (path, body, method) {
    return fetch("/api/" + path, { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.ok ? r.json() : null; });
  }
};
