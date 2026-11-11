"""Checks on the hill itself, run by `hills check`. Each runs the real evaluator on a real subprocess."""

import json
import textwrap
from pathlib import Path

import pytest
from hills import run_evaluator

HILL = Path(__file__).resolve().parents[1]
UNTUNED = HILL / "examples" / "untuned"
LIMIT = 300

pytestmark = pytest.mark.skipif(not (HILL / "private" / "val.json").is_file(),
                                reason="private/val.json missing; run build.py")  # fmt: skip


def submission(tmp_path: Path, body: str) -> Path:
    (tmp_path / "train.py").write_text(textwrap.dedent(body))
    return tmp_path


def test_untuned_scores_like_the_old_served_model():
    r = run_evaluator(HILL, UNTUNED, time_limit_s=LIMIT)
    assert r["passed"], r["details"]
    assert [m["name"] for m in r["metrics"]] == ["acc@1", "acc@5", "mrr"]
    # The untuned encoder got 44.7% on the frozen test; held-out training letters read a little higher.
    assert 0.35 < r["metrics"][0]["value"] < 0.65
    assert {c["name"] for c in r["config"] if c["primary"]} == {"device", "time_limit_s", "mode"}


def test_missing_train_py_is_rejected(tmp_path):
    r = run_evaluator(HILL, tmp_path, time_limit_s=LIMIT)
    assert not r["passed"] and "train.py" in r["details"]["error"]


def test_no_model_is_rejected(tmp_path):
    r = run_evaluator(HILL, submission(tmp_path, "print('trained, honest')\n"), time_limit_s=LIMIT)
    assert not r["passed"] and "SentenceTransformer" in r["details"]["error"]
    assert "trained, honest" in r["details"]["train_log_tail"]


def test_bigger_encoder_is_rejected(tmp_path):
    body = """
        import argparse, json, pathlib
        from sentence_transformers import SentenceTransformer
        ap = argparse.ArgumentParser(); ap.add_argument("--data"); ap.add_argument("--out")
        ap.add_argument("--time-limit-s"); a = ap.parse_args()
        SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").save(a.out)
        p = pathlib.Path(a.out) / "config.json"; c = json.loads(p.read_text())
        c["num_hidden_layers"] = 24; p.write_text(json.dumps(c))
    """
    r = run_evaluator(HILL, submission(tmp_path, body), time_limit_s=LIMIT)
    assert not r["passed"] and "12 layers" in r["details"]["error"]
