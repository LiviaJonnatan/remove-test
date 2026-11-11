// An organization's scorecard across every mapped rule: did EPA do what they asked?
import "./pages.css";
import "./account.css";
import { initAuth, accountWidget, authFetch, onMe, ready, signIn, signedIn, me, toast } from "./auth.js";
import { esc, fmt, pct, VERDICT, OUTCOME, siteHeader, initShared, track, reportProblem } from "./shared.js";

const $ = (s) => document.querySelector(s);
const slug = decodeURIComponent(location.pathname.split("/")[2] || "");
const SIDE = { for: ["asked for it", "for"], against: ["argued against it", "against"] };

function ring(rec) {
  const order = ["won", "partly", "lost", "no_change"], tot = order.reduce((a, k) => a + (rec[k] || 0), 0) || 1;
  const R = 120, C = 2 * Math.PI * R;
  let off = 0;
  const segs = order.map((k) => {
    const len = (C * (rec[k] || 0)) / tot, gap = len > 6 ? 3 : 0;
    const s = `<circle class="seg" r="${R}" cx="150" cy="150" stroke="${OUTCOME[k][1]}" stroke-dasharray="${Math.max(0, len - gap)} ${C}" stroke-dashoffset="${C}" data-off="${-off}"/>`;
    off += len;
    return s;
  }).join("");
  return `<svg viewBox="0 0 300 300"><circle r="${R}" cx="150" cy="150" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="22"/>${segs}</svg>`;
}
function countUp(el, to, ms = 1100, suffix = "") {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = to + suffix; return; }
  const t0 = performance.now();
  const f = (t) => { const p = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - p, 3); el.textContent = Math.round(to * e) + suffix; if (p < 1) requestAnimationFrame(f); };
  requestAnimationFrame(f);
}
const recbar = (r) => `<div class="recbar">${["won", "partly", "lost", "no_change"].map((k) => `<div style="flex:${r[k] || 0};background:${OUTCOME[k][1]}" title="${OUTCOME[k][0]}: ${r[k] || 0}"></div>`).join("")}</div>`;

function askCard(a, short) {
  const v = VERDICT[a.verdict] || { l: a.verdict, c: "#8b9bb4" };
  return `<a class="ask rise-in" href="/rule/${esc(short)}?n=${encodeURIComponent(a.id)}" data-o="${a.outcome}">
    <div class="ask-top"><span class="pill" style="--vc:${v.c}">${v.l}</span><span class="tag ${SIDE[a.side][1]}">${a.side === "for" ? "They asked for it" : "They argued against it"}</span>${a.changed ? `<span class="tag">changed the rule</span>` : ""}<span class="code">§ ${esc(a.code || "")}</span></div>
    <h4>${esc(a.label)}</h4>
    ${a.quote ? `<div class="epa"><b>EPA:</b> ${esc(a.quote.length > 240 ? a.quote.slice(0, 239) + "…" : a.quote)}${a.page ? ` <span class="pg">p. ${a.page}</span>` : ""}</div>` : ""}
    ${a.final_rule_change ? `<div class="eff"><b>Final rule:</b> ${esc(a.final_rule_change.length > 180 ? a.final_rule_change.slice(0, 179) + "…" : a.final_rule_change)}</div>` : ""}
  </a>`;
}

function ruleSection(r) {
  const tabs = [["all", "All", null, r.asks.length], ...Object.entries(OUTCOME).map(([k, [l, c]]) => [k, l, c, r.record[k] || 0])].filter((t) => t[3]);
  const shown = 6;
  return `<section class="rule-sec" data-rule="${esc(r.short)}">
    <div class="rule-top"><h2><a href="/rule/${esc(r.short)}">${esc(r.title)}</a></h2>${recbar(r.record)}<span class="sub">${r.asks.length} asks · final ${esc(r.final || "")}</span></div>
    <div class="seg-tabs">${tabs.map(([k, l, c, n], i) => `<button type="button" data-k="${k}" class="${i ? "" : "on"}">${c ? `<i style="background:${c}"></i>` : ""}${l} <span class="n">${n}</span></button>`).join("")}</div>
    <div class="asks">${r.asks.map((a, i) => askCard(a, r.short).replace('class="ask rise-in"', `class="ask rise-in"${i >= shown ? " hidden" : ""}`)).join("")}</div>
    ${r.asks.length > shown ? `<button type="button" class="btn more no-print">Show all ${r.asks.length}</button>` : ""}
  </section>`;
}

function wireSection(sec) {
  const cards = [...sec.querySelectorAll(".ask")];
  let k = "all", all = false;
  const apply = () => {
    let n = 0;
    cards.forEach((c) => { const ok = k === "all" || c.dataset.o === k; c.hidden = !ok || (!all && n >= 6); if (ok) n++; if (!c.hidden) c.classList.add("seen"); });
    const more = sec.querySelector(".more");
    if (more) { more.hidden = all || n <= 6; more.textContent = `Show all ${n}`; }
  };
  sec.querySelectorAll(".seg-tabs button").forEach((b) => b.addEventListener("click", () => {
    sec.querySelectorAll(".seg-tabs button").forEach((x) => x.classList.toggle("on", x === b));
    k = b.dataset.k; apply(); track("org:tab", { k });
  }));
  sec.querySelector(".more")?.addEventListener("click", () => { all = true; apply(); });
  apply();
}

function followBtn(o) {
  const b = $("#follow");
  const render = (m) => {
    const on = m?.org_follows?.includes(o.slug);
    b.innerHTML = on ? "★ Following" : "☆ Follow";
    b.classList.toggle("primary", !on);
    b.title = on ? "You'll get an update when EPA finalizes a rule they commented on" : "Get an update when EPA decides on something they asked for";
  };
  b.addEventListener("click", async () => {
    if (!signedIn()) { toast("Sign in to follow organizations."); signIn(); return; }
    const on = !me()?.org_follows?.includes(o.slug);
    const r = await authFetch("/api/follow-org", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ slug: o.slug, on }) });
    if (r.ok) { me().org_follows = (await r.json()).org_follows; render(me()); toast(on ? `Following ${o.name}` : "Unfollowed", true); track("org:follow", { on }); }
  });
  render(me()); onMe(render); ready.then(render);
}

async function main() {
  siteHeader($("#top"));
  await initAuth();
  accountWidget($("#account"));
  initShared("org");
  const main = $("#main");
  main.innerHTML = `<div class="skel" style="height:44px;width:60%;margin-top:30px"></div><div class="skel" style="height:300px;margin-top:20px"></div>`;
  const r = await fetch(`/api/org/${encodeURIComponent(slug)}`);
  if (!r.ok) { main.innerHTML = `<div class="empty"><h2>We don't have that organization</h2><p>Press <kbd>⌘K</kbd> to search every commenter.</p></div>`; return; }
  const o = await r.json();
  document.title = `${o.name} · Oversight`;
  const peer = o.peer, me_ = o.share;
  main.innerHTML = `
    <div class="org-hero">
      <div>
        <div class="eyebrow">Commenter scorecard</div>
        <h1 class="big">${esc(o.name)}${o.acronym ? ` <span style="color:var(--ink-3);font-weight:500">(${esc(o.acronym)})</span>` : ""}</h1>
        <div class="org-meta"><span class="chip solid">${esc(o.group_label)}</span>${o.rule_list.map((r) => `<a class="chip" href="/rule/${esc(r.short)}?n=${encodeURIComponent(r.node)}" title="Open them on the ${esc(r.short)} map">${esc(r.short)} map →</a>`).join("")}</div>
        <p class="lede">${o.decided ? `When EPA made a decision on something ${esc(o.name)} took a side on, it went their way <b style="color:var(--won)">${pct(o.share)}</b> of the time, across ${o.decided} decided asks.` : `${esc(o.name)} commented, but EPA made no adopt-or-decline decision on the asks they took a side on.`}</p>
        <div class="row-btns no-print" style="margin-top:18px">
          <button type="button" class="btn" id="follow">☆ Follow</button>
          <button type="button" class="btn" id="share">Copy link</button>
          <a class="btn" href="/og/org/${esc(o.slug)}.png" target="_blank" rel="noopener">Share card</a>
          <button type="button" class="btn" id="print">Print briefing</button>
          <button type="button" class="btn" id="csv">CSV</button>
        </div>
      </div>
      <div class="ring-box">${ring(o.record)}<div class="ring-mid"><div><b id="pct">0%</b><span>of decided asks went their way</span></div></div></div>
    </div>
    <div class="tiles">
      <div class="tile"><b>${fmt(o.asks)}</b><span>asks they took a side on</span></div>
      <div class="tile"><b style="color:var(--won)">${fmt(o.record.won)}</b><span>got their way</span></div>
      <div class="tile"><b style="color:var(--lost)">${fmt(o.record.lost)}</b><span>did not</span></div>
      <div class="tile"><b>${fmt(o.excerpts)}</b><span>comment excerpts EPA quoted</span></div>
    </div>
    ${peer && me_ != null ? `<div class="compare">
      <div><b>${o.rank ? `Ranked ${o.rank} of ${o.ranked_n}` : "Not ranked (fewer than 8 decided asks)"}</b> <span class="sub">among organizations with 8 or more decided asks.</span> ${esc(peer.label)} average ${pct(peer.mean)} (${peer.n} organizations).</div>
      <div class="cmp-bar"><i class="avg" style="left:calc(${peer.mean * 100}% - 1px)" title="${esc(peer.label)} average"></i><i class="me" style="left:calc(${me_ * 100}% - 1px)" title="${esc(o.name)}"></i></div>
      <div class="cmp-legend"><span>0%</span><span><b style="color:var(--won)">|</b> ${esc(o.acronym || o.name.split(" ").slice(0, 3).join(" "))} &nbsp; <b style="color:var(--ink-3)">|</b> ${esc(peer.label)} average</span><span>100%</span></div>
    </div>` : ""}
    <div class="print-only" style="margin-top:12px;color:#444">Got their way = EPA adopted what they asked for, or declined what they argued against. Source: EPA response-to-comments documents. ${esc(location.href)}</div>
    ${o.rule_list.map(ruleSection).join("")}
    <div class="sec card no-print" style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <div style="flex:1;min-width:240px"><b>How to read this.</b> <span class="sub">Each ask is one thing commenters asked EPA for, read from EPA's response document. Got their way means EPA adopted what ${esc(o.name)} asked for, or declined what they argued against. Partly adopted counts as half in the percentage. Names are matched across rules and spellings${o.names.length > 1 ? `: ${o.names.slice(0, 3).map(esc).join("; ")}` : ""}.</span></div>
      <div class="row-btns"><a class="btn" href="/methods">Methods and accuracy</a><button type="button" class="btn" id="wrong">Something wrong?</button><a class="btn primary" href="/rule/${esc(o.rule_list[0]?.short || "PFAS")}?ask=${encodeURIComponent(`What did ${o.name} ask for, and what did EPA do?`)}">Ask Iris about them</a></div>
    </div>`;
  // the ring draws itself in, segment by segment
  requestAnimationFrame(() => setTimeout(() => main.querySelectorAll(".ring-box .seg").forEach((s, i) => { s.style.transitionDelay = `${i * 120}ms`; s.style.strokeDashoffset = s.dataset.off; }), 80));
  if (o.share != null) countUp($("#pct"), Math.round(o.share * 100), 1200, "%"); else $("#pct").textContent = "n/a";
  main.querySelectorAll(".rule-sec").forEach(wireSection);
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("seen"); io.unobserve(e.target); } }));
  main.querySelectorAll(".rise-in").forEach((el, i) => { el.style.setProperty("--i", i % 6); io.observe(el); });
  followBtn(o);
  $("#share").addEventListener("click", (e) => navigator.clipboard?.writeText(location.href).then(() => { e.target.textContent = "Link copied"; track("org:share"); setTimeout(() => (e.target.textContent = "Copy link"), 1500); }));
  $("#print").addEventListener("click", () => { track("org:print"); main.querySelectorAll(".ask").forEach((c) => (c.hidden = false)); print(); });
  $("#csv").addEventListener("click", () => {
    const q = (x) => `"${String(x ?? "").replace(/"/g, '""')}"`;
    const rows = [["rule", "section", "ask", "their side", "EPA verdict", "outcome for them", "changed the rule", "EPA said", "page", "final rule change"]];
    for (const r of o.rule_list) for (const a of r.asks) rows.push([r.short, a.code, a.label, a.side, VERDICT[a.verdict]?.l, OUTCOME[a.outcome][0], a.changed ? "yes" : "no", a.quote, a.page, a.final_rule_change]);
    const url = URL.createObjectURL(new Blob([rows.map((r) => r.map(q).join(",")).join("\n")], { type: "text/csv" }));
    Object.assign(document.createElement("a"), { href: url, download: `${o.slug}-oversight.csv` }).click();
    track("org:csv");
  });
  $("#wrong").addEventListener("click", () => reportProblem({ node_id: `org:${o.slug}`, label: o.name }));
}
main();
