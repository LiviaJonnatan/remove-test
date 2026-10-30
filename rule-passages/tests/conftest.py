from __future__ import annotations

import re
import uuid
from pathlib import Path

import chromadb
import pytest

from rule_passages.chunking import Chunk
from rule_passages.collect import RuleDocument

FIXTURES = Path(__file__).parent / "fixtures"
VOCAB = ["wetland", "ditch", "tributary", "permit", "lake", "farm"]


class FakeEmbedder:
    """Vectors from keyword counts, so store tests run offline and results are predictable."""

    def __init__(self) -> None:
        self.passages_embedded = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        words = re.findall(r"[a-z]+", text.lower())
        vec = [float(sum(w.startswith(v) for w in words)) for v in VOCAB]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm + 1e-6 for x in vec]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.passages_embedded += len(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def chroma() -> chromadb.ClientAPI:
    return chromadb.EphemeralClient()


@pytest.fixture
def collection_name() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def raw_excerpt() -> str:
    return (FIXTURES / "fr_excerpt.txt").read_text(encoding="utf-8")


@pytest.fixture
def document(raw_excerpt: str) -> RuleDocument:
    return RuleDocument(
        docket_id="EPA-HQ-OW-2018-0149",
        document_number="2019-00791",
        title="Revised Definition of “Waters of the United States”",
        doc_type="Proposed Rule",
        publication_date="2019-02-14",
        citation="84 FR 4154",
        url="https://www.federalregister.gov/d/2019-00791",
        raw_text=raw_excerpt,
    )


def make_chunk(
    index: int,
    text: str,
    ref: str = "III/G",
    heading: str = "G. Wetlands",
    doc: str = "2019-00791",
    docket: str = "EPA-HQ-OW-2018-0149",
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
    )


DOCKET = "EPA-HQ-OW-2018-0149"


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload, self.text = payload, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def listing(number: str, title: str, doc_type: str, date: str, citation: str) -> dict:
    return {
        "document_number": number,
        "title": title,
        "type": doc_type,
        "publication_date": date,
        "citation": citation,
        "html_url": f"https://example.org/{number}",
        "raw_text_url": f"https://example.org/{number}.txt",
        "docket_ids": [DOCKET],
    }


class FakeSession:
    """Serves a two-page document listing and a text body per document, and counts requests."""

    def __init__(self, raw_text: str):
        self.raw_text = raw_text
        self.requests: list[str] = []
        self.listing_params: dict = {}

    def get(self, url, params=None, timeout=None):
        self.requests.append(url)
        if url.endswith("documents.json"):
            self.listing_params = params
        if url.endswith("documents.json"):
            first = listing(
                "2019-00791", "Revised Definition", "Proposed Rule", "2019-02-14", "84 FR 4154"
            )
            return FakeResponse({"results": [first], "next_page_url": "https://example.org/page2"})
        if url == "https://example.org/page2":
            second = listing("2019-01483", "Extension", "Notice", "2019-02-27", "84 FR 6")
            return FakeResponse({"results": [second]})
        return FakeResponse(text=self.raw_text)
