"""Which dockets and documents the stage indexes."""

from rule_passages.config import COMMENTED_ON, Settings


def clear(monkeypatch):
    for name in ("RULE_DOCKETS", "DOCKET_IDS", "RULE_DOCUMENTS", "RULE_DOC_TYPES"):
        monkeypatch.delenv(name, raising=False)


def test_dockets_follow_the_chain_unless_rule_dockets_is_set(monkeypatch):
    clear(monkeypatch)
    assert Settings.from_env().dockets == ("EPA-HQ-OW-2018-0149",)

    monkeypatch.setenv("DOCKET_IDS", "EPA-HQ-OW-2022-0801, EPA-HQ-OW-2018-0149")
    assert Settings.from_env().dockets == ("EPA-HQ-OW-2022-0801", "EPA-HQ-OW-2018-0149")

    monkeypatch.setenv("RULE_DOCKETS", "EPA-HQ-OAR-2017-0355")
    assert Settings.from_env().dockets == ("EPA-HQ-OAR-2017-0355",)

    monkeypatch.setenv("RULE_DOCKETS", "")  # an empty line in .env is the same as unset
    assert Settings.from_env().dockets == ("EPA-HQ-OW-2022-0801", "EPA-HQ-OW-2018-0149")


def test_lead_and_copper_indexes_only_the_proposal_comments_answered(monkeypatch):
    clear(monkeypatch)
    settings = Settings.from_env()
    docket = "EPA-HQ-OW-2022-0801"
    assert COMMENTED_ON[docket] == ("2023-26148",)  # 88 FR 84878
    assert settings.wanted(docket, "2023-26148", "Proposed Rule")
    # The same docket holds an earlier notice and the 2024 final rule. Neither is searched.
    assert not settings.wanted(docket, "2022-21857", "Proposed Rule")
    assert not settings.wanted(docket, "2024-23549", "Rule")
