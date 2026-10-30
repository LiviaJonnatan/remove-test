"""rule-passages: chunk Federal Register rule text into ChromaDB; BM25 baseline.

Run with no arguments it does the batch stage: download the rule text for each docket in
RULE_DOCKETS (default: DOCKET_IDS), chunk it, embed it, and load it into the ChromaDB collection
`rule_passages`.
The other commands are for looking at the result:

  query   find the rule passages a letter argues about (BM25, dense, or both)
  outline list the section references a hand label can name
  eval    top-k accuracy on hand-mapped campaigns
  sweep   index at several chunk sizes and score each
  baseline  how often each method finds the section a comment passage cites (U-28)

Environment: DATA_DIR, CHROMA_HOST, CHROMA_PORT, RULE_DOCKETS, DOCKET_IDS, RULE_DOC_TYPES,
RULE_COLLECTION, CHUNK_MAX_WORDS, CHUNK_OVERLAP_WORDS, FASTEMBED_CACHE_PATH.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from rule_passages import baseline, pipeline
from rule_passages.config import Settings
from rule_passages.embedding import BgeEmbedder
from rule_passages.evaluate import format_table, load_labels, top_k_accuracy
from rule_passages.retrieve import BM25Retriever, DenseRetriever, Hit, Retriever
from rule_passages.store import PassageStore, connect


def open_store(settings: Settings) -> PassageStore:
    return PassageStore(
        connect(settings.chroma_host, settings.chroma_port), settings.collection, BgeEmbedder()
    )


def retrievers(
    store: PassageStore,
    method: str,
    docket_id: str | None = None,
    include_procedural: bool = False,
) -> list[Retriever]:
    found: list[Retriever] = []
    if method in ("bm25", "both"):
        found.append(BM25Retriever(list(store.chunks()), include_procedural, docket_id))
    if method in ("dense", "both"):
        found.append(DenseRetriever(store, include_procedural, docket_id))
    return found


def read_query(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    return args.text if args.text else sys.stdin.read()


def show(hits: list[Hit]) -> None:
    for h in hits:
        c = h.chunk
        page = f", p. {c.page}" if c.page else ""
        print(f"{h.retriever:5s} #{h.rank} {h.score:6.3f}  {c.citation}{page}  [{c.section_ref}]")
        print(f"      {c.heading}")
        print(f"      {' '.join(c.text.split())[:240]}...")


def cmd_query(settings: Settings, args: argparse.Namespace) -> None:
    text = read_query(args)
    found = retrievers(open_store(settings), args.method, args.docket)
    hits = [h for r in found for h in r.search(text, args.k)]
    if args.json:
        print(json.dumps([h.to_dict() for h in hits], indent=2))
    else:
        show(hits)


def cmd_outline(settings: Settings, args: argparse.Namespace) -> None:
    for doc, ref, heading, page, n, procedural in pipeline.section_outline(
        list(open_store(settings).chunks())
    ):
        flag = "procedural" if procedural else ""
        print(f"{doc}:{ref:<24s} p.{page or '?':<5} {n:>3} chunks  {flag:<10s} {heading[:80]}")


def cmd_eval(settings: Settings, args: argparse.Namespace) -> None:
    labels = load_labels(Path(args.labels))
    found = retrievers(open_store(settings), "both", include_procedural=args.include_procedural)
    rows = [(r.name, top_k_accuracy(r, labels)) for r in found]
    print(f"{len(labels)} labeled campaigns\n{format_table(rows)}")


def cmd_sweep(settings: Settings, args: argparse.Namespace) -> None:
    client = connect(settings.chroma_host, settings.chroma_port)
    labels = load_labels(Path(args.labels))
    sizes = [int(size) for size in args.sizes.split(",")]
    rows = pipeline.sweep(
        settings, client, BgeEmbedder(), labels, sizes, include_procedural=args.include_procedural
    )
    print(f"{len(labels)} labeled campaigns\n{format_table(rows)}")


def cmd_baseline(settings: Settings, args: argparse.Namespace) -> None:
    store = open_store(settings)
    chunks = list(store.chunks())
    for docket in settings.dockets:
        print(baseline.run(settings.data_dir, docket, chunks, store))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="collect and index (the default)")
    sub.add_parser("collect", help="download rule text only")
    sub.add_parser("index", help="chunk and index collected rule text only")
    query = sub.add_parser("query", help="find passages for a letter (text, file, or stdin)")
    source = query.add_mutually_exclusive_group()
    source.add_argument("--text")
    source.add_argument("--file")
    query.add_argument("--method", choices=["bm25", "dense", "both"], default="both")
    query.add_argument("--docket", help="only search this docket's rule text")
    query.add_argument("-k", type=int, default=3)
    query.add_argument("--json", action="store_true")
    sub.add_parser("outline", help="list the section references labels can use")
    score = sub.add_parser("eval", help="top-k accuracy on labeled campaigns")
    score.add_argument("--labels", required=True)
    score.add_argument(
        "--include-procedural", action="store_true", help="also search summary, addresses, etc."
    )
    sweep = sub.add_parser("sweep", help="compare chunk sizes")
    sweep.add_argument("--labels", required=True)
    sweep.add_argument("--sizes", default="120,250")
    sweep.add_argument(
        "--include-procedural", action="store_true", help="also search summary, addresses, etc."
    )
    sub.add_parser("baseline", help="find the section each citing comment passage cites")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per Chroma call
    settings = Settings.from_env()
    command = args.command or "run"
    if command in ("run", "collect"):
        pipeline.collect_all(settings)
    if command in ("run", "index"):
        pipeline.index(settings, connect(settings.chroma_host, settings.chroma_port), BgeEmbedder())
    inspect = {
        "query": cmd_query,
        "outline": cmd_outline,
        "eval": cmd_eval,
        "sweep": cmd_sweep,
        "baseline": cmd_baseline,
    }
    if command in inspect:
        inspect[command](settings, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
