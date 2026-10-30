"""Contrastive fine-tune of the serving encoder on free citation labels.

Each training passage is pulled toward the best window of the section its author cited and pushed away
from the windows of other sections the current model ranks highest (hard negatives, mined again each
epoch), plus every other passage's windows in the batch. The loss is the usual in-batch softmax
(multiple-negatives ranking) over cosine similarities.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass

import numpy as np
import torch
import torch.nn.functional as F

from linker.data import LinkingSet, Rule, query_text
from linker.encoder import SectionScorer, rank_sections
from linker.metrics import accuracy


@dataclass
class TrainConfig:
    base_model: str = "BAAI/bge-small-en-v1.5"
    epochs: int = 4
    batch_size: int = 32
    hard_negatives: int = 3
    lr: float = 3e-5
    warmup: float = 0.1
    weight_decay: float = 0.01
    scale: float = 20.0
    max_seq_length: int = 384
    remine_each_epoch: bool = True
    grad_chunk: int = 16  # texts per backward pass; memory, not the result, depends on it
    val_share: float = 0.1
    limit_train: int = 0  # 0 = all; a small number for a quick check of the whole loop
    preamble_queries: bool = False  # add the rule's own preamble paragraphs as training queries (extras.py)
    seed: int = 13


@dataclass
class Example:
    query: str
    positive: str
    negatives: list[str]
    key: tuple[str, str]  # (docket, section) of the positive
    negative_keys: list[tuple[str, str]]


def device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def mine(scorer: SectionScorer, rules: dict[str, Rule], passages: list[dict], n_neg: int) -> list[Example]:
    """Positive: the cited section's best window under the current model. Negatives: the best
    windows of the n_neg highest-scoring other sections."""
    out = []
    by_docket: dict[str, list[dict]] = {}
    for p in passages:
        by_docket.setdefault(p["docket"], []).append(p)
    for d, ps in by_docket.items():
        rule = rules[d]
        ws = np.asarray(rule.window_section)
        W = scorer.window_scores(rule, ps)
        for p, row in zip(ps, W, strict=True):
            label = rule.sections.index(p["section"])
            own = np.where(ws == label)[0]
            pos = own[np.argmax(row[own])]
            best_other: dict[int, int] = {}
            for j in np.argsort(-row):
                s = int(ws[j])
                if s != label and s not in best_other:
                    best_other[s] = int(j)
                if len(best_other) == n_neg:
                    break
            out.append(Example(
                query_text(p), rule.windows[pos].text,
                [rule.windows[j].text for j in best_other.values()], (d, p["section"]),
                [(d, rule.sections[s]) for s in best_other],
            ))
    return out


def batches(examples: list[Example], size: int, rng: random.Random) -> list[list[Example]]:
    pool = examples[:]
    rng.shuffle(pool)
    return [pool[i : i + size] for i in range(0, len(pool), size)]


def false_negatives(batch: list[Example]) -> torch.Tensor:
    """n_queries x n_docs, True where a document belongs to the query's own section but is not its
    positive: another passage citing the same section. Those are masked out of the softmax, not
    scored as negatives."""
    doc_keys = [e.key for e in batch] + [k for e in batch for k in e.negative_keys]
    mask = torch.tensor([[dk == e.key for dk in doc_keys] for e in batch])
    mask[torch.arange(len(batch)), torch.arange(len(batch))] = False
    return mask


def embed(model, texts: list[str], dev: str) -> torch.Tensor:
    feats = model.tokenize(texts)
    feats = {k: v.to(dev) for k, v in feats.items() if hasattr(v, "to")}
    return F.normalize(model(feats)["sentence_embedding"], dim=-1)


def contrastive_step(model, batch: list[Example], cfg: TrainConfig, dev: str) -> float:
    """One batch of the in-batch softmax loss, with cached gradients (Gao et al., 2021).

    Every text is embedded once without a graph, the loss and its gradient with respect to the
    embeddings are taken on the full batch, then each chunk is embedded again with a graph and given
    that gradient. Memory is one chunk's worth whatever the batch size, and the gradient is the same as
    a full-batch backward. Dropout is off (the model stays in eval mode), so the two passes agree.
    """
    queries = [e.query for e in batch]
    docs = [e.positive for e in batch] + [n for e in batch for n in e.negatives]
    chunk = cfg.grad_chunk
    with torch.no_grad():
        q = torch.cat([embed(model, queries[i : i + chunk], dev) for i in range(0, len(queries), chunk)])
        d = torch.cat([embed(model, docs[i : i + chunk], dev) for i in range(0, len(docs), chunk)])
    q.requires_grad_(True)
    d.requires_grad_(True)
    logits = (cfg.scale * q @ d.T).masked_fill(false_negatives(batch).to(dev), float("-inf"))
    loss = F.cross_entropy(logits, torch.arange(len(batch), device=dev))
    loss.backward()
    for texts, grads in ((queries, q.grad), (docs, d.grad)):
        for i in range(0, len(texts), chunk):
            e = embed(model, texts[i : i + chunk], dev)
            e.backward(grads[i : i + chunk])
    return loss.item()


def evaluate(scorer: SectionScorer, data: LinkingSet, passages: list[dict]) -> dict:
    scorer.forget()
    r = rank_sections(scorer, data.rules, passages)
    return accuracy(r["ranks"], [p["comment"] for p in passages], draws=200)


def fit(data: LinkingSet, train: list[dict], val: list[dict], cfg: TrainConfig, run=None, log=print):
    """Train in place and return (model, history). `run` is a W&B run or None."""
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(cfg.seed)
    rng = random.Random(cfg.seed)
    dev = device()
    model = SentenceTransformer(cfg.base_model, device=dev)
    model.max_seq_length = cfg.max_seq_length
    scorer = SectionScorer(model)

    history = []
    base = evaluate(scorer, data, val)
    history.append({"epoch": 0, "val": base})
    log(f"epoch 0  val acc@1 {base['acc@1'][0]:.3f}  acc@5 {base['acc@5'][0]:.3f}")
    if run:
        run.log({"epoch": 0, "val/acc@1": base["acc@1"][0], "val/acc@5": base["acc@5"][0],
                 "val/mrr": base["mrr"]})

    if cfg.limit_train:
        train = random.Random(cfg.seed).sample(train, min(cfg.limit_train, len(train)))
        val = val[: cfg.limit_train]
    model.eval()
    examples = mine(scorer, data.rules, train, cfg.hard_negatives)
    steps_per_epoch = math.ceil(len(examples) / cfg.batch_size)
    total = steps_per_epoch * cfg.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    warm = max(1, int(cfg.warmup * total))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (total - s) / max(1, total - warm))
    )
    best_state, best_acc, step = None, -1.0, 0
    for epoch in range(1, cfg.epochs + 1):
        if epoch > 1 and cfg.remine_each_epoch:
            model.eval()
            scorer.forget()
            with torch.no_grad():
                examples = mine(scorer, data.rules, train, cfg.hard_negatives)
        t0, losses = time.time(), []
        for batch in batches(examples, cfg.batch_size, rng):
            opt.zero_grad()
            losses.append(contrastive_step(model, batch, cfg, dev))
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            if run and step % 10 == 0:
                run.log({"train/loss": float(np.mean(losses[-10:])), "train/lr": sched.get_last_lr()[0],
                         "step": step})
        model.eval()
        with torch.no_grad():
            v = evaluate(scorer, data, val)
        rec = {"epoch": epoch, "loss": float(np.mean(losses)), "seconds": round(time.time() - t0, 1),
               "val": v}
        history.append(rec)
        log(f"epoch {epoch}  loss {rec['loss']:.4f}  val acc@1 {v['acc@1'][0]:.3f}  "
            f"acc@5 {v['acc@5'][0]:.3f}  {rec['seconds']}s")
        if run:
            run.log({"epoch": epoch, "train/epoch_loss": rec["loss"], "val/acc@1": v["acc@1"][0],
                     "val/acc@5": v["acc@5"][0], "val/mrr": v["mrr"], "step": step})
        if v["acc@1"][0] > best_acc:
            best_acc = v["acc@1"][0]
            best_state = {k: t.detach().cpu().clone() for k, t in model.state_dict().items()}
            history[-1]["best"] = True
    model.load_state_dict(best_state)
    scorer.forget()
    return model, history


def config_dict(cfg: TrainConfig) -> dict:
    return asdict(cfg)
