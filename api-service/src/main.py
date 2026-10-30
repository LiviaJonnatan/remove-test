"""Undersigned API: the HTTP service the frontend calls.

At startup it opens the rule passage index that the rule-passages stage loaded into ChromaDB and
reads every passage once, so a request only has to search. The retrieval code lives in
rule-passages (the `rule_passages` package); this service imports it rather than keeping a copy.

Endpoints:
  GET  /health     liveness, plus how many passages the API can search and for which dockets
  POST /retrieve   a letter in, the rule passages it argues about out (BM25, embeddings, both
                   as separate lists, or one merged list)
  GET  /rules/{docket_id}/sections
                   the rule's sections in reading order, for the rule page
  GET  /rules/{docket_id}/passages?section_ref=...
                   the comment passages that cite a section or one under it
  POST /link       a comment passage in, the rule's sections ranked by the tuned linker out
  GET  /stats      request counts, errors and latency per endpoint since the process started

The section counts and citing passages come from passage-stage's links.parquet and
passages.parquet in DATA_DIR/derived/passages/<docket>/, also read once at startup. A docket
without those files keeps its counts and passages null (unknown).

Environment, with the same names rule-passages uses: CHROMA_HOST, CHROMA_PORT (or CHROMA_PATH for an
index folder), RULE_COLLECTION, FASTEMBED_CACHE_PATH, DATA_DIR. LINKER_MODEL_DIR is the exported
linker; without it /link answers 503.

Every request is logged as one JSON line (method, path, status, latency), never its body, so Cloud
Run's logs can be filtered and charted by field.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import pyarrow.parquet as pq
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, StringConstraints
from rule_passages.chunking import Chunk
from rule_passages.config import Settings
from rule_passages.embedding import BgeEmbedder
from rule_passages.retrieve import BM25Retriever, DenseRetriever, FusedRetriever, Hit
from rule_passages.store import PassageStore, connect

from linker import SectionLinker, open_linker

# uvicorn only prints its own loggers, so startup messages go through this one.
log = logging.getLogger("uvicorn.error")

Method = Literal["bm25", "dense", "both", "merged"]

# The most passages a request can ask for. 50, not 20: a reranker will read the top 30 candidates,
# so the API has to be able to supply them.
MAX_K = 50


def rule_sections(chunks: list[Chunk]) -> list[dict]:
    """One entry per section of rule text, in reading order, for a single docket's chunks.

    A section is a `section_ref` within one Federal Register document, plus every heading above
    it, so a parent with no text of its own ("III/D" when all its text sits under "III/D/1" and
    "III/D/2") still gets an entry: commenters cite "Section III.D". A parent comes just before
    its first child, and its counts include its children's. Procedural sections (summary,
    addresses, ...) are left out, as /retrieve leaves them out: nobody argues about them.
    """
    sections: dict[tuple[str, str], dict] = {}
    for chunk in sorted(chunks, key=lambda c: (c.document_number, c.index)):
        if chunk.procedural:
            continue
        refs = chunk.section_ref.split("/")
        headings = chunk.heading.split(" > ")
        # rule-passages builds both from the same heading path, one level per "/" and " > ", so
        # they line up. If a chunk's do not, list just its own section rather than guess its
        # parents' headings, so one odd chunk cannot stop the API from starting.
        first = 1 if len(refs) == len(headings) else len(refs)
        # Ancestors first, then the section itself, so dict order is reading order.
        for depth in range(first, len(refs) + 1):
            key = (chunk.document_number, "/".join(refs[:depth]))
            if key not in sections:
                own = depth == len(refs)
                sections[key] = {
                    "document_number": chunk.document_number,
                    "citation": chunk.citation,
                    "section_ref": key[1],
                    "parent_ref": "/".join(refs[: depth - 1]) or None,
                    "heading": chunk.heading if own else " > ".join(headings[:depth]),
                    "title": headings[-1] if own else headings[depth - 1],
                    "depth": depth,
                    # Where the section's first passage starts; for a parent, its first child's.
                    "page": chunk.page,
                    "rule_passages": 0,
                    # Comment passages, and distinct letters, that cite this section or one
                    # under it. Filled by add_citation_counts; null when the passage stage has
                    # not run for the docket, which is unknown, not zero.
                    "citing_passages": None,
                    "citing_letters": None,
                }
            sections[key]["rule_passages"] += 1
    return list(sections.values())


def read_links(passages_dir: Path | None, docket_id: str) -> list[dict] | None:
    """passage-stage's citation links for one docket, or None if it has not written them."""
    if passages_dir is None:
        return None
    path = passages_dir / docket_id / "links.parquet"
    if not path.exists():
        return None
    columns = ["passage_id", "letter_id", "section_ref", "citation_raw"]
    return pq.read_table(path, columns=columns).to_pylist()


def read_passages(passages_dir: Path | None, docket_id: str, wanted: set[str]) -> dict | None:
    """passage-stage's passages for one docket, by id, keeping only the `wanted` ones."""
    if passages_dir is None:
        return None
    path = passages_dir / docket_id / "passages.parquet"
    if not path.exists():
        return None
    columns = ["passage_id", "letter_id", "index", "text", "n_words"]
    rows = pq.read_table(path, columns=columns).to_pylist()
    return {r["passage_id"]: r for r in rows if r["passage_id"] in wanted}


def in_section(ref: str | None, section_ref: str) -> bool:
    """Whether a link's `section_ref` is the section or one under it."""
    return ref is not None and (ref == section_ref or ref.startswith(section_ref + "/"))


def add_citation_counts(sections: list[dict], links: list[dict]) -> int:
    """Fill each section's citing counts from the links, and return how many links are unresolved.

    A link names one section by rule-passages' `section_ref`, so it counts for that section and
    every section above it ("PART 141/§ 141.84" also counts for "PART 141"). Counts are of distinct
    passages and distinct letters: a passage citing two sections under one parent counts once there.
    A link whose `section_ref` is null cites something that is not a section of the rule.
    """
    passages: dict[str, set[str]] = defaultdict(set)
    letters: dict[str, set[str]] = defaultdict(set)
    unresolved = 0
    for link in links:
        ref = link["section_ref"]
        if ref is None:
            unresolved += 1
            continue
        parts = ref.split("/")
        for depth in range(1, len(parts) + 1):
            passages["/".join(parts[:depth])].add(link["passage_id"])
            letters["/".join(parts[:depth])].add(link["letter_id"])
    listed = {s["section_ref"] for s in sections}
    if missing := sorted(set(passages) - listed):
        # Both stages read the rule with rule-passages' chunking, so this means they ran on
        # different versions of the rule text.
        log.warning("Links cite sections the rule's index does not list: %s", ", ".join(missing))
    for section in sections:
        section["citing_passages"] = len(passages.get(section["section_ref"], ()))
        section["citing_letters"] = len(letters.get(section["section_ref"], ()))
    return unresolved


class PassageIndex:
    """The rule passages the API searches, read from ChromaDB once at startup."""

    def __init__(self, store: PassageStore, passages_dir: Path | None = None):
        self.store = store
        self.chunks: list[Chunk] = list(store.chunks())
        # An API that answers "ok" over an empty index looks healthy and finds nothing,
        # so refuse to start instead.
        if not self.chunks:
            raise RuntimeError(
                f"ChromaDB collection {store.name!r} is empty. Fill it with "
                "`docker compose run --rm rule-passages` before starting the API."
            )
        self.dockets: list[str] = sorted({c.docket_id for c in self.chunks})
        # BM25 keeps its index in memory, so build one for all dockets (key None) and one per
        # docket now rather than on every request.
        self._bm25 = {d: BM25Retriever(self.chunks, docket_id=d) for d in [None, *self.dockets]}
        # The rule text does not change while the API runs, so its sections are listed once.
        self.sections: dict[str, list[dict]] = {
            d: rule_sections([c for c in self.chunks if c.docket_id == d]) for d in self.dockets
        }
        # Links that cite something outside the rule, per docket; None where counts are unknown.
        self.unresolved_citations: dict[str, int | None] = {}
        self.links: dict[str, list[dict] | None] = {}
        # Only the passages some link cites, by id: the rest are never served.
        self.passages: dict[str, dict | None] = {}
        for d in self.dockets:
            links = self.links[d] = read_links(passages_dir, d)
            if links is None:
                self.unresolved_citations[d] = self.passages[d] = None
                log.info("No passage links for %s, so its citation counts stay null", d)
                continue
            self.unresolved_citations[d] = add_citation_counts(self.sections[d], links)
            cited = {link["passage_id"] for link in links}
            passages = self.passages[d] = read_passages(passages_dir, d, cited)
            if passages is not None and (missing := cited - set(passages)):
                log.warning("%d linked passages are missing from %s's passages", len(missing), d)
            log.info("Read %d passage links for %s", len(links), d)

    def citing_passages(self, docket_id: str, section_ref: str) -> list[dict] | None:
        """The passages citing a section or one under it, by letter then position in the letter.

        Each lists the citations it makes inside that section, so a parent's list says which
        child each passage cites. None when the passage stage has not run for the docket.
        """
        passages = self.passages.get(docket_id)
        if passages is None:
            return None
        cites: dict[str, dict[tuple[str, str], None]] = defaultdict(dict)
        for link in self.links[docket_id]:
            if in_section(link["section_ref"], section_ref) and link["passage_id"] in passages:
                cites[link["passage_id"]][(link["section_ref"], link["citation_raw"])] = None
        found = sorted(cites, key=lambda p: (passages[p]["letter_id"], passages[p]["index"]))
        return [
            {
                **passages[p],
                "citations": [{"section_ref": r, "citation_raw": c} for r, c in cites[p]],
            }
            for p in found
        ]

    def search(self, text: str, k: int, method: Method, docket_id: str | None) -> list[Hit]:
        """Top-k passages from each requested retriever, or one merged top-k list.

        For "both", BM25 hits come first, then embedding hits. They stay separate lists because
        their scores are on different scales (BM25 is unbounded, embeddings are cosine
        similarity), so sorting them together by score means nothing. "merged" combines them by
        rank instead (`FusedRetriever` in rule-passages, the same one its evaluation uses).
        """
        if docket_id is not None and docket_id not in self.dockets:
            return []
        bm25 = self._bm25[docket_id]
        dense = DenseRetriever(self.store, docket_id=docket_id)
        if method == "merged":
            return FusedRetriever([bm25, dense]).search(text, k)
        if method == "bm25":
            return bm25.search(text, k)
        if method == "dense":
            return dense.search(text, k)
        return bm25.search(text, k) + dense.search(text, k)


class LinkRequest(BaseModel):
    """A comment passage to link to a section of one docket's rule."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]
    docket_id: str = Field(description="the docket whose rule the passage comments on")
    k: int = Field(5, ge=1, le=MAX_K, description="sections to return")


class RequestStats:
    """Counts, errors and recent latencies per endpoint, for /stats. In memory, per instance."""

    def __init__(self, keep: int = 1000):
        self.count: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=keep))

    def add(self, route: str, status: int, ms: float) -> None:
        self.count[route] += 1
        self.errors[route] += status >= 500
        self.latency[route].append(ms)

    def summary(self) -> dict:
        def pct(xs, q):
            xs = sorted(xs)
            return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1) if xs else None

        return {
            r: {"requests": self.count[r], "server_errors": self.errors[r],
                "p50_ms": pct(self.latency[r], 0.5), "p90_ms": pct(self.latency[r], 0.9),
                "p99_ms": pct(self.latency[r], 0.99)}
            for r in sorted(self.count)
        }  # fmt: skip


class _StdoutHandler(logging.Handler):
    """Writes to whatever sys.stdout is when the line is logged."""

    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout.write(record.getMessage() + "\n")
        sys.stdout.flush()


def access_logger() -> logging.Logger:
    """One JSON object per line on stdout, which Cloud Run turns into a structured log entry."""
    logger = logging.getLogger("undersigned.access")
    if not logger.handlers:
        logger.addHandler(_StdoutHandler())
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


access = access_logger()


class RetrieveRequest(BaseModel):
    """A letter to find rule passages for. Invalid fields are rejected with a 422."""

    # bge-small reads only the first 512 tokens (a few hundred words) of a query; BM25 reads all
    # of it. The cap only stops absurd payloads.
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]
    k: int = Field(3, ge=1, le=MAX_K, description="passages per retriever, or in total for merged")
    method: Method = "both"
    docket_id: str | None = Field(None, description="only search this docket's rule text")


def open_index() -> PassageIndex:
    """Connect to the ChromaDB that rule-passages filled, with the model it embedded with."""
    settings = Settings.from_env()
    client = connect(settings.chroma_host, settings.chroma_port)
    store = PassageStore(client, settings.collection, BgeEmbedder())
    return PassageIndex(store, settings.data_dir / "derived" / "passages")


def create_app(
    load_index: Callable[[], PassageIndex] = open_index,
    load_linker: Callable[[list[Chunk]], SectionLinker | None] = open_linker,
) -> FastAPI:
    """Build the app. Tests pass a `load_index` that serves an in-memory collection, and a
    `load_linker` with a fake embedder."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        index = load_index()
        log.info(
            "Loaded %d rule passages from %r for %s",
            len(index.chunks), index.store.name, ", ".join(index.dockets),
        )  # fmt: skip
        app.state.index = index
        app.state.linker = load_linker(index.chunks)
        if app.state.linker is None:
            log.info("No LINKER_MODEL_DIR, so /link is off")
        else:
            log.info("Linker %s ready for %s", app.state.linker.info.get("run"),
                     ", ".join(app.state.linker.dockets))
        yield

    app = FastAPI(title="Undersigned API", lifespan=lifespan)
    app.state.stats = RequestStats()

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            ms = (time.perf_counter() - start) * 1000
            route = request.scope.get("route")
            name = route.path if route is not None else "unmatched"
            app.state.stats.add(f"{request.method} {name}", status, ms)
            access.info(json.dumps({
                "severity": "ERROR" if status >= 500 else "INFO",
                "message": f"{request.method} {request.url.path} {status} {ms:.0f}ms",
                "method": request.method, "route": name, "status": status,
                "latency_ms": round(ms, 1),
            }))  # fmt: skip

    @app.get("/health")
    def health(request: Request) -> dict:
        """Liveness check that also says what the API can search, and which linker it serves."""
        index: PassageIndex = request.app.state.index
        linker: SectionLinker | None = request.app.state.linker
        return {
            "status": "ok", "passages": len(index.chunks), "dockets": index.dockets,
            "linker": None if linker is None else linker.describe(),
        }  # fmt: skip

    @app.get("/stats")
    def stats(request: Request) -> dict:
        """Requests, server errors and latency percentiles per endpoint, for this instance."""
        return request.app.state.stats.summary()

    @app.post("/link")
    def link(body: LinkRequest, request: Request) -> dict:
        """The rule's sections ranked for one comment passage, each with the rule text that matched.

        `needs_reader` is true when the first two sections are too close to call (margin below the
        cutoff stored with the model); a batch job sends those passages to the reader model.
        """
        linker: SectionLinker | None = request.app.state.linker
        if linker is None:
            raise HTTPException(status_code=503, detail="No linker model (LINKER_MODEL_DIR).")
        if body.docket_id not in linker.rules:
            raise HTTPException(
                status_code=404,
                detail=f"No regulatory sections indexed for docket {body.docket_id!r}. "
                f"Linkable: {', '.join(linker.dockets) or 'none'}.",
            )
        return {**linker.link(body.text, body.docket_id, body.k), "model": linker.describe()}

    # A plain `def`, not `async def`: embedding the query blocks for a moment, and FastAPI runs
    # plain functions in a worker thread so other requests are not held up meanwhile.
    @app.post("/retrieve")
    def retrieve(body: RetrieveRequest, request: Request) -> dict:
        """The rule passages a letter argues about, in the shape `Hit.to_dict()` defines."""
        index: PassageIndex = request.app.state.index
        hits = index.search(body.text, body.k, body.method, body.docket_id)
        return {"hits": [hit.to_dict() for hit in hits]}

    @app.get("/rules/{docket_id}/sections")
    def sections(docket_id: str, request: Request) -> dict:
        """The sections of the rule a docket's comments answered, in reading order."""
        index: PassageIndex = request.app.state.index
        require_docket(index, docket_id)
        return {
            "docket_id": docket_id,
            "unresolved_citations": index.unresolved_citations[docket_id],
            "sections": index.sections[docket_id],
        }

    # section_ref is a query parameter, not part of the path, because refs contain "/".
    @app.get("/rules/{docket_id}/passages")
    def passages(
        docket_id: str,
        request: Request,
        section_ref: Annotated[str, Query(min_length=1)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        """One page of the comment passages citing a section, with the total across all pages."""
        index: PassageIndex = request.app.state.index
        require_docket(index, docket_id)
        if section_ref not in {s["section_ref"] for s in index.sections[docket_id]}:
            raise HTTPException(
                status_code=404,
                detail=f"Docket {docket_id!r} has no section {section_ref!r}.",
            )
        found = index.citing_passages(docket_id, section_ref)
        return {
            "docket_id": docket_id,
            "section_ref": section_ref,
            "total": None if found is None else len(found),
            "passages": None if found is None else found[offset : offset + limit],
        }

    return app


def require_docket(index: PassageIndex, docket_id: str) -> None:
    # A 404, not an empty list: the rule page should say "no such rule", not "no sections".
    if docket_id not in index.sections:
        raise HTTPException(
            status_code=404,
            detail=f"No rule text indexed for docket {docket_id!r}. "
            f"Indexed: {', '.join(index.dockets)}.",
        )


app = create_app()
