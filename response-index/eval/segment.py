"""Can a letter be cut into the points EPA answered? Scored on EPA's own excerpts.

EPA quotes each commenter in excerpts, and response-index located 7,358 of them in our letters as
character spans. Those spans are the answer key: a method cuts a letter into segments, and an EPA
excerpt counts as found when one segment overlaps it with intersection over union of at least 0.5.
Segment precision is the same test the other way round.

Our letter text has whitespace flattened, so there are no paragraphs to split on. Methods:

- sentence: every sentence is a segment
- block: consecutive sentences packed to about 82 words, EPA's median excerpt length
- llm: the model sees the letter's numbered sentences and returns sentence ranges, one per point

Letters: held-out groups from match.py's split, 150 to 6,000 words, with at least 90% of their EPA
entries located, sampled by a hash of the letter id. Calls go through `claude -p` and stop at
--budget.

Run from the repo root:
    PYTHONPATH=argument-graph/src:response-index/eval uv run --project response-index --group eval \
        python response-index/eval/segment.py --model opus --n 60 --budget 10
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
from match import DOCKET, is_test

SENTENCE_END = re.compile(r"(?<=[.!?;:])[\"'”’)\]]*\s+(?=[\"'“‘(\[]*[A-Z0-9•●▪\-–])")
BLOCK_WORDS = 82
IOU = 0.5

SYSTEM = (
    "You prepare public comments for an agency's response-to-comments document. Reply with JSON "
    "only."
)
PROMPT = """Below is a public comment letter on EPA's proposed Lead and Copper Rule Improvements,
split into numbered sentences.

Cut it into the separate comments an agency would quote and answer one at a time in its response to
comments. Each comment is a contiguous range of sentences that makes one point: a request, an
objection, support, or information on one issue. Leave out greetings, sign-offs and contact details.

Reply with only this JSON, ranges inclusive: {{"segments": [[1, 4], [5, 9]]}}

Letter:
{sentences}
"""


def sentences(text: str) -> list[tuple[int, int]]:
    """Character spans of the sentences in a letter."""
    spans, start = [], 0
    for m in SENTENCE_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def blocks(text: str, sents: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, cur, words = [], None, 0
    for s, e in sents:
        cur = (cur[0], e) if cur else (s, e)
        words += len(text[s:e].split())
        if words >= BLOCK_WORDS:
            out.append(cur)
            cur, words = None, 0
    if cur:
        out.append(cur)
    return out


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def score(pred: list[tuple[int, int]], gold: list[tuple[int, int]]) -> dict:
    found = sum(any(iou(g, p) >= IOU for p in pred) for g in gold)
    precise = sum(any(iou(p, g) >= IOU for g in gold) for p in pred)
    return {"gold": len(gold), "pred": len(pred), "found": found, "precise": precise}


def gold_spans(entries: pd.DataFrame) -> list[tuple[int, int]]:
    """EPA's excerpts in one letter, an excerpt filed under several codes counted once."""
    spans = sorted({(int(s), int(e)) for s, e in zip(entries["span_start"], entries["span_end"], strict=True)})
    out: list[tuple[int, int]] = []
    for sp in spans:
        if out and iou(out[-1], sp) >= 0.9:
            continue
        out.append(sp)
    return out


def sample(data_dir: Path, n: int) -> list[dict]:
    resp = data_dir / "derived" / "responses" / DOCKET
    entries = pd.read_parquet(resp / "entries.parquet")
    letters = pd.read_parquet(
        data_dir / "derived" / "letters" / DOCKET / "letters.parquet",
        columns=["letter_id", "record_id", "text"],
    )
    assign = pd.read_parquet(data_dir / "derived" / "campaigns" / DOCKET / "assignments.parquet")
    campaign = dict(zip(assign["letter_id"], assign["campaign_id"], strict=True))
    rows = []
    for lt in letters.itertuples():
        g = entries[entries["record_id"] == lt.record_id]
        if g.empty:
            continue
        words = len(lt.text.split())
        located = g["letter_id"].eq(lt.letter_id) & g["span_start"].notna()
        group = campaign.get(lt.letter_id)
        group = group if isinstance(group, str) else lt.record_id
        if not (150 <= words <= 6000) or located.mean() < 0.9 or not is_test(group):
            continue
        rows.append(
            {
                "letter_id": lt.letter_id,
                "text": lt.text,
                "words": words,
                "gold": gold_spans(g[located]),
                "h": hashlib.sha1(lt.letter_id.encode()).hexdigest(),
            }
        )
    return sorted(rows, key=lambda r: r["h"])[:n]


def parse(text: str, n_sents: int) -> list[tuple[int, int]] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        segs = json.loads(m.group(0)).get("segments")
    except json.JSONDecodeError:
        return None
    out = []
    for seg in segs or []:
        if isinstance(seg, list) and len(seg) == 2 and all(isinstance(x, int) for x in seg):
            a, b = max(1, seg[0]), min(n_sents, seg[1])
            if a <= b:
                out.append((a - 1, b - 1))
    return out


def totals(scores: list[dict]) -> dict:
    g = sum(s["gold"] for s in scores)
    p = sum(s["pred"] for s in scores)
    recall = sum(s["found"] for s in scores) / g if g else 0.0
    precision = sum(s["precise"] for s in scores) / p if p else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "letters": len(scores),
        "epa_excerpts": g,
        "segments": p,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--model", default="opus")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--budget", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    letters = sample(args.data_dir, args.n)
    out_dir = args.data_dir / "derived" / "responses" / DOCKET / "match"
    out_path = out_dir / f"segment_{args.model}.jsonl"
    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            r = json.loads(line)
            done[r["letter_id"]] = r
    spent = sum(r.get("usd") or 0 for r in done.values())
    backend = CliBackend(model=args.model)
    sents_of = {r["letter_id"]: sentences(r["text"]) for r in letters}

    def call(r):
        sents = sents_of[r["letter_id"]]
        numbered = "\n".join(
            f"[{i}] {' '.join(r['text'][s:e].split())}" for i, (s, e) in enumerate(sents, 1)
        )
        return r, backend.complete("segment", SYSTEM, "", PROMPT.format(sentences=numbered), {}, None)

    todo = iter([r for r in letters if r["letter_id"] not in done])
    with out_path.open("a") as f, ThreadPoolExecutor(args.workers) as pool:
        pending = {pool.submit(call, r) for r in [next(todo, None) for _ in range(args.workers)] if r}
        while pending:
            fut = next(as_completed(pending))
            pending.remove(fut)
            r, res = fut.result()
            spent += res.usd or 0
            rec = {
                "letter_id": r["letter_id"],
                "model": res.model,
                "segments": parse(res.text, len(sents_of[r["letter_id"]])) if not res.error else None,
                "error": res.error,
                "usd": res.usd,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[r["letter_id"]] = rec
            print(f"{len(done)}/{len(letters)} ${spent:.2f}", file=sys.stderr)
            nxt = next(todo, None) if spent < args.budget else None
            if nxt:
                pending.add(pool.submit(call, nxt))

    scored = [r for r in letters if done.get(r["letter_id"], {}).get("segments") is not None]
    results = {"sentence": [], "block": [], "llm": []}
    for r in scored:
        sents = sents_of[r["letter_id"]]
        llm = [(sents[a][0], sents[b][1]) for a, b in done[r["letter_id"]]["segments"]]
        results["sentence"].append(score(sents, r["gold"]))
        results["block"].append(score(blocks(r["text"], sents), r["gold"]))
        results["llm"].append(score(llm, r["gold"]))
    report = {
        "model": next((done[r["letter_id"]]["model"] for r in scored), args.model),
        "usd": round(spent, 2),
        "median_words": float(pd.Series([r["words"] for r in scored]).median()),
        "iou_threshold": IOU,
        "block_words": BLOCK_WORDS,
        **{m: totals(s) for m, s in results.items()},
    }
    (out_dir / f"segment_{args.model}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
