"""Run settings, read once from the environment. main.py's docstring documents every variable."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

Embed = Callable[[list[str]], list[list[float]]]


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


def _opt_int(name: str) -> int | None:
    v = os.getenv(name, "").strip()
    return int(v) if v else None


@dataclass
class Config:
    backend_name: str = "auto"  # cli, sdk, fake, none, auto
    model: str = "fable"  # CLI alias
    model_id: str = "claude-fable-5-1"  # SDK id
    effort: str = "medium"
    batch: int = 12
    pairs_per_call: int = 40
    pair_min: float = 0.60
    pair_k: int = 10
    max_passages: int | None = None
    max_pairs: int | None = None
    max_usd: float = 40.0
    threads: int = 8
    include_uncited: bool = False
    linker_dir: str | None = None
    link_url: str | None = None
    label_issues: bool = False
    fixtures: Path | None = None  # FakeBackend
    embed: Embed | None = None  # injected by tests; fastembed bge-small otherwise
    wandb: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            backend_name=os.getenv("GRAPH_BACKEND", "auto").strip().lower() or "auto",
            model=os.getenv("GRAPH_MODEL", "fable").strip() or "fable",
            model_id=os.getenv("GRAPH_MODEL_ID", "claude-fable-5-1").strip() or "claude-fable-5-1",
            effort=os.getenv("GRAPH_EFFORT", "medium").strip() or "medium",
            batch=int(os.getenv("GRAPH_BATCH", "12")),
            pairs_per_call=int(os.getenv("GRAPH_PAIRS_PER_CALL", "40")),
            pair_min=float(os.getenv("GRAPH_PAIR_MIN", "0.60")),
            pair_k=int(os.getenv("GRAPH_PAIR_K", "10")),
            max_passages=_opt_int("GRAPH_MAX_PASSAGES"),
            max_pairs=_opt_int("GRAPH_MAX_PAIRS"),
            max_usd=float(os.getenv("GRAPH_MAX_USD", "40")),
            threads=int(os.getenv("GRAPH_THREADS", "8")),
            include_uncited=_flag("GRAPH_INCLUDE_UNCITED"),
            linker_dir=os.getenv("GRAPH_LINKER_DIR") or None,
            link_url=os.getenv("GRAPH_LINK_URL") or None,
            label_issues=_flag("GRAPH_LABEL_ISSUES"),
            fixtures=Path(os.environ["GRAPH_FIXTURES"]) if os.getenv("GRAPH_FIXTURES") else None,
            wandb=_flag("GRAPH_WANDB"),
        )


def short_ref(section_ref: str) -> str:
    """`PART 141/§ 141.84` -> `141.84`; a preamble ref such as `V/E` -> `V-E`. Used in tags."""
    last = section_ref.split("/")[-1].strip()
    if "§" in last:
        return last.replace("§", "").strip()
    return section_ref.replace("/", "-").replace(" ", "_")
