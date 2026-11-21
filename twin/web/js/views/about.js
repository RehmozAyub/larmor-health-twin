// View: Architecture and limits. Every text block is read live from the deliverable files via /api/about,
// so this page and the files a judge downloads can never disagree. The diagram is hand-built SVG.
import { api, esc, toast } from "../core.js";

const OWNER_CODE = {
  "Quantum Engineering": "QE", "Precision Mechanics / Metrology": "PM", "Data Science": "DS",
  "Digital Twins": "DT", "Shared gate": "Shared",
};
const AIM_ICON = {
  "Physical counterpart": "ph-brain", "Modality": "ph-wave-sine", "State variable to update": "ph-gauge",
  "Ambiguity to resolve": "ph-scales", "Prototype output": "ph-target", "One limitation": "ph-warning",
};
const FILE_ICON = { canvas: "ph-target", architecture: "ph-blueprint", limits: "ph-shield-warning", dictionary: "ph-file-csv", reflection: "ph-note-pencil", qc: "ph-list-checks" };
const ETHICS = [
  { title: "Synthetic data only", icon: "ph-flask" },
  { title: "Privacy", icon: "ph-lock-key", tall: true },
  { title: "Clinical non-equivalence", icon: "ph-scales" },
  { title: "Bias and transfer", icon: "ph-compass" },
  { title: "Use of AI", icon: "ph-robot" },
];
const VIEW_ICON = { Domain: "ph-atom", Developer: "ph-code", Application: "ph-app-window", User: "ph-user" };

// ---- diagram model: what is drawn where. Text in the detail panel comes from architecture.md. ----
const STEPS = [
  { step: "Source file", short: "NIfTI, NIfTI-MRS", dts: "PT" },
  { step: "Evidence packet", short: "schema v1.0", dts: "CN" },
  { step: "Six-layer check", short: "PASS, WARN, FAIL", dts: "SS", layers: true },
  { step: "Gated update", short: "gain K, posterior", dts: "DT" },
  { step: "Prediction", short: "95 % repeat range", dts: "DT" },
  { step: "Explanations", short: "kept open", dts: "CC" },
  { step: "Next measurement", short: "gain per minute", dts: "CC" },
];
const LANES = [
  { code: "QE", track: "Quantum Engineering", name: "Quantum Engineering", q: "What is observed?", hands: "measurement card",
    cells: { 0: "spectrum, SNR", 1: "meaning, unit", 2: "SNR, range", 5: "shim, peaks", 6: "re-shim" } },
  { code: "PM", track: "Precision Mechanics / Metrology", name: "Metrology", q: "Can we trust it?", hands: "uncertainty card",
    cells: { 1: "uncertainty", 2: "linewidth, RMS", 3: "honest u", 4: "repeat SD", 5: "registration", 6: "cost, sigma" } },
  { code: "DS", track: "Data Science", name: "Data Science", q: "How is it carried?", hands: "checked packet",
    cells: { 0: "SHA-256", 1: "schema, labels", 2: "schema, links" } },
  { code: "DT", track: "Digital Twins", name: "Digital Twins", q: "How does it update?", hands: "next measurement",
    cells: { 2: "policy layer", 3: "K, posterior", 4: "repeat range", 5: "keeps all open", 6: "rank, advise" } },
];

const G = { X0: 180, COL: 132, GAP: 14, NY: 58, NH: 84, BY: 154, DDY: 192, LY: 240, LH: 54, HX: 1206, W: 1360 };
G.H = G.LY + LANES.length * G.LH + 8;
const colX = (i) => G.X0 + i * (G.COL + G.GAP);
const colC = (i) => colX(i) + G.COL / 2;

// ---- small helpers ----
function md(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
}
const plain = (s) => String(s ?? "").replace(/[`*]/g, "");
const sec = (doc, title) => doc?.sections?.find((s) => s.title === title) || { blocks: [] };
const tableOf = (s) => s.blocks.find((b) => b.kind === "table") || { header: [], rows: [] };
const parasOf = (s) => s.blocks.filter((b) => b.kind === "p").map((b) => b.text);
const listOf = (s) => s.blocks.filter((b) => b.kind === "list").flatMap((b) => b.items);
function rowsBy(s, key = 0) {
  const t = tableOf(s);
  return Object.fromEntries(t.rows.map((r) => [plain(r[key]), Object.fromEntries(t.header.map((h, i) => [h, r[i] ?? ""]))]));
}
const kb = (n) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} kB`);
// "2.05 (limit 1.96)" -> big "2.05" + small "(limit 1.96)"
function ledValue(v) {
  const m = String(v).match(/^(.*?)(\s\(.*|,\s.*)$/);
  return m ? `${md(m[1])}<small>${md(m[2].replace(/^,\s*/, ""))}</small>` : md(v);
}
const codes = (s) => (String(s).match(/`([^`]+)`/g) || []).map((c) => c.slice(1, -1));

function blocksHtml(blocks) {
  return blocks.map((b) => {
    if (b.kind === "p") return `<p>${md(b.text)}</p>`;
    if (b.kind === "list") return `<ul class="ab-list">${b.items.map((x) => `<li>${md(x)}</li>`).join("")}</ul>`;
    return "";
  }).join("");
}

// ---- page ----
export async function render(root) {
  root.innerHTML = `<div class="view"><h1>Architecture and limits</h1>
    <div class="skeleton" style="height:84px;margin:18px 0"></div><div class="skeleton" style="height:360px"></div></div>`;
  let d;
  try { d = await api.get("/api/about"); }
  catch (err) {
    toast(err.message, true);
    root.innerHTML = `<div class="view"><h1>Architecture and limits</h1><div class="empty">Could not read the deliverable files (${esc(err.message)}).</div></div>`;
    return;
  }
  root.innerHTML = `<div class="view ab">
    <h1>Architecture and limits</h1>
    <p class="lede">Our aim, how the system is built and where it stops being valid, read live from the files below.</p>
    ${filesHtml(d.files)}
    ${canvasHtml(d.canvas)}
    ${architectureHtml(d.architecture)}
    ${limitsHtml(d.limits)}
    ${dictionaryHtml(d)}
  </div>`;
  wireDiagram(root, d);
  wireDictionary(root, d);
}

function filesHtml(files) {
  return `<nav class="ab-files" aria-label="Deliverable files">${files.map((f) => `
    <a class="ab-file" href="${esc(f.url)}" download="${esc(f.name)}">
      <i class="ph-duotone ${FILE_ICON[f.key] || "ph-file-text"}"></i>
      <span class="ab-file-dl"><span class="mono">${kb(f.bytes)}</span><i class="ph-duotone ph-download-simple"></i></span>
      <span class="ab-file-txt"><b>${esc(f.name)}</b><span>${esc(f.description)}</span></span>
    </a>`).join("")}</nav>`;
}

// ---- 1. canvas ----
function canvasHtml(c) {
  const aim = tableOf(sec(c, "Aim contract"));
  const primary = sec(c, "Primary variable, declared before looking");
  const success = sec(c, "Success criterion");
  const maturity = sec(c, "Maturity level");
  const levels = listOf(maturity).map((x) => { const i = x.indexOf(":"); return i < 0 ? ["", x] : [x.slice(0, i), x.slice(i + 1).trim()]; });
  return `<section class="ab-sec" aria-labelledby="ab-aim">
    <header class="ab-sec-head"><h2 id="ab-aim">Aim contract</h2><p>${md(c.intro.map((b) => b.text).join(" "))}</p></header>
    <div class="grid g-primary ab-top">
      <div class="panel ab-aim">${aim.rows.map(([k, v]) => `
        <div class="ab-aim-item"><div class="ab-aim-k"><i class="ph-duotone ${AIM_ICON[k] || "ph-circle"}"></i>${esc(k)}</div><p>${md(v)}</p></div>`).join("")}
      </div>
      <div class="stack">
        ${levels.length ? `<div class="panel"><div class="panel-head"><i class="ph-duotone ph-stairs ab-ic"></i><h2 class="grow">Maturity level</h2></div>
          ${parasOf(maturity).map((p) => `<p class="ab-prose-p">${md(p)}</p>`).join("")}
          <div class="ab-mat">${levels.map(([k, t]) => `<div><span class="chip ${/^Past/.test(k) ? "accent" : "neutral"}">${esc(k)}</span><p>${md(t.charAt(0).toUpperCase() + t.slice(1))}</p></div>`).join("")}</div></div>` : ""}
        <details class="panel fold"><summary class="panel-head"><i class="ph-duotone ph-seal-check ab-ic"></i><h2 class="grow">Declared before looking</h2><span class="muted small">primary variable and limits</span><i class="ph ph-caret-down ab-caret"></i></summary>
          <div class="ab-prose">${blocksHtml(primary.blocks)}</div></details>
        <details class="panel fold"><summary class="panel-head"><i class="ph-duotone ph-target ab-ic"></i><h2 class="grow">Success criterion</h2><span class="muted small">${listOf(success).length} checks</span><i class="ph ph-caret-down ab-caret"></i></summary>
          ${parasOf(success).map((p) => `<p class="ab-prose-p">${md(p)}</p>`).join("")}
          <ul class="ab-checks">${listOf(success).map((x) => `<li><i class="ph-duotone ph-check-circle"></i><span>${md(x)}</span></li>`).join("")}</ul></details>
      </div>
    </div>
  </section>`;
}

// ---- 2. architecture ----
function architectureHtml(a) {
  const views = tableOf(sec(a, "Four views"));
  return `<section class="ab-sec" aria-labelledby="ab-arch">
    <header class="ab-sec-head"><h2 id="ab-arch">System architecture</h2><p>${md(parasOf(sec(a, "In one picture")).join(" "))}</p></header>
    <div class="panel ab-arch">
      <div class="ab-mission"><i class="ph-duotone ph-compass"></i><span><b>Mission.</b> ${md(plain(rowsBy(sec(a, "Digital twin system components")).Mission?.["In our prototype"] || ""))}</span>
        <span class="ab-hint"><i class="ph-duotone ph-cursor-click"></i>Select a step, track or component</span></div>
      <div class="ab-svg-wrap">${diagramSvg()}</div>
      <div class="ab-detail" id="abDetail" aria-live="polite"></div>
    </div>
    <details class="panel fold ab-views">
      <summary class="panel-head"><i class="ph-duotone ph-eye ab-ic"></i><h2 class="grow">Four views of the same system</h2><span class="muted small">TU/e digital twin system lecture</span><i class="ph ph-caret-down ab-caret"></i></summary>
      <div class="ab-views-grid">${views.rows.map(([v, who, what, where]) => `
        <div class="ab-view"><div class="ab-view-h"><i class="ph-duotone ${VIEW_ICON[v] || "ph-eye"}"></i><b>${esc(v)} view</b></div>
          <div class="ab-view-who">${md(who)}</div><p>${md(what)}</p><div class="ab-view-where"><i class="ph-duotone ph-map-pin-line"></i>${md(where)}</div></div>`).join("")}
      </div>
    </details>
  </section>`;
}

function diagramSvg() {
  const { NY, NH, BY, DDY, LY, LH, HX, W, H } = G;
  const out = [];
  out.push(`<svg class="ab-svg" viewBox="0 0 ${W} ${H}" role="group" aria-label="Architecture diagram: data flow, digital twin system components and the four tracks">
    <defs><marker id="abArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="ab-ah" d="M0,1 L9,5 L0,9 z"/></marker>
    <marker id="abArrowA" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="ab-ah acc" d="M0,1 L9,5 L0,9 z"/></marker></defs>`);

  // column backgrounds (click targets for a whole step)
  STEPS.forEach((s, i) => out.push(`<rect class="ab-colbg" data-col="${i}" x="${colX(i) - 6}" y="${NY - 10}" width="${G.COL + 12}" height="${H - NY + 4}" rx="12"/>`));

  // loop: next measurement goes back to the scanner
  const lx1 = colC(6), lx0 = colC(0), ly = 22;
  out.push(`<path class="ab-loop" d="M${lx1},${NY - 2} V${ly + 10} Q${lx1},${ly} ${lx1 - 10},${ly} H${lx0 + 10} Q${lx0},${ly} ${lx0},${ly + 10} V${NY - 4}" marker-end="url(#abArrowA)"/>`);
  const mid = (lx0 + lx1) / 2;
  out.push(`<rect class="ab-loop-bg" x="${mid - 162}" y="${ly - 10}" width="324" height="20" rx="6"/>
    <text class="ab-loop-t" x="${mid}" y="${ly + 4}" text-anchor="middle">the next measurement goes back to the scanner</text>`);

  // flow nodes + arrows
  STEPS.forEach((s, i) => {
    const x = colX(i);
    out.push(`<g class="ab-node" data-col="${i}" tabindex="0" role="button" aria-label="${esc(s.step)}">
      <rect x="${x}" y="${NY}" width="${G.COL}" height="${NH}" rx="10"/>
      <text class="ab-node-t" x="${x + 12}" y="${NY + 24}">${esc(s.step)}</text>
      <text class="ab-node-s" x="${x + 12}" y="${NY + NH - 14}">${esc(s.short)}</text>`);
    if (s.layers) {
      const sw = (G.COL - 24 - 5 * 3) / 6;
      for (let k = 0; k < 6; k++) out.push(`<rect class="ab-layer" x="${x + 12 + k * (sw + 3)}" y="${NY + 38}" width="${sw}" height="12" rx="3"/>`);
    }
    out.push(`</g>`);
    if (i < STEPS.length - 1) out.push(`<line class="ab-flow" data-col="${i}" x1="${x + G.COL + 1}" y1="${NY + NH / 2}" x2="${colX(i + 1) - 2}" y2="${NY + NH / 2}" marker-end="url(#abArrow)"/>`);
  });

  // DTS component brackets
  const groups = [];
  STEPS.forEach((s, i) => { const g = groups[groups.length - 1]; if (g && g.dts === s.dts) g.to = i; else groups.push({ dts: s.dts, from: i, to: i }); });
  groups.forEach((g) => {
    const x0 = colX(g.from) + 4, x1 = colX(g.to) + G.COL - 4;
    out.push(`<g class="ab-dts" data-dts="${g.dts}" tabindex="0" role="button" aria-label="Component ${g.dts}">
      <path class="ab-br" d="M${x0},${BY} v8 H${x1} v-8"/>
      <rect class="ab-dts-chip" x="${(x0 + x1) / 2 - 17}" y="${BY + 15}" width="34" height="19" rx="5"/>
      <text class="ab-dts-t" x="${(x0 + x1) / 2}" y="${BY + 28.5}" text-anchor="middle">${g.dts}</text></g>`);
  });

  // DD band + provenance walk-back
  const dx0 = colX(1), dx1 = colX(6) + G.COL, px = colX(0) + 22;   // px: clear of the PT chip
  out.push(`<g class="ab-dd" data-dts="DD" tabindex="0" role="button" aria-label="Component DD, digital twin data and provenance">
    <rect x="${dx0}" y="${DDY + 4}" width="${dx1 - dx0}" height="28" rx="8"/>
    <text class="ab-dd-t" x="${dx0 + 12}" y="${DDY + 22}"><tspan class="ab-dd-code">DD</tspan>  packets, append-only event log, provenance trail</text>
    <text class="ab-dd-s" x="${dx1 - 12}" y="${DDY + 22}" text-anchor="end">provenance walks back to the file</text>
    <path class="ab-prov" d="M${dx0},${DDY + 18} H${px + 10} Q${px},${DDY + 18} ${px},${DDY + 8} V${NY + NH + 4}" marker-end="url(#abArrow)"/></g>`);

  // swimlanes
  out.push(`<text class="ab-hand-h" x="${HX}" y="${LY - 4}">hands over</text>`);
  LANES.forEach((l, r) => {
    const y = LY + r * LH;
    out.push(`<line class="ab-lane-sep" x1="0" x2="${W}" y1="${y}" y2="${y}"/>`);
    out.push(`<g class="ab-lane" data-lane="${r}" tabindex="0" role="button" aria-label="Track ${esc(l.track)}">
      <rect class="ab-lane-hit" x="0" y="${y + 2}" width="${G.X0 - 16}" height="${LH - 4}" rx="8"/>
      <rect class="ab-code" x="6" y="${y + 15}" width="30" height="20" rx="5"/><text class="ab-code-t" x="21" y="${y + 29}" text-anchor="middle">${l.code}</text>
      <text class="ab-lane-t" x="44" y="${y + 24}">${esc(l.name)}</text><text class="ab-lane-q" x="44" y="${y + 40}">${esc(l.q)}</text></g>`);
    Object.entries(l.cells).forEach(([i, txt]) => {
      const w = Math.min(G.COL - 8, txt.length * 6.1 + 20);
      out.push(`<g class="ab-cell" data-col="${i}" data-row="${r}"><rect x="${colC(+i) - w / 2}" y="${y + 15}" width="${w}" height="24" rx="6"/>
        <text x="${colC(+i)}" y="${y + 31}" text-anchor="middle">${esc(txt)}</text></g>`);
    });
    out.push(`<text class="ab-hand" data-lane="${r}" x="${HX + 16}" y="${y + 31}">${esc(l.hands)}</text>`);
    if (r < LANES.length - 1) out.push(`<line class="ab-hand-a" x1="${HX + 5}" y1="${y + 36}" x2="${HX + 5}" y2="${y + LH + 18}" marker-end="url(#abArrow)"/>`);
  });
  const yTop = LY + 27, yBot = LY + (LANES.length - 1) * LH + 27;
  out.push(`<path class="ab-hand-a" d="M${W - 30},${yBot} H${W - 12} V${yTop} H${W - 26}" marker-end="url(#abArrow)"/>`);
  out.push(`</svg>`);
  return out.join("");
}

function wireDiagram(root, d) {
  const a = d.architecture;
  const flow = rowsBy(sec(a, "Data flow"));
  const dts = rowsBy(sec(a, "Digital twin system components"));
  const tracks = rowsBy(sec(a, "Tracks and their handover artifacts"));
  const svg = root.querySelector(".ab-svg");
  const box = root.querySelector("#abDetail");
  const modChips = (s) => codes(s).map((c) => `<code class="ab-mod">${esc(c)}</code>`).join(" ");

  function owners(i) {
    return LANES.filter((l) => l.cells[i] !== undefined)
      .map((l) => `<span class="chip owner" title="${esc(l.track)}">${l.code}</span><span class="ab-own-t">${esc(l.cells[i])}</span>`).join("");
  }

  function show(kind, key) {
    svg.querySelectorAll(".on").forEach((n) => n.classList.remove("on"));
    svg.classList.toggle("has-sel", true);
    if (kind === "col") {
      const s = STEPS[key], f = flow[s.step] || {}, comp = dts[s.dts] || {};
      svg.querySelectorAll(`[data-col="${key}"]`).forEach((n) => n.classList.add("on"));
      svg.querySelectorAll(`.ab-dts[data-dts="${s.dts}"]`).forEach((n) => n.classList.add("on"));
      const layers = s.layers ? `<ol class="ab-layers">${d.layers.map((l) => `<li><code>${esc(l.id)}</code>${esc(l.title)}</li>`).join("")}</ol>` : "";
      box.innerHTML = `<div class="ab-d-main"><div class="ab-d-h"><span class="ab-d-n mono">${key + 1}/${STEPS.length}</span><h3>${esc(s.step)}</h3></div>
          <p>${md(f["What happens"] || "")}</p>${layers}</div>
        <div class="ab-d-side"><dl>
          <dt>Modules</dt><dd>${modChips(f.Modules || "") || md(f.Modules || "")}</dd>
          <dt>Output</dt><dd>${md(f.Output || "")}</dd>
          <dt>Component</dt><dd><span class="chip accent">${esc(s.dts)}</span> ${esc(comp.Component || "")}. ${md(comp["In our prototype"] || "")}</dd>
          <dt>Tracks</dt><dd class="ab-owners">${owners(key) || "<span class='muted'>none</span>"}</dd></dl></div>`;
    } else if (kind === "dts") {
      const comp = dts[key] || {};
      svg.querySelectorAll(`[data-dts="${key}"]`).forEach((n) => n.classList.add("on"));
      STEPS.forEach((s, i) => { if (s.dts === key) svg.querySelectorAll(`.ab-node[data-col="${i}"]`).forEach((n) => n.classList.add("on")); });
      const prov = key === "DD" ? flow.Provenance : null;
      box.innerHTML = `<div class="ab-d-main"><div class="ab-d-h"><span class="chip accent">${esc(key)}</span><h3>${esc(comp.Component || key)}</h3></div>
          <p>${md(comp["In our prototype"] || "")}</p>${prov ? `<p><b>Provenance.</b> ${md(prov["What happens"])}</p>` : ""}</div>
        <div class="ab-d-side"><dl><dt>Modules</dt><dd>${modChips(comp.Modules || "") || md(comp.Modules || "")}${prov ? " " + modChips(prov.Modules) : ""}</dd>
          <dt>Source</dt><dd>TU/e lecture, digital twin system components (dossier section 7.9)</dd></dl></div>`;
    } else {
      const l = LANES[key], t = tracks[l.track] || {};
      svg.querySelectorAll(`[data-lane="${key}"], .ab-cell[data-row="${key}"]`).forEach((n) => n.classList.add("on"));
      box.innerHTML = `<div class="ab-d-main"><div class="ab-d-h"><span class="chip owner">${l.code}</span><h3>${esc(l.track)}</h3></div>
          <p><b>${md(t.Question || l.q)}</b></p><p>${md(t["Owns in the code"] || "")}</p></div>
        <div class="ab-d-side"><dl><dt>Hands over</dt><dd>${md(t["Hands over to"] || l.hands)}</dd>
          <dt>Steps it owns</dt><dd class="ab-owners">${Object.entries(l.cells).map(([i, txt]) => `<span class="ab-own-t"><b>${esc(STEPS[i].step)}</b> ${esc(txt)}</span>`).join("")}</dd></dl></div>`;
    }
  }

  const pick = (el) => {
    if (el.dataset.lane !== undefined) show("lane", +el.dataset.lane);
    else if (el.dataset.dts !== undefined) show("dts", el.dataset.dts);
    else if (el.dataset.col !== undefined) show("col", +el.dataset.col);
  };
  svg.addEventListener("click", (e) => {
    const el = e.target.closest(".ab-lane, .ab-dts, .ab-dd, .ab-node, .ab-cell, .ab-colbg, .ab-hand");
    if (el) pick(el);
  });
  svg.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("[role=button]")) { e.preventDefault(); pick(e.target); }
  });
  show("col", 2);
}

// ---- 3. limits and ethics ----
const STATUS_CLASS = (s) => (/proposal/i.test(s) ? "WARN" : /declared/i.test(s) ? "accent" : "neutral");

function limitsHtml(l) {
  const statement = parasOf(sec(l, "Short limitations statement")).join(" ");
  const domain = tableOf(sec(l, "Validation domain"));
  const domainNote = parasOf(sec(l, "Validation domain"));
  const assum = tableOf(sec(l, "Teaching assumptions and declared policies"));
  const epi = listOf(sec(l, "Epistemic labels"));
  const open = listOf(sec(l, "Open items"));
  return `<section class="ab-sec" aria-labelledby="ab-lim">
    <header class="ab-sec-head"><h2 id="ab-lim">Limits and ethics</h2><p>${md(statement)}</p></header>
    <div class="grid g-primary">
      <div class="panel"><div class="panel-head"><i class="ph-duotone ph-crosshair ab-ic"></i><h2 class="grow">Validation domain</h2></div>
        ${domainNote[0] ? `<p class="ab-prose-p">${md(domainNote[0])}</p>` : ""}
        <div class="ab-dom ab-dom-h"><div>${esc(domain.header[0] || "")}</div><div>${esc(domain.header[1] || "")}</div><div>${esc(domain.header[2] || "")}</div></div>
        ${domain.rows.map(([c, v, o]) => `<div class="ab-dom"><div class="ab-dom-c">${md(c)}</div><div class="ab-dom-v">${md(v)}</div><div class="ab-dom-o">${md(o)}</div></div>`).join("")}
      </div>
      <div class="stack">
        <div class="ab-stamp" role="note"><i class="ph-duotone ph-shield-warning"></i>
          <div><div class="ab-stamp-k">Outside this domain the twin answers</div><div class="ab-stamp-v">not validated for this condition</div>
          ${domainNote[1] ? `<p>${md(domainNote[1])}</p>` : ""}</div></div>
        <details class="panel fold"><summary class="panel-head"><i class="ph-duotone ph-list-magnifying-glass ab-ic"></i><h2 class="grow">Open items</h2><span class="muted small">${open.length} items</span><i class="ph ph-caret-down ab-caret"></i></summary>
          <ul class="ab-list">${open.map((x) => `<li>${md(x)}</li>`).join("")}</ul></details>
      </div>
    </div>
    <details class="panel fold" style="margin-top:16px"><summary class="panel-head"><i class="ph-duotone ph-shield-check ab-ic"></i><h2 class="grow">Data, privacy, bias and use of AI</h2><span class="muted small">${ETHICS.length} statements</span><i class="ph ph-caret-down ab-caret"></i></summary>
    <div class="ab-ethics">${ETHICS.map((e) => {
      const s = sec(l, e.title);
      return `<div class="panel ab-eth${e.tall ? " tall" : ""}"><div class="ab-eth-h"><i class="ph-duotone ${e.icon}"></i><h3>${esc(e.title)}</h3></div>${blocksHtml(s.blocks)}</div>`;
    }).join("")}</div></details>
    <div class="grid g-primary ab-top" style="margin-top:16px">
      <div class="panel"><div class="panel-head"><i class="ph-duotone ph-flag ab-ic"></i><h2 class="grow">Teaching assumptions and declared policies</h2></div>
        <p class="ab-prose-p">Every choice that is not physics is marked here, so it can be questioned and replaced.</p>
        ${assum.rows.map(([item, val, status, where]) => `<div class="ab-as">
          <div><div class="ab-as-i">${md(item)}</div><div class="ab-as-v">${md(val)}</div></div>
          <div><span class="chip ${STATUS_CLASS(status)}" title="${esc(plain(status))}">${esc(plain(status).split(/[,;(]/)[0].trim())}</span></div>
          <div class="ab-as-w">${md(where)}</div></div>`).join("")}
      </div>
      <details class="panel fold"><summary class="panel-head"><i class="ph-duotone ph-identification-badge ab-ic"></i><h2 class="grow">Epistemic labels</h2><span class="muted small">${epi.length} labels</span><i class="ph ph-caret-down ab-caret"></i></summary>
        <div class="ab-epi">${epi.map((x) => { const [k, ...rest] = x.split(":"); const txt = rest.join(":").trim(); return `<div><span class="chip neutral mono">${esc(k)}</span><p>${md(txt.charAt(0).toUpperCase() + txt.slice(1))}</p></div>`; }).join("")}</div>
        ${parasOf(sec(l, "Epistemic labels")).map((p) => `<p class="ab-prose-p" style="margin-top:12px">${md(p)}</p>`).join("")}
      </details>
    </div>
  </section>`;
}

// ---- 4. twin data dictionary ----
function dictionaryHtml(d) {
  const groups = d.dictionary_groups;
  return `<section class="ab-sec" aria-labelledby="ab-dict">
    <details class="panel fold ab-dict">
      <summary class="panel-head"><i class="ph-duotone ph-database ab-ic"></i><h2 class="grow" id="ab-dict">Twin data dictionary</h2><span class="muted small">${d.dictionary.length} fields the twin writes</span><i class="ph ph-caret-down ab-caret"></i></summary>
      <p class="ab-prose-p">Every field with its type, unit, owner track and epistemic label. A regression test fails if this list names a field the code does not produce.</p>
      <div class="ab-dict-bar">
        <label class="field ab-search"><span>Search fields</span>
          <span class="ab-search-box"><i class="ph-duotone ph-magnifying-glass"></i><input type="text" id="abQ" placeholder="for example K, sha256, Metrology" autocomplete="off"></span></label>
        <div class="ab-tabs" role="tablist" aria-label="Field groups">${groups.map((g, i) => `
          <button class="ab-tab${i === 0 ? " sel" : ""}" role="tab" aria-selected="${i === 0}" data-g="${esc(g.id)}">${esc(g.title)}<span class="mono">${g.count}</span></button>`).join("")}</div>
      </div>
      <div id="abDictBody"></div>
    </details>
  </section>`;
}

function wireDictionary(root, d) {
  const body = root.querySelector("#abDictBody");
  const q = root.querySelector("#abQ");
  const tabs = root.querySelectorAll(".ab-tab");
  let group = d.dictionary_groups[0]?.id;
  const titles = Object.fromEntries(d.dictionary_groups.map((g) => [g.id, g]));

  const row = (r) => {
    const [pre, rest] = [r.field.split(".")[0], r.field.split(".").slice(1).join(".")];
    const code = OWNER_CODE[r.owner] || r.owner;
    return `<div class="ab-f">
      <div class="ab-f-name mono"><span class="ab-f-pre">${esc(pre)}.</span>${esc(rest)}</div>
      <div class="ab-f-type"><span class="mono">${esc(r.type)}</span>${r.unit ? `<span class="ab-f-unit">${esc(r.unit)}</span>` : ""}</div>
      <div class="ab-f-own"><span class="chip owner" title="${esc(r.owner)}">${esc(code)}</span>${r.epistemic ? `<span class="chip neutral ab-epi-chip">${esc(r.epistemic)}</span>` : ""}</div>
      <div class="ab-f-m">${esc(r.meaning)}</div></div>`;
  };
  const head = `<div class="ab-f ab-f-head"><div>Field</div><div>Type and unit</div><div>Owner and label</div><div>Meaning</div></div>`;

  function draw() {
    const term = q.value.trim().toLowerCase();
    if (term) {
      const hits = d.dictionary.filter((r) => Object.values(r).join(" ").toLowerCase().includes(term));
      tabs.forEach((t) => { t.classList.remove("sel"); t.setAttribute("aria-selected", "false"); });
      if (!hits.length) { body.innerHTML = `<div class="empty">No field matches "${esc(q.value)}". Try a name such as <span class="mono">posterior</span> or an owner such as <span class="mono">Data Science</span>.</div>`; return; }
      const byG = {};
      hits.forEach((r) => (byG[r.group] = byG[r.group] || []).push(r));
      body.innerHTML = `<div class="ab-count muted small">${hits.length} of ${d.dictionary.length} fields</div>` +
        Object.entries(byG).map(([g, rs]) => `<div class="ab-g-h"><b>${esc(titles[g]?.title || g)}</b><span>${esc(titles[g]?.description || "")}</span></div>${head}${rs.map(row).join("")}`).join("");
      return;
    }
    tabs.forEach((t) => { const on = t.dataset.g === group; t.classList.toggle("sel", on); t.setAttribute("aria-selected", String(on)); });
    const rs = d.dictionary.filter((r) => r.group === group);
    body.innerHTML = `<div class="ab-g-h"><span>${esc(titles[group]?.description || "")}</span></div>${head}${rs.map(row).join("")}`;
  }
  tabs.forEach((t) => t.addEventListener("click", () => { group = t.dataset.g; q.value = ""; draw(); }));
  q.addEventListener("input", draw);
  draw();
}
