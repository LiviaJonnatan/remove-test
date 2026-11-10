"""Shared test inputs: three synthetic letters, a campaign with copies, recorded model answers.

No test reaches the network. The FakeBackend serves tests/fixtures/<tag>.json and raises for a tag
with no fixture; the embedder is a lookup table, so candidate pairs are known in advance.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import Config

DOCKET = "D-1"
S84 = "PART 141/§ 141.84"
S85 = "PART 141/§ 141.85"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

P1 = (
    "We oppose the ten-year replacement deadline in § 141.84(b) as proposed. Replacing every "
    "lead service line in ten years is not feasible for systems with more than 10,000 lines. Our "
    "utility has 42,000 lead lines and replaced 1,900 of them in 2023. EPA should allow a "
    "deferred deadline based on the number of lines a system owns."
)
P2 = (
    "The inventory in § 141.84(a) and the notice in § 141.85(a) should use the same reporting "
    "form. Two forms double the work for small systems."
)
P3 = (
    "Please require full replacement of all lead pipes within ten years as proposed in "
    "§ 141.84(b). Our children deserve safe water. Studies show no safe level of lead exposure."
)
P4 = "Also, § 141.85(a) notices should be mailed in Spanish as well as English."

LETTERS = pd.DataFrame(
    {
        "letter_id": ["L1", "L2", "L3", "L4"],
        "text": [P1 + " " + P2, P3, P3 + " " + P4, P3],
        "kind": ["organization", "individual", "individual", "individual"],
        "state": ["NJ", "MI", "MI", "OH"],
        "docket_id": [DOCKET] * 4,
    }
)
ASSIGNMENTS = pd.DataFrame(
    {
        "letter_id": ["L1", "L2", "L3", "L4"],
        "campaign_id": [None, "L2", "L2", "L2"],
        "method": ["containment"] * 4,
        "similarity": [None, 1.0, 0.9, 1.0],
    }
)
CAMPAIGNS = pd.DataFrame(
    {"campaign_id": ["L2"], "representative_letter_id": ["L2"], "n_letters": [3]}
)
# passage-stage output: L4 is a copy and has no passage; L3 only its own sentence.
PASSAGES = pd.DataFrame(
    {
        "passage_id": ["L1:p000", "L1:p001", "L2:p000", "L3:p000", "L1:p002"],
        "letter_id": ["L1", "L1", "L2", "L3", "L1"],
        "docket_id": [DOCKET] * 5,
        "index": [0, 1, 0, 0, 2],
        "text": [P1, P2, P3, P4, "Thank you for the opportunity to comment."],
        "text_masked": [P1, P2, P3, P4, "Thank you for the opportunity to comment."],
        "n_words": [len(P1.split()), len(P2.split()), len(P3.split()), len(P4.split()), 7],
        "n_citations": [1, 2, 1, 1, 0],
    }
)
LINKS = pd.DataFrame(
    {
        "passage_id": ["L1:p000", "L1:p001", "L1:p001", "L2:p000", "L3:p000", "L1:p002"],
        "letter_id": ["L1", "L1", "L1", "L2", "L3", "L1"],
        "docket_id": [DOCKET] * 6,
        "section_ref": [S84, S84, S85, S84, S85, None],
        "citation_raw": ["§ 141.84(b)", "§ 141.84(a)", "§ 141.85(a)", "§ 141.84(b)", "§ 141.85(a)",
                         "40 CFR 142.14"],
        "source": ["citation"] * 6,
    }
)  # fmt: skip

# The texts pairs.py embeds (ask, or quote when the ask is null) and the vectors they get.
VECTORS = {
    "Allow a deferred deadline based on the number of lines a system owns.": [1.0, 0.0, 0.0],
    "Replacing every lead service line in ten years is not feasible for systems with more than "
    "10,000 lines.": [0.7, -0.714, 0.0],
    "Require full replacement of all lead pipes within ten years.": [0.8, 0.6, 0.0],
    "Use one reporting form for the inventory and the notice.": [0.0, 0.0, 1.0],
    "Mail § 141.85(a) notices in Spanish as well as English.": [0.0, 0.76, 0.65],
}


def fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        if t in VECTORS:
            v = np.array(VECTORS[t], dtype=float)
        else:  # deterministic and unlike anything else
            h = hashlib.sha1(t.encode()).digest()
            v = np.array([h[0], h[1], h[2]], dtype=float) + 1.0
        out.append((v / np.linalg.norm(v)).tolist())
    return out


def write_inputs(data_dir: Path, letters=LETTERS, assignments=ASSIGNMENTS, campaigns=CAMPAIGNS,
                 passages=PASSAGES, links=LINKS) -> None:  # fmt: skip
    for layer in ("letters", "campaigns", "passages"):
        (data_dir / "derived" / layer / DOCKET).mkdir(parents=True, exist_ok=True)
    letters.to_parquet(data_dir / "derived" / "letters" / DOCKET / "letters.parquet", index=False)
    assignments.to_parquet(
        data_dir / "derived" / "campaigns" / DOCKET / "assignments.parquet", index=False
    )
    campaigns.to_parquet(
        data_dir / "derived" / "campaigns" / DOCKET / "campaigns.parquet", index=False
    )
    passages.to_parquet(
        data_dir / "derived" / "passages" / DOCKET / "passages.parquet", index=False
    )
    links.to_parquet(data_dir / "derived" / "passages" / DOCKET / "links.parquet", index=False)


def read_outputs(data_dir: Path) -> dict:
    out = data_dir / "derived" / "graph" / DOCKET
    tables = {
        name: pd.read_parquet(out / f"{name}.parquet")
        for name in ("claims", "pairs", "issues", "claim_issues", "review")
        if (out / f"{name}.parquet").exists()
    }
    tables["summary"] = json.loads((out / "summary.json").read_text())
    tables["graph"] = json.loads((out / "graph.json").read_text())
    tables["ledger"] = [
        json.loads(x) for x in (out / "ledger.jsonl").read_text().splitlines() if x.strip()
    ]
    return tables


def make_cfg(fixtures: Path = FIXTURES, **overrides) -> Config:
    base = {"backend_name": "fake", "fixtures": fixtures, "embed": fake_embed, "threads": 1}
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    write_inputs(tmp_path)
    return tmp_path


@pytest.fixture
def cfg() -> Config:
    return make_cfg()


@pytest.fixture
def failing_fixtures(tmp_path: Path) -> Path:
    """The recorded answers, with the 141.84 extract call answering nonsense twice."""
    dst = tmp_path / "fixtures_failing"
    shutil.copytree(FIXTURES, dst)
    (dst / "extract_141.84_000.json").write_text(
        json.dumps({"results": ["Sorry, I cannot help with that.", "{\"passages\": 7}"]})
    )
    return dst
