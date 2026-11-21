// Felix: the built-in assistant drawer, available on every page.
// It sends the question together with what is on the screen right now (the visible text of the page), and the
// server adds the live twin numbers and our docs. Answers stream in as they are written; reasoning is never shown.
import { api, esc } from "./core.js";

const SUGGEST = {
  twin: ["What does this result mean?", "Why did the twin only move 32 %?", "What is the difference between z and d²?"],
  scans: ["What does this 3D view show?", "Why does the follow-up region look bigger?", "Why is the real field 2.895 T?"],
  check: ["Why was this packet rejected?", "What do the six checks do?", "What happens if I apply this packet?"],
  trace: ["What does SHA-256 verified prove?", "How do I trace a value to its file?"],
  explain: ["Which explanation is most likely?", "What would separate these explanations?"],
  next: ["Why is re-shim and repeat recommended?", "What does the expected repeat range mean?"],
  bench: ["What do these test bench results mean?", "Why is the false alarm rate 20 %?"],
  cards: ["What dominates the uncertainty?", "What can Cho/Cr not tell us?"],
  about: ["What is the validation domain?", "Explain the architecture in three sentences."],
  tests: ["What do the regression tests check?"],
};
const PAGE_NAMES = {
  twin: "Twin state", scans: "Scans and spectra", check: "Check a packet", trace: "Trace to source",
  explain: "Competing explanations", next: "What to measure next", bench: "Test bench", cards: "Measurement cards",
  about: "Architecture and limits", tests: "Regression tests",
};
const STATUS_TEXT = {
  ready: "Ready", warming: "Reading our docs", starting: "Starting the local model", offline: "Offline", idle: "Waiting",
};

let history = [];                 // [{role, content}] plain questions and answers, cleared by "Clear memory"
let open = false, streaming = null, statusTimer = 0;
const el = {};

const page = () => (location.hash.replace(/^#\//, "") || "twin").split("?")[0];

function screenSnapshot() {
  const view = document.querySelector("#main .view");
  const text = (view?.innerText || "").replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();
  const title = view?.querySelector("h1")?.textContent?.trim() || PAGE_NAMES[page()] || page();
  const sel = view?.querySelector(".lib button.sel, [aria-selected='true'], .s3d-evlist .sel");
  return { page: page(), title, text: text.slice(0, 3500), focus: sel ? sel.textContent.trim().slice(0, 200) : undefined };
}

// ---------- tiny, safe markdown: escape first, then bold, code, lists, paragraphs ----------
function md(src) {
  const lines = esc(src).split("\n");
  let html = "", list = null;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const src = line.match(/^Source:\s*(.+)$/i);
    const ul = line.match(/^\s*[-*]\s+(.*)$/), ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (src) { close(); html += `<p class="as-src"><i class="ph ph-book-open-text"></i>${inline(src[1])}</p>`; }
    else if (ul) { if (list !== "ul") { close(); html += "<ul>"; list = "ul"; } html += `<li>${inline(ul[1])}</li>`; }
    else if (ol) { if (list !== "ol") { close(); html += "<ol>"; list = "ol"; } html += `<li>${inline(ol[1])}</li>`; }
    else if (!line.trim()) { close(); }
    else { close(); html += `<p>${inline(line)}</p>`; }
  }
  close();
  return html;
}

// ---------- status ----------
async function refreshStatus() {
  clearTimeout(statusTimer);
  let s;
  try { s = await api.get("/api/assistant/status"); } catch (e) { s = { state: "offline", detail: "The Larmor server is not reachable." }; }
  el.root.dataset.state = s.state;
  el.status.textContent = STATUS_TEXT[s.state] || s.state;
  el.status.title = s.detail || "";
  el.detail.textContent = s.state === "ready" ? "Answers come from our docs and from what is on your screen." : s.detail || "";
  el.retry.hidden = s.state !== "offline";
  statusTimer = setTimeout(refreshStatus, s.state === "ready" ? 30000 : 3000);
}

// ---------- rendering ----------
function renderEmpty() {
  const items = SUGGEST[page()] || SUGGEST.twin;
  el.log.innerHTML = `<div class="as-empty">
      <p><b>I can see the page you are on.</b> Ask what a number means, why the twin decided something, or how a page works.</p>
      <div class="as-chips">${items.map((q) => `<button type="button" class="as-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    </div>`;
}

function addTurn(role, content, meta = "") {
  el.log.querySelector(".as-empty")?.remove();
  const div = document.createElement("div");
  div.className = `as-msg as-${role}`;
  div.innerHTML = role === "user" ? `<p>${esc(content)}</p>` : md(content);
  if (meta) div.insertAdjacentHTML("beforeend", `<span class="as-meta">${esc(meta)}</span>`);
  el.log.appendChild(div);
  el.log.scrollTop = el.log.scrollHeight;
  return div;
}

function updateContext() {
  el.ctx.innerHTML = `<i class="ph ph-eye"></i>Looking at: <b>${esc(PAGE_NAMES[page()] || page())}</b>`;
}

// ---------- asking ----------
async function ask(question) {
  question = question.trim();
  if (!question || streaming) return;
  el.input.value = ""; autosize();
  addTurn("user", question);
  const bubble = addTurn("assistant", "");
  bubble.classList.add("as-live");
  bubble.innerHTML = `<span class="as-wait"><i></i><i></i><i></i></span><span class="as-reading">Reading your screen and our docs</span>`;
  const ctrl = new AbortController();
  streaming = ctrl;
  setBusy(true);
  let text = "", meta = "";
  try {
    const res = await fetch("/api/assistant/ask", {
      method: "POST", headers: { "content-type": "application/json" }, signal: ctrl.signal,
      body: JSON.stringify({ question, history, screen: screenSnapshot() }),
    });
    if (!res.ok || !res.body) throw new Error(`The server answered ${res.status}.`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, cut); buf = buf.slice(cut + 2);
        if (!chunk.startsWith("data:")) continue;
        const ev = JSON.parse(chunk.slice(5));
        if (ev.error) throw new Error(ev.error);
        if (ev.t) { text += ev.t; bubble.innerHTML = md(text) + `<span class="as-caret"></span>`; el.log.scrollTop = el.log.scrollHeight; }
        if (ev.done) meta = `first words after ${ev.first_token_s} s`;
      }
    }
    bubble.innerHTML = md(text) + (meta ? `<span class="as-meta">${esc(meta)}</span>` : "");
    history.push({ role: "user", content: question }, { role: "assistant", content: text });
  } catch (err) {
    if (err.name === "AbortError") {
      bubble.innerHTML = md(text || "Stopped.") + `<span class="as-meta">stopped</span>`;
      if (text) history.push({ role: "user", content: question }, { role: "assistant", content: text });
    } else {
      bubble.classList.add("as-error");
      bubble.innerHTML = `<p>${esc(err.message)}</p>`;
    }
  } finally {
    bubble.classList.remove("as-live");
    streaming = null;
    setBusy(false);
    refreshStatus();
  }
}

function setBusy(b) {
  el.send.hidden = b; el.stop.hidden = !b;
  el.input.disabled = false;
}

function clearMemory() {
  if (streaming) streaming.abort();
  history = [];
  renderEmpty();
  el.input.focus();
}

function autosize() {
  el.input.style.height = "auto";
  el.input.style.height = `${Math.min(el.input.scrollHeight, 140)}px`;
}

function setOpen(v) {
  open = v;
  el.root.classList.toggle("open", v);
  el.fab.setAttribute("aria-expanded", String(v));
  el.panel.setAttribute("aria-hidden", String(!v));
  if (v) {
    updateContext();
    if (!history.length) renderEmpty();
    setTimeout(() => el.input.focus(), 160);
    refreshStatus();
  }
}

export function initAssistant() {
  const root = document.createElement("div");
  root.className = "as-root";
  root.dataset.state = "idle";
  root.innerHTML = `
    <button type="button" class="as-fab" aria-expanded="false" aria-controls="as-panel" title="Ask Felix (press /)">
      <i class="ph-duotone ph-chat-circle-dots"></i><span>Ask Felix</span><i class="as-dot" aria-hidden="true"></i>
    </button>
    <aside class="as-panel" id="as-panel" aria-label="Felix, the Larmor assistant" aria-hidden="true">
      <header class="as-head">
        <div class="as-title"><i class="ph-duotone ph-chat-circle-dots"></i><div><b>Felix</b>
          <span class="as-status"><i class="as-dot"></i><span data-status>Waiting</span></span></div></div>
        <div class="as-actions">
          <button type="button" class="btn ghost small" data-clear title="Forget this conversation"><i class="ph ph-eraser"></i>Clear memory</button>
          <button type="button" class="btn icon ghost" data-close aria-label="Close"><i class="ph ph-x"></i></button>
        </div>
      </header>
      <p class="as-detail" data-detail></p>
      <button type="button" class="btn small as-retry" data-retry hidden><i class="ph ph-arrow-clockwise"></i>Retry</button>
      <div class="as-log" data-log aria-live="polite"></div>
      <form class="as-compose" data-form>
        <div class="as-ctx" data-ctx></div>
        <div class="as-row">
          <textarea rows="1" data-input placeholder="Ask about anything on this page" aria-label="Your question"></textarea>
          <button type="submit" class="btn primary icon" data-send aria-label="Send"><i class="ph ph-paper-plane-right"></i></button>
          <button type="button" class="btn icon" data-stop aria-label="Stop the answer" hidden><i class="ph ph-stop"></i></button>
        </div>
        <span class="as-hint">Local model on this laptop. Answers use only our docs and your screen. Not medical advice.</span>
      </form>
    </aside>`;
  document.body.appendChild(root);
  Object.assign(el, {
    root, fab: root.querySelector(".as-fab"), panel: root.querySelector(".as-panel"), log: root.querySelector("[data-log]"),
    input: root.querySelector("[data-input]"), send: root.querySelector("[data-send]"), stop: root.querySelector("[data-stop]"),
    status: root.querySelector("[data-status]"), detail: root.querySelector("[data-detail]"), retry: root.querySelector("[data-retry]"),
    ctx: root.querySelector("[data-ctx]"),
  });
  el.fab.addEventListener("click", () => setOpen(!open));
  root.querySelector("[data-close]").addEventListener("click", () => setOpen(false));
  root.querySelector("[data-clear]").addEventListener("click", clearMemory);
  el.retry.addEventListener("click", async () => { await api.post("/api/assistant/warm"); refreshStatus(); });
  root.querySelector("[data-form]").addEventListener("submit", (e) => { e.preventDefault(); ask(el.input.value); });
  el.stop.addEventListener("click", () => streaming?.abort());
  el.input.addEventListener("input", autosize);
  el.input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(el.input.value); } });
  el.log.addEventListener("click", (e) => { const c = e.target.closest("[data-q]"); if (c) ask(c.dataset.q); });
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if (e.key === "/" && !typing && !open) { e.preventDefault(); setOpen(true); }
    else if (e.key === "Escape" && open) setOpen(false);
  });
  window.addEventListener("hashchange", () => {
    if (!open) return;
    updateContext();
    if (!history.length) renderEmpty();
  });
  refreshStatus();
}
