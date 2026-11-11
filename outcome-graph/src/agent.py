"""The agent loop behind Iris and the comment coach.

Production path: Claude on Vertex AI through `AsyncAnthropicVertex`. It authenticates with Google
credentials (Application Default Credentials: `gcloud auth application-default login` on a laptop,
the Cloud Run service account with roles/aiplatform.user in production). There is no Anthropic API
key. The tools are the rule's MCP server (mcp_server.build), listed and called in process, plus two
local tools that need the request's context: `show_on_graph` (drives the page) and `my_history`
(the signed-in user's own past chats and drafts).

Development fallback (LLM_BACKEND=cli): the laptop's `claude -p` with the same MCP server as a
subprocess. Same events, no local tools.

Both yield the same events, which the API forwards to the page as server-sent events:
  {"type": "text", "delta"}                 answer text as it is written
  {"type": "tool", "name", "input", "ids"}  a tool call
  {"type": "visit", "tool", "ids"}          node ids that tool's result touched (the page lights them)
  {"type": "show", "ids", "focus"}          the agent asked the page to show these nodes
  {"type": "done", "text", "trace", "usd", "ms", "turns"}
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import config

ID_RE = re.compile(r"\b(?:[A-Z]{2,6}/)?(topic:[\d.]+\d|ask:[\d.]+:\d+|org:\d+|sec:14[12]\.\d+|ch:\d+)\b")
QID_RE = re.compile(r"\b(?:[A-Z]{2,6}/)?(?:topic:[\d.]+\d|ask:[\d.]+:\d+|org:\d+|sec:14[12]\.\d+|ch:\d+)\b")
HERE = Path(__file__).resolve().parent
_workdir = Path(tempfile.mkdtemp(prefix="oversight-agent-"))

# Vertex prices differ from Anthropic's first-party list; these are for the running cost estimate
# shown to the user and for the per-run cap, not billing.
PRICE = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0), "claude-haiku-5-5": (0.1, 0.5)}

SHOW_TOOL = {
    "name": "show_on_graph",
    "description": "Show nodes on the user's screen: highlights them on the graph and, with focus, "
    "opens one in the side panel. Call it once per answer with the nodes the answer is about "
    "(at most 30), focus on the single most relevant one.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ids": {"type": "array", "items": {"type": "string"}, "description": "node ids, e.g. org:14, ask:9.7:2"},
            "focus": {"type": "string", "description": "one id to open in the side panel"},
        },
        "required": ["ids"],
    },
}
HISTORY_TOOL = {
    "name": "my_history",
    "description": "Search this signed-in user's own earlier conversations with you and their saved "
    "draft comments. Use it when they refer to something from before ('my draft', 'what you told me "
    "last time', 'the utility issue I asked about').",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


def _ids(text: str, limit: int = 80) -> list[str]:
    return list(dict.fromkeys(QID_RE.findall(text)))[:limit]


def _cost(model: str, usage) -> float:
    pin, pout = PRICE.get(model, (3.0, 15.0))
    tin = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    tin += 0.1 * (getattr(usage, "cache_read_input_tokens", 0) or 0)
    return (tin * pin + (getattr(usage, "output_tokens", 0) or 0) * pout) / 1e6


def _tool_text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return "\n".join(getattr(b, "text", "") for b in content)


_client = None


def vertex():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropicVertex

        _client = AsyncAnthropicVertex(project_id=config.GCP_PROJECT, region=config.VERTEX_REGION)
    return _client


async def run(
    *,
    system: str,
    history: list[dict],
    prompt: str,
    srv,  # FastMCP for the rule
    docket: str,
    history_search: Callable[[str], list[dict]] | None = None,
    allowed: list[str] | None = None,
    ui: bool = True,
    max_turns: int = 14,
    budget_usd: float = 1.0,
    effort: str = "medium",
) -> AsyncIterator[dict]:
    if config.LLM_BACKEND == "cli":
        async for ev in _run_cli(system=system, history=history, prompt=prompt, docket=docket):
            yield ev
        return

    t0 = time.time()
    tools = [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
             for t in await srv.list_tools() if not allowed or t.name in allowed]  # fmt: skip
    if ui:
        tools.append(SHOW_TOOL)
    if history_search:
        tools.append(HISTORY_TOOL)
    msgs = [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]
    msgs.append({"role": "user", "content": prompt})
    trace: list[dict] = []
    text, usd, turns = "", 0.0, 0

    while turns < max_turns:
        turns += 1
        async with vertex().messages.stream(
            model=config.MODEL, max_tokens=16000, system=system, messages=msgs, tools=tools,
            output_config={"effort": effort},
        ) as stream:  # fmt: skip
            async for ev in stream:
                if ev.type == "text":
                    yield {"type": "text", "delta": ev.text}
            final = await stream.get_final_message()
        usd += _cost(config.MODEL, final.usage)
        turn_text = "".join(b.text for b in final.content if b.type == "text")
        if final.stop_reason != "tool_use":
            text = turn_text
            if final.stop_reason == "refusal":
                text = text or "I can't help with that one. Try asking about the record."
            break
        if turn_text:
            yield {"type": "text", "delta": "\n\n"}
        msgs.append({"role": "assistant", "content": final.content})
        results = []
        for b in final.content:
            if b.type != "tool_use":
                continue
            args = b.input if isinstance(b.input, dict) else {}
            yield {"type": "tool", "name": b.name, "input": args, "ids": _ids(json.dumps(args))}
            if b.name == "show_on_graph":
                ids = [i for i in args.get("ids", []) if isinstance(i, str)][:30]
                yield {"type": "show", "ids": ids, "focus": args.get("focus")}
                out = "Shown."
            elif b.name == "my_history" and history_search:
                out = json.dumps(history_search(str(args.get("query", ""))), default=str, ensure_ascii=False)
            else:
                try:
                    out = _tool_text(await srv.call_tool(b.name, args))
                except Exception as e:  # noqa: BLE001
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Error: {e}", "is_error": True})
                    continue
            ids = _ids(out)
            trace.append({"tool": b.name, "input": args, "ids": ids[:40]})
            if b.name not in ("show_on_graph", "my_history"):
                yield {"type": "visit", "tool": b.name, "ids": ids}
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out[:60000]})
        msgs.append({"role": "user", "content": results})
        if usd > budget_usd:
            text = turn_text or "I stopped there to stay inside this question's budget."
            break
    yield {"type": "done", "text": text, "trace": trace, "usd": round(usd, 4),
           "ms": int((time.time() - t0) * 1000), "turns": turns}  # fmt: skip


# ------------------------------------------------------------------ development fallback
def _mcp_config(docket: str) -> str:
    cfg = {"mcpServers": {"outcome": {
        "command": sys.executable, "args": [str(HERE / "mcp_server.py")],
        "env": {"PYTHONPATH": str(HERE), "DOCKET": docket}
        | ({"OUTCOME_DATA_ROOT": str(config.DATA_ROOT)} if config.DATA_ROOT else {}),
    }}}  # fmt: skip
    p = _workdir / f"mcp_{docket}.json"
    p.write_text(json.dumps(cfg))
    return str(p)


async def _run_cli(*, system: str, history: list[dict], prompt: str, docket: str) -> AsyncIterator[dict]:
    t0 = time.time()
    if history:
        past = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-8:])
        prompt = f"Earlier in this conversation:\n{past}\n\nNow: {prompt}"
    cmd = ["claude", "-p", "--model", config.CLI_MODEL, "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--system-prompt", system, "--mcp-config", _mcp_config(docket),
           "--strict-mcp-config", "--setting-sources", "", "--tools", "", "--allowedTools", "mcp__outcome",
           "--no-session-persistence", "--max-budget-usd", "1.00"]  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=_workdir, env=env, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                limit=2**24)  # fmt: skip
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    tools: dict[str, str] = {}
    trace: list[dict] = []
    text, usd, streamed = "", None, False
    async for line in proc.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "stream_event":
            e = ev.get("event", {})
            if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                streamed = True
                yield {"type": "text", "delta": e["delta"]["text"]}
        elif t == "assistant":
            for b in ev.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    name = b["name"].replace("mcp__outcome__", "")
                    tools[b["id"]] = name
                    yield {"type": "tool", "name": name, "input": b.get("input", {}), "ids": _ids(json.dumps(b.get("input", {})))}
                elif b.get("type") == "text":
                    text = b.get("text", "")
        elif t == "user":
            for b in ev.get("message", {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    ids = _ids(json.dumps(b.get("content")))
                    name = tools.get(b.get("tool_use_id"))
                    trace.append({"tool": name, "ids": ids[:40]})
                    yield {"type": "visit", "tool": name, "ids": ids}
        elif t == "result":
            usd = ev.get("total_cost_usd")
            text = ev.get("result") or text
    await proc.wait()
    if not streamed and text:
        yield {"type": "text", "delta": text}
    cited = _ids(text, 30)
    if cited:
        yield {"type": "show", "ids": cited, "focus": cited[0]}
    if proc.returncode not in (0, None) and not text:
        err = (await proc.stderr.read()).decode()[-600:]
        yield {"type": "error", "message": err or "The agent stopped."}
    yield {"type": "done", "text": text, "trace": trace, "usd": usd, "ms": int((time.time() - t0) * 1000), "turns": None}
