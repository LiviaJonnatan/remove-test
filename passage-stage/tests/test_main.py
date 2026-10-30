"""The stage end to end: letters and groups in, passages, links and a summary out."""

import json
from pathlib import Path

import pandas as pd
import pytest

import main as m

DOCKET = "D-1"
REFS = ["V/E", "PART 141/§ 141.2", "PART 141/§ 141.84", "PART 141/§ 141.85"]
FIXTURE = Path(__file__).resolve().parents[2] / "rule-passages" / "tests" / "fixtures"


def write_inputs(data_dir, letters, groups):
    (data_dir / "derived" / "letters" / DOCKET).mkdir(parents=True)
    (data_dir / "derived" / "campaigns" / DOCKET).mkdir(parents=True)
    pd.DataFrame(letters).to_parquet(
        data_dir / "derived" / "letters" / DOCKET / "letters.parquet", index=False
    )
    pd.DataFrame(groups).to_parquet(
        data_dir / "derived" / "campaigns" / DOCKET / "assignments.parquet", index=False
    )


def read_outputs(data_dir):
    out = data_dir / "derived" / "passages" / DOCKET
    summary = json.loads((out / "summary.json").read_text())
    return (
        pd.read_parquet(out / "passages.parquet"),
        pd.read_parquet(out / "links.parquet"),
        summary,
    )


def test_section_numbers_map_to_rule_passages_refs():
    assert m.section_refs_by_number(REFS) == {
        "141.2": "PART 141/§ 141.2",
        "141.84": "PART 141/§ 141.84",
        "141.85": "PART 141/§ 141.85",
    }


def test_one_letter_per_exact_match_group():
    letters = pd.DataFrame({"letter_id": ["a", "b", "c"], "text": ["x", "x", "y"]})
    groups = pd.DataFrame({"letter_id": ["a", "b", "c"], "campaign_id": ["a", "a", None]})
    assert list(m.distinct_letters(letters, groups)["letter_id"]) == ["a", "c"]


def test_a_campaign_member_is_read_for_its_own_sentences_only():
    template = "Replace every lead line in ten years. Do it at no cost to households."
    letters = pd.DataFrame(
        {
            "letter_id": ["m1", "m2", "m3", "m4"],
            "text": [
                "My block still has lead pipes. " + template,  # named letter: read whole
                template + " Our school tested at 30 ppb.",
                "REPLACE every lead line in ten years!  " + template.split(". ")[1],  # a copy
                template + " Our school tested at 30 ppb. See § 141.84(b).",
            ],
        }
    )
    groups = pd.DataFrame({"letter_id": ["m1", "m2", "m3", "m4"], "campaign_id": ["m1"] * 4})
    read = m.distinct_letters(letters, groups).set_index("letter_id")["text"]
    assert read.to_dict() == {
        "m1": "My block still has lead pipes. " + template,
        "m2": "Our school tested at 30 ppb.",
        "m4": "See § 141.84(b).",  # its other added sentence was already read in m2
    }


def test_links_follow_the_contract(tmp_path):
    text = (
        "We oppose the deadline in § 141.84(b) and ask for 15 years. "
        "The notice in 40 CFR 141.85 and § 141.84(c) is also too fast. "
        "Our own state rule, 40 CFR 142.14, already covers this."
    )
    write_inputs(
        tmp_path,
        {"letter_id": ["L1", "L2"], "text": [text, text]},
        {"letter_id": ["L1", "L2"], "campaign_id": ["L1", "L1"]},  # L2 is a copy of L1
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is True
    passages, links, summary = read_outputs(tmp_path)

    assert list(links.columns) == [
        "passage_id",
        "letter_id",
        "docket_id",
        "section_ref",
        "citation_raw",
        "source",
    ]
    assert set(passages["letter_id"]) == {"L1"}  # the copy is skipped
    resolved = links.dropna(subset=["section_ref"])
    # 141.84 is cited twice in the passage and links once
    assert sorted(resolved["section_ref"]) == ["PART 141/§ 141.84", "PART 141/§ 141.85"]
    unresolved = links[links["section_ref"].isna()]
    assert list(unresolved["citation_raw"]) == ["40 CFR 142.14"]
    assert set(links["source"]) == {"citation"}
    assert links["passage_id"].iloc[0] == "L1:p000"
    assert summary["letters_skipped_as_copies"] == 1
    assert (summary["links_resolved"], summary["links_unresolved"]) == (2, 1)
    assert summary["sections_cited"] == 2


def test_a_letters_own_section_numbers_are_not_citations():
    assert m.is_own_numbering("2.4", "R1_section")
    assert not m.is_own_numbering("141.83", "R1_section")  # a CFR section outside the rule
    assert not m.is_own_numbering("2.4", "R2_cfr")  # it said CFR, so keep it


def test_own_numbering_is_left_out_of_links(tmp_path):
    text = "As we explain in Section 2.4 above, the deadline in § 141.84(b) is too short."
    write_inputs(
        tmp_path,
        {"letter_id": ["L1"], "text": [text]},
        {"letter_id": ["L1"], "campaign_id": [None]},
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is True
    passages, links, _ = read_outputs(tmp_path)
    assert list(links["section_ref"]) == ["PART 141/§ 141.84"]
    assert passages["n_citations"].tolist() == [1]


def test_letters_without_citations_still_get_passages(tmp_path):
    write_inputs(
        tmp_path,
        {"letter_id": ["L1"], "text": ["Please protect children from lead in water."]},
        {"letter_id": ["L1"], "campaign_id": [None]},
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is True
    passages, links, summary = read_outputs(tmp_path)
    assert len(passages) == 1 and links.empty
    assert summary["passages_with_citation"] == 0


@pytest.mark.parametrize("missing", ["letters", "campaigns"])
def test_a_missing_input_fails_the_stage(tmp_path, missing):
    write_inputs(
        tmp_path, {"letter_id": ["L1"], "text": ["x"]}, {"letter_id": ["L1"], "campaign_id": [None]}
    )
    folder = tmp_path / "derived" / missing / DOCKET
    for f in folder.iterdir():
        f.unlink()
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is False


def test_empty_letters_or_no_rule_text_fail_the_stage(tmp_path):
    write_inputs(tmp_path, {"letter_id": [], "text": []}, {"letter_id": [], "campaign_id": []})
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is False

    other = tmp_path / "other"
    write_inputs(
        other, {"letter_id": ["L1"], "text": ["x"]}, {"letter_id": ["L1"], "campaign_id": [None]}
    )
    assert m.build_docket(DOCKET, other, section_refs=[]) is False


def test_a_rule_without_numbered_sections_still_gets_passages(tmp_path):
    # The Clean Power Plan repeal has no "Sec." headings. Its passages must still be written, so
    # the API, which waits on this stage, starts.
    text = "We oppose the repeal. See § 60.5740(a) and section 2.4 of our letter."
    write_inputs(
        tmp_path,
        {"letter_id": ["L1"], "text": [text]},
        {"letter_id": ["L1"], "campaign_id": [None]},
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=["I/A", "II"]) is True
    passages, links, summary = read_outputs(tmp_path)
    assert len(passages) == 1
    assert links["section_ref"].isna().all()
    assert list(links["citation_raw"]) == ["§ 60.5740(a)"]  # kept; "section 2.4" is not
    assert summary["rule_sections_known"] == 0


def test_rule_sections_come_from_rule_passages_chunking(tmp_path, monkeypatch):
    # The same document rule-passages tests with, saved the way its collect step saves it.
    docket = "EPA-HQ-OW-2018-0149"
    folder = tmp_path / "raw" / "federal_register" / docket
    folder.mkdir(parents=True)
    (folder / "2019-00791.txt").write_text((FIXTURE / "fr_excerpt.txt").read_text(encoding="utf-8"))
    (folder / "2019-00791.json").write_text(
        json.dumps(
            {
                "document_number": "2019-00791",
                "title": "Revised Definition of Waters of the United States",
                "type": "Proposed Rule",
                "publication_date": "2019-02-14",
                "citation": "84 FR 4154",
                "html_url": "https://www.federalregister.gov/d/2019-00791",
            }
        )
    )
    for name in ("RULE_DOCKETS", "RULE_DOCUMENTS", "RULE_DOC_TYPES"):
        monkeypatch.delenv(name, raising=False)
    refs, documents = m.rule_section_refs(docket, tmp_path)
    assert documents == ["2019-00791"]
    assert "328.3" in m.section_refs_by_number(refs)


def test_masked_text_has_no_citation_left(tmp_path):
    text = (
        "We oppose the deadline in § 141.84(b) and ask for 15 years. "
        "The notice in 40 CFR 141.85 and § 141.84(c) is also too fast."
    )
    write_inputs(
        tmp_path,
        {"letter_id": ["L1"], "text": [text]},
        {"letter_id": ["L1"], "campaign_id": [None]},
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is True
    passages, _, _ = read_outputs(tmp_path)
    masked = passages["text_masked"].iloc[0]
    assert "141.84" not in masked and "141.85" not in masked
    assert passages["text"].iloc[0] == text  # the original is kept as well


def test_a_section_sign_is_never_read_as_own_numbering():
    assert not m.is_own_numbering("60.5740", "R1_sign")
    assert m.is_own_numbering("2.4", "R1_section")


def test_a_range_links_every_rule_section_inside_it(tmp_path):
    refs = ["PART 141/§ 141.80", "PART 141/§ 141.81", "PART 141/§ 141.82", "PART 141/§ 141.84"]
    text = "We comment on §§ 141.80 through 141.84 as a whole."
    write_inputs(
        tmp_path,
        {"letter_id": ["L1"], "text": [text]},
        {"letter_id": ["L1"], "campaign_id": [None]},
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=refs) is True
    _, links, _ = read_outputs(tmp_path)
    assert sorted(links["section_ref"]) == sorted(refs)


def test_lost_ligatures_are_repaired_before_citations_are_read(tmp_path):
    # Calibri's "ti" glyph comes out of pypdf as U+FFFD. Repaired, "Section 141.84" is a citation,
    # and the passage text is whole. The letters file itself is not changed.
    damaged = "The Associa�on asks EPA to revise Sec�on 141.84 on lead service lines."
    write_inputs(
        tmp_path,
        {
            "letter_id": ["L1", "L2"],
            "text": [damaged, "Our association supports the section on service lines."],
        },
        {"letter_id": ["L1", "L2"], "campaign_id": [None, None]},
    )
    assert m.build_docket(DOCKET, tmp_path, section_refs=REFS) is True
    passages, links, summary = read_outputs(tmp_path)
    assert passages.loc[passages.letter_id == "L1", "text"].iloc[0] == damaged.replace("�", "ti")
    assert links.loc[links.letter_id == "L1", "section_ref"].tolist() == ["PART 141/§ 141.84"]
    assert summary["words_repaired"] == 2 and summary["letters_repaired"] == 1
    letters = pd.read_parquet(tmp_path / "derived" / "letters" / DOCKET / "letters.parquet")
    assert letters.loc[0, "text"] == damaged
