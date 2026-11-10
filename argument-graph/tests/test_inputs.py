"""Which passages are extracted, and the exit when an upstream stage has not run."""

import pytest

import inputs
from conftest import DOCKET, S84, S85, make_cfg, write_inputs


def test_cited_passages_are_selected_once_with_all_candidates(data_dir):
    data = inputs.load(DOCKET, data_dir)
    selected = inputs.select(data, make_cfg(), section_order=[S84, S85])
    assert list(selected["passage_id"]) == ["L1:p000", "L1:p001", "L2:p000", "L3:p000"]
    multi = selected.set_index("passage_id").loc["L1:p001"]
    assert multi["candidates"] == [S84, S85]
    assert multi["primary_ref"] == S84
    assert set(selected["section_source"]) == {"citation"}
    by_id = selected.set_index("passage_id")
    assert by_id.loc["L2:p000", "campaign_id"] == "L2"
    assert by_id.loc["L1:p000", "campaign_id"] is None


def test_max_passages_caps_in_section_order(data_dir):
    data = inputs.load(DOCKET, data_dir)
    selected = inputs.select(data, make_cfg(max_passages=2), section_order=[S84, S85])
    assert list(selected["passage_id"]) == ["L1:p000", "L1:p001"]


def test_missing_links_exits_with_the_stage_to_run(tmp_path, capsys):
    write_inputs(tmp_path)
    (tmp_path / "derived" / "passages" / DOCKET / "links.parquet").unlink()
    with pytest.raises(SystemExit) as e:
        inputs.load(DOCKET, tmp_path)
    assert e.value.code == 1
    assert "run passage-stage first" in capsys.readouterr().err


def test_rule_context_without_chroma_or_files_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("CHROMA_HOST", raising=False)
    monkeypatch.delenv("CHROMA_PATH", raising=False)
    chunks, source = inputs.rule_chunks(DOCKET, tmp_path)
    assert (chunks, source) == ([], "none")
    assert inputs.rule_context([]) == {}
