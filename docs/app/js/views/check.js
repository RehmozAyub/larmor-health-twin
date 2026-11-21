// View: the live packet checker ("Defend" stage). Paste, drop or pick any packet; see the decision and every reason.
import { ACTION_TEXT, api, chip, esc, fmt, label, ownerChip, pct, store, toast } from "../core.js";

let current = { text: "", picked: null, result: null, applied: false };
const BIG_ICON = { PASS: "ph-check-circle", WARN: "ph-warning", FAIL: "ph-prohibit" };

function libraryHtml() {
  const groups = {};
  for (const it of store.meta.library) (groups[it.group] ||= []).push(it);
  return Object.entries(groups).map(([g, items]) => `<div class="lib-group">${esc(g)}</div>
    ${items.map((it) => `<button type="button" data-pick="${esc(it.id)}" class="${current.picked === it.id ? "sel" : ""}"><i class="ph ph-cube"></i>${esc(it.id)}</button>`).join("")}`).join("");
}

function verdictHtml() {
  const r = current.result;
  if (!r) {
    return `<div class="verdict idle"><div class="icon"><i class="ph ph-shield"></i></div>
      <div class="act">Waiting for a packet</div><div class="head">Pick one on the left, paste JSON, or drop a file. The twin is not changed until you choose to apply.</div></div>`;
  }
  const v = r.verdict;
  const ev = r.event;
  return `<div class="verdict ${esc(v.status)}"><div class="icon"><i class="ph-fill ${BIG_ICON[v.status]}"></i></div>
      <div class="act">${esc(ACTION_TEXT[v.action])}${v.packet_id ? ` <span class="muted mono small">${esc(v.packet_id)}</span>` : ""}</div>
      <div class="head">${esc(v.headline)}</div></div>
    ${ev && ev.posterior ? `<div class="note" style="margin-top:12px"><i class="ph ph-pulse"></i><div>Applied as event #${ev.event_id}. ${esc(label(ev.observable))}: ${fmt(ev.prior.mean)} → <b>${fmt(ev.posterior.mean)} ± ${fmt(ev.posterior.sd)}</b>, K = ${fmt(ev.K, 3)} (${pct(ev.K)}), d² = ${fmt(ev.d2, 2)}${ev.discrepancy ? ". <b>Model disagreement flagged</b>: the twin did not expect this value." : "."}</div></div>`
      : ev && ev.type === "reject" ? `<div class="note" style="margin-top:12px"><i class="ph ph-prohibit"></i><div>Logged as event #${ev.event_id} (rejected). The twin state did not change.</div></div>`
      : ev && ev.type === "initialize" ? `<div class="note" style="margin-top:12px"><i class="ph ph-flag"></i><div>Applied as event #${ev.event_id}: first evidence for ${esc(label(ev.observable))}, it sets the starting belief.</div></div>` : ""}
    ${sessionForm(v)}
    <div class="layers">${layersHtml(v)}</div>`;
}

function sessionForm(v) {
  const miss = v.findings.find((f) => f.check === "session" && f.status === "FAIL");
  if (!miss || !v.packet?.session_id) return "";
  return `<form class="panel" data-session style="margin-top:12px;box-shadow:none">
    <div class="panel-head"><i class="ph ph-calendar-plus"></i><h2 class="grow">Register this session?</h2></div>
    <p class="small muted" style="margin:0 0 10px">Evidence can only be linked to a session that is in the sessions table with its acquisition time. Registering is a deliberate step, never automatic.</p>
    <div class="row"><label class="field">Session<input type="text" name="sid" value="${esc(v.packet.session_id)}" readonly></label>
      <label class="field">Acquired at<input type="datetime-local" name="when" value="2027-02-20T09:00" required></label>
      <button class="btn" type="submit" style="align-self:end"><i class="ph ph-plus"></i>Register</button></div></form>`;
}

function layersHtml(v) {
  const status = (fs) => fs.reduce((w, f) => (f.status === "FAIL" ? "FAIL" : f.status === "WARN" && w !== "FAIL" ? "WARN" : w), "PASS");
  return store.meta.layers.map((L, i) => {
    const fs = v.findings.filter((f) => f.layer === L.id);
    if (!fs.length) return `<div class="layer skip" style="--i:${i}"><div class="ld"><i class="ph ph-minus"></i></div><div><div class="lt">${esc(L.title)}</div><div class="small muted">Not reached or nothing to check.</div></div></div>`;
    const st = status(fs);
    const issues = fs.filter((f) => f.status === "WARN" || f.status === "FAIL");
    const rest = fs.filter((f) => !(f.status === "WARN" || f.status === "FAIL"));
    const row = (f) => `<div class="finding">${chip(f.status)}<div class="msg"><b>${esc(f.check)}</b>${esc(f.message)}</div>${ownerChip(f.owner)}</div>`;
    return `<div class="layer ${st}" style="--i:${i}"><div class="ld"><i class="ph-fill ${st === "PASS" ? "ph-check" : st === "WARN" ? "ph-warning" : "ph-x"}"></i></div>
      <div><div class="lt">${esc(L.title)}</div>
        ${issues.map(row).join("")}
        ${rest.length ? `<details><summary class="toggle-pass">${rest.length} passed or informational check${rest.length > 1 ? "s" : ""}</summary>${rest.map(row).join("")}</details>` : ""}
      </div></div>`;
  }).join("");
}

async function run(root, apply) {
  const text = root.querySelector("textarea").value;
  if (!text.trim()) { toast("Paste or pick a packet first.", true); return; }
  try {
    const r = await api.post("/api/check", { text, apply });
    current.result = r.result; current.applied = apply; current.text = text;
    store.setState(r.state);
    paint(root);
    if (apply) toast(r.result.event.type === "reject" ? "Rejected and logged. Twin unchanged." : `Twin updated (event #${r.result.event.event_id}).`);
  } catch (err) { toast(err.message, true); }
}

function paint(root) {
  root.querySelector("[data-verdict]").innerHTML = verdictHtml();
  const form = root.querySelector("[data-session]");
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    try {
      store.meta = await api.post("/api/session", { session_id: fd.get("sid"), acq_time: `${fd.get("when")}:00` });
      toast(`Session ${fd.get("sid")} registered. Check the packet again.`);
      run(root, false);
    } catch (err) { toast(err.message, true); }
  });
}

export function render(root) {
  root.innerHTML = `<div class="view">
    <h1>Check a packet</h1>
    <p class="lede">Any evidence packet goes through six checks, from "can the file be read" to "may the twin use it". Each problem names the track that owns it. Nothing is repaired silently.</p>
    <div class="grid g-check">
      <section class="panel">
        <div class="panel-head"><i class="ph ph-cube"></i><h2 class="grow">Packet</h2></div>
        <div class="drop" data-drop><i class="ph ph-upload-simple"></i> Drop a .json file here, or paste below. It is checked at once.</div>
        <label class="field">Packet JSON<textarea spellcheck="false" aria-label="Packet JSON">${esc(current.text)}</textarea></label>
        <div class="row" style="margin:12px 0 14px">
          <button class="btn" data-run="check"><i class="ph ph-magnifying-glass"></i>Check only</button>
          <button class="btn primary" data-run="apply"><i class="ph ph-arrow-right"></i>Check and apply</button>
        </div>
        <div class="lib">${libraryHtml()}</div>
      </section>
      <section class="panel"><div class="panel-head"><i class="ph ph-shield-check"></i><h2 class="grow">Decision</h2></div><div data-verdict></div></section>
    </div></div>`;
  paint(root);

  root.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const p = await api.get(`/api/packet/${encodeURIComponent(b.dataset.pick)}`);
      current = { text: p.text, picked: b.dataset.pick, result: null };
      root.querySelector("textarea").value = p.text;
      root.querySelectorAll("[data-pick]").forEach((x) => x.classList.toggle("sel", x === b));
      run(root, false);
    } catch (err) { toast(err.message, true); }
  }));
  root.querySelector('[data-run="check"]').addEventListener("click", () => run(root, false));
  root.querySelector('[data-run="apply"]').addEventListener("click", () => run(root, true));
  // A pasted packet is checked straight away (never applied), so a judge's packet needs no scrolling and no second click.
  root.querySelector("textarea").addEventListener("paste", () => setTimeout(() => { current.picked = null; run(root, false); }, 0));
  const drop = root.querySelector("[data-drop]");
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
  drop.addEventListener("drop", async (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (!f) return;
    if (f.size > 2_000_000) { toast("That file is larger than 2 MB; a packet should be a small JSON file.", true); return; }
    root.querySelector("textarea").value = await f.text();
    current.picked = null;
    run(root, false);
  });
}
