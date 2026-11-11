"""The outcome graph in memory, with the lookups both the web API and the agent's MCP tools use.

Everything returned carries node ids (`topic:9.7`, `ask:9.7:2`, `org:14`, `sec:141.84`, `ch:9`), so
the page can highlight whatever the agent is reading.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DOCKET = os.environ.get("DOCKET", "EPA-HQ-OW-2022-0801")
VERDICT_ORDER = ["adopted", "partly_adopted", "declined", "clarified", "already_required"]


def _outcome(verdict: str, side: str) -> str:
    if verdict == "partly_adopted":
        return "partly"
    if verdict == "adopted":
        return "won" if side == "for" else "lost"
    if verdict == "declined":
        return "lost" if side == "for" else "won"
    return "no_change"


_SUFFIX = re.compile(r"\b(inc|llc|co|company|corp|corporation|ltd|the)\b")
_NOT_AN_ORG = re.compile(r"^(anonymous|unknown|individual|private citizen|none|n/?a)\b", re.I)


def org_key(label: str) -> str:
    """One key per organization across rules and spellings: "American Water Works Association (AWWA)"
    and "American Water Works Association" are the same commenter. Empty for people and placeholders."""
    if not label or _NOT_AN_ORG.match(label.strip()):
        return ""
    s = re.sub(r"\(([^)]*)\)", " ", label).lower().replace("&", " and ")
    s = _SUFFIX.sub(" ", re.sub(r"[^a-z0-9 ]", " ", s))
    return "-".join(s.split())


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s.lower())


_AVAILABLE: dict[tuple, dict] = {}


def available(data_root: Path | None = None) -> dict[str, dict]:
    """Every built rulemaking: docket id -> its meta (title, short name, dates) and headline stats.

    Each graph.json is several MB and this is called on most requests, so the parsed result is kept
    until a graph file is added, removed or rewritten (checked by a cheap stat of each file).
    """
    base = (data_root or ROOT / "data/derived") / "outcomes"
    graphs = sorted(base.glob("*/graph.json"))
    key = (str(base), tuple((str(g), g.stat().st_mtime_ns) for g in graphs))
    if key in _AVAILABLE:
        return dict(_AVAILABLE[key])
    out = {}
    for g in graphs:
        with g.open() as f:
            stats = json.load(f)["stats"]
        meta = stats.get("meta") or {"title": g.parent.name, "short": g.parent.name}
        out[g.parent.name] = {**meta, "docket": g.parent.name, "asks": stats.get("asks"),
                              "comments": stats.get("comments"), "verdicts": stats.get("verdicts"),
                              "changed": stats.get("asks_with_rule_change")}  # fmt: skip
    _AVAILABLE.clear()
    _AVAILABLE[key] = out
    return dict(out)


class Store:
    def __init__(self, docket: str = DOCKET, data_root: Path | None = None):
        base = data_root or ROOT / "data/derived"
        self.docket = docket
        self.dir = base / f"outcomes/{docket}"
        g = json.loads((self.dir / "graph.json").read_text())
        self.stats = g["stats"]
        self.meta = self.stats.get("meta") or {"title": docket, "short": docket}
        self.short = self.meta.get("short") or docket
        # form letters are their own group, not "advocacy": one campaign is thousands of copies of one letter
        for n in g["nodes"]:
            if n["kind"] == "org" and re.match(r"mass comment campaign", n.get("label", ""), re.I):
                n["stakeholder"] = "campaign"
        for n in g["nodes"]:  # organizations get a scorecard page; people and campaigns do not
            if n["kind"] == "org" and n.get("stakeholder") not in ("individual", "campaign") and org_key(n["label"]):
                n["slug"] = org_key(n["label"])
        sh: dict[str, int] = defaultdict(int)
        for n in g["nodes"]:
            if n["kind"] == "org":
                sh[n.get("stakeholder") or "unknown"] += 1
        if self.stats.get("stakeholders"):
            self.stats["stakeholders"] = dict(sh)
        self.graph_json = json.dumps(g, ensure_ascii=False, separators=(",", ":")).encode()
        self.nodes: dict[str, dict] = {n["id"]: n for n in g["nodes"]}
        self.edges: list[dict] = g["edges"]
        self.details: dict[str, dict] = json.loads((self.dir / "details.json").read_text())
        cites = self.dir / "cites.json"  # page and paragraph of each EPA quote (jobs/cite.py)
        self.cites: dict[str, dict] = json.loads(cites.read_text()) if cites.exists() else {}
        self.adj: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for e in self.edges:
            self.adj[e["source"]].append((e["target"], e))
            self.adj[e["target"]].append((e["source"], e))
        self.entries = pd.read_parquet(base / f"responses/{docket}/entries.parquet")
        self.entries["organization"] = self.entries["organization"].fillna("Unknown").str.strip()
        self.org_by_name = {n["label"]: n["id"] for n in self.nodes.values() if n["kind"] == "org"}

    # ---------- helpers
    def brief(self, nid: str) -> dict:
        n = self.nodes[nid]
        out = {"id": nid, "kind": n["kind"], "label": n["label"]}
        for k in (
            "verdict",
            "code",
            "comments",
            "stakeholder",
            "title",
            "changed",
            "record",
            "for",
            "against",
        ):
            if k in n and n[k] not in (None, {}, ""):
                out[k] = n[k]
        return out

    def neighbors(self, nid: str, kind: str | None = None, limit: int = 50) -> list[dict]:
        seen, out = set(), []
        items = sorted(self.adj.get(nid, []), key=lambda x: -x[1]["weight"])
        for other, e in items:
            if other in seen or (kind and self.nodes[other]["kind"] != kind):
                continue
            seen.add(other)
            b = self.brief(other)
            b["edge"] = e["kind"]
            b["weight"] = e["weight"]
            out.append(b)
            if len(out) >= limit:
                break
        return out

    # ---------- search
    @cached_property
    def _index(self) -> tuple[list[str], list[Counter]]:
        ids, docs = [], []
        for nid, n in self.nodes.items():
            text = n["label"] + " " + (n.get("title") or "") + " " + (n.get("code") or "")
            if n["kind"] == "ask":
                text += " " + (self.details[nid].get("final_rule_change") or "")
            ids.append(nid)
            docs.append(Counter(_tok(text)))
        return ids, docs

    @cached_property
    def _df(self) -> Counter:
        df = Counter()
        for d in self._index[1]:
            df.update(d.keys())
        return df

    def search(self, query: str, kind: str | None = None, limit: int = 12) -> list[dict]:
        q = _tok(query)
        ids, docs = self._index
        n = len(ids)
        scores = []
        for nid, d in zip(ids, docs):
            if kind and self.nodes[nid]["kind"] != kind:
                continue
            s = sum(np.log(1 + n / (1 + self._df[t])) for t in q if t in d)
            if s > 0:
                label = self.nodes[nid]["label"].lower()
                if query.lower() in label:
                    s += 5
                if self.nodes[nid]["kind"] == "org":
                    s += 0.1 * np.log1p(self.nodes[nid].get("comments", 0))
                scores.append((s, nid))
        scores.sort(reverse=True)
        return [self.brief(nid) for _, nid in scores[:limit]]

    @cached_property
    def _embedder(self):
        from fastembed import TextEmbedding

        return TextEmbedding("BAAI/bge-small-en-v1.5")

    @cached_property
    def _excerpt_vecs(self) -> tuple[np.ndarray, pd.DataFrame]:
        if not (self.dir / "excerpt_vec.npy").exists():  # a rule whose document quotes no comments
            return np.zeros((0, 384), np.float32), self.entries.iloc[:0].assign(entry_id=[])
        v = np.load(self.dir / "excerpt_vec.npy").astype(np.float32)
        ids = pd.read_parquet(self.dir / "excerpt_vec_ids.parquet")
        meta = ids.merge(self.entries, on="entry_id", how="left")
        return v, meta

    def search_comments(
        self, query: str, organization: str | None = None, topic: str | None = None,
        stakeholder: str | None = None, limit: int = 8,
    ) -> list[dict]:  # fmt: skip
        """Semantic search over the comment excerpts EPA quoted."""
        v, meta = self._excerpt_vecs
        qv = next(iter(self._embedder.embed(
            ["Represent this sentence for searching relevant passages: " + query]
        )))  # fmt: skip
        qv = qv / np.linalg.norm(qv)
        sims = v @ qv
        mask = np.ones(len(meta), bool)
        if organization:
            mask &= (
                meta["organization"].str.contains(organization, case=False, regex=False).to_numpy()
            )
        if topic:
            code = topic.replace("topic:", "")
            mask &= (meta["code"] == code).to_numpy()
        if stakeholder:
            kinds = meta["organization"].map(
                lambda o: self.nodes.get(self.org_by_name.get(o, ""), {}).get("stakeholder")
            )
            mask &= (kinds == stakeholder).to_numpy()
        sims = np.where(mask, sims, -1)
        out = []
        for i in np.argsort(-sims)[:limit]:
            if sims[i] < 0:
                break
            r = meta.iloc[i]
            out.append({
                "org": self.org_by_name.get(r.organization), "organization": r.organization,
                "topic": f"topic:{r.code}", "topic_title": self.nodes[f"topic:{r.code}"]["label"],
                "record_id": r.record_id, "excerpt": str(r.excerpt)[:700],
                "epa_response": str(r.response)[:500], "similarity": round(float(sims[i]), 3),
            })  # fmt: skip
        return out

    # ---------- node detail
    def node(self, nid: str, offset: int = 0, max_chars: int = 6000) -> dict:
        if nid not in self.nodes:
            hits = self.search(nid, limit=1)
            if not hits:
                return {"error": f"no node {nid}"}
            nid = hits[0]["id"]
        n = dict(self.nodes[nid])
        d = self.details.get(nid, {})
        out = {"node": n}
        if n["kind"] == "topic":
            s = d.get("summary") or ""
            out["epa_summary"] = s[offset : offset + max_chars]
            out["summary_chars"] = len(s)
            out["asks"] = [
                {**a, "final_rule_change": self.details[a["id"]].get("final_rule_change")}
                for a in self.neighbors(nid, "ask", 60)
            ]
            out["top_commenters"] = self.neighbors(nid, "org", 15)
            out["sections"] = self.neighbors(nid, "section", 10)
        elif n["kind"] == "ask":
            out.update(d)
            out["topic"] = self.neighbors(nid, "topic", 1)
            out["sections"] = self.neighbors(nid, "section", 10)
            orgs = self.neighbors(nid, "org", 200)
            out["supporters"] = [o for o in orgs if o["edge"] == "supports"][:20]
            out["opponents"] = [o for o in orgs if o["edge"] == "opposes"][:20]
            out["excerpts_for"] = n.get("for", 0)
            out["excerpts_against"] = n.get("against", 0)
            if nid in self.cites:
                out["cite"] = self.cites[nid] | {"pdf": (self.dir / "rtc.pdf").exists()}
        elif n["kind"] == "org":
            ents = d.get("entries", [])
            out["record"] = d.get("record", {})
            out["topics"] = self.neighbors(nid, "topic", 25)
            every = [
                {**a, "side": "for" if a["edge"] == "supports" else "against",
                 "outcome": _outcome(a["verdict"], "for" if a["edge"] == "supports" else "against")}
                for a in self.neighbors(nid, "ask", 10_000)
            ]  # fmt: skip
            out["asks"] = every[:40]
            out["ask_count"] = len(every)
            # the record in asks, the unit people quote; the excerpt-level record stays as "record"
            out["ask_record"] = {k: sum(a["outcome"] == k for a in every) for k in ("won", "partly", "lost", "no_change")}
            out["excerpts"] = [
                {
                    **e,
                    "excerpt": (e["excerpt"] or "")[:400],
                    "response": (e["response"] or "")[:300],
                }
                for e in ents[offset : offset + 12]
            ]
            out["excerpt_count"] = len(ents)
        elif n["kind"] == "section":
            diff = d.get("diff", [])
            out["changes"] = diff[offset : offset + 15]
            out["change_count"] = len(diff)
            out["topics"] = self.neighbors(nid, "topic", 20)
            out["asks"] = self.neighbors(nid, "ask", 30)
        elif n["kind"] == "chapter":
            out["topics"] = self.neighbors(nid, "topic", 40)
        return out

    # ---------- roll-ups
    def org_record(self, name: str) -> dict:
        nid = self.org_by_name.get(name)
        if not nid:
            hits = self.search(name, kind="org", limit=1)
            if not hits:
                return {"error": f"no organization like {name!r}"}
            nid = hits[0]["id"]
        n = self.nodes[nid]
        asks = [
            {**a, "side": "for" if a["edge"] == "supports" else "against",
             "outcome": _outcome(a["verdict"], "for" if a["edge"] == "supports" else "against")}
            for a in self.neighbors(nid, "ask", 200)
        ]  # fmt: skip
        return {
            "org": self.brief(nid),
            "comments_quoted_by_epa": n["comments"],
            "record_by_excerpt": n.get("record", {}),
            "asks": asks[:40],
            "topics": self.neighbors(nid, "topic", 30),
            "how_to_read": "won = EPA adopted what they asked for, or declined what they opposed. "
            "no_change = EPA clarified or said it was already required.",
        }

    def compare_stakeholders(self, scope: str | None = None) -> dict:
        """Did each stakeholder group get its way, overall or in one topic or chapter."""
        codes = None
        if scope:
            s = scope.replace("topic:", "").replace("ch:", "")
            codes = {n["code"] for n in self.nodes.values()
                     if n["kind"] == "topic" and (n["code"] == s or n["chapter"] == s)}  # fmt: skip
        table: dict[str, Counter] = defaultdict(Counter)
        for e in self.edges:
            if e["kind"] not in ("supports", "opposes"):
                continue
            ask = self.nodes[e["target"]]
            if codes is not None and ask["code"] not in codes:
                continue
            kind = self.nodes[e["source"]]["stakeholder"]
            side = "for" if e["kind"] == "supports" else "against"
            table[kind][_outcome(ask["verdict"], side)] += e["weight"]
        rows = []
        for kind, c in table.items():
            decided = c["won"] + c["partly"] + c["lost"]
            rows.append({"stakeholder": kind, "excerpts": int(sum(c.values())),
                         "won": int(c["won"]), "partly": int(c["partly"]), "lost": int(c["lost"]),
                         "no_change": int(c["no_change"]),
                         "won_share_of_decided": round((c["won"] + 0.5 * c["partly"]) / decided, 3)
                         if decided else None})  # fmt: skip
        rows.sort(key=lambda r: -r["excerpts"])
        return {"scope": scope or "whole rule", "rows": rows,
                "how_to_read": "Each excerpt EPA quoted counts once. won_share_of_decided counts "
                               "partly as half, over excerpts where EPA adopted or declined."}  # fmt: skip

    def overview(self) -> dict:
        chapters = []
        for n in self.nodes.values():
            if n["kind"] != "chapter":
                continue
            topics = self.neighbors(n["id"], "topic", 100)
            v = Counter()
            for t in topics:
                v.update(self.nodes[t["id"]].get("verdicts", {}))
            chapters.append({"id": n["id"], "label": n["label"], "topics": len(topics),
                             "comments": sum(t.get("comments", 0) for t in topics),
                             "verdicts": dict(v)})  # fmt: skip
        chapters.sort(key=lambda c: -c["comments"])
        return {"stats": self.stats, "chapters": chapters}
