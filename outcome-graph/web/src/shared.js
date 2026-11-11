// Shared by every page: the command palette (⌘K), the inbox bell, "this looks wrong" reports,
// first-party usage events, and the site header on the newer pages.
import "./shared.css";
import { authFetch, clientId, onMe, ready, signedIn, toast } from "./auth.js";

export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
export const fmt = (n) => Number(n || 0).toLocaleString("en-US");
export const pct = (x) => (x == null ? "n/a" : Math.round(x * 100) + "%");
export const VERDICT = {
  adopted: { l: "Adopted", c: "#3ddc97" }, partly_adopted: { l: "Partly adopted", c: "#f5c451" },
  already_required: { l: "Already in the rule", c: "#a98bff" }, clarified: { l: "Explained, no change", c: "#8b9bb4" },
  declined: { l: "Declined", c: "#ff6b6b" },
};
export const OUTCOME = { won: ["Got their way", "#3ddc97"], partly: ["Partly", "#f5c451"], lost: ["Did not", "#ff6b6b"], no_change: ["No decision", "#5b6579"] };

// ------------------------------------------------------------------ usage events (first party only)
export function track(name, props = {}) {
  try {
    const body = JSON.stringify({ name, path: location.pathname + location.search, props, anon: clientId() });
    if (navigator.sendBeacon) navigator.sendBeacon("/api/e", new Blob([body], { type: "application/json" }));
    else fetch("/api/e", { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true });
  } catch { /* never let analytics break the page */ }
}

// ------------------------------------------------------------------ site header for the newer pages
export function siteHeader(el, { active = "" } = {}) {
  el.className = "site-top";
  el.innerHTML = `<a class="logo" href="/"><span class="ring"></span><b>Oversight</b><span class="by">by Undersigned</span></a>
    <nav class="site-nav">
      <a href="/" class="${active === "rules" ? "on" : ""}">Rules</a>
      <a href="/methods" class="${active === "methods" ? "on" : ""}">Methods</a>
      <a href="/connect" class="${active === "connect" ? "on" : ""}">Use in Claude</a>
    </nav>
    <div class="site-right"><button type="button" class="kbtn" data-palette><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><span>Search</span><kbd>⌘K</kbd></button>
    <span class="bell-slot"></span><div class="acct" id="account"></div></div>`;
}

// ------------------------------------------------------------------ command palette
const ACTIONS = [
  { label: "PFAS map", hint: "Rule", url: "/rule/PFAS" },
  { label: "Lead and Copper Rule Improvements map", hint: "Rule", url: "/rule/LCRI" },
  { label: "Lead and Copper Rule Revisions map", hint: "Rule", url: "/rule/LCRR" },
  { label: "Check a draft comment", hint: "Coach", url: "/rule/PFAS?tab=coach" },
  { label: "Who got their way on PFAS", hint: "Scores", url: "/rule/PFAS?tab=score" },
  { label: "How this is built, and how accurate it is", hint: "Methods", url: "/methods" },
  { label: "Use Oversight in your own Claude", hint: "MCP", url: "/connect" },
  { label: "Add comment deadlines to your calendar", hint: "Calendar", url: "/calendar.ics" },
];
let P = null;
function palette() {
  if (P) return P;
  const el = document.createElement("div");
  el.className = "pal";
  el.hidden = true;
  el.innerHTML = `<div class="pal-back"></div><div class="pal-box" role="dialog" aria-label="Search Oversight">
    <div class="pal-in"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input placeholder="Search organizations, asks, topics, rules…" autocomplete="off" spellcheck="false" /><kbd>esc</kbd></div>
    <div class="pal-list"></div>
    <div class="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span>Try “AWWA”, “compliance date”, “Hazard Index”</span></div></div>`;
  document.body.appendChild(el);
  const input = el.querySelector("input"), list = el.querySelector(".pal-list");
  let rows = [], sel = 0, timer = null, seq = 0;
  const render = () => {
    let g = "";
    list.innerHTML = rows.length ? rows.map((r, i) => {
      const head = r.group !== g ? `<div class="pal-g">${esc((g = r.group))}</div>` : "";
      return `${head}<a class="pal-row${i === sel ? " sel" : ""}" href="${esc(r.url)}" data-i="${i}">
        ${r.dot ? `<span class="pal-dot" style="background:${r.dot}"></span>` : `<span class="pal-ic">${r.icon || "→"}</span>`}
        <span class="pal-l">${esc(r.label)}</span><span class="pal-h">${esc(r.hint || "")}</span></a>`;
    }).join("") : `<div class="pal-empty">Nothing matches. Try a word EPA would use, like “compliance” or “cost”.</div>`;
    list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
  };
  const load = async (q) => {
    const my = ++seq;
    const r = await fetch(`/api/find?q=${encodeURIComponent(q)}`).then((x) => x.json()).catch(() => null);
    if (my !== seq || !r) return;
    const ql = q.toLowerCase();
    rows = [
      ...r.orgs.map((o) => ({ group: q.length < 2 ? "Most quoted organizations" : "Organizations", label: o.name + (o.acronym ? ` (${o.acronym})` : ""),
        hint: `${o.group_label} · ${o.share == null ? "no decided asks" : pct(o.share) + " won"} · ${o.rules.join(", ")}`, url: `/org/${o.slug}`, icon: "◎" })),
      ...r.rules.map((x) => ({ group: "Rules", label: x.title, hint: x.short, url: x.url, icon: "◌" })),
      ...r.items.map((x) => ({ group: "Asks and topics", label: x.label, hint: `${x.rule} · ${x.kind === "ask" ? VERDICT[x.verdict]?.l || "" : x.kind + " " + (x.code || "")}`,
        url: x.url, dot: x.kind === "ask" ? VERDICT[x.verdict]?.c : null, icon: x.kind === "topic" ? "#" : "§" })),
      ...ACTIONS.filter((a) => !q || a.label.toLowerCase().includes(ql) || a.hint.toLowerCase().includes(ql)).map((a) => ({ group: "Go to", ...a })),
    ];
    if (q.length >= 3 && /^\/rule\//.test(location.pathname))
      rows.push({ group: "Ask Iris", label: `Ask Iris: “${q}”`, hint: "answers from this rule's record", url: `${location.pathname}?ask=${encodeURIComponent(q)}`, icon: "◍" });
    sel = 0;
    render();
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load(input.value.trim()), 110); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(rows.length - 1, sel + 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
    else if (e.key === "Enter" && rows[sel]) { e.preventDefault(); go(rows[sel]); }
    else if (e.key === "Escape") close();
  });
  list.addEventListener("click", (e) => { const a = e.target.closest(".pal-row"); if (a) { e.preventDefault(); go(rows[+a.dataset.i]); } });
  list.addEventListener("mousemove", (e) => { const a = e.target.closest(".pal-row"); if (a && +a.dataset.i !== sel) { sel = +a.dataset.i; list.querySelectorAll(".pal-row").forEach((x, i) => x.classList.toggle("sel", i === sel)); } });
  el.querySelector(".pal-back").addEventListener("click", close);
  function go(r) { track("palette:open", { url: r.url, group: r.group }); close(); location.href = r.url; }
  function close() { el.classList.remove("on"); setTimeout(() => { el.hidden = true; }, 140); }
  P = { el, open(q = "") { el.hidden = false; requestAnimationFrame(() => el.classList.add("on")); input.value = q; input.focus(); load(q); track("palette:show"); } };
  return P;
}
export const openPalette = (q) => palette().open(q);

// ------------------------------------------------------------------ inbox bell
function bell(slot) {
  if (!slot) return;
  const render = async (m) => {
    if (!m) { slot.innerHTML = ""; return; }
    const r = await authFetch("/api/notifications").then((x) => x.ok ? x.json() : null).catch(() => null);
    if (!r) return;
    const ago = (s) => { const d = (Date.now() - new Date(s)) / 1000; return d < 3600 ? `${Math.max(1, Math.round(d / 60))} min` : d < 86400 ? `${Math.round(d / 3600)} h` : `${Math.round(d / 86400)} d`; };
    slot.innerHTML = `<div class="bell"><button type="button" class="bell-btn" aria-label="Updates${r.unread ? `, ${r.unread} new` : ""}">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>
        ${r.unread ? `<span class="bell-n">${r.unread}</span>` : ""}</button>
      <div class="bell-menu"><div class="bell-h">Updates</div>${r.items.map((n) => `<a class="bell-i${n.read_at ? "" : " new"}" href="${esc(n.url || "#")}"><b>${esc(n.title)}</b>${n.body ? `<span>${esc(n.body)}</span>` : ""}<i>${ago(n.created_at)} ago</i></a>`).join("") || `<div class="bell-e">Nothing yet.</div>`}
        <a class="bell-foot" href="/calendar.ics">Add comment deadlines to your calendar</a></div></div>`;
    const b = slot.querySelector(".bell");
    b.querySelector(".bell-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      b.classList.toggle("open");
      if (b.classList.contains("open") && r.unread) { authFetch("/api/notifications/read", { method: "POST" }); b.querySelector(".bell-n")?.remove(); }
    });
    document.addEventListener("click", (e) => { if (!b.contains(e.target)) b.classList.remove("open"); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") b.classList.remove("open"); });
  };
  onMe(render);
  ready.then(render);
  return render;
}
export function mountBell(slot) { bell(slot); }

// ------------------------------------------------------------------ "this looks wrong"
const PROBLEMS = ["EPA's verdict is wrong", "The ask is misstated", "Wrong organization listed", "Quote or page is off", "Something else"];
export function reportProblem({ docket, node_id, label }) {
  const el = document.createElement("div");
  el.className = "pal on rep";
  el.innerHTML = `<div class="pal-back"></div><div class="pal-box rep-box" role="dialog" aria-label="Report a problem">
    <div class="rep-h">What looks wrong?</div>${label ? `<div class="rep-sub">${esc(label)}</div>` : ""}
    <div class="rep-opts">${PROBLEMS.map((p, i) => `<label><input type="radio" name="rp" value="${esc(p)}" ${i ? "" : "checked"}> ${esc(p)}</label>`).join("")}</div>
    <textarea placeholder="What should it say? A page number helps." rows="3"></textarea>
    <div class="rep-btns"><button type="button" class="ghost" data-x>Cancel</button><button type="button" class="primary" data-go>Send</button></div>
    <div class="rep-note">Goes to the team. Reports and spot checks feed the accuracy numbers on the Methods page.</div></div>`;
  document.body.appendChild(el);
  const close = () => el.remove();
  el.querySelector(".pal-back").addEventListener("click", close);
  el.querySelector("[data-x]").addEventListener("click", close);
  el.querySelector("textarea").focus();
  el.querySelector("[data-go]").addEventListener("click", async () => {
    const problem = el.querySelector("input:checked").value, note = el.querySelector("textarea").value;
    const r = await authFetch("/api/report", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ docket, node_id, problem, note, url: location.href }) }).catch(() => null);
    close();
    toast(r?.ok ? "Thanks. The team will check it." : "Couldn't send that. Try again later.", !!r?.ok);
    track("report", { problem });
  });
}

// ------------------------------------------------------------------ boot
export function initShared(page, { keys = true } = {}) {
  track(`view:${page}`);
  if (keys) addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
    else if (e.key === "/" && !typing) { e.preventDefault(); openPalette(); }
  });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-palette]")) { e.preventDefault(); openPalette(); } });
  mountBell(document.querySelector(".bell-slot"));
  onMe((m) => { if (m && !sessionStorage.getItem("ov-signed")) { sessionStorage.setItem("ov-signed", "1"); track("signin"); } });
  return { signedIn };
}
