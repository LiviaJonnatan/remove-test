import random

from linker.train import Example, batches, false_negatives


def ex(section, negs=()):
    return Example("q", "p", ["n"] * len(negs), ("D", section), [("D", s) for s in negs])


def test_batches_are_full_and_cover_every_example():
    examples = [ex(str(i % 3)) for i in range(70)]
    out = batches(examples, 32, random.Random(0))
    assert [len(b) for b in out] == [32, 32, 6]
    assert sorted(id(e) for b in out for e in b) == sorted(id(e) for e in examples)


def test_false_negatives_masks_same_section_but_not_own_positive():
    batch = [ex("a", ["b"]), ex("a", ["c"]), ex("b", ["a"])]
    m = false_negatives(batch)
    # docs: positives a, a, b, then negatives b, c, a
    assert m.shape == (3, 6)
    assert m[0].tolist() == [False, True, False, False, False, True]
    assert m[1].tolist() == [True, False, False, False, False, True]
    assert m[2].tolist() == [False, False, False, True, False, False]
