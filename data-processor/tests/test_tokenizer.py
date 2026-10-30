import os
from pathlib import Path

import pytest

from tokenization import load_token_counter


def test_wrong_tokenizer_asset_is_rejected(tmp_path):
    path = tmp_path / "tokenizer.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="unexpected_bge_tokenizer_checksum"):
        load_token_counter(path)


def test_real_bge_asset_when_available():
    path = os.getenv("BGE_TOKENIZER_TEST_PATH")
    if not path:
        pytest.skip("optional real tokenizer check; offline unit tests need no download")
    count = load_token_counter(Path(path))
    assert count("water") == 3  # [CLS], water, [SEP]
    assert count(" ".join(["water"] * 600)) == 602
