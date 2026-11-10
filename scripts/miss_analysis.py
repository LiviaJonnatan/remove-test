"""Error analysis for one held-out docket: what the linker got wrong and how.

Usage, from the repo root:
  python3 scripts/miss_analysis.py HHS-OS-2022-0012 \
      docs/evidence/linker-train/lodo-pre-HHS-OS-2022-0012/HHS-OS-2022-0012+ctx/predictions.jsonl \
      --out docs/evidence/linker-train/lodo-pre-HHS-OS-2022-0012/misses.md

Reads data/linking/test.json for the passage text and data/linking/rules/<docket>.json for headings.
Writes a markdown report and prints a summary.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

TEXT_FIELDS = ("text", "passage", "masked", "query")


def section_key(s: str):
    """'106.31' -> (106, 31) for ordering; non-numeric parts sort last."""
    parts = re.split(r"[.\-]", s)
    out = []
    for p in parts:
        m = re.match(r"\d+", p)
        out.append((0, int(m.group()), p) if m else (1, 0, p))
    return tuple(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docket")
    ap.add_argument("predictions")
    ap.add_argument("--data", default="data/linking")
    ap.add_argument("--out", default=None)
    ap.add_argument("--examples", type=int, default=15)
    a = ap.parse_args()

    data = Path(a.data)
    rule = json.loads((data / "rules" / f"{a.docket}.json").read_text())
    heading = {s["section"]: s["heading"] for s in rule["sections"]}
    order = sorted(heading, key=section_key)
    pos = {s: i for i, s in enumerate(order)}

    test = json.loads((data / "test.json").read_text())
    text_field = next((f for f in TEXT_FIELDS if f in test[0]), None)
    if text_field is None:
        raise SystemExit(f"no text field in test.json; keys are {list(test[0])}")
    passage = {p["qid"]: p for p in test if p["docket"] == a.docket}

    rows = [json.loads(l) for l in Path(a.predictions).read_text().splitlines()]
    rows = [r for r in rows if r["split"] == "test" and r["docket"] == a.docket]
    misses = [r for r in rows if r["rank"] != 1]
    n = len(rows)

    # 1. where the true section ended up
    rank_buckets = Counter()
    for r in misses:
        rk = r["rank"]
        rank_buckets["2" if rk == 2 else "3-5" if rk <= 5 else "6-10" if rk <= 10 else ">10 (not in top10)"] += 1

    # 2. what kind of wrong pick
    kinds = Counter()
    for r in misses:
        pick, true = r["top10"][0], r["label"]
        if pick == true:
            kinds["tie/other"] += 1
            continue
        same_part = pick.split(".")[0] == true.split(".")[0]
        adjacent = abs(pos.get(pick, -99) - pos.get(true, 99)) == 1
        kinds["adjacent section" if adjacent else "same part, not adjacent" if same_part else "different part"] += 1

    # 3. sections that absorb picks, and sections the model never gets
    absorb = Counter(r["top10"][0] for r in misses)
    true_counts = Counter(r["label"] for r in rows)
    hit_counts = Counter(r["label"] for r in rows if r["rank"] == 1)
    worst = sorted(true_counts, key=lambda s: (hit_counts[s] / true_counts[s], -true_counts[s]))

    # 4. confusion pairs
    pairs = Counter((r["label"], r["top10"][0]) for r in misses)

    # 5. margin: are misses low-confidence?
    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else float("nan")

    m_hit = med([r["margin"] for r in rows if r["rank"] == 1])
    m_miss = med([r["margin"] for r in misses])

    out = []
    out.append(f"# Misses on {a.docket} ({len(misses)} of {n} test passages, {100 * (n - len(misses)) / n:.1f}% top-1)\n")
    out.append("## Where the true section ranked\n")
    out += [f"- rank {k}: {v}" for k, v in sorted(rank_buckets.items())]
    out.append("\n## What was picked instead\n")
    out += [f"- {k}: {v}" for k, v in kinds.most_common()]
    out.append(f"\n## Confidence\n\nmedian margin on hits {m_hit:.3f}, on misses {m_miss:.3f}\n")
    out.append("## Sections that absorb wrong picks\n")
    out += [f"- {s} ({heading.get(s, '?')}): picked wrongly {c} times" for s, c in absorb.most_common(8)]
    out.append("\n## Sections the model gets least often (true count >= 3)\n")
    out += [
        f"- {s} ({heading.get(s, '?')}): {hit_counts[s]}/{true_counts[s]}"
        for s in worst
        if true_counts[s] >= 3
    ][:10]
    out.append("\n## Most common confusions (true -> picked)\n")
    out += [f"- {t} -> {p}: {c}   [{heading.get(t, '?')} -> {heading.get(p, '?')}]" for (t, p), c in pairs.most_common(10)]
    out.append(f"\n## {a.examples} example misses\n")
    for r in sorted(misses, key=lambda r: -r["margin"])[: a.examples]:
        p = passage.get(r["qid"])
        txt = (p[text_field] if p else "(text not found)").replace("\n", " ")
        if len(txt) > 400:
            txt = txt[:400] + " ..."
        out.append(
            f"**true {r['label']}** ({heading.get(r['label'], '?')}) · picked {r['top10'][0]} "
            f"({heading.get(r['top10'][0], '?')}) · true at rank {r['rank']} · margin {r['margin']:.3f}\n\n> {txt}\n"
        )

    report = "\n".join(out)
    print(report[: report.index("## Most common confusions")])
    if a.out:
        Path(a.out).write_text(report)
        print(f"\nwritten {a.out}")


if __name__ == "__main__":
    main()