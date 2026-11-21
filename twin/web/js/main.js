// App entry: theme, background, router.
import { store, toast } from "./core.js";
import { startSpins } from "./spins.js";
import * as twin from "./views/twin.js";
import * as check from "./views/check.js";
import * as scans from "./views/scans.js";
import * as trace from "./views/trace.js";
import { renderExplain, renderNext } from "./views/reasoning.js";
import { renderCards, renderTests } from "./views/cards.js";
import * as bench from "./views/bench.js";
import * as about from "./views/about.js";
import { initAssistant } from "./assistant.js";

const ROUTES = {
  twin: twin.render, scans: scans.render, check: check.render, trace: trace.render,
  explain: renderExplain, next: renderNext, cards: renderCards, tests: renderTests,
  bench: bench.render, about: about.render,
};

const main = document.getElementById("main");

function setThemeIcon() {
  const dark = document.documentElement.dataset.theme !== "light";
  document.querySelector("#themeBtn i").className = `ph ${dark ? "ph-sun" : "ph-moon"}`;
}
document.getElementById("themeBtn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("larmor-theme", next); } catch (e) { /* storage unavailable */ }
  setThemeIcon();
  route();
});

async function route() {
  const name = (location.hash.replace(/^#\//, "") || "twin").split("?")[0];
  const view = ROUTES[name] || ROUTES.twin;
  document.querySelectorAll(".rail a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#/${name}`));
  // Each navigation draws into a fresh container: a slow page that finishes late writes into a detached
  // element instead of overwriting the page the user has moved on to.
  const host = document.createElement("div");
  main.replaceChildren(host);
  try { await view(host); } catch (err) { console.error(err); toast(`Could not draw this page: ${err.message}`, true); }
}

async function boot() {
  setThemeIcon();
  startSpins(document.getElementById("spins"));
  main.innerHTML = `<div class="view"><div class="skeleton" style="height:28px;width:220px;margin-bottom:18px"></div><div class="skeleton" style="height:420px"></div></div>`;
  try { await store.load(); }
  catch (err) {
    main.innerHTML = `<div class="view"><div class="empty">Cannot reach the twin engine. Start it with <span class="mono">py -m uvicorn server:app --port 8765</span> in the twin folder. (${err.message})</div></div>`;
    return;
  }
  window.addEventListener("hashchange", route);
  route();
  initAssistant();          // the drawer is on every page; the model itself is warmed by the server at startup
}
boot();
