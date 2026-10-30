"""Every number in docs/evidence/campaign-builder/containment.md, from the processor's letters.

    uv run python scripts/evaluate_containment.py \
        --sample ../data/derived/letters/EPA-HQ-OW-2022-0801/letters.parquet \
        --ids ../data-collector/samples/ms2_ids.txt \
        --docket <the whole docket's letters.parquet>

--sample is the processor's output for the 40-record sample (RECORD_IDS_FILE set, the default in
.env.example); --docket is its output for the whole docket (RECORD_IDS_FILE and MAX_RECORDS empty).
Either may be left out. Prints markdown; no letter text.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import containment as C  # noqa: E402
from bcubed import bcubed  # noqa: E402
from exact_match import group_exact  # noqa: E402
from minhash_grouping import group_minhash  # noqa: E402

GROUPERS = {
    "Exact match": lambda letters: group_exact(letters),
    "MinHash, Jaccard 0.8": lambda letters: group_minhash(letters, threshold=0.8),
    "MinHash, Jaccard 0.3": lambda letters: group_minhash(letters, threshold=0.3),
    "Containment 0.4": lambda letters: C.group_containment(letters, threshold=0.4),
    "Containment 0.5": lambda letters: C.group_containment(letters, threshold=0.5),
    "Containment 0.6": lambda letters: C.group_containment(letters, threshold=0.6),
}


def campaigns_in(ids_file: Path) -> dict[str, str]:
    """letter_id -> campaign label, from the "# campaign_..." headings of the sample's ids file."""
    label, gold = None, {}
    for line in ids_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("#"):
            label = line[1:].strip() if line[1:].strip().startswith("campaign") else None
        elif line and label:
            gold[line] = label
    return gold


def predicted(assignments: pd.DataFrame) -> dict[str, str | None]:
    return {
        r.letter_id: None if pd.isna(r.campaign_id) else r.campaign_id
        for r in assignments.itertuples()
    }


def sample_table(letters: pd.DataFrame, gold: dict[str, str]) -> None:
    marked = sum(i in gold for i in letters.letter_id)
    print(f"Sample: {len(letters)} letters, {marked} campaign letters\n")
    print("| Grouper | Campaign letters grouped | Groups for them | Other letters grouped | F1 |")
    print("|---|---|---|---|---|")
    for name, run in GROUPERS.items():
        groups = predicted(run(letters))
        ours = [i for i in letters.letter_id if i in gold]
        grouped = [i for i in ours if groups[i] is not None]
        others = sum(groups[i] is not None for i in letters.letter_id if i not in gold)
        f1 = bcubed(groups, {i: gold.get(i) for i in groups}).f1
        print(
            f"| {name} | {len(grouped)} of {len(ours)} | {len({groups[i] for i in grouped})} "
            f"| {others} | {f1:.2f} |"
        )


def agreement(a: dict[str, str | None], b: dict[str, str | None]) -> float:
    """B-cubed F1 of `a` against `b` over letters either grouped; ungrouped is a group of one."""
    either = {i for i in a if a[i] is not None or b[i] is not None}
    gold = {i: b[i] if b[i] is not None else f"alone:{i}" for i in either}
    return bcubed({i: a[i] for i in either}, gold).f1


def docket_table(letters: pd.DataFrame) -> None:
    print(f"\nDocket: {len(letters)} letters\n")
    print("| Grouper | Letters grouped | Groups | Largest groups | Time |")
    print("|---|---|---|---|---|")
    runs = {}
    for name, run in GROUPERS.items():
        if name == "MinHash, Jaccard 0.3":
            continue
        start = time.perf_counter()
        runs[name] = predicted(run(letters))
        seconds = time.perf_counter() - start
        sizes = pd.Series([c for c in runs[name].values() if c is not None]).value_counts()
        print(
            f"| {name} | {int(sizes.sum())} | {len(sizes)} | "
            f"{', '.join(map(str, sizes.head(6)))} | {seconds:.1f} s |"
        )
    base = runs["Containment 0.5"]
    print()
    for other in ("Containment 0.4", "Containment 0.6"):
        print(f"- {other} against 0.5: B-cubed F1 {agreement(runs[other], base):.2f}")

    result = C.group_containment(letters)
    print(f"- Lowest similarity of a grouped letter: {result.similarity.min():.2f}")

    checked = C.CANDIDATES_CHECKED
    C.CANDIDATES_CHECKED = 10**9
    exhaustive = predicted(C.group_containment(letters, common_limit=10**9))
    C.CANDIDATES_CHECKED = checked
    same = sum(exhaustive[i] == base[i] for i in base)
    print(f"- Without the candidate shortcut: {same} of {len(base)} letters assigned the same")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--ids", type=Path)
    parser.add_argument("--docket", type=Path)
    args = parser.parse_args()
    if args.sample:
        sample_table(pd.read_parquet(args.sample), campaigns_in(args.ids))
    if args.docket:
        docket_table(pd.read_parquet(args.docket))


if __name__ == "__main__":
    main()
