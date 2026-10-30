"""Ways to find the rule passages a letter argues about, behind one interface: BM25, embeddings,
and the two combined by rank."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .bm25 import BM25Index
from .chunking import Chunk, clean_markup
from .store import PassageStore


def clean_query(text: str) -> str:
    """Comment bodies arrive as HTML with <br/> and style spans, so clean them like the rule."""
    return " ".join(clean_markup(text).split())


@dataclass(frozen=True)
class Hit:
    rank: int
    score: float
    retriever: str
    chunk: Chunk

    def to_dict(self) -> dict:
        """The JSON shape of a result, shared by the command line and the API."""
        c = self.chunk
        return {
            "retriever": self.retriever,
            "rank": self.rank,
            "score": round(self.score, 4),
            "id": c.id,
            "docket_id": c.docket_id,
            "document_number": c.document_number,
            "citation": c.citation,
            "page": c.page,
            "section_ref": c.section_ref,
            "heading": c.heading,
            "text": c.text,
        }


class Retriever(Protocol):
    name: str

    def search(self, query: str, k: int) -> list[Hit]: ...


class BM25Retriever:
    name = "bm25"

    def __init__(
        self, chunks: list[Chunk], include_procedural: bool = False, docket_id: str | None = None
    ):
        kept = [
            c
            for c in chunks
            if (include_procedural or not c.procedural)
            and (docket_id is None or c.docket_id == docket_id)
        ]
        self.chunks = sorted(kept, key=lambda c: c.id)
        self.index = BM25Index([c.embed_text for c in self.chunks])

    def search(self, query: str, k: int) -> list[Hit]:
        return [
            Hit(rank, score, self.name, self.chunks[i])
            for rank, (i, score) in enumerate(self.index.search(clean_query(query), k), start=1)
        ]


class DenseRetriever:
    name = "dense"

    def __init__(
        self, store: PassageStore, include_procedural: bool = False, docket_id: str | None = None
    ):
        self.store = store
        self.include_procedural = include_procedural
        self.docket_id = docket_id

    def search(self, query: str, k: int) -> list[Hit]:
        return [
            Hit(rank, score, self.name, chunk)
            for rank, (chunk, score) in enumerate(
                self.store.query(clean_query(query), k, self.include_procedural, self.docket_id),
                start=1,
            )
        ]


# Reciprocal rank fusion (Cormack, Clarke and Büttcher, SIGIR 2009). 60 is the constant from the
# paper; results barely change across a wide range, so it is the convention, not a value we tuned.
RRF_K = 60
# How deep each retriever is searched before fusing, so a passage both rank 8th can still make a
# fused top 3.
FUSION_DEPTH = 50


def reciprocal_rank_fusion(ranked_lists: Sequence[list[Hit]], k: int) -> list[Hit]:
    """Merge ranked lists into one top-k list using ranks only, never the raw scores.

    BM25 scores are unbounded and embedding scores are cosine similarity, so they cannot be added
    or sorted together. Instead each list a passage appears in adds 1 / (RRF_K + rank) to its
    score, so a passage that every retriever ranks fairly high beats one that a single retriever
    ranks first. Ties go to the passage with the better best rank, then to the passage id, so the
    order is always the same.
    """
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    chunks: dict[str, Chunk] = {}
    for hits in ranked_lists:
        for hit in hits:
            pid = hit.chunk.id
            scores[pid] = scores.get(pid, 0.0) + 1 / (RRF_K + hit.rank)
            best_rank[pid] = min(best_rank.get(pid, hit.rank), hit.rank)
            chunks[pid] = hit.chunk
    order = sorted(scores, key=lambda pid: (-scores[pid], best_rank[pid], pid))
    return [
        Hit(rank, scores[pid], FusedRetriever.name, chunks[pid])
        for rank, pid in enumerate(order[:k], start=1)
    ]


class FusedRetriever:
    """Several retrievers (usually BM25 and embeddings) combined into one list by rank.

    It is a Retriever like the other two, so anything that takes one (the API, `top_k_accuracy`)
    can use it without a special case. Pass retrievers built with the same docket and procedural
    settings; it does not filter on its own.
    """

    name = "merged"

    def __init__(self, retrievers: Sequence[Retriever], depth: int = FUSION_DEPTH):
        self.retrievers = list(retrievers)
        self.depth = depth

    def search(self, query: str, k: int) -> list[Hit]:
        lists = [r.search(query, max(k, self.depth)) for r in self.retrievers]
        return reciprocal_rank_fusion(lists, k)
