"""One model call: cached by tag, validated against a schema, priced, and written to a ledger.

Port of the 12 Oct pilot's llm.py (reading/llm.py) without its hard-coded paths, module-level
ledger and Sonnet glitch hack. The backend is chosen once per run:

  GRAPH_BACKEND=cli | sdk | fake, or auto: sdk when ANTHROPIC_API_KEY is set, else cli when
  `claude` is on PATH, else none. With none, main.py prints a skip message and exits 0 so the
  compose chain stays green on a machine with no model access.

Per call, under data/derived/graph/<docket>/:
  prompts/<tag>.txt   the system prompt and the user prompt, written before the call
  raw/<tag>.json      the backend's response, written on success. A rerun finds it and makes no call
  ledger.jsonl        one row per attempt: tag, step, model, backend, effort, attempt, secs, tokens,
                      usd, price_source, ok, stop_reason, cached

A call gets at most two attempts. The second appends the validator's error text to the user prompt.
Budget: a live call is refused (BudgetExceeded, nothing paid) once the ledger's spend is above
GRAPH_MAX_USD, and the call that crosses the cap is kept: its answer is written to raw/ before the
exception, so a rerun with a higher cap serves it from cache. Cached answers never raise, so a rerun
over a finished folder costs nothing whatever the cap. main.py writes partial outputs and exits 2.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

import jsonschema

from backends import CliBackend, FakeBackend, Response, SdkBackend
from config import ROOT, Config

PRICES = json.loads((ROOT / "prices.json").read_text())
MAX_ATTEMPTS = 2


class BudgetExceeded(RuntimeError):
    pass


class CallFailed(RuntimeError):
    """Both attempts failed to produce output that validates against the schema."""


class NoBackend(RuntimeError):
    pass


def choose_backend(cfg: Config):
    name = cfg.backend_name
    if name == "auto":
        if SdkBackend.available():
            name = "sdk"
        elif CliBackend.available():
            name = "cli"
        else:
            name = "none"
    if name == "none":
        raise NoBackend("no LLM backend")
    if name == "fake":
        if cfg.fixtures is None:
            raise NoBackend("GRAPH_BACKEND=fake needs GRAPH_FIXTURES")
        return FakeBackend(cfg.fixtures)
    if name == "sdk":
        return SdkBackend(cfg.model_id)
    if name == "cli":
        return CliBackend(cfg.model)
    raise NoBackend(f"unknown GRAPH_BACKEND {name!r}")


def parse_json(text: str) -> dict:
    """Strip code fences and anything around the outermost {...}, then json.loads."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in output")
    return json.loads(text[i : j + 1])


def price(usage: dict, model_id: str) -> tuple[float | None, str]:
    """USD for a call from prices.json, or (None, 'unknown') for a model not in the table."""
    table = PRICES.get(model_id)
    if not table:
        return None, "unknown"
    per = table["per"]
    usd = (
        usage.get("input_tokens", 0) * table["input"]
        + usage.get("cache_write_tokens", 0) * table["cache_write_5m"]
        + usage.get("cache_read_tokens", 0) * table["cache_read"]
        + usage.get("output_tokens", 0) * table["output"]
    ) / per
    return round(usd, 6), f"prices.json ({table.get('source', '')})"


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class LLM:
    def __init__(self, cfg: Config, out_dir: Path, backend=None):
        self.cfg = cfg
        self.out = Path(out_dir)
        (self.out / "raw").mkdir(parents=True, exist_ok=True)
        (self.out / "prompts").mkdir(parents=True, exist_ok=True)
        self.backend = backend or choose_backend(cfg)
        self.ledger_path = self.out / "ledger.jsonl"
        self._lock = threading.Lock()
        self.spent = self._spent_so_far()

    # -- ledger ---------------------------------------------------------------------------------

    def _spent_so_far(self) -> float:
        if not self.ledger_path.exists():
            return 0.0
        total = 0.0
        for line in self.ledger_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                total += row.get("usd") or 0.0
        return total

    def _log(self, row: dict) -> None:
        with self._lock:
            with self.ledger_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            self.spent += row.get("usd") or 0.0

    def _check_budget(self) -> None:
        if self.spent > self.cfg.max_usd:
            raise BudgetExceeded(f"spent ${self.spent:.2f} > GRAPH_MAX_USD {self.cfg.max_usd:.2f}")

    def rows(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(x) for x in self.ledger_path.read_text().splitlines() if x.strip()]

    # -- one call ---------------------------------------------------------------------------------

    def call(
        self, tag: str, step: str, system: str, static: str, user: str, schema: dict
    ) -> dict:
        """Validated JSON for a tag. Cached: raw/<tag>.json exists -> parse and return, no call."""
        raw_path = self.out / "raw" / f"{tag}.json"
        # A tag names a batch position, not its content: a smoke run with GRAPH_MAX_PASSAGES or a
        # changed claim set can leave raw/<tag>.json holding the answer to a different batch. The
        # prompt's hash is stored with the answer, and a cached answer to another prompt is a miss.
        user_sha1 = sha1(f"{static}\n{user}")
        cached = json.loads(raw_path.read_text()) if raw_path.exists() else None
        if cached is not None and cached.get("user_sha1") != user_sha1:
            cached = None  # stale, or written before the hash was stored: a miss either way
        if cached is not None:
            try:
                out = parse_json(cached["result"])
                jsonschema.validate(out, schema)
            except (ValueError, json.JSONDecodeError, jsonschema.ValidationError):
                cached = None  # the schema moved since the answer was recorded
        if cached is not None:
            self._log(
                {"tag": tag, "step": step, "model": cached.get("model"),
                 "backend": self.backend.name, "effort": None, "attempt": 0, "secs": 0.0,
                 "input_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0,
                 "output_tokens": 0, "usd": 0.0, "price_source": "cached", "ok": True,
                 "stop_reason": cached.get("stop_reason"), "cached": True}
            )  # fmt: skip
            return out

        self._check_budget()  # refuse a live call once over the cap: nothing is paid for
        (self.out / "prompts" / f"{tag}.txt").write_text(
            f"=== SYSTEM ===\n{system}\n\n=== STATIC ===\n{static}\n\n=== USER ===\n{user}\n"
        )
        effort = self.cfg.effort if self.backend.name == "sdk" else None
        user_attempt = user
        last_error = "no attempt"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            t0 = time.time()
            r: Response = self.backend.complete(tag, system, static, user_attempt, schema, effort)
            secs = round(time.time() - t0, 1)
            ok, out, err = False, None, r.error
            if not err:
                try:
                    out = parse_json(r.text)
                    jsonschema.validate(out, schema)
                    ok = True
                except (ValueError, json.JSONDecodeError) as e:
                    err = f"output is not JSON: {e}"
                except jsonschema.ValidationError as e:
                    err = f"output does not match the schema: {e.message}"
            priced_model = r.model if r.model in PRICES else self.cfg.model_id
            usd, source = (
                (r.usd, self.backend.price_source)
                if r.usd is not None
                else price(r.usage, priced_model)
            )
            self._log(
                {"tag": tag, "step": step, "model": r.model, "backend": self.backend.name,
                 "effort": effort, "attempt": attempt, "secs": secs, **r.usage, "usd": usd,
                 "price_source": source, "ok": ok, "stop_reason": r.stop_reason,
                 "cached": False, **({"error": err[:500]} if err else {})}
            )  # fmt: skip
            if ok:
                raw_path.write_text(
                    json.dumps(
                        {"tag": tag, "model": r.model, "stop_reason": r.stop_reason,
                         "usage": r.usage, "usd": usd, "user_sha1": user_sha1,
                         "result": r.text}
                    )  # fmt: skip
                )
                self._check_budget()  # after the answer is on disk, so the paid call is kept
                return out
            self._check_budget()
            last_error = err or "unknown"
            if r.stop_reason == "refusal":
                break  # the same prompt will be refused again
            user_attempt = (
                f"{user}\n\nYour previous answer could not be used: {last_error}. "
                "Return only JSON that matches the schema."
            )
        raise CallFailed(f"{tag}: {last_error}")
