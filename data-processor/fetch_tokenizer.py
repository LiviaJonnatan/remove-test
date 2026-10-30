"""One-time download of the pinned tokenizer only; no embedding model weights."""

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

from src.tokenization import BGE_TOKENIZER_SHA256, BGE_TOKENIZER_URL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with urlopen(BGE_TOKENIZER_URL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != BGE_TOKENIZER_SHA256:
        raise ValueError("Tokenizer changed upstream; review before updating the pin.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"Saved verified bge-small tokenizer to {args.out}")


if __name__ == "__main__":
    main()
