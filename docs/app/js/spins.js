// Background: one Hahn spin echo, drawn the way MR textbooks draw it, slowly and in faint ink.
//
// What you see, in the rotating frame and from slightly above:
//   1. Net magnetization rests along B0 (vertical).
//   2. A 90 degree pulse tips it into the transverse plane (the ellipse).
//   3. Each isochromat sees a slightly different field, so their phases fan out (T2* dephasing). Their summed
//      vector, and so the signal in the coil, fades: the free induction decay (FID).
//   4. A 180 degree pulse turns every vector over about x'. The fan is mirrored, the fast ones now trail.
//   5. They catch up and meet: the echo. The summed vector and the trace below grow again, then fade.
//   6. T1 recovery brings the magnetization back up along B0, and the cycle repeats.
// The trace at the bottom is the signal the coil records over the same time axis (FID, then echo).
// Motivation: every number in the app starts as this signal. Static frame under prefers-reduced-motion,
// paused while the tab is hidden, capped at 30 fps, no scroll listeners, colours read from CSS tokens.

const TAU = Math.PI * 2;
const ease = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u));

// Timeline of one cycle, in milliseconds.
const REST = 1600, P90 = 1300, HALF_TE = 4300, P180 = 1200, AFTER = 3400, RELAX = 3400;
const T_FREE = REST + P90;                      // start of free precession
const CYCLE = T_FREE + HALF_TE + P180 + HALF_TE + AFTER + RELAX;
const ECHO = T_FREE + 2 * HALF_TE + P180;       // moment of the echo
const T2 = 32000;                               // irreversible decay, so the echo is a little smaller than the FID
const N = 64;                                   // isochromats
const OMEGA0 = TAU / 30000;                     // small common off-resonance: the whole fan drifts slowly
const SIGMA = 1.9 / HALF_TE;                    // spread of local field offsets (rad per ms)

// Deterministic Gaussian quantiles for the field offsets (no randomness, same picture every load).
function probit(p) {
  // Acklam's rational approximation, plenty for a picture.
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const q = Math.min(p, 1 - p);
  let x;
  if (q < 0.02425) {
    const r = Math.sqrt(-2 * Math.log(q));
    x = (((((c[0] * r + c[1]) * r + c[2]) * r + c[3]) * r + c[4]) * r + c[5]) / ((((d[0] * r + d[1]) * r + d[2]) * r + d[3]) * r + 1);
    return p < 0.5 ? x : -x;
  }
  const r = (p - 0.5) ** 2;
  return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * (p - 0.5)) /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}
const OFFS = Array.from({ length: N }, (_, i) => OMEGA0 + SIGMA * probit((i + 0.5) / N));

/** Magnetization of isochromat i at cycle time tc, as [x, y, z] in the rotating frame (|M0| = 1). */
function vec(i, tc) {
  if (tc < REST) return [0, 0, 1];
  if (tc < T_FREE) {                                  // 90 degree pulse about x': z tips toward +y
    const a = ease((tc - REST) / P90) * (Math.PI / 2);
    return [0, Math.sin(a), Math.cos(a)];
  }
  const w = OFFS[i], phi0 = Math.PI / 2;
  const s = tc - T_FREE;
  if (s < HALF_TE) {                                  // free precession, dephasing
    const m = Math.exp(-s / T2), p = phi0 + w * s;
    return [m * Math.cos(p), m * Math.sin(p), 0];
  }
  if (s < HALF_TE + P180) {                           // 180 degree pulse about x': y and z rotate
    const m = Math.exp(-HALF_TE / T2), p = phi0 + w * HALF_TE;
    const th = Math.PI * ease((s - HALF_TE) / P180);
    const x = m * Math.cos(p), y = m * Math.sin(p);
    return [x, y * Math.cos(th), y * Math.sin(th)];
  }
  const s2 = s - HALF_TE - P180;                      // mirrored phases now refocus, echo at s2 = HALF_TE
  const p = -(phi0 + w * HALF_TE) + w * s2;
  let m = Math.exp(-(s - P180) / T2), z = 0;
  const r = ease((s2 - HALF_TE - AFTER) / RELAX);     // T1 recovery at the end of the cycle
  if (r > 0) { m *= 1 - r; z = r; }
  return [m * Math.cos(p), m * Math.sin(p), z];
}

function netTransverse(tc) {
  let x = 0, y = 0;
  for (let i = 0; i < N; i++) { const v = vec(i, tc); x += v[0]; y += v[1]; }
  return Math.hypot(x, y) / N;
}

export function startSpins(canvas) {
  const ctx = canvas.getContext("2d");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  const FPS = 30, TRAIL = 12, TRAIL_DT = 60, SAMPLES = 720;
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0, t0 = 0;
  let geo = null, env = null;
  let ink = { acc: "87, 207, 198", dim: "122, 142, 147", gain: 1 };

  const readColor = () => {
    const css = getComputedStyle(document.documentElement);
    ink = {
      acc: css.getPropertyValue("--spin-color").trim() || ink.acc,
      dim: css.getPropertyValue("--spin-muted").trim() || ink.dim,
      gain: parseFloat(css.getPropertyValue("--spin-gain")) || 1,
    };
  };

  function layout() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const narrow = w < 760;
    // The figure sits to the right, where pages keep the most empty space, and is cropped by the edge on
    // small screens rather than shrunk into illegibility.
    const R = narrow ? w * 0.42 : Math.min(w * 0.17, h * 0.3, 270);
    const cx = narrow ? w * 0.72 : w - R * 1.2;
    const cy = narrow ? h * 0.3 : Math.max(150, h * 0.2);
    const k = 0.34, hz = 0.94;                         // ellipse squash and height of the B0 axis
    const tx0 = narrow ? w * 0.06 : Math.max(w * 0.45, w - R * 3.8), tx1 = w - (narrow ? w * 0.06 : R * 0.2);
    const ty = Math.max(cy + R * 1.1, h * 0.84);
    // on a phone the figure sits under the text itself, so it is drawn fainter there
    geo = { R, cx, cy, k, hz, tx0, tx1, ty, amp: Math.min(R * 0.42, 70), soft: narrow ? 0.6 : 1 };
    // the coil signal over one cycle, precomputed once: envelope times a visual carrier
    env = new Float32Array(SAMPLES);
    for (let j = 0; j < SAMPLES; j++) env[j] = netTransverse((j / (SAMPLES - 1)) * CYCLE);
  }

  const P = (v) => [geo.cx + geo.R * v[0], geo.cy + geo.R * geo.k * v[1] - geo.R * geo.hz * v[2]];
  const a = (x) => Math.max(0, Math.min(1, x * ink.gain * geo.soft));

  function drawFrame(tc) {
    const { R, cx, cy, k, hz, tx0, tx1, ty, amp } = geo;
    ctx.clearRect(0, 0, w, h);
    ctx.lineCap = "round"; ctx.lineJoin = "round";

    // transverse plane and the B0 axis
    ctx.strokeStyle = `rgba(${ink.dim}, ${a(0.16)})`; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.ellipse(cx, cy, R, R * k, 0, 0, TAU); ctx.stroke();
    ctx.strokeStyle = `rgba(${ink.dim}, ${a(0.07)})`;
    ctx.beginPath(); ctx.ellipse(cx, cy, R * 0.5, R * k * 0.5, 0, 0, TAU); ctx.stroke();
    ctx.strokeStyle = `rgba(${ink.dim}, ${a(0.2)})`;
    ctx.beginPath(); ctx.moveTo(cx, cy + R * k * 0.25); ctx.lineTo(cx, cy - R * hz * 1.18); ctx.stroke();
    ctx.fillStyle = `rgba(${ink.dim}, ${a(0.32)})`;
    ctx.beginPath(); ctx.moveTo(cx - 4, cy - R * hz * 1.18 + 8); ctx.lineTo(cx, cy - R * hz * 1.18); ctx.lineTo(cx + 4, cy - R * hz * 1.18 + 8); ctx.fill();
    ctx.font = "500 12px 'Geist Mono', ui-monospace, monospace";
    ctx.fillText("B₀", cx + 9, cy - R * hz * 1.18 + 10);

    // isochromats: a fan of faint shafts, long-exposure trails, and heads that are dimmer on the far side
    const vs = [], pts = [];
    for (let i = 0; i < N; i++) { const v = vec(i, tc); vs.push(v); pts.push(P(v)); }
    ctx.strokeStyle = `rgba(${ink.acc}, ${a(0.075)})`; ctx.lineWidth = 1;
    ctx.beginPath();
    for (const p of pts) { ctx.moveTo(cx, cy); ctx.lineTo(p[0], p[1]); }
    ctx.stroke();
    let prev = pts;
    for (let s = 1; s <= TRAIL; s++) {
      const tt = tc - s * TRAIL_DT;
      if (tt < 0) break;
      const cur = [];
      for (let i = 0; i < N; i++) cur.push(P(vec(i, tt)));
      ctx.strokeStyle = `rgba(${ink.acc}, ${a(0.32 * (1 - s / (TRAIL + 1)))})`; ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let i = 0; i < N; i++) { ctx.moveTo(prev[i][0], prev[i][1]); ctx.lineTo(cur[i][0], cur[i][1]); }
      ctx.stroke();
      prev = cur;
    }
    for (const far of [true, false]) {
      ctx.fillStyle = `rgba(${ink.acc}, ${a(far ? 0.3 : 0.6)})`;
      ctx.beginPath();
      for (let i = 0; i < N; i++) {
        if ((vs[i][1] < 0) !== far) continue;
        const p = pts[i];
        ctx.moveTo(p[0] + 1.7, p[1]); ctx.arc(p[0], p[1], 1.7, 0, TAU);
      }
      ctx.fill();
    }

    // the summed magnetization: this is what the coil can hear
    let sx = 0, sy = 0, sz = 0;
    for (const v of vs) { sx += v[0]; sy += v[1]; sz += v[2]; }
    const M = [sx / N, sy / N, sz / N], mp = P(M), strength = Math.hypot(M[0], M[1]);
    ctx.strokeStyle = `rgba(${ink.acc}, ${a(0.18 + 0.5 * strength)})`; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(mp[0], mp[1]); ctx.stroke();
    ctx.fillStyle = `rgba(${ink.acc}, ${a(0.25 + 0.55 * strength)})`;
    ctx.beginPath(); ctx.arc(mp[0], mp[1], 3, 0, TAU); ctx.fill();

    // the recorded signal: faint full cycle, brighter where the sweep has already passed
    const X = (j) => tx0 + (j / (SAMPLES - 1)) * (tx1 - tx0);
    const Y = (j) => ty - env[j] * amp * Math.sin(j * 0.48);
    const now = Math.floor((tc / CYCLE) * (SAMPLES - 1));
    ctx.lineWidth = 1;
    ctx.strokeStyle = `rgba(${ink.dim}, ${a(0.12)})`;
    ctx.beginPath(); ctx.moveTo(tx0, ty); ctx.lineTo(tx1, ty); ctx.stroke();
    ctx.strokeStyle = `rgba(${ink.acc}, ${a(0.07)})`;
    ctx.beginPath();
    for (let j = 0; j < SAMPLES; j++) j ? ctx.lineTo(X(j), Y(j)) : ctx.moveTo(X(j), Y(j));
    ctx.stroke();
    ctx.strokeStyle = `rgba(${ink.acc}, ${a(0.24)})`; ctx.lineWidth = 1.1;
    ctx.beginPath();
    for (let j = 0; j <= now; j++) j ? ctx.lineTo(X(j), Y(j)) : ctx.moveTo(X(j), Y(j));
    ctx.stroke();
    if (now > 0 && now < SAMPLES - 1) {
      ctx.fillStyle = `rgba(${ink.acc}, ${a(0.6)})`;
      ctx.beginPath(); ctx.arc(X(now), Y(now), 2.2, 0, TAU); ctx.fill();
    }
    // the pulse marks and the two events the trace shows
    const jx = (t) => X(Math.round((t / CYCLE) * (SAMPLES - 1)));
    ctx.fillStyle = `rgba(${ink.dim}, ${a(0.42)})`;
    ctx.font = "500 11px 'Geist Mono', ui-monospace, monospace";
    ctx.textAlign = "center";
    const mark = (t, label, up) => {
      ctx.fillRect(jx(t) - 0.5, ty + amp + 2, 1, 5);
      ctx.fillText(label, jx(t), up ? ty - amp - 8 : ty + amp + 18);
    };
    mark(REST + P90 / 2, "90°", false);
    mark(T_FREE + HALF_TE + P180 / 2, "180°", false);
    mark(ECHO, "echo", false);
    ctx.fillText("FID", jx(T_FREE + 1100), ty + amp + 18);
    ctx.textAlign = "start";
  }

  function loop(t) {
    raf = requestAnimationFrame(loop);
    if (t - last < 1000 / FPS - 1) return;
    last = t;
    drawFrame((t - t0) % CYCLE);
  }

  // A still frame that reads on its own: the fan halfway refocused, with the whole trace drawn.
  const STILL = T_FREE + HALF_TE + P180 + HALF_TE * 0.55;

  function start() {
    cancelAnimationFrame(raf);
    readColor(); layout();
    if (reduce.matches) { drawFrame(STILL); return; }
    if (!t0) t0 = performance.now() - (T_FREE + 500);   // open on the fan, not on the resting vector
    raf = requestAnimationFrame(loop);
  }

  window.addEventListener("resize", start);
  reduce.addEventListener("change", start);
  document.addEventListener("visibilitychange", () => {
    cancelAnimationFrame(raf);
    if (!document.hidden && !reduce.matches) raf = requestAnimationFrame(loop);
  });
  new MutationObserver(() => { readColor(); if (reduce.matches) drawFrame(STILL); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  start();
}
