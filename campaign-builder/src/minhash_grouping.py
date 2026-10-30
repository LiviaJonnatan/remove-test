"""Representative-based near-copy grouping. LSH proposes; exact Jaccard verifies.

Only representatives enter the index, preventing transitive chains of weak matches.
Sorted IDs, sorted candidates and a fixed seed make runs independent of input order.
LSH is approximate: verification removes false candidates but cannot recover misses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from datasketch import MinHash, MinHashLSH

from bcubed import score_frames
from exact_match import MIN_WORDS, normalize


def shingles(text: str, size: int = 5) -> set[str]:
    """Distinct consecutive word sequences, with a whole-text fallback for short text."""
    words = text.split()
    if not words:
        return set()
    return {" ".join(words[i : i + size]) for i in range(max(1, len(words) - size + 1))}


def group_minhash(
    letters: pd.DataFrame,
    threshold: float = 0.8,
    num_perm: int = 128,
    shingle_size: int = 5,
    min_words: int = MIN_WORDS,
    seed: int = 1,
) -> pd.DataFrame:
    """Return schema-compatible assignments; singleton campaign IDs remain null.

    Call once per docket. similarity is exact shingle Jaccard to the representative;
    ungrouped letters have null similarity. EPA labels never determine membership.
    """
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1 (exclusive)")
    if num_perm < 2 or shingle_size < 1 or min_words < 1:
        raise ValueError("num_perm >= 2, shingle_size >= 1 and min_words >= 1 required")
    ids = letters["letter_id"]
    if ids.isna().any() or not ids.map(lambda x: isinstance(x, str)).all():
        raise ValueError("letter_id must contain non-null strings")
    if ids.duplicated().any():
        raise ValueError("letter_id must be unique")
    if "docket_id" in letters and letters["docket_id"].nunique(dropna=False) > 1:
        raise ValueError("group one docket at a time")

    index = MinHashLSH(threshold=threshold, num_perm=num_perm)
    representatives: dict[str, set[str]] = {}
    exact_representatives: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    assigned: dict[str, tuple[str, float]] = {}
    for letter_id, text in letters.sort_values("letter_id")[["letter_id", "text"]].itertuples(
        index=False, name=None
    ):
        normalized = normalize(text if isinstance(text, str) else "")
        if len(normalized.split()) < min_words:
            continue
        # Avoid rebuilding signatures for the many exact copies of a form letter.
        if normalized in exact_representatives:
            representative = exact_representatives[normalized]
            members[representative].append(letter_id)
            assigned[letter_id] = (representative, 1.0)
            continue
        tokens = shingles(normalized, shingle_size)
        signature = MinHash(num_perm=num_perm, seed=seed)
        signature.update_batch([token.encode("utf-8") for token in sorted(tokens)])
        best_id, best_similarity = None, -1.0
        for candidate in sorted(index.query(signature)):
            other = representatives[candidate]
            similarity = len(tokens & other) / len(tokens | other)
            if similarity >= threshold and similarity > best_similarity:
                best_id, best_similarity = candidate, similarity
        if best_id is None:
            best_id, best_similarity = letter_id, 1.0
            representatives[letter_id] = tokens
            exact_representatives[normalized] = letter_id
            members[letter_id] = []
            index.insert(letter_id, signature)
        members[best_id].append(letter_id)
        assigned[letter_id] = (best_id, best_similarity)

    rows = []
    for letter_id in ids:
        representative, similarity = assigned.get(letter_id, (None, None))
        grouped = representative is not None and len(members[representative]) > 1
        rows.append(
            (
                letter_id,
                representative if grouped else None,
                "minhash",
                similarity if grouped else None,
            )
        )
    return pd.DataFrame(rows, columns=["letter_id", "campaign_id", "method", "similarity"])


def representative_tables(
    letters: pd.DataFrame, assignments: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Campaign summaries plus all representatives, including singleton letters.

    n_letters counts observed rows, never agency copies_claimed. n_copies is left
    to record-level accounting, where sample letters and attached letters can overlap.
    """
    mapping = assignments.copy()
    mapping["representative_letter_id"] = mapping["campaign_id"].fillna(mapping["letter_id"])
    counts = mapping.groupby("representative_letter_id", sort=True).size().rename("n_letters")
    representatives = letters.set_index("letter_id").loc[counts.index].reset_index()
    representatives = representatives.rename(columns={"letter_id": "representative_letter_id"})
    representatives["n_letters"] = counts.to_numpy()
    representatives["campaign_id"] = representatives["representative_letter_id"].where(
        representatives["n_letters"] > 1, None
    )
    campaigns = representatives.loc[
        representatives["n_letters"] > 1, ["campaign_id", "representative_letter_id", "n_letters"]
    ].reset_index(drop=True)
    return campaigns, representatives


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--letters", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--num-perm", type=int, default=128)
    parser.add_argument("--shingle-size", type=int, default=5)
    parser.add_argument("--min-words", type=int, default=MIN_WORDS)
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args(argv)
    letters = pd.read_parquet(args.letters)
    assignments = group_minhash(
        letters, args.threshold, args.num_perm, args.shingle_size, args.min_words
    )
    campaigns, representatives = representative_tables(letters, assignments)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in [
        ("assignments", assignments),
        ("campaigns", campaigns),
        ("representatives", representatives),
    ]:
        frame.to_parquet(out / f"{name}.parquet", index=False)
    print(
        f"{len(letters)} letters -> {len(representatives)} representatives; "
        f"{len(campaigns)} groups; threshold={args.threshold}"
    )
    has_labels = "epa_campaign_id" in letters and letters["epa_campaign_id"].notna().any()

    if args.score and not has_labels:
        print("Skipping B-cubed: no EPA campaign labels available.")

    if args.score and has_labels:
        score = score_frames(assignments, letters)
        print(
            f"B-cubed: precision={score.precision:.3f} recall={score.recall:.3f} "
            f"f1={score.f1:.3f} n={score.n_scored}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
