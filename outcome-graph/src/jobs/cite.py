"""Find where each EPA quote sits in the response-to-comments PDF: page number and the paragraph
around it. Writes cites.json next to graph.json, so the ask panel can cite "p. 412" and link to the
PDF at that page.

    uv run python src/jobs/cite.py            # every built rule
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import config  # noqa: E402
from store import ROOT  # noqa: E402

BASE = (config.DATA_ROOT or ROOT / "data/derived") / "outcomes"

RAW = Path(__file__).resolve().parents[3] / "data" / "raw"


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("­", "")
    s = re.sub(r"-\s*\n\s*", "", s)  # words split across lines
    return re.sub(r"\s+", " ", s).strip().lower()


def pages(pdf: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return out.split("\f")


def paragraph(page: str, quote_n: str) -> str:
    """The paragraph on this page holding the start of the quote, as the PDF prints it."""
    paras = [p for p in re.split(r"\n\s*\n", page) if p.strip()]
    key = quote_n[:60]
    for i, p in enumerate(paras):
        if key in norm(p):
            text = re.sub(r"-\s*\n\s*", "", p)
            return re.sub(r"\s+", " ", text).strip()[:1600]
    return ""


def window(para: str, quote: str) -> str:
    """Two sentences before the quote, the quote, one sentence after: enough to read it in context."""
    if not para:
        return ""
    keep = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})
    flat = re.sub(r"\s+", " ", para)
    low = flat.translate(keep).lower()  # same length as flat, so indexes carry over
    qn = re.sub(r"\s+", " ", quote).translate(keep).lower().strip()
    i = low.find(qn[:40])
    if i < 0:
        return ""
    ends = [m.end() for m in re.finditer(r"[.?!][\"')\u201d]?\s", flat[:i])]
    start = ends[-3] if len(ends) >= 3 else 0
    j = low.find(qn[-30:], i)
    j = j + 30 if j >= 0 else i + len(qn)
    after = re.search(r"[.?!][\"')\u201d]?\s", flat[j:])
    stop = min(j + (after.end() if after else len(flat) - j), j + 400)
    return ("… " if start else "") + flat[start:stop].strip() + (" …" if stop < len(flat) else "")


def cite(docket: str) -> dict:
    pdf = RAW / docket / "rtc" / "rtc.pdf"
    det = BASE / docket / "details.json"
    if not pdf.exists() or not det.exists():
        return {}
    pg = pages(pdf)
    flat, starts = [], []
    pos = 0
    for p in pg:
        n = norm(p) + " "
        starts.append(pos)
        flat.append(n)
        pos += len(n)
    whole = "".join(flat)
    details = json.loads(det.read_text())
    out = {}
    for nid, d in details.items():
        if not nid.startswith("ask:") or not d.get("quote"):
            continue
        q = norm(d["quote"])
        i = -1
        for k in (q[:120], q[:60], q[-60:]):
            if len(k) >= 30 and (i := whole.find(k)) >= 0:
                break
        if i < 0:
            continue
        page = max(j for j, s in enumerate(starts) if s <= i)
        para = paragraph(pg[page], q) or paragraph(pg[min(page + 1, len(pg) - 1)], q)
        both = re.sub(r"-\s*\n\s*", "", pg[page] + "\n" + (pg[page + 1] if page + 1 < len(pg) else ""))
        out[nid] = {"page": page + 1, "context": window(para, d["quote"]) or window(both, d["quote"])}
    return out


def main() -> None:
    from store import available

    for docket in available(config.DATA_ROOT):
        c = cite(docket)
        n = sum(1 for k in json.loads((BASE / docket / "details.json").read_text()) if k.startswith("ask:"))
        (BASE / docket / "cites.json").write_text(json.dumps(c, ensure_ascii=False))
        print(f"{docket}: {len(c)} of {n} asks placed, {sum(1 for v in c.values() if v['context'])} with a paragraph")


if __name__ == "__main__":
    main()
