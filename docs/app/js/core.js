// Shared helpers: API calls, app store, formatting, small HTML builders.

async function handle(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); msg = j.detail || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  get: (path) => fetch(path).then(handle),
  post: (path, body) => fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) }).then(handle),
};

export const store = {
  meta: null,
  state: null,
  lastEventId: 0,
  async load() {
    [this.meta, this.state] = await Promise.all([api.get("/api/meta"), api.get("/api/state")]);
    return this;
  },
  setState(s) { this.state = s; },
};

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

export function fmt(x, digits = 3) {
  if (x === null || x === undefined || Number.isNaN(x)) return "n/a";
  const a = Math.abs(x);
  if (a >= 1000) return Math.round(x).toLocaleString("en-US");
  if (a !== 0 && a < 0.001) return x.toExponential(2);
  return Number(x).toFixed(digits);
}
export const pct = (x, d = 0) => (x === null || x === undefined ? "n/a" : `${(x * 100).toFixed(d)} %`);

export const STATUS_ICON = { PASS: "ph-check-circle", INFO: "ph-info", WARN: "ph-warning", FAIL: "ph-x-circle" };
export const ACTION_TEXT = { update: "Update", update_with_warning: "Update with warning", reject: "Reject", initialize: "Initialize" };
export const ACTION_ICON = { update: "ph-check-circle", update_with_warning: "ph-warning", reject: "ph-x-circle", initialize: "ph-flag" };

export function chip(status, text) {
  const icon = STATUS_ICON[status] || ACTION_ICON[status] || "ph-circle";
  return `<span class="chip ${esc(status)}"><i class="ph-fill ${icon}"></i>${esc(text ?? status)}</span>`;
}
export const actionChip = (a) => chip(a, ACTION_TEXT[a] || a);
export const ownerChip = (o) => `<span class="chip owner" title="${esc(store.meta?.owners?.[o] || o)}">${esc(o)}</span>`;

export function label(name) {
  return store.state?.models?.[name]?.label || name;
}
export function unit(name) {
  const u = store.state?.models?.[name]?.unit;
  return u === "1" ? "" : u === "mm3" ? "mm³" : u || "";
}

let toastTimer;
export function toast(msg, isErr = false) {
  document.querySelector(".toast")?.remove();
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.setAttribute("role", "status");
  t.textContent = msg;
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 4200);
}

export function lastUpdate(name) {
  const evs = store.state?.events || [];
  return [...evs].reverse().find((e) => e.observable === name && e.type !== "reject" && e.type !== "initialize") || null;
}
