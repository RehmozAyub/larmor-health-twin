// View: provenance. Click a twin variable, walk back to the source files, with live SHA-256 verification.
import { api, esc, label, store, toast } from "../core.js";
import { provenanceGraph } from "../charts.js";

let selected = "Cho_Cr";

export async function render(root) {
  const vars = Object.keys(store.state.variables);
  if (!vars.length) {
    root.innerHTML = `<div class="view"><h1>Trace to source</h1><div class="empty">The twin has no variables yet. Run the update on the Twin state page first.</div></div>`;
    return;
  }
  if (!vars.includes(selected)) selected = vars[0];
  let trace;
  try { trace = await api.get(`/api/provenance/${encodeURIComponent(selected)}`); } catch (err) { toast(err.message, true); return; }
  root.innerHTML = `<div class="view">
    <h1>Trace to source</h1>
    <p class="lede">Every number in the twin can be walked back to the file it came from. The file's fingerprint (SHA-256) is recomputed live and compared with the StarterPack manifest.</p>
    <div class="row" style="margin-bottom:14px">${vars.map((v) => `<button class="btn ${v === selected ? "primary" : ""}" data-var="${esc(v)}">${esc(label(v))}</button>`).join("")}</div>
    <section class="panel"><div class="panel-head"><i class="ph ph-tree-structure"></i><h2 class="grow">Provenance of ${esc(label(selected))}</h2><span class="muted small">click a box for details</span></div>
      <div class="prov-wrap">${provenanceGraph(trace)}</div>
      <div class="detail" data-detail>Select a node.</div>
      <p class="small muted" style="margin:10px 0 0">A matching fingerprint proves the file bytes are unchanged. It says nothing about whether the physics is right; that is what the quality checks are for.</p>
    </section></div>`;
  root.querySelectorAll("[data-var]").forEach((b) => b.addEventListener("click", () => { selected = b.dataset.var; render(root); }));
  const byId = Object.fromEntries(trace.nodes.map((n) => [n.id, n]));
  const show = (id) => {
    const n = byId[id];
    root.querySelector("[data-detail]").innerHTML = `<b>${esc(n.label)}</b><br>${esc(n.detail || "")}
      ${n.path ? `<br>path: <span class="mono">${esc(n.path)}</span>` : ""}
      ${n.sha256 ? `<br>SHA-256: <span class="mono">${esc(n.sha256)}</span> ${n.verified ? "(matches manifest)" : "(not verified)"}` : ""}`;
  };
  root.querySelectorAll("g.node").forEach((g) => {
    g.addEventListener("click", () => show(g.dataset.id));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(g.dataset.id); } });
  });
  const st = trace.nodes.find((n) => n.kind === "state");
  if (st) show(st.id);
}
