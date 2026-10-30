from linker.promote import no_worse


def test_the_served_model_retrained_is_not_worse_than_itself():
    assert no_worse(318 / 490, 0.649)


def test_one_fewer_correct_passage_is_worse():
    assert not no_worse(317 / 490, 0.649)


def test_nothing_served_yet():
    assert no_worse(0.1, None)
