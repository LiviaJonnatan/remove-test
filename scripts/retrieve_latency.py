"""Latency of POST /retrieve on real passages, as the API is running.

  uv run --with pandas --with pyarrow python scripts/retrieve_latency.py \
      --passages data/derived/passages/EPA-HQ-OW-2022-0801/passages.parquet --n 200

Sends the passages one at a time, after 10 warm-up calls, and prints p50, p90, p99 and max in
milliseconds, measured from the client. Needs `docker compose up` (or at least chromadb and
api-service) and a passages file from passage-stage.
"""

import argparse
import json
import random
import time
import urllib.request

import pandas as pd


def call(url: str, text: str, k: int) -> float:
    body = json.dumps({"text": text, "k": k}).encode()
    request = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    start = time.perf_counter()
    urllib.request.urlopen(request, timeout=60).read()
    return (time.perf_counter() - start) * 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passages", required=True)
    ap.add_argument("--url", default="http://localhost:8000/retrieve")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    texts = list(pd.read_parquet(a.passages)["text"])
    random.seed(a.seed)
    sample = random.sample(texts, min(a.n, len(texts)))
    first = call(a.url, sample[0], a.k)
    for text in sample[:10]:
        call(a.url, text, a.k)
    times = sorted(call(a.url, text, a.k) for text in sample)

    def pct(q: float) -> float:
        return round(times[min(len(times) - 1, round(q * len(times)) - 1)], 1)

    print(json.dumps({
        "n": len(times), "k": a.k, "first_call_ms": round(first, 1),
        "p50_ms": pct(0.5), "p90_ms": pct(0.9), "p99_ms": pct(0.99), "max_ms": round(times[-1], 1),
    }))  # fmt: skip


if __name__ == "__main__":
    main()
