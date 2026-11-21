// Larmor, read-only online copy.
// The app normally asks a Python engine for its numbers through /api/... . This page has no engine, so this script
// answers the same calls from files that the real engine wrote beforehand (snapshot/, made by tools/build_static.py).
// Nothing here computes a result. What only the engine can do is refused with a plain message.
(function () {
  "use strict";

  var script = document.currentScript;
  var BASE = new URL("snapshot/", script && script.src ? script.src : location.href).href;
  var realFetch = window.fetch.bind(window);

  var READ_ONLY = "This online copy is read-only. It can show the stored packets. Run Larmor on your own computer to check your own packet.";
  var NO_APPLY = "This online copy is read-only, so a packet cannot be applied here. Use Next packet on the Twin state page to watch the twin update.";
  var NO_BENCH = "This online copy shows the stored bench run (seed 2026, 250 cases). Run Larmor on your own computer for a new run.";
  var NO_SESSION = "This online copy is read-only, so a session cannot be registered here.";
  var NO_FELIX = "Felix runs on a local model, so it is not part of this online copy.";

  // The twin this page shows: a step of the golden path (s0 empty ... s6 all six packets),
  // or the full update replayed with another WARN factor (p1.0 ... p4.0).
  var current = "s6";
  var cache = {};

  function load(name) {
    if (!cache[name]) {
      cache[name] = realFetch(BASE + name).then(function (r) {
        if (!r.ok) throw new Error("stored answer missing: " + name);
        return r.json();
      });
      cache[name].catch(function () { delete cache[name]; });
    }
    return cache[name];
  }

  function reply(body, status) {
    return new Response(JSON.stringify(body), { status: status || 200, headers: { "content-type": "application/json" } });
  }
  function refuse(message, status) { return reply({ detail: message }, status || 409); }

  function stateFile(key) { return load("state/" + key + ".json"); }
  function checksKey() { return current.charAt(0) === "p" ? "s6" : current; }   // the WARN factor does not change a check

  // Two packets are the same when they parse to the same JSON; text that does not parse is compared as text.
  function canonical(text) {
    try { return "j:" + JSON.stringify(JSON.parse(text)); } catch (e) { return "t:" + String(text).trim(); }
  }
  function libraryId(text) {
    return load("packets.json").then(function (packets) {
      var want = canonical(text);
      for (var id in packets) if (canonical(packets[id]) === want) return id;
      return null;
    });
  }

  function exportOf(state) {
    var out = {};
    for (var k in state) if (["predictions", "next", "explanations", "models"].indexOf(k) < 0) out[k] = state[k];
    return out;
  }

  function get(path) {
    if (path === "/api/state") return stateFile(current).then(function (f) { return reply(f.state); });
    if (path === "/api/version") return stateFile(current).then(function (f) { return reply({ version: f.state.version, events: f.state.events.length }); });
    if (path === "/api/export") return stateFile(current).then(function (f) { return reply(exportOf(f.state)); });
    if (path === "/api/scene") return load("scene.json").then(function (d) { return reply(d); });
    if (path === "/api/bench") return load("bench.json").then(function (d) { return reply(d); });
    if (path === "/api/assistant/sources") return reply([]);
    var m = path.match(/^\/api\/provenance\/(.+)$/);
    if (m) {
      return stateFile(current).then(function (f) {
        var p = f.provenance[decodeURIComponent(m[1])];
        return p ? reply(p.body, p.status) : refuse("unknown variable", 404);
      });
    }
    m = path.match(/^\/api\/packet\/(.+)$/);
    if (m) {
      var id = decodeURIComponent(m[1]);
      return load("packets.json").then(function (packets) {
        return id in packets ? reply({ id: id, text: packets[id] }) : refuse("unknown packet " + id, 404);
      });
    }
    return load("fixed.json").then(function (fixed) {
      return path in fixed ? reply(fixed[path]) : refuse("not part of the online copy: " + path, 404);
    });
  }

  function post(path, body) {
    if (path === "/api/reset") {
      current = body.mode === "empty" ? "s0" : body.mode === "baseline" ? "s3" : "s6";
      return stateFile(current).then(function (f) { return reply(f.state); });
    }
    if (path === "/api/step") {
      var k = current.charAt(0) === "s" ? Number(current.slice(1)) : 6;
      if (k >= 6) return stateFile(current).then(function (f) { return reply({ result: null, state: f.state }); });
      current = "s" + (k + 1);
      return Promise.all([load("steps.json"), stateFile(current)]).then(function (r) {
        return reply({ result: r[0][String(k + 1)], state: r[1].state });
      });
    }
    if (path === "/api/policy") {
      var f = Number(body.warn_factor);
      if (!(f >= 1 && f <= 10)) return refuse("WARN factor must be between 1 and 10", 400);
      return load("index.json").then(function (ix) {
        var key = f.toFixed(1);
        if (ix.policy_factors.indexOf(key) < 0) return refuse("This online copy stores the WARN factors " + ix.policy_factors.join(", ") + ".");
        current = "p" + key;
        return stateFile(current).then(function (file) { return reply(file.state); });
      });
    }
    if (path === "/api/check") {
      if (body.apply) return refuse(NO_APPLY);
      return libraryId(body.text || "").then(function (id) {
        if (!id) return refuse(READ_ONLY);
        return Promise.all([load("checks/" + checksKey() + ".json"), stateFile(current)]).then(function (r) {
          return reply({ result: r[0][id], state: r[1].state });
        });
      });
    }
    if (path === "/api/tests") {
      return load("tests.json").then(function (d) { return reply(d); }, function () { return refuse("No stored test run in this copy."); });
    }
    if (path === "/api/bench/run") return refuse(NO_BENCH);
    if (path === "/api/session") return refuse(NO_SESSION);
    if (path === "/api/assistant/warm" || path === "/api/assistant/prime") return load("fixed.json").then(function (fixed) { return reply(fixed["/api/assistant/status"]); });
    if (path.indexOf("/api/assistant/") === 0) return refuse(NO_FELIX);
    return refuse("not part of the online copy: " + path, 404);
  }

  function apiPath(input) {
    var url = typeof input === "string" ? input : input && input.url;
    if (!url) return null;
    var p = new URL(url, location.href).pathname;
    var i = p.indexOf("/api/");
    return i >= 0 && (i === 0 || p.slice(0, i + 1) === new URL(".", location.href).pathname) ? p.slice(i) : null;
  }

  window.fetch = function (input, init) {
    var path = apiPath(input);
    if (!path) return realFetch(input, init);
    var method = ((init && init.method) || (typeof input !== "string" && input.method) || "GET").toUpperCase();
    try {
      if (method === "GET") return Promise.resolve(get(path));
      var body = {};
      try { body = init && init.body ? JSON.parse(init.body) : {}; } catch (e) { body = {}; }
      return Promise.resolve(post(path, body || {}));
    } catch (err) {
      return Promise.resolve(refuse(String(err && err.message || err), 500));
    }
  };

  // Download links that point at the engine: hand over the stored file instead.
  function save(name, blob) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href^="/api/"]') : null;
    if (!a) return;
    e.preventDefault();
    var path = a.getAttribute("href");
    var name = a.getAttribute("download") || "";
    if (path === "/api/export") {
      stateFile(current).then(function (f) {
        save(name || "twin_audit_trail.json", new Blob([JSON.stringify(exportOf(f.state), null, 2)], { type: "application/json" }));
      });
      return;
    }
    var file = path === "/api/bench/packets" ? "bench_packets.json" : path === "/api/bench/truth" ? "bench_truth.json"
      : path.indexOf("/api/about/files/") === 0 ? decodeURIComponent(path.slice("/api/about/files/".length)) : null;
    if (!file) return;
    realFetch(BASE + "files/" + encodeURIComponent(file)).then(function (r) {
      if (!r.ok) throw new Error("missing");
      return r.blob();
    }).then(function (blob) { save(name || file, blob); }).catch(function () { /* the file is not part of this copy */ });
  }, true);

  // Felix needs a local model: no button in this copy.
  var style = document.createElement("style");
  style.textContent = ".as-root{display:none !important}";
  document.head.appendChild(style);
})();
