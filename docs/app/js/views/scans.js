// View: the raw data. A live 3D hero (the scanned volume, the region masks and one spectroscopy cube per evidence
// packet in the twin), then both spectra, the slice view (synced with the 3D slice scrubber), and our own
// recomputation of packet numbers straight from the source files.
import { api, chip, esc, fmt, store, toast, ACTION_TEXT } from "../core.js";
import { spectrumChart } from "../charts.js";

// Kept across re-renders (the theme toggle redraws the page): one download, and the camera and choices stay put.
let sceneData = null;
let libGeo = null;
const ui = { view: null, session: "all", slice: null, clip: false, selected: null };

const POLL_MS = 3000;
const SES_NAMES = { "ses-baseline": "Baseline", "ses-followup": "Follow-up", "ses-repeat": "Repeat" };
const sesLabel = (s) => SES_NAMES[s] || (s || "").replace(/^ses-/, "").replace(/^\w/, (c) => c.toUpperCase());

// ------------------------------------------------------------------ evidence from the twin state

function cubeOf(sr, observable) {
  if (!sr || !Array.isArray(sr.voi_center_mm)) return null;
  const isCho = /^cho/i.test(observable || "");
  const shift = isCho ? Number(sr.csde_mm_NAA_Cho || 0) : 0;
  return { center: sr.voi_center_mm.map((v) => Number(v) + shift), size: (sr.voi_size_mm || [20, 20, 20]).map(Number),
    stated: sr.voi_center_mm.map(Number), shift };
}

function evidenceFrom(state) {
  const out = [];
  for (const e of state.events || []) {
    const rejected = e.type === "reject";
    let sr = null, from = "its packet";
    if (!rejected) sr = state.packets?.[e.packet_id]?.spatial_reference;
    else {
      const g = (libGeo || []).find((x) => x.packet_id === e.packet_id && x.session_id === e.session_id);
      if (g) { sr = g.spatial_reference; from = `library file ${g.library_id}`; }
    }
    const reasons = (e.findings || []).filter((f) => f.status && f.status !== "PASS" && f.status !== "INFO").map((f) => f.message);
    out.push({
      id: e.event_id, packet_id: e.packet_id, session_id: e.session_id, observable: e.observable, time: e.time_month,
      status: e.qc_status || "INFO", type: e.type, headline: e.headline, reason: e.reason,
      reasons: reasons.length ? reasons : e.reason ? [e.reason] : [], rejected, from, cube: cubeOf(sr, e.observable),
    });
  }
  return out;
}

function sessionsFrom(items) {
  const t = new Map();
  for (const it of items) if (it.session_id) t.set(it.session_id, Math.min(t.get(it.session_id) ?? Infinity, it.time ?? Infinity));
  for (const s of Object.keys(sceneData?.sessions || {})) if (!t.has(s)) t.set(s, s === "ses-baseline" ? 0 : 6);
  return [...t.entries()].sort((a, b) => a[1] - b[1]).map(([s, m]) => ({ id: s, month: Number.isFinite(m) ? m : null, image: !!sceneData?.sessions?.[s] }));
}

// ------------------------------------------------------------------ 2D slices (drawn from the same volumes as the 3D view)

function tokenRGB(name, fallback) {
  const c = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  c.fillStyle = fallback;
  c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  c.fillRect(0, 0, 1, 1);
  return [...c.getImageData(0, 0, 1, 1).data.slice(0, 3)];
}

const volCache = new Map();
function u8(str) {
  if (!volCache.has(str)) { const bin = atob(str); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); volCache.set(str, a); }
  return volCache.get(str);
}

function drawSlice(canvas, ses, k, cubes, tint) {
  const d = sceneData, s = d.sessions[ses];
  if (!canvas || !s) return;
  const [nx, ny] = d.shape, scale = 10, win = d.bands[3].centre * 1.05;
  const t1 = u8(s.t1w), roi = s.roi ? u8(s.roi) : null;
  canvas.width = nx * scale; canvas.height = ny * scale;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(nx, ny);
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    const idx = i + j * nx + k * nx * ny;
    const g = Math.min(255, (t1[idx] / win) * 255), r = roi ? roi[idx] / 255 : 0;
    const o = ((ny - 1 - j) * nx + i) * 4;          // anterior at the top; subject's left on screen left (neurological view)
    img.data[o] = g * (1 - 0.55 * r) + tint[0] * 0.55 * r;
    img.data[o + 1] = g * (1 - 0.55 * r) + tint[1] * 0.55 * r;
    img.data[o + 2] = g * (1 - 0.55 * r) + tint[2] * 0.55 * r;
    img.data[o + 3] = 255;
  }
  const tmp = document.createElement("canvas"); tmp.width = nx; tmp.height = ny;
  tmp.getContext("2d").putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.drawImage(tmp, 0, 0, nx * scale, ny * scale);
  // spectroscopy cubes of this session that cut this slice (light line: the scan is always dark)
  const A = d.affine, z = A[2][2] * k + A[2][3];
  ctx.strokeStyle = "#eef3f7"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  for (const c of cubes) {
    if (Math.abs(z - c.stated[2]) > c.size[2] / 2) continue;
    const px = (x) => ((x - A[0][3]) / A[0][0] + 0.5) * scale, py = (y) => (ny - ((y - A[1][3]) / A[1][1] + 0.5)) * scale;
    const x0 = px(c.stated[0] - c.size[0] / 2), x1 = px(c.stated[0] + c.size[0] / 2);
    const y0 = py(c.stated[1] + c.size[1] / 2), y1 = py(c.stated[1] - c.size[1] / 2);
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
  }
}

// ------------------------------------------------------------------ hero markup

function heroHTML() {
  return `<section class="panel s3d" aria-labelledby="s3d-title">
    <div class="s3d-grid">
      <div class="s3d-stage" data-stage>
        <div class="s3d-skel" data-skel><div class="skeleton"></div><span>Building the 3D view</span></div>
        <span class="s3d-badge">SIMULATED</span>
        <div class="s3d-stage-note" data-stage-note hidden></div>
        <div class="s3d-card" data-card hidden></div>
      </div>
      <aside class="s3d-side">
        <h2 class="s3d-title" id="s3d-title">Where does the evidence come from?</h2>
        <p class="s3d-caption" data-caption>Every spectrum comes from one 20 mm cube, drawn where its packet says it was measured.</p>
        <div class="s3d-field"><span class="s3d-label" id="s3d-ses">Session</span>
          <div class="s3d-seg" role="radiogroup" aria-labelledby="s3d-ses" data-sessions></div></div>
        <div class="s3d-field"><label class="s3d-label" for="s3d-slice">Slice <span class="num" data-slice-label></span></label>
          <div class="s3d-scrub"><input type="range" id="s3d-slice" min="0" max="15" step="1" data-slice>
          <label class="s3d-check"><input type="checkbox" data-clip> Cut away above</label></div></div>
        <div class="s3d-field s3d-evfield"><span class="s3d-label">Evidence in the twin <span class="s3d-live" data-live title="Checks for new evidence every 3 seconds while this page is open">live</span></span>
          <ul class="s3d-evlist" data-evlist></ul></div>
        <ul class="s3d-legend" data-legend></ul>
        <div class="s3d-foot"><span>Drag to turn. Scroll to zoom. Click a cube.</span>
          <button type="button" class="btn ghost s3d-reset" data-reset><i class="ph ph-arrow-counter-clockwise"></i>Reset view</button></div>
      </aside>
    </div>
  </section>`;
}

function legendHTML(d) {
  const rc = d.roi_change;
  const rows = [
    ["brain", `<i class="sw3 sw-ring"></i>`, "Brain surface", "The brain mask from the file, drawn as glass. Its flat top and bottom are the edge of the scan."],
    ["slice", `<i class="sw3 sw-vol"></i>`, "T1-weighted slice", "Move the slider to show one real scanned slice inside the brain."],
    ["rings", `<i class="sw3 sw-ring"></i>`, "Brain outline", "One ring per acquired slice."],
    ["slab", `<i class="sw3 sw-slab"></i>`, "Scanned slab", `Only ${d.shape[2]} slices of 4 mm (${Math.round(d.slab_mm[1][2] - d.slab_mm[0][2])} mm). The flat shape is the slab, not the brain.`],
    ["region", `<i class="sw3 sw-base"></i>`, "Region, baseline", `<span class="num">${fmt(rc.baseline, 0)}</span> mm³`],
    ["region", `<i class="sw3 sw-follow"></i>`, "Region, follow-up", `<span class="num">${fmt(rc.followup, 0)}</span> mm³ (<span class="num">+${fmt(rc.increase_pct, 1)}</span> %), an alignment artifact.`],
    ["evidence", `<i class="sw3 sw-cube s-PASS"></i><i class="sw3 sw-cube s-WARN"></i><i class="sw3 sw-cube s-FAIL dashed"></i>`, "Spectroscopy cube", "Coloured by the twin's check: pass, warning, rejected (dashed)."],
  ];
  return rows.map(([k, sw, name, desc]) => `<li><button type="button" data-key="${k}"><span class="sws">${sw}</span>
    <span class="nm">${name}</span><span class="ds">${desc}</span></button></li>`).join("");
}

function captionText(d) {
  const pct = Math.round(d.roi_change.increase_pct);
  return `Every spectrum comes from one 20 mm cube, drawn where its packet says it was measured and coloured by the twin's check. The amber follow-up region looks about ${pct} % bigger only because the baseline mask was pushed through an imperfect 1.1 mm alignment: nothing grew.`;
}

function cardHTML(it) {
  if (!it) return "";
  const c = it.cube;
  const pos = c ? `(${c.stated.map((v) => fmt(v, 0)).join(", ")}) mm, ${fmt(c.size[0], 0)} mm cube` : "No position in the packet.";
  const shift = c && c.shift ? ` Drawn ${fmt(c.shift, 1)} mm off along each axis: choline is seen from a shifted cube.` : "";
  return `<div class="s3d-card-head"><span class="mono">${esc(it.packet_id)}</span>${chip(it.status, ACTION_TEXT[it.type] || it.type)}
      <button type="button" class="btn icon ghost" data-card-close aria-label="Close"><i class="ph ph-x"></i></button></div>
    <div class="s3d-card-sub">${esc(sesLabel(it.session_id))}${it.time != null ? `, month ${fmt(it.time, 0)}` : ""}, ${esc(it.observable || "")}</div>
    <p>${esc(it.headline || "")}</p>
    ${it.reasons.length ? `<ul>${it.reasons.slice(0, 2).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    <div class="s3d-card-pos">Position stated by ${esc(it.from)}: ${esc(pos)}${esc(shift)}</div>`;
}

// ------------------------------------------------------------------ hero wiring

async function mountHero(root, page) {
  const stage = root.querySelector("[data-stage]");
  const side = root.querySelector(".s3d-side");
  const fail = (msg) => {
    stage.querySelector("[data-skel]")?.remove();
    stage.insertAdjacentHTML("beforeend", `<div class="s3d-error" role="alert"><i class="ph ph-cube-transparent"></i><b>The 3D view could not load.</b><span>${esc(msg)}</span>
      <button type="button" class="btn" data-retry><i class="ph ph-arrow-clockwise"></i>Try again</button></div>`);
    stage.querySelector("[data-retry]").addEventListener("click", () => { stage.querySelector(".s3d-error")?.remove(); stage.insertAdjacentHTML("afterbegin", `<div class="s3d-skel" data-skel><div class="skeleton"></div><span>Building the 3D view</span></div>`); mountHero(root, page); });
  };
  let mod, state;
  try {
    [sceneData, libGeo, state, mod] = await Promise.all([
      sceneData || api.get("/api/scene"), libGeo || api.get("/api/scene/library-geometry").catch(() => []),
      api.get("/api/state"), import("../scene3d.js")]);
  } catch (err) {
    if (stage.isConnected) fail(/404|not found/i.test(err.message) ? "The server is running older code without the 3D scene. Restart it, then try again." : err.message);
    return;
  }
  if (!stage.isConnected) return;                    // the user already left the page
  store.setState(state);
  const d = sceneData;
  side.querySelector("[data-caption]").textContent = captionText(d);
  side.querySelector("[data-legend]").innerHTML = legendHTML(d);
  if (ui.slice == null) {                            // start on the slice through the spectroscopy voxel
    const c = evidenceFrom(state).find((x) => x.cube)?.cube.stated || [0, 0, 6];
    ui.slice = Math.max(0, Math.min(d.shape[2] - 1, Math.round((c[2] - d.affine[2][3]) / d.affine[2][2])));
  }
  const slider = side.querySelector("[data-slice]");
  slider.max = d.shape[2] - 1; slider.value = ui.slice;
  side.querySelector("[data-clip]").checked = ui.clip;
  stage.querySelector("[data-skel]")?.remove();

  let items = evidenceFrom(state), version = state.version, eventCount = (state.events || []).length;
  const byId = (id) => items.find((x) => x.id === id);
  const card = stage.querySelector("[data-card]");
  const note = stage.querySelector("[data-stage-note]");

  function describe(hit) {
    if (hit.kind === "region") {
      const v = d.sessions[hit.ses].roi_volume_mm3;
      return [`Region mask, ${sesLabel(hit.ses).toLowerCase()}`, `${fmt(v, 0)} mm³, from ${d.sessions[hit.ses].roi_file.split("/").pop()}.`];
    }
    const it = hit.e.item;
    const more = hit.count > 1 ? ` ${hit.count} cubes share this spot; pick one in the list.` : "";
    return [`${it.packet_id}, ${sesLabel(it.session_id)}`, `${ACTION_TEXT[it.type] || it.type} (${it.status}). Click for the reasons.${more}`];
  }

  let view;
  try {
    view = mod.mountScene(stage, d, {
      view: ui.view, session: ui.session, slice: ui.slice, clip: ui.clip, selected: ui.selected, describe,
      onDispose: (v) => { ui.view = v; },
      onSelect: (id) => select(id),
      onRegion: () => {},
    });
  } catch (err) { fail(err.message); return; }

  function select(id) {
    ui.selected = id;
    const it = byId(id);
    card.hidden = !it;
    card.innerHTML = cardHTML(it);
    card.querySelector("[data-card-close]")?.addEventListener("click", () => select(null));
    side.querySelectorAll("[data-ev]").forEach((r) => r.setAttribute("aria-pressed", String(Number(r.dataset.ev) === id)));
    view.select(id);
  }

  function renderSessions() {
    const list = sessionsFrom(items);
    if (ui.session !== "all" && !list.some((s) => s.id === ui.session)) ui.session = "all";
    side.querySelector("[data-sessions]").innerHTML = [{ id: "all", label: "All" }, ...list.map((s) => ({ id: s.id, label: sesLabel(s.id) }))]
      .map((s) => `<button type="button" role="radio" data-ses="${esc(s.id)}" aria-checked="${s.id === ui.session}">${esc(s.label)}</button>`).join("");
    const cur = list.find((s) => s.id === ui.session);
    note.hidden = !cur || cur.image;
    note.textContent = cur && !cur.image ? `No image file for ${cur.id}. Its evidence cubes are drawn on the baseline anatomy.` : "";
  }

  function renderList(fresh = new Set()) {
    const shown = items.filter((x) => ui.session === "all" || x.session_id === ui.session);
    side.querySelector("[data-evlist]").innerHTML = shown.length ? shown.slice().reverse().map((it) => `<li><button type="button" data-ev="${it.id}" aria-pressed="${it.id === ui.selected}" class="${fresh.has(it.id) ? "fresh" : ""}">
        <i class="st s-${esc(it.status)}${it.rejected ? " dashed" : ""}"></i><span class="mono">${esc(it.packet_id)}</span>
        <span class="ses">${esc(sesLabel(it.session_id))}</span><span class="pos">${it.cube ? "" : it.observable === "roi_volume" ? "region" : "no position"}</span></button></li>`).join("")
      : `<li class="s3d-empty">No evidence for this session yet.</li>`;
  }

  side.querySelector("[data-sessions]").addEventListener("click", (e) => {
    const b = e.target.closest("[data-ses]"); if (!b) return;
    ui.session = b.dataset.ses;
    renderSessions(); renderList();
    view.setSession(ui.session);
    page.redrawSlices?.();
  });
  side.querySelector("[data-sessions]").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const btns = [...side.querySelectorAll("[data-ses]")];
    const i = btns.findIndex((b) => b.dataset.ses === ui.session) + (e.key === "ArrowRight" ? 1 : -1);
    const b = btns[(i + btns.length) % btns.length]; b.click(); side.querySelector(`[data-ses="${CSS.escape(b.dataset.ses)}"]`)?.focus();
  });
  side.querySelector("[data-evlist]").addEventListener("click", (e) => {
    const b = e.target.closest("[data-ev]"); if (!b) return;
    const id = Number(b.dataset.ev);
    select(ui.selected === id ? null : id);
  });
  const sliceLabel = side.querySelector("[data-slice-label]");
  const setSliceLabel = () => { sliceLabel.textContent = `${ui.slice + 1} of ${d.shape[2]}, z = ${fmt(d.contours[ui.slice].z_mm, 0)} mm`; };
  setSliceLabel();
  slider.addEventListener("input", () => { ui.slice = Number(slider.value); setSliceLabel(); view.setSlice(ui.slice); page.redrawSlices?.(); });
  side.querySelector("[data-clip]").addEventListener("change", (e) => { ui.clip = e.target.checked; view.setClip(ui.clip); });
  for (const r of side.querySelectorAll("[data-key]")) {
    const on = () => view.highlight(r.dataset.key), off = () => view.highlight(null);
    r.addEventListener("pointerenter", on); r.addEventListener("pointerleave", off);
    r.addEventListener("focus", on); r.addEventListener("blur", off);
  }
  side.querySelector("[data-reset]").addEventListener("click", () => view.resetView());

  renderSessions(); renderList();
  view.setEvidence(items);
  if (ui.selected != null && byId(ui.selected)) select(ui.selected); else ui.selected = null;
  page.evidence = () => items;
  page.redrawSlices?.();

  // ---- live: poll the twin while this page is visible; update the evidence layer in place
  const live = side.querySelector("[data-live]");
  let busy = false;
  const timer = setInterval(async () => {
    if (!stage.isConnected) { clearInterval(timer); return; }
    if (document.hidden || busy) return;
    busy = true;
    try {
      // cheap check first: only the twin's version number; the full state is fetched only when it changed
      const v = await api.get("/api/version");
      if (!stage.isConnected) return;
      live.classList.remove("off");
      if (v.version === version && v.events === eventCount) return;
      const s = await api.get("/api/state");
      if (!stage.isConnected) return;
      const before = new Set(items.map((x) => x.id));
      if ((s.events || []).some((e) => e.type === "reject" && !(libGeo || []).some((g) => g.packet_id === e.packet_id))) {
        libGeo = await api.get("/api/scene/library-geometry").catch(() => libGeo);
      }
      store.setState(s);
      version = s.version; eventCount = (s.events || []).length;
      items = evidenceFrom(s);
      const fresh = new Set(items.filter((x) => !before.has(x.id)).map((x) => x.id));
      if (ui.selected != null && !byId(ui.selected)) { ui.selected = null; card.hidden = true; }
      renderSessions(); renderList(fresh);
      view.setEvidence(items);
      view.setSession(ui.session);
      if (ui.selected != null) select(ui.selected);
      page.redrawSlices?.();
    } catch (err) {
      live.classList.add("off");                     // server unreachable: keep the last picture, try again next tick
    } finally { busy = false; }
  }, POLL_MS);
}

// ------------------------------------------------------------------ page

const check = (a, b, tol) => (Math.abs(a - b) <= tol ? chip("PASS", "matches") : chip("WARN", "differs"));

export async function render(root) {
  root.innerHTML = `<div class="view">
    <h1>Scans and spectra</h1>
    <p class="lede">Where the numbers come from. We read the raw files ourselves and recompute what the packets claim, instead of trusting them.</p>
    ${heroHTML()}
    <div data-rest><div class="grid g-2" style="margin-top:16px"><div class="skeleton" style="height:340px"></div><div class="skeleton" style="height:340px"></div></div></div>
  </div>`;
  const page = {};
  mountHero(root, page);
  const rest = root.querySelector("[data-rest]");
  let d;
  try {
    d = await Promise.all(["ses-baseline", "ses-followup"].flatMap((s) => [api.get(`/api/anatomy/${s}`), api.get(`/api/spectrum/${s}`)]));
  } catch (err) { toast(err.message, true); return; }
  if (!rest.isConnected) return;
  const [a0, s0, a1, s1] = d;
  const pk = (pid) => store.state.packets[pid];
  const qc = (pid, n) => (pk(pid)?.qc_checks || []).find((c) => c.name === n)?.value;
  rest.innerHTML = `
    <div class="grid g-2" style="margin-top:16px">
      <section class="panel">
        <div class="panel-head" style="flex-wrap:wrap"><i class="ph ph-waveform"></i><h2 class="grow">¹H spectrum of the frontal voxel</h2><span class="chip neutral">PRESS, TE 30 ms, 64 averages</span></div>
        ${spectrumChart(s0, s1)}
        <div class="legend"><span><i class="sw t0"></i>baseline, linewidth 8.7 Hz</span><span style="color:var(--accent)"><i class="sw post"></i>follow-up, linewidth 11.4 Hz</span></div>
        <p class="reason">The follow-up peaks are lower and broader: the magnetic field was less uniform (poorer shim). Choline (3.20 ppm) and creatine (3.03 ppm) sit only about 21 Hz apart, so broader lines make them overlap and the fitted ratio less reliable.</p>
      </section>
      <section class="panel">
        <div class="panel-head"><i class="ph ph-brain"></i><h2 class="grow" data-slice-title>T1-weighted slice, z = ${fmt(a0.slice_z_mm, 0)} mm</h2></div>
        <div class="grid g-2" style="gap:10px">
          <div class="scan"><canvas data-a="0" aria-label="Baseline slice"></canvas><span class="cap">baseline</span></div>
          <div class="scan"><canvas data-a="1" aria-label="Follow-up slice"></canvas><span class="cap">follow-up</span></div>
        </div>
        <div class="legend"><span style="color:var(--accent)"><i class="sw post"></i>region mask, baseline</span><span style="color:var(--warn)"><i class="sw ev"></i>region mask, follow-up</span><span><i class="sw s3d-sw-dash"></i>20 mm spectroscopy voxel</span></div>
        <p class="reason">Neurological view: front of the head at the top, the subject's left on the left. Move the slice slider above to walk through all 16 slices. The larger follow-up mask comes from pushing the baseline mask through an imperfect alignment.</p>
      </section>
    </div>
    <section class="panel" style="margin-top:16px">
      <div class="panel-head"><i class="ph ph-fingerprint"></i><h2 class="grow">Independent check: packet value vs recomputed from the raw file</h2></div>
      <div style="overflow-x:auto"><div class="verify" style="min-width:560px">
        <div class="h">Quantity</div><div class="h">Packet says</div><div class="h">We recompute</div><div class="h">Result</div>
        ${[
          ["SNR, baseline (NAA peak / noise SD)", qc("E-t0-cho", "mrs_snr"), s0.snr_recomputed, 0.5, 1],
          ["SNR, follow-up", qc("E-t1-cho", "mrs_snr"), s1.snr_recomputed, 0.5, 1],
          ["ROI volume, baseline (mm³)", pk("E-t0-roi")?.value, a0.roi_volume_mm3_recomputed, 1, 0],
          ["ROI volume, follow-up (mm³)", pk("E-t1-roi")?.value, a1.roi_volume_mm3_recomputed, 1, 0],
          ["Real field from 123.25 MHz (T)", 3.0, s0.nu0_MHz / 42.577, 0.001, 3],
        ].map(([n, p, r, tol, dg]) => `<div>${esc(n)}</div><div class="num">${p === undefined ? "n/a" : fmt(p, dg)}</div><div class="num">${fmt(r, dg)}</div>
          <div>${p === undefined ? chip("INFO", "ingest packets first") : n.startsWith("Real field") ? chip("INFO", "label 3 T, actual 2.895 T") : check(p, r, tol)}</div>`).join("")}
      </div></div>
    </section>`;
  const title = rest.querySelector("[data-slice-title]");
  page.redrawSlices = () => {
    if (!rest.isConnected) { themeObs.disconnect(); return; }
    if (!sceneData || ui.slice == null) return;     // the 3D data has not arrived yet; it calls back when it does
    const items = page.evidence ? page.evidence() : [];
    const cubesOf = (ses) => items.filter((x) => x.session_id === ses && x.cube && !x.rejected).map((x) => ({ ...x.cube, stated: x.cube.stated }));
    title.textContent = `T1-weighted slice ${ui.slice + 1} of ${sceneData.shape[2]}, z = ${fmt(sceneData.contours[ui.slice].z_mm, 0)} mm`;
    drawSlice(rest.querySelector('[data-a="0"]'), "ses-baseline", ui.slice, cubesOf("ses-baseline"), tokenRGB("--accent", "#57cfc6"));
    drawSlice(rest.querySelector('[data-a="1"]'), "ses-followup", ui.slice, cubesOf("ses-followup"), tokenRGB("--warn", "#ebb556"));
  };
  const themeObs = new MutationObserver(() => page.redrawSlices());
  themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  page.redrawSlices();
}
