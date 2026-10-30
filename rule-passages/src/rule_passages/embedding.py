"""Sentence embeddings from bge-small-en-v1.5, run through ONNX so the image needs no PyTorch."""

from __future__ import annotations

import os
from typing import Protocol

MODEL_NAME = "BAAI/bge-small-en-v1.5"
# BGE retrieval models expect this instruction in front of a query, and none in front of a passage.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class BgeEmbedder:
    def __init__(self, model_name: str = MODEL_NAME, cache_dir: str | None = None):
        from fastembed import TextEmbedding  # imported here so tests can run without the model

        self.model_name = model_name
        self._model = TextEmbedding(
            model_name=model_name, cache_dir=cache_dir or os.environ.get("FASTEMBED_CACHE_PATH")
        )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([QUERY_PREFIX + text]))).tolist()
