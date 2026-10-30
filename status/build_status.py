#!/usr/bin/env python3
"""Build the team status page from GitHub itself. Standard library only.

A ticket is an issue titled "U-NN ...". Its status is worked out, never typed in:
  done         the issue is closed
  in review    an open pull request mentions it ("Closes #6", "Refs #3", "Part of #14")
  started      it carries the `started` label
  not started  none of the above
The judgment calls (blockers, the critical path, next steps) live in status/plan.json.

  GITHUB_TOKEN=... python status/build_status.py        writes site/index.html and site/status.json
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = os.environ.get("GITHUB_REPOSITORY", "aidaneichman/AC215_Undersigned")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("OUT_DIR", ROOT / "site"))
ET = ZoneInfo("America/New_York")
LANES = [("Livia", "collector, data, DVC"), ("Andrew", "processing"), ("Aadil", "grouping, evaluation"),
         ("Aidan", "rule retrieval, compose"), ("Rishi", "API, frontend"), ("Everyone", "")]
STATUS_NAME = {"d": "done", "r": "in review", "s": "started", "n": "not started"}


def api(path: str, params: dict | None = None):
    query = "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()) if params else ""
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}{query}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "undersigned-status")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def paged(path: str, params: dict, limit: int = 300) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 6):
        rows = api(path, {**params, "per_page": 100, "page": page}) or []
        out += rows
        if len(rows) < 100 or len(out) >= limit:
            break
    return out


def references(pr: dict, number: int) -> bool:
    text = f"{pr.get('title', '')} {pr.get('body') or ''}"
    text = re.sub(r"`[^`]*`", "", text)  # examples in code spans are not references
    return bool(re.search(rf"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|part of)\s+#{number}\b", text))


def ticket_status(issue: dict, open_prs: list[dict]) -> tuple[str, str]:
    """(status code, the PR number if it is in review)."""
    if issue["state"] == "closed":
        return "d", ""
    for pr in open_prs:
        if references(pr, issue["number"]):
            return "r", str(pr["number"])
    if "started" in {label["name"] for label in issue["labels"]}:
        return "s", ""
    return "n", ""


def when(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    return t.strftime("%a %-d %b, %-I:%M %p")


def dvc_pointers() -> list[tuple[str, int, int]]:
    rows = []
    for path in sorted((ROOT / "data" / "raw").glob("*.dvc")):
        text = path.read_text()
        size = re.search(r"size:\s*(\d+)", text)
        files = re.search(r"nfiles:\s*(\d+)", text)
        if size and files:
            rows.append((path.stem, int(files.group(1)), int(size.group(1))))
    return rows


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def collect(plan: dict) -> dict:
    issues = [i for i in paged("/issues", {"state": "all"}) if "pull_request" not in i]
    pulls = paged("/pulls", {"state": "all", "sort": "updated", "direction": "desc"}, limit=100)
    open_prs = [p for p in pulls if p["state"] == "open"]
    for pr in open_prs:
        detail = api(f"/pulls/{pr['number']}") or {}
        pr["reviews"] = api(f"/pulls/{pr['number']}/reviews") or []
        pr["requested"] = [r["login"] for r in detail.get("requested_reviewers", [])]
        pr["mergeable_state"] = detail.get("mergeable_state", "unknown")
    tickets = []
    for issue in issues:
        m = re.match(r"^(U-\d\d)\b", issue["title"])
        if not m:
            continue
        code, pr = ticket_status(issue, open_prs)
        owner = next((l["name"][6:].title() for l in issue["labels"] if l["name"].startswith("owner-")), "Everyone")
        short = plan["short"].get(m.group(1)) or issue["title"][5:27]
        note = f"PR #{pr}" if code == "r" else plan.get("notes", {}).get(m.group(1), "") if code in "s" else ""
        tickets.append({"id": m.group(1), "number": issue["number"], "title": issue["title"], "short": short,
                        "owner": owner, "status": code, "note": note, "url": issue["html_url"]})
    tickets.sort(key=lambda t: t["id"])
    commits = api("/commits", {"sha": "main", "per_page": 8}) or []
    runs = (api("/actions/workflows/ci.yml/runs", {"branch": "main", "per_page": 1}) or {}).get("workflow_runs", [])
    return {"tickets": tickets, "open_prs": open_prs, "commits": commits, "ci": runs[0] if runs else None,
            "merged": [p for p in pulls if p.get("merged_at")][:5]}


def chip(t: dict) -> str:
    sub = f"<small>{esc(t['note'])}</small>" if t["note"] else "<small></small>"
    return (f'<a class="chip {t["status"]}" href="{esc(t["url"])}"><b>{t["id"]}</b> {esc(t["short"])}{sub}</a>')


def lanes_html(tickets: list[dict]) -> str:
    out = ""
    for name, role in LANES:
        mine = [t for t in tickets if t["owner"] == name]
        if not mine:
            continue
        out += (f'<div class="lane"><div class="who"><b>{name}</b><small>{esc(role)}</small></div>'
                f'<div class="chips">{"".join(chip(t) for t in mine)}</div></div>')
    return out


def review_line(pr: dict) -> str:
    states = {}
    for r in pr["reviews"]:
        states[r["user"]["login"]] = r["state"]
    approved = [u for u, s in states.items() if s == "APPROVED"]
    changes = [u for u, s in states.items() if s == "CHANGES_REQUESTED"]
    if changes:
        return "changes requested by " + ", ".join(changes)
    if approved:
        return "approved by " + ", ".join(approved)
    if pr["requested"]:
        return "waiting on " + ", ".join(pr["requested"])
    return "no review yet"


def prs_html(data: dict) -> str:
    if not data["open_prs"]:
        return "<p class='quiet'>No open pull requests.</p>"
    rows = ""
    for pr in data["open_prs"]:
        clean = "ready to merge" if pr["mergeable_state"] == "clean" else pr["mergeable_state"].replace("_", " ")
        rows += (f'<li><a href="{esc(pr["html_url"])}"><b>#{pr["number"]}</b> {esc(pr["title"][:70])}</a>'
                 f'<br><span class="quiet">{esc(pr["user"]["login"])}, {esc(review_line(pr))}, {esc(clean)}</span></li>')
    return f"<ul class='plain'>{rows}</ul>"


def path_svg(plan: dict, tickets: list[dict]) -> str:
    by_number = {t["number"]: t for t in tickets}
    W, bw = 948, 182
    gap = (W - 120 - 4 * bw) / 3
    ink, acc = "#1b1b1b", "#1f4e79"
    s = f'<svg width="100%" viewBox="0 0 {W} {len(plan["path"]) * 60 + 2}" role="img" aria-label="Critical path">'
    for row, lane in enumerate(plan["path"]):
        y = 2 + row * 60
        s += f'<text x="2" y="{y + 27}" font-size="10" font-weight="700">{esc(lane["lane"])}</text>'
        for i, b in enumerate(lane["boxes"]):
            x = 120 + i * (bw + gap)
            code = by_number.get(b.get("ticket"), {}).get("status", "n")
            fill = {"d": ink, "r": acc, "s": "#d3dde9", "n": "#fff"}[code]
            col = "#fff" if code in "dr" else ink
            dash = ' stroke-dasharray="4 3"' if code == "n" else ""
            s += f'<rect x="{x}" y="{y}" width="{bw}" height="42" fill="{fill}" stroke="{ink}" stroke-width="1.1"{dash}/>'
            s += f'<text x="{x + 7}" y="{y + 15}" font-size="9.4" font-weight="700" fill="{col}">{esc(b["title"])}</text>'
            sub = b["sub"] + (f" ({STATUS_NAME[code]})" if b.get("ticket") else "")
            s += f'<text x="{x + 7}" y="{y + 28}" font-size="8.2" fill="{col}" opacity=".85">{esc(sub)}</text>'
            if i < 3:
                x2 = x + bw + gap - 1
                s += (f'<line x1="{x + bw + 3}" y1="{y + 21}" x2="{x2 - 6}" y2="{y + 21}" stroke="{ink}" stroke-width="1.2"/>'
                      f'<path d="M{x2 - 7},{y + 17.5} L{x2},{y + 21} L{x2 - 7},{y + 24.5} z" fill="{ink}"/>')
    return s + "</svg>"


CSS = """
:root{--ink:#1b1b1b;--sec:#5a5955;--rule:#cfcdc6;--acc:#1f4e79;--bg:#fff;--soft:#e4e2dc}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.4 "Helvetica Neue",Helvetica,Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:22px 24px 40px}
h1{font:600 26px Georgia,serif;margin:0}
.sub{color:var(--sec);font-size:14px;margin:4px 0 10px;max-width:980px}
h2{font:600 15px Georgia,serif;margin:16px 0 6px;border-bottom:1.5px solid var(--ink);padding-bottom:2px}
a{color:inherit;text-decoration:none}
.top{display:grid;grid-template-columns:1.75fr 1fr;gap:26px}
.lane{display:grid;grid-template-columns:92px 1fr;gap:8px;padding:5px 0;border-bottom:1px solid var(--soft);align-items:start}
.who b{font-size:13px;display:block}.who small{color:var(--sec);font-size:10.5px}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{border:1px solid var(--ink);padding:3px 8px;font-size:11.5px;min-width:104px;line-height:1.25}
.chip small{display:block;font-size:9.6px;opacity:.85;min-height:11px}
.chip.d{background:var(--ink);color:#fff}.chip.r{background:var(--acc);color:#fff;border-color:var(--acc)}
.chip.s{background:#d3dde9}.chip.n{background:#fff;border:1px dashed var(--sec);color:var(--sec)}
.chip:hover{outline:2px solid var(--acc)}
.legend{display:flex;gap:10px;margin-top:8px;font-size:11px;align-items:center;flex-wrap:wrap}.legend .chip{min-width:0;padding:1px 8px}
.bar{display:flex;height:18px;border:1px solid var(--ink);margin:6px 0}.bar div{display:flex;align-items:center;justify-content:center;font-size:10.5px;font-weight:700;color:#fff}
.block{border-left:3px solid var(--acc);padding:1px 0 1px 10px;margin:0 0 8px}.block b{display:block}
.facts{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:12px}.facts span{color:var(--sec)}
.quiet{color:var(--sec);font-size:11.5px}
ul.plain{margin:0;padding:0;list-style:none}ul.plain li{margin-bottom:7px}
.cols{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.cols>div{border-top:1.5px solid var(--ink);padding-top:4px}.cols b{display:block;font-size:12.5px}
.cols ul{margin:3px 0;padding-left:15px}.cols li{margin-bottom:2px}
.feed li{margin-bottom:3px}.feed{margin:0;padding-left:16px}
footer{margin-top:22px;color:var(--sec);font-size:11px;border-top:1px solid var(--rule);padding-top:8px}
@media (max-width:900px){.top{grid-template-columns:1fr}.cols{grid-template-columns:1fr 1fr}}
@media (max-width:560px){.cols{grid-template-columns:1fr}.lane{grid-template-columns:1fr}}
@media print{@page{size:letter landscape;margin:.4in}main{padding:0}meta{display:none}}
"""

JS = """
const due=new Date(document.body.dataset.due), built=new Date(document.body.dataset.built);
function tick(){
  const ms=due-new Date(), d=Math.floor(ms/864e5), h=Math.floor(ms%864e5/36e5);
  document.getElementById('left').textContent=ms>0?`${d} days ${h} hours left`:'past the deadline';
  const m=Math.round((new Date()-built)/6e4);
  document.getElementById('age').textContent=m<1?'just now':m<60?`${m} min ago`:`${Math.round(m/60)} h ago`;
}
tick();setInterval(tick,30000);
"""


def render(plan: dict, data: dict) -> str:
    tickets = data["tickets"]
    counts = {k: sum(1 for t in tickets if t["status"] == k) for k in "drsn"}
    total = len(tickets)
    now = datetime.now(timezone.utc)
    ci = data["ci"]
    if ci is None:
        ci_text = "no run yet"
    elif ci["status"] != "completed":
        ci_text = "running"
    else:
        ci_text = "passing" if ci["conclusion"] == "success" else ci["conclusion"] or "unknown"
    ci_link = f'<a href="{esc(ci["html_url"])}">{esc(ci_text)}</a>' if ci else esc(ci_text)
    last = data["commits"][0] if data["commits"] else None
    pointers = dvc_pointers()
    dvc = (f"{sum(f for _, f, _ in pointers):,} files, {sum(s for _, _, s in pointers) / 1e9:.1f} GB "
           f"in {len(pointers)} DVC folders") if pointers else "none yet"
    facts = "".join(f"<span>{esc(k)}</span><b>{esc(v)}</b>" for k, v in plan["facts"])
    blockers = "".join(f'<div class="block"><b>{i}. {esc(b["title"])}</b>{esc(b["text"])}</div>'
                       for i, b in enumerate(plan["blockers"], 1))
    nxt = "".join(f'<div><b>{esc(c["title"])}</b><ul>{"".join(f"<li>{esc(x)}</li>" for x in c["items"])}</ul></div>'
                  for c in plan["next"])
    feed = "".join(f'<li>{esc(c["commit"]["message"].splitlines()[0][:96])} '
                   f'<span class="quiet">{esc(c["commit"]["author"]["name"])}, {when(c["commit"]["author"]["date"])}</span></li>'
                   for c in data["commits"])
    bar = "".join(f'<div style="width:{100 * counts[k] / total:.1f}%;background:{c}">{counts[k] or ""}</div>'
                  for k, c in (("d", "#1b1b1b"), ("r", "#1f4e79"), ("s", "#7d97b3"), ("n", "#bdbbb4")) if total)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>{esc(plan['title'])}</title><style>{CSS}</style></head>
<body data-due="{esc(plan['due'])}" data-built="{now.isoformat()}"><main>
<h1>{esc(plan['title'])}</h1>
<div class="sub">{esc(plan['due_label'])}, <b id="left"></b>. {counts['d']} of {total} tickets done, {counts['r']} in review, {counts['s']} started, {counts['n']} not started.
Built from the repository {esc(when(now.isoformat()))} ET, updated <span id="age"></span>. It rebuilds on every push and every 15 minutes.</div>
<div class="bar" title="done, in review, started, not started">{bar}</div>
<div class="top"><div>
<h2>Who has what</h2>{lanes_html(tickets)}
<div class="legend"><span>Ticket status:</span><span class="chip d"><b>done</b></span><span class="chip r"><b>in review</b></span><span class="chip s"><b>started</b></span><span class="chip n"><b>not started</b></span></div>
</div><div>
<h2>Blocking the team right now</h2>{blockers}
<h2>Open pull requests</h2>{prs_html(data)}
<h2>Numbers</h2>
<div class="facts"><span>CI on main</span><b>{ci_link}</b><span>Data in the bucket</span><b>{dvc}</b>
<span>Last push to main</span><b>{esc(when(last['commit']['author']['date'])) if last else 'none'}</b>{facts}</div>
</div></div>
<h2>The critical path: each row waits on the box before it</h2>{path_svg(plan, tickets)}
<h2>Next steps</h2><div class="cols">{nxt}</div>
<h2>Recent activity on main</h2><ul class="feed">{feed}</ul>
<footer>Built from this repository's issues, pull requests, commits and CI runs by <code>status/build_status.py</code>.
A ticket is done when its issue is closed, in review when an open pull request mentions it, started when it has the
<code>started</code> label. Blockers, the critical path and next steps are edited by hand in <code>status/plan.json</code>.
<a href="status.json">status.json</a> has the same data for scripts.</footer>
</main><script>{JS}</script></body></html>"""


def main() -> None:
    plan = json.loads((Path(__file__).parent / "plan.json").read_text())
    data = collect(plan)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(render(plan, data), encoding="utf-8")
    summary = {
        "built": datetime.now(timezone.utc).isoformat(),
        "tickets": [{k: t[k] for k in ("id", "number", "owner", "status", "note")} for t in data["tickets"]],
        "open_prs": [{"number": p["number"], "title": p["title"], "review": review_line(p)} for p in data["open_prs"]],
        "ci": (data["ci"] or {}).get("conclusion"),
    }
    (OUT / "status.json").write_text(json.dumps(summary, indent=2))
    counts = {k: sum(1 for t in data["tickets"] if t["status"] == k) for k in "drsn"}
    print(f"wrote {OUT}/index.html: {len(data['tickets'])} tickets {counts}, {len(data['open_prs'])} open PRs")


if __name__ == "__main__":
    main()
