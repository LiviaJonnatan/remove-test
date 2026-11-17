"""Evaluator for undersigned-linker.

Owns the clock and the metric. Launches the submitted train.py with the training data, kills it at the
deadline, loads the encoder it saved, and ranks held-out passages with the frozen scoring in scoring.py,
the same ranking the API serves. The held-out passages live under private/ and are only read here.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch
from scoring import MAX_SEQ_LENGTH, ranks

HILL = Path(__file__).resolve().parent
DATA = HILL / "data"
VAL = HILL / "private" / "val.json"
TEST = HILL / "private" / "test.json"
LOG_TAIL_LINES = 40
# What the API's ONNX export expects: bge-small's shape and its three modules, nothing added.
HIDDEN, LAYERS = 384, 12
MODULES = ["Transformer", "Pooling", "Normalize"]  # class names; the module path moved in s-t 6
# Secrets the training run must not see: no calls to hosted models, no logging out.
DROP_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "WANDB_API_KEY",
            "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")  # fmt: skip


def device_profile() -> str:
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        slug = "".join(ch if ch.isalnum() else "-" for ch in p.name.lower()).strip("-")
        return f"{slug}-{round(p.total_memory / 1024**3)}gb"
    if torch.backends.mps.is_available():
        return "apple-mps"
    return "cpu"


def device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def fail(reason: str, config: list[dict], **details) -> dict:
    return {"passed": False, "metrics": [], "config": config, "details": {"error": reason, **details}}


def tail(path: Path) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:])


def run_training(submission: Path, out: Path, time_limit_s: int, log_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env.update({"PYTHONPATH": str(submission), "WANDB_MODE": "disabled", "TOKENIZERS_PARALLELISM": "false"})
    cmd = [sys.executable, "train.py", "--data", str(DATA), "--out", str(out),
           "--time-limit-s", str(time_limit_s)]  # fmt: skip
    started = time.perf_counter()
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, cwd=submission, stdout=log, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)  # fmt: skip
        try:
            proc.wait(timeout=time_limit_s)
            killed = False
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()
            killed = True
    return {"elapsed_s": round(time.perf_counter() - started, 1), "killed_at_limit": killed,
            "exit_code": proc.returncode}  # fmt: skip


def check_shape(model_dir: Path) -> str | None:
    """None if the saved encoder is one the API can serve, else why not."""
    try:
        cfg = json.loads((model_dir / "config.json").read_text())
        mods_raw = json.loads((model_dir / "modules.json").read_text())
        mods = [m["type"].rsplit(".", 1)[-1] for m in mods_raw]
        pool = (
            json.loads((model_dir / mods_raw[1]["path"] / "config.json").read_text())
            if len(mods) > 1 else {}
        )
    except (OSError, ValueError, KeyError) as e:
        return f"model/ is not a saved SentenceTransformer folder ({e})"
    if (cfg.get("hidden_size"), cfg.get("num_hidden_layers")) != (HIDDEN, LAYERS):
        return (f"encoder must keep bge-small's size ({HIDDEN} hidden, {LAYERS} layers), got "
                f"{cfg.get('hidden_size')} hidden, {cfg.get('num_hidden_layers')} layers")  # fmt: skip
    if mods != MODULES:
        return f"modules must be exactly Transformer, Pooling, Normalize; got {mods}"
    cls = pool.get("pooling_mode") == "cls" or (  # s-t 6 writes pooling_mode; older versions, flags
        pool.get("pooling_mode_cls_token") and not pool.get("pooling_mode_mean_tokens"))
    if not cls:
        return "pooling must stay CLS-token pooling, as bge-small and the API's ONNX export use"
    return None


def eval(submission: Path, *, final: bool = False, time_limit_s: int = 1800) -> dict:
    config = [
        {"name": "device", "value": device_profile(), "primary": True},
        {"name": "time_limit_s", "value": time_limit_s, "primary": True},
        {"name": "mode", "value": "test" if final else "validation", "primary": True},
        {"name": "torch", "value": torch.__version__, "primary": False},
    ]
    if not (submission / "train.py").is_file():
        return fail("submission must contain train.py at its root", config)

    parent = Path(os.environ.get("HILLS_RUN_DIR", tempfile.gettempdir()))
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="train-", dir=parent))
    out = work / "model"
    log_path = work / "train.log"
    timing = run_training(submission, out, time_limit_s, log_path)

    why = check_shape(out)
    if why:
        return fail(f"{why}. Save the encoder to --out before the deadline: the process is killed at it.",
                    config, training=timing, train_log_tail=tail(log_path))  # fmt: skip

    from sentence_transformers import SentenceTransformer

    try:
        model = SentenceTransformer(str(out), device=device())
    except Exception as e:  # noqa: BLE001 - any load failure is the submission's
        return fail(f"model/ could not be loaded: {e}", config, training=timing,
                    train_log_tail=tail(log_path))  # fmt: skip
    model.max_seq_length = MAX_SEQ_LENGTH
    model.eval()

    passages = json.loads((TEST if final else VAL).read_text())
    with torch.no_grad():
        r = np.asarray(ranks(model, DATA / "rules", passages))
    per_docket = {}
    for d in sorted({p["docket"] for p in passages}):
        m = np.asarray([p["docket"] == d for p in passages])
        per_docket[d] = {"n": int(m.sum()), "acc@1": round(float((r[m] == 1).mean()), 4)}
    return {
        "passed": True,
        "metrics": [
            {"name": "acc@1", "value": round(float((r == 1).mean()), 4), "direction": "max"},
            {"name": "acc@5", "value": round(float((r <= 5).mean()), 4), "direction": "max"},
            {"name": "mrr", "value": round(float((1.0 / r).mean()), 4), "direction": "max"},
        ],
        "config": config,
        "details": {"n": len(passages), "acc@3": round(float((r <= 3).mean()), 4),
                    "by_docket": per_docket, "training": timing, "train_log_tail": tail(log_path)},
    }  # fmt: skip
