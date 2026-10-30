"""Splitting a one-line letter into passages of whole sentences."""

from passages import MAX_WORDS, sentences, split_passages


def sentence(i, words=10):
    # Capitalized, so the next sentence visibly starts one.
    return " ".join([f"W{i}"] * (words - 1)) + " end."


def test_every_word_is_kept_in_order():
    text = " ".join(sentence(i) for i in range(40))
    passages = split_passages(text)
    assert " ".join(passages).split() == text.split()


def test_passages_end_at_sentence_boundaries_near_the_target():
    text = " ".join(sentence(i) for i in range(40))  # 400 words in 10-word sentences
    passages = split_passages(text, target=120)
    assert all(p.endswith("end.") for p in passages)
    assert [len(p.split()) for p in passages] == [120, 120, 120, 40]


def test_no_passage_is_longer_than_the_maximum():
    long_sentence = " ".join(["x"] * (MAX_WORDS * 2 + 30)) + "."
    passages = split_passages("Short opening sentence here. " + long_sentence)
    assert max(len(p.split()) for p in passages) <= MAX_WORDS


def test_a_short_tail_joins_the_passage_before_it():
    text = " ".join(sentence(i) for i in range(12)) + " Thank you."
    passages = split_passages(text, target=120, min_words=20)
    assert len(passages) == 1 and passages[0].endswith("Thank you.")


def test_bullets_start_a_new_sentence():
    text = (
        "We have three concerns: • the deadline is too short • the cost is high • notice is unclear"
    )
    assert sentences(text) == [
        "We have three concerns:",
        "• the deadline is too short",
        "• the cost is high",
        "• notice is unclear",
    ]


def test_empty_text_has_no_passages():
    assert split_passages("") == []


def test_a_citation_is_never_split_from_its_prefix():
    # 115 filler words, then "Sec." right where a passage closes. A splitter that breaks after
    # "Sec." put the prefix in one passage and the number in the next, and the citation was lost.
    filler = " ".join(["Word"] * 115) + "."
    text = filler + " We ask EPA to see Sec. 141.84 which governs replacement. " + filler
    passages = split_passages(text, target=120)
    assert any("Sec. 141.84" in p for p in passages)
    assert sentences("See 40 C.F.R. 141.85 for notices. Then more.")[0] == (
        "See 40 C.F.R. 141.85 for notices."
    )
