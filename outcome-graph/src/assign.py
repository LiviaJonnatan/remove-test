"""Tie each comment excerpt EPA quoted to the ask it makes, and which side it takes.

Text similarity finds the right topic but often the wrong ask, and it cannot tell support from
opposition ("move the compliance date earlier" sits closest to "keep the date at three years").
So a model reads each excerpt next to its topic's asks and answers: which ask, for or against.
Batches of 40 excerpts from one topic per call, cached in assign/<code>_<batch>.json.

    uv run python src/assign.py --budget 15
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
BATCH = 40

SYSTEM = """You match public comments to the asks an agency recorded for one topic.

You get a numbered list of asks (what commenters wanted, as the agency summarized it) and a \
numbered list of comment excerpts. For each excerpt, give the ONE ask it most directly takes a \
side on, and the side:
  "for"      the excerpt wants what the ask says
  "against"  the excerpt wants the opposite (e.g. ask "Keep the 10-year deadline", excerpt \
wants a 5-year deadline, or wants more time)
Use null for the ask when the excerpt takes no side on any listed ask (background, praise, a \
question, a different point). Be strict: a shared subject is not enough, the excerpt must argue \
the ask's point or its opposite.

Reply with JSON only: {"m": [[excerpt_number, ask_number_or_null, "for"|"against"|null], ...]} \
with one row per excerpt, in order."""


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


def one_batch(job: dict, model: str, workdir: Path) -> dict:
    asks = "\n".join(f"A{i}. {a['ask']}" for i, a in enumerate(job["asks"]))
    ex = "\n\n".join(
        f"E{i}. [{r['organization']}] {r['excerpt'][:900]}" for i, r in enumerate(job["rows"])
    )
    prompt = f"Topic {job['code']}: {job['title']}\n\nAsks:\n{asks}\n\nExcerpts:\n\n{ex}"
    text, usd = call(prompt, model, workdir)
    m = json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0))["m"]
    out = []
    for row in m:
        i, a, side = (row + [None, None])[:3]
        i = int(str(i).lstrip("E"))
        a = None if a is None else int(str(a).lstrip("A"))
        if i >= len(job["rows"]) or (a is not None and a >= len(job["asks"])):
            continue
        out.append({
            "entry_id": job["rows"][i]["entry_id"],
            "ask": None if a is None else f"ask:{job['code']}:{a}",
            "side": side if a is not None and side in ("for", "against") else None,
        })  # fmt: skip
    return {"key": job["key"], "rows": out, "usd": usd, "model": model, "n": len(job["rows"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--budget", type=float, default=15.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    O = ROOT / f"data/derived/outcomes/{args.docket}"
    entries = pd.read_parquet(ROOT / f"data/derived/responses/{args.docket}/entries.parquet")
    entries["organization"] = entries["organization"].fillna("Unknown")
    entries["excerpt"] = entries["excerpt"].fillna("")
    out_dir = O / "assign"
    out_dir.mkdir(exist_ok=True)

    jobs = []
    for p in sorted((O / "raw").glob("*.json")):
        d = json.loads(p.read_text())
        if not d["asks"] or (args.only and d["code"] not in args.only):
            continue
        rows = entries[entries["code"] == d["code"]].to_dict("records")
        for b in range(0, len(rows), BATCH):
            key = f"{d['code']}_{b // BATCH:03d}"
            if (out_dir / f"{key}.json").exists():
                continue
            jobs.append({"key": key, "code": d["code"], "title": d["title"], "asks": d["asks"],
                         "rows": rows[b : b + BATCH]})  # fmt: skip
    spent = sum(json.loads(p.read_text())["usd"] for p in out_dir.glob("*.json"))
    print(f"{len(jobs)} batches to run, ${spent:.2f} already spent", flush=True)
    workdir = Path(tempfile.mkdtemp(prefix="outcome-assign-"))

    with ThreadPoolExecutor(args.workers) as pool:
        it = iter(jobs)
        futs = {}
        for j in it:
            futs[pool.submit(one_batch, j, args.model, workdir)] = j
            if len(futs) >= args.workers:
                break
        while futs:
            for f in as_completed(list(futs)):
                j = futs.pop(f)
                try:
                    res = f.result()
                    (out_dir / f"{j['key']}.json").write_text(json.dumps(res))
                    spent += res["usd"]
                    hit = sum(r["ask"] is not None for r in res["rows"])
                    print(
                        f"{j['key']:>14}  {len(res['rows'])}/{res['n']} rows, {hit} tied to an ask, "
                        f"${res['usd']:.2f}  total ${spent:.2f}",
                        flush=True,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"{j['key']:>14}  FAILED {e}", file=sys.stderr, flush=True)
                if spent < args.budget:
                    nxt = next(it, None)
                    if nxt:
                        futs[pool.submit(one_batch, nxt, args.model, workdir)] = nxt
                break
    print(f"done, ${spent:.2f}", flush=True)


if __name__ == "__main__":
    main()
