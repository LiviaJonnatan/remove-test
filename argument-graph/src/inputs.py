"""What the stage reads, and which passages it extracts from.

Inputs, all written by earlier stages under DATA_DIR/derived/<layer>/<docket>/:
  letters/letters.parquet          letter_id, text, kind, state: quote fallback and letter nodes
  campaigns/assignments.parquet    letter_id -> campaign_id (null when ungrouped)
  campaigns/campaigns.parquet      campaign_id, n_letters, for counts that include copies
  passages/passages.parquet        the extraction unit; passage-stage already wrote one copy of a
                                   campaign's shared text, so no dedupe happens here
  passages/links.parquet           source == "citation" rows pick the passages and name the section

Selection: passages with at least one resolved citation link. A passage citing several sections is
extracted once with all of them as candidates; the first in reading order is its primary section,
which decides the batch it goes in. GRAPH_INCLUDE_UNCITED=1 adds passages the linker places with a
margin at or above the model's cutoff, marked section_source="linker".

Rule context for the prompts: heading plus the first 150 words of each section's first chunk, from
the rule_passages Chroma collection. When Chroma is unreachable the chunks are rebuilt from the rule
text on disk with rule-passages' own chunker (same section_refs); when that is missing too, the
prompts carry the heading only and summary.rule_context says so.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import Config

CONTEXT_WORDS = 150

LETTER_COLUMNS = ["letter_id", "text", "kind", "state"]


@dataclass
class Inputs:
    docket: str
    letters: pd.DataFrame
    assignments: pd.DataFrame
    campaigns: pd.DataFrame
    passages: pd.DataFrame
    links: pd.DataFrame
    paths: dict[str, Path]


def _stage_paths(docket: str, data_dir: Path) -> dict[str, Path]:
    d = data_dir / "derived"
    return {
        "letters": d / "letters" / docket / "letters.parquet",
        "assignments": d / "campaigns" / docket / "assignments.parquet",
        "campaigns": d / "campaigns" / docket / "campaigns.parquet",
        "passages": d / "passages" / docket / "passages.parquet",
        "links": d / "passages" / docket / "links.parquet",
    }


def load(docket: str, data_dir: Path) -> Inputs:
    """Read every input, or print `run <stage> first` and exit 1 like the other stages."""
    paths = _stage_paths(docket, data_dir)
    stage_of = {
        "letters": "data-processor",
        "assignments": "campaign-builder",
        "campaigns": "campaign-builder",
        "passages": "passage-stage",
        "links": "passage-stage",
    }
    for key, path in paths.items():
        if not path.exists():
            print(
                f"[{docket}] no {path.name} at {path}; run {stage_of[key]} first", file=sys.stderr
            )
            raise SystemExit(1)
    frames = {k: pd.read_parquet(p) for k, p in paths.items()}
    for key in ("letters", "passages"):
        if frames[key].empty:
            print(f"[{docket}] {paths[key]} is empty; run {stage_of[key]} first", file=sys.stderr)
            raise SystemExit(1)
    letters = frames["letters"]
    for col in LETTER_COLUMNS:
        if col not in letters.columns:
            letters[col] = None
    return Inputs(
        docket=docket,
        letters=letters[LETTER_COLUMNS],
        assignments=frames["assignments"],
        campaigns=frames["campaigns"],
        passages=frames["passages"],
        links=frames["links"],
        paths=paths,
    )


def select(
    inputs: Inputs,
    cfg: Config,
    link: Callable[[str], dict] | None = None,
    section_order: list[str] | None = None,
) -> pd.DataFrame:
    """One row per passage to extract: passage_id, letter_id, campaign_id, text, candidates,
    primary_ref, section_source. Sorted by (primary_ref, passage_id)."""
    cited = inputs.links[
        (inputs.links["source"] == "citation") & inputs.links["section_ref"].notna()
    ]
    order = {ref: i for i, ref in enumerate(section_order or [])}

    def ordered(refs: list[str]) -> list[str]:
        return sorted(set(refs), key=lambda r: (order.get(r, len(order)), r))

    by_passage = cited.groupby("passage_id")["section_ref"].agg(lambda s: ordered(list(s)))
    passages = inputs.passages.set_index("passage_id")
    campaign_of = dict(
        zip(inputs.assignments["letter_id"], inputs.assignments["campaign_id"], strict=True)
    )
    rows = []
    for pid, refs in by_passage.items():
        if pid not in passages.index:
            continue
        p = passages.loc[pid]
        rows.append(
            {
                "passage_id": pid,
                "letter_id": p["letter_id"],
                "campaign_id": campaign_of.get(p["letter_id"]),
                "text": p["text"],
                "candidates": list(refs),
                "primary_ref": refs[0],
                "section_source": "citation",
            }
        )
    if cfg.include_uncited and link is not None:
        chosen = {r["passage_id"] for r in rows}
        for pid, p in passages.iterrows():
            if pid in chosen:
                continue
            res = link(p["text"])
            if not res.get("sections") or res.get("needs_reader", True):
                continue
            top = res["sections"][0]["section_ref"]
            rows.append(
                {
                    "passage_id": pid,
                    "letter_id": p["letter_id"],
                    "campaign_id": campaign_of.get(p["letter_id"]),
                    "text": p["text"],
                    "candidates": [s["section_ref"] for s in res["sections"][:5]],
                    "primary_ref": top,
                    "section_source": "linker",
                }
            )
    out = pd.DataFrame(
        rows,
        columns=[
            "passage_id", "letter_id", "campaign_id", "text", "candidates", "primary_ref",
            "section_source",
        ],
    )  # fmt: skip
    out["campaign_id"] = out["campaign_id"].astype("object").where(out["campaign_id"].notna(), None)
    out = out.sort_values(["primary_ref", "passage_id"], kind="stable").reset_index(drop=True)
    if cfg.max_passages is not None:
        out = out.head(cfg.max_passages).reset_index(drop=True)
    return out


# -- rule text ------------------------------------------------------------------------------------


def rule_chunks(docket: str, data_dir: Path) -> tuple[list, str]:
    """rule-passages' chunks for this docket and where they came from: chroma, files or none."""
    from rule_passages.config import Settings

    settings = Settings.from_env()
    if os.environ.get("CHROMA_PATH") or os.environ.get("CHROMA_HOST"):
        try:
            from rule_passages.store import PassageStore, connect

            client = connect(settings.chroma_host, settings.chroma_port)
            store = PassageStore(client, settings.collection, None)
            chunks = [c for c in store.chunks() if c.docket_id == docket]
            if chunks:
                return chunks, "chroma"
        except Exception as e:  # the server is down or the collection is empty
            print(f"[{docket}] rule_passages collection unreachable ({e}); reading rule text",
                  file=sys.stderr)  # fmt: skip
    try:
        from rule_passages.chunking import chunk_document
        from rule_passages.collect import load_documents

        chunks = []
        for doc in load_documents(docket, data_dir / "raw" / "federal_register"):
            if settings.wanted(docket, doc.document_number, doc.doc_type):
                chunks.extend(chunk_document(doc, settings.max_words, settings.overlap_words))
        if chunks:
            return chunks, "files"
    except (FileNotFoundError, OSError):
        pass
    return [], "none"


def rule_context(chunks: list) -> dict[str, dict]:
    """section_ref -> {heading, context}: the heading and the first 150 words of the first chunk."""
    out: dict[str, dict] = {}
    for c in sorted(chunks, key=lambda c: (c.document_number, c.index)):
        if c.section_ref in out:
            continue
        words = c.text.split()
        out[c.section_ref] = {
            "heading": c.heading.split(" > ")[-1] if c.heading else "",
            "context": " ".join(words[:CONTEXT_WORDS]),
        }
    return out
