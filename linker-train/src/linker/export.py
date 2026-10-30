"""Turn a trained encoder into the ONNX folder the API loads with fastembed, and check it.

The API image has no PyTorch: rule-passages and api-service run bge-small through ONNX. Exporting the
tuned copy the same way means serving it needs no new dependency. The export is checked against the
PyTorch model on real passages before it is written as servable.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import torch

TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt")
MAX_COSINE_GAP = 1e-3


class _Encoder(torch.nn.Module):
    """The transformer alone; fastembed does the CLS pooling and normalization itself."""

    def __init__(self, transformer):
        super().__init__()
        self.t = transformer

    def forward(self, input_ids, attention_mask, token_type_ids):
        return self.t(
            input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids
        ).last_hidden_state


def export(model_dir: Path, out: Path, check_texts: list[str], info: dict) -> dict:
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModel, AutoTokenizer

    out.mkdir(parents=True, exist_ok=True)
    st = SentenceTransformer(str(model_dir), device="cpu")
    tok = AutoTokenizer.from_pretrained(model_dir)
    # Serve with the length it was trained and scored with, not the model's 512.
    tok.model_max_length = st.max_seq_length
    hf = AutoModel.from_pretrained(model_dir).eval()
    sample = tok(["a sample passage"], return_tensors="pt")
    torch.onnx.export(
        _Encoder(hf),
        (sample["input_ids"], sample["attention_mask"], sample["token_type_ids"]),
        str(out / "model.onnx"),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["last_hidden_state"],
        opset_version=17,
        dynamo=False,
        dynamic_axes={
            n: {0: "batch", 1: "seq"}
            for n in ("input_ids", "attention_mask", "token_type_ids", "last_hidden_state")
        },
    )
    tok.save_pretrained(out)
    shutil.copy(model_dir / "config.json", out / "config.json")

    # Check: the ONNX graph with CLS pooling and normalization against the PyTorch model.
    import onnxruntime as ort

    sess = ort.InferenceSession(str(out / "model.onnx"))
    ref = st.encode(check_texts, normalize_embeddings=True)
    enc = tok(check_texts, padding=True, truncation=True, max_length=st.max_seq_length, return_tensors="np")
    hidden = sess.run(
        None, {k: enc[k].astype(np.int64) for k in ("input_ids", "attention_mask", "token_type_ids")}
    )[0]
    cls = hidden[:, 0]
    cls /= np.linalg.norm(cls, axis=1, keepdims=True)
    gap = float(1 - (cls * ref).sum(axis=1).min())
    if gap > MAX_COSINE_GAP:
        raise RuntimeError(f"ONNX export differs from the trained model: cosine gap {gap:.2e}")
    manifest = {
        **info,
        "max_length": st.max_seq_length,
        "pooling": "CLS",
        "normalize": True,
        "dim": int(ref.shape[1]),
        "parity_texts": len(check_texts),
        "parity_max_cosine_gap": gap,
    }
    (out / "linker.json").write_text(json.dumps(manifest, indent=1))
    return manifest
