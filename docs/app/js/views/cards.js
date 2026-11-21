// Views: measurement card + uncertainty card + data dictionary, and the live regression-test runner.
import { api, esc, fmt, pct, toast } from "../core.js";

export async function renderCards(root) {
  root.innerHTML = `<div class="view"><h1>Measurement cards</h1><div class="skeleton" style="height:420px"></div></div>`;
  let c;
  try { c = await api.get("/api/cards"); } catch (err) { toast(err.message, true); return; }
  const m = c.measurement, b = c.budget;
  const list = (xs) => `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  root.innerHTML = `<div class="view">
    <h1>Measurement cards</h1>
    <p class="lede">What the number means (Quantum Engineering) and how sure we are of it (Precision Mechanics / Metrology), for the primary variable Cho/Cr.</p>
    <div class="grid g-2">
      <section class="panel"><div class="panel-head"><i class="ph ph-atom"></i><h2 class="grow">Measurement card: ${esc(m.name)}</h2></div>
        <dl class="card-list">
          <dt>Meaning</dt><dd>${esc(m.physical_meaning)}</dd>
          <dt>How measured</dt><dd>${esc(m.how_measured)}</dd>
          <dt>Unit and range</dt><dd class="mono">${esc(m.unit)}, valid ${esc(JSON.stringify(m.valid_range))}</dd>
          <dt>Why a ratio</dt><dd>${esc(m.why_a_ratio)}</dd>
          <dt>Where</dt><dd>${esc(m.spatial_support)}</dd>
          <dt>Quality checks</dt><dd>${list(m.quality_indicators)}</dd>
          <dt>Cannot tell</dt><dd>${list(m.cannot_tell)}</dd>
          <dt>Failure modes</dt><dd>${list(m.failure_modes)}</dd>
        </dl>
        <h3 style="margin:18px 0 10px">From spins to belief</h3>
        <div class="chain">${m.chain.map((x) => `<div>${esc(x)}</div>`).join("")}</div>
      </section>
      <section class="panel"><div class="panel-head"><i class="ph ph-ruler"></i><h2 class="grow">Uncertainty card: follow-up Cho/Cr</h2></div>
        <div class="bigvalue" style="margin-bottom:6px"><span class="v">${fmt(b.u_combined, 3)}</span><span class="pm">combined SD</span><span class="from">packet states ${fmt(b.u_packet, 2)}</span></div>
        <div class="small muted" style="margin-bottom:10px">${esc(b.rule)}</div>
        <div class="budget-row" style="color:var(--text-3);font-size:12px;border-top:0"><div>Source</div><div>u</div><div>Share of variance</div><div></div></div>
        ${b.rows.map((r) => `<div class="budget-row ${r.source === b.dominant ? "dom" : ""}"><div>${esc(r.source)}<div class="small muted">fix: ${esc(r.fix)}</div></div>
          <div class="num">${fmt(r.u, 3)}</div><div><div class="bar" style="width:${(r.share * 100).toFixed(0)}%"></div></div><div class="num small">${pct(r.share)}</div></div>`).join("")}
        <div class="note" style="margin-top:14px"><i class="ph ph-lightbulb"></i><div>${esc(b.lesson)}</div></div>
      </section>
    </div>
    <section class="panel" style="margin-top:16px"><div class="panel-head"><i class="ph ph-database"></i><h2 class="grow">Data dictionary</h2><span class="muted small">every field has a unit, an owner and an epistemic label</span></div>
      <div style="overflow-x:auto"><table class="dict"><thead><tr><th>Field</th><th>Type</th><th>Unit</th><th>Owner</th><th>Label</th><th>Meaning</th></tr></thead>
      <tbody>${c.dictionary.map((r) => `<tr><td>${esc(r.field)}</td><td>${esc(r.type)}</td><td class="mono">${esc(r.unit)}</td><td>${esc(r.owner)}</td><td>${esc(r.epistemic)}</td><td>${esc(r.meaning)}</td></tr>`).join("")}</tbody></table></div>
    </section></div>`;
}

// The last run is kept in the browser, so the page shows a result at once instead of a 40-second wait.
const TESTS_KEY = "larmor-tests-last";
function readLastRun() {
  try { const r = JSON.parse(localStorage.getItem(TESTS_KEY)); return r && Array.isArray(r.tests) ? r : null; } catch (e) { return null; }
}
function saveLastRun(r) {
  try { localStorage.setItem(TESTS_KEY, JSON.stringify(r)); } catch (e) { /* storage unavailable: the result still shows for this visit */ }
}

export function renderTests(root) {
  root.innerHTML = `<div class="view">
    <h1>Regression tests</h1>
    <p class="lede">The dossier's worked numbers, the cross-team checks of section 8.7 and every practice packet, run against the real engine.</p>
    <div class="toolbar"><button class="btn primary" data-run><i class="ph ph-play"></i>Run all tests</button><span class="muted small" data-sum></span></div>
    <section class="panel"><div data-out><div class="empty">No stored result yet. Press "Run all tests". It takes about 40 seconds.</div></div></section></div>`;
  const btn = root.querySelector("[data-run]");
  const pretty = (n) => n.replace(/^test_/, "").replace(/-expected\d+\]$/, "]").replace(/\[(.*)\]$/, ": $1").replaceAll("_", " ");
  const show = (r) => {
    root.querySelector("[data-sum]").textContent = `${r.summary}, last run ${r.at}`;
    root.querySelector("[data-out]").innerHTML = `<div class="tests">${r.tests.map((t) => `<div class="test ${esc(t.status)}"><i class="ph-fill ${t.status === "PASSED" ? "ph-check-circle" : "ph-x-circle"}"></i>${esc(pretty(t.name))}</div>`).join("")}</div>`;
  };
  const stored = readLastRun();
  if (stored) show(stored);
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    root.querySelector("[data-sum]").textContent = "running, about 40 seconds";
    root.querySelector("[data-out]").innerHTML = `<div class="skeleton" style="height:260px"></div>`;
    try {
      const r = await api.post("/api/tests");
      const at = new Date().toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      const run = { summary: r.summary, tests: r.tests, at };
      saveLastRun(run);
      show(run);
    } catch (err) {
      toast(err.message, true);
      const prev = readLastRun();
      if (prev) show(prev); else root.querySelector("[data-out]").innerHTML = `<div class="empty">The test run failed: ${esc(err.message)}</div>`;
    }
    btn.disabled = false;
  });
}
