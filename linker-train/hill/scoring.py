"""Frozen copy of how the API ranks sections, so a model that scores well here serves as is.

Copied from linker/data.py and linker/encoder.py, not imported, so a change to the project's code cannot
change what the hill measures. A section's score is its best window's cosine with the passage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

SINGLE_SECTION = {"EPA-HQ-OW-2018-0149": "328.3"}
MASK_TOKENS = re.compile(r"\[(CITATION|NUM|PARA|PART|HEADING)\]")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
QUERY_MAX_WORDS = 300
WINDOW_WORDS, WINDOW_STEP, WINDOW_SPLIT_ABOVE = 220, 180, 240
MAX_SEQ_LENGTH = 384


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", MASK_TOKENS.sub(" ", text)).strip()


def query_text(passage: dict) -> str:
    return QUERY_PREFIX + " ".join(clean(passage["masked"]).split()[:QUERY_MAX_WORDS])


def load_rule(path: Path) -> tuple[list[str], list[str], list[int]]:
    """(sections, window texts, window -> section index) for one rule file."""
    raw = json.loads(path.read_text())
    chunks = raw["chunks"]
    if raw["docket"] in SINGLE_SECTION:
        chunks = [c for c in chunks if c["section"] == SINGLE_SECTION[raw["docket"]]]
    texts, owners, sections = [], [], []
    for c in chunks:
        words = c["text"].split()
        if len(words) > WINDOW_SPLIT_ABOVE:
            parts = [" ".join(words[i : i + WINDOW_WORDS]) for i in range(0, len(words), WINDOW_STEP)]
        else:
            parts = [c["text"]]
        if c["section"] not in sections:
            sections.append(c["section"])
        for p in parts:
            texts.append((c["heading"] + ". " + p).strip())
            owners.append(sections.index(c["section"]))
    return sections, texts, owners


def ranks(model, rules_dir: Path, passages: list[dict]) -> list[int]:
    """1-based rank of each passage's labelled section among its rule's sections; ties count against."""
    out = [0] * len(passages)
    by: dict[str, list[int]] = {}
    for i, p in enumerate(passages):
        by.setdefault(p["docket"], []).append(i)
    for docket, idx in by.items():
        sections, texts, owners = load_rule(rules_dir / f"{docket}.json")
        W = model.encode(texts, batch_size=64, normalize_embeddings=True, convert_to_numpy=True)
        Q = model.encode([query_text(passages[i]) for i in idx], batch_size=64,
                         normalize_embeddings=True, convert_to_numpy=True)  # fmt: skip
        S = Q @ W.T
        owners_arr = np.asarray(owners)
        best = np.stack([S[:, owners_arr == s].max(axis=1) for s in range(len(sections))], axis=1)
        for r, i in enumerate(idx):
            label = sections.index(passages[i]["section"])
            row = best[r]
            out[i] = int((row > row[label]).sum() + (row == row[label]).sum())
    return out
