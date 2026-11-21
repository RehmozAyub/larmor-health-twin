// Hero: the journey of one number (Cho/Cr) up the ladder of the course, L0 spins to L4 twin.
// Same framing as the organisers' intro lecture ("follow one number up the ladder"). Every visual is drawn
// from the real StarterPack data. Nothing plays on its own: all five stages are readable at rest, and hovering
// or focusing one lights the path the number took to get there. Only the L0 canvas moves, and only while its
// stage is hovered or focused: the FID is a process in time, which a still frame cannot show.
import { esc, fmt } from "./core.js";
import { beliefChart } from "./charts.js";

const reduce = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function fidCanvasStage() {
  return `<canvas class="hero-canvas" data-fid role="img" aria-label="Precessing spins and the free induction decay they induce in the coil"></canvas>`;
}

function spectrumSvg(s0, s1) {
  const W = 220, H = 120, lo = 1.85, hi = 3.45, T = 16, B = 18;
  const pick = (s) => s.ppm.map((p, i) => [p, s.real[i]]).filter(([p]) => p >= lo && p <= hi);
  const a0 = pick(s0), a1 = pick(s1);
  const ymax = Math.max(...a0.map((x) => x[1]), ...a1.map((x) => x[1]));
  const ymin = Math.min(...a0.map((x) => x[1]), ...a1.map((x) => x[1]));
  const X = (p) => ((hi - p) / (hi - lo)) * W;
  const Y = (v) => H - B - ((v - ymin) / (ymax - ymin)) * (H - T - B);
  const line = (a) => a.map(([p, v], i) => `${i ? "L" : "M"}${X(p).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const area = (a, p0, p1) => {
    const seg = a.filter(([p]) => p >= p0 && p <= p1);
    if (!seg.length) return "";
    return `M${X(seg[0][0])},${Y(ymin)}` + seg.map(([p, v]) => `L${X(p).toFixed(1)},${Y(v).toFixed(1)}`).join("") + `L${X(seg[seg.length - 1][0])},${Y(ymin)}Z`;
  };
  return `<svg class="hero-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Follow-up spectrum with the choline and creatine peaks highlighted">
    <path d="${area(a1, 3.14, 3.27)}" class="pk-cho"/><path d="${area(a1, 2.96, 3.10)}" class="pk-cr"/>
    <path d="${line(a0)}" class="sp0"/><path d="${line(a1)}" class="sp1 draw" pathLength="1" style="--len:1"/>
    <text x="${X(3.21)}" y="11" text-anchor="middle" class="lab acc">Cho</text>
    <text x="${X(3.02)}" y="11" text-anchor="middle" class="lab">Cr</text>
    <text x="${X(2.01)}" y="11" text-anchor="middle" class="lab">NAA</text>
    <text x="${W}" y="${H - 3}" text-anchor="end" class="ax">ppm</text>
    ${[3.4, 3.0, 2.6, 2.2].map((p) => `<text x="${X(p)}" y="${H - 3}" text-anchor="middle" class="ax">${p.toFixed(1)}</text>`).join("")}
  </svg>`;
}

function voxelSvg() {
  // Isometric 20 mm cubes: where the Cho signal and the NAA signal actually come from (2.4 mm apart, PRESS).
  const iso = (x, y, z) => [110 + (x - y) * 2.7, 60 + (x + y) * 1.35 - z * 2.9];
  const cube = (o, cls) => {
    const c = [[0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0], [0, 0, 20], [20, 0, 20], [20, 20, 20], [0, 20, 20]]
      .map(([x, y, z]) => iso(x + o[0] - 10, y + o[1] - 10, z + o[2] - 10));
    const E = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
    return E.map(([a, b]) => `<line x1="${c[a][0].toFixed(1)}" y1="${c[a][1].toFixed(1)}" x2="${c[b][0].toFixed(1)}" y2="${c[b][1].toFixed(1)}" class="${cls}"/>`).join("");
  };
  return `<svg class="hero-svg" viewBox="0 0 220 120" role="img" aria-label="The NAA and choline voxels are offset by 2.4 mm">
    <g class="spin-slow">${cube([0, 0, 0], "vx-naa")}${cube([2.4, 2.4, 2.4], "vx-cho")}</g>
    <text x="8" y="112" class="ax">20 mm voxel</text><text x="212" y="112" text-anchor="end" class="ax acc">Cho shifted 2.4 mm</text>
  </svg>`;
}

function gauges(checks) {
  const rows = [
    { n: "SNR", key: "mrs_snr", lim: 25, max: 40, low: true },
    { n: "Linewidth", key: "mrs_linewidth_Hz", lim: 10, max: 16, unit: "Hz" },
    { n: "Alignment", key: "registration_rms_mm", lim: 2, max: 3.2, unit: "mm" },
  ];
  return `<div class="gauges">${rows.map((r) => {
    const c = checks.find((x) => x.name === r.key) || {};
    const v = c.value ?? 0;
    const st = c.status || "PASS";
    const pos = Math.min(100, (v / r.max) * 100), lim = (r.lim / r.max) * 100;
    return `<div class="gauge ${esc(st)}"><span class="gn">${r.n}</span>
      <span class="gs"><i class="gl" style="left:${lim}%"></i><i class="gv" style="left:${pos}%"></i></span>
      <span class="gx num">${fmt(v, 1)}${r.unit ? ` ${r.unit}` : ""}</span></div>`;
  }).join("")}</div>`;
}

export function heroHtml(d) {
  const t1 = d.t1, ev = d.event;
  const stage = (i, level, title, owner, visual, value, caption, label) => `
    <article class="stage" data-stage="${i}" tabindex="0" role="listitem" aria-labelledby="stage-h-${i}" aria-describedby="stage-p-${i}">
      <header><span class="lvl">${level}</span><span class="own" title="Owning track">${owner}</span></header>
      <h3 id="stage-h-${i}">${title}</h3>
      <div class="visual">${visual}</div>
      <div class="sval">${value}</div>
      <p id="stage-p-${i}">${caption}</p>
      <span class="epi">${label}</span>
    </article>`;
  return `<section class="hero" aria-label="The journey of one number">
    <div class="hero-head">
      <div><h2>The journey of one number</h2>
      <p>Cho/Cr travels from the spins to the twin. Each step is owned by one track and adds what the next one needs.</p></div>
      <a class="btn ghost" href="#/scans"><i class="ph ph-wave-sine"></i>Raw spectra</a>
    </div>
    <div class="stages" role="list">
      ${stage(0, "L0 · Spins", "The coil records a fading signal", "QE", fidCanvasStage(),
        `<span class="num">123.25</span> MHz`, `¹H spins precess in B₀ = 2.895 T (label says 3 T). The decaying FID is the raw data.`, "MEASURED-level")}
      ${stage(1, "L1 · Molecules", "Chemistry becomes frequency", "QE", spectrumSvg(d.spec0, d.spec1),
        `<span>Cho <span class="num">3.20</span>, Cr <span class="num">3.03</span> ppm</span>`, `Fourier transform gives the spectrum. Choline and creatine sit only 21 Hz apart.`, "DERIVED")}
      ${stage(2, "L2 · One voxel", "A ratio from one cube of tissue", "QE", voxelSvg(),
        `<span class="num big">${fmt(t1.y, 2)}</span> <span class="num">± ${fmt(t1.u, 2)}</span>`, `Fitted Cho/Cr in the frontal voxel. It was ${fmt(d.t0.y, 2)} ± ${fmt(d.t0.u, 2)} six months earlier.`, "DERIVED")}
      ${stage(3, "L3 · Scanner", "Are the two sessions comparable?", "PM · DS", gauges(t1.checks),
        `<span class="chip ${esc(t1.status)}"><i class="ph-fill ph-warning"></i>${esc(t1.status)}</span> <span class="small muted">SHA-256 ${d.verified ? "verified" : "n/a"}</span>`,
        `Broader line and lower SNR than baseline. The evidence packet carries every check, its owner and the source hash.`, "CHECKED")}
      ${stage(4, "L4 · Twin", "How far may the belief move?", "DT", ev ? beliefChart({
          prior: { mean: ev.prior.mean_minus, sd: Math.sqrt(ev.prior.var_minus) },
          evidence: { mean: ev.evidence.y, sd: Math.sqrt(ev.evidence.R_used) },
          posterior: { mean: ev.posterior.mean, sd: ev.posterior.sd } }, { digits: 1, aria: "Twin belief update" }) : "",
        ev ? `<span class="num">${fmt(ev.prior.mean, 2)}</span> → <span class="num big">${fmt(ev.posterior.mean, 3)}</span>` : "not updated",
        ev ? `Warning evidence counts half. The twin moves ${Math.round(ev.K * 100)} % of the way: suggestive, not conclusive.` : "Run the update to see the belief move.", "INFERRED")}
    </div>
  </section>`;
}

export function startHero(root, d) {
  const wrap = root.querySelector(".stages");
  const stages = [...root.querySelectorAll(".stage")];
  const fid = fidAnimation(root.querySelector("[data-fid]"), d.spec1);
  let hovered = -1, focused = -1;
  // Hover wins over focus so pointer and keyboard never fight; leaving with the pointer restores the focused stage.
  const paint = () => {
    const i = hovered >= 0 ? hovered : focused;
    wrap.classList.toggle("engaged", i >= 0);
    stages.forEach((s, k) => {
      s.classList.toggle("on-path", i >= 0 && k <= i);
      s.classList.toggle("is-active", k === i);
    });
    if (fid) (i === 0 ? fid.play : fid.rest)();
  };
  stages.forEach((s, k) => {
    s.addEventListener("pointerenter", (e) => { if (e.pointerType !== "touch") { hovered = k; paint(); } });
    s.addEventListener("pointerleave", () => { hovered = -1; paint(); });
    s.addEventListener("focus", () => { focused = k; paint(); });
    s.addEventListener("blur", () => { focused = -1; paint(); });
    s.addEventListener("keydown", (e) => {
      const to = { ArrowRight: k + 1, ArrowDown: k + 1, ArrowLeft: k - 1, ArrowUp: k - 1, Home: 0, End: stages.length - 1 }[e.key];
      if (to === undefined || to < 0 || to >= stages.length) return;
      e.preventDefault();
      stages[to].focus();
      stages[to].scrollIntoView({ block: "nearest", inline: "nearest", behavior: reduce() ? "auto" : "smooth" });
    });
  });
}

function fidAnimation(canvas, spec) {
  if (!canvas) return null;
  const ctx = canvas.getContext("2d");
  const fid = spec.fid_real.slice(0, 140);   // first 70 ms: the beat pattern stays readable
  const peak = Math.max(...fid.map(Math.abs));
  const N = 3;
  let w = 0, h = 0, raf = 0, last = 0, t0 = 0, playing = false, col = { acc: "", dim: "" };
  const size = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  const colours = () => {
    const css = getComputedStyle(document.documentElement);
    col = { acc: css.getPropertyValue("--accent").trim(), dim: css.getPropertyValue("--text-3").trim() };
  };
  // u: how far the decay has run (0 = just after the pulse, 1 = whole FID recorded); ph0: precession angle
  const draw = (u, ph0) => {
    if (!w) return;
    const { acc, dim } = col;
    ctx.clearRect(0, 0, w, h);
    const top = h * 0.48;
    // B0 arrow
    ctx.globalAlpha = 1; ctx.strokeStyle = dim; ctx.fillStyle = dim; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(10, top * 0.95); ctx.lineTo(10, top * 0.2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(6, top * 0.28); ctx.lineTo(10, top * 0.16); ctx.lineTo(14, top * 0.28); ctx.fill();
    ctx.font = "10px 'Geist Mono', monospace"; ctx.fillText("B₀", 16, top * 0.26);
    // precessing spins on cones; their phases fan out (T2* dephasing) exactly while the FID below decays
    const k = Math.min(u, 1), shown = Math.floor(k * fid.length), spread = k * 4.5;
    for (let i = 0; i < N; i++) {
      const cx = w * (0.3 + i * 0.25), cy = top * 0.95, L = top * 0.78, th = 0.55;
      const ph = ph0 + (i - 1) * spread * 0.7;
      const ex = cx + Math.sin(th) * L * Math.cos(ph), ey = cy - Math.cos(th) * L + Math.sin(th) * L * Math.sin(ph) * 0.3;
      ctx.strokeStyle = dim; ctx.globalAlpha = 0.22; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.ellipse(cx, cy - Math.cos(th) * L, Math.sin(th) * L, Math.sin(th) * L * 0.3, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.globalAlpha = 1; ctx.strokeStyle = acc; ctx.lineWidth = 2.2;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
      ctx.fillStyle = acc; ctx.beginPath(); ctx.arc(ex, ey, 3, 0, Math.PI * 2); ctx.fill();
    }
    // the FID, as recorded so far
    const mid = top + (h - top) * 0.5, amp = (h - top) * 0.46;
    ctx.strokeStyle = acc; ctx.lineWidth = 1.2; ctx.beginPath();
    for (let i = 0; i < shown; i++) {
      const x = (i / (fid.length - 1)) * w, y = mid - (fid[i] / peak) * amp;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke();
    ctx.strokeStyle = dim; ctx.globalAlpha = 0.5; ctx.setLineDash([3, 3]); ctx.beginPath();
    ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
  };
  // At rest the whole FID is on screen and the spins hold a dephased pose: a complete still figure.
  const still = () => draw(1, 0.9);
  const loop = (t) => {
    if (!canvas.isConnected || !playing) return;
    raf = requestAnimationFrame(loop);
    if (t - last < 33) return;
    last = t;
    const e = t - t0;
    draw(((e * 0.04) / fid.length) % 1.3, 0.9 + e * 0.011);
  };
  const api = {
    play() {
      if (playing || reduce()) return;
      playing = true; colours(); t0 = performance.now(); last = 0;
      raf = requestAnimationFrame(loop);
    },
    rest() {
      if (!playing) return;
      playing = false; cancelAnimationFrame(raf); still();
    },
  };
  colours(); size(); still();
  if ("ResizeObserver" in window) {
    const ro = new ResizeObserver(() => {
      if (!canvas.isConnected) { ro.disconnect(); return; }
      size(); colours(); if (!playing) still();
    });
    ro.observe(canvas);
  }
  return api;
}
