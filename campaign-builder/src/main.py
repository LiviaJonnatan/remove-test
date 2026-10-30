"""campaign-builder: group the processor's letters into campaigns.

For each docket in DOCKET_IDS, reads DATA_DIR/derived/letters/<docket>/letters.parquet and writes
DATA_DIR/derived/campaigns/<docket>/assignments.parquet, the paths in schema.md.
GROUPING_METHOD selects the grouper: "exact" (identical text), "minhash" (Jaccard of phrases) or
"containment" (how much of one letter's wording the other contains, for personalized form letters;
see containment.py).

Beside the assignments it writes summary.json: the counts, B-cubed when EPA grouped any of the
letters, and the sha256 of the letters file it read, so the result can be tied to its input
without reading the container's output.

Environment:
  DOCKET_IDS              comma-separated, default EPA-HQ-OW-2018-0149
  DATA_DIR                default /app/data
  GROUPING_METHOD         exact, minhash or containment, default containment
  MINHASH_THRESHOLD       Jaccard for minhash, default 0.8
  CONTAINMENT_THRESHOLD   for containment, default 0.5
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

import containment
from bcubed import score_frames
from exact_match import MIN_WORDS, group_exact, summarize
from minhash_grouping import group_minhash, representative_tables


def build_docket(
    docket: str, data_dir: Path, method: str = "containment", threshold: float | None = None
) -> bool:
    """Group one docket's letters. False if the processor wrote no letters for it.

    threshold defaults to containment.THRESHOLD for containment and 0.8 for MinHash."""
    letters_path = data_dir / "derived" / "letters" / docket / "letters.parquet"
    if not letters_path.exists():
        print(f"[{docket}] no letters at {letters_path}; run data-processor first", file=sys.stderr)
        return False
    letters = pd.read_parquet(letters_path)
    # An empty file means every record failed or none were collected. Grouping it would "succeed"
    # with nothing grouped, and the chain would look like it passed.
    if letters.empty:
        print(f"[{docket}] {letters_path} is empty; see the processor's report", file=sys.stderr)
        return False
    if method not in {"exact", "minhash", "containment"}:
        raise ValueError("GROUPING_METHOD must be exact, minhash or containment")
    if threshold is None:
        threshold = containment.THRESHOLD if method == "containment" else 0.8
    if method == "exact":
        assignments = group_exact(letters)
    elif method == "minhash":
        assignments = group_minhash(letters, threshold=threshold)
    else:
        assignments = containment.group_containment(letters, threshold=threshold)
    out = data_dir / "derived" / "campaigns" / docket / "assignments.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    assignments.to_parquet(out, index=False)
    campaigns, representatives = representative_tables(letters, assignments)
    campaigns.to_parquet(out.parent / "campaigns.parquet", index=False)
    representatives.to_parquet(out.parent / "representatives.parquet", index=False)

    grouped = assignments["campaign_id"].notna()
    summary = {
        "docket_id": docket,
        "method": method,
        "min_words": MIN_WORDS,
        "letters": int(len(assignments)),
        "letters_grouped": int(grouped.sum()),
        "groups": int(assignments.loc[grouped, "campaign_id"].nunique()),
        "individual": int((~grouped).sum()),
        "bcubed": None,
        "letters_file": str(letters_path.relative_to(data_dir)),
        "letters_sha256": hashlib.sha256(letters_path.read_bytes()).hexdigest(),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if method == "minhash":
        summary.update({"threshold": threshold, "num_perm": 128, "shingle_size": 5, "seed": 1})
    if method == "containment":
        summary.update(
            {
                "threshold": threshold,
                "shingle_size": containment.SHINGLE_SIZE,
                "max_length_ratio": containment.MAX_LENGTH_RATIO,
                "common_limit": containment.COMMON_LIMIT,
            }
        )
    status = summarize(assignments)
    if method != "exact":
        status = status.replace("exact-match", method)
    print(f"[{docket}] {status}")

    # EPA's grouping only exists for letters inside campaign attachments, so score when present.
    if "epa_campaign_id" in letters and letters["epa_campaign_id"].notna().any():
        scores = score_frames(assignments, letters)
        summary["bcubed"] = {
            "n_scored": int(scores.n_scored),
            "precision": round(float(scores.precision), 4),
            "recall": round(float(scores.recall), 4),
            "f1": round(float(scores.f1), 4),
        }
        print(
            f"[{docket}] B-cubed on {scores.n_scored} labeled letters: "
            f"precision {scores.precision:.3f}  recall {scores.recall:.3f}  f1 {scores.f1:.3f}"
        )
    (out.parent / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return True


def main() -> int:
    load_dotenv()
    dockets = [
        d.strip() for d in os.getenv("DOCKET_IDS", "EPA-HQ-OW-2018-0149").split(",") if d.strip()
    ]
    data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
    method = os.getenv("GROUPING_METHOD") or "containment"
    # An empty value in .env means the default, as for GROUPING_METHOD.
    if method == "containment":
        threshold = float(os.getenv("CONTAINMENT_THRESHOLD") or containment.THRESHOLD)
    else:
        threshold = float(os.getenv("MINHASH_THRESHOLD") or 0.8)
    done = [build_docket(docket, data_dir, method, threshold) for docket in dockets]
    return 0 if all(done) else 1


if __name__ == "__main__":
    sys.exit(main())
