"""Send the frozen test passages of one docket to a running API's /link and score the answers.

    python scripts/link_check.py --api http://localhost:8000 --docket EPA-HQ-OW-2022-0801
    ID_TOKEN="$(gcloud auth print-identity-token)" python scripts/link_check.py --api "$URL"   # Cloud Run

Checks that the served model (ONNX through fastembed, the API's own rule chunks) scores like the
evaluation in linker-train did. Writes a JSON summary next to the evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--docket", default="EPA-HQ-OW-2022-0801")
    ap.add_argument("--out", default=str(ROOT / "docs/evidence/linker-train/link-check.json"))
    args = ap.parse_args()
    test = json.loads((ROOT / "data/linking/test.json").read_text())
    test = [p for p in test if p["docket"] == args.docket]
    top1 = top5 = reader = 0
    lat = []
    for p in test:
        text = re.sub(r"\[(CITATION|NUM|PARA|PART|HEADING)\]", " ", p["masked"])
        body = json.dumps({"text": text, "docket_id": args.docket, "k": 5}).encode()
        headers = {"Content-Type": "application/json"}
        if token := os.environ.get("ID_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{args.api}/link", data=body, headers=headers)
        t = time.perf_counter()
        out = json.load(urllib.request.urlopen(req))
        lat.append((time.perf_counter() - t) * 1000)
        got = [s["section_ref"].split("§ ")[-1] for s in out["sections"]]
        top1 += got[0] == p["section"]
        top5 += p["section"] in got
        reader += out["needs_reader"]
    lat.sort()
    n = len(test)
    summary = {"api": args.api, "docket": args.docket, "n": n, "top1": round(top1 / n, 4),
               "top5": round(top5 / n, 4), "needs_reader_share": round(reader / n, 4),
               "latency_ms_p50": round(lat[n // 2], 1), "latency_ms_p90": round(lat[int(0.9 * n)], 1),
               "model": out["model"]}
    Path(args.out).write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
