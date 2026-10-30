"""ChromaDB collection of rule chunks.

One document per chunk: the id is `<document_number>:<index>`, the stored text is the passage,
and every other Chunk field travels as metadata. Vectors are computed here and handed to Chroma,
so the collection never depends on a server-side embedding function. Rerunning an index call only
embeds chunks whose text changed.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterator
from dataclasses import asdict

import chromadb

from .chunking import Chunk
from .embedding import Embedder

BATCH = 128

log = logging.getLogger("rule-passages")


def connect(host: str, port: int) -> chromadb.ClientAPI:
    """The ChromaDB server, or with CHROMA_PATH set, a collection stored in that folder. Cloud Run
    serves the API from an image with the index inside it, so it needs no database server."""
    if path := os.environ.get("CHROMA_PATH"):
        return chromadb.PersistentClient(path=path)
    return chromadb.HttpClient(host=host, port=port)


def _digest(chunk: Chunk) -> str:
    return hashlib.sha1(f"{chunk.procedural}\n{chunk.embed_text}".encode()).hexdigest()


def _metadata(chunk: Chunk) -> dict[str, str | int]:
    meta = {k: v for k, v in asdict(chunk).items() if k not in ("id", "text") and v is not None}
    meta["sha1"] = _digest(chunk)
    return meta


def _where(include_procedural: bool, docket_id: str | None) -> dict | None:
    """The Chroma metadata filter for a query, or None when nothing is excluded."""
    conditions = []
    if not include_procedural:
        conditions.append({"procedural": False})
    if docket_id:
        conditions.append({"docket_id": docket_id})
    if len(conditions) > 1:
        return {"$and": conditions}
    return conditions[0] if conditions else None


def _chunk(chunk_id: str, text: str, meta: dict) -> Chunk:
    return Chunk(
        id=chunk_id,
        text=text,
        page=meta.get("page"),
        procedural=meta.get("procedural", False),
        **{
            k: meta[k]
            for k in Chunk.__dataclass_fields__
            if k not in ("id", "text", "page", "procedural")
        },
    )


class PassageStore:
    def __init__(self, client: chromadb.ClientAPI, name: str, embedder: Embedder):
        self.name = name
        self.embedder = embedder
        self.collection = client.get_or_create_collection(
            name, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
        )

    def count(self) -> int:
        return self.collection.count()

    def upsert(self, chunks: list[Chunk]) -> int:
        """Add or refresh chunks and return how many were embedded this call."""
        embedded = 0
        for start in range(0, len(chunks), BATCH):
            batch = chunks[start : start + BATCH]
            have = self.collection.get(ids=[c.id for c in batch], include=["metadatas"])
            stored = dict(zip(have["ids"], have["metadatas"], strict=True))
            todo = [c for c in batch if stored.get(c.id, {}).get("sha1") != _digest(c)]
            if not todo:
                continue
            self.collection.upsert(
                ids=[c.id for c in todo],
                documents=[c.text for c in todo],
                embeddings=self.embedder.embed_passages([c.embed_text for c in todo]),
                metadatas=[_metadata(c) for c in todo],
            )
            embedded += len(todo)
            log.info("[%s] embedded %d/%d", self.name, start + len(batch), len(chunks))
        return embedded

    def prune(self, keep: set[str], dockets: set[str] | None = None) -> int:
        """Delete stored chunks whose ids are not in `keep`, so the index matches the settings.

        With `dockets`, only chunks of those dockets are candidates, so indexing one docket
        never deletes another's chunks from the shared collection.
        """
        stale = [
            c.id
            for c in self.chunks()
            if c.id not in keep and (dockets is None or c.docket_id in dockets)
        ]
        for start in range(0, len(stale), BATCH):
            self.collection.delete(ids=stale[start : start + BATCH])
        return len(stale)

    def query(
        self, text: str, k: int, include_procedural: bool = True, docket_id: str | None = None
    ) -> list[tuple[Chunk, float]]:
        """The k nearest chunks to the text as (chunk, cosine similarity)."""
        res = self.collection.query(
            query_embeddings=[self.embedder.embed_query(text)],
            n_results=k,
            where=_where(include_procedural, docket_id),
            include=["documents", "metadatas", "distances"],
        )
        return [
            (_chunk(i, doc, meta), 1.0 - dist)
            for i, doc, meta, dist in zip(
                res["ids"][0],
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
                strict=True,
            )
        ]

    def chunks(self) -> Iterator[Chunk]:
        """Every stored chunk, ordered by id, for building the BM25 index from the same data."""
        offset = 0
        while True:
            page = self.collection.get(
                limit=BATCH, offset=offset, include=["documents", "metadatas"]
            )
            if not page["ids"]:
                return
            for i, doc, meta in zip(page["ids"], page["documents"], page["metadatas"], strict=True):
                yield _chunk(i, doc, meta)
            offset += len(page["ids"])
