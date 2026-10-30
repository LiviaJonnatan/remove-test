"""Unit tests for data-collector. No network: the API client is stubbed."""

import json
import time

import pytest

import main as m

# --------------------------------------------------------------------------- shards

def test_shards_partition_the_index():
    ids = list(range(10))
    parts = [[i for i in ids if m.in_shard(i, (k, 3))] for k in (1, 2, 3)]
    assert parts == [[0, 3, 6, 9], [1, 4, 7], [2, 5, 8]]
    assert sorted(sum(parts, [])) == ids  # every id in exactly one shard


def test_parse_shard():
    assert m.parse_shard(None) == (1, 1)
    assert m.parse_shard("") == (1, 1)
    assert m.parse_shard("2/5") == (2, 5)
    with pytest.raises(ValueError):
        m.parse_shard("0/5")
    with pytest.raises(ValueError):
        m.parse_shard("6/5")


# --------------------------------------------------------------------------- #27: window dates

def test_filter_date_is_eastern_time_with_backoff():
    # April: EDT is UTC-4. 00:37 UTC -> 20:37 the previous evening, minus one minute.
    assert m._to_filter_date("2019-04-25T00:37:00Z") == "2019-04-24 20:36:00"
    # January: EST is UTC-5.
    assert m._to_filter_date("2019-01-15T05:00:00Z") == "2019-01-14 23:59:00"


def test_filter_date_backoff_is_configurable():
    assert m._to_filter_date("2019-04-25T00:37:00Z", back_off_seconds=0) == "2019-04-24 20:37:00"


def test_index_not_marked_complete_when_count_disagrees(tmp_path):
    ckpt = tmp_path / "ckpt.json"
    with pytest.raises(RuntimeError, match="10906.*11444"):
        m._finish_index("D", ckpt, 10906, 11444)
    assert json.loads(ckpt.read_text())["complete"] is False


def test_index_marked_complete_when_count_matches(tmp_path):
    ckpt = tmp_path / "ckpt.json"
    assert m._finish_index("D", ckpt, 11444, 11444) == 11444
    assert json.loads(ckpt.read_text())["complete"] is True


# --------------------------------------------------------------------------- MAX_RECORDS

def test_trim_index_keeps_first_n(tmp_path):
    p = tmp_path / "comments_index.jsonl"
    m.append_jsonl(p, [{"id": f"X-{i}"} for i in range(250)])
    assert m._trim_index(p, 50) == 50
    assert [r["id"] for r in m.read_jsonl(p)] == [f"X-{i}" for i in range(50)]


def test_capped_checkpoint_does_not_satisfy_an_uncapped_run():
    capped = {"complete": True, "truncated": True}
    assert m._checkpoint_satisfies(capped, 50, max_records=50)
    assert m._checkpoint_satisfies(capped, 50, max_records=20)
    assert not m._checkpoint_satisfies(capped, 50, max_records=None)
    assert not m._checkpoint_satisfies(capped, 50, max_records=500)
    assert m._checkpoint_satisfies({"complete": True}, 11444, max_records=None)


def test_capped_pass_then_uncapped_pass_rebuilds_index(tmp_path, monkeypatch):
    """A 3-record smoke run followed by a full run ends with the whole docket indexed."""
    docket = "D"
    all_ids = [f"D-{i}" for i in range(7)]

    class FakeClient:
        calls = 0

        def get(self, path, params):
            page = params["page[number]"]
            rows = all_ids[(page - 1) * 5 : page * 5]
            return {
                "data": [
                    {"id": i, "attributes": {"lastModifiedDate": "2019-01-01T00:00:00Z"}}
                    for i in rows
                ],
                "meta": {"totalElements": len(all_ids), "hasNextPage": page * 5 < len(all_ids)},
            }

    monkeypatch.setattr(m, "PAGE_SIZE", 5)
    assert m.build_index(FakeClient(), docket, tmp_path, max_records=3) == 3
    assert json.loads((tmp_path / "index_checkpoint.json").read_text())["truncated"] is True
    assert m.build_index(FakeClient(), docket, tmp_path, max_records=None) == 7
    assert json.loads((tmp_path / "index_checkpoint.json").read_text())["complete"] is True
    assert [r["id"] for r in m.read_jsonl(tmp_path / "comments_index.jsonl")] == all_ids


# --------------------------------------------------------------------------- keys

def test_key_pool_round_robins_and_skips_resting_keys():
    pool = m.KeyPool(["a", "b", "c"])
    assert [pool.next() for _ in range(4)] == ["a", "b", "c", "a"]
    pool.rest("b", seconds=3600)
    picks = [pool.next() for _ in range(6)]
    assert "b" not in picks
    assert set(picks) == {"a", "c"}


def test_key_pool_rests_key_when_remaining_is_low():
    pool = m.KeyPool(["a", "b"])
    pool.observe("a", remaining=3)  # below RATE_MARGIN
    assert pool.rested_until["a"] > time.time()
    assert pool.next() == "b"
    pool.observe("b", remaining=500)
    assert "b" not in pool.rested_until


# --------------------------------------------------------------------------- resumability

def test_fetch_details_skips_records_already_on_disk(tmp_path):
    out = tmp_path
    m.append_jsonl(out / "comments_index.jsonl", [{"id": "D-1"}, {"id": "D-2"}, {"id": "D-3"}])
    (out / "details").mkdir()
    (out / "details" / "D-2.json").write_text(json.dumps({"data": {"id": "D-2", "attributes": {}}}))

    fetched = []

    class FakeClient:
        calls = 0

        def get(self, path, params=None):
            fetched.append(path)
            return {"data": {"id": path.rsplit("/", 1)[-1], "attributes": {}}, "included": []}

    assert m.fetch_details(FakeClient(), "D", out) == 3
    assert fetched == ["/comments/D-1", "/comments/D-3"]
    assert sorted(p.name for p in (out / "details").glob("*.json")) == [
        "D-1.json",
        "D-2.json",
        "D-3.json",
    ]


# --------------------------------------------------------------------------- RECORD_IDS_FILE

def test_read_record_ids_skips_comments_blanks_and_repeats(tmp_path):
    p = tmp_path / "ids.txt"
    p.write_text("# sample\nD-2\n\nD-1  # the long one\nD-2\n")
    assert m.read_record_ids(p) == ["D-2", "D-1"]


def test_fixed_list_fetches_exactly_those_records_and_never_indexes(tmp_path):
    fetched = []

    class FakeClient:
        calls = 0
        failed_downloads = []

        def get(self, path, params=None):
            assert path != "/comments", "the index stage must not run for a fixed list"
            fetched.append(path)
            return {"data": {"id": path.rsplit("/", 1)[-1], "attributes": {}}, "included": []}

    summary = m.collect_docket(
        FakeClient(), "D", tmp_path, 50, False, (1, 1), record_ids=["D-7", "OTHER-1", "D-3"]
    )
    assert fetched == ["/comments/D-7", "/comments/D-3"]  # the other docket's id is left out
    assert summary["comments_indexed"] == 2 and summary["details_on_disk"] == 2
    assert not (tmp_path / "raw" / "D" / "comments_index.jsonl").exists()


def test_fixed_list_leaves_an_existing_index_alone(tmp_path):
    out = tmp_path / "raw" / "D"
    out.mkdir(parents=True)
    m.append_jsonl(out / "comments_index.jsonl", [{"id": f"D-{i}"} for i in range(5)])
    before = (out / "comments_index.jsonl").read_text()

    class FakeClient:
        calls = 0
        failed_downloads = []

        def get(self, path, params=None):
            return {"data": {"id": path.rsplit("/", 1)[-1], "attributes": {}}, "included": []}

    m.collect_docket(FakeClient(), "D", tmp_path, None, True, (1, 1), record_ids=["D-4"])
    assert (out / "comments_index.jsonl").read_text() == before
    assert [p.name for p in (out / "details").glob("*.json")] == ["D-4.json"]


def test_check_record_ids_accepts_a_list_that_matches_the_dockets():
    ids = ["A-1", "A-2", "B-7"]
    assert m.check_record_ids(ids, ["A", "B"]) == []


def test_check_record_ids_names_each_mismatch():
    # A list for docket A while DOCKET_IDS says B: B gets nothing and every id is unmatched.
    problems = m.check_record_ids(["A-1", "A-2"], ["B"])
    assert problems == [
        "no id in the list belongs to B",
        "ids for no docket in DOCKET_IDS: 2, first A-1",
    ]
    # A docket that is a prefix of another is not a match: "A" is not "AB".
    assert m.check_record_ids(["AB-1"], ["A"]) == [
        "no id in the list belongs to A",
        "ids for no docket in DOCKET_IDS: 1, first AB-1",
    ]


def test_mismatched_list_exits_1_before_any_api_call(tmp_path, monkeypatch):
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("EPA-HQ-OW-2022-0801-1264\n")
    monkeypatch.setenv("API_DATA_GOV_KEYS", "not-a-real-key")
    monkeypatch.setenv("DOCKET_IDS", "EPA-HQ-OW-2018-0149")
    monkeypatch.setenv("RECORD_IDS_FILE", str(ids_file))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["main.py"])

    def no_client(*args, **kwargs):
        raise AssertionError("the collector must stop before it builds an API client")

    monkeypatch.setattr(m, "Client", no_client)
    assert m.main() == 1
