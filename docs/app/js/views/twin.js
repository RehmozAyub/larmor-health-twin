// View: the twin's current belief, how the last update happened, and the event log.
import { actionChip, api, chip, esc, fmt, label, lastUpdate, pct, store, toast, unit } from "../core.js";
import { beliefChart } from "../charts.js";
import { heroHtml, startHero } from "../hero.js";

let heroData = null;   // spectra + reference packets do not change, so they are fetched once
async function loadHeroData() {
  if (heroData) return heroData;
  const [spec0, spec1, p0, p1] = await Promise.all([
    api.get("/api/spectrum/ses-baseline"), api.get("/api/spectrum/ses-followup"),
    api.get("/api/packet/E-t0-cho"), api.get("/api/packet/E-t1-cho")]);
  heroData = { spec0, spec1, p0: JSON.parse(p0.text), p1: JSON.parse(p1.text) };
  return heroData;
}

function heroModel(h) {
  const ev = lastUpdate("Cho_Cr");
  return {
    spec0: h.spec0, spec1: h.spec1, event: ev,
    t0: { y: h.p0.value, u: h.p0.uncertainty.value },
    t1: { y: h.p1.value, u: h.p1.uncertainty.value, checks: h.p1.qc_checks, status: h.p1.qc_status },
    verified: ev ? ev.hash_verified : false,
  };
}

const SESSIONS = [
  { id: "ses-baseline", title: "Baseline", sub: "May 2026, month 0", icon: "ph-flag" },
  { id: "ses-followup", title: "Follow-up", sub: "Nov 2026, month 6", icon: "ph-arrows-clockwise" },
  { id: "ses-repeat", title: "Repeat (registered)", sub: "Dec 2026, month 7", icon: "ph-repeat" },
];

function timeline(s) {
  const used = SESSIONS.filter((x, i) => i < 2 || s.events.some((e) => e.session_id === x.id));
  return `<div class="timeline" style="--n:${used.length}">${used.map((x) => {
    const evs = s.events.filter((e) => e.session_id === x.id);
    const chips = evs.map((e) => chip(e.type === "reject" ? "FAIL" : e.qc_status, label(e.observable))).join("");
    return `<div class="tl-node ${evs.length ? "on" : ""}">
      <div class="tl-dot"><i class="ph ${x.icon}"></i></div>
      <div class="tl-title">${x.title}</div><div class="tl-sub">${x.sub}</div>
      <div class="tl-chips">${chips || '<span class="muted small">not ingested yet</span>'}</div></div>`;
  }).join("")}</div>`;
}

function primaryPanel(s, name) {
  const v = s.variables[name];
  if (!v) return `<section class="panel"><div class="empty">No evidence for ${esc(label(name))} yet. Use "Next packet" to ingest the baseline.</div></section>`;
  const e = lastUpdate(name);
  const u = unit(name);
  if (!e) {
    return `<section class="panel"><div class="panel-head"><i class="ph ph-target"></i><h2 class="grow">${esc(label(name))} <span class="muted small">primary variable</span></h2>${chip("INFO", "baseline only")}</div>
      <div class="bigvalue"><span class="v">${fmt(v.mean)}</span><span class="pm">± ${fmt(v.sd)}</span></div>
      ${beliefChart({ posterior: { mean: v.mean, sd: v.sd } }, { aria: "baseline belief" })}
      <p class="reason">The baseline sets the starting belief. It is not the truth: it keeps its own uncertainty.</p></section>`;
  }
  const ct = e.change_test;
  return `<section class="panel">
    <div class="panel-head"><i class="ph ph-target"></i><h2 class="grow">${esc(label(name))} <span class="muted small">primary variable, declared before looking at the data</span></h2>${actionChip(e.type)}</div>
    <div class="bigvalue"><span class="v">${fmt(v.mean)}</span><span class="pm">± ${fmt(v.sd)} ${esc(u)}</span>
      <span class="from">was ${fmt(e.prior.mean)} ± ${fmt(Math.sqrt(e.prior.var))}, new evidence ${fmt(e.evidence.y)} ± ${fmt(e.evidence.u_effective)}</span></div>
    <div class="kv">
      <div><div class="k">Change test z</div><div class="val">${fmt(ct.z, 2)}<small>limit ${fmt(ct.z_crit, 2)}</small></div></div>
      <div><div class="k">Surprise d²</div><div class="val">${fmt(e.d2, 2)}<small>gate ${fmt(e.d2_gate, 2)}</small></div></div>
      <div><div class="k">Trust in evidence K</div><div class="val">${fmt(e.K, 3)}<small>${pct(e.K)}</small></div></div>
      <div><div class="k">Evidence variance</div><div class="val">×${fmt(e.evidence.R_factor, 1)}<small>${esc(e.qc_status)} policy</small></div></div>
    </div>
    ${beliefChart({ prior: { mean: e.prior.mean_minus, sd: Math.sqrt(e.prior.var_minus) },
                    evidence: { mean: e.evidence.y, sd: Math.sqrt(e.evidence.R_used) },
                    posterior: { mean: e.posterior.mean, sd: e.posterior.sd } }, { evidenceStatus: e.qc_status })}
    <div class="legend"><span><i class="sw prior"></i>prior (with 6-month drift)</span><span style="color:var(--warn)"><i class="sw ev"></i>evidence, as weighted</span><span style="color:var(--accent)"><i class="sw post"></i>posterior belief</span></div>
    <p class="reason">${esc(e.reason)}</p>
  </section>`;
}

function miniPanel(s, name) {
  const v = s.variables[name];
  if (!v) return `<div class="mini"><div class="top"><h3>${esc(label(name))}</h3>${chip("INFO", "no evidence")}</div></div>`;
  const e = lastUpdate(name);
  const held = e && e.K < 0.05;
  return `<div class="mini">
    <div class="top"><h3>${esc(label(name))}</h3>${e ? actionChip(e.type) : chip("INFO", "baseline")}</div>
    <div class="v">${fmt(v.mean, name === "roi_volume" ? 0 : 3)} <small>± ${fmt(v.sd, name === "roi_volume" ? 0 : 3)} ${esc(unit(name))}</small></div>
    ${e ? `<div class="small muted">evidence ${fmt(e.evidence.y)}, z ${fmt(e.change_test.z, 2)}, d² ${fmt(e.d2, 2)}, K ${fmt(e.K, 3)}</div>` : ""}
    ${held ? `<div class="row" style="margin-top:6px">${chip("WARN", "held: audit requested")}</div>
      <div class="small muted">The stated 4 % uncertainty was inconsistent with the 1.1 mm alignment error. With the honest ~19 % the change is not significant.</div>` : ""}
  </div>`;
}

function unknownT1() {
  return `<div class="mini"><div class="top"><h3>T1 relaxation (qMRI)</h3>${chip("INFO", "unknown")}</div>
    <div class="small muted">The T1 map was not re-acquired at follow-up. The twin keeps it unknown instead of guessing a value.</div></div>`;
}

function logPanel(s) {
  const evs = [...s.events].reverse();
  if (!evs.length) return `<div class="empty">The event log is empty. Every update, warning and rejection will appear here, append-only.</div>`;
  return `<div class="log">${evs.map((e) => `<div class="log-row ${e.event_id > store.lastEventId ? "fresh" : ""}">
    <span class="id">#${e.event_id}</span><span class="pk">${esc(e.packet_id || "unparsed")}</span>
    <span class="obs small muted">${esc(label(e.observable || ""))}</span>
    <span class="why">${esc(e.type === "reject" ? e.reason : e.reason || e.headline)}</span>${actionChip(e.type)}</div>`).join("")}</div>`;
}

export async function render(root) {
  const s = store.state;
  const factor = s.policy?.WARN?.R_factor ?? 2;
  let hero = "";
  try { hero = heroHtml(heroModel(await loadHeroData())); } catch (err) { toast(`Could not load the raw data: ${err.message}`, true); }
  root.innerHTML = `<div class="view">
    <h1>Has it changed, and how sure are we?</h1>
    <p class="lede">A digital twin of subject sub-01, scanned twice six months apart. New evidence moves the twin's belief only as far as its quality allows.</p>
    ${hero}
    <div class="toolbar">
      <button class="btn" data-act="empty"><i class="ph ph-arrow-counter-clockwise"></i>Start empty</button>
      <button class="btn" data-act="step"><i class="ph ph-play"></i>Next packet</button>
      <button class="btn primary" data-act="golden"><i class="ph ph-lightning"></i>Run full update</button>
      <span class="sep"></span>
      <label class="policy" title="Declared team policy: WARN evidence counts with this multiple of its variance. Change it and the twin replays the follow-up.">
        WARN policy <input type="range" min="1" max="4" step="0.5" value="${factor}" data-policy><output>×${fmt(factor, 1)}</output></label>
      <span class="sep"></span>
      <a class="btn ghost" href="/api/export" download="twin_audit_trail.json"><i class="ph ph-download-simple"></i>Audit trail</a>
    </div>
    <section class="panel" style="margin-bottom:16px"><div class="panel-head"><i class="ph ph-clock-counter-clockwise"></i><h2 class="grow">Sessions</h2><span class="muted small">state version ${s.version}</span></div>${timeline(s)}</section>
    <div class="grid g-primary">
      ${primaryPanel(s, "Cho_Cr")}
      <section class="panel"><div class="panel-head"><i class="ph ph-stack"></i><h2 class="grow">Other twin variables</h2></div>
        ${miniPanel(s, "NAA_Cr")}${miniPanel(s, "roi_volume")}${unknownT1()}</section>
    </div>
    <section class="panel" style="margin-top:16px"><div class="panel-head"><i class="ph ph-list-checks"></i><h2 class="grow">Event log</h2><span class="muted small">append-only, newest first</span></div>${logPanel(s)}</section>
  </div>`;
  store.lastEventId = Math.max(0, ...s.events.map((e) => e.event_id));
  const heroEl = root.querySelector(".hero");
  if (heroData && heroEl) startHero(heroEl, heroModel(heroData));

  root.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const act = b.dataset.act;
      if (act === "step") {
        const r = await api.post("/api/step");
        store.setState(r.state);
        toast(r.result ? `${r.result.verdict.packet_id}: ${r.result.event.type.replaceAll("_", " ")}` : "All StarterPack packets are already in the twin.");
      } else {
        store.setState(await api.post("/api/reset", { mode: act }));
      }
      render(root);
    } catch (err) { toast(err.message, true); b.disabled = false; }
  }));
  const slider = root.querySelector("[data-policy]");
  slider.addEventListener("input", () => { slider.nextElementSibling.textContent = `×${(+slider.value).toFixed(1)}`; });
  slider.addEventListener("change", async () => {
    try { store.setState(await api.post("/api/policy", { warn_factor: +slider.value })); render(root); toast(`Replayed the follow-up with WARN variance ×${(+slider.value).toFixed(1)}`); }
    catch (err) { toast(err.message, true); }
  });
}
