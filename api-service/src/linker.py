"""The tuned linker: which section of the rule a comment passage argues about.

linker-train fine-tunes bge-small on passages whose authors cited a section, with the citation
masked, and exports it as an ONNX folder (`linker-train export`). This module serves that folder
through fastembed, the runtime the rest of the API already uses, so no PyTorch is needed.

Only the rule's regulatory sections are ranked (section refs with a "§", such as
"PART 141/§ 141.84"): those are what the model was trained and scored on. A section's score is
its best passage's cosine with the comment, as in training. The gap between the first and second
section is the model's margin; below the cutoff stored with the model, the answer is flagged for
the reader model (the least sure 20% of the frozen test set).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from rule_passages.chunking import Chunk
from rule_passages.retrieve import clean_query

MODEL_NAME = "undersigned/linker"


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OnnxLinkerEmbedder:
    """The exported model through fastembed, with the query prefix and length it trained with."""

    def __init__(self, model_dir: Path, info: dict):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        if MODEL_NAME not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=MODEL_NAME, pooling=PoolingType.CLS, normalization=True,
                sources=ModelSource(hf=MODEL_NAME), dim=info["dim"], model_file="model.onnx",
            )  # fmt: skip
        self._model = TextEmbedding(MODEL_NAME, specific_model_path=str(model_dir))
        self.prefix = info["query_prefix"]
        self.max_words = info.get("query_max_words", 300)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        words = " ".join(text.split()[: self.max_words])
        return next(iter(self._model.embed([self.prefix + words]))).tolist()


def is_regulatory(chunk: Chunk) -> bool:
    return not chunk.procedural and "§" in chunk.section_ref.split("/")[-1]


@dataclass
class RuleSections:
    refs: list[str]
    chunks: list[Chunk]
    chunk_section: np.ndarray  # section index of each chunk
    vectors: np.ndarray  # one normalized row per chunk


class SectionLinker:
    """Every docket's regulatory sections, embedded once at startup."""

    def __init__(self, chunks: list[Chunk], embedder: Embedder, info: dict):
        self.embedder = embedder
        self.info = info
        cutoff = os.environ.get("LINK_MARGIN_CUTOFF", info.get("margin_cutoff", 0.0))
        self.margin_cutoff = float(cutoff)
        self.rules: dict[str, RuleSections] = {}
        by_docket: dict[str, list[Chunk]] = {}
        for c in chunks:
            if is_regulatory(c):
                by_docket.setdefault(c.docket_id, []).append(c)
        for docket, cs in by_docket.items():
            cs.sort(key=lambda c: (c.document_number, c.index))
            refs = list(dict.fromkeys(c.section_ref for c in cs))
            idx = {r: i for i, r in enumerate(refs)}
            vecs = self.embedder.embed_passages([c.embed_text for c in cs])
            vecs = np.asarray(vecs, dtype=np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
            section = np.array([idx[c.section_ref] for c in cs])
            self.rules[docket] = RuleSections(refs, cs, section, vecs)

    @property
    def dockets(self) -> list[str]:
        return sorted(self.rules)

    def link(self, text: str, docket_id: str, k: int) -> dict:
        rule = self.rules[docket_id]
        q = np.asarray(self.embedder.embed_query(clean_query(text)), dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        cos = rule.vectors @ q
        best = np.full(len(rule.refs), -np.inf, dtype=np.float32)
        best_chunk = np.zeros(len(rule.refs), dtype=int)
        for i, s in enumerate(rule.chunk_section):
            if cos[i] > best[s]:
                best[s], best_chunk[s] = cos[i], i
        order = np.argsort(-best, kind="stable")
        margin = float(best[order[0]] - best[order[1]]) if len(order) > 1 else 1.0
        sections = []
        for rank, s in enumerate(order[:k], start=1):
            c = rule.chunks[best_chunk[s]]
            sections.append({
                "rank": rank,
                "section_ref": rule.refs[s],
                "heading": c.heading,
                "citation": c.citation,
                "page": c.page,
                "score": round(float(best[s]), 4),
                "evidence": {"id": c.id, "text": c.text},
            })  # fmt: skip
        return {
            "docket_id": docket_id,
            "margin": round(margin, 4),
            "needs_reader": margin < self.margin_cutoff,
            "sections": sections,
        }

    def describe(self) -> dict:
        keep = ("run", "commit", "base_model", "test_acc@1", "reader_share", "margin_cutoff")
        return {**{k: self.info.get(k) for k in keep}, "margin_cutoff": self.margin_cutoff}


def open_linker(chunks: list[Chunk]) -> SectionLinker | None:
    """The model in LINKER_MODEL_DIR, or None when it is not set (then /link answers 503)."""
    model_dir = os.environ.get("LINKER_MODEL_DIR")
    if not model_dir:
        return None
    info = json.loads((Path(model_dir) / "linker.json").read_text())
    return SectionLinker(chunks, OnnxLinkerEmbedder(Path(model_dir), info), info)
