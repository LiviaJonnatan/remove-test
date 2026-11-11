// Use Oversight from your own Claude: the public MCP server at /mcp.
import "./pages.css";
import "./account.css";
import { initAuth, accountWidget } from "./auth.js";
import { esc, pct, siteHeader, initShared, track } from "./shared.js";

const $ = (s) => document.querySelector(s);
const URL_ = `${location.origin}/mcp/`;
const TOOLS = [
  ["list_rules", "The rules with a full record, with how EPA ruled on the asks."],
  ["find", "Organizations, topics and asks across every rule."],
  ["list_asks", "Asks in a rule, by verdict, by who argued, or only those that changed the rule."],
  ["get_ask", "EPA's verbatim answer, the page, the surrounding paragraph, and everyone for and against."],
  ["organization", "An organization's record across rules: every position and whether it won."],
  ["similar_asks", "Past asks closest to a point you want to make, with EPA's answers."],
  ["scoreboard", "Which stakeholder groups got their way on a rule."],
];
const PROMPTS = [
  "How did the American Water Works Association do on the PFAS rule?",
  "Which asks from utilities changed the final lead rule? Cite pages.",
  "I want to argue for a longer compliance deadline. What did EPA say when others tried?",
  "Compare advocacy groups and trade groups on PFAS.",
];
const copyBox = (id, text) => `<div class="copybox"><code id="${id}">${esc(text)}</code><button type="button" class="btn" data-copy="${id}">Copy</button></div>`;

async function demo() {
  const body = $("#term");
  const o = await fetch("/api/org/american-water-works-association").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!o) { body.textContent = ""; return; }
  const pf = o.rule_list.find((r) => r.short === "PFAS") || o.rule_list[0];
  const won = pf.asks.filter((a) => a.outcome === "won").slice(0, 2);
  const lines = [
    ["you", `> ${PROMPTS[0]}`],
    ["tool", `  ⏺ oversight · organization("AWWA")`],
    ["ok", `  ⎿ ${o.name}: ${pf.asks.length} asks on ${pf.short}`],
    ["", ""],
    ["", `On ${pf.short}, AWWA took a side on ${pf.asks.length} asks. EPA went their way on ${pf.record.won}, partly on ${pf.record.partly}, and against them on ${pf.record.lost}.`],
    ...won.map((a) => ["", `  • ${a.label}${a.page ? ` (EPA response, p. ${a.page})` : ""}`]),
    ["", `Across rules: ${pct(o.share)} of ${o.decided} decided asks went their way.`],
  ];
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { body.innerHTML = lines.map(([c, t]) => `<span class="${c}">${esc(t)}</span>`).join("\n"); return; }
  body.innerHTML = "";
  for (const [cls, text] of lines) {
    const span = document.createElement("span");
    span.className = cls;
    body.appendChild(span);
    const caret = Object.assign(document.createElement("span"), { className: "caret" });
    body.appendChild(caret);
    const speed = cls === "you" ? 22 : cls === "" ? 6 : 12;
    for (let i = 0; i <= text.length; i += cls === "" ? 3 : 1) { span.textContent = text.slice(0, i); await new Promise((r) => setTimeout(r, speed)); }
    span.textContent = text;
    caret.remove();
    body.appendChild(document.createTextNode("\n"));
    await new Promise((r) => setTimeout(r, cls === "tool" ? 650 : 160));
  }
  body.appendChild(Object.assign(document.createElement("span"), { className: "caret" }));
}

async function main() {
  siteHeader($("#top"), { active: "connect" });
  await initAuth();
  accountWidget($("#account"));
  initShared("connect");
  const desktop = JSON.stringify({ mcpServers: { oversight: { command: "npx", args: ["-y", "mcp-remote", URL_] } } }, null, 2);
  $("#main").innerHTML = `
    <div style="margin-top:18px"><div class="eyebrow">Use in Claude</div>
      <h1 class="big">Ask your own Claude what happened to every comment</h1>
      <p class="lede">Oversight runs a public MCP server. Connect it once and Claude can look up any ask, EPA's answer with its page, and any organization's record, inside your own chats and documents. Free, read-only, no account.</p></div>
    <div class="term"><div class="term-top"><i></i><i></i><i></i></div><div class="term-body" id="term"></div></div>
    <div class="sec"><div class="sec-head"><h2>Connect it</h2><span class="sub">Server address</span></div>${copyBox("u", URL_)}</div>
    <div class="conn">
      <div class="card"><h3>Claude.ai and the Claude apps</h3><p>On plans that allow custom connectors.</p><ol><li>Settings, then Connectors</li><li>Add custom connector</li><li>Name it Oversight and paste the address above</li></ol></div>
      <div class="card"><h3>Claude Code</h3><p>One command in your terminal.</p>${copyBox("cc", `claude mcp add --transport http oversight ${URL_}`)}</div>
      <div class="card"><h3>Claude Desktop (config file)</h3><p>For older versions without custom connectors.</p>${copyBox("cd", desktop)}</div>
    </div>
    <div class="sec"><div class="sec-head"><h2>Try asking</h2><span class="sub">Click to copy</span></div>
      <div class="prompts">${PROMPTS.map((p, i) => `<button type="button" class="chip" data-p="${i}">${esc(p)}</button>`).join("")}</div></div>
    <div class="sec"><div class="sec-head"><h2>Tools</h2><span class="sub">${TOOLS.length} read-only tools, no model calls on our side</span></div>
      <div class="tools">${TOOLS.map(([n, d]) => `<div class="card"><code>${n}</code><p>${esc(d)}</p></div>`).join("")}</div></div>`;
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
    navigator.clipboard?.writeText($("#" + b.dataset.copy).textContent).then(() => { b.textContent = "Copied"; track("connect:copy", { what: b.dataset.copy }); setTimeout(() => (b.textContent = "Copy"), 1500); });
  }));
  document.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => {
    navigator.clipboard?.writeText(PROMPTS[+b.dataset.p]).then(() => { const t = b.textContent; b.textContent = "Copied"; setTimeout(() => (b.textContent = t), 1200); });
  }));
  new IntersectionObserver((es, io) => es.forEach((e) => { if (e.isIntersecting) { io.disconnect(); demo(); } })).observe($("#term"));
}
main();
