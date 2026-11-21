// Larmor pitch deck: slide navigation, theme, speaker notes, and the three drawings.
// Standalone on purpose: no imports and no API calls, so the same file works from the app and from a static host.
// Every number drawn here is a verified value of the worked example (see deliverables/challenge_canvas.md).
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const el = (name, attrs, text) => {
    const n = document.createElementNS(NS, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");

  // ---------- drawings ----------

  // Title: a free induction decay, the raw signal every number in the app starts from.
  function drawFid(svg) {
    const pts = [];
    for (let i = 0; i <= 640; i++) {
      const t = i / 640;
      pts.push([10 + 780 * t, 55 - 46 * Math.exp(-t / 0.28) * Math.cos(2 * Math.PI * 34 * t)]);
    }
    svg.appendChild(el("path", { d: path(pts) }));
  }

  // Evidence: two Lorentzian spectra drawn from the packet values.
  // Peak area = the ratio to creatine; linewidth 8.7 Hz (baseline) and 11.4 Hz (follow-up) at 123.25 MHz.
  function drawSpectrum(svg) {
    const MHZ = 123.25, P0 = 3.6, P1 = 1.7, Y0 = 300, H = 250;
    const X = (ppm) => 40 + ((P0 - ppm) / (P0 - P1)) * 720;
    const scans = [
      { cls: "l-base", fwhmHz: 8.7, peaks: [[2.01, 1.25], [3.03, 1.0], [3.20, 0.69]] },
      { cls: "l-follow", fwhmHz: 11.4, peaks: [[2.01, 1.16], [3.03, 1.0], [3.20, 0.85]] },
    ];
    const value = (s, ppm) => {
      const w = s.fwhmHz / MHZ, hw2 = (w / 2) ** 2;
      return s.peaks.reduce((a, [p0, area]) => a + (area * 2 / (Math.PI * w)) * hw2 / ((ppm - p0) ** 2 + hw2), 0);
    };
    const top = value(scans[0], 2.01);                      // tallest point: baseline NAA
    const Y = (v) => Y0 - (v / top) * H;

    svg.appendChild(el("line", { class: "axis", x1: 40, y1: Y0, x2: 760, y2: Y0 }));
    for (const p of [3.5, 3.0, 2.5, 2.0]) {
      svg.appendChild(el("line", { class: "tick", x1: X(p), y1: Y0, x2: X(p), y2: Y0 + 6 }));
      svg.appendChild(el("text", { class: "lbl dim", x: X(p), y: Y0 + 27, "text-anchor": "middle" }, p.toFixed(1)));
    }
    svg.appendChild(el("text", { class: "lbl dim", x: 760, y: Y0 + 52, "text-anchor": "end" }, "ppm"));

    for (const s of scans) {
      const pts = [];
      for (let i = 0; i <= 720; i++) { const ppm = P0 - (i / 720) * (P0 - P1); pts.push([X(ppm), Y(value(s, ppm))]); }
      svg.appendChild(el("path", { class: s.cls, d: path(pts) }));
    }

    const yCho = Y(value(scans[0], 3.20)), yCr = Y(value(scans[0], 3.03));
    svg.appendChild(el("text", { class: "lbl", x: X(3.20) - 10, y: yCho - 6, "text-anchor": "end" }, "Cho 3.20"));
    svg.appendChild(el("text", { class: "lbl", x: X(3.03) + 10, y: yCr - 4, "text-anchor": "start" }, "Cr 3.03"));
    svg.appendChild(el("text", { class: "lbl", x: X(2.01), y: Y(top) - 12, "text-anchor": "middle" }, "NAA 2.01"));
    const by = Math.min(yCho, yCr) - 34;                    // bracket over the two close peaks
    svg.appendChild(el("path", { class: "bracket", d: `M${X(3.20)},${by + 8}V${by}H${X(3.03)}V${by + 8}` }));
    svg.appendChild(el("text", { class: "lbl warn", x: (X(3.20) + X(3.03)) / 2, y: by - 8, "text-anchor": "middle" }, "21 Hz apart"));
  }

  // Update: prior (with six months of drift), evidence as weighted (variance doubled), and the new belief.
  function drawCurves(svg) {
    const A = 0.50, B = 1.05, Y0 = 300, H = 250;
    const X = (v) => 40 + ((v - A) / (B - A)) * 720;
    const curves = [
      { cls: "l-prior", mean: 0.69, sd: Math.sqrt(0.05 ** 2 + 0.03 ** 2) },       // P- = 0.0034
      { cls: "l-evidence", mean: 0.85, sd: Math.sqrt(2 * 0.06 ** 2) },            // R = 0.0072
      { cls: "l-post", mean: 0.741, sd: 0.048 },
    ];
    const pdf = (c, v) => Math.exp(-0.5 * ((v - c.mean) / c.sd) ** 2) / (c.sd * Math.sqrt(2 * Math.PI));
    const top = pdf(curves[2], curves[2].mean);
    const Y = (d) => Y0 - (d / top) * H;

    svg.appendChild(el("line", { class: "axis", x1: 40, y1: Y0, x2: 760, y2: Y0 }));
    for (const v of [0.6, 0.7, 0.8, 0.9, 1.0]) {
      svg.appendChild(el("line", { class: "tick", x1: X(v), y1: Y0, x2: X(v), y2: Y0 + 6 }));
      svg.appendChild(el("text", { class: "lbl dim", x: X(v), y: Y0 + 27, "text-anchor": "middle" }, v.toFixed(1)));
    }
    svg.appendChild(el("text", { class: "lbl dim", x: 760, y: Y0 + 52, "text-anchor": "end" }, "Cho/Cr"));

    for (const c of curves) {
      const pts = [];
      for (let i = 0; i <= 360; i++) { const v = A + (i / 360) * (B - A); pts.push([X(v), Y(pdf(c, v))]); }
      svg.appendChild(el("path", { class: c.cls, d: path(pts) + (c.cls === "l-post" ? "Z" : "") }));
    }
    svg.appendChild(el("line", { class: "guide", x1: X(0.741), y1: Y(top), x2: X(0.741), y2: Y0 }));

    const peak = (c) => Y(pdf(c, c.mean));
    svg.appendChild(el("text", { class: "lbl", x: X(0.69) - 36, y: peak(curves[0]) - 4, "text-anchor": "end" }, "prior 0.69"));
    svg.appendChild(el("text", { class: "lbl accent", x: X(0.741) + 14, y: peak(curves[2]) - 10, "text-anchor": "start" }, "belief 0.741"));
    svg.appendChild(el("text", { class: "lbl warn", x: X(0.85) + 10, y: peak(curves[1]) - 14, "text-anchor": "start" }, "evidence 0.85, half weight"));
  }

  const DRAW = { fid: drawFid, spectrum: drawSpectrum, curves: drawCurves };
  document.querySelectorAll("svg[data-draw]").forEach((svg) => {
    try { DRAW[svg.dataset.draw]?.(svg); } catch (err) { console.error("drawing failed:", svg.dataset.draw, err); }
  });

  // ---------- navigation ----------

  const slides = [...document.querySelectorAll(".slide")];
  const counter = document.getElementById("counter");
  const label = document.getElementById("slideLabel");
  const bar = document.getElementById("progressBar");
  const notesPanel = document.getElementById("notesPanel");
  const notesText = document.getElementById("notesText");
  let current = 0;

  const fromHash = () => {
    const n = parseInt(location.hash.replace("#", ""), 10);
    return Number.isFinite(n) ? Math.min(Math.max(n, 1), slides.length) - 1 : 0;
  };

  function show(i, writeHash = true) {
    current = Math.min(Math.max(i, 0), slides.length - 1);
    slides.forEach((s, k) => s.classList.toggle("on", k === current));
    counter.textContent = `${current + 1} / ${slides.length}`;
    label.textContent = slides[current].dataset.label || "";
    bar.style.width = `${((current + 1) / slides.length) * 100}%`;
    notesText.textContent = slides[current].querySelector(".notes")?.textContent.trim() || "";
    if (writeHash && location.hash !== `#${current + 1}`) history.replaceState(null, "", `#${current + 1}`);
  }
  const next = () => show(current + 1);
  const prev = () => show(current - 1);

  function setThemeIcon() {
    const dark = document.documentElement.dataset.theme !== "light";
    document.querySelector("#themeBtn i").className = `ph ${dark ? "ph-sun" : "ph-moon"}`;
  }
  function toggleTheme() {
    const to = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = to;
    try { localStorage.setItem("larmor-theme", to); } catch (e) { /* storage unavailable */ }
    setThemeIcon();
  }
  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else document.documentElement.requestFullscreen?.().catch(() => {});
  }

  document.getElementById("themeBtn").addEventListener("click", toggleTheme);
  document.getElementById("nextBtn").addEventListener("click", next);
  document.getElementById("prevBtn").addEventListener("click", prev);
  document.getElementById("deck").addEventListener("click", (e) => {
    if (window.matchMedia("(max-width: 720px)").matches) return;          // phones scroll instead
    if (e.target.closest("a, button, .sim-badge") || String(window.getSelection())) return;
    next();
  });
  window.addEventListener("hashchange", () => show(fromHash(), false));
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " " || k === "Enter") { e.preventDefault(); next(); }
    else if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp" || k === "Backspace") { e.preventDefault(); prev(); }
    else if (k === "Home") { e.preventDefault(); show(0); }
    else if (k === "End") { e.preventDefault(); show(slides.length - 1); }
    else if (k === "f" || k === "F") toggleFullscreen();
    else if (k === "n" || k === "N") notesPanel.hidden = !notesPanel.hidden;
    else if (k === "t" || k === "T") toggleTheme();
    else if (k === "Escape") notesPanel.hidden = true;
  });

  setThemeIcon();
  show(fromHash(), false);
})();
