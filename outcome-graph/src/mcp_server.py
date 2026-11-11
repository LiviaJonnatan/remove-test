"""MCP server over the outcome graph: the tools Iris and the comment coach use, and the same tools
anyone can attach to their own Claude:

    DOCKET=EPA-HQ-OW-2022-0114 claude mcp add outcome -- uv run --project outcome-graph python outcome-graph/src/mcp_server.py

`build(store, coach)` makes one server per rule. The web API calls it in process (agent.py lists
and calls these tools directly), so the agent on the page and an external client see exactly the
same tools. Every tool returns node ids; the page lights up whatever the agent reads.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from coach import Coach
from store import Store, available


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)


def build(st: Store, coach: Callable[[], Coach]) -> FastMCP:
    """The tool server for one rule. `coach` is called lazily: it embeds every rule's asks."""
    mcp = FastMCP("outcome")

    def S() -> Store:
        return st

    def C() -> Coach:
        return coach()

    @mcp.tool()
    def overview() -> str:
        """Totals for the docket and every chapter of EPA's response document, with how EPA ruled on
        the asks in each chapter. Start here for broad questions."""
        return _j(S().overview())


    @mcp.tool()
    def search(query: str, kind: str | None = None, limit: int = 12) -> str:
        """Keyword search over node names. kind: topic, ask, org, section or chapter.
        Use it to find an organization, a topic, an ask or a CFR section (e.g. "141.84")."""
        return _j(S().search(query, kind, limit))


    @mcp.tool()
    def search_comments(
        query: str, organization: str | None = None, topic: str | None = None,
        stakeholder: str | None = None, limit: int = 8,
    ) -> str:  # fmt: skip
        """Meaning-based search over the 7,889 comment excerpts EPA quoted in its response document,
        each with EPA's reply. Filter by organization name, topic id (topic:9.7) or stakeholder
        (state, utility, trade, advocacy, local, federal, industry, labor, academic, individual)."""
        return _j(S().search_comments(query, organization, topic, stakeholder, limit))


    @mcp.tool()
    def get_node(node_id: str, offset: int = 0) -> str:
        """Everything about one node. Topic: EPA's summary response (paged by offset), its asks and
        verdicts, top commenters, sections. Ask: EPA's verbatim quote, what changed in the final
        rule. Org: excerpts EPA quoted, the asks it supported or opposed, and whether it won. Section: paragraph-level changes from
        proposal to final rule as word diffs ([-removed-] {+added+}). An id from another rule carries
        its prefix, e.g. "LCRR/ask:6.2:3"."""
        if "/" in node_id:
            hit = C().resolve(node_id)
            if not hit:
                return _j({"error": f"unknown id {node_id}"})
            st, nid = hit
            return _j({"rule": st.meta, **st.node(nid, offset)})
        return _j(S().node(node_id, offset))


    @mcp.tool()
    def neighbors(node_id: str, kind: str | None = None, limit: int = 30) -> str:
        """Nodes linked to node_id, strongest first, optionally only one kind."""
        return _j(S().neighbors(node_id, kind, limit))


    @mcp.tool()
    def org_record(name: str) -> str:
        """One commenter's track record: the asks they supported or opposed, EPA's verdict on each,
        and whether they won (EPA adopted what they wanted or declined what they opposed)."""
        return _j(S().org_record(name))


    @mcp.tool()
    def compare_stakeholders(scope: str | None = None) -> str:
        """Did each stakeholder group (states, utilities, advocacy groups...) get its way: won, partly,
        lost, no change, for the whole rule or one topic (topic:9.7) or chapter (ch:9)."""
        return _j(S().compare_stakeholders(scope))




    @mcp.tool()
    def find_similar_asks(text: str, limit: int = 8, rule: str | None = None) -> str:
        """Past asks that make the same or the opposite point as `text`, closest first. Each has EPA's
        verdict, EPA's own sentence (epa_said), what changed in the final rule, and a match score
        (above about 0.80 is a close match, below 0.72 is loose). Matches both the ask's wording and
        the comments that argued it. Searches every rule in the record; each hit names its rule, and
        ids from other rules carry a prefix ("LCRR/ask:6.2:3"). `rule` limits to one rule by short
        name (LCRI, LCRR, PFAS)."""
        return _j(C().similar_asks(text, min(limit, 12), rule))


    @mcp.tool()
    def search_rule_text(query: str, section: str | None = None, limit: int = 6) -> str:
        """Meaning-based search over the paragraphs of the final regulatory text (40 CFR 141/142) of
        the rule being commented on.
        Use it to check whether something is already required. `section` narrows to e.g. "141.84".
        Each hit says whether it changed from the proposal (added, modified, unchanged) or was in the
        proposal only and dropped (in: proposed_only)."""
        return _j(C().search_rule(query, section, min(limit, 10)))

    return mcp


if __name__ == "__main__":
    DATA_ROOT = Path(os.environ["OUTCOME_DATA_ROOT"]) if os.environ.get("OUTCOME_DATA_ROOT") else None
    _st = Store(os.environ.get("DOCKET", "EPA-HQ-OW-2022-0801"), data_root=DATA_ROOT)
    _c: list[Coach] = []

    def _coach() -> Coach:
        if not _c:
            others = [Store(d, data_root=DATA_ROOT) for d in available(DATA_ROOT) if d != _st.docket]
            _c.append(Coach(_st, others))
        return _c[0]

    build(_st, _coach).run()
