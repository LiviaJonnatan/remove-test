import "./landing.css";
import "./account.css";
import { initAuth, accountWidget, onMe, ready, authFetch, saveProfile, signIn, toast, ORG_TYPES, config as authConfig } from "./auth.js";
import { createMascot } from "./mascot.js";
import { heroRing, countUp, reveal, say } from "./hero.js";
import { initShared, track, pct as pctOf } from "./shared.js";

let IRIS = null;

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const VERDICT = [
  ["adopted", "Adopted", "#3ddc97"], ["partly_adopted", "Partly adopted", "#f5c451"], ["declined", "Declined", "#ff6b6b"],
  ["clarified", "Clarified only", "#8b9bb4"], ["already_required", "Already required", "#a98bff"],
];
const date = (s) => s ? new Date(s + (s.length === 10 ? "T12:00:00" : "")).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
const ago = (s) => {
  const d = (Date.now() - new Date(s)) / 1000;
  if (d < 90) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return `${Math.round(d / 86400)} d ago`;
};

let RULES = [];
const shortOf = (docket) => RULES.find((r) => r.docket === docket)?.short || docket;

function status(r) {
  const today = new Date().toISOString().slice(0, 10);
  if (r.status === "open_for_comment" || (r.status === "proposed" && r.comments_close >= today))
    return ["open", `Comments open until ${date(r.comments_close)}`];
  return {
    proposed: ["prop", "Proposed, waiting on the final rule"],
    awaiting_rtc: ["await", "Final, no response document yet"],
    processing: ["proc", "Building the map"],
    failed: ["fail", "Build failed"],
  }[r.status] || ["prop", r.status];
}

function card(r, follows) {
  const v = r.verdicts || {};
  const total = VERDICT.reduce((a, [k]) => a + (v[k] || 0), 0) || 1;
  const on = follows?.includes(r.docket);
  return `<a class="card reveal" style="--i:${CARD_I++}" href="/rule/${esc(r.short)}">
    <div class="c-top"><span class="c-short">${esc(r.short)}</span><span class="c-dates">${esc(r.proposed || "")} → ${esc(r.final || "")}</span>
      ${follows ? `<button class="follow ${on ? "on" : ""}" data-d="${esc(r.docket)}" title="${on ? "Following: it's listed under Your work" : "Follow this rule: it's listed under Your work"}">${on ? "★" : "☆"}</button>` : ""}</div>
    <h3>${esc(r.title)}</h3>
    <div class="c-bar">${VERDICT.map(([k, l, c], j) => v[k] ? `<span title="${l}: ${fmt(v[k])}" style="flex:${v[k]};background:${c};--j:${j}"></span>` : "").join("")}</div>
    <div class="c-stats">
      <span><b>${fmt(r.asks || 0)}</b> asks</span>
      <span><b style="color:#3ddc97">${Math.round(100 * ((v.adopted || 0) + (v.partly_adopted || 0)) / total)}%</b> adopted in part or full</span>
      <span><b>${fmt(r.changed || 0)}</b> changed the rule</span>
    </div>
    <div class="c-foot">${r.comments ? `${fmt(r.comments)} comments EPA answered by name` : "EPA summarized comments without naming commenters"}<span class="go">Open →</span></div>
  </a>`;
}

let CARD_I = 0, ROW_I = 0;
function watchRow(r) {
  const [cls, label] = status(r);
  const today = new Date().toISOString().slice(0, 10);
  const when = r.final_on ? `Final ${date(r.final_on)}` : r.proposed_on ? `Proposed ${date(r.proposed_on)}` : "";
  const closed = r.status === "proposed" && r.comments_close && r.comments_close < today ? ` · comment period closed ${date(r.comments_close)}` : "";
  const open = cls === "open";
  // a review of a rule we already map: say so, and link to it
  const mapped = RULES.find((x) => x.status === "ready" && r.title.includes(x.title));
  return `<div class="wrow reveal${open ? " is-open" : ""}" style="--i:${Math.min(ROW_I++, 12)}">
    <span class="chip ${cls}">${esc(label)}</span>
    <span class="w-title">${esc(r.title)}${mapped ? ` <a class="w-map" href="/rule/${esc(mapped.short)}">a separate action; see the ${esc(mapped.short)} map →</a>` : ""}</span>
    <span class="w-meta">${esc(when)}${esc(closed)} · <span class="mono">${esc(r.docket)}</span>${r.fr_url ? ` · <a href="${esc(r.fr_url)}" target="_blank" rel="noopener">Federal Register</a>` : ""} · <a href="https://www.regulations.gov/docket/${encodeURIComponent(r.docket)}" target="_blank" rel="noopener">${open ? "Comment on Regulations.gov" : "Regulations.gov"}</a>${r.status === "proposed" || open ? ` · <a href="/prepare/${encodeURIComponent(r.docket)}">${open ? "Prepare a comment" : "How EPA answered similar points"} →</a>` : ""}</span>
  </div>`;
}

function renderRules(me) {
  const ready = RULES.filter((r) => r.status === "ready");
  const watch = RULES.filter((r) => r.status !== "ready");
  const rank = { open_for_comment: 0, proposed: 1, processing: 2, awaiting_rtc: 3, failed: 4 };
  watch.sort((a, b) => (status(a)[0] === "open" ? -1 : 0) - (status(b)[0] === "open" ? -1 : 0) || rank[a.status] - rank[b.status]
    || String(b.final_on || b.proposed_on).localeCompare(String(a.final_on || a.proposed_on)));
  CARD_I = 0; ROW_I = 0;
  $("#ready").innerHTML = ready.map((r) => card(r, me ? me.follows : null)).join("");
  $("#ready-note").textContent = `${ready.length} rules · ${fmt(ready.reduce((a, r) => a + (r.asks || 0), 0))} asks`;
  const openN = watch.filter((r) => status(r)[0] === "open").length;
  $("#watch").innerHTML = (watch.length ? `<div class="w-open-note">${openN ? `<b>${openN} open for comment now.</b> They're at the top.` : "<b>No EPA drinking water rule is open for comment right now.</b> Proposed rules show when their comment period closed."}</div>` + watch.map(watchRow).join("") : `<div class="empty">The watcher has not run yet.</div>`);
  reveal();
  wireCards();
  document.querySelectorAll(".follow").forEach((b) => b.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();
    const on = !b.classList.contains("on");
    const r = await authFetch("/api/follow", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ docket: b.dataset.d, on }) });
    if (r.ok) { b.classList.toggle("on", on); b.textContent = on ? "★" : "☆"; }
  }));
}

async function renderYours(me) {
  const el = $("#yours");
  if (!authConfig()?.accounts) { el.hidden = true; return; }
  if (!me) {
    el.hidden = false;
    el.innerHTML = `<div class="pitch"><div><b>Sign in to keep your work.</b> Iris remembers your earlier questions and your organization, your draft comments and every check on them are saved, and you can follow rules. Signed out, everything is open to browse and nothing is stored.</div><button type="button" class="pitch-in">Sign in with Google</button></div>`;
    el.querySelector(".pitch-in").addEventListener("click", () => signIn());
    return;
  }
  el.hidden = false;
  el.innerHTML = `<div class="sec-head"><h2>Your work</h2><span class="sec-note">${esc(me.user.email)}</span></div><div class="y-grid"><div class="y-col sk-col"></div><div class="y-col sk-col"></div></div>`;
  const [convs, drafts] = await Promise.all([
    authFetch("/api/conversations").then((r) => r.json()).catch(() => []),
    authFetch("/api/drafts").then((r) => r.json()).catch(() => []),
  ]);
  const u = me.user;
  const editing = !u.org_type || el.dataset.edit === "1";
  const profile = !editing ? `<div class="p-line">${esc(u.name || "")}${u.name ? " · " : ""}${esc(u.email)} · <b>${esc(ORG_TYPES[u.org_type] || u.org_type)}</b>${u.org_name ? ` at ${esc(u.org_name)}` : ""} <button type="button" class="linkish" id="p-edit">Edit</button></div>` : `<div class="profile">
      <div><b>What kind of commenter are you?</b> Iris uses it to point you at what groups like yours won and lost.</div>
      <div class="p-row"><select id="p-type"><option value="">Choose one</option>${Object.entries(ORG_TYPES).map(([k, l]) => `<option value="${k}" ${u.org_type === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <input id="p-org" placeholder="Organization (optional)" value="${esc(u.org_name || "")}" /><button id="p-save" type="button" ${u.org_type ? "" : "disabled"}>Save</button></div></div>`;
  const follows = (me.follows || []).map((d) => RULES.find((r) => r.docket === d)).filter(Boolean);
  el.innerHTML = `<div class="sec-head"><h2>Your work</h2><span class="sec-note">${esc(u.email)}</span></div>${profile}
    ${follows.length ? `<div class="p-follow">Following: ${follows.map((r) => `<a href="/rule/${esc(r.short)}">${esc(r.short)}</a>`).join(" · ")}</div>` : ""}
    <div class="y-grid">
      <div class="y-col"><h4>Conversations with Iris</h4>${convs.length ? convs.slice(0, 6).map((c) => `<a class="y-item" href="/rule/${esc(shortOf(c.docket))}?c=${esc(c.id)}"><span class="y-tag">${esc(shortOf(c.docket))}</span><span class="y-t">${esc(c.title)}</span><span class="y-m">${c.n} message${c.n === 1 ? "" : "s"} · ${ago(c.updated_at)}</span><button type="button" class="y-del" data-del="conversations/${esc(c.id)}" title="Delete this chat" aria-label="Delete this chat">×</button></a>`).join("") : `<div class="y-empty">None yet. Open a rule and ask Iris anything.</div>`}</div>
      <div class="y-col"><h4>Draft comments</h4>${drafts.length ? drafts.slice(0, 6).map((d) => `<a class="y-item" href="/rule/${esc(shortOf(d.docket))}?draft=${esc(d.id)}"><span class="y-tag">${esc(shortOf(d.docket))}</span><span class="y-t">${esc(d.title)}…</span><span class="y-m">${d.runs} check${d.runs === 1 ? "" : "s"} · ${ago(d.updated_at)}</span><button type="button" class="y-del" data-del="drafts/${esc(d.id)}" title="Delete this draft" aria-label="Delete this draft">×</button></a>`).join("") : `<div class="y-empty">None yet. Open a rule, then the Coach tab.</div>`}</div>
    </div>`;
  el.querySelectorAll(".y-del").forEach((b) => b.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();
    if (!b.classList.contains("sure")) {  // two clicks, no browser dialog
      b.classList.add("sure"); b.textContent = "Delete?";
      setTimeout(() => { b.classList.remove("sure"); b.textContent = "×"; }, 3000);
      return;
    }
    const r = await authFetch(`/api/${b.dataset.del}`, { method: "DELETE" });
    if (r.ok) { b.closest(".y-item").remove(); toast("Deleted", true); } else toast("Couldn't delete that.");
  }));
  $("#p-type")?.addEventListener("change", (e) => { $("#p-save").disabled = !e.target.value; });
  $("#p-edit")?.addEventListener("click", () => { el.dataset.edit = "1"; renderYours(me); });
  $("#p-save")?.addEventListener("click", async () => {
    const t = $("#p-type").value;
    if (!t) return;
    el.dataset.edit = "";
    await saveProfile({ org_type: t, org_name: $("#p-org").value.trim() || null });
    toast("Saved. Iris will use it, and the Scores tab marks your group.", true);
  });
  // returning visitors: one line under the hero to pick up where they left off
  const last = [...convs.map((c) => ({ t: c.updated_at, href: `/rule/${shortOf(c.docket)}?c=${c.id}`, label: `your chat “${c.title}”` })),
    ...drafts.map((d) => ({ t: d.updated_at, href: `/rule/${shortOf(d.docket)}?draft=${d.id}`, label: `your draft “${d.title}…”` }))].sort((a, b) => String(b.t).localeCompare(String(a.t)))[0];
  const cont = $("#continue");
  if (cont) { cont.hidden = !last; if (last) cont.innerHTML = `Continue: <a href="${esc(last.href)}">${esc(last.label.length > 70 ? last.label.slice(0, 69) + "…”" : last.label)}</a>`; }
}

function wireCards() {  // cards tilt toward the pointer, and Iris looks at the one you're on
  document.querySelectorAll("#ready .card").forEach((c) => {
    c.addEventListener("pointermove", (e) => {
      const b = c.getBoundingClientRect(), x = (e.clientX - b.left) / b.width - 0.5, y = (e.clientY - b.top) / b.height - 0.5;
      c.style.setProperty("--rx", `${-y * 6}deg`); c.style.setProperty("--ry", `${x * 8}deg`);
      c.style.setProperty("--mx", `${(x + 0.5) * 100}%`); c.style.setProperty("--my", `${(y + 0.5) * 100}%`);
      IRIS?.lookAt(e.clientX, e.clientY, 600);
    });
    c.addEventListener("pointerenter", () => IRIS?.react("happy"));
    c.addEventListener("pointerleave", () => { c.style.setProperty("--rx", "0deg"); c.style.setProperty("--ry", "0deg"); });
  });
}

function startHero() {
  const totals = { asks: 0, comments: 0, changed: 0 }, verdicts = {};
  for (const r of RULES.filter((x) => x.status === "ready")) {
    totals.asks += r.asks || 0; totals.comments += r.comments || 0; totals.changed += r.changed || 0;
    for (const [k, n] of Object.entries(r.verdicts || {})) verdicts[k] = (verdicts[k] || 0) + n;
  }
  document.querySelectorAll("[data-count]").forEach((el, i) => setTimeout(() => countUp(el, totals[el.dataset.count]), 500 + i * 150));
  try {
    IRIS = createMascot($("#hero-iris"), { size: 280 });
    window.__iris = IRIS;  // used by the screenshot tests
    setTimeout(() => { IRIS.react("wave"); say($("#hero-bubble"), "Hi, I'm Iris. I read every EPA response so you don't have to."); }, 900);
  } catch (e) { console.warn("[oversight] no WebGL, Iris stays home", e); }
  heroRing($("#hero-ring"), Object.keys(verdicts).length ? verdicts : { adopted: 1 }, IRIS);
  $("#account")?.addEventListener("pointerenter", () => { if (IRIS) { const b = $("#account").getBoundingClientRect(); IRIS.lookAt(b.left + b.width / 2, b.top + b.height / 2, 1500); } });
  document.querySelectorAll(".cta").forEach((a) => a.addEventListener("pointerenter", () => IRIS?.react("happy")));
}

// ------------------------------------------------------------------ find your organization
function finder() {
  const input = $("#finder"), list = $("#finder-list");
  let rows = [], sel = 0, t = null, seq = 0;
  const draw = () => {
    list.hidden = !rows.length && !input.value.trim();
    list.innerHTML = rows.length ? rows.map((o, i) => `<a class="fr${i === sel ? " sel" : ""}" href="/org/${esc(o.slug)}">
        <span class="fr-n">${esc(o.name)}${o.acronym ? ` <i>${esc(o.acronym)}</i>` : ""}</span>
        <span class="fr-m">${esc(o.group_label)} · ${o.rules.join(", ")}</span>
        <span class="fr-p" style="color:${o.share == null ? "#6f7a90" : o.share >= 0.5 ? "#3ddc97" : "#ff8a8a"}">${o.share == null ? "–" : pctOf(o.share)}</span></a>`).join("")
      : `<div class="fr-e">No organization by that name in the mapped rules. Try its acronym, or press ⌘K to search asks too.</div>`;
  };
  const load = async () => {
    const my = ++seq, q = input.value.trim();
    if (!q) { rows = []; list.hidden = true; return; }
    const r = await fetch(`/api/orgs?q=${encodeURIComponent(q)}&limit=6`).then((x) => x.json()).catch(() => []);
    if (my === seq) { rows = r; sel = 0; draw(); }
  };
  input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 100); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(rows.length - 1, sel + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && rows[sel]) { track("finder:open", { slug: rows[sel].slug }); location.href = `/org/${rows[sel].slug}`; }
    else if (e.key === "Escape") { list.hidden = true; input.blur(); }
  });
  input.addEventListener("focus", () => { if (rows.length) list.hidden = false; IRIS?.react("happy"); });
  input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
}

// ------------------------------------------------------------------ "I'm with a…": a starting point per kind of user
const ROLES = {
  utility: ["Water utility", [["What utilities won and lost on PFAS", "/rule/PFAS?who=utility&list=1"], ["AWWA's scorecard", "/org/american-water-works-association"], ["Check a draft comment", "/rule/PFAS?tab=coach"]]],
  advocacy: ["Advocacy group", [["What advocacy groups won on PFAS", "/rule/PFAS?who=advocacy&list=1"], ["NRDC's scorecard", "/org/natural-resources-defense-council"], ["Asks that changed the lead rule", "/rule/LCRI?changed=1&list=1"]]],
  trade: ["Trade group", [["What trade groups won on PFAS", "/rule/PFAS?who=trade&list=1"], ["Who got their way, by group", "/rule/PFAS?tab=score"], ["Check a draft comment", "/rule/PFAS?tab=coach"]]],
  state: ["State or local agency", [["What states won on PFAS", "/rule/PFAS?who=state&list=1"], ["ASDWA's scorecard", "/org/association-of-state-drinking-water-administrators"], ["Deadline calendar", "/calendar.ics"]]],
  press: ["Reporter", [["Who got their way on PFAS", "/rule/PFAS?tab=score"], ["Every ask that changed the PFAS rule", "/rule/PFAS?changed=1&list=1"], ["How accurate this is", "/methods"]]],
  academic: ["Researcher", [["Methods and accuracy", "/methods"], ["Use it in Claude", "/connect"], ["Spot-check an ask", "/methods#review"]]],
};
function roles(me) {
  const el = $("#roles");
  let pick = me?.user?.org_type in ROLES ? me.user.org_type : null;
  try { pick ||= localStorage.getItem("ov-role"); } catch { /* private window */ }
  const draw = () => {
    el.innerHTML = `<div class="roles-q">I'm with a</div><div class="roles-chips">${Object.entries(ROLES).map(([k, [l]]) => `<button type="button" data-r="${k}" class="${k === pick ? "on" : ""}">${l}</button>`).join("")}</div>
      ${pick ? `<div class="roles-go">${ROLES[pick][1].map(([l, u]) => `<a href="${u}">${esc(l)} <span>→</span></a>`).join("")}</div>` : ""}`;
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      pick = pick === b.dataset.r ? null : b.dataset.r;
      try { pick ? localStorage.setItem("ov-role", pick) : localStorage.removeItem("ov-role"); } catch { /* fine */ }
      track("role", { role: pick }); IRIS?.react("happy"); draw();
    }));
  };
  draw();
}

// ------------------------------------------------------------------ scorecards: the most quoted organizations
async function scorecards() {
  const orgs = await fetch("/api/orgs?limit=12").then((r) => r.json()).catch(() => []);
  const el = $("#scores");
  el.innerHTML = orgs.filter((o) => o.decided >= 8).slice(0, 8).map((o, i) => {
    const r = o.record, tot = r.won + r.partly + r.lost + r.no_change || 1;
    return `<a class="sc reveal" style="--i:${i}" href="/org/${esc(o.slug)}">
      <div class="sc-top"><span class="sc-g">${esc(o.group_label)}</span><span class="sc-r">${o.rules.join(" · ")}</span></div>
      <b class="sc-n">${esc(o.acronym || o.name)}</b><span class="sc-full">${o.acronym ? esc(o.name) : "&nbsp;"}</span>
      <div class="sc-p"><b style="color:${o.share >= 0.5 ? "#3ddc97" : "#ff8a8a"}">${pctOf(o.share)}</b> of ${o.decided} decided asks went their way</div>
      <div class="c-bar">${[["won", "#3ddc97"], ["partly", "#f5c451"], ["lost", "#ff6b6b"], ["no_change", "#5b6579"]].map(([k, c], j) => r[k] ? `<span style="flex:${r[k]};background:${c};--j:${j}"></span>` : "").join("")}</div>
    </a>`;
  }).join("") + `<button type="button" class="sc sc-more" data-palette><b>Find any commenter</b><span>Press ⌘K to search every organization, topic and ask</span></button>`;
  reveal();
}

async function main() {
  await initAuth();
  accountWidget($("#account"));
  initShared("landing");
  finder();
  roles(null);
  scorecards();
  fetch("/api/methods").then((r) => r.json()).then((m) => {
    const t = m.rules.reduce((a, r) => [a[0] + r.quotes_verified, a[1] + r.asks], [0, 0]);
    $("#way-acc").textContent = `${Math.round((100 * t[0]) / t[1])}% of quotes matched word for word →`;
  }).catch(() => {});
  const rulesP = fetch("/api/rules").then((r) => r.json());
  fetch("/api/watcher").then((r) => r.json()).then((w) => {
    if (w.last) $("#watch-note").textContent = `Checked ${ago(w.last.finished_at)}, from ${w.last.seen} Federal Register documents`;
  }).catch(() => {});
  RULES = await rulesP.catch(() => []);
  startHero();
  renderRules(null);  // content first; sign-in state fills in when it arrives
  const me = await ready;
  renderRules(me);
  renderYours(me);
  roles(me);
  if (me && IRIS) setTimeout(() => say($("#hero-bubble"), `Welcome back${me.user.name ? ", " + me.user.name.split(" ")[0] : ""}. Your chats and drafts are below.`), 4200);
  onMe((m) => {
    renderRules(m); renderYours(m);
    if (!m) { const c = $("#continue"); if (c) c.hidden = true; }
    if (!IRIS) return;
    if (m) { IRIS.react("happy"); say($("#hero-bubble"), `Hi${m.user.name ? " " + m.user.name.split(" ")[0] : ""}! I'll remember what we talk about now.`); }
    else { IRIS.react("wave"); say($("#hero-bubble"), "Hi, I'm Iris. I read every EPA response so you don't have to."); }  // never leave the last person's name up
  });
  if (location.hash === "#yours") setTimeout(() => $("#yours").scrollIntoView({ behavior: "smooth" }), 200);
}
main();
