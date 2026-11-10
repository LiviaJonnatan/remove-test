"""Extractor: every claim a cited passage makes, with a verbatim quote, a stance, an ask and the
kind of evidence offered.

Batches of GRAPH_BATCH passages share a section, so the section heading and rule context are the
same for the whole call (and cached on the SDK backend). Tags are extract_<section>_<batch>; a
rerun finds raw/<tag>.json and makes no call.

Checks after each call, all deterministic (see README "Harness rules"):
  partition    every passage id back exactly once, else one re-ask listing the missing and
               duplicated ids; a passage still missing gets a `missing_from_output` review row
  quote        quotes.verified() against the passage, then the whole letter; the failing claims of
               a batch get one re-ask (requote_<section>_<batch>); still failing -> the claim is
               dropped and logged `quote_failed`. The script never shortens a quote
  fragment     a heading-like or very short quote keeps the claim with needs_review=true
  section      the model's section_ref must be one of the passage's cited sections; otherwise the
               citation wins and the disagreement is logged
  llm_failed   both attempts invalid: one review row per passage of the batch, run exits non-zero
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd

from config import Config, short_ref
from llm import LLM, BudgetExceeded, CallFailed
from quotes import is_fragment, verified
from templates import prompt, render, schema, split_static

CLAIM_COLUMNS = [
    "claim_id", "docket_id", "letter_id", "passage_id", "campaign_id", "section_ref",
    "section_source", "quote", "quote_verified", "quote_source", "stance", "ask", "evidence_type",
    "needs_review", "linker_rank", "prompt_sha1", "claim_index", "model_section_ref",
]  # fmt: skip


@dataclass
class Batch:
    section_ref: str
    index: int
    passages: pd.DataFrame  # rows of inputs.select()

    @property
    def tag(self) -> str:
        return f"extract_{short_ref(self.section_ref)}_{self.index:03d}"

    @property
    def requote_tag(self) -> str:
        return f"requote_{short_ref(self.section_ref)}_{self.index:03d}"


@dataclass
class BatchResult:
    claims: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def batches(selected: pd.DataFrame, size: int) -> list[Batch]:
    out = []
    for ref, group in selected.groupby("primary_ref", sort=True):
        group = group.sort_values("passage_id", kind="stable")
        for i in range(0, len(group), size):
            out.append(Batch(ref, i // size, group.iloc[i : i + size]))
    return out


def prompt_sha1() -> str:
    return hashlib.sha1((prompt("system") + "\n" + prompt("extract")).encode()).hexdigest()


def render_passages(rows: pd.DataFrame) -> str:
    return "\n".join(f"=== PASSAGE {r.passage_id} ===\n{r.text}\n" for r in rows.itertuples())


def partition_check(expected: list[str], out: dict) -> tuple[list[str], list[str], list[str]]:
    """Missing, duplicated and unknown passage ids in an extractor answer."""
    seen: dict[str, int] = {}
    for p in out.get("passages", []):
        seen[p["passage_id"]] = seen.get(p["passage_id"], 0) + 1
    missing = [i for i in expected if i not in seen]
    dup = [i for i, n in seen.items() if n > 1]
    unknown = [i for i in seen if i not in set(expected)]
    return missing, dup, unknown


def resolve_section(model_ref: str, candidates: list[str]) -> tuple[str, str | None]:
    """The claim's section and a review reason when the model and the citations disagree."""
    primary = candidates[0]
    if not model_ref or model_ref.strip().lower() == "none":
        return primary, "no_section"
    by_short = {short_ref(c): c for c in candidates}
    m = model_ref.strip()
    if m in candidates:
        return m, None
    if short_ref(m) in by_short:
        return by_short[short_ref(m)], None
    return primary, "section_disagrees"


class Extractor:
    def __init__(
        self, cfg: Config, llm: LLM, ctx: dict[str, dict], letters: pd.DataFrame, docket: str
    ):
        self.cfg = cfg
        self.llm = llm
        self.ctx = ctx
        self.docket = docket
        self.letter_text = dict(zip(letters["letter_id"], letters["text"], strict=True))
        self.system = prompt("system")
        self.static_tpl, self.user_tpl = split_static(prompt("extract"), "Candidate sections")
        self.sha1 = prompt_sha1()
        self.budget_hit = threading.Event()

    # -- prompt --------------------------------------------------------------------------------

    def static(self, section_ref: str) -> str:
        c = self.ctx.get(section_ref, {})
        return render(
            self.static_tpl,
            section_ref=short_ref(section_ref),
            heading=c.get("heading", ""),
            rule_context=c.get("context") or "(not available)",
        )

    def user(self, batch: Batch) -> str:
        cands = sorted({c for cs in batch.passages["candidates"] for c in cs})
        return render(
            self.user_tpl,
            candidates=", ".join(cands),
            passages=render_passages(batch.passages),
        )

    # -- one batch -------------------------------------------------------------------------------

    def run_batch(self, batch: Batch) -> BatchResult:
        res = BatchResult(stats={"calls": 0, "requotes": 0, "fix_calls": 0})
        ids = list(batch.passages["passage_id"])
        if self.budget_hit.is_set():
            res.review += [
                {"claim_id": None, "issue_id": None, "reason": "llm_failed",
                 "detail": {"passage_id": i, "tag": batch.tag, "error": "budget exceeded"}}
                for i in ids
            ]  # fmt: skip
            res.stats["failed"] = True
            return res
        static, user = self.static(batch.section_ref), self.user(batch)
        try:
            out = self.llm.call(batch.tag, "extract", self.system, static, user, schema("extract"))
            missing, dup, unknown = partition_check(ids, out)
            if missing or dup or unknown:
                res.stats["fix_calls"] = 1
                fb = (
                    f"{user}\n\nYOUR PREVIOUS ANSWER DID NOT COVER EVERY PASSAGE EXACTLY ONCE. "
                    f"Previous answer:\n{json.dumps(out)}\n\nProblems found by script: missing "
                    f"passage ids {missing}; ids returned more than once {dup}; unknown ids "
                    f"{unknown}. Return the full corrected JSON: every one of the {len(ids)} "
                    "passage ids exactly once."
                )
                out = self.llm.call(
                    f"{batch.tag}_fix1", "extract", self.system, static, fb, schema("extract")
                )
                missing, dup, unknown = partition_check(ids, out)
        except BudgetExceeded:
            self.budget_hit.set()
            res.review += [
                {"claim_id": None, "issue_id": None, "reason": "llm_failed",
                 "detail": {"passage_id": i, "tag": batch.tag, "error": "budget exceeded"}}
                for i in ids
            ]  # fmt: skip
            res.stats["failed"] = True
            return res
        except CallFailed as e:
            res.review += [
                {"claim_id": None, "issue_id": None, "reason": "llm_failed",
                 "detail": {"passage_id": i, "tag": batch.tag, "error": str(e)[:300]}}
                for i in ids
            ]  # fmt: skip
            res.stats["failed"] = True
            return res

        for i in missing:
            res.review.append(
                {"claim_id": None, "issue_id": None, "reason": "missing_from_output",
                 "detail": {"passage_id": i, "tag": batch.tag}}
            )  # fmt: skip
        by_id = {r.passage_id: r for r in batch.passages.itertuples()}
        seen: set[str] = set()
        claims: list[dict] = []
        for p in out["passages"]:
            pid = p["passage_id"]
            if pid not in by_id or pid in seen:
                continue  # unknown id, or a duplicate: the first answer stands
            seen.add(pid)
            row = by_id[pid]
            for k, c in enumerate(p["claims"]):
                section, reason = resolve_section(c.get("section_ref", ""), list(row.candidates))
                claims.append(
                    {
                        "docket_id": self.docket,
                        "letter_id": row.letter_id,
                        "passage_id": pid,
                        "campaign_id": row.campaign_id,
                        "section_ref": section,
                        "section_source": row.section_source,
                        "quote": c.get("quote"),
                        "quote_verified": False,
                        "quote_source": "none",
                        "stance": c["stance"],
                        "ask": c.get("ask") or None,
                        "evidence_type": list(c.get("evidence_type") or []),
                        "needs_review": False,
                        "linker_rank": None,
                        "prompt_sha1": self.sha1,
                        "claim_index": k,
                        "model_section_ref": c.get("section_ref"),
                        "_section_reason": reason,
                        "_text": row.text,
                    }
                )
        self.check_quotes(batch, claims, res)
        res.claims = claims
        return res

    # -- quotes ------------------------------------------------------------------------------------

    def verify(self, claim: dict) -> bool:
        if verified(claim["quote"], claim["_text"]):
            claim["quote_verified"], claim["quote_source"] = True, "passage"
            return True
        letter = self.letter_text.get(claim["letter_id"])
        if isinstance(letter, str) and verified(claim["quote"], letter):
            claim["quote_verified"], claim["quote_source"] = True, "letter"
            return True
        return False

    def check_quotes(self, batch: Batch, claims: list[dict], res: BatchResult) -> None:
        failing = [c for c in claims if not self.verify(c)]
        res.stats["quotes_first_pass"] = len(claims) - len(failing)
        res.stats["claims_first_pass"] = len(claims)
        if failing and not self.budget_hit.is_set():
            res.stats["requotes"] = 1
            blocks = []
            for c in failing:
                blocks.append(
                    f"--- passage_id: {c['passage_id']}  index: {c['claim_index']} ---\n"
                    f"claim ask: {c['ask']}\nprevious quote: {c['quote']}\n"
                    f"PASSAGE TEXT:\n{c['_text']}\n"
                )
            user = render(prompt("requote"), failed_claims_with_passage_text="\n".join(blocks))
            try:
                out = self.llm.call(
                    batch.requote_tag, "requote", self.system, self.static(batch.section_ref),
                    user, schema("requote"),
                )  # fmt: skip
                fixes = {(f["passage_id"], f["index"]): f["quote"] for f in out["claims"]}
                for c in failing:
                    new = fixes.get((c["passage_id"], c["claim_index"]))
                    if new:
                        c["quote"] = new
                        self.verify(c)
            except BudgetExceeded:
                self.budget_hit.set()
            except CallFailed as e:
                res.review.append(
                    {"claim_id": None, "issue_id": None, "reason": "llm_failed",
                     "detail": {"tag": batch.requote_tag, "error": str(e)[:300]}}
                )  # fmt: skip
        kept = []
        for c in claims:
            if not c["quote_verified"]:
                res.review.append(
                    {"claim_id": None, "issue_id": None, "reason": "quote_failed",
                     "detail": {"passage_id": c["passage_id"], "claim_index": c["claim_index"],
                                "quote": c["quote"], "ask": c["ask"]}}
                )  # fmt: skip
                continue
            if is_fragment(c["quote"]):
                c["needs_review"] = True
                c["_fragment"] = True
            kept.append(c)
        res.stats["quotes_final"] = len(kept)
        claims[:] = kept


def run(
    selected: pd.DataFrame, letters: pd.DataFrame, ctx: dict[str, dict], llm: LLM, cfg: Config,
    docket: str,
) -> tuple[pd.DataFrame, list[dict], dict]:  # fmt: skip
    """claims.parquet rows, review rows and stats for every selected passage."""
    ex = Extractor(cfg, llm, ctx, letters, docket)
    work = batches(selected, cfg.batch)
    with ThreadPoolExecutor(max(1, cfg.threads)) as pool:
        results = list(pool.map(ex.run_batch, work))

    claims = [c for r in results for c in r.claims]
    claims.sort(key=lambda c: (c["section_ref"], c["passage_id"], c["claim_index"]))
    review = [row for r in results for row in r.review]
    for n, c in enumerate(claims, start=1):
        c["claim_id"] = f"C{n:06d}"
        if c.pop("_fragment", False):
            review.append(
                {"claim_id": c["claim_id"], "issue_id": None, "reason": "quote_fragment",
                 "detail": {"quote": c["quote"]}}
            )  # fmt: skip
        reason = c.pop("_section_reason")
        if reason:
            review.append(
                {"claim_id": c["claim_id"], "issue_id": None, "reason": reason,
                 "detail": {"model_section_ref": c["model_section_ref"],
                            "kept": c["section_ref"]}}
            )  # fmt: skip
        c.pop("_text")
    df = pd.DataFrame(claims, columns=CLAIM_COLUMNS)
    df["linker_rank"] = df["linker_rank"].astype("Int64")
    stats = {
        "passages_in": int(len(selected)),
        "passages_extracted": int(len(selected) - sum(
            1 for row in review if row["reason"] in ("llm_failed", "missing_from_output")
            and row["detail"].get("passage_id") is not None
        )),
        "batches": len(work),
        "batches_failed": sum(1 for r in results if r.stats.get("failed")),
        "claims_first_pass": sum(r.stats.get("claims_first_pass", 0) for r in results),
        "quotes_verified_first_pass": sum(r.stats.get("quotes_first_pass", 0) for r in results),
        "quotes_verified_final": sum(r.stats.get("quotes_final", 0) for r in results),
        "requote_calls": sum(r.stats.get("requotes", 0) for r in results),
        "fix_calls": sum(r.stats.get("fix_calls", 0) for r in results),
        "budget_exceeded": ex.budget_hit.is_set(),
        "prompt_sha1": ex.sha1,
    }  # fmt: skip
    stats["claims_dropped"] = stats["claims_first_pass"] - stats["quotes_verified_final"]
    return df, review, stats
