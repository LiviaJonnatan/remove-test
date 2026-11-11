// Preparing a comment on a proposed rule: its timeline, and how EPA answered similar points before.
import "./pages.css";
import "./account.css";
import { initAuth, accountWidget, authFetch, onMe, ready, signIn, signedIn, me, toast } from "./auth.js";
import { esc, fmt, pct, VERDICT, siteHeader, initShared, track } from "./shared.js";

const $ = (s) => document.querySelector(s);
const docket = decodeURIComponent(location.pathname.split("/")[2] || "");
const date = (s) => (s ? new Date(s + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "");

function askCard(a) {
  const v = VERDICT[a.verdict] || { l: a.verdict, c: "#8b9bb4" };
  const rule = a.rule_short, id = a.id;
  return `<a class="ask" href="/rule/${esc(rule || "PFAS")}?n=${encodeURIComponent(id)}">
    <div class="ask-top"><span class="pill" style="--vc:${v.c}">${v.l}</span>${a.final_rule_change ? `<span class="tag">changed the rule</span>` : ""}<span class="code">${esc(a.rule || "")}</span></div>
    <h4>${esc(a.ask)}</h4>
    ${a.epa_said ? `<div class="epa"><b>EPA:</b> ${esc(a.epa_said.length > 220 ? a.epa_said.slice(0, 219) + "…" : a.epa_said)}</div>` : ""}
    <div class="match">${Math.round(a.match * 100)}% match to: “${esc(a.point.length > 90 ? a.point.slice(0, 89) + "…" : a.point)}”</div>
  </a>`;
}

async function main() {
  siteHeader($("#top"), { active: "rules" });
  await initAuth();
  accountWidget($("#account"));
  initShared("prepare");
  const main = $("#main");
  main.innerHTML = `<div class="skel" style="height:44px;width:70%;margin-top:30px"></div><div class="skel" style="height:260px;margin-top:20px"></div>`;
  const r = await fetch(`/api/prepare/${encodeURIComponent(docket)}`);
  if (!r.ok) { main.innerHTML = `<div class="empty"><h2>That docket isn't on the watch list</h2><p><a href="/">See every rule</a></p></div>`; return; }
  const p = await r.json();
  const open = p.days_left != null;
  const today = new Date().toISOString().slice(0, 10);
  const stage = p.final_on ? 3 : open ? 1 : p.comments_close && p.comments_close < today ? 2 : 1;
  const adopted = p.related.filter((a) => ["adopted", "partly_adopted"].includes(a.verdict));
  const declined = p.related.filter((a) => a.verdict === "declined");
  const n = p.related.length;
  main.innerHTML = `
    <div class="prep-hero">
      <div><div class="eyebrow">${open ? "Open for comment" : p.final_on ? "Final rule out" : "Proposed rule"}</div>
        <h1 class="big" style="font-size:clamp(26px,3.4vw,38px)">${esc(p.title)}</h1>
        <div class="org-meta"><span class="chip">${esc(p.docket)}</span>${p.proposed_on ? `<span class="chip">Proposed ${date(p.proposed_on)}</span>` : ""}</div>
        ${p.abstract ? `<p class="lede" style="font-size:14.5px">${esc(p.abstract)}</p>` : ""}
        <div class="row-btns no-print" style="margin-top:16px">
          <a class="btn primary" href="${esc(p.regs_url)}" target="_blank" rel="noopener">${open ? "Comment on Regulations.gov" : "Docket on Regulations.gov"}</a>
          ${p.fr_url ? `<a class="btn" href="${esc(p.fr_url)}" target="_blank" rel="noopener">Federal Register</a>` : ""}
          <button type="button" class="btn" id="follow">☆ Follow</button>
          <a class="btn" href="/calendar.ics">Add deadlines to calendar</a>
        </div>
      </div>
      <div class="card count ${open ? "open" : ""}">${open ? `<b>${p.days_left}</b><span>day${p.days_left === 1 ? "" : "s"} left to comment<br>closes ${date(p.comments_close)}</span>` : p.comments_close ? `<b style="font-size:30px">Closed</b><span>comment period ended ${date(p.comments_close)}</span>` : `<b style="font-size:30px">–</b><span>no comment deadline listed</span>`}</div>
    </div>
    <div class="tl"><div class="pt done"><i></i>Proposed</div><div class="ln ${stage >= 2 ? "done" : ""}"></div><div class="pt ${stage === 1 ? "now" : stage > 1 ? "done" : ""}"><i></i>Comments ${open ? "open" : "close"}</div><div class="ln ${stage >= 3 ? "done" : ""}"></div><div class="pt ${stage === 3 ? "done" : ""}"><i></i>Final rule</div><div class="ln"></div><div class="pt"><i></i>Oversight maps it</div></div>

    <section class="sec"><div class="sec-head"><h2>When commenters made similar points before</h2><span class="sub">${n} past asks that match a point in this proposal, by meaning, from the rules we've mapped</span></div>
      ${n ? `<div class="card" style="padding:14px 18px"><b>${pct(adopted.length / n)}</b> of these were adopted in full or part, and <b>${pct(declined.length / n)}</b> declined. The rest EPA explained or said were already required.
        <div class="recbar" style="margin-top:10px">${Object.entries(VERDICT).map(([k, v]) => `<div style="flex:${p.tally[k] || 0};background:${v.c}"></div>`).join("")}</div></div>
      <div class="two" style="margin-top:14px">
        <div><h3><i style="background:var(--won)"></i>What EPA adopted (${adopted.length})</h3><div class="asks" style="grid-template-columns:1fr">${adopted.slice(0, 8).map(askCard).join("") || `<div class="empty">None close enough.</div>`}</div></div>
        <div><h3><i style="background:var(--lost)"></i>What EPA declined (${declined.length})</h3><div class="asks" style="grid-template-columns:1fr">${declined.slice(0, 8).map(askCard).join("") || `<div class="empty">None close enough.</div>`}</div></div>
      </div>` : `<div class="empty">Nothing in the mapped rules is close to this one yet.</div>`}
    </section>
    <section class="sec card" style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <div style="flex:1;min-width:240px"><b>Drafting a comment?</b> <span class="sub">Paste it into the coach. It shows how EPA answered past asks like each of your points, then reads the rule text and suggests edits.</span></div>
      <a class="btn primary" href="/rule/PFAS?tab=coach">Open the coach</a>
    </section>`;
  const fb = $("#follow");
  const render = (m) => { const on = m?.follows?.includes(docket); fb.innerHTML = on ? "★ Following" : "☆ Follow"; };
  fb.addEventListener("click", async () => {
    if (!signedIn()) { toast("Sign in to follow rules."); signIn(); return; }
    const on = !me()?.follows?.includes(docket);
    const res = await authFetch("/api/follow", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ docket, on }) });
    if (res.ok) { const j = await res.json(); me().follows = j.follows || (on ? [...(me().follows || []), docket] : me().follows.filter((d) => d !== docket)); render(me()); toast(on ? "Following. Updates land in the bell." : "Unfollowed", true); track("prepare:follow", { on }); }
  });
  render(me()); onMe(render); ready.then(render);
}
main();
