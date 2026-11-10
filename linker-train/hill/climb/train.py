"""Starting submission: the served model's recipe (contrastive fine-tune of bge-small with hard negatives
and the preamble as extra queries), cut to the epochs that fit the time limit."""

import argparse
import time
from pathlib import Path

import yaml

from linker import data as D
from linker.extras import load_extras
from linker.train import TrainConfig, fit

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--time-limit-s", type=int, default=1800)
args = ap.parse_args()
start = time.time()

data = D.load(args.data)
cfg = TrainConfig(**yaml.safe_load((Path(__file__).parent / "configs" / "bge-small.yaml").read_text()))
# About 15 minutes an epoch on an M2 Pro with the preamble queries; keep 5 minutes to score and save.
cfg.epochs = max(1, min(cfg.epochs, (args.time_limit_s - 300) // 900))

pool = D.scored(data.train, data.rules)
train, val = D.split_by_comment(pool, cfg.val_share, cfg.seed)
pre, _ = load_extras(Path(args.data) / "linking-extra")
train += [
    {"qid": f"pre-{d}-{i}", "docket": d, "comment": f"preamble:{d}", "section": w["sections"][0],
     "masked": w["text"]}
    for d in data.multi_section_dockets for i, w in enumerate(pre.get(d, [])) if len(w["sections"]) == 1
]  # fmt: skip

model, history = fit(data, train, val, cfg)
model.save(args.out)
print(f"saved after {time.time() - start:.0f}s, {cfg.epochs} epoch(s)", flush=True)
