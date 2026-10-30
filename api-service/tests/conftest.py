"""Shared test setup: an in-memory ChromaDB and a fake embedder, so tests run offline.

Same approach as rule-passages/tests/conftest.py: no Docker, no network, no model download.
"""

from __future__ import annotations

import re
import uuid

import chromadb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rule_passages.chunking import Chunk
from rule_passages.store import PassageStore

DEV_DOCKET = "EPA-HQ-OW-2018-0149"
LEAD = "EPA-HQ-OW-2022-0801"
PART = "PART 141--NATIONAL PRIMARY DRINKING WATER REGULATIONS"
REPLACEMENT = "V. Proposed Revisions > B. Service Line Replacement"
VOCAB = ["wetland", "ditch", "tributary", "ephemeral", "permit", "farm"]


class FakeEmbedder:
    """Vectors from keyword counts, so search results are predictable."""

    @staticmethod
    def _vector(text: str) -> list[float]:
        words = re.findall(r"[a-z]+", text.lower())
        vec = [float(sum(w.startswith(v) for w in words)) for v in VOCAB]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm + 1e-6 for x in vec]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def make_chunk(
    index: int,
    text: str,
    docket: str = DEV_DOCKET,
    doc: str = "2019-00791",
    ref: str = "III/D/1",
    heading: str = "D. Tributaries",
    procedural: bool = False,
) -> Chunk:
    return Chunk(
        id=f"{doc}:{index:04d}",
        docket_id=docket,
        document_number=doc,
        doc_title="Revised Definition",
        citation="84 FR 4154",
        url="https://example.org/doc",
        publication_date="2019-02-14",
        index=index,
        text=text,
        heading=heading,
        section_ref=ref,
        page=4170 + index,
        procedural=procedural,
    )


@pytest.fixture
def store() -> PassageStore:
    # EphemeralClient keeps collections for the whole test run, so each test gets a fresh name.
    name = f"test_{uuid.uuid4().hex[:8]}"
    return PassageStore(chromadb.EphemeralClient(), name, FakeEmbedder())


def lead_chunk(index: int, ref: str, heading: str) -> Chunk:
    return make_chunk(index, "Rule text.", docket=LEAD, doc="2023-26148", ref=ref, heading=heading)


@pytest.fixture
def lead_store(store: PassageStore) -> PassageStore:
    """Two parts of the lead rule, plus one WOTUS section so the store holds two dockets."""
    store.upsert([
        lead_chunk(0, "V/B", REPLACEMENT),
        lead_chunk(1, "PART 141/§ 141.84", f"{PART} > § 141.84 Lead service line inventory."),
        lead_chunk(2, "PART 141/§ 141.85", f"{PART} > § 141.85 Public education."),
        make_chunk(0, "Tributary flow.", ref="III/D", heading="III. Definition > D. Tributaries"),
    ])  # fmt: skip
    return store


def write_links(passages_dir, docket, rows) -> None:
    """links.parquet as passage-stage writes it, from (passage_id, letter_id, section_ref) rows.

    A row may add a fourth item, its citation_raw.
    """
    (passages_dir / docket).mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "passage_id": [r[0] for r in rows],
        "letter_id": [r[1] for r in rows],
        "docket_id": [docket] * len(rows),
        "section_ref": pa.array([r[2] for r in rows], pa.string()),
        "citation_raw": [r[3] if len(r) > 3 else "§ 141.8x" for r in rows],
        "source": ["citation"] * len(rows),
    })  # fmt: skip
    pq.write_table(table, passages_dir / docket / "links.parquet")


def write_passages(passages_dir, docket, rows) -> None:
    """passages.parquet as passage-stage writes it, from (passage_id, letter_id, index) rows."""
    (passages_dir / docket).mkdir(parents=True, exist_ok=True)
    texts = [f"Passage {r[0]} text." for r in rows]
    table = pa.table({
        "passage_id": [r[0] for r in rows],
        "letter_id": [r[1] for r in rows],
        "docket_id": [docket] * len(rows),
        "index": pa.array([r[2] for r in rows], pa.int64()),
        "text": texts,
        "text_masked": texts,
        "n_words": pa.array([3] * len(rows), pa.int64()),
        "n_citations": pa.array([1] * len(rows), pa.int64()),
    })  # fmt: skip
    pq.write_table(table, passages_dir / docket / "passages.parquet")
