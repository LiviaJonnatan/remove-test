"""Build the outcome graph for one docket from files earlier stages already wrote.

Inputs (all under data/derived):
  responses/<docket>/codes.parquet      EPA's 138 topics and its summary response for each
  responses/<docket>/entries.parquet    every comment EPA quoted: organization, topic, excerpt, answer
  responses/<docket>/rule_diff.parquet  proposed vs final regulatory text, paragraph by paragraph
  outcomes/<docket>/raw/<code>.json     asks and verdicts per topic (extract.py)

Output: outcomes/<docket>/graph.json (what the page draws) and details.json (what a click opens).

Node kinds: chapter, topic, ask, section, org. Edges:
  topic -> chapter    EPA's own numbering (9.7 sits in chapter 9)
  ask -> topic        the ask was read out of that topic's summary
  ask -> section      the ask's quote or row names that CFR section
  topic -> section    EPA's summary for the topic cites the section (weight = times cited)
  org -> topic        EPA quoted the organization under the topic (weight = excerpts)
  org -> ask          supports / opposes: a model read each excerpt next to the topic's asks

    uv run python src/build.py --docket EPA-HQ-OW-2022-0801
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

# One entry per rulemaking: how the page names it, and short chapter names from each response
# document's table of contents.
DOCKETS = {
    "EPA-HQ-OW-2022-0801": {
        "title": "Lead and Copper Rule Improvements", "short": "LCRI",
        "proposed": "Dec 2023", "final": "Oct 2024",
        "chapters": {
    "1": "General and compliance dates", "2": "Statutory basis", "3": "Process and guidance",
    "4": "Definitions", "5": "Corrosion control treatment", "6": "Distribution system assessment",
    "7": "Service line inventory", "8": "Replacement plan", "9": "Service line replacement",
    "10": "Small system flexibility", "11": "Public education", "12": "Consumer confidence reports",
    "13": "Public notification", "14": "Multiple action level exceedances",
    "15": "Tap sampling", "16": "Water quality parameters", "17": "Source water",
    "18": "Schools and child care", "19": "System reporting", "20": "State implementation",
    "21": "Costs and benefits", "22": "Environmental justice", "24": "Out of scope",
},
    },
    "EPA-HQ-OW-2017-0300": {
        "title": "Lead and Copper Rule Revisions", "short": "LCRR",
        "proposed": "Nov 2019", "final": "Jan 2021",
        "chapters": {
            "1": "General matters", "2": "Definitions", "3": "Lead trigger level",
            "4": "Corrosion control treatment", "5": "Service line inventory",
            "6": "Service line replacement", "7": "Small system flexibility",
            "8": "Public education", "9": "Tap sampling", "10": "Water quality parameters",
            "11": "Source water", "12": "Schools and child care", "13": "Find-and-fix",
            "14": "System reporting", "15": "State implementation", "16": "Economic analysis",
            "17": "Regulatory process", "18": "Statutory requirements", "19": "Other rule changes",
        },
    },
    "EPA-HQ-OW-2022-0114": {
        "title": "PFAS Drinking Water Standard", "short": "PFAS",
        "proposed": "Mar 2023", "final": "Apr 2024",
        "chapters": {
            "1": "General information", "2": "Background", "3": "Regulatory determinations",
            "4": "Health effects and MCLGs", "5": "Maximum contaminant levels", "6": "Occurrence",
            "7": "Analytical methods", "8": "Monitoring and compliance", "9": "Right-to-know",
            "10": "Treatment technologies", "11": "Implementation", "12": "Exemptions",
            "13": "Costs and benefits", "14": "Statutory reviews", "15": "Out of scope",
            "16": "Rule text", "17": "Comment period and timeline",
        },
    },
}  # fmt: skip

# Titles the document leaves blank, filled from the first sentence of EPA's text.
BLANK_TITLES = {
    "1.3": "Timely guidance",
    "11.4.3": "Notice of service line disturbance",
    "22.10": "Environmental justice analysis",
}

SECTION_RE = re.compile(r"§+\s*(14[12]\.\d+)")

STAKEHOLDERS = [  # first match wins; order matters
    ("federal", (r"senator|congress|representative\b|u\.s\. small business|advisory committee|"
                r"federal|\bepa region")),
    ("state", (r"department of (environment|health|public health|natural|environmental|agriculture)|"
              r"commission on environmental|environment department|water resources control board|"
              r"attorney general|state of |commonwealth of|groundwater protection|"
              r"\b(deq|dep|dph|dnr|wdnr|egle|nmed|tceq|mde|denr|danr)\b|drinking water program|"
              r"state (water|health|environmental|drinking)|division of environmental|environmental quality")),
    ("labor", r"\bunion\b|afl-cio|laborers|brotherhood|workers"),
    ("advocacy", (r"defense|kids|future|coalition|network|\bfund\b|foundation|naacp|campaign|"
                 r"alliance|center for|progress|voters|millennials|policy|lead-free|lead free|"
                 r"earthjustice|sierra|\bclean\b|justice|people'?s counsel|citizens|advocat|"
                 r"rivers|riverkeeper|league|action|elevate|environmental protection network|"
                 r"environmental working|public citizen|moms|parents|families|church|"
                 r"physicians|pediatric|nurses|public health (law|institute)|collaborative|latinos|"
                 r"women for|healthy environment|\(tendr\)")),
    ("trade", (r"association|\bawwa\b|\bamwa\b|\bnrwa\b|council|conference|federation|"
              r"institute|chamber|\baiha\b|society|\bnaco\b|counties \(")),
    ("utility", (r"water (works|district|system|department|authority|bureau|supply|company|"
                r"commission|utilit|resources authority|service)|utilities|sewer|"
                r"division of water|^aqua|water one|\bwater\b$|water co\b|\bwsc\b")),
    ("local", r"city of|county|town of|village|municipal|law department|mayor|borough|township"),
    ("industry", (r"\binc\b|llc|company|corporation|\bcorp\b|group|technolog|manufactur|consult|"
                 r"engineer|laborator|plumbing|blueconduit|\bltd\b|partners")),
    ("academic", r"universit|college|school of|academ|research"),
]  # fmt: skip
STAKEHOLDER_RE = [(k, re.compile(p, re.IGNORECASE)) for k, p in STAKEHOLDERS]


def stakeholder(org: str) -> str:
    if not org or org.strip().lower() in {"unknown", "anonymous", "anonymous public comment"}:
        return "unknown"
    clean = re.sub(r"\(.*?\)|\bet al\.?", "", org).strip(" ,.-")
    for kind, rx in STAKEHOLDER_RE:
        if rx.search(clean) or rx.search(org):
            return kind
    words = org.replace(",", " ").split()
    if 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words):
        return "individual"
    return "other"


def chapter_of(code: str) -> str:
    return code.split(".")[0]


def embed(texts: list[str]) -> np.ndarray:
    from fastembed import TextEmbedding

    m = TextEmbedding("BAAI/bge-small-en-v1.5")
    v = np.array(list(m.embed(texts, batch_size=64)), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


VERDICT_STACK = ["adopted", "partly_adopted", "already_required", "clarified", "declined"]


def layout(nodes: dict[str, dict], edges: list[dict]) -> dict:
    """Deterministic dot-ring layout.

    Each topic is one radial column, one dot per ask, stacked from the inside out by verdict
    (adopted first, declined last). Topics run clockwise from twelve o'clock in EPA's order, with a
    gap between chapters. Commenters and rule sections sit inside the ring (drawn only when in
    focus), at the mean angle of the topics they connect to.
    """
    asks_of = defaultdict(list)
    for n in nodes.values():
        if n["kind"] == "ask":
            asks_of[n["code"]].append(n)

    def code_key(c: str):
        return [int(x) for x in c.split(".")]

    topics = sorted(
        (n for n in nodes.values() if n["kind"] == "topic"), key=lambda n: code_key(n["code"])
    )
    chapters = list(dict.fromkeys(t["chapter"] for t in topics))
    CH_GAP = 2.4  # chapter gap, in columns
    H = 8  # dots per column; bigger topics get more columns, so the ring has an even height
    width = {t["id"]: max(1, math.ceil(len(asks_of[t["code"]]) / H)) for t in topics}
    slots = sum(width.values()) + CH_GAP * len(chapters)
    step = 2 * math.pi / slots
    DOT = 1.0  # radial spacing between dots in a column
    R0 = 1.18 * DOT / step  # inner radius: neighbouring columns one dot apart at the base
    angle_of: dict[str, float] = {}
    arcs = []
    pos = CH_GAP / 2
    for ch in chapters:
        first = pos
        for t in (t for t in topics if t["chapter"] == ch):
            k = width[t["id"]]
            ang = math.pi / 2 - (pos + (k - 1) / 2) * step
            angle_of[t["id"]] = ang
            t["x"], t["y"] = (R0 - 1.6) * math.cos(ang), (R0 - 1.6) * math.sin(ang)
            stack = sorted(
                asks_of[t["code"]],
                key=lambda a: (VERDICT_STACK.index(a["verdict"]), a["id"]),
            )
            for i, a in enumerate(stack):  # fill row by row, so verdicts form bands
                row, col = divmod(i, k)
                aa = math.pi / 2 - (pos + col) * step
                r = R0 + row * DOT
                a["x"], a["y"] = r * math.cos(aa), r * math.sin(aa)
            pos += k
        last = pos - 1
        a0, a1 = math.pi / 2 - first * step, math.pi / 2 - last * step
        mid = (a0 + a1) / 2
        n = nodes[f"ch:{ch}"]
        n["x"], n["y"] = (R0 - 3.2) * math.cos(mid), (R0 - 3.2) * math.sin(mid)
        arcs.append({"id": f"ch:{ch}", "a0": a0, "a1": a1, "mid": mid})
        pos += CH_GAP
    for n in nodes.values():
        if n["kind"] == "chapter" and "x" not in n:
            n["x"], n["y"] = 0.0, 0.0

    def mean_angle(pairs):
        if not pairs:
            return None
        sx = sum(w * math.sin(a) for a, w in pairs)
        sy = sum(w * math.cos(a) for a, w in pairs)
        return math.atan2(sx, sy), math.hypot(sx, sy) / sum(w for _, w in pairs)

    topic_of_ask = {n["id"]: f"topic:{n['code']}" for n in nodes.values() if n["kind"] == "ask"}
    links = defaultdict(list)
    for e in edges:
        for a, b in ((e["source"], e["target"]), (e["target"], e["source"])):
            tb = b if b in angle_of else topic_of_ask.get(b)
            if tb in angle_of and nodes[a]["kind"] in ("section", "org"):
                links[a].append((angle_of[tb], e["weight"]))
    groups = {"section": [], "org": []}
    for n in nodes.values():
        if n["kind"] not in groups:
            continue
        m = mean_angle(links[n["id"]])
        ang, conc = m if m else (0.0, 0.0)
        if n["kind"] == "section":
            r = R0 * (0.12 + 0.22 * conc)
        else:  # focused commenters sit near their topics, broad ones toward the middle
            r = R0 * (0.38 + 0.45 * conc)
        groups[n["kind"]].append([n, r * math.cos(ang), r * math.sin(ang)])
    for kind, size in (("section", 2.2), ("org", 1.1)):
        group = groups[kind]
        if not group:
            continue
        P = np.array([[x, y] for _, x, y in group], dtype=float)
        P += np.random.default_rng(11).normal(0, 0.2, P.shape)
        for _ in range(150):
            d = P[:, None, :] - P[None, :, :]
            dist = np.maximum(np.sqrt((d**2).sum(-1)), 1e-3) + np.eye(len(P)) * 1e9
            push = np.clip(size - dist, 0, None) / dist
            P += 0.5 * (d * push[..., None]).sum(1)
            rad = np.linalg.norm(P, axis=1, keepdims=True)  # stay inside the ring
            P = np.where(rad > R0 - 4, P / rad * (R0 - 4), P)
        for (n, _, _), (x, y) in zip(group, P, strict=True):
            n["x"], n["y"] = float(x), float(y)
    for n in nodes.values():
        n["x"], n["y"] = round(float(n.get("x", 0.0)), 3), round(float(n.get("y", 0.0)), 3)
    return {"r0": R0, "rmax": R0 + (H - 1) * DOT, "dot": DOT, "arcs": arcs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801")
    ap.add_argument("--min-org-entries", type=int, default=3, help="orgs drawn by default")
    ap.add_argument("--reembed", action="store_true", help="recompute excerpt vectors")
    args = ap.parse_args()
    D = ROOT / f"data/derived/responses/{args.docket}"
    O = ROOT / f"data/derived/outcomes/{args.docket}"

    codes = pd.read_parquet(D / "codes.parquet")
    entries = pd.read_parquet(D / "entries.parquet")
    diff = pd.read_parquet(D / "rule_diff.parquet")
    entries["organization"] = entries["organization"].fillna("Unknown").str.strip()

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    details: dict[str, dict] = {}

    def edge(s, t, kind, w=1.0, **kw):
        edges.append({"source": s, "target": t, "kind": kind, "weight": float(w), **kw})

    # ---- rule sections, with what changed between proposal and final
    sec_titles = diff.groupby("section")["title"].first().to_dict()
    for sec, g in diff.groupby("section"):
        ops = g["op"].value_counts().to_dict()
        changed = sum(ops.get(k, 0) for k in ("modified", "added", "removed"))
        sid = f"sec:{sec}"
        nodes[sid] = {
            "id": sid, "kind": "section", "label": f"§ {sec}",
            "title": sec_titles[sec].rstrip("."), "ops": ops, "changed": changed,
            "paragraphs": len(g), "change_share": round(changed / max(len(g), 1), 3),
        }  # fmt: skip
        sample = g[g["op"] != "unchanged"].copy()
        sample["len"] = sample["diff"].fillna("").str.len()
        details[sid] = {
            "diff": [
                {"op": r.op, "marker": None if pd.isna(r.marker) else r.marker,
                 "diff": r.diff if isinstance(r.diff, str) else None,
                 "proposed": r.proposed if isinstance(r.proposed, str) else None,
                 "final": r.final if isinstance(r.final, str) else None}
                for r in sample.itertuples()
            ]
        }  # fmt: skip

    def section_node(sec: str) -> str | None:
        sid = f"sec:{sec}"
        if sid not in nodes:  # cited by EPA but not in the diff: the final rule left it alone
            nodes[sid] = {
                "id": sid, "kind": "section", "label": f"§ {sec}", "title": "",
                "ops": {}, "changed": 0, "paragraphs": 0, "change_share": 0.0,
            }  # fmt: skip
            details[sid] = {"diff": []}
        return sid

    # ---- chapters and topics
    n_by_code = entries.groupby("code").size().to_dict()
    meta = DOCKETS.get(args.docket, {"title": args.docket, "short": args.docket, "chapters": {}})
    used = {chapter_of(c) for c in codes["code"]}
    for ch, name in meta["chapters"].items():
        if ch not in used:
            continue
        nodes[f"ch:{ch}"] = {"id": f"ch:{ch}", "kind": "chapter", "label": name, "chapter": ch}
    for r in codes.itertuples():
        tid = f"topic:{r.code}"
        title = (r.title or "").strip() or (BLANK_TITLES.get(r.code) if args.docket == "EPA-HQ-OW-2022-0801" else None) or f"Topic {r.code}"
        ch = chapter_of(r.code)
        nodes[tid] = {
            "id": tid, "kind": "topic", "label": title, "code": r.code, "chapter": ch,
            "comments": int(n_by_code.get(r.code, 0)), "page": None if pd.isna(r.page) else r.page,
        }  # fmt: skip
        details[tid] = {"summary": r.summary_response}
        edge(tid, f"ch:{ch}", "in_chapter")
        for sec, n in Counter(SECTION_RE.findall(r.summary_response or "")).items():
            edge(tid, section_node(sec), "cites", n)

    # ---- asks and verdicts
    asks: list[dict] = []
    raw_dir = O / "raw"
    for p in sorted(raw_dir.glob("*.json")):
        d = json.loads(p.read_text())
        for i, a in enumerate(d["asks"]):
            aid = f"ask:{d['code']}:{i}"
            a = {**a, "id": aid, "code": d["code"]}
            asks.append(a)
            nodes[aid] = {
                "id": aid, "kind": "ask", "label": a["ask"], "verdict": a["verdict"],
                "code": d["code"], "chapter": chapter_of(d["code"]), "who": a.get("who"),
                "changed": bool(a.get("final_rule_change")),
            }  # fmt: skip
            details[aid] = {
                "quote": a["quote"], "quote_verified": a["quote_verified"],
                "final_rule_change": a.get("final_rule_change"), "who": a.get("who"),
            }  # fmt: skip
            edge(aid, f"topic:{d['code']}", "asked_in")
            for sec in a.get("sections") or []:
                sec = str(sec).replace("§", "").strip()
                if re.fullmatch(r"14[12]\.\d+", sec):
                    edge(aid, section_node(sec), "about")

    # ---- organizations
    org_counts = entries.groupby("organization").size()
    org_kind = {o: stakeholder(o) for o in org_counts.index}
    org_id = {o: f"org:{i}" for i, o in enumerate(org_counts.sort_values(ascending=False).index)}
    for o, n in org_counts.items():
        oid = org_id[o]
        nodes[oid] = {
            "id": oid, "kind": "org", "label": o, "stakeholder": org_kind[o],
            "comments": int(n), "drawn": bool(n >= args.min_org_entries and o != "Unknown"),
        }  # fmt: skip
    for (o, code), g in entries.groupby(["organization", "code"]):
        edge(org_id[o], f"topic:{code}", "commented", len(g))

    # ---- excerpt vectors, for the agent's meaning-based search
    asks_by_code = defaultdict(list)
    for a in asks:
        asks_by_code[a["code"]].append(a)
    ex = entries.copy()
    if len(ex) and (not (O / "excerpt_vec.npy").exists() or args.reembed):
        ex_vec = embed([str(t)[:1500] for t in ex["excerpt"].fillna("")])
        np.save(O / "excerpt_vec.npy", ex_vec.astype(np.float16))
        ex[["entry_id"]].to_parquet(O / "excerpt_vec_ids.parquet", index=False)

    # ---- excerpt -> the ask it takes a side on (assign.py), and whether that side won
    verdict_of = {a["id"]: a["verdict"] for a in asks}
    side_of: dict[str, tuple[str, str]] = {}
    for p in sorted((O / "assign").glob("*.json")):
        for r in json.loads(p.read_text())["rows"]:
            if r["ask"] in verdict_of and r["side"]:
                side_of[r["entry_id"]] = (r["ask"], r["side"])

    def outcome(ask_id: str, side: str) -> str:
        v = verdict_of[ask_id]
        if v == "partly_adopted":
            return "partly"
        if v == "adopted":
            return "won" if side == "for" else "lost"
        if v == "declined":
            return "lost" if side == "for" else "won"
        return "no_change"  # clarified or already required: nothing moved either way

    org_of_entry = dict(zip(entries["entry_id"], entries["organization"]))
    pair = Counter()
    for eid, (aid, side) in side_of.items():
        pair[(org_of_entry[eid], aid, side)] += 1
        nodes[aid][side] = nodes[aid].get(side, 0) + 1
    for (o, aid, side), n in pair.items():
        edge(org_id[o], aid, "supports" if side == "for" else "opposes", n)

    # ---- per-org record and per-entry detail for the side panel
    for o, g in entries.groupby("organization"):
        rec = Counter()
        items = []
        for r in g.itertuples():
            aid, side = side_of.get(r.entry_id, (None, None))
            res = outcome(aid, side) if aid else None
            if res:
                rec[res] += 1
            items.append(
                {"code": r.code, "record_id": r.record_id, "excerpt": r.excerpt,
                 "response": r.response, "ask": aid, "side": side, "outcome": res}
            )  # fmt: skip
        items.sort(key=lambda x: x["ask"] is None)
        details[org_id[o]] = {"entries": items[:400], "record": dict(rec)}
        nodes[org_id[o]]["record"] = dict(rec)

    # ---- topic roll-ups: how EPA answered the asks in each topic
    for a in asks:
        t = nodes[f"topic:{a['code']}"]
        t.setdefault("verdicts", Counter())[a["verdict"]] += 1
    for n in nodes.values():
        if "verdicts" in n:
            n["verdicts"] = dict(n["verdicts"])

    # ---- layout: the rule at the core, EPA's topics on a ring, commenters in an outer halo
    rings = layout(nodes, edges)

    stats = {
        "docket": args.docket, "rings": rings,
        "meta": {k: meta.get(k) for k in ("title", "short", "proposed", "final")},
        "topics": len(codes), "asks": len(asks), "comments": len(entries),
        "orgs": len(org_counts), "sections": sum(n["kind"] == "section" for n in nodes.values()),
        "verdicts": dict(Counter(a["verdict"] for a in asks)),
        "asks_with_rule_change": sum(bool(a.get("final_rule_change")) for a in asks),
        "quotes_verified": sum(bool(a["quote_verified"]) for a in asks),
        "excerpts_tied_to_ask": len(side_of),
        "excerpt_sides": dict(Counter(s for _, s in side_of.values())),
        "excerpt_outcomes": dict(Counter(outcome(a, s) for a, s in side_of.values())),
        "usd_assign": round(sum(json.loads(p.read_text())["usd"] for p in (O / "assign").glob("*.json")), 2),
        "stakeholders": dict(Counter(org_kind.values())),
        "usd_extraction": round(sum(json.loads(p.read_text())["usd"] for p in raw_dir.glob("*.json")), 2),
    }  # fmt: skip
    (O / "graph.json").write_text(
        json.dumps({"stats": stats, "nodes": list(nodes.values()), "edges": edges})
    )
    (O / "details.json").write_text(json.dumps(details))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
