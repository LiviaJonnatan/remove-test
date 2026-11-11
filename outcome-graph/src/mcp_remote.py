"""Oversight as a public, read-only MCP server at /mcp, so anyone can ask their own Claude (or any MCP
client) what happened to public comments on EPA drinking water rules.

    claude mcp add --transport http oversight https://<host>/mcp/

Covers every mapped rule at once (mcp_server.py is the per-rule server Iris uses in process).
No sign-in: everything here is public record. No model calls, so it costs nothing to serve.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import hub
from store import _outcome


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def build() -> FastMCP:
    # Public server on Cloud Run's hostname: the SDK's localhost-only host check is turned off on purpose.
    mcp = FastMCP("oversight", host="0.0.0.0", stateless_http=True, json_response=True, streamable_http_path="/",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
                  instructions="What happened to public comments on US EPA drinking water rules. Every ask a "
                               "commenter made, EPA's verdict in its own words with a page citation, the effect on "
                               "the final rule, and which organizations asked. Start with list_rules or find.")  # fmt: skip

    def _rule(short: str):
        for st in hub.stores():
            if st.short.lower() == short.lower() or st.docket.lower() == short.lower():
                return st
        raise ValueError(f"Unknown rule {short!r}. Use list_rules.")

    @mcp.tool()
    def list_rules() -> str:
        """The rules with a full outcome record: short name, title, dates, and how EPA ruled on the asks."""
        return _j([{"rule": st.short, "docket": st.docket, "title": st.meta.get("title"), "proposed": st.meta.get("proposed"),
                    "final": st.meta.get("final"), "asks": st.stats.get("asks"), "verdicts": st.stats.get("verdicts"),
                    "asks_that_changed_the_rule": st.stats.get("asks_with_rule_change")} for st in hub.stores()])  # fmt: skip

    @mcp.tool()
    def find(query: str) -> str:
        """Search organizations, topics and asks across every rule. Returns ids to pass to get_ask."""
        return _j(hub.find(query))

    @mcp.tool()
    def list_asks(rule: str, verdict: str | None = None, group: str | None = None, changed_rule: bool = False,
                  limit: int = 40) -> str:  # fmt: skip
        """Asks in one rule, filtered. verdict: adopted, partly_adopted, declined, clarified, already_required.
        group (who argued): utility, advocacy, trade, state, local, federal, industry, academic, individual.
        changed_rule: only asks that changed the final rule text."""
        st = _rule(rule)
        out = []
        for n in st.nodes.values():
            if n["kind"] != "ask" or (verdict and n.get("verdict") != verdict) or (changed_rule and not n.get("changed")):
                continue
            orgs = [(st.nodes[o], e) for o, e in st.adj[n["id"]] if st.nodes[o]["kind"] == "org"]
            if group and not any(o.get("stakeholder") == group for o, _ in orgs):
                continue
            d = st.details.get(n["id"], {})
            out.append({"id": n["id"], "ask": n["label"], "verdict": n.get("verdict"), "changed_rule": bool(n.get("changed")),
                        "epa_said": d.get("quote"), "page": st.cites.get(n["id"], {}).get("page"),
                        "asked_by": [o["label"] for o, e in orgs if e["kind"] == "supports"][:5]})  # fmt: skip
        return _j({"rule": st.short, "total": len(out), "asks": out[: max(1, min(limit, 100))]})

    @mcp.tool()
    def get_ask(rule: str, ask_id: str) -> str:
        """One ask: EPA's verbatim answer, the page in EPA's response document, the surrounding paragraph,
        the change to the final rule, and every organization for and against it."""
        st = _rule(rule)
        n = st.nodes.get(ask_id)
        if not n or n["kind"] != "ask":
            raise ValueError(f"No ask {ask_id!r} in {st.short}")
        d, c = st.details.get(ask_id, {}), st.cites.get(ask_id, {})
        side = lambda k: [st.nodes[o]["label"] for o, e in st.adj[ask_id] if st.nodes[o]["kind"] == "org" and e["kind"] == k]  # noqa: E731
        return _j({"rule": st.short, "id": ask_id, "topic": n.get("code"), "ask": n["label"], "verdict": n.get("verdict"),
                   "epa_said": d.get("quote"), "quote_checked_word_for_word": bool(d.get("quote_verified")),
                   "citation": {"document": f"EPA Response to Comments, {st.meta.get('title')}", "section": n.get("code"),
                                "page": c.get("page")}, "paragraph": c.get("context"),
                   "final_rule_change": d.get("final_rule_change"), "asked_for_by": side("supports"),
                   "argued_against_by": side("opposes")})  # fmt: skip

    @mcp.tool()
    def organization(name: str) -> str:
        """An organization's record across every rule: each ask it took a side on, EPA's verdict, and
        whether it got its way (EPA adopted what it asked for, or declined what it opposed)."""
        hits = hub.find_orgs(name, 1)
        if not hits:
            raise ValueError(f"No organization like {name!r}")
        o = hub.org(hits[0]["slug"])
        for r in o["rule_list"]:
            r["asks"] = [{k: a[k] for k in ("id", "label", "verdict", "side", "outcome", "changed", "page")} for a in r["asks"]]
        return _j(o)

    @mcp.tool()
    def similar_asks(text: str, rule: str | None = None, limit: int = 8) -> str:
        """Past asks closest in meaning to a point you want to make, with how EPA answered. Use it to test
        a draft comment against precedent."""
        co = hub._C(next(iter(s.docket for s in hub.stores())))
        return _j(co.similar_asks(text, limit=max(1, min(limit, 20)), rule=rule))

    @mcp.tool()
    def scoreboard(rule: str) -> str:
        """Which stakeholder groups got their way on a rule, counted by ask positions."""
        st = _rule(rule)
        g: dict[str, dict] = {}
        for e in st.edges:
            if e["kind"] not in ("supports", "opposes"):
                continue
            o, a = (e["source"], e["target"]) if st.nodes[e["source"]]["kind"] == "org" else (e["target"], e["source"])
            grp = st.nodes[o].get("stakeholder") or "other"
            r = g.setdefault(grp, {"won": 0, "partly": 0, "lost": 0, "no_change": 0})
            r[_outcome(st.nodes[a].get("verdict"), "for" if e["kind"] == "supports" else "against")] += 1
        return _j({"rule": st.short, "groups": {k: v | {"share_won": hub._share(v)} for k, v in g.items()},
                   "how_to_read": "Each count is one organization's position on one ask. share_won counts partly as half."})

    return mcp
