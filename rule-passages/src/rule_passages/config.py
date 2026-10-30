"""Settings read from the environment, with defaults that work inside the compose network."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COLLECTION = "rule_passages"
# The document each docket's comments answered. A docket can hold later notices and final rules,
# and comments cannot have argued about text that did not exist yet.
COMMENTED_ON = {
    "EPA-HQ-OW-2018-0149": ("2019-00791",),  # 84 FR 4154, revised definition of WOTUS
    "EPA-HQ-OAR-2017-0355": ("2017-22349",),  # 82 FR 48035, repeal of the Clean Power Plan
    "EPA-HQ-OW-2022-0801": ("2023-26148",),  # 88 FR 84878, Lead and Copper Rule Improvements
}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    chroma_host: str
    chroma_port: int
    collection: str
    dockets: tuple[str, ...]
    doc_types: tuple[str, ...]
    documents: tuple[str, ...]
    max_words: int
    overlap_words: int

    @property
    def rule_dir(self) -> Path:
        return self.data_dir / "raw" / "federal_register"

    def wanted(self, docket: str, document_number: str, doc_type: str) -> bool:
        """Whether a collected document of this docket should be indexed."""
        if self.documents:
            return document_number in self.documents
        if docket in COMMENTED_ON:
            return document_number in COMMENTED_ON[docket]
        return doc_type in self.doc_types

    @classmethod
    def from_env(cls) -> Settings:
        # RULE_DOCKETS wins; otherwise index the rule for the dockets the rest of the chain
        # collects (DOCKET_IDS), so one setting moves every stage to another docket.
        dockets = (
            os.environ.get("RULE_DOCKETS") or os.environ.get("DOCKET_IDS") or "EPA-HQ-OW-2018-0149"
        )
        # Comments answer a proposal, so only proposed rules are searched by default.
        doc_types = os.environ.get("RULE_DOC_TYPES", "Proposed Rule")
        # Empty means the document each docket's comments answered (COMMENTED_ON).
        documents = os.environ.get("RULE_DOCUMENTS", "")
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "/app/data")),
            chroma_host=os.environ.get("CHROMA_HOST", "localhost"),
            chroma_port=int(os.environ.get("CHROMA_PORT", "8000")),
            collection=os.environ.get("RULE_COLLECTION", DEFAULT_COLLECTION),
            dockets=tuple(d.strip() for d in dockets.split(",") if d.strip()),
            doc_types=tuple(t.strip() for t in doc_types.split(",") if t.strip()),
            documents=tuple(d.strip() for d in documents.split(",") if d.strip()),
            max_words=int(os.environ.get("CHUNK_MAX_WORDS", "200")),
            overlap_words=int(os.environ.get("CHUNK_OVERLAP_WORDS", "40")),
        )
