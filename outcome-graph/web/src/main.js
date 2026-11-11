import "./style.css";
import "./account.css";
import { createMascot } from "./mascot.js";
import { initAuth, accountWidget, authFetch, onMe, ready, signedIn, me, config as authConfig } from "./auth.js";
import Graph from "graphology";
import Sigma from "sigma";
import { createNodeBorderProgram } from "@sigma/node-border";

// ------------------------------------------------------------------ palette
const VERDICT = {  // EPA's answer to one ask; these words are used everywhere on the page
  adopted: { c: "#3ddc97", l: "Adopted", s: "Adopted", says: "EPA adopted" },
  partly_adopted: { c: "#f5c451", l: "Partly adopted", s: "Partly adopted", says: "EPA partly adopted" },
  already_required: { c: "#a98bff", l: "Already in the rule", s: "Already in the rule", says: "EPA said were already in the rule" },
  clarified: { c: "#7f8ea8", l: "Explained, no change", s: "Explained, no change", says: "EPA explained but did not change" },
  declined: { c: "#ff6b6b", l: "Declined", s: "Declined", says: "EPA declined" },
};
const OUTCOME = { won: "#3ddc97", partly: "#f5c451", lost: "#ff6b6b", no_change: "#55607a" };
const KIND = {
  chapter: { c: "#e8ecf4", l: "Chapter" },
  topic: { c: "#6ea8ff", l: "Topic" },
  ask: { c: "#cfd6e4", l: "Ask" },
  section: { c: "#2fd4e6", l: "Rule section" },
  org: { c: "#8a96ad", l: "Commenter" },
};
const STAKE = {
  state: ["#6ea8ff", "States"], utility: ["#2fd4e6", "Utilities"],
  trade: ["#f59e6b", "Trade groups"], advocacy: ["#ff7ab6", "Advocacy"],
  local: ["#a3e635", "Local gov't"], federal: ["#facc15", "Federal"],
  industry: ["#c084fc", "Industry"], labor: ["#fb923c", "Labor"],
  academic: ["#94a3b8", "Academic"], individual: ["#8a96ad", "Individuals"],
  campaign: ["#e879f9", "Form-letter campaigns"],
  other: ["#8a96ad", "Other or untagged"], unknown: ["#5b6579", "Untagged"],
};
const ORG_MUTED = "#8a96ad";
const BG = "#080a11";

import { initShared, track, openPalette, reportProblem } from "./shared.js";
const $ = (s) => document.querySelector(s);
const TOUCH = matchMedia("(hover: none)").matches;
const tapWord = TOUCH ? "Tap" : "Click";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const short = (s, n = 46) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
function mix(hex, to = BG, t = 0.85) {
  if (!hex.startsWith("#")) return hex;
  const a = parseInt(hex.slice(1), 16), b = parseInt(to.slice(1), 16);
  const ch = (sh) => Math.round(((a >> sh) & 255) * (1 - t) + ((b >> sh) & 255) * t);
  return `#${((1 << 24) | (ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).slice(1)}`;
}
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// ------------------------------------------------------------------ state
const st = {
  data: null, nodes: {}, hovered: null, selected: null,
  focus: new Set(),     // nodes lit by hover or selection
  visited: new Set(),   // nodes the agent read
  cited: new Set(),     // nodes the agent's answer cites
  labelSet: new Set(),  // nodes that get a text label right now
  conv: null, history: [], draftId: null, busy: false, selT0: 0,
  columns: {},          // topic code -> [topic id, ask ids...]
  order: {},            // ask/topic id -> clockwise position 0..1, for the intro sweep
  intro: null,          // start time of the "asked, then decided" intro
  tween: null, moved: new Set(), more: 0,
  filter: { verdict: "", changed: false, group: "" }, askGroups: {},
};
const graph = new Graph({ multi: false, type: "undirected" });
let renderer;

function nodeColor(n) {
  if (n.kind === "ask") return VERDICT[n.verdict]?.c || "#999";
  if (n.kind === "org") return STAKE[n.stakeholder]?.[0] || ORG_MUTED;
  return KIND[n.kind].c;
}
function nodeSize(n) {  // in graph units: dots are 1 unit apart
  switch (n.kind) {
    case "ask": return 0.46;
    case "topic": return 0.3;
    case "chapter": return 0.3;
    case "section": return 0.55 + Math.sqrt(n.changed || 0) * 0.03;
    case "org": return 0.3 + Math.min(Math.sqrt(n.comments || 0) * 0.04, 0.45);
  }
  return 0.4;
}
const isLit = (id) => st.focus.has(id) || st.visited.has(id) || st.selected === id;
const active = () => st.focus.size > 0 || st.visited.size > 0;

// ------------------------------------------------------------------ load
// Which rule this page shows: ?d=PFAS (short name) or ?d=<docket id>; default from the server.
const RULE = { docket: null, meta: null, all: {} };
const api = (url) => url + (url.includes("?") ? "&" : "?") + "docket=" + encodeURIComponent(RULE.docket);

async function pickRule() {
  try {
    const r = await (await fetch("/api/dockets")).json();
    RULE.all = r.dockets;
    const want = decodeURIComponent(location.pathname.match(/^\/rule\/([^/]+)/)?.[1] || "") || new URLSearchParams(location.search).get("d");
    const hit = Object.values(r.dockets).find((m) => want && (m.short?.toLowerCase() === want.toLowerCase() || m.docket === want));
    RULE.docket = hit ? hit.docket : r.default in r.dockets ? r.default : Object.keys(r.dockets)[0];
  } catch {
    RULE.docket = "EPA-HQ-OW-2022-0801";
  }
  RULE.meta = RULE.all[RULE.docket] || {};
  const m = RULE.meta;
  if (m.title) {
    $("#brand h1").textContent = m.title;
    $("#brand .sub").innerHTML = `EPA · proposed ${esc(m.proposed)} → final ${esc(m.final)} · <span id="stat-line"></span>`;
    document.title = `${m.short} · Oversight`;
  }
  const rules = Object.values(RULE.all).sort((a, b) => String(a.final).slice(-4) - String(b.final).slice(-4));
  if (rules.length > 1) {
    const nav = document.createElement("nav");
    nav.id = "rules";
    nav.innerHTML = rules.map((m) => `<a href="/rule/${esc(m.short)}" class="${m.docket === RULE.docket ? "on" : ""}" title="${esc(m.title)}, final ${esc(m.final)}">${esc(m.short)} <span>${esc(String(m.final).slice(-4))}</span></a>`).join("");
    $("#brand").appendChild(nav);
  }
}

let LD_IRIS = null;
try { LD_IRIS = createMascot($("#ld-iris"), { size: 150, interactive: false, ground: false }); LD_IRIS.setState("thinking"); } catch { /* no WebGL */ }

async function load() {
  await Promise.all([pickRule(), initAuth()]);
  accountWidget($("#account"), { compact: true });
  const data = await (await fetch(api("/api/graph"))).json();
  st.data = data;
  for (const n of data.nodes) st.nodes[n.id] = n;
  for (const n of data.nodes) {
    if (n.kind === "org" && !n.drawn) continue;
    const ringed = (n.kind === "ask" && n.changed) || n.kind === "section";
    graph.addNode(n.id, {
      x: n.x, y: n.y, size: nodeSize(n), color: nodeColor(n), label: n.label, kind: n.kind,
      type: ringed ? "ring" : "circle",
      borderColor: n.kind === "section" ? "#2fd4e6" : "#f4f7fb",
      zIndex: { section: 4, org: 3, topic: 2, ask: 1, chapter: 0 }[n.kind],
    });
    if (n.kind === "topic") (st.columns[n.code] ||= []).unshift(n.id);
    if (n.kind === "ask") (st.columns[n.code] ||= []).push(n.id);
  }
  for (const e of data.edges) {
    if (!graph.hasNode(e.source) || !graph.hasNode(e.target) || graph.hasEdge(e.source, e.target)) continue;
    graph.addEdge(e.source, e.target, { kind: e.kind, weight: e.weight, size: 0.6 });
  }

  renderer = new Sigma(graph, $("#graph"), {
    nodeProgramClasses: {
      ring: createNodeBorderProgram({
        borders: [
          { size: { value: 0.2 }, color: { attribute: "borderColor" } },
          { size: { value: 0.18 }, color: { value: BG } },
          { size: { fill: true }, color: { attribute: "color" } },
        ],
      }),
    },
    defaultNodeType: "circle",
    itemSizesReference: "positions",
    zoomToSizeRatioFunction: (r) => r,
    renderLabels: false,          // every label is drawn by the overlay, with collision checks
    enableEdgeEvents: false,
    zIndex: true,
    minCameraRatio: 0.08,
    maxCameraRatio: 1.8,
    stagePadding: innerWidth <= 820 ? 56 : 150,  // phones: the ring gets the width, labels squeeze in
    allowInvalidContainer: true,  // the stage can be 0 wide for a frame while a phone rotates
    defaultDrawNodeHover: () => {},
    nodeReducer, edgeReducer,
  });

  const TAU = Math.PI * 2;
  for (const n of data.nodes) {
    if (n.kind !== "ask" && n.kind !== "topic") continue;
    st.order[n.id] = (((Math.PI / 2 - Math.atan2(n.y, n.x)) % TAU) + TAU) % TAU / TAU;
  }
  st.askOrder = data.nodes.filter((n) => n.kind === "ask").map((n) => [st.order[n.id], n.verdict]).sort((a, b) => a[0] - b[0]);
  for (const e of data.edges) {
    if (e.kind !== "supports" && e.kind !== "opposes") continue;
    const [o, a] = st.nodes[e.source].kind === "org" ? [e.source, e.target] : [e.target, e.source];
    (st.askGroups[a] ||= new Set()).add(st.nodes[o].stakeholder);
  }
  try {  // the hosted copy runs without the agent: drop the Ask tab, open on the Scoreboard
    const h = await (await fetch("/api/health")).json();
    if (h.agent === false) {
      document.querySelector('#tabs [data-tab="ask"]')?.remove();
      document.querySelector('#tabs [data-tab="coach"]')?.remove();
      $("#tab-ask")?.remove();
      $("#tab-coach")?.remove();
      st.noAgent = true;
    }
  } catch { /* health check is best effort */ }
  wireGraph();
  buildLegend();
  buildScore();
  if (!st.noAgent) { intro(); coachIntro(); }
  $("#stat-line").textContent = data.stats.comments
    ? `${fmt(data.stats.comments)} comments EPA answered · ${fmt(data.stats.orgs)} commenters`
    : `${fmt(data.stats.asks)} asks · EPA summarized comments without naming commenters`;
  const cam = renderer.getCamera();
  cam.setState({ x: 0.5, y: 0.5, ratio: 1.16, angle: 0 });
  cam.animate({ x: 0.5, y: 0.5, ratio: 1.08 }, { duration: 2600, easing: "quadraticOut" });
  startIntro();
  window.__og = { st, graph, select, clearSelection, vp: (id) => vp(id), renderer };  // used by the screenshot tests
  requestAnimationFrame(fxLoop);
  if (st.noAgent) tab("score");
  LD_IRIS?.react("happy");
  setTimeout(() => $("#loading")?.classList.add("gone"), 450);
  setTimeout(() => { LD_IRIS?.dispose(); $("#loading")?.remove(); }, 1200);
  if (!st.noAgent) irisInit();
  const h = decodeURIComponent(location.hash.slice(1));  // old links: #ask:1.2:3
  if (h && st.nodes[h]) history.replaceState({}, "", `${location.pathname}?n=${encodeURIComponent(h)}`);
  setTimeout(applyURL, 300);
  addResetView();
  phoneToggle();
  setTimeout(firstVisitHint, 2600);
}
function phoneToggle() {  // phones: the list can take the whole screen, with the map one tap away
  const b = document.createElement("div");
  b.id = "view-toggle";
  b.innerHTML = `<button type="button" data-v="map" class="on">Map</button><button type="button" data-v="list">List</button>`;
  document.body.appendChild(b);
  b.querySelectorAll("button").forEach((x) => x.addEventListener("click", () => {
    const list = x.dataset.v === "list";
    b.querySelectorAll("button").forEach((y) => y.classList.toggle("on", y === x));
    document.body.classList.toggle("list-mode", list);
    if (list && !st.listOpen && !st.selected) showList();
    track("phone:view", { v: x.dataset.v });
  }));
}
function firstVisitHint() {
  try { if (localStorage.getItem("ov-hint")) return; } catch { return; }
  const el = document.createElement("div");
  el.id = "hint-card";
  el.innerHTML = `<b>New here?</b> Each dot is one thing commenters asked EPA for. Pick a group under <i>Argued by</i>, then <i>See the list</i> for their record. <kbd>⌘K</kbd> searches everything. <button type="button" aria-label="Dismiss">Got it</button>`;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("on"));
  const done = () => { el.classList.remove("on"); setTimeout(() => el.remove(), 300); try { localStorage.setItem("ov-hint", "1"); } catch { /* fine */ } };
  el.querySelector("button").addEventListener("click", done);
  setTimeout(done, 16000);
}
function addResetView() {
  const b = document.createElement("button");
  b.id = "reset-view"; b.type = "button"; b.textContent = "Reset view"; b.hidden = true;
  document.body.appendChild(b);
  const cam = renderer.getCamera();
  b.addEventListener("click", () => { clearSelection(); cam.animate({ x: 0.5, y: 0.5, ratio: 1.08, angle: 0 }, { duration: 500 }); });
  cam.on("updated", (c) => { b.hidden = Math.abs(c.ratio - 1.08) < 0.05 && Math.abs(c.x - 0.5) < 0.02 && Math.abs(c.y - 0.5) < 0.02; });
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName) && st.selected) {
      clearSelection(); cam.animate({ x: 0.5, y: 0.5, ratio: 1.08 }, { duration: 500 });
    }
  });
}

// ------------------------------------------------------------------ intro: asked, then decided
// Phase 1: every ask appears in grey, clockwise in EPA's document order (what commenters asked).
// Phase 2: a sweep goes round and gives each ask EPA's verdict colour (what EPA decided).
const APPEAR = 1300, REVEAL0 = 1500, REVEAL = 1500, INTRO_END = REVEAL0 + REVEAL + 300;
const ASKED_GREY = "#46526b";
function startIntro() {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  st.intro = performance.now();
}
const ease = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
function introState(id) {
  if (st.intro == null) return 2;
  const o = st.order[id];
  if (o === undefined) return 2;
  const t = performance.now() - st.intro;
  if (t < o * APPEAR) return 0;            // not yet asked
  if (t < REVEAL0 + o * REVEAL) return 1;  // asked, EPA has not answered
  return 2;                                // decided
}

// ------------------------------------------------------------------ filter
const filterOn = () => !!(st.filter.verdict || st.filter.changed || st.filter.group);
function matches(n) {
  if (n.kind !== "ask") return true;
  if (st.filter.verdict && n.verdict !== st.filter.verdict) return false;
  if (st.filter.changed && !n.changed) return false;
  if (st.filter.group && !st.askGroups[n.id]?.has(st.filter.group)) return false;
  return true;
}
// ------------------------------------------------------------------ the list: the asks behind a filter
function listTitle() {
  const f = st.filter, rule = RULE.meta?.short || "";
  const who = f.group ? STAKE[f.group]?.[1] : "Commenters";
  let t = `${who} on ${rule}`;
  if (f.verdict) t += `: asks ${VERDICT[f.verdict].says}`;
  if (f.changed) t += f.verdict ? ", that changed the rule" : ": asks that changed the final rule";
  return t;
}
async function showList({ keepTab = false, ids = null, title = null } = {}) {
  if (!keepTab) track("open:list", { filter: st.filter, ids: !!ids });
  st.listOpen = { ids, title };
  if (!keepTab) { syncURL(true); tab("inspect"); }
  const box = $("#inspect");
  const f = st.filter;
  const qs = new URLSearchParams({ docket: RULE.docket });
  if (ids) qs.set("ids", ids.join(","));
  else {
    if (f.verdict) qs.set("verdict", f.verdict);
    if (f.changed) qs.set("changed", "true");
    if (f.group) qs.set("group", f.group);
  }
  box.innerHTML = `<div class="empty">Loading the list…</div>`;
  const r = await fetch(`/api/asks?${qs}`).then((x) => x.json()).catch(() => null);
  if (!r) { box.innerHTML = `<div class="empty">The list didn't load. Try again.</div>`; return; }
  const a = r.asks;
  const cnt = (p) => a.filter(p).length;
  const won = cnt((x) => ["adopted", "partly_adopted"].includes(x.verdict)), lost = cnt((x) => x.verdict === "declined");
  let head = `${fmt(r.total)} ask${r.total === 1 ? "" : "s"} · ${fmt(won)} adopted or partly · ${fmt(lost)} declined · ${fmt(cnt((x) => x.changed))} changed the rule`;
  let groupsOf = null;
  if (f.group && !ids) {  // the group's own score: which side it took, and whether that side won
    const o = (k) => cnt((x) => x.outcome === k);
    head = `${fmt(r.total)} asks they took a side on · won ${fmt(o("won"))} · partly ${fmt(o("partly"))} · lost ${fmt(o("lost"))} · no decision ${fmt(o("no_change"))} · ${fmt(cnt((x) => x.changed))} changed the rule`;
    groupsOf = [["won", "Won"], ["partly", "Partly"], ["lost", "Lost"], ["no_change", "No decision"]];
  }
  const sections = groupsOf
    ? groupsOf.map(([k, l]) => [l, a.filter((x) => x.outcome === k), OUTCOME[k]])
    : Object.entries(VERDICT).map(([k, v]) => [v.l, a.filter((x) => x.verdict === k), v.c]);
  const row = (x) => `<div class="li" data-id="${x.id}">
      <div class="li-top"><span class="pill" style="--vc:${VERDICT[x.verdict].c}">${VERDICT[x.verdict].s}</span>${x.side === "against" ? `<span class="tag against">they argued against</span>` : ""}${x.changed ? `<span class="tag">changed the rule</span>` : ""}<span class="li-code">${esc(x.code || "")}</span></div>
      <div class="li-ask">${esc(x.label)}</div>
      ${x.quote ? `<div class="li-epa"><b>EPA:</b> ${esc(short(x.quote, 210))}${x.page ? ` <span class="pg">p. ${x.page}</span>` : ""}</div>` : ""}
      ${x.final_rule_change ? `<div class="li-eff"><b>Final rule:</b> ${esc(short(x.final_rule_change, 180))}</div>` : ""}
      <div class="li-who">${x.asked_by.length ? `${x.side === "against" ? "Argued against by" : "Asked by"} ${esc(x.asked_by.join(", "))}${x.asked_by_n > x.asked_by.length ? ` +${x.asked_by_n - x.asked_by.length}` : ""}` : "EPA didn't name who asked"}</div>
    </div>`;
  box.innerHTML = `<div class="list">
    <div class="ins-kind">List</div>
    <div class="ins-title">${esc(title || listTitle())}</div>
    <div class="list-head">${head}</div>
    <div class="list-tools"><button type="button" class="ghost" id="l-copy">Copy as text</button><button type="button" class="ghost" id="l-link">Copy link</button>${filterOn() && !ids ? `<button type="button" class="ghost" id="l-clear">Clear filters</button>` : ""}</div>
    ${r.total > a.length ? `<div class="note">Showing the first ${fmt(a.length)}.</div>` : ""}
    ${sections.filter(([, xs]) => xs.length).map(([l, xs, c]) => `<details class="fold" open><summary><span class="d" style="background:${c}"></span>${esc(l)} <span class="n">${xs.length}</span></summary>${xs.map(row).join("")}</details>`).join("")}
  </div>`;
  box.querySelectorAll(".li").forEach((el) => el.addEventListener("click", () => openNode(el.dataset.id)));
  $("#l-copy").addEventListener("click", (e) => {
    const lines = [title || listTitle(), head, ""];
    for (const [l, xs] of sections) if (xs.length) {
      lines.push(`${l} (${xs.length})`);
      for (const x of xs) lines.push(`- ${x.label}${x.quote ? `\n  EPA: "${x.quote}"${x.page ? ` (Response to Comments, p. ${x.page})` : ""}` : ""}${x.final_rule_change ? `\n  Final rule: ${x.final_rule_change}` : ""}`);
      lines.push("");
    }
    lines.push(location.href);
    copy(lines.join("\n"), e.target, "Copied");
  });
  $("#l-link").addEventListener("click", (e) => copy(location.href, e.target, "Link copied"));
  $("#l-clear")?.addEventListener("click", () => { st.listOpen = null; setFilter({ verdict: "", changed: false, group: "" }); box.innerHTML = `<div class="empty">Filters cleared. ${tapWord} a dot to see EPA's words, or pick a filter below the map.</div>`; });
  box.scrollTop = 0;
}
function copy(text, btn, done = "Copied") {
  navigator.clipboard?.writeText(text).then(() => {
    const t = btn.textContent; btn.textContent = done; setTimeout(() => { btn.textContent = t; }, 1600);
  }).catch(() => {});
}

// ------------------------------------------------------------------ the URL holds the view, so it can be shared
let urlReady = false;
function syncURL(push = false) {
  if (!urlReady) return;
  const qs = new URLSearchParams();
  const f = st.filter;
  if (st.selected) qs.set("n", st.selected);
  if (f.verdict) qs.set("v", f.verdict);
  if (f.changed) qs.set("changed", "1");
  if (f.group) qs.set("who", f.group);
  const t = document.querySelector("#tabs button.on")?.dataset.tab;
  if (t && t !== "ask" && !st.selected) qs.set("tab", t);
  if (st.listOpen && !st.selected) qs.set("list", "1");
  const url = location.pathname + (qs.toString() ? "?" + qs : "");
  if (url === location.pathname + location.search) return;
  history[push ? "pushState" : "replaceState"]({}, "", url);
}
function applyURL() {
  const qs = new URLSearchParams(location.search);
  urlReady = false;
  setFilter({ verdict: VERDICT[qs.get("v")] ? qs.get("v") : "", changed: qs.get("changed") === "1", group: STAKE[qs.get("who")] ? qs.get("who") : "" });
  const n = qs.get("n");
  if (n && st.nodes[n]) openNode(n);
  else if (qs.get("list")) showList();
  else if (qs.get("tab")) tab(qs.get("tab"));
  urlReady = true;
  const q = qs.get("ask");  // links from scorecards and the palette: /rule/PFAS?ask=...
  if (q && !st.noAgent) {
    qs.delete("ask");
    history.replaceState({}, "", location.pathname + (qs.toString() ? "?" + qs : ""));
    tab("ask");
    setTimeout(() => { const v = viewFor(q); if (v && (st.offline || st.left?.ask === 0)) v(); else ask(q); }, 500);
  }
}
addEventListener("popstate", () => { urlReady = false; clearSelection(); st.listOpen = null; applyURL(); });
function filterPhrase() {
  const f = st.filter;
  let t = f.verdict ? `asks ${VERDICT[f.verdict].says}` : "asks";
  if (f.changed) t += f.verdict ? ", that changed the final rule" : " that changed the final rule";
  if (f.group) t += `, argued by ${STAKE[f.group][1].toLowerCase()}`;
  return t;
}
function setFilter(patch) {
  Object.assign(st.filter, patch);
  document.querySelectorAll("#legend .key[data-v]").forEach((b) => b.classList.toggle("on", b.dataset.v === st.filter.verdict));
  document.querySelectorAll("#legend .key[data-v]").forEach((b) => b.classList.toggle("dim", !!st.filter.verdict && b.dataset.v !== st.filter.verdict));
  $("#f-changed")?.classList.toggle("on", !!st.filter.changed);
  $("#f-all")?.classList.toggle("on", !filterOn());
  const dd = $("#f-group");
  if (dd) {  // show the chosen group on the dropdown button
    const g = st.filter.group;
    dd.querySelector(".dd-val").textContent = g ? STAKE[g]?.[1] || g : "anyone";
    dd.querySelector(".dd-btn .dd-dot").style.background = g ? STAKE[g]?.[0] : "";
    dd.classList.toggle("set", !!g);
    dd.querySelectorAll(".dd-opt").forEach((o) => o.classList.toggle("on", o.dataset.v === g));
  }
  st.filterCount = st.data.nodes.filter((n) => n.kind === "ask" && matches(n)).length;
  // counts follow the other filters: pick Utilities and each verdict shows the utilities' split
  const asks = st.data.nodes.filter((n) => n.kind === "ask");
  const base = (n) => (!st.filter.group || st.askGroups[n.id]?.has(st.filter.group)) && (!st.filter.changed || n.changed);
  document.querySelectorAll("#legend .key[data-v]").forEach((b) => {
    b.querySelector(".n").textContent = fmt(asks.filter((n) => base(n) && n.verdict === b.dataset.v).length);
  });
  const chN = asks.filter((n) => n.changed && (!st.filter.group || st.askGroups[n.id]?.has(st.filter.group)) && (!st.filter.verdict || n.verdict === st.filter.verdict)).length;
  $("#f-changed .n").textContent = fmt(chN);
  $("#f-changed").classList.toggle("na", !chN && !st.filter.changed);
  $("#f-changed").title = !chN && st.filter.verdict ? `No ${VERDICT[st.filter.verdict].l.toLowerCase()} ask changed the final rule` : "";
  $("#f-all .n").textContent = fmt(asks.filter((n) => !st.filter.group || st.askGroups[n.id]?.has(st.filter.group)).length);
  const fc = $("#f-count");
  fc.innerHTML = !filterOn() ? "" : st.filterCount
    ? `${fmt(st.filterCount)} of ${fmt(st.data.stats.asks)} <button type="button" class="lg-list">See the list →</button>`
    : `<span class="none">No asks match: ${st.filter.changed && st.filter.verdict ? `no ${esc(VERDICT[st.filter.verdict].l.toLowerCase())} ask changed the final rule` : "try fewer filters"}</span>`;
  fc.querySelector(".lg-list")?.addEventListener("click", () => showList());
  if (st.listOpen) showList({ keepTab: true });
  syncURL();
  if (filterOn()) {  // one soft ripple on each match, travelling clockwise, so the eye finds them
    let i = 0;
    for (const n of st.data.nodes) if (n.kind === "ask" && matches(n) && i++ < 400) pulse(n.id, st.filter.changed && !st.filter.verdict ? "#ffffff" : VERDICT[n.verdict].c, st.order[n.id] * 600);
  }
  renderer.refresh({ skipIndexation: true });
}

// ------------------------------------------------------------------ reducers
function hiddenNode(n) {
  return false;
}
function nodeReducer(id, attrs) {
  const n = st.nodes[id];
  const out = { ...attrs };
  if (hiddenNode(n)) { out.hidden = true; return out; }
  const phase = introState(id);
  if (phase === 0) { out.hidden = true; return out; }
  if (phase === 1) { out.color = ASKED_GREY; out.borderColor = ASKED_GREY; return out; }
  const lit = isLit(id);
  if (filterOn() && id !== st.selected && ((n.kind === "ask" && !matches(n)) || (n.kind === "topic" && !lit))) {
    out.color = mix(attrs.color, BG, 0.87); out.borderColor = mix(attrs.borderColor, BG, 0.87); out.zIndex = 0;
    return out;
  }
  if (filterOn() && n.kind === "ask" && matches(n)) out.size = attrs.size * 1.3;  // matches stand out
  // commenters, sections and chapter anchors only appear when something points at them
  if (n.kind === "chapter" || ((n.kind === "org" || n.kind === "section") && !lit)) { out.hidden = true; return out; }
  if (active() && !lit) {
    out.color = mix(attrs.color, BG, 0.84);
    out.borderColor = mix(attrs.borderColor, BG, 0.84);
    out.zIndex = 0;
  } else if (active()) {
    out.zIndex = 10;
  }
  if (n.kind === "topic" && !lit) out.color = mix(attrs.color, BG, active() ? 0.9 : 0.55);
  return out;
}
function edgeReducer(id, attrs) {  // links are drawn on the overlay as curves with flowing comments
  return { ...attrs, hidden: true };
}
function shownLinks() {
  const out = [];
  const seen = new Set();
  const add = (s, t, k, w, cited = false) => {
    const key = s < t ? s + "|" + t : t + "|" + s;
    if (seen.has(key) || hiddenNode(st.nodes[s]) || hiddenNode(st.nodes[t])) return;
    seen.add(key);
    out.push({ s, t, k, w, cited });
  };
  const pivot = st.hovered && st.nodes[st.hovered].kind !== "ask" ? st.hovered : st.selected;
  if (pivot && graph.hasNode(pivot)) {
    graph.forEachEdge(pivot, (e, a, s, t) => {
      if (["supports", "opposes", "cites", "about"].includes(a.kind)) add(s, t, a.kind, a.weight);
    });
    const n = st.nodes[pivot];
    if (n.kind === "topic") for (const ask of st.columns[n.code] || []) {
      if (graph.hasNode(ask)) graph.forEachEdge(ask, (e, a, s, t) => {
        if ((a.kind === "supports" || a.kind === "opposes") && isLit(s) && isLit(t)) add(s, t, a.kind, a.weight);
      });
    }
  }
  for (const id of st.cited) if (graph.hasNode(id) && st.nodes[id].kind === "ask") graph.forEachEdge(id, (e, a, s, t) => {
    if ((a.kind === "supports" || a.kind === "opposes") && st.cited.has(s) && st.cited.has(t)) add(s, t, a.kind, a.weight, true);
  });
  return out.sort((x, y) => y.w - x.w).slice(0, 220);
}

// ------------------------------------------------------------------ commenters gather beside what they argued
// On selection, the commenters involved move into a tidy arc just inside the ring, centred on the
// ask or topic: supporters on one side, opponents on the other. Short curves, nothing crossing the ring.
function sideOf(org, asks) {
  let f = 0, a = 0;
  for (const ask of asks) {
    if (!graph.hasNode(ask) || !graph.hasEdge(org, ask)) continue;
    const k = graph.getEdgeAttribute(graph.edge(org, ask), "kind");
    if (k === "supports") f++; else if (k === "opposes") a++;
  }
  return a > f ? 1 : 0;
}
function arrange(id) {
  restorePositions();
  const n = st.nodes[id];
  const R = st.data.stats.rings;
  const items = [];
  if (n.kind === "org") {
    return;  // commenters keep their home spot, near the topics they wrote on
  } else if (n.kind === "ask" || n.kind === "topic") {
    const asks = n.kind === "ask" ? [id] : (st.columns[n.code] || []).slice(1);
    const orgs = [...st.focus].filter((x) => st.nodes[x]?.kind === "org" && graph.hasNode(x));
    const w = (o) => asks.reduce((acc, a) => acc + (graph.hasEdge(o, a) ? graph.getEdgeAttribute(graph.edge(o, a), "weight") : 0), 0);
    // show the most-quoted named organisations; the rest are counted, not drawn
    const named = (o) => {  // placeholders like "(web)" or "(name illegible)" rank with individuals
      const nd = st.nodes[o];
      return nd.stakeholder === "individual" || nd.stakeholder === "unknown" || /^\(|^anonymous|illegible/i.test(nd.label) ? 1 : 0;
    };
    orgs.sort((x, y) => named(x) - named(y) || w(y) - w(x));
    const CAP = 18;
    st.more = Math.max(0, orgs.length - CAP);
    for (const o of orgs.slice(CAP)) st.focus.delete(o);
    orgs.length = Math.min(orgs.length, CAP);
    orgs.sort((x, y) => sideOf(x, asks) - sideOf(y, asks) || w(y) - w(x));
    st.moreAt = anchor0(n);
    // name the commenters that are actually drawn; collisions decide how many fit at this zoom
    st.labelSet = new Set([...(n.kind === "ask" ? [`topic:${n.code}`] : []), ...[...orgs].sort((x, y) => w(y) - w(x))]);
    const anchor = Math.atan2(n.y, n.x);
    const GAP = 2.5, SPAN = 1.6;
    let i = 0, r = R.r0 - 9;
    while (i < orgs.length && r > 6) {
      const cap = Math.max(1, Math.floor((SPAN * r) / GAP));
      const row = orgs.slice(i, i + cap);
      row.forEach((o, j) => {
        const ang = anchor + ((row.length - 1) / 2 - j) * (GAP / r);
        items.push([o, r * Math.cos(ang), r * Math.sin(ang)]);
      });
      i += cap;
      r -= 3;
    }
    st.moreR = r + 0.8;
  }
  if (!items.length) return;
  st.tween = {
    t0: performance.now(), dur: 650,
    items: items.map(([o, x, y]) => {
      st.moved.add(o);
      return [o, x * 0.55, y * 0.55, x, y];  // rise outward from the centre toward the ring
    }),
  };
}
function anchor0(n) { return Math.atan2(n.y, n.x); }
function restorePositions() {
  st.tween = null;
  for (const o of st.moved) {
    const n = st.nodes[o];
    graph.mergeNodeAttributes(o, { x: n.x, y: n.y });
  }
  st.moved.clear();
}
function stepTween(now) {
  const T = st.tween;
  if (!T) return;
  const k = ease((now - T.t0) / T.dur);
  for (const [o, x0, y0, x1, y1] of T.items) graph.mergeNodeAttributes(o, { x: x0 + (x1 - x0) * k, y: y0 + (y1 - y0) * k });
  if (k >= 1) st.tween = null;
}

// ------------------------------------------------------------------ overlay: rings, labels, glow
// Two overlay layers: links, arcs and glows go UNDER the dots; labels, rings and ripples go over them.
const fx = $("#fx"), fxTop = fx.getContext("2d"), fxb = $("#fxb"), fxBot = fxb.getContext("2d");
let fxc = fxTop;
const pulses = [];
let chapterBoxes = [];
function pulse(id, color = "#8fb6ff", delay = 0) {
  if (!graph.hasNode(id)) return;
  pulses.push({ id, color, t0: performance.now() + delay });
}
function vp(id) {
  const d = renderer.getNodeDisplayData(id);
  if (!d) return null;
  const p = renderer.framedGraphToViewport(d);
  return { x: p.x, y: p.y, r: renderer.scaleSize(d.size), hidden: d.hidden };
}
function boxOverlaps(b, list) {
  return list.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
}
function wrap(text, n) {
  const out = [];
  let line = "";
  for (const w of text.split(/\s+/)) {
    if ((line + " " + w).trim().length > n && line) { out.push(line); line = w; } else line = (line + " " + w).trim();
  }
  if (line) out.push(line);
  return out;
}
function placeLines(lines, x, y, align, font, color, taken, pad = 4) {
  fxc.font = font;
  const lh = parseInt(font.match(/(\d+)px/)[1], 10) + 4;
  const w = Math.max(...lines.map((l) => fxc.measureText(l).width)), h = lh * lines.length;
  const bx = align === "right" ? x - w : x;
  const box = { x: bx - pad, y: y - h / 2 - pad, w: w + 2 * pad, h: h + 2 * pad };
  const W = fx.width / Math.min(window.devicePixelRatio || 1, 2);
  if (box.x < 4 || box.x + box.w > W - 4) return null;
  taken.push(box);
  fxc.fillStyle = "rgba(10,13,22,0.88)";  // a quiet card so the text reads over dots
  fxc.strokeStyle = "rgba(255,255,255,0.08)"; fxc.lineWidth = 1;
  fxc.beginPath(); fxc.roundRect(box.x - 3, box.y - 1, box.w + 6, box.h + 2, 7); fxc.fill(); fxc.stroke();
  fxc.textAlign = align; fxc.textBaseline = "middle";
  lines.forEach((l, i) => {
    const ly = y - h / 2 + lh * (i + 0.5);
    fxc.lineWidth = 4; fxc.strokeStyle = "rgba(8,10,17,0.92)"; fxc.strokeText(l, x, ly);
    fxc.fillStyle = color; fxc.fillText(l, x, ly);
  });
  return box;
}
function placeText(text, x, y, align, font, color, taken, pad = 3) {
  fxc.font = font;
  const w = fxc.measureText(text).width, h = parseInt(font.match(/(\d+)px/)[1], 10) + 2;
  const bx = align === "right" ? x - w : align === "center" ? x - w / 2 : x;
  const box = { x: bx - pad, y: y - h / 2 - pad, w: w + 2 * pad, h: h + 2 * pad };
  const W = fx.width / Math.min(window.devicePixelRatio || 1, 2), Hh = fx.height / Math.min(window.devicePixelRatio || 1, 2);
  if (box.x < 4 || box.y < 4 || box.x + box.w > W - 4 || box.y + box.h > Hh - 4 || boxOverlaps(box, taken)) return null;
  taken.push(box);
  fxc.textAlign = align;
  fxc.textBaseline = "middle";
  fxc.lineWidth = 4;
  fxc.strokeStyle = "rgba(8,10,17,0.92)";
  fxc.strokeText(text, x, y);
  fxc.fillStyle = color;
  fxc.fillText(text, x, y);
  return box;
}

function fxLoop(now) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const stage = document.getElementById("stage");
  const w = stage.clientWidth, h = stage.clientHeight;
  for (const cv of [fx, fxb]) {
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
  }
  for (const g of [fxTop, fxBot]) { g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h); }
  if (renderer && st.data) {
    if (st.tween) { stepTween(now); renderer.refresh(); }
    if (st.intro != null) {
      if (now - st.intro > INTRO_END) st.intro = null;
      renderer.refresh({ skipIndexation: true });
    }
    drawOverlay(now);
  }
  requestAnimationFrame(fxLoop);
}

function drawOverlay(now) {
  const R = st.data.stats.rings;
  const c = renderer.graphToViewport({ x: 0, y: 0 });
  const px = (r) => { const e = renderer.graphToViewport({ x: r, y: 0 }); return Math.hypot(e.x - c.x, e.y - c.y); };
  // screen y is flipped relative to graph y
  const at = (ang, r) => ({ x: c.x + Math.cos(ang) * px(r), y: c.y - Math.sin(ang) * px(r) });
  const focusChapters = new Set();
  for (const id of [...st.focus, ...st.visited, st.selected]) {
    const n = id && st.nodes[id];
    if (n && n.chapter) focusChapters.add(n.chapter);
  }
  const act = active();

  fxc = fxBot;
  // soft core
  const core = fxc.createRadialGradient(c.x, c.y, 0, c.x, c.y, px(R.r0));
  core.addColorStop(0, "rgba(70,110,200,0.10)"); core.addColorStop(1, "rgba(70,110,200,0)");
  fxc.fillStyle = core; fxc.beginPath(); fxc.arc(c.x, c.y, px(R.r0), 0, Math.PI * 2); fxc.fill();

  // chapter arcs under the columns
  const it = st.intro != null ? now - st.intro : Infinity;
  const arcFrac = (ang) => ((((Math.PI / 2 - ang) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) / (2 * Math.PI);
  for (const a of R.arcs) {
    const ch = a.id.slice(3);
    if (it < arcFrac(a.a0) * APPEAR) continue;
    const on = !act || focusChapters.has(ch);
    fxc.strokeStyle = on ? (act ? "#8fb6ff" : "#2c3a57") : "#161c2a";
    fxc.lineWidth = act && on ? 2 : 1.5;
    fxc.lineCap = "round";
    fxc.beginPath();
    const pad = 0.006;
    fxc.arc(c.x, c.y, px(R.r0 - 1.1), -(a.a0 + pad), -(a.a1 - pad), false);
    fxc.stroke();
  }

  // center summary
  if (it < REVEAL0 + REVEAL) {  // the sweep: EPA's answer travelling round the ring
    const f = (it - REVEAL0) / REVEAL;
    if (f > 0) {
      const ang = Math.PI / 2 - f * 2 * Math.PI;
      const p0 = at(ang, R.r0 - 2), p1 = at(ang, R.rmax + 2);
      const g = fxc.createLinearGradient(p0.x, p0.y, p1.x, p1.y);
      g.addColorStop(0, "rgba(143,182,255,0)"); g.addColorStop(0.5, "rgba(200,220,255,0.9)"); g.addColorStop(1, "rgba(143,182,255,0)");
      fxc.strokeStyle = g; fxc.lineWidth = 2;
      fxc.beginPath(); fxc.moveTo(p0.x, p0.y); fxc.lineTo(p1.x, p1.y); fxc.stroke();
      fxc.save();  // faint trailing wedge
      fxc.globalAlpha = 0.07;
      fxc.fillStyle = "#8fb6ff";
      fxc.beginPath(); fxc.moveTo(c.x, c.y);
      fxc.arc(c.x, c.y, px(R.rmax + 2), -ang - 0.35, -ang, false);
      fxc.closePath(); fxc.fill();
      fxc.restore();
    }
  }
  fxc = fxTop;
  const zoomedIn = renderer.getCamera().ratio < 0.7;  // the headline belongs to the overview only
  if (zoomedIn) st.centerHit = null;
  else if (!act && filterOn() && it >= INTRO_END) {
    const big = Math.max(18, px(R.r0) * 0.26);
    fxc.textAlign = "center"; fxc.textBaseline = "middle";
    fxc.fillStyle = st.filter.verdict ? VERDICT[st.filter.verdict].c : "#eef2f9";
    fxc.font = `650 ${big}px Inter, system-ui, sans-serif`;
    fxc.fillText(fmt(st.filterCount), c.x, c.y - big * 0.4);
    fxc.fillStyle = "#8c97ab";
    fxc.font = `500 ${Math.max(11, big * 0.2)}px Inter, system-ui, sans-serif`;
    fxc.fillText(filterPhrase(), c.x, c.y + big * 0.3);
    st.centerHit = null;
  } else if (!act) {
    const s = st.data.stats;
    let v = s.verdicts, asksN = s.asks, changedN = s.asks_with_rule_change;
    if (it < INTRO_END) {
      v = { adopted: 0, partly_adopted: 0, declined: 0 };
      asksN = 0;
      for (const [o, verdict] of st.askOrder) {
        if (it >= o * APPEAR) asksN++;
        if (it >= REVEAL0 + o * REVEAL && verdict in v) v[verdict]++;
      }
      changedN = Math.round(s.asks_with_rule_change * ease((it - REVEAL0) / REVEAL));
    }
    const big = Math.max(18, px(R.r0) * 0.26), tiny = px(R.r0) < 80;  // small ring: the number alone
    fxc.textAlign = "center"; fxc.textBaseline = "middle";
    fxc.fillStyle = "#eef2f9";
    fxc.font = `650 ${big}px Inter, system-ui, sans-serif`;
    fxc.fillText(fmt(asksN), c.x, tiny ? c.y : c.y - big * 0.55);
    if (!tiny) {
      fxc.fillStyle = "#8c97ab";
      fxc.font = `500 ${Math.max(11, big * 0.2)}px Inter, system-ui, sans-serif`;
      fxc.fillText("things commenters asked EPA for", c.x, c.y + big * 0.12);
      const parts = [[`${v.adopted + v.partly_adopted} adopted or partly`, "#3ddc97"], ["·", "#55607a"], [`${v.declined} declined`, "#ff6b6b"], ["·", "#55607a"], [`${changedN} changed the final rule`, "#e8ecf4"]];
      // the verdict line has to fit inside the ring's hole: one line if it fits, else two
      const fs = Math.max(11, big * 0.21), gap = 6, room = px(R.r0) * 1.55;
      fxc.font = `600 ${fs}px Inter, system-ui, sans-serif`;
      const lineW = (ps) => ps.reduce((a, [t]) => a + fxc.measureText(t).width, 0) + gap * (ps.length - 1);
      const lines = lineW(parts) <= room ? [parts] : [parts.slice(0, 3), parts.slice(4)];
      fxc.textAlign = "left";
      fxc.save();
      fxc.globalAlpha = it < REVEAL0 ? 0.25 : 1;
      lines.forEach((ps, li) => {
        let x = c.x - lineW(ps) / 2;
        ps.forEach(([t, col]) => { fxc.fillStyle = col; fxc.fillText(t, x, c.y + big * 0.55 + li * fs * 1.45); x += fxc.measureText(t).width + gap; });
      });
      fxc.restore();
    }
    st.centerHit = { x: c.x, y: c.y, r: big * 1.2 };
  } else st.centerHit = null;

  fxc = fxBot;
  // links: soft curves bending toward the centre, with comments flowing from commenter to ask
  const links = shownLinks();
  const dense = links.length > 60;
  for (const L of links) {
    const orgEnd = st.nodes[L.s].kind === "org" ? L.s : L.t, other = orgEnd === L.s ? L.t : L.s;
    const side = L.k === "supports" || L.k === "opposes";
    const a0 = side ? vp(orgEnd) : vp(L.s), a1 = side ? vp(other) : vp(L.t);
    if (!a0 || !a1 || a0.hidden || a1.hidden) continue;
    const mx = (a0.x + a1.x) / 2, my = (a0.y + a1.y) / 2;
    const cx2 = mx + (c.x - mx) * 0.18, cy2 = my + (c.y - my) * 0.18;
    const col = L.k === "opposes" ? "#ff6b6b" : L.k === "supports" ? "#6ea8ff" : "#2fd4e6";
    // links from an answer stay faint until you point at one of their ends
    const quiet = L.cited && st.hovered !== L.s && st.hovered !== L.t;
    fxc.strokeStyle = hexA(col, quiet ? 0.07 : dense ? 0.14 : 0.3);
    fxc.lineWidth = 1;
    fxc.beginPath(); fxc.moveTo(a0.x, a0.y); fxc.quadraticCurveTo(cx2, cy2, a1.x, a1.y); fxc.stroke();
    if (!side || quiet) continue;
    const seed = (L.s.length * 7 + L.t.charCodeAt(L.t.length - 1) * 13) % 100 / 100;
    {  // one wave of comments every 8 s, not a constant stream
      const t = ((now - st.selT0 - seed * 350) % 8000) / 1300;
      if (t < 0 || t > 1) continue;
      const u = 1 - t;
      const x = u * u * a0.x + 2 * u * t * cx2 + t * t * a1.x, y = u * u * a0.y + 2 * u * t * cy2 + t * t * a1.y;
      const g = fxc.createRadialGradient(x, y, 0, x, y, 5);
      g.addColorStop(0, hexA(col, 0.95)); g.addColorStop(1, hexA(col, 0));
      fxc.fillStyle = g; fxc.beginPath(); fxc.arc(x, y, 5, 0, Math.PI * 2); fxc.fill();
    }
  }

  // glow behind visited and selected nodes, then ripples
  const halo = (id, color, strength) => {
    const p = vp(id);
    if (!p || p.hidden) return;
    const r = Math.max(p.r * 3, 10);
    const g = fxc.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
    g.addColorStop(0, hexA(color, 0.4 * strength)); g.addColorStop(1, hexA(color, 0));
    fxc.fillStyle = g; fxc.beginPath(); fxc.arc(p.x, p.y, r, 0, Math.PI * 2); fxc.fill();
  };
  for (const id of st.cited) {
    const n = st.nodes[id];
    if (n && graph.hasNode(id)) halo(id, n.kind === "ask" ? VERDICT[n.verdict].c : "#8fb6ff", 0.6 + 0.25 * Math.sin(now / 450 + id.length));
  }
  if (st.selected && graph.hasNode(st.selected)) halo(st.selected, "#ffffff", 0.8);
  fxc = fxTop;
  if (st.hovered && graph.hasNode(st.hovered)) {  // crisp ring so you can see which dot the pointer holds
    const p = vp(st.hovered);
    if (p && !p.hidden) {
      fxc.strokeStyle = "#ffffff"; fxc.lineWidth = 1.5;
      fxc.beginPath(); fxc.arc(p.x, p.y, Math.max(p.r + 3, 6), 0, Math.PI * 2); fxc.stroke();
    }
  }
  for (let i = pulses.length - 1; i >= 0; i--) {
    const P = pulses[i];
    const t = (now - P.t0) / 1000;
    if (t < 0) continue;
    if (t > 1) { pulses.splice(i, 1); continue; }
    const p = vp(P.id);
    if (!p) continue;
    fxc.strokeStyle = hexA(P.color, (1 - t) * 0.85);
    fxc.lineWidth = 1.5 * (1 - t) + 0.5;
    fxc.beginPath(); fxc.arc(p.x, p.y, p.r + 3 + t * 22, 0, Math.PI * 2); fxc.stroke();
  }

  // labels: chapters first (they own the outside), then focused nodes by priority, never overlapping
  const fs = Math.round(Math.min(13, Math.max(11, px(1) * 1.6)));
  const taken = [];
  chapterBoxes = [];
  const sr = $("#stage").getBoundingClientRect();
  for (const sel of ["#brand", "#searchbox", "#legend"]) {  // keep labels off the page chrome
    const b = $(sel)?.getBoundingClientRect();
    if (b && b.width) taken.push({ x: b.left - sr.left - 6, y: b.top - sr.top - 6, w: b.width + 12, h: b.height + 12 });
  }
  // every lit dot is an obstacle, so no label is ever drawn across a circle
  const lit = new Set([...st.focus, ...st.labelSet, ...st.cited, ...st.visited]);
  if (st.selected) lit.add(st.selected);
  for (const id of lit) {
    if (!graph.hasNode(id)) continue;
    const q = vp(id);
    if (q && !q.hidden) taken.push({ x: q.x - q.r - 1, y: q.y - q.r - 1, w: 2 * q.r + 2, h: 2 * q.r + 2 });
  }
  const labelNode = (id) => {
    const n = st.nodes[id], p = vp(id);
    if (!p || p.hidden) return;
    const inner = Math.hypot(p.x - c.x, p.y - c.y) < px(R.r0 - 2);
    const right = inner ? p.x < c.x : p.x >= c.x;  // ring nodes label outward, inner nodes inward
    const zin = px(1) > 9;  // zoomed in: there is room for full names
    const text = n.kind === "topic" ? `${n.code} ${short(n.label, zin ? 80 : 44)}` : n.kind === "section" ? `${n.label} ${short(n.title || "", zin ? 70 : 28)}` : short(n.label, n.kind === "ask" ? (zin ? 90 : 56) : zin ? 70 : 40);
    const color = id === st.selected ? "#ffffff" : n.kind === "ask" ? mix(VERDICT[n.verdict].c, "#ffffff", 0.45) : n.kind === "org" ? "#dfe5ef" : "#c6d0e0";
    let out = n.kind === "topic" || n.kind === "ask" ? px(R.rmax - Math.hypot(n.x, n.y)) + 6 : 0;
    if (out > 90) out = 0;  // zoomed in: sit beside the dot instead of past the end of the column
    const ang = Math.atan2(c.y - p.y, p.x - c.x);
    const x = out ? p.x + Math.cos(ang) * out : p.x, y = out ? p.y - Math.sin(ang) * out : p.y;
    const font = `${id === st.selected ? 650 : 520} ${fs - 1}px Inter, system-ui, sans-serif`;
    const sides = right ? [1, -1] : [-1, 1];
    if (id === st.selected && (n.kind === "ask" || n.kind === "topic")) {  // full text, wrapped, never cut off
      const full = n.kind === "topic" ? `${n.code} ${n.label}` : n.label;
      for (const sd of sides) for (const width of [44, 34, 26])
        if (placeLines(wrap(full, width), sd > 0 ? x + p.r + 6 : x - p.r - 6, y, sd > 0 ? "left" : "right", font, color, taken)) return;
    }
    // try beside (outward first), then the other side, then above, then below
    for (const sd of sides) if (placeText(text, sd > 0 ? x + p.r + 6 : x - p.r - 6, y, sd > 0 ? "left" : "right", font, color, taken)) return;
    if (placeText(text, p.x, p.y - p.r - fs * 0.8, "center", font, color, taken)) return;
    placeText(text, p.x, p.y + p.r + fs * 0.8, "center", font, color, taken);
  };
  if (st.selected && graph.hasNode(st.selected)) labelNode(st.selected);
  fxc.save();
  fxc.globalAlpha = it === Infinity ? 1 : ease((it - 900) / 900);
  for (const a of R.arcs) {
    const ch = a.id.slice(3);
    const name = st.nodes[a.id]?.label;
    if (!name) continue;
    const on = !act || focusChapters.has(ch);
    const cos = Math.cos(a.mid), sin = Math.sin(a.mid);
    const align = cos > 0.3 ? "left" : cos < -0.3 ? "right" : "center";
    const color = on ? (act ? "#ffffff" : "#b4bed0") : "#3b4456";
    const font = `${on && act ? 650 : 560} ${fs}px Inter, system-ui, sans-serif`;
    let placed = null, r = R.rmax + 2.2;
    for (let k = 0; k < 6 && !placed; k++, r += 2.4) {
      const p = at(a.mid, r);
      const y = p.y - (align === "center" ? (sin > 0 ? fs * 0.4 : -fs * 0.4) : 0);
      placed = placeText(name, p.x, y, align, font, color, taken, 4);
      if (placed && k > 0) {  // leader line back to the arc when the label had to move out
        const q = at(a.mid, R.rmax + 1.2), e = at(a.mid, r - 0.8);
        fxc.strokeStyle = on ? "#3a4864" : "#1b2130"; fxc.lineWidth = 1;
        fxc.beginPath(); fxc.moveTo(q.x, q.y); fxc.lineTo(e.x, e.y); fxc.stroke();
      }
    }
    if (placed) chapterBoxes.push({ ...placed, id: a.id });
  }
  fxc.restore();
  const seen = new Set([st.selected]);
  for (const id of [...st.labelSet, ...st.cited]) {
    if (seen.has(id) || !graph.hasNode(id)) continue;
    seen.add(id);
    labelNode(id);
  }
}

// ------------------------------------------------------------------ interaction
function columnOf(id) {
  const n = st.nodes[id];
  return n && (n.kind === "ask" || n.kind === "topic") ? st.columns[n.code] || [id] : [id];
}
function focusFor(id) {
  const n = st.nodes[id];
  const s = new Set([id]);
  if (n.kind === "chapter") {
    for (const [code, ids] of Object.entries(st.columns)) if (st.nodes[ids[0]]?.chapter === n.chapter) ids.forEach((x) => s.add(x));
    return s;
  }
  columnOf(id).forEach((x) => s.add(x));
  if (graph.hasNode(id)) graph.forEachNeighbor(id, (nb) => { if (st.nodes[nb].kind !== "chapter") s.add(nb); });
  if (n.kind === "topic") {  // a topic also lights the commenters who argued its asks
    for (const a of columnOf(id)) if (graph.hasNode(a)) graph.forEachNeighbor(a, (nb) => { if (st.nodes[nb].kind === "org") s.add(nb); });
  }
  return s;
}
function topNeighbors(id, kind, k) {
  if (!graph.hasNode(id)) return [];
  return graph.edges(id).map((e) => [graph.opposite(id, e), graph.getEdgeAttribute(e, "weight")])
    .filter(([x]) => !kind || st.nodes[x].kind === kind).sort((a, b) => b[1] - a[1]).slice(0, k).map((x) => x[0]);
}
function labelsFor(id) {
  const n = st.nodes[id];
  if (n.kind === "topic") return new Set(topNeighbors(id, "org", 10));
  if (n.kind === "ask") return new Set([`topic:${n.code}`, ...topNeighbors(id, "org", 10)]);
  if (n.kind === "org") return new Set(topNeighbors(id, "ask", 6));
  if (n.kind === "section") return new Set(topNeighbors(id, "topic", 6));
  return new Set();
}

// Own hit-testing: dots are a few pixels apart, so sigma's exact-hit hover flickers between
// neighbours. Snap to the nearest visible node within a generous radius, and only switch when
// the pointer is clearly closer to another one.
function hitTest(x, y) {
  let best = null, bestD = Infinity, curD = Infinity;
  const unit = renderer.scaleSize(1);  // pixels per graph unit at this zoom
  graph.forEachNode((id) => {
    const d = renderer.getNodeDisplayData(id);
    if (!d || d.hidden) return;
    if (filterOn() && st.nodes[id]?.kind === "ask" && !matches(st.nodes[id]) && id !== st.selected) return;  // dimmed: not clickable
    const p = renderer.framedGraphToViewport(d);
    const dist = Math.hypot(p.x - x, p.y - y);
    if (id === st.hovered) curD = dist;
    if (dist < bestD) { bestD = dist; best = id; }
  });
  const reach = Math.max(9, unit * 0.75);
  if (st.hovered && curD < reach * 1.25 && curD < bestD * 1.35 + 2) return st.hovered;  // stickiness
  return bestD < reach ? best : null;
}
function setHover(node, tip) {
  if (node === st.hovered) return;
  st.hovered = node;
  if (node) {
    if (IRIS?.state === "sleepy") orbState("idle");
    lastActive = performance.now();
    irisGlance(node, 900);
    if (!st.selected && !st.visited.size) st.focus = columnOf(node).length > 1 ? new Set(columnOf(node)) : focusFor(node);
    tip.innerHTML = tipHtml(st.nodes[node]);
    tip.style.display = "block";
  } else {
    if (!st.selected && !st.visited.size) st.focus = new Set();
    tip.style.display = "none";
  }
  renderer.refresh({ skipIndexation: true });
}

function wireGraph() {
  const tip = document.createElement("div");
  tip.id = "tip";
  document.body.appendChild(tip);
  const local = (ev) => {
    const r = $("#graph").getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  };
  let raf = 0, lastEv = null;
  renderer.getMouseCaptor().on("mousemovebody", (e) => {
    lastEv = e.original;
    tip.style.left = lastEv.clientX + 16 + "px";
    tip.style.top = lastEv.clientY - 14 + "px";  // above the pointer, so it never covers labels
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const [x, y] = local(lastEv);
      setHover(hitTest(x, y), tip);
      const over = chapterBoxes.find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
      $("#graph").style.cursor = st.hovered || over ? "pointer" : "";
    });
  });
  $("#graph").addEventListener("mouseleave", () => setHover(null, tip));
  renderer.on("clickStage", (e) => {
    const [x, y] = local(e.event.original);
    const node = hitTest(x, y);
    if (node) { tip.style.display = "none"; return select(node, { fly: false }); }
    const hit = chapterBoxes.find((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
    const C = st.centerHit;
    if (C && !st.selected && Math.hypot(x - C.x, y - C.y) < C.r) { startIntro(); return; }
    if (hit) select(hit.id, { fly: false });
    else { clearSelection(); clearVisited(); }
  });
  renderer.on("clickNode", ({ node }) => { tip.style.display = "none"; select(st.hovered || node, { fly: false }); });
  renderer.getCamera().on("updated", () => { $("#hint").style.opacity = 0; });
}
function tipHtml(n) {
  const kinds = { chapter: "Chapter", topic: `Topic ${n.code}`, ask: VERDICT[n.verdict]?.l, section: "Rule section", org: STAKE[n.stakeholder]?.[1] || "Commenter" };
  let m = "";
  if (n.kind === "topic") m = `${fmt(n.comments)} comments quoted · ${Object.values(n.verdicts || {}).reduce((a, b) => a + b, 0)} asks`;
  if (n.kind === "ask") m = `Topic ${n.code} · ${n.for || 0} excerpts for, ${n.against || 0} against${n.changed ? " · changed the final rule" : ""}`;
  if (n.kind === "section") m = `${n.changed} of ${n.paragraphs} paragraphs changed`;
  if (n.kind === "org") { const r = n.record || {}; m = `${fmt(n.comments)} excerpts quoted · got their way on ${r.won || 0}, not on ${r.lost || 0}`; }
  const color = n.kind === "ask" ? VERDICT[n.verdict].c : n.kind === "org" ? STAKE[n.stakeholder]?.[0] : KIND[n.kind].c;
  return `<div class="k" style="color:${color}">${esc(kinds[n.kind] || n.kind)}</div><div>${esc(n.kind === "section" ? `${n.label} ${n.title}` : n.label)}</div>${m ? `<div class="m">${m}</div>` : ""}`;
}
function frame(ids) {
  const pts = ids.map((id) => graph.hasNode(id) && renderer.getNodeDisplayData(id)).filter(Boolean);
  if (!pts.length) return;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  renderer.getCamera().animate({ x: cx, y: cy, ratio: Math.max(0.6, Math.min(1, span * 1.3)) }, { duration: 750, easing: "cubicInOut" });
}
function select(id, { fly: doFly = true } = {}) {
  if (!st.nodes[id]) return;
  // a commenter clicked inside the ring glides home instead of jumping
  const from = graph.hasNode(id) && st.nodes[id].kind === "org" ? graph.getNodeAttributes(id) : null;
  st.more = 0;
  st.selT0 = performance.now();
  st.selected = id;
  st.focus = focusFor(id);
  st.labelSet = labelsFor(id);
  arrange(id);
  if (from && (from.x !== st.nodes[id].x || from.y !== st.nodes[id].y)) {
    st.moved.add(id);
    st.tween = { t0: performance.now(), dur: 600, items: [[id, from.x, from.y, st.nodes[id].x, st.nodes[id].y]] };
  }
  renderer.refresh();
  if (doFly && graph.hasNode(id)) frame([id, ...topNeighbors(id, null, 12)]);
  const n = st.nodes[id];
  pulse(id, "#ffffff");
  if (n.kind === "ask") {  // the comments arrive, then EPA answers
    pulse(id, VERDICT[n.verdict].c, 750);
    pulse(id, VERDICT[n.verdict].c, 1000);
  }
  st.listOpen = null;
  syncURL(true);  // a new history entry, so Back returns to the view before
  inspect(id);
}
function clearSelection() {
  restorePositions();
  st.more = 0;
  st.selected = null;
  st.labelSet = new Set();
  st.focus = new Set();
  renderer.refresh();
  syncURL();
}
function clearVisited() {
  st.visited = new Set();
  st.cited = new Set();
  renderer.refresh({ skipIndexation: true });
}
function fly(id) { frame([id]); }

// ------------------------------------------------------------------ legend: one compact row
function buildLegend() {
  // the minifier drops "backdrop-filter: none" from the phone CSS, and a blurred legend would trap the
  // fixed "Argued by" sheet inside it, so clear it here
  const lgEl = document.getElementById("legend");
  const phoneFix = () => { lgEl.style.backdropFilter = lgEl.style.webkitBackdropFilter = innerWidth <= 820 ? "none" : ""; };
  phoneFix(); addEventListener("resize", phoneFix);
  const v = st.data.stats.verdicts;
  const sh = { ...st.data.stats.stakeholders };
  if (sh.unknown) { sh.other = (sh.other || 0) + sh.unknown; delete sh.unknown; }
  const groups = Object.entries(sh).filter(([k, n]) => STAKE[k] && n).sort((a, b) => (a[0] === "other") - (b[0] === "other") || b[1] - a[1]);
  $("#legend").innerHTML = `<div class="lg-title">EPA's answer to each ask <span>click to filter</span></div>
    <div class="lg-row">
      <button class="key on" id="f-all">All<span class="n">${fmt(st.data.stats.asks)}</span></button>
      ${Object.entries(VERDICT).map(([k, x]) => `<button class="key" data-v="${k}"><span class="dot" style="background:${x.c}"></span>${x.l}<span class="n">${fmt(v[k] || 0)}</span></button>`).join("")}
    </div>
    <div class="lg-row">
      <button class="key" id="f-changed"><span class="dot ringed"></span>Changed the final rule<span class="n">${fmt(st.data.stats.asks_with_rule_change)}</span></button>
      ${groups.length ? `<span class="grp">Argued by <span class="dd" id="f-group"><button type="button" class="dd-btn" aria-haspopup="listbox" aria-expanded="false"><span class="dd-dot"></span><span class="dd-val">anyone</span><svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 6.5 5 3.5 8 6.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>
        <div class="dd-menu" role="listbox">
          <button type="button" class="dd-opt" data-v="" role="option"><span class="dd-dot"></span><span class="t">Anyone</span></button>
          ${groups.map(([k, n]) => `<button type="button" class="dd-opt" data-v="${k}" role="option"><span class="dd-dot" style="background:${STAKE[k][0]}"></span><span class="t">${STAKE[k][1]}</span><span class="bar"><i style="width:${Math.max(4, Math.round(100 * n / groups[0][1]))}%;background:${STAKE[k][0]}"></i></span><span class="n">${fmt(n)}</span></button>`).join("")}
          <div class="dd-note">Number = commenters in the group</div>
        </div></span></span>` : ""}
      <span id="f-count"></span>
    </div>
    <div class="lg-help">Each dot is one thing commenters asked EPA for. Color is EPA's answer. A ringed dot changed the final rule. One column per topic. ${tapWord} a dot to read EPA's answer.</div>`;
  document.querySelectorAll("#legend .key[data-v]").forEach((el) => el.addEventListener("click", () =>
    setFilter({ verdict: st.filter.verdict === el.dataset.v ? "" : el.dataset.v })));
  $("#f-all").addEventListener("click", () => setFilter({ verdict: "" }));  // clears the answer only; "anyone" clears the group
  $("#f-changed").addEventListener("click", () => setFilter({ changed: !st.filter.changed }));
  const dd = $("#f-group");
  if (dd) {
    const btn = dd.querySelector(".dd-btn");
    const open = (on) => { dd.classList.toggle("open", on); btn.setAttribute("aria-expanded", on); };
    btn.addEventListener("click", (e) => { e.stopPropagation(); open(!dd.classList.contains("open")); });
    dd.querySelectorAll(".dd-opt").forEach((o) => o.addEventListener("click", () => { open(false); setFilter({ group: o.dataset.v }); }));
    document.addEventListener("click", (e) => { if (!dd.contains(e.target)) open(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });
  }
}

// ------------------------------------------------------------------ search
let resultsSel = 0, resultsList = [];
function filterHits(q) {
  const hits = [];
  const words = {
    adopted: /^adopt|^accept|^agreed/, partly_adopted: /^part/, declined: /^decl|^reject|^refus|^denied|^not adopt/,
    clarified: /^expla|^clarif|^no change/, already_required: /^alread/,
  };
  for (const [k, rx] of Object.entries(words)) if (rx.test(q))
    hits.push({ id: `filter:v:${k}`, kind: "filter", label: `Show asks ${VERDICT[k].says}`, c: VERDICT[k].c });
  if (/^chang|^final rule|^rule chang/.test(q)) hits.push({ id: "filter:c:1", kind: "filter", label: "Show asks that changed the final rule", c: "#ffffff" });
  for (const [k, [, l]] of Object.entries(STAKE)) if (st.data.stats.stakeholders[k] && l.toLowerCase().startsWith(q))
    hits.push({ id: `filter:g:${k}`, kind: "filter", label: `Show asks argued by ${l.toLowerCase()}`, c: STAKE[k][0] });
  return hits;
}
// words people type -> words EPA's documents use
const SYNONYMS = [
  [/\b(five|5|more|extra) years?\b|\bextension\b|\bextend\b|\bmore time\b|\bdeadline\b|\btime to comply\b/, "compliance"],
  [/\bcost|afford|expensive|money|fund/, "cost"],
  [/\bsmall (system|utilit)/, "small system"],
  [/\bschools?\b|\bdaycare|child ?care/, "school"],
  [/\bpipes?\b|\blead lines?\b/, "service line"],
];
const ALIAS = { awwa: "american water works", nrdc: "natural resources defense", amwa: "association of metropolitan water", asdwa: "association of state drinking water", edf: "environmental defense fund", ewg: "environmental working group" };
function localSearch(q) {
  q = q.trim().toLowerCase();
  if (!q) return [];
  const terms = [q];
  if (ALIAS[q]) terms.push(ALIAS[q]);
  for (const [rx, w] of SYNONYMS) if (rx.test(q) && !terms.includes(w)) terms.push(w);
  const out = new Map();
  const fh = q.length >= 3 ? filterHits(q) : [];
  terms.forEach((t, ti) => {
    for (const n of st.data.nodes) {
      const hay = `${n.label} ${n.code || ""} ${n.title || ""}`.toLowerCase();
      const i = hay.indexOf(t);
      if (i < 0) continue;
      // commenters rank by how much EPA quoted them, so the real AWWA beats a two-excerpt duplicate
      const score = (i === 0 ? 3 : 1) - ti * 0.4 + ({ topic: 1.2, section: 1.5, org: 1, ask: 0.6, chapter: 1.4 }[n.kind]) + Math.log10(1 + (n.comments || 0)) * (n.kind === "org" ? 1.4 : 0.5);
      if (!out.has(n.id) || out.get(n.id)[0] < score) out.set(n.id, [score, n]);
    }
  });
  const hits = [...out.values()].sort((a, b) => b[0] - a[0]).slice(0, 14 - fh.length).map((x) => x[1]);
  const res = [...fh, ...hits];
  if (!res.length && q.length >= 2) res.push({ id: "none", kind: "none", label: q });
  return res;
}
function renderResults() {
  const box = $("#results");
  if (!resultsList.length) { box.classList.remove("on"); return; }
  box.classList.add("on");
  if (resultsList[0]?.kind === "none") {
    box.innerHTML = `<div class="res none">No commenter, topic or ask matches “${esc(resultsList[0].label)}” on this rule. Try a word EPA would use, like “compliance date” or “cost”.</div>
      <div class="res all" data-all="1"><span class="k">all</span><span class="l">Search every rule for “${esc(resultsList[0].label)}” →</span></div>`;
    box.querySelector("[data-all]").addEventListener("mousedown", (e) => { e.preventDefault(); openPalette($("#search").value.trim()); });
    return;
  }
  box.innerHTML = resultsList.map((n, i) => {
    const c = n.kind === "filter" ? n.c || "#e8ecf4" : n.kind === "ask" ? VERDICT[n.verdict].c : n.kind === "org" ? STAKE[n.stakeholder]?.[0] : KIND[n.kind].c;
    const tail = n.kind === "org" ? `<span class="m">${fmt(n.comments)} excerpts</span>` : n.kind === "ask" ? `<span class="m" style="color:${VERDICT[n.verdict].c}">${VERDICT[n.verdict].s}</span>` : "";
    return `<div class="res ${i === resultsSel ? "sel" : ""}" data-id="${n.id}"><span class="k" style="color:${c}">${n.kind === "org" ? "who" : n.kind}</span><span class="l">${esc(n.kind === "topic" ? `${n.code} ${n.label}` : n.kind === "section" ? `${n.label} ${n.title}` : n.label)}</span>${tail}</div>`;
  }).join("");
  box.querySelectorAll(".res").forEach((el) => el.addEventListener("mousedown", (e) => { e.preventDefault(); pick(el.dataset.id); }));
}
function pick(id) {
  $("#search").value = "";
  resultsList = [];
  renderResults();
  $("#search").blur();
  if (id.startsWith("filter:")) {
    const [, t, k] = id.split(":");
    clearSelection();
    return setFilter(t === "v" ? { verdict: k } : t === "c" ? { changed: true } : { group: k });
  }
  openNode(id);
}
$("#search").addEventListener("input", (e) => { resultsList = localSearch(e.target.value); resultsSel = 0; renderResults(); });
$("#search").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { resultsSel = Math.min(resultsSel + 1, resultsList.length - 1); renderResults(); e.preventDefault(); }
  if (e.key === "ArrowUp") { resultsSel = Math.max(resultsSel - 1, 0); renderResults(); e.preventDefault(); }
  if (e.key === "Enter" && resultsList[resultsSel] && resultsList[resultsSel].kind !== "none") pick(resultsList[resultsSel].id);
  if (e.key === "Escape") { resultsList = []; renderResults(); e.target.blur(); }
});
$("#search").addEventListener("blur", () => setTimeout(() => { resultsList = []; renderResults(); $("#searchbox").classList.remove("open"); }, 150));
$("#search-open")?.addEventListener("click", () => { $("#searchbox").classList.add("open"); $("#search").focus(); });
window.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#search").focus(); }
});

function openNode(id) {
  if (graph.hasNode(id)) select(id);
  else inspect(id);
}

// ------------------------------------------------------------------ tabs
const TAB_ALIAS = { scoreboard: "score", scores: "score", check: "coach", iris: "ask", chat: "ask" };
function tab(name) {
  name = TAB_ALIAS[name] || name;
  if (!document.querySelector(`#tabs button[data-tab="${name}"]`)) name = document.querySelector("#tabs button")?.dataset.tab || "ask";
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${name}`));
  syncURL();
}
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => { if (b.dataset.tab !== "inspect") st.listOpen = null; tab(b.dataset.tab); }));

// ------------------------------------------------------------------ chips and mini markdown
const placeholder = (label) => /^\(|^anonymous|^unknown|illegible/i.test(label || "");
function chip(id, count) {
  const n = st.nodes[id];
  if (!n) return `<code>${esc(id)}</code>`;
  const c = n.kind === "ask" ? VERDICT[n.verdict].c : n.kind === "org" ? STAKE[n.stakeholder]?.[0] || ORG_MUTED : KIND[n.kind].c;
  const text = n.kind === "topic" ? `${n.code} ${n.label}` : n.kind === "section" ? n.label : n.label;
  return `<span class="chip" data-id="${esc(id)}" title="${esc(text)}"><span class="d" style="background:${c}"></span><span class="l">${esc(text)}</span>${count != null ? `<span class="c">${count}</span>` : ""}</span>`;
}
function inline(s) {
  s = esc(s);
  s = s.replace(/\(\s*((?:\[\[[a-z]+:[0-9.:]+\]\][,;\s]*)+)\)/g, " $1");  // chips never sit inside brackets
  s = s.replace(/\[\[([a-z]+:[0-9.:]+)\]\]/g, (_, id) => chip(id));
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  return s;
}
function md(text) {
  const lines = text.split("\n");
  let html = "", list = null, table = null;
  const close = () => {
    if (list) { html += `</${list}>`; list = null; }
    if (table) { html += "</table>"; table = null; }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if (/^\s*\|.*\|\s*$/.test(line)) {
      if (/^\s*\|[\s:-|]+\|\s*$/.test(line)) continue;
      const cells = line.trim().slice(1, -1).split("|").map((c) => c.trim());
      if (!table) { close(); html += "<table>"; table = true; html += "<tr>" + cells.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr>"; }
      else html += "<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
      continue;
    }
    if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { close(); html += "<ul>"; list = "ul"; } html += `<li>${inline(m[1])}</li>`; continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); html += "<ol>"; list = "ol"; } html += `<li>${inline(m[1])}</li>`; continue; }
    close();
    if ((m = line.match(/^#{1,4}\s+(.*)/))) { html += `<h4>${inline(m[1])}</h4>`; continue; }
    if ((m = line.match(/^>\s?(.*)/))) { html += `<blockquote>${inline(m[1])}</blockquote>`; continue; }
    if (line.trim()) html += `<p>${inline(line)}</p>`;
  }
  close();
  return html;
}
document.addEventListener("click", (e) => {
  const c = e.target.closest(".chip, .row[data-id]");
  if (c && c.dataset.id) openNode(c.dataset.id);
});

// ------------------------------------------------------------------ agent
const SUGGEST = {
  LCRI: [
    "Which asks actually changed the final rule on service line replacement?",
    "What did water utilities win, and what did they lose?",
    "Compare how EPA answered NRDC and the American Water Works Association.",
    "Did anyone ask EPA to lower the lead action level? What happened?",
    "What changed in § 141.84 between proposal and final, and who asked for it?",
  ],
  PFAS: [
    "Which asks changed the final PFAS rule?",
    "What did water utilities win, and what did they lose?",
    "How did EPA answer requests to drop the Hazard Index?",
    "Compare how EPA answered AWWA and 3M.",
    "Did anyone get more time to comply? What did EPA say?",
  ],
  LCRR: [
    "Which asks changed the final rule on service line replacement?",
    "How did EPA answer calls to lower the lead action level?",
    "What did commenters say about the trigger level, and what did EPA do?",
    "Which asks about schools and child care did EPA adopt?",
    "What changed in § 141.84 between proposal and final?",
  ],
};
// What each suggested question opens without the model: a filter and its list, a matching set of
// asks, or a commenter. Used when Iris is offline or out of questions, so the question still answers.
const asksLike = (rx) => st.data.nodes.filter((n) => n.kind === "ask" && rx.test(n.label)).map((n) => n.id);
const orgLike = (rx) => st.data.nodes.filter((n) => n.kind === "org" && rx.test(n.label)).sort((a, b) => (b.comments || 0) - (a.comments || 0))[0]?.id;
const VIEWS = {
  PFAS: [
    () => { setFilter({ changed: true, verdict: "", group: "" }); showList(); },
    () => { setFilter({ group: "utility", verdict: "", changed: false }); showList(); },
    () => showList({ ids: asksLike(/hazard index/i), title: "Asks about the Hazard Index" }),
    () => { const a = orgLike(/american water works/i); if (a) openNode(a); },
    () => showList({ ids: asksLike(/compliance (date|deadline|period)|extend|extension|more time|years to comply/i), title: "Asks for more time to comply" }),
  ],
  LCRI: [
    () => { setFilter({ changed: true, verdict: "", group: "" }); showList({ ids: asksLike(/service line|replacement/i).filter((id) => st.nodes[id].changed), title: "Service line asks that changed the final rule" }); },
    () => { setFilter({ group: "utility", verdict: "", changed: false }); showList(); },
    () => { const a = orgLike(/natural resources defense|nrdc/i); if (a) openNode(a); },
    () => showList({ ids: asksLike(/action level/i), title: "Asks about the lead action level" }),
    () => { const sec = st.data.nodes.find((n) => n.kind === "section" && /141\.84/.test(n.label)); if (sec) openNode(sec.id); },
  ],
  LCRR: [
    () => showList({ ids: asksLike(/service line|replacement/i).filter((id) => st.nodes[id].changed), title: "Service line asks that changed the final rule" }),
    () => showList({ ids: asksLike(/action level/i), title: "Asks about the lead action level" }),
    () => showList({ ids: asksLike(/trigger level/i), title: "Asks about the trigger level" }),
    () => showList({ ids: asksLike(/school|child ?care/i), title: "Asks about schools and child care" }),
    () => { const sec = st.data.nodes.find((n) => n.kind === "section" && /141\.84/.test(n.label)); if (sec) openNode(sec.id); },
  ],
};
function viewFor(q) {
  const list = SUGGEST[RULE.meta?.short] || SUGGEST.LCRI, i = list.indexOf(q);
  return i >= 0 ? (VIEWS[RULE.meta?.short] || VIEWS.LCRI)[i] : null;
}
function notice(detail, q) {  // one calm message for "offline", "out of questions" and real errors
  const d = typeof detail === "object" && detail ? detail : { code: "error", message: String(detail || "Iris hit a snag.") };
  const view = viewFor(q);
  const btns = [];
  if (view) btns.push(`<button type="button" class="primary" data-act="view">Show the answer from the record</button>`);
  if (d.code === "limit" && !signedIn() && authConfig()?.accounts) btns.push(`<button type="button" class="primary" data-act="signin">Sign in with Google</button>`);
  if (d.code !== "limit" || !view) btns.push(`<button type="button" class="ghost" data-act="score">Open the Scoreboard</button>`, `<button type="button" class="ghost" data-act="search">Search the record</button>`);
  const el = document.createElement("div");
  el.className = "notice";
  el.innerHTML = `<p>${esc(d.message)}</p><div class="notice-btns">${btns.join("")}</div>`;
  el.querySelector('[data-act="view"]')?.addEventListener("click", () => view());
  el.querySelector('[data-act="signin"]')?.addEventListener("click", () => import("./auth.js").then((m) => m.signIn()));
  el.querySelector('[data-act="score"]')?.addEventListener("click", () => tab("score"));
  el.querySelector('[data-act="search"]')?.addEventListener("click", () => { if (innerWidth <= 820) $("#searchbox").classList.add("open"); $("#search").focus(); });
  if (d.code === "offline") st.offline = true;
  if (d.code === "limit") { st.left = { ...(st.left || {}), ask: 0 }; syncLeft(); }
  return el;
}
async function refreshLeft() {
  const r = await authFetch("/api/left").then((x) => x.ok ? x.json() : null).catch(() => null);
  if (!r) return;
  st.left = r.left; st.limit = r.limit; st.offline = r.offline || st.offline;
  syncLeft();
}
function syncLeft() {
  const el = $("#ask-left");
  if (!el || !st.left) return;
  const n = st.left.ask;
  el.innerHTML = st.offline ? "Iris is offline for typed questions right now. The suggested questions still open the answer from the record."
    : n > 0 ? `${n} question${n === 1 ? "" : "s"} left today${signedIn() ? "" : " · sign in for more"}`
    : `No questions left today${signedIn() ? "" : ". Sign in for more"}`;
  el.classList.toggle("warn", !!st.offline || n <= 1);
}
function intro() {
  const s = st.data.stats;
  $("#chat").innerHTML = `<div class="intro">
    <h2>Ask the record</h2>
    <p>Every comment EPA answered on the ${esc(RULE.meta?.title || "rule")}, what commenters asked for, EPA's verdict in its own words, and what changed in the final text. ${fmt(s.asks)} asks${s.excerpts_tied_to_ask ? `, ${fmt(s.excerpts_tied_to_ask)} comment excerpts tied to the ask they argue` : ""}.</p>
    <div class="suggest">${(SUGGEST[RULE.meta?.short] || SUGGEST.LCRI).map((q) => `<button>${esc(q)}</button>`).join("")}</div></div>`;
  $("#chat").querySelectorAll(".suggest button").forEach((b) => b.addEventListener("click", () => {
    const v = viewFor(b.textContent);
    if (v && (st.offline || st.left?.ask === 0)) { v(); return; }  // no model: open the answer from the record
    ask(b.textContent);
  }));
}
const input = $("#ask-input");
input.addEventListener("focus", () => { if (!st.busy && IRIS?.state !== "listening") IRIS?.lookAt(innerWidth - 220, innerHeight - 60, 1500); });
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, Math.max(160, window.innerHeight * 0.3)) + "px"; $("#ask-send").disabled = !input.value.trim(); });
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); } });
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = input.value.trim(); if (q) ask(q); });

const TOOL_LABEL = {
  overview: () => "Reading the overview",
  search: (i) => `Searching “${i.query}”`,
  search_comments: (i) => `Reading comments on “${i.query}”${i.organization ? ` from ${i.organization}` : ""}${i.stakeholder ? ` (${i.stakeholder})` : ""}`,
  get_node: (i) => `Opening ${st.nodes[i.node_id]?.kind === "topic" ? "topic " + st.nodes[i.node_id].code : st.nodes[i.node_id] ? short(st.nodes[i.node_id].label, 40) : i.node_id}`,
  neighbors: (i) => `Following links from ${st.nodes[i.node_id] ? short(st.nodes[i.node_id].label, 36) : i.node_id}`,
  org_record: (i) => `Pulling the record for ${i.name}`,
  find_similar_asks: (i) => `Finding past asks like “${short(i.text || i.query || "", 50)}”`,
  search_rule_text: (i) => `Reading the final rule on “${short(i.query || "", 50)}”`,
  compare_stakeholders: (i) => `Scoring stakeholder groups${i.scope ? " in " + (st.nodes[i.scope]?.label || i.scope) : ""}`,
};

async function ask(q) {
  track("ask:sent", { suggested: !!viewFor(q) });
  if (st.busy) return;
  st.busy = true;
  $("#ask-send").disabled = true;
  input.value = "";
  input.style.height = "auto";
  tab("ask");
  orbState("thinking");
  const chat = $("#chat");
  if (chat.querySelector(".intro")) chat.innerHTML = "";
  chat.insertAdjacentHTML("beforeend", `<div class="msg user"><div class="b">${esc(q)}</div></div>`);
  const bot = document.createElement("div");
  bot.className = "msg bot";
  bot.innerHTML = `<div class="trace"></div><div class="b cursor"></div>`;
  chat.appendChild(bot);
  const trace = bot.querySelector(".trace"), body = bot.querySelector(".b");
  clearSelection();
  clearVisited();
  let text = "", lastStep = null;
  const scroll = () => { chat.scrollTop = chat.scrollHeight; };
  scroll();

  try {
    const res = await authFetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, docket: RULE.docket, conversation_id: st.conv, history: signedIn() ? null : st.history }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw Object.assign(new Error("http"), { detail: j.detail || res.statusText }); }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!chunk.startsWith("data: ")) continue;
        const ev = JSON.parse(chunk.slice(6));
        if (ev.type === "conversation") { st.conv = ev.id; irisSub(ev.title); }
        else if (ev.type === "show") { irisShow(ev.ids || [], ev.focus); }
        else if (ev.type === "tool") {
          if (ev.name === "show_on_graph" || ev.name === "my_history") {
            if (ev.name === "my_history") { trace.insertAdjacentHTML("beforeend", `<div class="step"><span class="q">Looking through your earlier work for “${esc(ev.input?.query || "")}”</span></div>`); scroll(); }
            continue;
          }
          if (lastStep) lastStep.classList.remove("live");
          if (text.trim()) {  // narration before a tool call belongs in the trace, not the answer
            trace.insertAdjacentHTML("beforeend", `<div class="step note-step"><span class="q">${esc(short(text.trim().replace(/\s+/g, " "), 120))}</span></div>`);
            text = "";
            body.innerHTML = "";
          }
          const f = TOOL_LABEL[ev.name] || (() => ev.name);
          trace.insertAdjacentHTML("beforeend", `<div class="step live"><span class="sp"></span><span class="q">${esc(f(ev.input || {}))}</span></div>`);
          lastStep = trace.lastElementChild;
          for (const id of ev.ids || []) { visit(id, 0); }
          scroll();
        } else if (ev.type === "visit") {
          (ev.ids || []).slice(0, 40).forEach((id, k) => visit(id, k * 35));
        } else if (ev.type === "text") {
          if (lastStep) { lastStep.classList.remove("live"); lastStep = null; }
          text += ev.delta;
          body.innerHTML = md(text);
          for (const m of text.matchAll(/\[\[([a-z]+:[0-9.:]+)\]\]/g)) if (!st.cited.has(m[1])) { st.cited.add(m[1]); visit(m[1], 0, true); }
          scroll();
        } else if (ev.type === "done") {
          body.classList.remove("cursor");
          if (ev.usd != null) bot.insertAdjacentHTML("beforeend", `<div class="cost">${(ev.ms / 1000).toFixed(1)} s · $${ev.usd.toFixed(3)}</div>`);
        } else if (ev.type === "error") {
          body.appendChild(notice(ev, q));
        }
      }
    }
  } catch (err) {
    body.appendChild(notice(err.detail || String(err.message || err), q));
  }
  trace.querySelectorAll(".step.live").forEach((x) => x.classList.remove("live"));
  if (!text.trim() && !trace.children.length) trace.remove();
  orbState("idle");
  if (text.trim()) {
    st.history.push({ role: "user", content: q }, { role: "assistant", content: text });
    st.history = st.history.slice(-12);
    IRIS?.react("happy");
    irisSpeak(text);
  } else IRIS?.react("oops");
  body.classList.remove("cursor");
  if (lastStep) lastStep.classList.remove("live");
  // focus the camera on what the answer cited
  const cited = [...text.matchAll(/\[\[([a-z]+:[0-9.:]+)\]\]/g)].map((m) => m[1]).filter((id) => graph.hasNode(id));
  if (cited.length) {
    st.visited = new Set([...cited, ...st.visited].slice(0, 160));
    st.cited = new Set(cited);
    renderer.refresh({ skipIndexation: true });
    frame(cited);
  }
  st.busy = false;
  $("#ask-send").disabled = false;
  refreshLeft();
}
function irisGlance(id, ms = 700) {
  const p = graph.hasNode(id) ? vp(id) : null;
  if (p && IRIS) { const b = $("#graph").getBoundingClientRect(); IRIS.lookAt(b.left + p.x, b.top + p.y, ms); }
}
function visit(id, delay, cited = false) {
  if (!st.nodes[id] || !graph.hasNode(id)) return;
  if (delay === 0 || Math.random() < 0.15) setTimeout(() => irisGlance(id, 500), delay);
  if (!st.visited.has(id)) {
    st.visited.add(id);
    renderer.refresh({ skipIndexation: true });
  }
  const n = st.nodes[id];
  pulse(id, n.kind === "ask" ? VERDICT[n.verdict].c : cited ? "#ffffff" : "#8fb6ff", delay);
}

// ------------------------------------------------------------------ inspect
function recordBar(rec) {
  const total = Object.values(rec || {}).reduce((a, b) => a + b, 0);
  if (!total) return `<div class="nochange">No excerpt from this commenter takes a side on a recorded ask.</div>`;
  return `<div class="recbar">${["won", "partly", "lost", "no_change"].map((k) => `<div style="flex:${rec[k] || 0};background:${OUTCOME[k]}"></div>`).join("")}</div>
  <div class="reclegend">${[["won", "got their way"], ["partly", "partly"], ["lost", "did not"], ["no_change", "no change"]].map(([k, l]) => `<span><b style="color:${OUTCOME[k]}">${rec[k] || 0}</b>${l}</span>`).join("")}</div>`;
}
function verdictPill(v) {
  const x = VERDICT[v];
  return `<span class="pill" style="background:${hexA(x.c, 0.14)};color:${x.c}"><span class="dot" style="width:7px;height:7px;border-radius:50%;background:${x.c}"></span>${x.l}</span>`;
}
function rows(list, f) { return list.map(f).join(""); }
// Inspect sections fold shut; the ones a reader opens stay open as they click around.
const FOLD_OPEN = new Set();
function fold(key, title, count, body, preview = "") {
  return `<details class="fold" data-k="${key}"${FOLD_OPEN.has(key) ? " open" : ""}><summary><span class="ft">${title}</span><span class="fp">${preview}</span>${count !== "" ? `<span class="fn">${count}</span>` : ""}<svg class="fc" width="12" height="12" viewBox="0 0 12 12"><path d="M4 2.5 7.5 6 4 9.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></summary><div class="fb">${body}</div></details>`;
}
function tally(list, key, colors) {  // "● 3 ● 1 ● 9": what a folded list holds, by color
  const c = {};
  for (const x of list) c[key(x)] = (c[key(x)] || 0) + 1;
  return Object.entries(colors).filter(([k]) => c[k]).map(([k, col]) => `<span class="fm"><i style="background:${col}"></i>${c[k]}</span>`).join("");
}
const VCOL = Object.fromEntries(Object.entries(VERDICT).map(([k, x]) => [k, x.c]));
function diffHtml(s) {
  return esc(s).replace(/\[-([\s\S]*?)-\]/g, "<del>$1</del>").replace(/\{\+([\s\S]*?)\+\}/g, "<ins>$1</ins>");
}

function citeLine(d, n) {
  const c = d.cite;
  if (!c) return "";
  const doc = `EPA, Response to Comments on the ${RULE.meta?.title || "rule"}`;
  return `<div class="cite">
    <div class="cite-src">${esc(doc)}, section ${esc(n.code || "")}, p. ${c.page}${c.pdf ? ` · <a href="/rtc/${encodeURIComponent(RULE.meta?.short || "")}.pdf#page=${c.page}" target="_blank" rel="noopener">Open the PDF at this page</a>` : ""}</div>
    <div class="cite-tools">${c.context ? `<button type="button" class="linkish" id="c-ctx">Show the paragraph around this</button>` : ""}<button type="button" class="linkish" id="c-copy">Copy quote with citation</button><button type="button" class="linkish" id="c-link">Copy link</button></div>
    <div class="cite-ctx" id="c-ctx-body" hidden></div>
  </div>`;
}
function wireCite(box, d, n) {
  const c = d.cite;
  if (!c) return;
  $("#c-ctx")?.addEventListener("click", (e) => {
    const body = $("#c-ctx-body");
    if (body.hidden) {
      const q = d.quote || "";
      const i = c.context.indexOf(q.slice(0, 40));
      body.innerHTML = i >= 0 ? esc(c.context.slice(0, i)) + "<mark>" + esc(c.context.slice(i, i + q.length)) + "</mark>" + esc(c.context.slice(i + q.length)) : esc(c.context);
    }
    body.hidden = !body.hidden;
    e.target.textContent = body.hidden ? "Show the paragraph around this" : "Hide the paragraph";
  });
  $("#c-copy")?.addEventListener("click", (e) => copy(`“${d.quote}” (EPA, Response to Comments on the ${RULE.meta?.title || "rule"}, ${RULE.meta?.final || ""}, section ${n.code}, p. ${c.page}). Via Oversight: ${location.href}`, e.target, "Copied"));
  $("#c-link")?.addEventListener("click", (e) => copy(location.href, e.target, "Link copied"));
}
async function inspect(id) {
  tab("inspect");
  const box = $("#inspect");
  box.innerHTML = `<div class="empty">Loading…</div>`;
  const r = await fetch(api(`/api/node/${encodeURIComponent(id)}`));
  if (!r.ok) { box.innerHTML = `<div class="empty">Nothing found for ${esc(id)}.</div>`; return; }
  const d = await r.json();
  const n = d.node;
  let h = "";
  if (n.kind === "topic") {
    const v = n.verdicts || {};
    const tot = Object.values(v).reduce((a, b) => a + b, 0);
    d.epa_summary = d.epa_summary.replace(/COMMENTS \(EPA's summary\):\s*/g, "").replace(/^Summary of Comments\s*/, "");
    h += `<div class="ins-kind" style="color:${KIND.topic.c}">EPA response topic <span class="code">${n.code}</span></div>
      <div class="ins-title">${esc(n.label)}</div>
      <div class="metrics">${st.data.stats.comments ? `<div class="metric"><div class="v">${fmt(n.comments)}</div><div class="l">comments EPA quoted</div></div>` : ""}
      <div class="metric"><div class="v">${tot}</div><div class="l">distinct asks</div></div>
      <div class="metric"><div class="v" style="color:var(--adopted)">${(v.adopted || 0) + (v.partly_adopted || 0)}</div><div class="l">adopted or partly</div></div></div>
      <div class="recbar">${Object.entries(VERDICT).map(([k, x]) => `<div style="flex:${v[k] || 0};background:${x.c}"></div>`).join("")}</div>
      ${fold("t-asks", "What commenters asked", d.asks.length, rows(d.asks, (a) => `<div class="row" data-id="${a.id}"><span class="d" style="background:${VERDICT[a.verdict].c}"></span><span class="t">${esc(a.label)}${a.final_rule_change ? (["adopted", "partly_adopted"].includes(a.verdict) ? `<span class="tag">changed the rule</span>` : `<span class="tag for">rule changed another way</span>`) : ""}</span></div>`), tally(d.asks, (a) => a.verdict, VCOL))}
      ${fold("t-sum", "EPA's summary response", "", `<div class="summary" id="sum">${esc(d.epa_summary.slice(0, 1400))}${d.epa_summary.length > 1400 ? "…" : ""}</div>
      ${d.epa_summary.length > 1400 ? `<button class="more" id="sum-more">Read all of it</button>` : ""}`, `<span class="fq">${esc(d.epa_summary.slice(0, 70))}…</span>`)}
      ${d.sections.length ? fold("t-sec", "Rule sections EPA cites", d.sections.length, `<div class="chips">${d.sections.map((s) => chip(s.id)).join("")}</div>`) : ""}
      ${d.top_commenters.length ? fold("t-org", "Most quoted commenters", d.top_commenters.length, `<div class="chips">${[...d.top_commenters].sort((a, b) => placeholder(st.nodes[a.id]?.label) - placeholder(st.nodes[b.id]?.label)).map((o) => chip(o.id, o.weight)).join("")}</div>`) : ""}`;
    box.innerHTML = h;
    $("#sum-more")?.addEventListener("click", (e) => { $("#sum").textContent = d.epa_summary; e.target.remove(); });
  } else if (n.kind === "ask") {
    const color = VERDICT[n.verdict].c;
    h += `<div class="ins-kind">Ask in topic ${d.topic[0] ? chip(d.topic[0].id) : ""}</div>
      <div class="ins-title">${esc(n.label)}</div>
      ${verdictPill(n.verdict)} ${n.who ? `<span style="color:var(--ink-3);margin-left:6px">raised by ${esc(n.who)}</span>` : ""}
      <div class="h">EPA, in its own words</div>
      <div class="verified">${d.quote_verified ? "✓ checked word for word against EPA's response document" : "quote not matched exactly"}</div>
      <div class="quote" style="--vc:${color}">“${esc(d.quote)}”</div>
      ${citeLine(d, n)}
      <div class="h">Effect on the final rule</div>
      ${d.final_rule_change ? `<div class="change">${esc(d.final_rule_change)}</div>` : ["adopted", "partly_adopted"].includes(n.verdict) ? `<div class="nochange">No new text: EPA's proposal already did this, or it was handled outside the rule text.</div>` : `<div class="nochange">No change to the final rule.</div>`}
      ${d.excerpts_for + d.excerpts_against
        ? `<div class="metrics"><div class="metric"><div class="v" style="color:var(--topic)">${d.supporters.length}</div><div class="l">commenters asked for it <span class="sub">${d.excerpts_for} excerpts</span></div></div>
           <div class="metric"><div class="v" style="color:var(--declined)">${d.opponents.length}</div><div class="l">argued against it <span class="sub">${d.excerpts_against} excerpts</span></div></div></div>`
        : `<div class="note">${st.data.stats.comments ? "EPA summarized this ask without quoting a named commenter, so we can't say who asked." : "EPA did not name commenters for this rule."}</div>`}
      ${d.supporters.length ? fold("a-for", "Asked for it", d.supporters.length, `<div class="chips">${d.supporters.map((o) => chip(o.id)).join("")}</div>`) : ""}
      ${d.opponents.length ? fold("a-against", "Argued against it", d.opponents.length, `<div class="chips">${d.opponents.map((o) => chip(o.id)).join("")}</div>`) : ""}
      ${d.sections.length ? fold("a-sec", "Rule sections", d.sections.length, `<div class="chips">${d.sections.map((s) => chip(s.id)).join("")}</div>`) : ""}`;
    h += `<div class="ins-foot"><button type="button" class="linkish" id="i-wrong">Something wrong with this?</button></div>`;
    box.innerHTML = h;
    wireCite(box, d, n);
    track("open:ask", { id, verdict: n.verdict });
    $("#i-wrong").addEventListener("click", () => reportProblem({ docket: RULE.docket, node_id: id, label: n.label }));
  } else if (n.kind === "org") {
    const sc = STAKE[n.stakeholder] || STAKE.other;
    h += `<div class="ins-kind" style="color:${sc[0]}">${esc(sc[1])}</div>
      <div class="ins-title">${esc(n.label)}</div>
      ${n.slug ? `<a class="ghost wide scorecard-link" href="/org/${encodeURIComponent(n.slug)}">Full scorecard across every rule →</a>` : ""}
      <div class="metrics"><div class="metric"><div class="v">${fmt(d.ask_count ?? d.asks.length)}</div><div class="l">asks they took a side on</div></div>
      <div class="metric"><div class="v">${fmt(n.comments)}</div><div class="l">excerpts EPA quoted</div></div>
      <div class="metric"><div class="v">${d.topics.length}</div><div class="l">topics</div></div></div>
      <div class="h">Did they get their way <span>by ask</span></div>${recordBar(d.ask_record || d.record)}
      <div class="note">Counted per ask. Got their way means EPA adopted what they asked for, or declined what they argued against.</div>
      ${d.asks.length ? fold("o-asks", "Asks they took a side on", d.asks.length, rows(d.asks, (a) => `<div class="row" data-id="${a.id}"><span class="d" style="background:${OUTCOME[a.outcome]}"></span><span class="t">${esc(a.label)}<span class="tag ${a.side}">${a.side === "for" ? "for" : "against"}</span></span></div>`), tally(d.asks, (a) => a.outcome, OUTCOME)) : ""}
      ${fold("o-ex", "What EPA quoted from them", fmt(d.excerpt_count), rows(d.excerpts, (e) => `<div class="excerpt"><div class="meta">${chip("topic:" + e.code)} ${e.outcome ? `<span class="tag" style="background:${hexA(OUTCOME[e.outcome], 0.14)};color:${OUTCOME[e.outcome]}">${{ won: "got their way", partly: "partly", lost: "did not", no_change: "no change" }[e.outcome]}</span>` : ""}</div><div class="e clamp">${esc(e.excerpt)}</div><div class="r clamp">EPA: ${esc(e.response)}</div></div>`), tally(d.excerpts, (e) => e.outcome, OUTCOME))}`;
    box.innerHTML = h;
  } else if (n.kind === "section") {
    const ops = n.ops || {};
    h += `<div class="ins-kind" style="color:${KIND.section.c}">Rule section</div>
      <div class="ins-title">${esc(n.label)} ${esc(n.title || "")}</div>
      <div class="metrics">${["modified", "added", "removed", "unchanged"].map((k) => `<div class="metric"><div class="v" style="color:${{ modified: "var(--partly)", added: "var(--adopted)", removed: "var(--declined)", unchanged: "var(--ink-3)" }[k]}">${ops[k] || 0}</div><div class="l">paragraphs ${k}</div></div>`).join("")}</div>
      ${d.asks.length ? fold("s-asks", "Asks tied to this section", d.asks.length, rows(d.asks, (a) => `<div class="row" data-id="${a.id}"><span class="d" style="background:${VERDICT[a.verdict].c}"></span><span class="t">${esc(a.label)}</span></div>`), tally(d.asks, (a) => a.verdict, VCOL)) : ""}
      ${d.topics.length ? fold("s-top", "Topics that cite it", d.topics.length, `<div class="chips">${d.topics.map((t) => chip(t.id)).join("")}</div>`) : ""}
      ${fold("s-diff", "Proposal → final rule", d.change_count, rows(d.changes, (c) => `<div class="diff"><span class="op">${c.op}${c.marker ? " " + esc(c.marker) : ""}</span>${c.op === "modified" ? diffHtml(c.diff || "") : c.op === "added" ? `<ins>${esc(c.final || "")}</ins>` : `<del>${esc(c.proposed || "")}</del>`}</div>`), tally(d.changes, (c) => c.op, { added: "var(--adopted)", modified: "var(--partly)", removed: "var(--declined)" }))}`;
    box.innerHTML = h;
  } else if (n.kind === "chapter") {
    const tops = d.topics.map((t) => st.nodes[t.id]).filter(Boolean);
    const v = {};
    for (const t of tops) for (const [k, c] of Object.entries(t.verdicts || {})) v[k] = (v[k] || 0) + c;
    const tot = Object.values(v).reduce((a, b) => a + b, 0);
    const askIds = st.data.nodes.filter((a) => a.kind === "ask" && a.chapter === String(n.id).split(":")[1]).map((a) => a.id);
    h += `<div class="ins-kind">Chapter of EPA's response</div><div class="ins-title">${esc(n.label)}</div>
      <div class="metrics"><div class="metric"><div class="v">${fmt(tot)}</div><div class="l">asks</div></div>
      <div class="metric"><div class="v" style="color:var(--adopted)">${fmt((v.adopted || 0) + (v.partly_adopted || 0))}</div><div class="l">adopted or partly</div></div>
      <div class="metric"><div class="v" style="color:var(--declined)">${fmt(v.declined || 0)}</div><div class="l">declined</div></div></div>
      <div class="recbar">${Object.entries(VERDICT).map(([k, x]) => `<div style="flex:${v[k] || 0};background:${x.c}"></div>`).join("")}</div>
      ${askIds.length ? `<button type="button" class="ghost wide" id="c-list">List all ${fmt(askIds.length)} asks in this chapter →</button>` : ""}
      ${fold("c-top", "Topics", d.topics.length, rows(d.topics, (t) => `<div class="row" data-id="${t.id}"><span class="d" style="background:${KIND.topic.c}"></span><span class="t">${esc(t.code)} ${esc(t.label)}</span><span class="n">${fmt(t.comments)}</span></div>`))}`;
    box.innerHTML = h;
    box.querySelector("details.fold")?.setAttribute("open", "");
    $("#c-list")?.addEventListener("click", () => showList({ ids: askIds, title: `${n.label}: every ask` }));
  }
  box.querySelectorAll("details.fold").forEach((el) => el.addEventListener("toggle", () => {
    if (el.open) FOLD_OPEN.add(el.dataset.k); else FOLD_OPEN.delete(el.dataset.k);
  }));
  box.querySelectorAll(".clamp").forEach((el) => {
    if (el.scrollHeight > el.clientHeight + 2) { el.classList.add("cut"); el.addEventListener("click", () => el.classList.remove("clamp", "cut"), { once: true }); }
  });
  box.scrollTop = 0;
}

// ------------------------------------------------------------------ scoreboard
// One unit everywhere: asks. A commenter's position on an ask is one of its supports/opposes links;
// it got its way if EPA adopted what it asked for or declined what it argued against.
const outcomeOf = (verdict, side) => verdict === "partly_adopted" ? "partly" : verdict === "adopted" ? (side === "for" ? "won" : "lost") : verdict === "declined" ? (side === "for" ? "lost" : "won") : "no_change";
function askRecords() {
  const byOrg = {}, byGroup = {};
  for (const e of st.data.edges) {
    if (e.kind !== "supports" && e.kind !== "opposes") continue;
    const [o, a] = st.nodes[e.source]?.kind === "org" ? [e.source, e.target] : [e.target, e.source];
    const ask = st.nodes[a], org = st.nodes[o];
    if (!ask || !org) continue;
    const k = outcomeOf(ask.verdict, e.kind === "supports" ? "for" : "against");
    const r = (byOrg[o] ||= { won: 0, partly: 0, lost: 0, no_change: 0, asks: new Set() });
    if (r.asks.has(a)) continue;
    r.asks.add(a); r[k]++;
    const g = org.stakeholder === "unknown" ? "other" : org.stakeholder || "other";
    const G = (byGroup[g] ||= { won: 0, partly: 0, lost: 0, no_change: 0, orgs: new Set(), asks: new Set() });
    G[k]++; G.orgs.add(o); G.asks.add(a);
  }
  return { byOrg, byGroup };
}
const shareOf = (r) => { const dec = r.won + r.lost + r.partly; return dec ? (r.won + 0.5 * r.partly) / dec : null; };

async function buildScore() {
  const s = st.data.stats;
  const { byOrg, byGroup } = askRecords();
  const top = Object.entries(byOrg).map(([id, r]) => ({ n: st.nodes[id], r, dec: r.won + r.lost + r.partly, sh: shareOf(r) }))
    .filter((x) => x.dec >= 8).sort((a, b) => b.sh - a.sh || b.dec - a.dec);
  const groups = Object.entries(byGroup).map(([g, r]) => ({ g, r, sh: shareOf(r), dec: r.won + r.lost + r.partly }))
    .filter((x) => x.dec >= 10 && STAKE[x.g]).sort((a, b) => b.sh - a.sh);
  const chapters = st.data.nodes.filter((n) => n.kind === "topic").reduce((m, t) => {
    const c = t.chapter; m[c] = m[c] || { won: 0, tot: 0 };
    m[c].won += (t.verdicts?.adopted || 0) + (t.verdicts?.partly_adopted || 0);
    m[c].tot += Object.values(t.verdicts || {}).reduce((a, b) => a + b, 0);
    return m;
  }, {});
  const chRows = Object.entries(chapters).filter(([, v]) => v.tot >= 8).map(([c, v]) => ({ id: `ch:${c}`, ...v, sh: v.won / v.tot })).sort((a, b) => b.sh - a.sh);
  const bar = (rec) => `<div class="bar">${["won", "partly", "lost", "no_change"].map((k) => `<div style="flex:${rec[k] || 0};background:${OUTCOME[k]}"></div>`).join("")}</div>`;
  const pct = (x) => Math.round(x * 100) + "%";
  const best = groups[0], worst = groups[groups.length - 1];
  const sentence = best && worst && best !== worst
    ? `On ${esc(RULE.meta?.short || "this rule")}, EPA went the way of <b>${esc(STAKE[best.g][1].toLowerCase())}</b> most often (${pct(best.sh)} of ${fmt(best.dec)} decided positions) and <b>${esc(STAKE[worst.g][1].toLowerCase())}</b> least often (${pct(worst.sh)} of ${fmt(worst.dec)}).`
    : "";
  const mine = me()?.user?.org_type && { utility: "utility", advocacy: "advocacy", trade: "trade", state: "state", industry: "industry", academic: "academic", resident: "individual" }[me().user.org_type];
  $("#score").innerHTML = `
    <div class="sb-hero">
      <div class="metric"><div class="v">${fmt(s.asks)}</div><div class="l">asks recorded</div></div>
      <div class="metric"><div class="v" style="color:var(--adopted)">${fmt((s.verdicts.adopted || 0) + (s.verdicts.partly_adopted || 0))}</div><div class="l">adopted or partly</div></div>
      <div class="metric"><div class="v" style="color:var(--adopted)">${fmt(s.asks_with_rule_change)}</div><div class="l">changed the rule</div></div>
    </div>
    ${s.comments ? `
    ${sentence ? `<p class="sb-answer">${sentence}</p>` : ""}
    <div class="h">Who got their way</div>
    ${groups.map((x) => `<button type="button" class="sb-row${x.g === mine ? " mine" : ""}" data-g="${x.g}" title="Show the asks ${esc(STAKE[x.g][1].toLowerCase())} took a side on"><div class="l">${esc(STAKE[x.g][1])}${x.g === mine ? ' <span class="you">You</span>' : ""}<span class="sub">${fmt(x.r.orgs.size)} commenters · ${fmt(x.r.asks.size)} asks</span></div>${bar(x.r)}<div class="n">${pct(x.sh)}<span class="sub">of ${fmt(x.dec)}</span></div></button>`).join("")}
    <div class="reclegend" style="margin-top:6px">${[["won", "got their way"], ["partly", "partly"], ["lost", "did not"], ["no_change", "no decision"]].map(([k, l]) => `<span><b style="color:${OUTCOME[k]}">■</b>${l}</span>`).join("")}</div>
    <div class="note">Each bar counts positions: one commenter for or against one ask. Percent = share of decided positions (adopted or declined) that went their way, partly counted as half. ${tapWord} a group to list its asks. Groups are tagged from commenter names, so treat them as rough.</div>
    <div class="h">Got their way most <span>8+ decided asks</span></div>
    ${top.slice(0, 8).map(({ n, sh, dec }) => `<div class="row" data-id="${n.id}"><span class="d" style="background:${STAKE[n.stakeholder]?.[0]}"></span><span class="t">${esc(short(n.label, 44))}</span><span class="n">won ${pct(sh)} of ${dec}</span></div>`).join("")}
    <div class="h">…and least</div>
    ${top.slice(-6).reverse().map(({ n, sh, dec }) => `<div class="row" data-id="${n.id}"><span class="d" style="background:${STAKE[n.stakeholder]?.[0]}"></span><span class="t">${esc(short(n.label, 44))}</span><span class="n">won ${pct(sh)} of ${dec}</span></div>`).join("")}
    ` : `<div class="note" style="margin-top:14px">EPA's response document for this rule summarizes comments without naming commenters, so there is no per-commenter record here. The asks and verdicts are complete.</div>`}
    <div class="h">Where EPA moved most <span>adopted or partly</span></div>
    ${chRows.map((c) => `<div class="row" data-id="${c.id}"><span class="d" style="background:var(--adopted);opacity:${0.35 + c.sh}"></span><span class="t">${esc(st.nodes[c.id].label)}</span><span class="n">${c.won} of ${c.tot}</span></div>`).join("")}
    <details class="about"><summary>About this data</summary><p>Built from EPA's response-to-comments document for this rule and the proposed and final rule text. A model read the asks and verdicts out of EPA's summaries, and every quote was checked word for word against the document. Groups are tagged from commenter names. Extraction cost $${s.usd_extraction}${s.usd_assign ? `, matching $${s.usd_assign}` : ""}.</p></details>`;
  $("#score").querySelectorAll(".sb-row[data-g]").forEach((b) => b.addEventListener("click", () => { clearSelection(); setFilter({ group: b.dataset.g, verdict: "", changed: false }); showList(); }));
}

initShared("rule", { keys: false });
load().catch((e) => {  // never leave someone on the loader
  console.error("[oversight] load failed", e);
  LD_IRIS?.react("oops");
  const t = $("#loading .ld-t"), s = $("#loading .ld-s");
  if (t) t.textContent = "This record didn't load";
  if (s) s.innerHTML = `Try reloading the page. <a href="/" style="color:#8fb6ff">Back to all rules</a>`;
});


// ------------------------------------------------------------------ comment coach
const OUTLOOK = {
  likely_adopted: ["Similar asks were adopted", "#3ddc97"],
  mixed: ["EPA's answers were mixed", "#f5c451"],
  likely_declined: ["Similar asks were declined", "#ff6b6b"],
  already_in_rule: ["Already in the final rule", "#a78bfa"],
  new: ["Nobody asked this before", "#8b9bb4"],
};
const EXAMPLES = {
  LCRI: `We urge EPA to require water systems to replace all lead service lines within five years, not ten. Replacement should be paid for entirely by the utility, with no cost to homeowners.

EPA should also lower the lead action level to 5 parts per billion.

Systems should have to post their full service line inventory online and update it every year. Finally, small systems need more time and technical help to meet the new deadlines.`,
  LCRR: `We urge EPA to require water systems to replace all lead service lines within five years, not ten. Replacement should be paid for entirely by the utility, with no cost to homeowners.

EPA should also lower the lead action level to 5 parts per billion.

Systems should have to post their full service line inventory online and update it every year. Finally, small systems need more time and technical help to meet the new deadlines.`,
  PFAS: `Our small utility serves 3,000 people from two wells. We ask EPA to give systems serving under 10,000 people five years to comply with the PFAS MCLs instead of three.

EPA should drop the Hazard Index and regulate only PFOA and PFOS, since the science on the other four is weak.

We also need federal money to pay for treatment, because our customers cannot absorb a doubling of rates. Finally, EPA should let us use point-of-use filters instead of central treatment.`,
};
let coachAll = [];
let coachAsks = {};  // id -> {label, verdict, rule, local} for asks the coach cited, including other rules

function coachIntro() {
  $("#coach").innerHTML = `<div class="coach-intro">
    <h2>Check a comment</h2>
    <p>Paste a draft comment. The coach shows how EPA answered past asks that made the same points${RULE.meta?.final ? ` (the ${esc(RULE.meta.short)} rule is final, so this is practice for the next rule, or for a comment on a related one)` : ""}, then reads the final rule and suggests edits.</p>
    <div class="composer" id="coach-box">
      <textarea id="coach-draft" rows="5" placeholder="Paste your draft comment here, or try the example"></textarea>
      <div class="composer-foot">
        <span id="coach-wc" class="wc"></span>
        <button id="coach-example" type="button" class="ghost">Try an example</button>
        <button id="coach-go" type="button" class="primary" disabled title="⌘ Enter">Check it</button>
      </div>
    </div>
    <div id="my-drafts"></div>
    <div class="coach-note">Evidence: the ${esc(RULE.meta?.short || "")} final rule text, and how EPA answered asks in ${Object.values(RULE.all).map((m) => esc(m.short)).join(", ") || "this rule"}. A guide, not a prediction.</div>
  </div><div id="coach-out"></div>`;
  const ta = $("#coach-draft");
  const sync = () => {  // grow with the text; the panel scrolls past a tall draft
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, Math.max(240, window.innerHeight * 0.55)) + "px";
    const words = (ta.value.match(/\S+/g) || []).length;
    $("#coach-wc").textContent = words ? `${fmt(words)} words${TOUCH ? "" : " · ⌘ Enter to check"}` : (st.left ? `${st.left.coach} check${st.left.coach === 1 ? "" : "s"} left today` : "");
    $("#coach-go").disabled = st.busy || ta.value.trim().length < 40;
  };
  ta.addEventListener("input", sync);
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (!$("#coach-go").disabled) runCoach(ta.value); } });
  const ex = $("#coach-example");
  ex.addEventListener("click", () => {  // never overwrite someone's own draft on one click
    const example = EXAMPLES[RULE.meta?.short] || EXAMPLES.LCRI;
    if (ta.value.trim() && ta.value !== example && !ex.dataset.sure) {
      ex.dataset.sure = "1"; ex.textContent = "Replace your draft?";
      setTimeout(() => { delete ex.dataset.sure; ex.textContent = "Try an example"; }, 3500);
      return;
    }
    delete ex.dataset.sure; ex.textContent = "Try an example";
    ta.value = example; sync(); ta.focus();
  });
  $("#coach-go").addEventListener("click", () => runCoach(ta.value));
  sync();
  st.coachSync = sync;
}

// ------------------------------------------------------------------ saved drafts (signed in)
async function loadDrafts() {
  const el = $("#my-drafts");
  if (!el) return;
  if (!signedIn()) { el.innerHTML = authConfig()?.accounts ? `<div class="drafts-note">Sign in to save drafts and every check on them.</div>` : ""; return; }
  const list = await authFetch(api("/api/drafts")).then((r) => r.json()).catch(() => []);
  el.innerHTML = list.length ? `<div class="drafts"><div class="dh">Your drafts on this rule</div>${list.slice(0, 5).map((d) =>
    `<button type="button" class="draft-row ${d.id === st.draftId ? "on" : ""}" data-id="${esc(d.id)}"><span class="t">${esc(d.title)}…</span><span class="m">${d.runs} check${d.runs === 1 ? "" : "s"}</span></button>`).join("")}</div>` : "";
  el.querySelectorAll(".draft-row").forEach((b) => b.addEventListener("click", () => openDraft(b.dataset.id)));
}
async function openDraft(id) {
  const d = await authFetch(`/api/drafts/${encodeURIComponent(id)}`).then((r) => r.ok ? r.json() : null).catch(() => null);
  if (!d) return;
  tab("coach");
  st.draftId = d.id;
  $("#coach-draft").value = d.body;
  st.coachSync?.();
  $("#coach-out").innerHTML = "";
  if (d.runs?.length) {
    const r = d.runs[0];
    renderCoach({ ...r.result, tools: r.tools, usd: r.usd != null ? Number(r.usd) : null, ms: r.ms });
  }
  loadDrafts();
}

// ------------------------------------------------------------------ Iris: the guide on the page
// Iris is the agent with a face: an orb on the graph that listens (voice or text), lights up what
// it reads, points at the nodes its answer is about, and can read the answer aloud. Signed-in
// conversations are saved and reopened from the history menu; signed-out ones live in this tab.
const orb = $("#orb");
const VOICE = { on: false, rec: null, listening: false };
try { VOICE.on = localStorage.getItem("iris-voice") === "1"; } catch { /* storage blocked */ }

let IRIS = null, lastActive = performance.now();
setInterval(() => {  // nobody around for a minute: Iris dozes off; any movement wakes her
  if (IRIS && IRIS.state === "idle" && !st.busy && performance.now() - lastActive > 60000) orbState("sleepy");
}, 5000);
addEventListener("pointermove", () => { lastActive = performance.now(); if (IRIS?.state === "sleepy") { orbState("idle"); IRIS.react("wave"); } }, { passive: true });
addEventListener("keydown", () => { lastActive = performance.now(); if (IRIS?.state === "sleepy") orbState("idle"); });
function orbState(s) {
  orb?.setAttribute("data-s", s);
  IRIS?.setState(s);
  document.querySelector('#tabs [data-tab="ask"]')?.setAttribute("data-s", s);
}
function irisSub(t) { $("#iris-sub").textContent = t ? short(t, 54) : "Ask about this rule's record"; }
function plain(text) {  // what Iris says aloud: chips become names, markdown goes
  return text.replace(/\[\[([a-z]+:[0-9.:]+)\]\]/g, (_, id) => st.nodes[id]?.label || "").replace(/[*_`#>|]/g, "").replace(/\s+/g, " ").trim();
}
// Iris's voice: Google Cloud TTS (Chirp 3 HD) from /api/speak, with her mouth following the
// audio's loudness. If the voice service is unreachable, the browser's best voice stands in.
let VOICE_AUDIO = null, VOICE_CTX = null;
async function irisSpeak(text) {
  if (!VOICE.on) return;
  stopSpeaking();
  const line = plain(text).slice(0, 1200);
  try {
    const r = await fetch("/api/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: line }) });
    if (!r.ok) throw new Error(r.status);
    const url = URL.createObjectURL(await r.blob());
    const audio = new Audio(url);
    VOICE_AUDIO = audio;
    VOICE_CTX ||= new (window.AudioContext || window.webkitAudioContext)();
    const src = VOICE_CTX.createMediaElementSource(audio), an = VOICE_CTX.createAnalyser();
    an.fftSize = 512;
    src.connect(an); an.connect(VOICE_CTX.destination);
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      if (VOICE_AUDIO !== audio || audio.paused) return;
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      IRIS?.level(Math.min(1, Math.sqrt(sum / buf.length) * 4));
      requestAnimationFrame(tick);
    };
    audio.onplay = () => { orbState("speaking"); tick(); };
    audio.onended = audio.onpause = () => { IRIS?.level(null); if (IRIS?.state === "speaking") orbState("idle"); URL.revokeObjectURL(url); };
    await VOICE_CTX.resume();
    await audio.play();
  } catch {
    browserSpeak(line);
  }
}
function stopSpeaking() {
  if (VOICE_AUDIO) { VOICE_AUDIO.pause(); VOICE_AUDIO = null; }
  window.speechSynthesis?.cancel();
}
function browserSpeak(line) {
  if (!window.speechSynthesis) return;
  const voices = speechSynthesis.getVoices();
  const pick = ["Google US English", "Samantha", "Ava (Premium)", "Ava", "Allison", "Zoe"].map((n) => voices.find((v) => v.name.startsWith(n))).find(Boolean)
    || voices.find((v) => /natural|neural|premium|enhanced/i.test(v.name) && v.lang.startsWith("en")) || voices.find((v) => v.lang === "en-US");
  const u = new SpeechSynthesisUtterance(line);
  if (pick) u.voice = pick;
  u.rate = 1.0; u.pitch = 1.05;
  u.onstart = () => orbState("speaking");
  u.onend = () => orbState("idle");
  speechSynthesis.speak(u);
}
function irisShow(ids, focus) {  // the agent pointed at these: light them, frame them, label the focus
  const live = ids.filter((id) => graph.hasNode(id));
  if (!live.length) return;
  st.cited = new Set(live);
  st.visited = new Set([...live, ...st.visited].slice(0, 160));
  st.labelSet = new Set(live.slice(0, 8));
  renderer.refresh({ skipIndexation: true });
  frame(live);
  live.slice(0, 20).forEach((id, k) => pulse(id, "#ffffff", k * 60));
  if (focus && graph.hasNode(focus)) {
    setTimeout(() => irisGlance(focus, 2600), 650);
    const n = st.nodes[focus];
    $("#orb-say").textContent = n.kind === "topic" ? `${n.code} ${n.label}` : short(n.label, 48);
    orb.classList.add("saying");
    setTimeout(() => orb.classList.remove("saying"), 4200);
  }
}
function newChat() {
  if (st.busy) return;
  st.conv = null;
  st.history = [];
  irisSub("");
  intro();
  coachLight([], false);
  $("#hist-menu").classList.remove("on");
}
async function openConversation(id) {
  if (st.busy) return;
  const c = await authFetch(`/api/conversations/${encodeURIComponent(id)}`).then((r) => r.ok ? r.json() : null).catch(() => null);
  if (!c) return;
  tab("ask");
  st.conv = c.id;
  irisSub(c.title);
  const chat = $("#chat");
  chat.innerHTML = c.messages.map((m) => m.role === "user"
    ? `<div class="msg user"><div class="b">${esc(m.content)}</div></div>`
    : `<div class="msg bot"><div class="b">${md(m.content)}</div>${m.trace?.length ? `<div class="cost">${m.trace.length} lookups</div>` : ""}</div>`).join("");
  const tail = c.messages[c.messages.length - 1];
  if (tail?.role === "user") {  // the answer never came (offline, limit): offer to ask again
    chat.insertAdjacentHTML("beforeend", `<div class="msg bot"><div class="notice"><p>Iris didn't answer this one.</p><div class="notice-btns"><button type="button" class="primary" id="re-ask">Ask again</button></div></div></div>`);
    $("#re-ask").addEventListener("click", () => ask(tail.content));
  }
  chat.scrollTop = chat.scrollHeight;
  const last = [...c.messages].reverse().find((m) => m.role === "assistant");
  if (last) irisShow([...last.content.matchAll(/\[\[([a-z]+:[0-9.:]+)\]\]/g)].map((m) => m[1]));
  $("#hist-menu").classList.remove("on");
}
async function toggleHistory() {
  const menu = $("#hist-menu");
  if (st.busy) return;
  if (menu.classList.toggle("on") === false) return;
  if (!signedIn()) {
    menu.innerHTML = authConfig()?.accounts ? `<div class="hm-empty">Sign in and Iris keeps your conversations, remembers what you asked, and knows what kind of commenter you are.</div>` : `<div class="hm-empty">Accounts are off on this copy.</div>`;
    return;
  }
  menu.innerHTML = `<div class="hm-empty">Loading…</div>`;
  const list = await authFetch(api("/api/conversations")).then((r) => r.json()).catch(() => []);
  menu.innerHTML = list.length ? list.map((c) => `<button type="button" class="hm-row ${c.id === st.conv ? "on" : ""}" data-id="${esc(c.id)}"><span>${esc(c.title)}</span><span class="m">${c.n} messages</span></button>`).join("")
    : `<div class="hm-empty">No conversations on this rule yet.</div>`;
  menu.querySelectorAll(".hm-row").forEach((b) => b.addEventListener("click", () => openConversation(b.dataset.id)));
}
function listen() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { input.placeholder = "Voice input isn't available in this browser"; return; }
  if (VOICE.listening) { VOICE.rec?.stop(); return; }
  stopSpeaking();
  const rec = new SR();
  VOICE.rec = rec;
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.onstart = () => { VOICE.listening = true; orbState("listening"); $("#ask-mic").classList.add("on"); };
  rec.onresult = (e) => {
    input.value = [...e.results].map((r) => r[0].transcript).join("");
    input.dispatchEvent(new Event("input"));
  };
  rec.onend = () => {
    VOICE.listening = false;
    $("#ask-mic").classList.remove("on");
    orbState("idle");
    if (input.value.trim()) { VOICE.on = true; syncVoice(); ask(input.value.trim()); }  // asked aloud, answered aloud
  };
  rec.start();
}
function syncVoice() {
  $("#iris-voice").classList.toggle("on", VOICE.on);
  try { localStorage.setItem("iris-voice", VOICE.on ? "1" : "0"); } catch { /* storage blocked */ }
}
function irisInit() {
  try {
    IRIS = createMascot($("#orb-iris"), { size: 128 });
    setTimeout(() => IRIS.react("wave"), 1400);
  } catch { /* no WebGL: the button still works */ }
  window.__iris = IRIS;  // used by the screenshot tests
  $("#ask-form").insertAdjacentHTML("afterend", `<div id="ask-left"></div>`);
  refreshLeft();
  orbState("idle");
  syncVoice();
  orb.addEventListener("click", () => { tab("ask"); input.focus(); });
  orb.addEventListener("dblclick", () => { tab("ask"); listen(); });
  $("#ask-mic").addEventListener("click", listen);
  $("#iris-voice").addEventListener("click", () => {
    VOICE.on = !VOICE.on;
    if (!VOICE.on) stopSpeaking(); else irisSpeak("Voice on. Ask me anything about this rule.");
    syncVoice();
  });
  $("#iris-new").addEventListener("click", newChat);
  $("#iris-hist").addEventListener("click", (e) => { e.stopPropagation(); toggleHistory(); });
  document.addEventListener("click", (e) => { if (!$("#iris-bar").contains(e.target)) $("#hist-menu").classList.remove("on"); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) { e.preventDefault(); tab("ask"); input.focus(); }
  });
  const qs = new URLSearchParams(location.search);
  ready.then((m) => {
    loadDrafts();
    if (m && qs.get("c")) openConversation(qs.get("c"));
    if (m && qs.get("draft")) openDraft(qs.get("draft"));
    if (m) irisGreet(m);
  });
  onMe((m) => { loadDrafts(); refreshLeft(); buildScore(); if (!m) newChat(); else irisGreet(m); });
}
function irisGreet(m) {
  const h = $("#chat .intro h2");
  if (h && m?.user) h.textContent = `Hi${m.user.name ? " " + m.user.name.split(" ")[0] : ""}. Ask the record.`;
}

function coachLight(ids, label = true) {
  st.cited = new Set(ids);
  st.visited = new Set(ids);
  st.labelSet = label ? new Set(ids.slice(0, 8)) : new Set();
  renderer.refresh({ skipIndexation: true });
}

async function runCoach(draft) {
  track("coach:run", { words: draft.split(/\s+/).length });
  if (st.busy || draft.trim().length < 40) return;
  st.busy = true;
  clearSelection();
  coachLight([], false);
  const out = $("#coach-out");
  orbState("thinking");
  out.innerHTML = `<div class="coach-steps"></div>`;
  const steps = out.querySelector(".coach-steps");
  $("#coach-go").disabled = true;
  const step = (text) => {
    steps.querySelectorAll(".step.on").forEach((e) => e.classList.replace("on", "done"));
    steps.insertAdjacentHTML("beforeend", `<div class="step on"><span class="sp"></span>${esc(text)}</div>`);
  };
  // first pass, no model: the past asks closest to each point (shown at once, kept if the AI is off)
  out.insertAdjacentHTML("afterbegin", `<div id="coach-like"></div>`);
  fetch("/api/similar", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ draft, docket: RULE.docket }) })
    .then((r) => r.ok ? r.json() : null).then((r) => { if (r) renderLike(r.points); }).catch(() => {});
  try {
    const res = await authFetch("/api/coach", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ draft, docket: RULE.docket, draft_id: st.draftId }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw Object.assign(new Error("http"), { detail: j.detail || res.statusText }); }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "draft") { st.draftId = ev.id; loadDrafts(); }
        if (ev.type === "phase") step(ev.text);
        if (ev.type === "tool") step(toolStep(ev.name, ev.input));
        if (ev.type === "visit" && ev.ids.length) {  // what the agent just read lights up round the ring
          const fresh = ev.ids.filter((id) => !id.includes("/") && st.nodes[id] && !st.visited.has(id));
          coachLight([...st.visited, ...fresh], false);
          fresh.slice(0, 12).forEach((id, k) => pulse(id, VERDICT[st.nodes[id].verdict].c, k * 50));
        }
        if (ev.type === "candidates") {  // the asks being compared light up round the ring
          coachLight(ev.ids, false);
          ev.ids.forEach((id, k) => pulse(id, VERDICT[st.nodes[id].verdict].c, k * 60));
        }
        if (ev.type === "error") throw Object.assign(new Error("sse"), { detail: ev });
        if (ev.type === "result") {
          orbState("idle"); IRIS?.react("happy");
          steps.querySelectorAll(".step.on").forEach((e) => e.classList.replace("on", "done"));
          renderCoach(ev);
        }
      }
    }
  } catch (e) {
    orbState("idle"); IRIS?.react("oops");
    steps.remove();  // no spinner left beside the message
    const d = typeof e.detail === "object" && e.detail ? e.detail : { code: "error", message: String(e.detail || e.message || e) };
    const msg = d.code === "offline" ? "The full check (reading the final rule and suggesting edits) needs the AI, which is offline right now. The past asks like yours are above."
      : d.code === "limit" ? d.message : "The full check hit a snag. The past asks like yours are above; try the full check again in a moment.";
    const el = document.createElement("div");
    el.className = "notice";
    el.innerHTML = `<p>${esc(msg)}</p>${d.code === "limit" && !signedIn() && authConfig()?.accounts ? `<div class="notice-btns"><button type="button" class="primary">Sign in with Google</button></div>` : ""}`;
    el.querySelector("button")?.addEventListener("click", () => import("./auth.js").then((m) => m.signIn()));
    out.appendChild(el);
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } finally {
    st.busy = false;
    $("#coach-go").disabled = false;
  }
}

function renderLike(points) {
  const box = $("#coach-like");
  if (!box) return;
  const any = points.some((p) => p.asks.length);
  box.innerHTML = `<div class="h">Past asks like yours <span>matched by meaning, no AI</span></div>
    ${any ? points.filter((p) => p.asks.length).map((p) => `<div class="like">
      <div class="like-pt">“${esc(short(p.point, 160))}”</div>
      ${p.asks.map((a) => `<div class="li" data-id="${a.id}">
        <div class="li-top"><span class="pill" style="--vc:${VERDICT[a.verdict]?.c || "#8b9bb4"}">${VERDICT[a.verdict]?.s || a.verdict}</span>${a.final_rule_change ? `<span class="tag">changed the rule</span>` : ""}<span class="li-code">${a.excerpts_for} for · ${a.excerpts_against} against</span></div>
        <div class="li-ask">${esc(a.ask)}</div>
        ${a.epa_said ? `<div class="li-epa"><b>EPA:</b> ${esc(short(a.epa_said, 220))}</div>` : ""}
        ${a.final_rule_change ? `<div class="li-eff"><b>Final rule:</b> ${esc(short(a.final_rule_change, 180))}</div>` : ""}
      </div>`).join("")}</div>`).join("") : `<div class="note">Nobody made these points in a way EPA answered on this rule. That can mean a new argument; say clearly what you want changed and why.</div>`}`;
  box.querySelectorAll(".li[data-id]").forEach((el) => el.addEventListener("click", () => openNode(el.dataset.id)));
  coachLight(points.flatMap((p) => p.asks.map((a) => a.id)).filter((id) => st.nodes[id]), false);
}
function coachChip(id) {
  if (!id) return "";
  if (st.nodes[id]) return chip(id);
  const a = coachAsks[id];  // an ask from another rule: links to that rule's page
  if (!a) return `<code>${esc(id)}</code>`;
  return `<a class="chip foreign" href="/rule/${esc(a.rule)}#${esc(a.id)}" target="_blank" title="${esc(a.label)}"><span class="d" style="background:${VERDICT[a.verdict]?.c || "#8b9bb4"}"></span><span class="rule">${esc(a.rule)}</span><span class="l">${esc(a.label)}</span></a>`;
}

function toolStep(name, inp = {}) {
  const q = (x) => `“${esc(String(x || "").slice(0, 70))}”`;
  if (name === "find_similar_asks") return `Looking for past asks${inp.rule ? " in " + esc(inp.rule) : ""} like ${q(inp.text)}`;
  if (name === "search_rule_text") return `Checking the final rule${inp.section ? " in § " + esc(inp.section) : ""} for ${q(inp.query)}`;
  if (name === "get_node") return `Reading ${esc(st.nodes[inp.node_id]?.label?.slice(0, 70) || inp.node_id)}`;
  if (name === "neighbors") return `Following links from ${esc(st.nodes[inp.node_id]?.label?.slice(0, 60) || inp.node_id)}`;
  if (name === "search_comments") return `Reading comments that argued ${q(inp.query)}`;
  if (name === "search") return `Searching the record for ${q(inp.query)}`;
  return `Using ${esc(name)}`;
}

function mixBar(mix) {
  const order = ["adopted", "partly_adopted", "already_required", "clarified", "declined"];
  const total = order.reduce((a, k) => a + (mix[k] || 0), 0);
  if (!total) return "";
  const words = order.filter((k) => mix[k]).map((k) => `<span><b style="color:${VERDICT[k].c}">${mix[k]}</b> ${VERDICT[k].l.toLowerCase()}</span>`).join("");
  return `<div class="mix"><div class="mixbar">${order.map((k) => mix[k] ? `<div style="flex:${mix[k]};background:${VERDICT[k].c}"></div>` : "").join("")}</div><div class="mixwords">${words}</div></div>`;
}

function renderCoach(r) {
  coachAsks = r.asks || {};
  coachAll = [...new Set(r.points.flatMap((p) => p.similar))].filter((id) => st.nodes[id]);
  coachLight(coachAll);
  const out = $("#coach-out");
  out.insertAdjacentHTML("beforeend", `<div class="coach-overall">${esc(r.overall)}</div>
    ${r.points.map((p, i) => {
      const [ol, oc] = OUTLOOK[p.outlook] || OUTLOOK.mixed;
      return `<div class="ccard" data-i="${i}">
        <div class="ctop"><span class="cnum">${i + 1}</span><span class="cask">${esc(p.ask)}</span></div>
        <div class="cdraft">"${esc(p.draft)}"</div>
        <div class="coutlook" style="color:${oc};background:${hexA(oc, 0.12)}">${ol}</div>
        ${mixBar(p.mix)}
        ${p.changed ? `<div class="cchanged">${p.changed} of these changed the final rule</div>` : ""}
        ${p.in_rule ? `<div class="cinrule"><div class="ch2">What the final rule says <span class="sec">§ ${esc(p.in_rule.section)}</span></div>“${esc(p.in_rule.quote)}”</div>` : ""}
        ${p.why ? `<div class="cwhy">${esc(p.why)}</div>` : ""}
        ${p.epa_said ? `<div class="cepa"><div class="ch2">EPA's words ${coachChip(p.epa_said_on)}</div>“${esc(p.epa_said)}”</div>` : ""}
        ${p.advice.length ? `<div class="ch">How to make it stronger</div><ul class="cadv">${p.advice.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
        ${p.rewrite ? `<div class="ch">Suggested wording <button class="copy" data-i="${i}">Copy</button></div><div class="crewrite">${esc(p.rewrite)}</div>` : ""}
        ${p.similar.length ? `<div class="ch">Past asks it is based on</div><div class="chips">${p.similar.map((a) => coachChip(a)).join("")}</div>` : ""}
      </div>`;
    }).join("")}
    <div class="meta-cost">${r.tools ? r.tools + " lookups · " : ""}${r.ms ? (r.ms / 1000).toFixed(1) + " s" : ""}${r.usd ? " · $" + r.usd.toFixed(3) : ""}</div>`);
  out.querySelectorAll(".ccard").forEach((el) => {
    const p = r.points[+el.dataset.i];
    const local = p.similar.filter((id) => st.nodes[id]);
    el.addEventListener("mouseenter", () => { coachLight(local); local.forEach((id, k) => pulse(id, VERDICT[st.nodes[id].verdict].c, k * 80)); });
    el.addEventListener("mouseleave", () => coachLight(coachAll));
  });
  out.querySelectorAll(".copy").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(r.points[+b.dataset.i].rewrite);
    b.textContent = "Copied";
    setTimeout(() => { b.textContent = "Copy"; }, 1400);
  }));
  out.querySelector(".coach-overall")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
