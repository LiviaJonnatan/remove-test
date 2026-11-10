"""The three ways a prompt reaches a model, behind one interface.

CliBackend   `claude -p --model fable ...` as a subprocess, the way the 12 Oct pilot ran. Uses the
             laptop's Claude Code login, so no API key is needed. Usage and cost come from the
             result JSON. Effort is not exposed by the CLI and is recorded as null.
SdkBackend   The Anthropic SDK with ANTHROPIC_API_KEY (or an `ant auth login` profile). This is what
             the container uses. Structured output through a JSON schema, the section context cached
             before the passages, server-side fallback on a refusal.
FakeBackend  Recorded responses from tests/fixtures/<tag>.json. A tag with no fixture raises, so no
             test can reach the network.

Every backend returns a Response; llm.py parses, validates and prices it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CLI_TIMEOUT_S = 900
SDK_MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Response:
    text: str
    usage: dict = field(default_factory=dict)  # input, cache_write, cache_read, output
    usd: float | None = None  # only when the backend reports a price itself (CLI)
    stop_reason: str | None = None
    model: str | None = None
    error: str | None = None


def _usage(raw: dict | None) -> dict:
    raw = raw or {}
    return {
        "input_tokens": int(raw.get("input_tokens") or 0),
        "cache_write_tokens": int(raw.get("cache_creation_input_tokens") or 0),
        "cache_read_tokens": int(raw.get("cache_read_input_tokens") or 0),
        "output_tokens": int(raw.get("output_tokens") or 0),
    }


class CliBackend:
    name = "cli"
    price_source = "cli"

    def __init__(self, model: str = "fable", workdir: Path | None = None):
        self.model = model
        # `claude -p` reads CLAUDE.md and settings from its cwd. An empty folder keeps the call
        # free of this repo's instructions, as in the pilot.
        self.workdir = workdir or Path(tempfile.mkdtemp(prefix="argument-graph-"))
        self.workdir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available() -> bool:
        return shutil.which("claude") is not None

    def complete(
        self, tag: str, system: str, static: str, user: str, schema: dict, effort: str | None
    ) -> Response:
        prompt = f"{static}\n\n{user}" if static else user
        cmd = [
            "claude", "-p", "--model", self.model, "--output-format", "json",
            "--system-prompt", system,
            "--tools", "", "--setting-sources", "", "--strict-mcp-config",
            "--no-session-persistence",
        ]  # fmt: skip
        try:
            r = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, cwd=self.workdir,
                timeout=CLI_TIMEOUT_S,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return Response(text="", error=f"claude -p timed out after {CLI_TIMEOUT_S}s")
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            return Response(text="", error=(r.stdout[-2000:] + r.stderr[-2000:]).strip())
        if out.get("is_error") or not out.get("result"):
            return Response(text="", error=str(out)[:2000], usage=_usage(out.get("usage")))
        usage = _usage(out.get("usage"))
        used = out.get("modelUsage")
        model = next(iter(used)) if isinstance(used, dict) and used else self.model
        return Response(
            text=out["result"],
            usage=usage,
            usd=out.get("total_cost_usd"),
            stop_reason=out.get("stop_reason") or "end_turn",
            model=model,
        )


class SdkBackend:
    name = "sdk"
    price_source = "prices.json"

    def __init__(self, model_id: str = "claude-fable-5-1"):
        import anthropic

        self.model = model_id
        # Reads ANTHROPIC_API_KEY, or an `ant auth login` profile when the key is unset.
        self.client = anthropic.Anthropic()

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def complete(
        self, tag: str, system: str, static: str, user: str, schema: dict, effort: str | None
    ) -> Response:
        import anthropic

        # Everything before the cache breakpoint is shared by a section's calls: the system prompt
        # and the section heading plus rule context. The passages or pairs come after it.
        system_blocks = [
            {
                "type": "text",
                "text": f"{system}\n\n{static}" if static else system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if effort:
            output_config["effort"] = effort
        try:
            # No `thinking` parameter: on Fable it is always on and any explicit setting is a 400.
            r = self.client.beta.messages.create(
                model=self.model,
                max_tokens=SDK_MAX_TOKENS,
                system=system_blocks,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIStatusError as e:  # 4xx/5xx after the SDK's own retries
            return Response(text="", error=f"{type(e).__name__}: {e}")
        except anthropic.APIConnectionError as e:
            return Response(text="", error=f"APIConnectionError: {e}")
        usage = r.usage.model_dump() if hasattr(r.usage, "model_dump") else dict(r.usage)
        text = "".join(
            getattr(b, "text", "") for b in r.content if getattr(b, "type", "") == "text"
        )
        return Response(
            text=text,
            usage=_usage(usage),
            stop_reason=r.stop_reason,
            model=getattr(r, "model", self.model),
            error="refusal" if r.stop_reason == "refusal" else None,
        )


class FakeBackend:
    """Recorded responses, keyed by tag. `result` is one response; `results` is one per attempt."""

    name = "fake"
    price_source = "fixture"

    def __init__(self, fixtures: Path, model: str = "fake"):
        self.fixtures = Path(fixtures)
        self.model = model
        self.calls: list[str] = []
        self._attempts: dict[str, int] = {}

    @staticmethod
    def available() -> bool:
        return True

    def complete(
        self, tag: str, system: str, static: str, user: str, schema: dict, effort: str | None
    ) -> Response:
        path = self.fixtures / f"{tag}.json"
        if not path.exists():
            raise FileNotFoundError(f"no fixture for tag {tag!r} at {path}")
        self.calls.append(tag)
        fx = json.loads(path.read_text())
        n = self._attempts.get(tag, 0)
        self._attempts[tag] = n + 1
        results = fx.get("results") or [fx["result"]]
        result = results[min(n, len(results) - 1)]
        if not isinstance(result, str):
            result = json.dumps(result)
        return Response(
            text=result,
            usage=_usage(fx.get("usage")),
            usd=fx.get("usd"),
            stop_reason=fx.get("stop_reason", "end_turn"),
            model=self.model,
            error="refusal" if fx.get("stop_reason") == "refusal" else fx.get("error"),
        )
