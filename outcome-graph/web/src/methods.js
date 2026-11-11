// How the record is built, the automated checks on every ask, people's spot checks, and the limits.
import "./pages.css";
import "./account.css";
import { initAuth, accountWidget, authFetch, onMe, ready, signIn, signedIn, toast } from "./auth.js";
import { esc, fmt, pct, VERDICT, siteHeader, initShared, track } from "./shared.js";

const $ = (s) => document.querySelector(s);
const STEPS = [
  ["Watch", "A daily job reads the Federal Register for every EPA drinking water rule since 2019."],
  ["Read", "EPA's response-to-comments document, often thousands of pages, is split into its sections."],
  ["Extract", "A model lists each thing commenters asked for and EPA's verdict, quoting EPA's own words."],
  ["Check", "Every quote is matched word for word against the document and located to a page."],
  ["Link", "Comment excerpts are tied to the ask they argue. Commenters are matched and grouped."],
];
const share = (a, b) => (b ? a / b : null);
const meter = (x) => `<div class="meter"><i style="width:${Math.round((x || 0) * 100)}%"></i></div>`;

async function main() {
  siteHeader($("#top"), { active: "methods" });
  await initAuth();
  accountWidget($("#account"));
  initShared("methods");
  const m = await fetch("/api/methods").then((r) => r.json());
  const T = m.rules.reduce((a, r) => { for (const k of ["asks", "quotes_verified", "cited", "named", "commenters", "tagged", "excerpts", "excerpts_tied", "usd"]) a[k] = (a[k] || 0) + r[k]; return a; }, {});
  const rv = m.review;
  $("#main").innerHTML = `
    <div style="margin-top:18px"><div class="eyebrow">Methods</div>
      <h1 class="big">How Oversight reads EPA, and how often it's right</h1>
      <p class="lede">Everything on the site comes from EPA's own response-to-comments documents. Here is how we turn ${fmt(T.asks)} asks across ${m.rules.length} rules into a map, the checks that run on every one, and what we can't promise.</p></div>
    <div class="pipe">${STEPS.map(([b, s], i) => `<div class="step rise-in" style="--i:${i}"><div class="dot">${i + 1}</div><div><b>${b}</b><span>${s}</span></div></div>`).join("")}</div>

    <section class="sec"><div class="sec-head"><h2>Checks on every ask</h2><span class="sub">Computed live from the data the site serves</span></div>
      <div class="card tbl-wrap"><table class="nums"><thead><tr><th>Rule</th><th>Asks</th><th>Quote matched word for word</th><th>Quote located to a page</th><th>Asks with a named commenter</th><th>Commenters given a group</th></tr></thead><tbody>
      ${m.rules.map((r) => `<tr><td><b>${esc(r.short)}</b><small>${esc(r.title)}</small></td><td class="n">${fmt(r.asks)}</td>
        <td class="n">${pct(share(r.quotes_verified, r.asks))}${meter(share(r.quotes_verified, r.asks))}</td>
        <td class="n">${pct(share(r.cited, r.asks))}${meter(share(r.cited, r.asks))}</td>
        <td class="n">${r.commenters ? pct(share(r.named, r.asks)) + meter(share(r.named, r.asks)) : "<small>EPA named no commenters</small>"}</td>
        <td class="n">${r.commenters ? pct(share(r.tagged, r.commenters)) + meter(share(r.tagged, r.commenters)) + `<small>${fmt(r.commenters)} commenters</small>` : "–"}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="sub" style="margin-top:10px">“Word for word” means EPA's text contains the quote exactly, ignoring spacing. A quote that doesn't match is sent back to the model once with the mismatch named; after that, every quote in all three rules matched. Asks without a named commenter are ones EPA summarized without quoting anyone. Extraction and matching cost $${T.usd.toFixed(2)} in model calls for all ${m.rules.length} rules.</p>
    </section>

    <section class="sec"><div class="sec-head"><h2>Spot checks by people</h2><span class="sub">A random ask, checked against EPA's paragraph</span></div>
      <div class="acc">
        <div class="tile"><b>${rv.n ? pct(rv.verdict.rate) : "–"}</b><span>verdicts judged right${rv.n ? ` · 95% range ${pct(rv.verdict.ci[0])} to ${pct(rv.verdict.ci[1])}` : ""}</span></div>
        <div class="tile"><b>${rv.n ? pct(rv.ask.rate) : "–"}</b><span>asks judged stated fairly${rv.n ? ` · 95% range ${pct(rv.ask.ci[0])} to ${pct(rv.ask.ci[1])}` : ""}</span></div>
        <div class="tile"><b>${fmt(rv.n)}</b><span>checks by ${fmt(rv.people || 0)} ${rv.people === 1 ? "person" : "people"} · ${fmt(rv.reports || 0)} problem reports</span></div>
      </div>
      ${rv.n < 30 ? `<p class="sub" style="margin-top:10px">${rv.n ? "Too few checks for a firm number yet; the range above shows how uncertain it is." : "No checks yet."} Each one takes about a minute. Check one below.</p>` : ""}
      <div class="card review" id="review"></div>
    </section>

    <section class="sec"><div class="sec-head"><h2>What we can't promise</h2></div>
      <div class="limits">
        <div class="card"><b>The model can misread EPA</b><p>Verdicts and asks are read by a model from EPA's summaries. The checks above catch made-up quotes, not every misreading. The spot checks measure that.</p></div>
        <div class="card"><b>Groups are tagged from names</b><p>“Utility”, “trade group” and the rest come from the commenter's name, so treat group totals as rough. Untagged commenters are shown as “Other or untagged”.</p></div>
        <div class="card"><b>EPA doesn't always name commenters</b><p>About a quarter of asks on the 2024 lead rule and 30% on PFAS have no named commenter, because EPA summarized the point without quoting anyone. The 2021 lead rule names nobody, so it has no scoreboard.</p></div>
        <div class="card"><b>The verdict categories are ours</b><p>EPA doesn't label its answers. “Partly adopted” and “explained, no change” are our reading of its wording, always shown next to EPA's own quote so you can judge.</p></div>
      </div>
    </section>

    <section class="sec"><div class="sec-head"><h2>Questions we get</h2></div>
      <div class="limits">
        <div class="card"><b>What counts as getting their way?</b><p>EPA adopted what the organization asked for, or declined what it argued against. Partly adopted counts as half. “Explained, no change” and “already in the rule” are no decision.</p></div>
        <div class="card"><b>Why count asks, not comments?</b><p>One letter can make twenty points, and twenty letters can make one. Counting each organization's position on each ask keeps one long letter from swamping the totals.</p></div>
        <div class="card"><b>Can I use this in my own tools?</b><p>Yes. Everything is public record. <a href="/connect">Connect it to Claude</a>, export any list as CSV, or subscribe to the <a href="/calendar.ics">deadline calendar</a>.</p></div>
        <div class="card"><b>Found a mistake?</b><p>Every ask and scorecard has a “Something wrong?” button. Reports go to the team and count toward the numbers above.</p></div>
      </div>
    </section>`;
  const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && e.target.classList.add("seen")));
  document.querySelectorAll(".rise-in").forEach((el) => io.observe(el));
  reviewer();
}

async function reviewer() {
  const box = $("#review");
  box.innerHTML = `<div class="skel" style="height:160px"></div>`;
  const r = await authFetch("/api/review/next").then((x) => (x.ok ? x.json() : x.json().then((j) => ({ error: j.detail })))).catch(() => ({ error: "Couldn't load an ask." }));
  if (r.error) { box.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
  const v = VERDICT[r.verdict] || { l: r.verdict, c: "#8b9bb4" };
  let ctx = esc(r.context || "");
  if (r.context && r.quote) { const i = r.context.indexOf(r.quote.slice(0, 40)); if (i >= 0) ctx = esc(r.context.slice(0, i)) + "<mark>" + esc(r.context.slice(i, i + r.quote.length)) + "</mark>" + esc(r.context.slice(i + r.quote.length)); }
  const ans = { verdict_ok: null, ask_ok: null };
  box.innerHTML = `<div class="sub">${esc(r.rule)} · section ${esc(r.code || "")}${r.page ? ` · p. ${r.page} · <a href="/rtc/${esc(r.rule)}.pdf#page=${r.page}" target="_blank" rel="noopener">open the PDF</a>` : ""}${r.reviewed_by_you ? ` · you've checked ${r.reviewed_by_you}` : ""}</div>
    <div class="rv-q">${esc(r.ask)}</div>
    <div><span class="pill" style="--vc:${v.c}">We say: ${v.l}</span></div>
    <div class="rv-quote" style="--vc:${v.c};margin-top:10px">“${esc(r.quote || "")}”</div>
    ${r.final_rule_change ? `<div class="sub" style="margin-top:8px"><b>We say the final rule changed:</b> ${esc(r.final_rule_change)}</div>` : ""}
    ${ctx ? `<div class="rv-ctx"><b>EPA's paragraph:</b> ${ctx}</div>` : ""}
    <div class="rv-ask">
      <fieldset><legend>Is the verdict right?</legend><div class="yn" data-k="verdict_ok"><button type="button" class="y" data-v="1">Yes</button><button type="button" class="n" data-v="0">No</button>
        <select id="rv-right" hidden><option value="">It should be…</option>${Object.entries(VERDICT).filter(([k]) => k !== r.verdict).map(([k, x]) => `<option value="${k}">${x.l}</option>`).join("")}</select></div></fieldset>
      <fieldset><legend>Is the ask stated fairly?</legend><div class="yn" data-k="ask_ok"><button type="button" class="y" data-v="1">Yes</button><button type="button" class="n" data-v="0">No</button></div></fieldset>
    </div>
    <div class="row-btns" style="margin-top:14px;justify-content:flex-end"><button type="button" class="btn" id="rv-skip">Skip</button><button type="button" class="btn primary" id="rv-go" disabled>${signedIn() ? "Submit and next" : "Sign in to submit"}</button></div>`;
  box.querySelectorAll(".yn").forEach((g) => g.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    g.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    ans[g.dataset.k] = b.dataset.v === "1";
    if (g.dataset.k === "verdict_ok") $("#rv-right").hidden = ans.verdict_ok;
    $("#rv-go").disabled = ans.verdict_ok === null || ans.ask_ok === null;
  })));
  $("#rv-skip").addEventListener("click", reviewer);
  $("#rv-go").addEventListener("click", async () => {
    if (!signedIn()) { signIn(); return; }
    const res = await authFetch("/api/review", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ docket: r.docket, ask_id: r.id, ...ans, right_verdict: $("#rv-right").value || null }) });
    if (res.ok) { toast("Thanks. Logged.", true); track("review", ans); reviewer(); } else toast("Couldn't save that.");
  });
  onMe(() => { const b = $("#rv-go"); if (b) b.textContent = signedIn() ? "Submit and next" : "Sign in to submit"; });
}
main();
