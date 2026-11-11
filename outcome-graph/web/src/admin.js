// Team dashboard: visitors, the main funnel, and open problem reports. Team accounts only (ADMIN_EMAILS).
import "./pages.css";
import "./account.css";
import { initAuth, accountWidget, authFetch, ready, onMe } from "./auth.js";
import { esc, fmt, siteHeader, initShared } from "./shared.js";

const $ = (s) => document.querySelector(s);
const LABEL = { "view:landing": "Opened the home page", "view:rule": "Opened a rule map", "open:ask": "Read an ask", "open:list": "Opened a list",
  "ask:sent": "Asked Iris", "coach:run": "Ran the coach", "view:org": "Opened a scorecard", signin: "Signed in" };

async function render(m) {
  const main = $("#main");
  if (!m) { main.innerHTML = `<div class="empty">Sign in with a team account.</div>`; return; }
  const r = await authFetch("/api/metrics?days=14");
  if (!r.ok) { main.innerHTML = `<div class="empty">This page is for the team.</div>`; return; }
  const d = await r.json();
  const max = Math.max(1, ...d.daily.map((x) => x.visitors)), top = Math.max(1, d.funnel[0]?.[1] || 1);
  main.innerHTML = `<div style="margin-top:18px"><div class="eyebrow">Team</div><h1 class="big" style="font-size:34px">Last ${d.days} days</h1>
    <p class="sub">${fmt(d.users)} accounts. First-party events only; visitors are browsers, counted by a random id.</p></div>
    <section class="sec"><h2>Visitors per day</h2><div class="card" style="display:flex;align-items:flex-end;gap:6px;height:180px">
      ${d.daily.map((x) => `<div title="${x.day}: ${x.visitors} visitors" style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;height:100%"><span class="sub" style="font-size:11px">${x.visitors}</span><div style="width:100%;height:${(x.visitors / max) * 120}px;background:linear-gradient(#8fb6ff,#3d7bff);border-radius:6px 6px 2px 2px"></div><span class="sub" style="font-size:10px">${String(x.day).slice(5)}</span></div>`).join("") || `<div class="empty" style="width:100%">No events yet.</div>`}</div></section>
    <section class="sec"><h2>Funnel</h2><div class="card">${d.funnel.map(([k, n]) => `<div style="display:grid;grid-template-columns:220px 1fr 60px;gap:12px;align-items:center;margin:6px 0"><span>${esc(LABEL[k] || k)}</span><div class="recbar" style="height:10px"><div style="flex:${n};background:#3ddc97"></div><div style="flex:${top - n}"></div></div><b class="n">${fmt(n)}</b></div>`).join("")}</div></section>
    <section class="sec"><h2>Open problem reports (${d.reports.length})</h2><div class="card tbl-wrap"><table class="nums"><thead><tr><th>When</th><th>Problem</th><th>Where</th><th>Note</th></tr></thead><tbody>
      ${d.reports.map((x) => `<tr><td>${new Date(x.created_at).toLocaleString()}</td><td>${esc(x.problem)}</td><td>${x.url ? `<a href="${esc(x.url)}">${esc(x.node_id || "page")}</a>` : esc(x.node_id || "")}</td><td>${esc(x.note || "")}<small>${esc(x.who)}</small></td></tr>`).join("") || `<tr><td colspan="4" class="sub">None.</td></tr>`}</tbody></table></div></section>
    <section class="sec"><h2>All events</h2><div class="card tbl-wrap"><table class="nums"><thead><tr><th>Event</th><th>Count</th><th>Browsers</th></tr></thead><tbody>${d.events.map((e) => `<tr><td>${esc(e.name)}</td><td class="n">${fmt(e.n)}</td><td class="n">${fmt(e.people)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

async function main() {
  siteHeader($("#top"));
  await initAuth();
  accountWidget($("#account"));
  initShared("admin");
  render(await ready);
  onMe(render);
}
main();
