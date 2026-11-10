"""Linker cross-check: is the claim's cited section among the frozen linker's top 5?

The linker (65.5% top-1, 90.2% top-5 on the frozen test set) is not used to assign sections here:
the citation is the label. It is used as a second opinion. A claim whose section is not in the
linker's top 5 gets `linker_disagrees` in the review queue and a null linker_rank; otherwise the
rank is stored. Agreement across all claims is a sanity row in the eval, beside the 90.2%.

Two sources, picked by environment:
  GRAPH_LINKER_DIR   the exported ONNX folder (model.onnx, linker.json), loaded through fastembed
                     as api-service/src/linker.py loads it, ranked over rule-passages' chunks
  GRAPH_LINK_URL     a running API's POST /link (local compose or Cloud Run)
Neither set: the step is skipped and summary.json says so.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from config import Config

MODEL_NAME = "undersigned/linker"
TOP_K = 5

Link = Callable[[str], dict]  # text -> {"sections": [{"rank", "section_ref", ...}], "margin", ...}


class OnnxLinker:
    """The exported linker over the rule's regulatory chunks. Copy of api-service's loader."""

    def __init__(self, model_dir: Path, chunks: list, docket: str):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
        from rule_passages.retrieve import clean_query

        self.clean_query = clean_query
        self.info = json.loads((Path(model_dir) / "linker.json").read_text())
        if MODEL_NAME not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=MODEL_NAME, pooling=PoolingType.CLS, normalization=True,
                sources=ModelSource(hf=MODEL_NAME), dim=self.info["dim"], model_file="model.onnx",
            )  # fmt: skip
        self.model = TextEmbedding(MODEL_NAME, specific_model_path=str(model_dir))
        self.prefix = self.info["query_prefix"]
        self.max_words = self.info.get("query_max_words", 300)
        self.margin_cutoff = float(self.info.get("margin_cutoff", 0.0))
        regulatory = [
            c for c in chunks
            if c.docket_id == docket and not c.procedural and "§" in c.section_ref.split("/")[-1]
        ]  # fmt: skip
        regulatory.sort(key=lambda c: (c.document_number, c.index))
        self.refs = list(dict.fromkeys(c.section_ref for c in regulatory))
        idx = {r: i for i, r in enumerate(self.refs)}
        vecs = np.asarray(
            [v for v in self.model.embed([c.embed_text for c in regulatory], batch_size=32)],
            dtype=np.float32,
        )
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
        self.vectors = vecs
        self.chunk_section = np.array([idx[c.section_ref] for c in regulatory])

    def link(self, text: str, k: int = TOP_K) -> dict:
        words = " ".join(self.clean_query(text).split()[: self.max_words])
        q = np.asarray(next(iter(self.model.embed([self.prefix + words]))), dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        cos = self.vectors @ q
        best = np.full(len(self.refs), -np.inf, dtype=np.float32)
        for i, s in enumerate(self.chunk_section):
            best[s] = max(best[s], cos[i])
        order = np.argsort(-best, kind="stable")
        margin = float(best[order[0]] - best[order[1]]) if len(order) > 1 else 1.0
        return {
            "margin": round(margin, 4),
            "needs_reader": margin < self.margin_cutoff,
            "sections": [
                {"rank": r, "section_ref": self.refs[s], "score": round(float(best[s]), 4)}
                for r, s in enumerate(order[:k], start=1)
            ],
        }


def http_linker(url: str, docket: str) -> Link:
    import requests

    def link(text: str) -> dict:
        r = requests.post(
            url.rstrip("/") + "/link", json={"text": text, "docket_id": docket, "k": TOP_K},
            timeout=60,
        )  # fmt: skip
        r.raise_for_status()
        return r.json()

    return link


def open_linker(cfg: Config, chunks: list, docket: str) -> Link | None:
    if cfg.link_url:
        return http_linker(cfg.link_url, docket)
    if cfg.linker_dir:
        if not chunks:
            print(f"[{docket}] GRAPH_LINKER_DIR set but no rule chunks; cross-check skipped",
                  file=sys.stderr)  # fmt: skip
            return None
        return OnnxLinker(Path(cfg.linker_dir), chunks, docket).link
    return None


def run(
    claims: pd.DataFrame, texts: dict[str, str], link: Link | None
) -> tuple[pd.DataFrame, list[dict], dict]:
    """Fill linker_rank, add `linker_disagrees` review rows. One link per passage, not per claim."""
    if link is None or claims.empty:
        return claims, [], {"linker_checked": False, "linker_agree": None, "linker_claims": 0}
    cache: dict[str, list[str]] = {}
    ranks: list[int | None] = []
    review: list[dict] = []
    for c in claims.itertuples():
        if c.passage_id not in cache:
            cache[c.passage_id] = [s["section_ref"] for s in link(texts[c.passage_id])["sections"]]
        top = cache[c.passage_id]
        rank = top.index(c.section_ref) + 1 if c.section_ref in top else None
        ranks.append(rank)
        if rank is None:
            review.append(
                {"claim_id": c.claim_id, "issue_id": None, "reason": "linker_disagrees",
                 "detail": {"section_ref": c.section_ref, "linker_top5": top}}
            )  # fmt: skip
    claims = claims.copy()
    claims["linker_rank"] = pd.array(ranks, dtype="Int64")
    agree = sum(r is not None for r in ranks)
    return claims, review, {
        "linker_checked": True,
        "linker_agree": agree,
        "linker_claims": int(len(claims)),
        "linker_agree_share": round(agree / len(claims), 4),
    }
