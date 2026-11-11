"""B3, the prompt baseline: what one well-written prompt per section produces from the same passages.

The question it answers: does the harness (claim extraction, quote check, pair judging, union-find)
beat simply handing the model every cited passage of a section and asking for the brief? Same input
as the pipeline (inputs.select, cited passages only), same model, same rule context. One call per
section; the model does the grouping itself, in context.

Writes eval/out/baselines/B3/issues.parquet in the pipeline's issues shape, so match.py and score.py
treat it like B0 to B2, plus quotes.parquet and checks.json: how many of its quotes are verbatim in
the passage it names, and whether the passage belongs to the letter it names. Nothing in the prompt
or the scoring sees the final rule.

Usage: GRAPH_MAX_USD=8 python eval/prompt_baseline.py [--data-dir ../data] [--docket EPA-HQ-OW-2022-0801]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import inputs  # noqa: E402
from config import Config, short_ref  # noqa: E402
from issues import ISSUE_COLUMNS  # noqa: E402
from llm import LLM, BudgetExceeded  # noqa: E402
from quotes import verified  # noqa: E402

SYSTEM = (HERE.parent / "prompts" / "system.md").read_text().strip()
STANCES = ["support", "oppose", "modify", "clarify", "other"]
SCHEMA = {
    "type": "object",
    "required": ["issues"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["ask", "stance", "supporters"],
                "properties": {
                    "ask": {"type": "string"},
                    "stance": {"type": "string", "enum": STANCES},
                    "evidence_type": {"type": "array", "items": {"type": "string"}},
                    "supporters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["passage_id", "quote"],
                            "properties": {
                                "passage_id": {"type": "string"},
                                "letter_id": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}
PROMPT = """You are briefing the EPA staff who must write the response to comments for {section} ({heading}).

Rule text, opening of the section:
{context}

Below are every comment passage that cites this section. Each starts with [passage_id | letter_id].

Write the brief: list every distinct argument or request commenters make about this section. Merge
passages that make the same request into one item, even when they word it differently; keep requests
that differ in substance apart. For each item give:
- ask: one sentence stating what commenters want EPA to do
- stance: support (keep as proposed), oppose, modify, clarify, or other
- evidence_type: any of data, legal, alternative, cost, feasibility, experience
- supporters: one entry per passage that makes this request, with its passage_id, letter_id, and a
  quote copied character for character from that passage

Cover every passage that makes a request. A passage can support more than one item.

Passages:
{passages}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(HERE.parent.parent / "data"))
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801")
    ap.add_argument("--out", default=str(HERE / "out" / "baselines" / "B3"))
    args = ap.parse_args()
    data_dir, out = Path(args.data_dir), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cfg = Config.from_env()
    data = inputs.load(args.docket, data_dir)
    chunks, _ = inputs.rule_chunks(args.docket, data_dir)
    ctx = inputs.rule_context(chunks)
    sel = inputs.select(data, cfg, section_order=list(ctx))
    llm = LLM(cfg, out)

    by_section: dict[str, list] = {}
    for r in sel.itertuples():
        for ref in r.candidates:  # a passage citing two sections is shown under both, as in B0
            by_section.setdefault(ref, []).append(r)
    text_of = dict(zip(sel["passage_id"], sel["text"], strict=True))
    letter_of = dict(zip(sel["passage_id"], sel["letter_id"], strict=True))

    rows, quotes, failed = [], [], []
    for ref, ps in sorted(by_section.items(), key=lambda kv: -len(kv[1])):
        c = ctx.get(ref, {})
        user = PROMPT.format(
            section=short_ref(ref), heading=c.get("heading", ""),
            context=c.get("context") or "(not available)",
            passages="\n\n".join(f"[{p.passage_id} | {p.letter_id}]\n{p.text}" for p in ps),
        )  # fmt: skip
        tag = "b3_" + short_ref(ref).replace("§ ", "").replace(" ", "_")
        try:
            res = llm.call(tag, "prompt_baseline", SYSTEM, "", user, SCHEMA)
        except BudgetExceeded as e:
            print(f"B3: stopped at {ref}: {e}", file=sys.stderr)
            failed.append(ref)
            break
        except Exception as e:  # noqa: BLE001 - one section failing is recorded, not fatal
            print(f"B3: {ref} failed: {e}", file=sys.stderr)
            failed.append(ref)
            continue
        for k, it in enumerate(res.get("issues", [])):
            iid = f"B3-{tag[3:]}-{k:03d}"
            letters = set()
            for s in it.get("supporters", []):
                pid = s.get("passage_id", "")
                in_sel = pid in text_of
                ok = in_sel and verified(s.get("quote"), text_of[pid])
                right_letter = in_sel and (not s.get("letter_id") or s["letter_id"] == letter_of[pid])
                quotes.append({"issue_id": iid, "section_ref": ref, "passage_id": pid,
                               "letter_id": letter_of.get(pid, s.get("letter_id")),
                               "quote": s.get("quote"), "passage_known": in_sel,
                               "quote_verified": ok, "letter_matches": right_letter})  # fmt: skip
                if in_sel:
                    letters.add(letter_of[pid])
            st = it.get("stance", "other")
            rows.append({
                "issue_id": iid, "docket_id": args.docket, "section_ref": ref, "label": it["ask"],
                "label_claim_id": None, "n_claims": len(it.get("supporters", [])),
                "n_letters": len(letters), "n_campaigns": 0, "n_letters_incl_copies": len(letters),
                "stances": json.dumps({st: 1}), "significant": False, "significance_from": [],
                "contested_merge": False, "giant_issue": False,
            })  # fmt: skip

    issues = pd.DataFrame(rows, columns=ISSUE_COLUMNS)
    q = pd.DataFrame(quotes)
    issues.to_parquet(out / "issues.parquet", index=False)
    q.to_parquet(out / "quotes.parquet", index=False)
    covered = set(q.loc[q["passage_known"], "passage_id"]) if len(q) else set()
    checks = {
        "sections": len(by_section), "sections_failed": failed, "issues": len(issues),
        "quotes": len(q),
        "quotes_verified": int(q["quote_verified"].sum()) if len(q) else 0,
        "quotes_unknown_passage": int((~q["passage_known"]).sum()) if len(q) else 0,
        "quotes_wrong_letter": int((q["passage_known"] & ~q["letter_matches"]).sum()) if len(q) else 0,
        "passages_in": len(sel), "passages_cited_by_brief": len(covered),
        "issues_multi_letter": int((issues["n_letters"] >= 2).sum()),
        "usd": round(sum(r.get("usd") or 0 for r in llm.rows()), 4),
        "calls": len(llm.rows()),
    }  # fmt: skip
    (out / "checks.json").write_text(json.dumps(checks, indent=1))
    print(json.dumps(checks, indent=1))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
