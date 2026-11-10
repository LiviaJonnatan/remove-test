"""Does an LLM pick EPA's answer better than the ranker, given the same candidates?

For held-out excerpts from match.py, the model sees the comment and the ranker's top 20 codes,
each as its title and best 150-word window, in an order shuffled by a hash so position says nothing
about the ranker's opinion. It returns up to 5 candidate ids, best first, or none. Scored on the
same EPA answer codes as match.py. The model can only find answers the top 20 contain, so the share
of excerpts whose answer is in the top 20 is reported alongside.

Calls go through `claude -p` (argument-graph's CliBackend), which reports each call's cost. The run
stops when the total reaches --budget.

Run from the repo root:
    PYTHONPATH=argument-graph/src uv run --project response-index python \
        response-index/eval/llm_rerank.py --model opus --n 200 --budget 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from backends import CliBackend

DOCKET = "EPA-HQ-OW-2022-0801"
MAX_EXCERPT_WORDS = 600

SYSTEM = (
    "You match public comments on an EPA rule to the part of EPA's Response to Comments document "
    "that answers them. Reply with JSON only."
)
PROMPT = """A commenter wrote the passage below about EPA's Lead and Copper Rule Improvements.
EPA's Response to Comments document groups its answers under topic codes. Below are {n} candidate
topics, each with the passage of EPA's summary response that best matches the comment.

Which topics' responses answer this comment? Rank up to 5 candidate ids, best first. If none of
them answers it, return an empty list.

Reply with only this JSON: {{"ranking": ["C7", "C2"]}}

Comment:
{comment}

Candidates:
{candidates}
"""


def shuffled(key: str, n: int) -> list[int]:
    return sorted(range(n), key=lambda i: hashlib.sha1(f"{key}:{i}".encode()).hexdigest())


def sample(preds: pd.DataFrame, n: int) -> pd.DataFrame:
    test = preds[preds["test"]].copy()
    test["h"] = [hashlib.sha1(e[0].encode()).hexdigest() for e in test["entry_ids"]]
    return test.sort_values("h").head(n).reset_index(drop=True)


def prompt_for(row) -> tuple[str, list[str]]:
    words = row.excerpt.split()
    comment = " ".join(words[:MAX_EXCERPT_WORDS]) + (
        " [...]" if len(words) > MAX_EXCERPT_WORDS else ""
    )
    order = shuffled(row.entry_ids[0], len(row.top20_codes))
    ids, blocks = [], []
    for k, i in enumerate(order, start=1):
        ids.append(row.top20_codes[i])
        blocks.append(f"[C{k}]\n{row.top20_windows[i]}")
    return PROMPT.format(n=len(ids), comment=comment, candidates="\n\n".join(blocks)), ids


def parse(text: str, ids: list[str]) -> list[str] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        ranking = json.loads(m.group(0)).get("ranking")
    except json.JSONDecodeError:
        return None
    out = []
    for c in ranking or []:
        k = int(c[1:]) if isinstance(c, str) and c[1:].isdigit() else 0
        if 1 <= k <= len(ids) and ids[k - 1] not in out:
            out.append(ids[k - 1])
    return out[:5]


def hit(ranked: list[str], answer: list[str], k: int) -> bool:
    return bool(set(ranked[:k]) & set(answer))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--model", default="opus")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--budget", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    match_dir = args.data_dir / "derived" / "responses" / DOCKET / "match"
    rows = sample(pd.read_parquet(match_dir / "predictions.parquet"), args.n)
    out_path = match_dir / f"llm_rerank_{args.model}.jsonl"
    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            r = json.loads(line)
            done[r["entry_id"]] = r
    backend = CliBackend(model=args.model)
    spent = sum(r.get("usd") or 0 for r in done.values())

    def call(row):
        user, ids = prompt_for(row)
        res = backend.complete("rerank", SYSTEM, "", user, {}, None)
        return row, ids, res

    todo = [r for r in rows.itertuples() if r.entry_ids[0] not in done]
    with out_path.open("a") as f, ThreadPoolExecutor(args.workers) as pool:
        pending = set()
        it = iter(todo)
        for _ in range(args.workers):
            row = next(it, None)
            if row is not None:
                pending.add(pool.submit(call, row))
        while pending:
            fut = next(as_completed(pending))
            pending.remove(fut)
            row, ids, res = fut.result()
            spent += res.usd or 0
            rec = {
                "entry_id": row.entry_ids[0],
                "model": res.model,
                "ranking": parse(res.text, ids) if not res.error else None,
                "error": res.error,
                "usd": res.usd,
                "usage": res.usage,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[rec["entry_id"]] = rec
            print(f"{len(done)}/{len(rows)} ${spent:.2f}", file=sys.stderr)
            if spent < args.budget:
                row = next(it, None)
                if row is not None:
                    pending.add(pool.submit(call, row))
            elif not pending:
                print(f"budget ${args.budget} reached", file=sys.stderr)

    scored = [(r, done[r.entry_ids[0]]) for r in rows.itertuples() if r.entry_ids[0] in done]
    ok = [(r, d) for r, d in scored if d["ranking"] is not None]
    n = len(ok)
    report = {
        "model": next((d["model"] for _, d in ok if d["model"]), args.model),
        "excerpts": n,
        "failed": len(scored) - n,
        "usd": round(spent, 2),
        "answer_in_ranker_top20": round(
            sum(hit(r.top20_codes, r.answer_codes, 20) for r, _ in ok) / n, 4
        ),
        "llm_returned_none": round(sum(not d["ranking"] for _, d in ok) / n, 4),
    }
    for k in (1, 5):
        report[f"ranker_hit@{k}"] = round(
            sum(hit(r.top20_codes, r.answer_codes, k) for r, _ in ok) / n, 4
        )
        report[f"llm_hit@{k}"] = round(
            sum(hit(d["ranking"], r.answer_codes, k) for r, d in ok) / n, 4
        )
    (match_dir / f"llm_rerank_{args.model}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
