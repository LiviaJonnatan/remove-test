"""Build the undersigned-linker hill and a climbing workspace that holds no held-out labels.

    python linker-train/hill/build.py --out ~/Downloads/undersigned-climb

Creates <out>/ as its own git repo with the starting submission (train.py, configs/, a copy of the
linker package) and the hill in <out>/.autolab/hills/undersigned-linker/. The held-out passages go to
the hill's private/; the climbing workspace never contains them or the frozen test set.

Validation split: 15% of training letters (seed 2026), minus any passage whose 8-word shingles mostly
appear in the letters left for training, so a copy of a form letter cannot be scored as held out.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = REPO / "linker-train" / "src"
sys.path.insert(0, str(SRC))

from linker import data as D  # noqa: E402

VAL_SHARE, SEED, SHINGLE, OVERLAP = 0.15, 2026, 8, 0.5
HILL_FILES = ["eval.py", "scoring.py", "hill.yaml", "pyproject.toml", "README.md"]
KEEP = ["qid", "docket", "comment", "section", "masked"]  # what the evaluator needs of a held-out passage


def shingles(text: str) -> set[str]:
    w = re.findall(r"[a-z0-9]+", D.clean(text).lower())
    return {" ".join(w[i : i + SHINGLE]) for i in range(max(1, len(w) - SHINGLE + 1))}


def split(pool: list[dict]) -> tuple[list[dict], list[dict], int]:
    letters = sorted({p["comment"] for p in pool})
    random.Random(SEED).shuffle(letters)
    held = set(letters[: round(len(letters) * VAL_SHARE)])
    train = [p for p in pool if p["comment"] not in held]
    seen = set().union(*(shingles(p["masked"]) for p in train))
    val, dropped = [], 0
    for p in pool:
        if p["comment"] not in held:
            continue
        s = shingles(p["masked"])
        if len(s & seen) / len(s) > OVERLAP:
            dropped += 1
        else:
            val.append(p)
    return train, val, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out).expanduser()
    src = REPO / "data" / "linking"
    extra = REPO / "data" / "linking-extra"
    data = D.load(src)

    pool = D.scored(data.train, data.rules)
    train, val, dropped = split(pool)
    test = D.scored(data.test, data.rules)
    # Training passages that cite no multi-section rule stay in train.json as the project has them.
    held_letters = {p["comment"] for p in val} | {p["comment"] for p in pool if p not in train}
    train_all = [p for p in data.train if p["comment"] not in held_letters]

    out.mkdir(parents=True, exist_ok=True)
    if not (out / ".git").exists():
        subprocess.run(["git", "init", "-q", str(out)], check=True)
    # Starting submission
    shutil.copy(HERE / "climb" / "train.py", out / "train.py")
    shutil.copytree(REPO / "linker-train" / "configs", out / "configs", dirs_exist_ok=True)
    shutil.copytree(SRC / "linker", out / "linker", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))  # fmt: skip
    (out / ".gitignore").write_text("__pycache__/\n*.pyc\nruns/\n")

    hill = out / ".autolab" / "hills" / "undersigned-linker"
    if not hill.exists():
        subprocess.run(["hills", "new", "undersigned-linker"], cwd=out, check=True)
    for f in ("prepare_data.py",):
        (hill / f).unlink(missing_ok=True)
    shutil.rmtree(hill / "examples", ignore_errors=True)
    shutil.rmtree(hill / "tests", ignore_errors=True)
    for f in HILL_FILES:
        shutil.copy(HERE / f, hill / f)
    shutil.copytree(HERE / "examples", hill / "examples")
    shutil.copytree(HERE / "tests", hill / "tests")

    d = hill / "data"
    shutil.rmtree(d, ignore_errors=True)
    (d / "rules").mkdir(parents=True)
    for f in (src / "rules").glob("*.json"):
        shutil.copy(f, d / "rules" / f.name)
    (d / "train.json").write_text(json.dumps(train_all))
    (d / "test.json").write_text("[]")
    (d / "uncited.json").write_text("[]")
    shutil.copytree(extra / "preamble", d / "linking-extra" / "preamble")
    cites = json.loads((extra / "letter_citations.json").read_text())
    keep = {p["qid"] for p in train_all}
    (d / "linking-extra" / "letter_citations.json").write_text(
        json.dumps({q: v for q, v in cites.items() if q in keep})
    )

    priv = hill / "private"
    priv.mkdir(exist_ok=True)
    (priv / "val.json").write_text(json.dumps([{k: p[k] for k in KEEP} for p in val]))
    (priv / "test.json").write_text(json.dumps([{k: p[k] for k in KEEP} for p in test]))

    summary = {
        "train_passages": len(train_all), "train_scored": len(train),
        "val_passages": len(val), "val_letters": len({p["comment"] for p in val}),
        "val_dropped_as_copies": dropped, "test_passages": len(test),
        "test_letters": len({p["comment"] for p in test}),
    }  # fmt: skip
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
