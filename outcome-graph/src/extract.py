"""Split each EPA response topic into the asks commenters made and what EPA decided on each.

EPA's summary response for a topic follows a fixed pattern: "Some commenters recommended X. The EPA
does not agree ..." or "... The EPA has adopted Y in the final rule." One model call per topic turns
that text into rows. Every row carries a quote from EPA's own text, and code checks the quote word for
word against the summary, so a verdict can always be traced to the sentence it came from.

Calls go through `claude -p` (the laptop's Claude Code login, as argument-graph's CliBackend does).
Results are cached per topic in raw/<code>.json, so a rerun only calls the model for missing topics.

    uv run python src/extract.py --docket EPA-HQ-OW-2022-0801 --budget 25
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VERDICTS = ("adopted", "partly_adopted", "declined", "clarified", "already_required")

SYSTEM = """You read one topic of an agency's response-to-comments document and record, as data, \
each distinct thing commenters asked for and what the agency decided.

Rules:
- One row per distinct ask. An ask is a concrete change commenters wanted, or a position they took \
on the proposal ("keep the 10-year deadline", "remove the trigger level"). Merge restatements.
- verdict is one of:
  adopted           the agency did what was asked in the final rule
  partly_adopted    the agency moved toward the ask but not all the way
  declined          the agency kept its approach or refused
  clarified         no rule change; the agency explained, or promised guidance
  already_required  the agency says the proposal or the law already does this
- quote: one or two sentences copied EXACTLY, character for character, from the agency text, \
that show the verdict. No ellipses, no paraphrase. Under 60 words.
- final_rule_change: one short sentence on what changed in the final rule because of this ask, \
or null if nothing changed.
- sections: CFR sections the agency text ties to this ask, like "141.84". Empty list if none named.
- who: the commenter group if the text names one ("States", "water systems", "public health \
groups"), else null.
- ask: under 20 words, plain English, starts with a verb or "Keep"/"Remove"/"Require".
- Cover every ask in the text. Typical topics have 2 to 10.

Reply with JSON only: {"asks": [{"ask": ..., "who": ..., "verdict": ..., "quote": ..., \
"final_rule_change": ..., "sections": [...]}]}"""


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("­", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_ok(quote: str, text: str) -> bool:
    q = norm(quote).rstrip(".")
    return len(q) > 15 and q in norm(text)


def call(prompt: str, model: str, workdir: Path) -> tuple[str, float]:
    cmd = [
        "claude", "-p", "--model", model, "--output-format", "json",
        "--system-prompt", SYSTEM, "--tools", "", "--setting-sources", "",
        "--strict-mcp-config", "--no-session-persistence",
    ]  # fmt: skip
    r = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, cwd=workdir, timeout=900, check=False
    )
    out = json.loads(r.stdout)
    if out.get("is_error"):
        raise RuntimeError(str(out)[:500])
    return out["result"], float(out.get("total_cost_usd") or 0)


def parse(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(m.group(0))
    return data["asks"]


AGENCY_MARK = "AGENCY RESPONSE:"


def agency_part(text: str) -> str:
    """Where the document mixes a comment summary with the agency's answer (LCRR), only the
    answer parts. Quotes are checked against this, so a commenter's words never pass as a verdict."""
    if AGENCY_MARK not in text:
        return text
    return " ".join(chunk.split("COMMENTS (EPA's summary):")[0] for chunk in text.split(AGENCY_MARK)[1:])


def one_topic(row: dict, model: str, workdir: Path) -> dict:
    note = ""
    if AGENCY_MARK in row["summary_response"]:
        note = ("\nThe text has EPA's summary of the comments, then parts marked AGENCY RESPONSE. "
                "Take the asks from the comment summary. Copy every quote from an AGENCY RESPONSE "
                "part only.\n")  # fmt: skip
    prompt = (
        f"Topic {row['code']}: {row['title'] or '(untitled)'}\n{note}\nAgency text:\n\n"
        f"{row['summary_response']}"
    )
    check = agency_part(row["summary_response"])
    text, usd = call(prompt, model, workdir)
    asks = parse(text)
    bad = [a for a in asks if not quote_ok(a.get("quote", ""), check)]
    if bad:  # one retry, naming the quotes that were not exact
        fix = "\n".join(f"- {a.get('quote', '')}" for a in bad)
        text2, usd2 = call(
            prompt + "\n\nYour previous answer had quotes that are not exact copies of the "
            f"agency text:\n{fix}\nAnswer again with exact quotes.\n\nPrevious answer:\n{text}",
            model,
            workdir,
        )
        usd += usd2
        asks = parse(text2)
    for a in asks:
        a["quote_verified"] = quote_ok(a.get("quote", ""), check)
        if a.get("verdict") not in VERDICTS:
            a["verdict"] = "clarified"
    return {"code": row["code"], "title": row["title"], "asks": asks, "usd": usd, "model": model}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--budget", type=float, default=25.0, help="stop starting new calls past this")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", nargs="*", help="topic codes to run (default all)")
    args = ap.parse_args()

    codes = pd.read_parquet(ROOT / f"data/derived/responses/{args.docket}/codes.parquet")
    entries = pd.read_parquet(ROOT / f"data/derived/responses/{args.docket}/entries.parquet")
    # A topic with no summary (PFAS's section-by-section topics) is read from EPA's individual
    # replies in it, each distinct reply once, capped so one topic stays one call.
    for i, r in codes.iterrows():
        if len(r["summary_response"] or "") < 300 and len(entries):
            replies = list(dict.fromkeys(entries.loc[entries["code"] == r["code"], "response"].dropna()))
            if replies:
                codes.at[i, "summary_response"] = "EPA's replies to individual comments:\n\n" + "\n\n".join(replies)[:40000]
    codes = codes[codes["summary_response"].fillna("").str.len() >= 300]
    out_dir = ROOT / f"data/derived/outcomes/{args.docket}"
    raw = out_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="outcome-graph-"))

    rows = [r for r in codes.to_dict("records") if not args.only or r["code"] in args.only]
    todo = [r for r in rows if not (raw / f"{r['code']}.json").exists()]
    spent = sum(json.loads(p.read_text())["usd"] for p in raw.glob("*.json"))
    print(f"{len(rows)} topics, {len(todo)} to run, ${spent:.2f} already spent", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        futs = {}
        it = iter(todo)
        for r in it:
            futs[pool.submit(one_topic, r, args.model, workdir)] = r
            if len(futs) >= args.workers:
                break
        while futs:
            for f in as_completed(list(futs)):
                r = futs.pop(f)
                try:
                    res = f.result()
                    (raw / f"{r['code']}.json").write_text(json.dumps(res, indent=1))
                    spent += res["usd"]
                    ok = sum(a["quote_verified"] for a in res["asks"])
                    print(
                        f"{r['code']:>8}  {len(res['asks'])} asks, {ok} quotes exact, "
                        f"${res['usd']:.2f}  total ${spent:.2f}",
                        flush=True,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"{r['code']:>8}  FAILED {e}", file=sys.stderr, flush=True)
                if spent < args.budget:
                    nxt = next(it, None)
                    if nxt:
                        futs[pool.submit(one_topic, nxt, args.model, workdir)] = nxt
                break
    print(f"done, ${spent:.2f}", flush=True)


if __name__ == "__main__":
    main()
