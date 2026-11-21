// Views: competing explanations, and what to measure next (prediction + ranked actions).
// All text on these pages is computed by the engine from the current state (planner.py, explain.py).
// Every new field is optional, so the page still renders against an older server.
import { esc, fmt, label, store } from "../core.js";
import { trajectoryChart } from "../charts.js";

const VCLASS = { supported: "v-supported", possible: "v-possible", investigate: "v-supported" };
const VICON = { supported: "ph-warning", possible: "ph-question", investigate: "ph-warning-octagon", "not supported": "ph-minus-circle", unlikely: "ph-minus-circle", "cannot be excluded": "ph-question" };
const FLAG_TEXT = { model_disagreement: "Model disagreement" };

// "What changed since the last evidence": one line, computed by the planner.
function sinceLast(nx) {
  const sl = nx?.since_last;
  if (!sl?.text) return "";
  return `<div class="note" style="margin-bottom:16px"><i class="ph ph-clock-counter-clockwise"></i><div><b>Since the last evidence.</b> ${esc(sl.text)}</div></div>`;
}

// Open flags: shown in the warning colour, with what to do about them.
function flagNotes(flags) {
  return (flags || []).map((f) => `<div class="note" style="margin-bottom:12px;background:var(--warn-soft)"><i class="ph ph-warning-octagon" style="color:var(--warn)"></i><div><b>${esc(FLAG_TEXT[f.flag] || f.flag)}</b>, event #${esc(f.event_id)}. ${esc(f.text)}</div></div>`).join("");
}

export function renderExplain(root) {
  const s = store.state;
  const ex = s.explanations || {};
  const vars = ["Cho_Cr", "NAA_Cr", "roi_volume"].filter((v) => ex[v]);
  const primary = store.meta?.primary || "Cho_Cr";
  const supported = (v) => ex[v].rows.filter((r) => r.verdict === "supported").length;
  root.innerHTML = `<div class="view">
    <h1>Competing explanations</h1>
    <p class="lede">A difference between two scans can come from real change, from the measurement, or from processing. The twin does not pick a winner. It judges each reason against all the evidence it holds, and names the test that would separate them.</p>
    ${flagNotes(s.next?.open_flags)}
    ${vars.length ? vars.map((v) => `<details class="panel fold" style="margin-bottom:16px"${v === primary ? " open" : ""}>
      <summary class="panel-head"><i class="ph ph-scales"></i><h2 class="grow">${esc(label(v))}${v === primary ? "" : ` <span class="muted small" style="font-weight:400">secondary, ${supported(v)} supported</span>`}</h2><span class="muted small">${v === primary ? esc(ex[v].note) : "show"}</span></summary>
      ${ex[v].summary ? `<p class="small muted" style="margin:0 0 8px">${esc(ex[v].summary)}</p>` : ""}
      <div class="hyp" style="color:var(--text-3);font-size:12px;padding-top:0"><div>Explanation</div><div>Verdict</div><div>Evidence</div><div>Test that would separate it</div></div>
      ${ex[v].rows.map((r) => `<div class="hyp"><div class="name">${esc(r.hypothesis)}</div>
        <div class="${VCLASS[r.verdict] || "v-not"}"><i class="ph ${VICON[r.verdict] || "ph-circle"}"></i> ${esc(r.verdict)}</div>
        <div class="ev">${esc(r.evidence)}</div><div class="test"><i class="ph ph-crosshair"></i><span>${esc(r.discriminating_test)}</span></div></div>`).join("")}
    </details>`).join("") : `<div class="empty">No follow-up evidence yet, so there is no change to explain.</div>`}
  </div>`;
}

function stateChip(st) {
  const map = { open: ["WARN", "open"], watch: ["INFO", "watch"], settled: ["PASS", "settled"], baseline_only: ["INFO", "baseline only"] };
  const [cls, text] = map[st] || ["INFO", st];
  return `<span class="chip ${cls}">${esc(text)}</span>`;
}

function variableStatus(nx) {
  const vs = nx?.variables || [];
  if (!vs.length) return "";
  return `<details class="panel fold" style="margin-top:16px"><summary class="panel-head"><i class="ph ph-list-checks"></i><h2 class="grow">Where each variable stands</h2><span class="muted small">good enough = SD below the declared target</span></summary>
    ${vs.map((a, i) => `<div style="padding:12px 0;${i ? "border-top:1px solid var(--line)" : ""}"><div><b>${esc(a.label)}</b> ${stateChip(a.state)}
      <span class="small muted num" style="margin-left:8px">SD ${fmt(a.sd, a.sd >= 100 ? 0 : 3)}${a.target_sd ? `, target ${fmt(a.target_sd, a.target_sd >= 100 ? 0 : 3)}` : ""}</span></div>
      <div class="small muted" style="margin-top:4px">${esc(a.summary)}</div>
      ${a.target_why ? `<div class="small muted" style="margin-top:2px">Target: ${esc(a.target_why)}.</div>` : ""}</div>`).join("")}
  </details>`;
}

export function renderNext(root) {
  const s = store.state;
  const nx = s.next;
  const pred = s.predictions?.Cho_Cr;
  const ranked = nx.ranked;
  const maxGain = Math.max(...ranked.map((r) => r.gain_per_min || 0), 1e-12);
  const hasNeed = ranked.some((r) => r.needed_now !== undefined);
  root.innerHTML = `<div class="view">
    <h1>What to measure next</h1>
    <p class="lede">${esc(nx.principle)}</p>
    ${sinceLast(nx)}
    ${flagNotes(nx.open_flags)}
    <div class="grid g-primary">
      <section class="panel"><div class="panel-head"><i class="ph ph-chart-line"></i><h2 class="grow">Cho/Cr belief over time</h2></div>
        ${trajectoryChart(s.events, "Cho_Cr", pred, { aria: "Cho/Cr observations, twin belief and expected repeat range" }) || '<div class="empty">No evidence yet.</div>'}
        <div class="legend"><span style="color:var(--pass)"><i class="sw" style="background:var(--pass)"></i>PASS observation, 95 % bar</span><span style="color:var(--warn)"><i class="sw ev"></i>WARN observation</span><span style="color:var(--accent)"><i class="sw post"></i>twin belief, 95 % band</span></div>
        ${pred ? `<p class="reason">If nothing has changed, a clean repeat after re-shimming should land between <b class="mono">${fmt(pred.low, 2)}</b> and <b class="mono">${fmt(pred.high, 2)}</b> (95 %). A value outside this range would be real news.</p>` : ""}
      </section>
      <section class="panel"><div class="panel-head"><i class="ph ph-crosshair"></i><h2 class="grow">Recommendation</h2></div>
        ${nx.summary ? `<p class="small" style="margin:0 0 10px;color:var(--text-2)">${esc(nx.summary)}</p>` : ""}
        ${nx.recommended.length ? nx.recommended.map((r, i) => `<div class="recommend"><div class="n">${i + 1}</div><div><b>${esc(r.action)}</b><div class="small muted" style="margin-top:4px">${esc(r.why)}</div></div></div>`).join("")
          : `<div class="empty">${esc(nx.summary || "Ingest the follow-up first.")}</div>`}
      </section>
    </div>
    ${variableStatus(nx)}
    <section class="panel" style="margin-top:16px"><div class="panel-head"><i class="ph ph-list-numbers"></i><h2 class="grow">All candidate measurements</h2><span class="muted small">${hasNeed ? "needed now first, then uncertainty gained per scanner minute" : "uncertainty gained per scanner minute"}</span></div>
      <div class="rank head"><div></div><div>Action</div><div>Cost</div><div>SD after</div><div>Gain per minute, or what it tests</div></div>
      ${ranked.map((r, i) => `<div class="rank"${r.needed_now === false ? ' style="opacity:.6"' : ""}><div class="muted mono">${i + 1}</div>
        <div><b>${esc(r.name)}</b><div class="small muted">targets ${esc(label(r.target))}${r.removes?.length ? `, removes: ${esc(r.removes.join(", "))}` : ""}</div>
          ${r.relevance ? `<div class="small" style="margin-top:2px;color:${r.needed_now ? "var(--accent)" : "var(--text-3)"}">${esc(r.relevance)}</div>` : ""}</div>
        <div class="num">${r.cost_min ? `${fmt(r.cost_min, 1)} min` : "offline"}</div>
        <div class="num">${r.sd_after ? `${fmt(r.sd_now)} → ${fmt(r.sd_after)}` : "n/a"}</div>
        <div>${r.gain_per_min ? `<div class="bar" style="width:${(100 * r.gain_per_min / maxGain).toFixed(0)}%"></div><div class="small muted num" style="margin-top:4px">${fmt(r.gain_per_min * 1e4, 1)} × 10⁻⁴ per min</div>`
          : `<div class="bar none">no variance gain; tests ${esc((r.tests_hypotheses || []).join(", "))}</div>`}</div></div>`).join("")}
      <p class="small muted" style="margin:12px 0 0">When the competing explanation is a bias (shim, voxel shift, calibration), the action that tells explanations apart is worth doing even with zero variance gain. Actions that close nothing open are dimmed.</p>
    </section></div>`;
}
