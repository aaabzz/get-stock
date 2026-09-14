import json

import pytest

from get_stock.storage import (
    append_json_line,
    atomic_write_json,
    cleaned_data_path,
    iter_json_lines,
    jsonl_to_pretty_json,
    load_announcement_ids,
    pretty_data_path,
    state_data_path,
    sync_pretty_json,
)


def test_json_and_jsonl_local_storage(tmp_path) -> None:
    stock_dir = tmp_path / "stocks" / "000001"
    security_path = cleaned_data_path(stock_dir, "security.json")
    announcements_path = cleaned_data_path(stock_dir, "announcements.jsonl")

    atomic_write_json(security_path, {"stock_code": "000001", "stock_name": "平安银行"})
    append_json_line(announcements_path, {"announcement_id": "1", "title": "公告一"})
    append_json_line(announcements_path, {"announcement_id": "2", "title": "公告二"})

    assert json.loads(security_path.read_text(encoding="utf-8"))["stock_name"] == "平安银行"
    assert list(iter_json_lines(announcements_path))[1]["title"] == "公告二"
    assert load_announcement_ids(announcements_path) == {"1", "2"}


def test_stock_data_paths_separate_cleaned_and_pretty_files(tmp_path) -> None:
    stock_dir = tmp_path / "stocks" / "000001"
    source = cleaned_data_path(stock_dir, "announcements.jsonl")

    assert source == stock_dir / "cleaned" / "announcements.jsonl"
    assert pretty_data_path(stock_dir, source) == stock_dir / "pretty" / "announcements.json"
    assert state_data_path(stock_dir, "crawl_state.json") == (
        stock_dir / "state" / "crawl_state.json"
    )


def test_invalid_jsonl_reports_line_number(tmp_path) -> None:
    path = tmp_path / "announcements.jsonl"
    path.write_text('{"announcement_id":"1"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r":2"):
        list(iter_json_lines(path))


def test_jsonl_to_pretty_json_keeps_source_and_creates_readable_array(tmp_path) -> None:
    source = tmp_path / "announcements.jsonl"
    append_json_line(source, {"announcement_id": "1", "title": "公告一"})
    append_json_line(source, {"announcement_id": "2", "title": "公告二"})
    original = source.read_text(encoding="utf-8")

    destination = jsonl_to_pretty_json(source)

    assert destination == tmp_path / "announcements.pretty.json"
    assert source.read_text(encoding="utf-8") == original
    assert json.loads(destination.read_text(encoding="utf-8")) == [
        {"announcement_id": "1", "title": "公告一"},
        {"announcement_id": "2", "title": "公告二"},
    ]
    assert '\n    "announcement_id": "1"' in destination.read_text(encoding="utf-8")


def test_jsonl_to_pretty_json_accepts_a_separate_destination(tmp_path) -> None:
    source = tmp_path / "records.jsonl"
    append_json_line(source, {"id": 1})

    destination = jsonl_to_pretty_json(source, tmp_path / "readable" / "records.json")

    assert destination == tmp_path / "readable" / "records.json"
    assert json.loads(destination.read_text(encoding="utf-8")) == [{"id": 1}]


def test_jsonl_to_pretty_json_rejects_overwriting_source(tmp_path) -> None:
    source = tmp_path / "records.jsonl"
    append_json_line(source, {"id": 1})

    with pytest.raises(ValueError, match="destination must be different"):
        jsonl_to_pretty_json(source, source)


@pytest.mark.parametrize("source_suffix", [".json", ".jsonl"])
def test_sync_pretty_json_supports_cleaned_json_and_jsonl(source_suffix, tmp_path) -> None:
    source = tmp_path / "cleaned" / f"records{source_suffix}"
    destination = tmp_path / "pretty" / "records.json"
    if source_suffix == ".json":
        atomic_write_json(source, {"stock_code": "000001"})
        expected = {"stock_code": "000001"}
    else:
        append_json_line(source, {"stock_code": "000001"})
        expected = [{"stock_code": "000001"}]

    result = sync_pretty_json(source, destination)

    assert result == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == expected
