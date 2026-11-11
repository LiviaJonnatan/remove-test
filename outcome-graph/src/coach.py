"""Comment coach: read a draft comment against the outcome record and suggest edits.

Retrieval is done in code, so every piece of evidence is a real node:
  1. split the draft into sentences;
  2. for each sentence, find the closest asks two ways: the ask's own text, and the comment
     excerpts EPA quoted that a model already tied to that ask (assign/*.json);
  3. hand the model the draft plus those candidate asks with EPA's verdict, EPA's own sentence and
     what changed in the final rule.
One model call then groups the draft into points and writes advice. Any ask id it cites that is
not in the candidate set is dropped, and the verdict counts shown on the page are computed here,
not by the model.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from functools import cached_property

import numpy as np
import pandas as pd

from store import Store

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
OUTLOOKS = ("likely_adopted", "mixed", "likely_declined", "already_in_rule", "new")

SYSTEM = """You coach someone writing a public comment on an EPA drinking water rule. You get \
their draft and a set of past asks from EPA's Lead and Copper Rule Improvements record: what \
commenters asked for, EPA's verdict, EPA's own sentence, and what changed in the final rule.

Do this:
- Split the draft into the distinct things it asks EPA to do (points). Ignore greetings and \
background.
- For each point, pick the past asks that make the same or the opposite request, ONLY from the \
candidates given, by id. Pick 1 to 5. If none really match, use an empty list and outlook "new".
- outlook: likely_adopted, mixed, likely_declined, or new, judged from how EPA answered the \
matching asks.
- why: one or two sentences on EPA's reasoning for those asks. Quote EPA's sentence (short, \
exact, inside curly quotes “ like this ”, never straight double quotes) when it explains the \
decision.
- advice: 2 or 3 concrete edits that would make this point stronger, based on what the adopted \
asks did that the declined ones did not (a specific number or date, a named CFR section, a \
feasible alternative, data on cost or health, scope limited to what EPA has authority over). \
When EPA said something is already in the rule, say so and suggest pointing to it or asking for \
something narrower.
- rewrite: the point rewritten as one to three sentences the person could paste in. Keep their \
position. Do not invent facts or numbers; use a placeholder like [your data] where evidence is \
needed.
- overall: two sentences on the draft as a whole.

Never put a straight double quote inside a JSON string value. The reply must parse with json.loads.

Style: plain, short sentences. No em dashes. Do not state counts of asks (the page computes them).

Reply with JSON only:
{"overall": "...", "points": [{"draft": "the exact draft sentence(s) this point covers", \
"ask": "what they are asking, under 15 words", "similar": ["ask:9.6:0"], \
"outlook": "likely_declined", "why": "...", "advice": ["...", "..."], "rewrite": "..."}]}"""


AGENT_SYSTEM = """You coach someone writing a public comment on an EPA drinking water rule: \
{target}. You have tools over EPA's record for {rules}: for each, every ask commenters made, \
EPA's verdict and own sentence, the comments EPA quoted, and the final rule's regulatory text. \
Past asks from every rule count as evidence of how EPA reasons; rule text is checked for {short} \
only.

Work like an analyst, one point at a time:
1. Split the draft into the distinct things it asks EPA to do. Ignore greetings and background.
2. For each point, call find_similar_asks with the point in your own words. If the best match is \
below about 0.75, try once more with different wording (the regulatory term, or the opposite \
position).
3. For each point, call search_rule_text to check whether the final rule already does it. If a \
paragraph already covers it, that is the most useful thing you can tell them.
4. If the matching asks got different verdicts, call get_node on one adopted and one declined ask \
to see what separated them.
5. Optional: search_comments to find what a successful commenter argued, when it would help the \
advice.
Keep it to about 12 tool calls in total. Do not call overview.

Then reply with ONLY a JSON object, no prose before or after:
{"overall": "two sentences on the draft as a whole",
 "points": [{
   "draft": "the exact draft sentence(s) this point covers",
   "ask": "what they ask, under 15 words",
   "similar": ["ask ids exactly as a tool returned them (keep any rule prefix), closest first, 1 to 5"],
   "outlook": "likely_adopted | mixed | likely_declined | already_in_rule | new",
   "in_rule": {"section": "141.84", "quote": "words copied exactly from a final-rule paragraph \
search_rule_text returned"} or null,
   "why": "one or two sentences on EPA's reasoning, in your words (the page shows EPA's own sentence next to it, so do not quote EPA)",
   "advice": ["2 or 3 concrete edits, based on what adopted asks did that declined ones did not"],
   "rewrite": "the point rewritten as 1 to 3 sentences they could paste in"
 }]}

Rules: use outlook already_in_rule only with an in_rule quote. Cite only ids a tool returned. \
Never invent facts or numbers; write [your data] where evidence is needed. Keep their position. \
Never write template placeholders like {{...}}. Never put a straight double quote inside a JSON \
string value. Plain, short sentences, no em \
dashes. Do not state counts of asks (the page computes them)."""


def agent_system(target: Store, all_meta: dict[str, dict]) -> str:
    rules = "; ".join(f"{m['title']} ({m['short']}, final {m['final']})" for m in all_meta.values())
    return AGENT_SYSTEM.replace("{target}", f"{target.meta['title']} (final {target.meta.get('final')})") \
        .replace("{rules}", rules).replace("{short}", target.short)


def parse_reply(text: str) -> dict | None:
    """Pull the JSON object out of the model's reply; None if it does not parse."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) and isinstance(out.get("points"), list) else None


class Index:
    """Search structures for one rulemaking, each cached on disk next to its graph."""

    def __init__(self, store: Store):
        self.s = store

    @cached_property
    def excerpt_ask(self) -> dict[str, tuple[str, str]]:
        """entry_id -> (ask id, side), from the model's excerpt-to-ask matching."""
        out = {}
        for p in sorted((self.s.dir / "assign").glob("*.json")):
            for r in json.loads(p.read_text())["rows"]:
                if r.get("ask") and r["ask"] in self.s.nodes:
                    out[r["entry_id"]] = (r["ask"], r.get("side") or "for")
        return out

    @cached_property
    def ask_vecs(self) -> tuple[np.ndarray, list[str]]:
        ids = [k for k, n in self.s.nodes.items() if n["kind"] == "ask"]
        return self.cached("ask_vec", [self.s.nodes[i]["label"] for i in ids]), ids

    def cached(self, name: str, texts: list[str]) -> np.ndarray:
        """Embeddings saved next to graph.json, keyed by a hash of the texts, so each new tool
        process (one per coach run) does not re-embed everything."""
        import hashlib

        key = hashlib.sha1("\n".join(texts).encode()).hexdigest()[:12]
        path = self.s.dir / f"{name}_{key}.npy"
        if path.exists():
            return np.load(path)
        v = np.array(list(self.s._embedder.embed(texts, batch_size=64)), dtype=np.float32)
        v = v / np.linalg.norm(v, axis=1, keepdims=True)
        for old in self.s.dir.glob(f"{name}_*.npy"):
            old.unlink()
        np.save(path, v)
        return v

    @cached_property
    def rule_paras(self) -> tuple[pd.DataFrame, np.ndarray]:
        """Every paragraph of the final rule (and dropped proposal text), embedded once."""
        p = self.s.dir.parents[1] / "responses" / self.s.dir.name / "rule_diff.parquet"
        d = pd.read_parquet(p)
        d["text"] = d["final"].where(d["final"].notna(), d["proposed"])
        d["which"] = np.where(d["final"].notna(), "final", "proposed_only")
        d = d[d["text"].notna() & (d["text"].str.len() > 30)].reset_index(drop=True)
        return d, self.cached("rule_vec", d["text"].str[:1200].tolist())

    def scores(self, q: np.ndarray, limit: int) -> dict[str, float]:
        """Ask id -> match score, from the ask's wording and from comments tied to it."""
        av, aids = self.ask_vecs
        score: dict[str, float] = defaultdict(float)
        for j in np.argsort(-(av @ q))[: limit * 2]:
            score[aids[j]] = max(score[aids[j]], float(av[j] @ q))
        ev, meta = self.s._excerpt_vecs
        if len(ev):
            entry_ids = meta["entry_id"].tolist()
            sims = ev @ q
            for j in np.argsort(-sims)[:60]:
                hit = self.excerpt_ask.get(entry_ids[j])
                if hit:
                    score[hit[0]] = max(score[hit[0]], float(sims[j]) - 0.02)
        return score


class Coach:
    """The coach's tools over every built rule. `target` is the rule being commented on: its rule
    text is what "already in the rule" is checked against, and its asks keep plain ids. Asks from
    other rules are qualified with that rule's short name, e.g. "LCRR/ask:6.2:3"."""

    def __init__(self, target: Store, others: list[Store] | None = None):
        self.s = target
        self.idx = {target.short: Index(target)} | {o.short: Index(o) for o in (others or []) if o.short != target.short}

    def qid(self, short: str, aid: str) -> str:
        return aid if short == self.s.short else f"{short}/{aid}"

    def resolve(self, qid: str) -> tuple[Store, str] | None:
        short, _, aid = qid.rpartition("/")
        ix = self.idx.get(short or self.s.short)
        return (ix.s, aid) if ix and aid in ix.s.nodes else None

    def _embed(self, texts: list[str]) -> np.ndarray:
        v = np.array(list(self.s._embedder.embed([QUERY_PREFIX + t for t in texts])), np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def evidence(self, qids: list[str]) -> list[dict]:
        out = []
        for q in qids:
            hit = self.resolve(q)
            if not hit:
                continue
            st, a = hit
            n, d = st.nodes[a], st.details.get(a, {})
            out.append({
                "id": q, "rule": f"{st.meta.get('title')} ({st.meta.get('final')})",
                "ask": n["label"], "topic": st.nodes[f"topic:{n['code']}"]["label"],
                "verdict": n["verdict"], "epa_said": d.get("quote"),
                "final_rule_change": None if d.get("final_rule_change") in (None, "None") else d["final_rule_change"],
                "excerpts_for": n.get("for", 0), "excerpts_against": n.get("against", 0),
            })  # fmt: skip
        return out

    def similar_asks(self, text: str, limit: int = 8, rule: str | None = None) -> list[dict]:
        """Past asks closest to one point, across every rule (or one, by short name)."""
        q = self._embed([text])[0]
        pooled = []
        for short, ix in self.idx.items():
            if rule and short.lower() != rule.lower():
                continue
            pooled += [(self.qid(short, a), sc) for a, sc in ix.scores(q, limit).items()]
        top = sorted(pooled, key=lambda x: -x[1])[:limit]
        out = self.evidence([a for a, _ in top])
        for e, (_, sc) in zip(out, top, strict=True):
            e["match"] = round(sc, 3)
        return out

    def search_rule(self, query: str, section: str | None = None, limit: int = 6) -> list[dict]:
        d, v = self.idx[self.s.short].rule_paras
        sims = v @ self._embed([query])[0]
        if section:
            sims = np.where(d["section"].str.startswith(section.replace("\u00a7", "").strip()), sims, -1)
        out = []
        for j in np.argsort(-sims)[:limit]:
            if sims[j] < 0:
                break
            r = d.iloc[j]
            out.append({
                "section": f"{r.section}{r.marker if isinstance(r.marker, str) else ''}",
                "section_title": r.title, "in": r.which,
                "change_from_proposal": r.op, "text": str(r.text)[:900],
                "match": round(float(sims[j]), 3),
            })  # fmt: skip
        return out

    def rule_has(self, quote: str) -> bool:
        """True if the quote appears word for word in the target rule's final text."""
        norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()  # noqa: E731
        q = norm(quote)
        if len(q) < 20:
            return False
        d, _ = self.idx[self.s.short].rule_paras
        return any(q in norm(t) for t in d.loc[d["which"] == "final", "text"])

    def _in_rule(self, x) -> dict | None:
        """Keep a rule citation only if its quote is in the final rule word for word."""
        if not isinstance(x, dict) or not x.get("quote"):
            return None
        q = str(x["quote"]).strip().strip("\u201c\u201d\"")
        return {"section": str(x.get("section", ""))[:40], "quote": q[:600]} if self.rule_has(q) else None

    def info(self, qid: str) -> dict:
        st, a = self.resolve(qid)
        n = st.nodes[a]
        return {"label": n["label"], "verdict": n["verdict"], "changed": bool(n.get("changed")),
                "rule": st.short, "local": st is self.s, "id": a,
                "epa_said": st.details.get(a, {}).get("quote")}  # fmt: skip

    def clean(self, raw: dict, allowed: set[str]) -> dict:
        """Keep only ids a tool returned; compute verdict counts here, not in the model."""
        points, used = [], set()
        for p in raw.get("points", []):
            sim = [a for a in p.get("similar", []) if a in allowed and self.resolve(a)][:5]
            used.update(sim)
            infos = [self.info(a) for a in sim]
            point = {
                "draft": str(p.get("draft", ""))[:600], "ask": str(p.get("ask", ""))[:160],
                "similar": sim, "mix": dict(Counter(i["verdict"] for i in infos)),
                "changed": sum(i["changed"] for i in infos),
                "outlook": p.get("outlook") if p.get("outlook") in OUTLOOKS else ("new" if not sim else "mixed"),
                "why": re.sub(r"[^.]*\{\{[^}]*\}\}\.?\s*", "", str(p.get("why", ""))).strip()[:700],
                "epa_said": next((i["epa_said"] for i in infos if i["epa_said"]), None),
                "epa_said_on": next((a for a, i in zip(sim, infos) if i["epa_said"]), None),
                "advice": [str(x)[:400] for x in p.get("advice", [])][:3],
                "rewrite": str(p.get("rewrite", ""))[:900],
                "in_rule": self._in_rule(p.get("in_rule")),
            }  # fmt: skip
            if point["outlook"] == "already_in_rule" and not point["in_rule"]:
                point["outlook"] = "mixed" if sim else "new"  # claim dropped: quote did not check out
            points.append(point)
        return {"overall": str(raw.get("overall", ""))[:600], "points": points,
                "asks": {a: self.info(a) for a in used}}  # fmt: skip
