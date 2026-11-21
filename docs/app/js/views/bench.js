// View: the Monte-Carlo test bench. Simulated follow-ups with KNOWN truth, graded through the real checker and twin.
import { api, esc, fmt, pct, toast } from "../core.js";

const view = { data: null, mode: "budget", running: false, error: null };

const MODES = {
  budget: { label: "Fit error + voxel placement", note: "The packet's SD is the fit's Cramér-Rao bound combined with a voxel-placement term. Lineshape and drift error are left out on purpose: covering them is the job the WARN factor claims to do." },
  crlb: { label: "Fit error only (CRLB)", note: "The packet's SD is the fit's Cramér-Rao bound alone, as many pipelines report it. Nothing else is in the error bar." },
};

const GROUPS = [
  ["PASS", "PASS"],
  ["WARN_spectral", "WARN: broad line or low SNR"],
  ["WARN_registration", "WARN: voxel misplaced"],
  ["WARN_field", "WARN: 3 T to 1.5 T, harmonized"],
  ["WARN_echo_time", "WARN: echo time 30 to 144 ms"],
];

const x2 = (v) => (v === null || v === undefined ? "n/a" : `×${fmt(v, 2)}`);

function ticks(lo, hi, n = 5) {
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= step0) || step0;
  const out = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(+v.toPrecision(10));
  return out;
}

// ---------------------------------------------------------------- charts

/** Coverage of the packet interval y ± 1.96·sqrt(f)·u around the truth, as the inflation factor f grows. */
function factorChart(curve, declared, fitted) {
  const W = 620, H = 270, L = 46, R = 18, T = 16, B = 38;
  const fs = curve.factors, fmax = fs[fs.length - 1];
  const shown = ["PASS", "WARN_spectral", "WARN_all"].flatMap((k) => (curve[k] || []).slice(0, 5)).filter((v) => v !== null);
  const ylo = Math.min(0.85, Math.floor(Math.min(...shown, 0.9) * 20) / 20), yhi = 1.0;
  const X = (f) => L + ((f - 1) / (fmax - 1)) * (W - L - R);
  const Y = (c) => H - B - ((Math.max(c, ylo) - ylo) / (yhi - ylo)) * (H - T - B);
  const line = (vals) => vals.map((v, i) => (v === null ? "" : `${i && vals[i - 1] !== null ? "L" : "M"}${X(fs[i]).toFixed(1)},${Y(v).toFixed(1)}`)).join("");
  const series = [
    ["PASS", "bench-l-pass", "PASS"],
    ["WARN_spectral", "bench-l-warn", "WARN, broad line or low SNR"],
    ["WARN_all", "bench-l-warn dash", "All WARN, incl. protocol changes"],
  ].filter(([k]) => curve[k] && curve[k].some((v) => v !== null));
  return `<svg class="chart bench-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Coverage of packet intervals versus the inflation factor">
    ${ticks(ylo, yhi, 5).map((c) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(c)}" y2="${Y(c)}"/><text x="${L - 8}" y="${Y(c) + 4}" text-anchor="end">${Math.round(c * 100)}%</text>`).join("")}
    ${[1, 2, 3, 4, 5, 6, 7, 8].filter((f) => f <= fmax).map((f) => `<text x="${X(f)}" y="${H - B + 16}" text-anchor="middle">×${f}</text>`).join("")}
    <text x="${W - R}" y="${H - 4}" text-anchor="end" class="label-strong">variance factor f</text>
    <line class="bench-target" x1="${L}" x2="${W - R}" y1="${Y(0.95)}" y2="${Y(0.95)}"/>
    <text x="${W - R}" y="${Y(0.95) - 6}" text-anchor="end" class="bench-target-t">target 95%</text>
    <line class="bench-mark" x1="${X(declared)}" x2="${X(declared)}" y1="${T}" y2="${H - B}"/>
    <text x="${X(declared) + (fitted && fitted > declared ? -6 : 6)}" y="${H - B - 8}" text-anchor="${fitted && fitted > declared ? "end" : "start"}" class="label-strong">declared ×${fmt(declared, 0)}</text>
    ${fitted ? `<line class="bench-mark fit" x1="${X(fitted)}" x2="${X(fitted)}" y1="${T}" y2="${H - B}"/>
      <text x="${X(fitted) + (fitted < declared ? -6 : 6)}" y="${H - B - 8}" text-anchor="${fitted < declared ? "end" : "start"}" class="bench-fit-t">data ×${fmt(fitted, 2)}</text>` : ""}
    ${series.map(([k, cls]) => `<path class="${cls} draw" pathLength="1" style="--len:1" d="${line(curve[k])}"/>`).join("")}
  </svg>
  <div class="legend">${series.map(([, cls, name]) => `<span><i class="sw ${cls}"></i>${esc(name)}</span>`).join("")}</div>`;
}

/** RMS of the reported CRLB, the real fit error and the total error, per linewidth bin. */
function crlbChart(rows) {
  const W = 620, H = 260, L = 50, R = 12, T = 14, B = 40;
  const keys = [["crlb_rms", "bench-b-crlb", "Cramér-Rao bound (reported)"], ["fit_err_rms", "bench-b-fit", "Real fit error"], ["total_err_rms", "bench-b-tot", "Total error vs truth"]];
  const ymax = Math.max(...rows.flatMap((r) => keys.map(([k]) => r[k]))) * 1.15;
  const Y = (v) => H - B - (v / ymax) * (H - T - B);
  const gw = (W - L - R) / rows.length, bw = Math.min(30, (gw - 26) / 3);
  const tk = ticks(0, ymax, 4);
  return `<svg class="chart bench-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cramér-Rao bound versus real error by linewidth">
    ${tk.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, 3)}</text>`).join("")}
    <line class="axis" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/>
    ${rows.map((r, i) => {
      const x0 = L + i * gw + (gw - 3 * bw - 8) / 2;
      return keys.map(([k, cls], j) => {
        const h = Y(0) - Y(r[k]);
        return `<rect class="${cls}" x="${x0 + j * (bw + 4)}" y="${Y(r[k])}" width="${bw}" height="${Math.max(h, 0)}" rx="3" style="--i:${i * 3 + j}"><title>${fmt(r[k], 4)}</title></rect>`;
      }).join("") + `<text x="${L + i * gw + gw / 2}" y="${H - B + 16}" text-anchor="middle">${r.lo}-${r.hi} Hz</text>
        <text x="${L + i * gw + gw / 2}" y="${H - B + 30}" text-anchor="middle" class="bench-n">n = ${r.n}</text>`;
    }).join("")}
  </svg>
  <div class="legend">${keys.map(([, cls, name]) => `<span><i class="sw block ${cls}"></i>${esc(name)}</span>`).join("")}</div>`;
}

/** Calibration curve of the twin's posterior: nominal interval level vs how often it held the truth. */
function calibrationChart(cov) {
  const W = 300, H = 260, L = 40, R = 12, T = 12, B = 36;
  const X = (v) => L + ((v - 0.4) / 0.6) * (W - L - R);
  const Y = (v) => H - B - ((Math.max(v, 0) - 0) / 1) * (H - T - B);
  const line = (vals) => vals.map((v, i) => (v === null ? "" : `${i ? "L" : "M"}${X(cov.levels[i]).toFixed(1)},${Y(v).toFixed(1)}`)).join("");
  const dots = (vals, cls) => vals.map((v, i) => (v === null ? "" : `<circle class="${cls}" cx="${X(cov.levels[i])}" cy="${Y(v)}" r="3.2"/>`)).join("");
  return `<svg class="chart bench-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Calibration of the twin's posterior intervals">
    ${[0, 0.25, 0.5, 0.75, 1].map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v * 100)}</text>`).join("")}
    ${[0.5, 0.68, 0.8, 0.95].map((v) => `<text x="${X(v)}" y="${H - B + 15}" text-anchor="middle">${Math.round(v * 100)}</text>`).join("")}
    <text x="${W - R}" y="${H - 4}" text-anchor="end" class="label-strong">stated level, %</text>
    <line class="bench-diag" x1="${X(0.4)}" y1="${Y(0.4)}" x2="${X(1)}" y2="${Y(1)}"/>
    <path class="bench-l-acc" d="${line(cov.nochange)}"/>${dots(cov.nochange, "bench-d-acc")}
    <path class="bench-l-mute" d="${line(cov.all)}"/>${dots(cov.all, "bench-d-mute")}
  </svg>
  <div class="legend"><span><i class="sw bench-l-acc"></i>No true change</span><span><i class="sw bench-l-mute"></i>All accepted cases</span><span><i class="sw dash bench-diag"></i>Perfect calibration</span></div>`;
}

/** Twin 95 % coverage and d² flag rate for each true change. */
function changeBars(rows) {
  const W = 300, H = 260, L = 40, R = 12, T = 12, B = 36;
  const gw = (W - L - R) / rows.length, bw = Math.min(22, gw / 3);
  const Y = (v) => H - B - (v ?? 0) * (H - T - B);
  return `<svg class="chart bench-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Twin coverage and surprise flags by true change">
    ${[0, 0.25, 0.5, 0.75, 1].map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v * 100)}</text>`).join("")}
    <line class="bench-target" x1="${L}" x2="${W - R}" y1="${Y(0.95)}" y2="${Y(0.95)}"/>
    ${rows.map((r, i) => {
      const x = L + i * gw + gw / 2;
      return `<rect class="bench-b-fit" x="${x - bw - 2}" y="${Y(r.coverage95)}" width="${bw}" height="${Y(0) - Y(r.coverage95)}" rx="3" style="--i:${i * 2}"><title>coverage ${pct(r.coverage95)}</title></rect>
        <rect class="bench-b-flag" x="${x + 2}" y="${Y(r.d2_flag_rate)}" width="${bw}" height="${Y(0) - Y(r.d2_flag_rate)}" rx="3" style="--i:${i * 2 + 1}"><title>flagged ${pct(r.d2_flag_rate)}</title></rect>
        <text x="${x}" y="${H - B + 15}" text-anchor="middle">${r.true_change ? `+${fmt(r.true_change, 2)}` : "none"}</text>`;
    }).join("")}
    <text x="${W - R}" y="${H - 4}" text-anchor="end" class="label-strong">true change</text>
  </svg>
  <div class="legend"><span><i class="sw block bench-b-fit"></i>95% interval holds the truth</span><span><i class="sw block bench-b-flag"></i>Surprise gate d² raised</span></div>`;
}

/** One simulated follow-up: data, Lorentzian fit, the Cho and Cr components, and the residual. */
function spectrumChart(ex) {
  const W = 760, H = 300, L = 12, R = 12, T = 26, B = 30;
  const lo = Math.min(...ex.ppm), hi = Math.max(...ex.ppm);
  const top = Math.max(...ex.data, ...ex.fit), bot = Math.min(...ex.data);
  const span = top - bot;
  const resOff = bot - 0.3 * span;
  const ymin = resOff - 0.16 * span, ymax = top + 0.04 * span;
  const X = (p) => L + ((hi - p) / (hi - lo)) * (W - L - R);
  const Y = (v) => H - B - ((v - ymin) / (ymax - ymin)) * (H - T - B);
  const path = (arr, off = 0) => ex.ppm.map((p, i) => `${i ? "L" : "M"}${X(p).toFixed(1)},${Y(arr[i] + off).toFixed(1)}`).join("");
  const area = (arr) => `${path(arr)}L${X(lo)},${Y(0)}L${X(hi)},${Y(0)}Z`;
  const peaks = ex.peaks.filter((p) => p.ppm >= lo && p.ppm <= hi && p.name !== "Cr CH2" && p.name !== "Glx");
  return `<svg class="chart bench-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Simulated spectrum with its fit">
    ${[4, 3.5, 3, 2.5, 2].filter((p) => p >= lo && p <= hi).map((p) => `<line class="grid" x1="${X(p)}" x2="${X(p)}" y1="${T}" y2="${H - B}"/><text x="${X(p)}" y="${H - 10}" text-anchor="middle">${p.toFixed(1)}</text>`).join("")}
    <text x="${W - R}" y="${H - 10}" text-anchor="end" class="label-strong">ppm</text>
    ${peaks.map((p) => `<text x="${X(p.ppm)}" y="${T - 10}" text-anchor="middle" class="label-strong">${esc(p.name)}</text>`).join("")}
    ${ex.components.Cr ? `<path class="bench-comp-cr" d="${area(ex.components.Cr)}"/>` : ""}
    ${ex.components.Cho ? `<path class="bench-comp-cho" d="${area(ex.components.Cho)}"/>` : ""}
    <path class="bench-data" d="${path(ex.data)}"/>
    <path class="bench-fitline draw" pathLength="1" style="--len:1" d="${path(ex.fit)}"/>
    <line class="grid" x1="${L}" x2="${W - R}" y1="${Y(resOff)}" y2="${Y(resOff)}"/>
    <path class="bench-resid" d="${path(ex.residual, resOff)}"/>
    <text x="${L + 2}" y="${Y(resOff - 0.1 * span) + 4}">residual (data minus fit)</text>
  </svg>
  <div class="legend"><span><i class="sw bench-data"></i>Simulated data</span><span><i class="sw bench-fitline"></i>Lorentzian fit</span><span><i class="sw block bench-comp-cho"></i>Fitted Cho</span><span><i class="sw block bench-comp-cr"></i>Fitted Cr</span></div>`;
}

// ---------------------------------------------------------------- page

function verdictChip(ok, yes, no) {
  return `<span class="chip ${ok ? "PASS" : "WARN"}"><i class="ph-fill ${ok ? "ph-check-circle" : "ph-warning"}"></i>${esc(ok ? yes : no)}</span>`;
}

function statsHtml(s, setup) {
  const h = s.headline;
  const fitted = h.fitted_warn_factor, declared = h.declared_warn_factor;
  const ev = h.evidence95, fa = h.false_alarm_supported ?? h.false_alarm, nc = h.coverage95_nochange;
  return `<section class="bench-stats" aria-label="Headline results">
    <div class="bench-stat lead">
      <div class="k">Error bars that hold the truth</div>
      <div class="v num">${pct(ev)}</div>
      <p>Each packet's 95% interval, after the twin's WARN factor, contains the true value this often. Target 95%.</p>
      ${verdictChip(ev >= 0.9, "close to target", "too narrow")}
    </div>
    <div class="bench-stat">
      <div class="k">WARN factor the data supports</div>
      <div class="v num">${x2(fitted)}<small>declared ×${fmt(declared, 0)}</small></div>
      <p>For WARN from a broad line or low SNR: the smallest factor that makes those intervals cover 95% of truths.</p>
      ${verdictChip(fitted <= declared, `×${fmt(declared, 0)} is on the safe side`, `×${fmt(declared, 0)} is too small`)}
    </div>
    <div class="bench-stat">
      <div class="k">False alarms</div>
      <div class="v num">${pct(fa)}</div>
      <p>No true change, yet the twin called the change "supported". Target: about 5%.${s.decisions.null_possible !== undefined ? ` In another ${pct(s.decisions.null_possible + s.decisions.null_investigate)} it asked for a repeat or a check, without claiming a change.` : ""}</p>
      ${verdictChip(fa <= 0.08, "near 5%", "above 5%")}
    </div>
    <div class="bench-stat">
      <div class="k">Twin interval, nothing changed</div>
      <div class="v num">${pct(nc)}</div>
      <p>When the truth stayed at 0.69, the twin's 95% belief interval at month 6 contained it this often.</p>
      ${verdictChip(nc >= 0.9, "honest", "too confident")}
    </div>
  </section>`;
}

function stepsHtml(setup, n) {
  const steps = [
    ["ph-pencil-simple-line", "Write the truth", `Cho/Cr is 0.69 at baseline. At month 6 it is unchanged (${Math.round(setup.change_p[0] * 100)}% of cases) or higher by 0.05, 0.10 or 0.16.`],
    ["ph-wave-sine", "Spoil the scan", "Linewidth 8 to 16 Hz, noise, frequency drift, a misplaced voxel, a longer echo time or a 1.5 T scanner."],
    ["ph-function", "Fit like a pipeline", "Lorentzian fit of the spectrum. Cho/Cr, its Cramér-Rao bound, SNR and linewidth, measured as the StarterPack defines them."],
    ["ph-shield-check", "Check, update, grade", `A schema-valid packet goes through the real checker and a fresh twin. The truth for all ${n} cases stays in a separate file.`],
  ];
  return `<ol class="bench-steps">${steps.map(([icon, t, d]) => `<li><i class="ph-duotone ${icon}"></i><div><b>${esc(t)}</b><span>${esc(d)}</span></div></li>`).join("")}</ol>`;
}

function calibTable(s) {
  const declared = s.headline.declared_warn_factor;
  const rows = GROUPS.map(([k, name]) => [name, s.calibration[k], k]).filter(([, c]) => c && c.n);
  return `<table class="dict bench-table"><thead><tr><th>Evidence group</th><th class="r">Cases</th><th class="r">Factor needed</th><th>Reading</th></tr></thead><tbody>
    ${rows.map(([name, c, k]) => {
      const need = c.k95, limit = k === "PASS" ? 1.3 : declared;
      const ok = need <= limit;
      const reading = k === "PASS" ? (ok ? "Honest as stated" : need <= 2 ? "Slightly too small" : "Too small even for PASS")
        : ok ? `Covered by the declared ×${fmt(declared, 0)}` : need > 3 * declared ? "A bias, not noise. No factor fixes it" : `Needs more than ×${fmt(declared, 0)}`;
      return `<tr><td>${esc(name)}</td><td class="r num">${c.n}</td><td class="r num">${x2(need)}</td><td>${verdictChip(ok, reading, reading)}</td></tr>`;
    }).join("")}
  </tbody></table>`;
}

function decisionTable(s) {
  const d = s.decisions;
  const c = (r, k) => r.calls?.[k] ?? 0;
  const noticed = (r) => { const a = r.n - r.rejected; return a ? (c(r, "supported") + c(r, "possible") + c(r, "investigate")) / a : null; };
  if (!s.decision_table[0]?.calls) return `<div class="empty">Press "Run again" to grade the twin's own words.</div>`;
  return `<table class="dict bench-table"><thead><tr><th>True change</th><th class="r">Cases</th><th class="r">Rejected</th><th class="r">"Supported"</th><th class="r">"Possible"</th><th class="r">"Investigate"</th><th class="r">No clear change</th><th class="r">Result</th></tr></thead><tbody>
    ${s.decision_table.map((r) => {
      const isNull = r.true_change === 0;
      const good = isNull ? r.rate_supported <= 0.08 : true;
      return `<tr class="${isNull ? "null" : ""}"><td class="num">${isNull ? "none" : `+${fmt(r.true_change, 2)}`}</td><td class="r num">${r.n}</td><td class="r num">${r.rejected}</td>
        <td class="r num">${c(r, "supported")}</td><td class="r num">${c(r, "possible")}</td><td class="r num">${c(r, "investigate")}</td><td class="r num">${c(r, "not supported")}</td>
        <td class="r"><span class="bench-rate ${good ? "ok" : "bad"} num">${pct(isNull ? r.rate_supported : noticed(r))}</span><span class="small muted"> ${isNull ? "false alarms" : "noticed"}</span></td></tr>`;
    }).join("")}
  </tbody></table>
  <p class="small muted bench-foot">The twin calls a change "supported" only when z is beyond 1.96 on evidence that passed every check. The same z on warned evidence reads "possible", and the advice is to repeat the scan. "Investigate" means the surprise gate d² fired. The raw z alone, without that rule, flags ${pct(d.false_alarm)} of the no-change cases (${d.raw_z_alarms_null_protocol_change} of those ${d.raw_z_alarms_null} follow an echo-time or field change, which shifts the value in a way no error bar covers).</p>`;
}

function lwSentence(rows) {
  const narrow = rows[0], broad = rows.slice(-2);
  if (!narrow || !broad.length) return "";
  const rN = narrow.fit_err_rms / narrow.crlb_rms;
  const rB = broad.reduce((a, r) => a + r.fit_err_rms * r.n, 0) / broad.reduce((a, r) => a + r.crlb_rms * r.n, 0);
  return `At narrow lines the real fit error is ${fmt(rN, 1)} times the bound. Above 12 Hz it is ${fmt(rB, 1)} times the bound: our simulated lines are partly Gaussian (a poor shim), and the fit assumes pure Lorentzians. The bound cannot see that model error. This is the gap the WARN factor is meant to cover (dossier §7.5).`;
}

function examplePanel(ex) {
  if (!ex) return "";
  return `<section class="panel bench-span">
    <div class="panel-head"><i class="ph ph-wave-triangle"></i><h2 class="grow">One simulated scan and its fit</h2>${verdictChip(ex.status === "PASS", "PASS", ex.status)}</div>
    <p class="bench-p">The case closest to the StarterPack follow-up (11.4 Hz, SNR 24.8). The fit finds Cho/Cr from the two shaded peaks. The residual shows what the Lorentzian model misses.</p>
    ${spectrumChart(ex)}
    <div class="kv bench-kv">
      <div><div class="k">True Cho/Cr</div><div class="val num">${fmt(ex.true_followup, 3)}</div></div>
      <div><div class="k">Fitted (DERIVED)</div><div class="val num">${fmt(ex.y, 3)}<small>± ${fmt(ex.u, 3)}</small></div></div>
      <div><div class="k">Linewidth</div><div class="val num">${fmt(ex.fwhm, 1)}<small>Hz</small></div></div>
      <div><div class="k">SNR</div><div class="val num">${fmt(ex.snr, 1)}</div></div>
    </div>
    <p class="small muted bench-foot">Error of this scan: ${fmt((ex.y - ex.true_followup) / ex.u, 1)} SD. The ratio actually in the voxel was ${fmt(ex.apparent_ratio, 3)}; the rest is fit error.</p>
  </section>`;
}

function limitsPanel(d) {
  const st = d.setup;
  return `<section class="panel bench-span bench-limits">
    <div class="panel-head"><i class="ph ph-warning-diamond"></i><h2 class="grow">What this bench does not show</h2></div>
    <ul>
      <li>The generator is ours. Its Gaussian shim broadening, drift and tissue model decide how big the gap above the bound is. A fit with a Voigt line model would close part of it. The fitted factor is a property of this generator, not of real scanners.</li>
      <li>Voxel misplacement is a random Cho/Cr shift of ${fmt(st.tissue_bias_per_mm, 3)} per mm of registration error. Real grey and white matter mixing is not simulated.</li>
      <li>Cr is assumed stable. There is no macromolecule baseline, no water residual, no eddy currents.</li>
      <li>The 1.5 T cases declare harmonization, so the checker gives WARN, not FAIL. In this generator Cho/Cr does not depend on field. On real data that claim needs its own evidence.</li>
      <li>The twin's drift assumption (about 0.03 in six months) is a teaching value. Large true changes break it on purpose, to show that the surprise gate catches most of them.</li>
      <li>Packets use session ses-followup with simulated source files. Each case runs on its own fresh twin, so duplicate and session rules never interfere.</li>
    </ul>
    <div class="row bench-dl">
      <a class="btn" href="/api/bench/packets" download><i class="ph ph-file-arrow-down"></i>Student packets</a>
      <a class="btn" href="/api/bench/truth" download><i class="ph ph-lock-key"></i>Instructor truth file</a>
      <span class="small muted">Kept apart on purpose (dossier §4.8): the packets carry no truth.</span>
    </div>
  </section>`;
}

function controlsHtml(d) {
  const lim = d?.limits || { n_min: 20, n_max: 600, default_n: 250 };
  return `<form class="bench-run" data-run>
    <label class="field">Seed<input type="number" name="seed" min="0" step="1" value="${esc(d?.seed ?? 2026)}" required></label>
    <label class="field">Cases<input type="number" name="n" min="${lim.n_min}" max="${lim.n_max}" step="10" value="${esc(d?.n ?? lim.default_n)}" required></label>
    <button class="btn primary" type="submit" ${view.running ? "disabled" : ""}><i class="ph ${view.running ? "ph-circle-notch bench-spin" : "ph-arrow-clockwise"}"></i>${view.running ? "Running" : "Run again"}</button>
  </form>`;
}

function modeHtml() {
  return `<div class="bench-mode">
    <span class="small muted">What the packet's error bar contains</span>
    <div class="bench-seg" role="tablist">${Object.entries(MODES).map(([k, m]) => `<button type="button" role="tab" aria-selected="${view.mode === k}" data-mode="${k}" class="${view.mode === k ? "on" : ""}">${esc(m.label)}</button>`).join("")}</div>
    <p class="small muted">${esc(MODES[view.mode].note)}</p>
  </div>`;
}

function pageHtml(d) {
  const s = (d.summaries && d.summaries[view.mode]) || d.summary;
  const h = s.headline;
  const sc = s.status_counts;
  return `<div class="view bench">
    <header class="bench-head">
      <div>
        <h1>Test bench</h1>
        <p class="lede">We wrote the true Cho/Cr ourselves and simulated ${d.n} follow-up scans that went wrong in known ways. Every scan went through the real checker and the real twin. Because we know the truth, we can grade the twin.</p>
      </div>
      ${controlsHtml(d)}
    </header>
    ${view.running ? `<div class="note bench-running"><i class="ph ph-hourglass-medium"></i><div>Simulating and fitting ${esc(view.runningN)} scans. This takes about ${Math.max(5, Math.round(view.runningN * 0.08))} seconds.</div></div>` : ""}
    ${stepsHtml(d.setup, d.n)}
    ${modeHtml()}
    ${statsHtml(s, d.setup)}
    <p class="small muted bench-meta">Seed ${d.seed}, ${d.n} cases: ${sc.PASS} PASS, ${sc.WARN} WARN, ${sc.FAIL} rejected. Computed in ${fmt(d.runtime_s, 1)} s. All values SIMULATED.</p>

    <div class="bench-grid">
      <section class="panel bench-span">
        <div class="panel-head"><i class="ph ph-git-diff"></i><h2 class="grow">Did the twin call the change right?</h2></div>
        ${decisionTable(s)}
      </section>
    </div>
    <details class="fold bench-more">
      <summary class="panel bench-more-sum"><i class="ph ph-caret-right"></i><b>The detail behind these numbers</b><span class="muted small">error bars, the Cramér-Rao bound, one simulated scan, what the bench does not show</span></summary>
    <div class="bench-grid">
      <section class="panel">
        <div class="panel-head"><i class="ph ph-arrows-out-line-vertical"></i><h2 class="grow">Is the error bar honest?</h2></div>
        <p class="bench-p">How often the packet interval y ± 1.96·√f·u holds the true value, as the variance factor f grows. The twin uses f = 1 for PASS and f = ${fmt(h.declared_warn_factor, 0)} for WARN. Where a line crosses 95% is the factor the data supports.</p>
        ${factorChart(s.factor_curve, h.declared_warn_factor, h.fitted_warn_factor)}
      </section>
      <section class="panel">
        <div class="panel-head"><i class="ph ph-scales"></i><h2 class="grow">Factor needed, by reason for WARN</h2></div>
        <p class="bench-p">Squared error divided by the reported variance, set so that 95% of intervals hold the truth. Noise can be fixed by a factor. A bias cannot.</p>
        ${calibTable(s)}
      </section>

      <section class="panel bench-span">
        <div class="panel-head"><i class="ph ph-chart-bar"></i><h2 class="grow">The Cramér-Rao bound is a lower bound</h2><span class="chip neutral">same protocol only</span></div>
        <div class="bench-split">
          <div>${crlbChart(s.crlb_by_linewidth)}</div>
          <p class="bench-p">${esc(lwSentence(s.crlb_by_linewidth))} The total error adds voxel misplacement, which no spectral fit can see.</p>
        </div>
      </section>

      <section class="panel bench-span">
        <div class="panel-head"><i class="ph ph-target"></i><h2 class="grow">The twin's belief at month 6</h2></div>
        <div class="bench-duo">
          <div>${calibrationChart(s.coverage)}</div>
          <div>${changeBars(s.coverage_by_change)}</div>
          <p class="bench-p">When nothing changed, the twin's 95% interval held the truth ${pct(h.coverage95_nochange)} of the time. The twin expects natural drift of about 0.03 in six months, so after a large real change (0.10 or 0.16) it moves only part of the way and its interval misses. It does not stay silent: the surprise gate d² rose in ${pct(s.coverage_by_change.at(-1)?.d2_flag_rate)} of the +0.16 cases, telling the user "this does not fit my model".</p>
        </div>
      </section>

      ${examplePanel(d.example)}
      ${limitsPanel(d)}
    </div>
    </details>
  </div>`;
}

function skeleton(msg) {
  return `<div class="view bench"><h1>Test bench</h1><p class="lede">${esc(msg)}</p>
    <div class="bench-stats">${[0, 1, 2, 3].map(() => `<div class="skeleton" style="height:150px"></div>`).join("")}</div>
    <div class="bench-grid" style="margin-top:16px"><div class="skeleton" style="height:320px"></div><div class="skeleton" style="height:320px"></div></div></div>`;
}

function errorHtml(msg) {
  return `<div class="view bench"><h1>Test bench</h1>
    <div class="empty bench-error"><i class="ph ph-plug-x"></i><p>The bench results could not be loaded. ${esc(msg)}</p>
    <button class="btn" type="button" data-retry><i class="ph ph-arrow-clockwise"></i>Try again</button></div></div>`;
}

function wire(root) {
  root.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    view.mode = b.dataset.mode;
    paint(root);
  }));
  root.querySelector("[data-run]")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (view.running) return;
    const fd = new FormData(e.currentTarget);
    const seed = parseInt(fd.get("seed"), 10), n = parseInt(fd.get("n"), 10);
    view.running = true; view.runningN = n;
    paint(root);
    try {
      view.data = await api.post("/api/bench/run", { seed, n });
      toast(`Bench finished: ${n} cases, seed ${seed}.`);
    } catch (err) {
      toast(`Bench run failed: ${err.message}`, true);
    } finally {
      view.running = false;
      if (view.root) paint(view.root);
    }
  });
  root.querySelector("[data-retry]")?.addEventListener("click", () => render(root));
}

function paint(root) {
  root.innerHTML = view.data ? pageHtml(view.data) : errorHtml(view.error || "");
  wire(root);
}

export async function render(root) {
  view.root = root;      // the router draws each visit into a fresh element; a finished run repaints the current one
  if (view.data) { paint(root); return; }
  root.innerHTML = skeleton("Loading the cached bench run. The first run ever simulates and fits a few hundred scans, which takes about 20 seconds.");
  try {
    view.data = await api.get("/api/bench");
    view.error = null;
  } catch (err) {
    view.error = err.message;
  }
  if (view.root === root) paint(root);
}
