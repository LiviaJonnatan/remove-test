"""linker-train: fine-tune the encoder that links comment passages to rule sections, and score it.

    python src/main.py baseline                       # the untuned encoder on the frozen test set
    python src/main.py train --mode in                # train on every docket's training comments
    python src/main.py train --mode lodo              # one model per held-out docket
    python src/main.py report --runs out/in out/lodo  # tables against every saved method
    python src/main.py export --run out/in            # ONNX folder the API serves
    python src/main.py promote --run out/in --serve DIR  # gate, then export to DIR if it passes

Data comes from DATA_ROOT (default ../data/linking; on Vertex AI a gs:// path, read through the
/gcs/ mount). Each run writes OUT_DIR/<name>/: config.json, history.json, predictions.jsonl,
metrics.json and model/ (only for --mode in, the model that can be promoted). Runs log to W&B after
`uv run wandb login` (or with WANDB_API_KEY set).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import fields
from pathlib import Path

import numpy as np
import yaml
from dotenv import load_dotenv

from linker import data as D
from linker.encoder import SectionScorer, rank_sections
from linker.metrics import accuracy, by_docket
from linker.train import TrainConfig, config_dict, device, fit

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent.parent / ".env")
if not os.environ.get("WANDB_API_KEY"):
    os.environ.pop("WANDB_API_KEY", None)  # an empty line in .env would hide a `wandb login`


def data_root(arg: str | None) -> Path:
    """On Vertex AI the bucket is mounted at /gcs/<bucket>/, so a gs:// path is read as that folder."""
    root = arg or os.environ.get("DATA_ROOT") or str(HERE.parent.parent / "data" / "linking")
    if root.startswith("gs://"):
        root = "/gcs/" + root[len("gs://") :]
    return Path(root)


def load_config(path: str | None, overrides: list[str]) -> TrainConfig:
    raw = yaml.safe_load(Path(path).read_text()) if path else {}
    for o in overrides:
        k, v = o.split("=", 1)
        raw[k] = yaml.safe_load(v)
    known = {f.name for f in fields(TrainConfig)}
    unknown = set(raw) - known
    if unknown:
        sys.exit(f"unknown config keys: {sorted(unknown)}")
    return TrainConfig(**raw)


def git_commit() -> str | None:
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True, cwd=HERE
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def wandb_run(name: str, cfg: dict, group: str, tags: list[str]):
    if os.environ.get("WANDB_DISABLED"):
        return None
    import wandb

    if not (os.environ.get("WANDB_API_KEY") or wandb.Api().api_key):  # env, or a `wandb login`
        print("W&B: no key, so this run is not tracked. Run `uv run wandb login` first.")
        return None

    return wandb.init(
        project=os.environ.get("WANDB_PROJECT", "undersigned-linker"),
        name=name,
        group=group,
        config=cfg,
        tags=tags,
        reinit="finish_previous",
    )


def predictions(scorer: SectionScorer, data: D.LinkingSet, passages: list[dict], split: str):
    r = rank_sections(scorer, data.rules, passages)
    rows = []
    for p, rank, top, s in zip(passages, r["ranks"], r["top10"], r["scores"], strict=True):
        srt = np.sort(s)[::-1]
        rows.append(
            {
                "qid": p["qid"],
                "docket": p["docket"],
                "comment": p["comment"],
                "split": split,
                "label": p["section"],
                "rank": rank,
                "top10": top,
                "margin": round(float(srt[0] - srt[1]), 5),
                "top_score": round(float(srt[0]), 5),
            }
        )
    return rows


def write_run(out: Path, cfg: dict, history, preds: list[dict], extra: dict | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    test = [p for p in preds if p["split"] == "test"]
    unc = [p for p in preds if p["split"] == "uncited"]
    metrics = {
        "test": accuracy([p["rank"] for p in test], [p["comment"] for p in test]),
        "test_by_docket": by_docket(
            [p["rank"] for p in test], [p["comment"] for p in test], [p["docket"] for p in test]
        ),
    }
    if unc:
        metrics["uncited"] = accuracy([p["rank"] for p in unc], [p["comment"] for p in unc])
    metrics.update(extra or {})
    (out / "config.json").write_text(json.dumps(cfg, indent=1))
    (out / "history.json").write_text(json.dumps(history, indent=1))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
    with open(out / "predictions.jsonl", "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    return metrics


def log_final(run, metrics: dict, preds: list[dict]):
    if not run:
        return
    t = metrics["test"]
    run.summary.update(
        {
            "test/acc@1": t["acc@1"][0],
            "test/acc@1_lo": t["acc@1"][1],
            "test/acc@1_hi": t["acc@1"][2],
            "test/acc@5": t["acc@5"][0],
            "test/mrr": t["mrr"],
            "test/n": t["n"],
        }
    )
    if "uncited" in metrics:
        run.summary["uncited/acc@1"] = metrics["uncited"]["acc@1"][0]
    for d, m in metrics["test_by_docket"].items():
        run.summary[f"test_by_docket/{d}/acc@1"] = m["acc@1"][0]
    import wandb

    table = wandb.Table(columns=["qid", "docket", "label", "rank", "top1", "margin"])
    for p in preds:
        if p["split"] == "test":
            table.add_data(p["qid"], p["docket"], p["label"], p["rank"], p["top10"][0], p["margin"])
    run.log({"test/predictions": table})


def extras_root(arg: str | None) -> Path:
    root = arg or os.environ.get("EXTRAS_ROOT") or str(HERE.parent.parent / "data" / "linking-extra")
    return Path("/gcs/" + root[len("gs://") :]) if root.startswith("gs://") else Path(root)


def preamble_passages(path: Path, dockets: list[str]) -> list[dict]:
    """Preamble windows that discuss exactly one section, as training passages labelled with it. They
    come with the rule, so a held-out docket's preamble is fair to train on."""
    from linker.extras import load_extras

    pre, _ = load_extras(path)
    if not pre:
        sys.exit(f"preamble_queries is on but {path} has no preamble/; run `python src/main.py extras`")
    return [
        {"qid": f"pre-{d}-{i}", "docket": d, "comment": f"preamble:{d}", "section": w["sections"][0],
         "masked": w["text"]}
        for d in dockets for i, w in enumerate(pre.get(d, [])) if len(w["sections"]) == 1
    ]  # fmt: skip


def cmd_baseline(args):
    from sentence_transformers import SentenceTransformer

    data = D.load(data_root(args.data))
    model = SentenceTransformer(args.model, device=device())
    model.max_seq_length = 384
    scorer = SectionScorer(model)
    test, unc = D.scored(data.test, data.rules), D.scored(data.uncited, data.rules)
    preds = predictions(scorer, data, test, "test") + predictions(scorer, data, unc, "uncited")
    m = write_run(Path(args.out), {"model": args.model, "trained": False}, [], preds)
    print(json.dumps(m["test"]), json.dumps(m.get("uncited")))


def cmd_train(args):
    cfg = load_config(args.config, args.set)
    data = D.load(data_root(args.data))
    multi = data.multi_section_dockets
    pool = D.scored(data.train, data.rules)
    test, unc = D.scored(data.test, data.rules), D.scored(data.uncited, data.rules)
    out = Path(args.out)
    meta = {
        "commit": git_commit(),
        "data_root": str(args.data or os.environ.get("DATA_ROOT", "")),
        "device": device(),
        "mode": args.mode,
        "n_train_pool": len(pool),
        "vertex_job": os.environ.get("CLOUD_ML_JOB_ID"),
    }
    group = args.group or f"{args.mode}-{time.strftime('%m%d-%H%M')}"

    if args.mode == "in":
        train, val = D.split_by_comment(pool, cfg.val_share, cfg.seed)
        if cfg.preamble_queries:
            train = train + preamble_passages(extras_root(args.extras), multi)
        cfgd = {**config_dict(cfg), **meta, "n_train": len(train), "n_val": len(val)}
        run = wandb_run(args.name or "in", cfgd, group, ["in", *args.tag])
        model, hist = fit(data, train, val, cfg, run)
        scorer = SectionScorer(model)
        preds = (predictions(scorer, data, test, "test") + predictions(scorer, data, unc, "uncited")
                 + predictions(scorer, data, val, "val"))
        m = write_run(out, cfgd, hist, preds)
        model.save(str(out / "model"))
        log_final(run, m, preds)
        print(json.dumps(m["test"]))
        if args.combine:
            combine_run(args, out, run)
        if run:
            run.finish()
        return

    # Leave one docket out: the setting of a new rule nobody has labelled.
    all_preds, hists = [], {}
    targets = [args.holdout] if args.holdout else multi
    for d in targets:
        others = [p for p in pool if p["docket"] != d]
        train, val = D.split_by_comment(others, cfg.val_share, cfg.seed)
        if cfg.preamble_queries:
            train = train + preamble_passages(extras_root(args.extras), multi)
        cfgd = {**config_dict(cfg), **meta, "holdout": d, "n_train": len(train), "n_val": len(val)}
        run = wandb_run(f"lodo-{d}", cfgd, group, ["lodo", *args.tag])
        model, hist = fit(data, train, val, cfg, run)
        scorer = SectionScorer(model)
        preds = predictions(scorer, data, [p for p in test if p["docket"] == d], "test") + predictions(
            scorer, data, [p for p in unc if p["docket"] == d], "uncited"
        ) + predictions(scorer, data, val, "val")
        m = write_run(out / d, cfgd, hist, preds)
        if args.holdout:
            model.save(str(out / d / "model"))
        log_final(run, m, preds)
        print(d, json.dumps(m["test"]["acc@1"]), flush=True)
        if args.combine and args.holdout:
            combine_run(args, out / d, run)
        if run:
            run.finish()
        all_preds += preds
        hists[d] = hist
        del model, scorer
    m = write_run(out, {**config_dict(cfg), **meta, "holdouts": targets}, hists, all_preds)
    print("pooled", json.dumps(m["test"]))


def cmd_export(args):
    from linker.export import export

    run = Path(args.run)
    data = D.load(data_root(args.data))
    texts = [D.query_text(p) for p in data.test[:32]] + [
        w.text for w in data.rules[data.test[0]["docket"]].windows[:32]
    ]
    metrics = json.loads((run / "metrics.json").read_text())
    config = json.loads((run / "config.json").read_text())
    # Margin below which a passage goes to the reader model: the least sure share of test passages.
    margins = [
        json.loads(line)["margin"]
        for line in (run / "predictions.jsonl").read_text().splitlines()
        if json.loads(line)["split"] == "test"
    ]
    info = {
        "run": run.name,
        "commit": config.get("commit"),
        "base_model": config.get("base_model"),
        "test_acc@1": metrics["test"]["acc@1"],
        "query_prefix": D.QUERY_PREFIX,
        "query_max_words": D.QUERY_MAX_WORDS,
        "reader_share": args.reader_share,
        "margin_cutoff": round(float(np.quantile(margins, args.reader_share)), 4),
    }
    print(json.dumps(export(run / "model", Path(args.out), texts, info), indent=1))


def cmd_promote(args):
    """Gate a run against hybrid search and the served model; export it to --serve if it passes."""
    import shutil

    from linker.promote import decide

    run, serve = Path(args.run), Path(args.serve)
    decision = decide(data_root(args.data), run, serve if serve.exists() else None)
    print(json.dumps(decision, indent=1))
    (run / "promotion.json").write_text(json.dumps(decision, indent=1))
    if not decision["promote"]:
        return
    staged = run / "onnx"
    args.out = str(staged)
    cmd_export(args)
    if serve.exists():
        shutil.rmtree(serve)
    shutil.copytree(staged, serve)
    print(f"promoted {run.name} to {serve}")


def cmd_extras(args):
    from linker.extras import build

    print(json.dumps(build(Path(args.src), data_root(args.data), Path(args.out)), indent=1))


def combine_run(args, run_dir: Path, run=None) -> dict:
    """combine on a run just trained, writing <run_dir>+ctx next to it, and log it to the same W&B run."""
    from linker.combine import combine

    res = combine(data_root(args.data), extras_root(args.extras), run_dir, Path(str(run_dir) + "+ctx"))
    print("combined", json.dumps({k: v["acc@1"] for k, v in res["crossfit"].items()}), flush=True)
    if run:
        for k, v in res["crossfit"].items():
            run.summary[f"combined/{k}/acc@1"] = v["acc@1"][0]
            run.summary[f"combined/{k}/minus_encoder"] = v["minus_encoder"][0]
    return res


def cmd_combine(args):
    from linker.combine import combine

    run = Path(args.run)
    out = Path(args.out) if args.out else run / "combined"
    res = combine(data_root(args.data), extras_root(args.extras), run, out)
    print(json.dumps({k: res[k] for k in ("weights", "val", "test")}, indent=1))


def cmd_report(args):
    from linker.report import report

    report(data_root(args.data), [Path(r) for r in args.runs], Path(args.out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", help="frozen linking set (folder or gs:// path)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline")
    b.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    b.add_argument("--out", default="out/baseline")
    t = sub.add_parser("train")
    t.add_argument("--mode", choices=["in", "lodo"], default="in")
    t.add_argument("--holdout", help="with --mode lodo, only this docket")
    t.add_argument("--config", default=str(HERE.parent / "configs" / "bge-small.yaml"))
    t.add_argument("--set", action="append", default=[], help="override, e.g. --set epochs=2")
    t.add_argument("--out", default=os.environ.get("OUT_DIR", "out/run"))
    t.add_argument("--name")
    t.add_argument("--group")
    t.add_argument("--tag", action="append", default=[])
    t.add_argument("--extras", help="data/linking-extra (preamble windows, letter citations)")
    t.add_argument("--combine", action="store_true", help="then run combine on the trained model")
    x = sub.add_parser("extras", help="build preamble windows and letter citations from the 11 Oct data")
    x.add_argument("--src", required=True, help="the 11 Oct linking test's data folder")
    x.add_argument("--out", default=str(HERE.parent.parent / "data" / "linking-extra"))
    c = sub.add_parser("combine", help="add preamble and letter-citation scores, weights picked on val")
    c.add_argument("--run", required=True, help="a run folder with model/")
    c.add_argument("--extras")
    c.add_argument("--out", help="default <run>/combined")
    e = sub.add_parser("export", help="ONNX folder for the API, checked against the trained model")
    e.add_argument("--run", default="out/in")
    e.add_argument("--out", default="out/in/onnx")
    e.add_argument("--reader-share", type=float, default=0.2, help="share of passages flagged unsure")
    pr = sub.add_parser("promote", help="gate a run, and export it to the serving folder if it passes")
    pr.add_argument("--run", required=True)
    pr.add_argument("--serve", required=True, help="the folder the API's deploy reads, e.g. a /gcs/ path")
    pr.add_argument("--reader-share", type=float, default=0.2)
    r = sub.add_parser("report")
    r.add_argument("--runs", nargs="+", required=True)
    r.add_argument("--out", default="out/report")
    args = ap.parse_args(argv)
    {
        "baseline": cmd_baseline,
        "train": cmd_train,
        "export": cmd_export,
        "promote": cmd_promote,
        "report": cmd_report,
        "extras": cmd_extras,
        "combine": cmd_combine,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
