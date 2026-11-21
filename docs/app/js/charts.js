// Hand-built SVG charts (no chart library): each one shows exactly one idea from the dossier.
import { esc, fmt } from "./core.js";

const gauss = (x, m, s) => Math.exp(-0.5 * ((x - m) / s) ** 2) / (s * Math.sqrt(2 * Math.PI));

function ticks(lo, hi, n = 5) {
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= step0) || step0;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-12; v += step) out.push(+v.toPrecision(10));
  return out;
}

/** Prior, evidence and posterior as probability curves (dossier Figure 16). */
export function beliefChart({ prior, evidence, posterior, evidenceStatus = "WARN" }, opts = {}) {
  const W = 640, H = 210, L = 14, R = 14, T = 12, B = 30;
  const items = [prior, evidence, posterior].filter(Boolean);
  const lo = Math.min(...items.map((d) => d.mean - 3.4 * d.sd));
  const hi = Math.max(...items.map((d) => d.mean + 3.4 * d.sd));
  const peak = Math.max(...items.map((d) => gauss(d.mean, d.mean, d.sd)));
  const X = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const Y = (p) => H - B - (p / peak) * (H - T - B);
  const path = (d, close = false) => {
    let s = "";
    for (let i = 0; i <= 160; i++) {
      const v = lo + (i / 160) * (hi - lo);
      s += `${i ? "L" : "M"}${X(v).toFixed(1)},${Y(gauss(v, d.mean, d.sd)).toFixed(1)}`;
    }
    return close ? `${s}L${X(hi)},${Y(0)}L${X(lo)},${Y(0)}Z` : s;
  };
  const tk = ticks(lo, hi, 6);
  const digits = opts.digits ?? 2;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria || "Prior, evidence and posterior belief")}">
    ${tk.map((v) => `<line class="grid" x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${H - B}"/><text x="${X(v)}" y="${H - 10}" text-anchor="middle">${fmt(v, digits)}</text>`).join("")}
    <line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
    ${prior ? `<path class="prior" d="${path(prior)}" style="animation:enter .5s both"/>` : ""}
    ${evidence ? `<path class="evidence ${esc(evidenceStatus)} draw" pathLength="1" style="--len:1;animation-delay:.15s" d="${path(evidence)}"/>` : ""}
    ${posterior ? `<path class="posterior" d="${path(posterior, true)}" style="animation:enter .6s .35s both"/>
      <line x1="${X(posterior.mean)}" x2="${X(posterior.mean)}" y1="${Y(gauss(posterior.mean, posterior.mean, posterior.sd))}" y2="${H - B}" stroke="var(--accent)" stroke-width="1" stroke-dasharray="2 3"/>` : ""}
  </svg>`;
}

/** Baseline vs follow-up spectra, ppm decreasing to the right (NMR convention). */
export function spectrumChart(s0, s1) {
  const W = 760, H = 280, L = 10, R = 10, T = 26, B = 30;
  const lo = 0.5, hi = 4.3;
  const all = [...s0.real, ...s1.real];
  const ymin = Math.min(...all), ymax = Math.max(...all);
  const X = (p) => L + ((hi - p) / (hi - lo)) * (W - L - R);
  const Y = (v) => H - B - ((v - ymin) / (ymax - ymin)) * (H - T - B);
  const line = (s) => s.ppm.map((p, i) => `${i ? "L" : "M"}${X(p).toFixed(1)},${Y(s.real[i]).toFixed(1)}`).join("");
  const tk = [4, 3.5, 3, 2.5, 2, 1.5, 1];
  const peaks = s0.peaks.filter((p) => p.ppm >= lo && p.ppm <= hi && p.name !== "Cr CH2");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="1H spectra at baseline and follow-up">
    ${tk.map((p) => `<line class="grid" x1="${X(p)}" x2="${X(p)}" y1="${T}" y2="${H - B}"/><text x="${X(p)}" y="${H - 10}" text-anchor="middle">${p.toFixed(1)}</text>`).join("")}
    <text x="${W - R}" y="${H - 10}" text-anchor="end" class="label-strong">ppm</text>
    ${peaks.map((p) => `<text x="${X(p.ppm)}" y="${T - 10}" text-anchor="middle" class="label-strong">${esc(p.name)}</text>`).join("")}
    <path class="t0" d="${line(s0)}"/>
    <path class="t1 draw" pathLength="1" style="--len:1" d="${line(s1)}"/>
  </svg>`;
}

/** Belief over time: observations with error bars, the twin's belief band, and the predicted repeat range. */
export function trajectoryChart(events, name, prediction, opts = {}) {
  const evs = events.filter((e) => e.observable === name && e.type !== "reject" && e.evidence);
  if (!evs.length) return "";
  const W = 640, H = 230, L = 46, R = 70, T = 14, B = 30;
  const obs = evs.map((e) => ({ t: e.time_month ?? 0, y: e.evidence.y, u: e.evidence.u_effective, st: e.qc_status }));
  const belief = evs.map((e) => ({ t: e.time_month ?? 0, m: e.posterior.mean, s: Math.sqrt(e.posterior.var) }));
  const tmax = Math.max(...obs.map((o) => o.t)) + 1.5;
  const ys = [...obs.flatMap((o) => [o.y - 2 * o.u, o.y + 2 * o.u]), ...belief.flatMap((b) => [b.m - 2 * b.s, b.m + 2 * b.s])];
  if (prediction) ys.push(prediction.low, prediction.high);
  const ylo = Math.min(...ys), yhi = Math.max(...ys);
  const X = (t) => L + (t / tmax) * (W - L - R);
  const Y = (v) => H - B - ((v - ylo) / (yhi - ylo)) * (H - T - B);
  let band = "";
  for (let i = 0; i < belief.length; i++) {
    const b = belief[i], t1 = i + 1 < belief.length ? belief[i + 1].t : tmax - 0.6;
    band += `<rect class="band" x="${X(b.t)}" y="${Y(b.m + 1.96 * b.s)}" width="${Math.max(X(t1) - X(b.t), 2)}" height="${Y(b.m - 1.96 * b.s) - Y(b.m + 1.96 * b.s)}"/>
      <line x1="${X(b.t)}" x2="${X(t1)}" y1="${Y(b.m)}" y2="${Y(b.m)}" stroke="var(--accent)" stroke-width="2"/>`;
  }
  const col = (st) => (st === "PASS" ? "var(--pass)" : st === "WARN" ? "var(--warn)" : "var(--fail)");
  const tk = ticks(ylo, yhi, 4);
  const pt = prediction ? tmax - 0.6 : null;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.aria || "Belief over time")}">
    ${tk.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, opts.digits ?? 2)}</text>`).join("")}
    ${[0, 6, 12].filter((t) => t <= tmax).map((t) => `<text x="${X(t)}" y="${H - 10}" text-anchor="middle">month ${t}</text>`).join("")}
    ${band}
    ${obs.map((o) => `<line x1="${X(o.t)}" x2="${X(o.t)}" y1="${Y(o.y - 1.96 * o.u)}" y2="${Y(o.y + 1.96 * o.u)}" stroke="${col(o.st)}" stroke-width="1.5"/>
      <circle cx="${X(o.t)}" cy="${Y(o.y)}" r="4.5" fill="var(--bg-2)" stroke="${col(o.st)}" stroke-width="2"/>`).join("")}
    ${prediction ? `<line x1="${X(pt)}" x2="${X(pt)}" y1="${Y(prediction.low)}" y2="${Y(prediction.high)}" stroke="var(--accent)" stroke-width="6" stroke-linecap="round" opacity=".35"/>
      <text x="${X(pt) + 10}" y="${Y(prediction.high) + 4}">${fmt(prediction.high, 2)}</text>
      <text x="${X(pt) + 10}" y="${Y(prediction.low) + 4}">${fmt(prediction.low, 2)}</text>
      <text x="${X(pt)}" y="${T + 2}" text-anchor="middle" class="label-strong">expected repeat</text>` : ""}
  </svg>`;
}

/** Provenance DAG: source files → processing → packet → twin event → twin variable. */
export function provenanceGraph(trace) {
  const colOf = (n) => n.kind === "file" ? 0 : n.id.startsWith("proc:") ? 1 : n.kind === "entity" ? 2 : n.id.startsWith("ev:") ? 3 : 4;
  const titles = ["Source file", "Processing", "Evidence packet", "Twin event", "Twin variable"];
  const cols = [[], [], [], [], []];
  trace.nodes.forEach((n) => cols[colOf(n)].push(n));
  const NW = 178, NH = 46, GX = 34, GY = 16, TOP = 26;
  const H = TOP + Math.max(...cols.map((c) => c.length), 1) * (NH + GY) + 10;
  const W = 5 * NW + 4 * GX;
  const pos = {};
  cols.forEach((c, ci) => {
    const off = (H - TOP - c.length * (NH + GY)) / 2;
    c.forEach((n, ri) => { pos[n.id] = { x: ci * (NW + GX), y: TOP + off + ri * (NH + GY) }; });
  });
  const cut = (s, k) => (s.length > k ? s.slice(0, k - 1) + "…" : s);
  const edges = trace.edges.filter((e) => pos[e.from] && pos[e.to]).map((e) => {
    const a = pos[e.from], b = pos[e.to];
    const x1 = a.x + NW, y1 = a.y + NH / 2, x2 = b.x, y2 = b.y + NH / 2, mx = (x1 + x2) / 2;
    return `<path class="edge ${e.label === "rejected" ? "rej" : ""}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
  }).join("");
  const nodes = trace.nodes.map((n) => {
    const p = pos[n.id];
    const sub = n.kind === "file" ? (n.verified ? "SHA-256 verified" : n.verified === false ? "hash MISMATCH" : "not in manifest") : cut(n.detail || "", 30);
    return `<g class="node ${esc(n.kind)} ${n.verified ? "ok" : ""}" data-id="${esc(n.id)}" tabindex="0" role="button" transform="translate(${p.x},${p.y})" style="cursor:pointer">
      <rect width="${NW}" height="${NH}"/>
      <text x="12" y="19">${esc(cut(n.label, 22))}</text>
      <text class="sub" x="12" y="35">${esc(cut(sub, 25))}</text></g>`;
  }).join("");
  return `<svg class="prov" viewBox="0 0 ${W} ${H}" style="width:100%;min-width:860px;height:auto" role="img" aria-label="Provenance graph">
    ${titles.map((t, i) => `<text class="col-title" x="${i * (NW + GX)}" y="12">${t}</text>`).join("")}
    ${edges}${nodes}</svg>`;
}
