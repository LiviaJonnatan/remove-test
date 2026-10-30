"""Pinned bge-small tokenizer, with full sequence lengths for the 512-token audit."""

import hashlib
from pathlib import Path

from tokenizers import Tokenizer

BGE_TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
BGE_TOKENIZER_URL = "https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/main/tokenizer.json"


def load_token_counter(tokenizer_path: Path, *, verify_model=True):
    if verify_model and hashlib.sha256(tokenizer_path.read_bytes()).hexdigest() != (
        BGE_TOKENIZER_SHA256
    ):
        raise ValueError("unexpected_bge_tokenizer_checksum")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return lambda text: len(tokenizer.encode(text, add_special_tokens=True).ids)
