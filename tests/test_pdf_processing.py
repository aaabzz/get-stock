import json
from pathlib import Path

import pytest

from get_stock.documents import ReportProcessingError, list_processable_reports, process_report
from get_stock.documents.chunker import chunk_sections
from get_stock.documents.cleaner import clean_pages
from get_stock.documents.heading_schemas import HeadingClassification, HeadingLLMAnalysis
from get_stock.documents.segmenter import resolve_headings, segment_sections
from get_stock.storage import atomic_write_json_lines, iter_json_lines


def _announcement(data_dir: Path, *, role: str = "full_report") -> Path:
    stock_dir = data_dir / "stocks" / "000001"
    pdf_path = stock_dir / "documents" / "reports" / "annual" / "2025" / "report.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nfixture")
    atomic_write_json_lines(
        stock_dir / "cleaned" / "announcements.jsonl",
        [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "announcement_id": "report-1",
                "title": "平安银行2025年年度报告",
                "category": "年度报告",
                "document_type": "financial_report",
                "document_role": role,
                "report_type": "annual",
                "report_period": "2025-12-31",
                "is_full_report": role == "full_report",
                "content_validation_status": (
                    "passed" if role == "full_report" else "not_applicable"
                ),
                "analysis_eligible": role == "full_report",
                "download_status": "success",
                "local_path": str(pdf_path),
            }
        ],
    )
    return pdf_path


def _fake_extraction() -> tuple[list[dict], dict]:
    pages = [
        {
            "page_number": 1,
            "text": "平安银行2025年年度报告\n报告全文前置内容" + "甲" * 200,
            "character_count": 220,
            "extraction_status": "passed",
            "error": None,
        },
        {
            "page_number": 2,
            "text": "第一节 公司简介和主要财务指标\n公司简介" + "乙" * 300,
            "character_count": 330,
            "extraction_status": "passed",
            "error": None,
        },
        {
            "page_number": 3,
            "text": "第三节 管理层讨论与分析\n经营情况" + "丙" * 300,
            "character_count": 330,
            "extraction_status": "passed",
            "error": None,
        },
        {
            "page_number": 4,
            "text": "第十节 财务报告\n合并资产负债表" + "丁" * 300,
            "character_count": 330,
            "extraction_status": "passed",
            "error": None,
        },
    ]
    return pages, {
        "page_count": 4,
        "is_encrypted": False,
        "failed_pages": [],
        "extraction_method": "fixture",
    }


def test_clean_segment_and_chunk_keep_page_and_section_provenance() -> None:
    pages, _ = _fake_extraction()
    cleaned = clean_pages(pages)
    sections = segment_sections(cleaned)
    chunks = chunk_sections(sections, chunk_size=250, chunk_overlap=20)

    assert [section["section_type"] for section in sections] == [
        "front_matter",
        "company_profile",
        "management_discussion",
        "financial_report",
    ]
    assert chunks
    assert all(chunk["section_id"] and chunk["start_page"] for chunk in chunks)
    assert all(len(chunk["text"]) <= 250 for chunk in chunks)


def test_unknown_chapter_is_preserved_as_an_independent_section() -> None:
    pages = [
        {"page_number": 1, "text": "报告前置内容"},
        {"page_number": 2, "text": "第一章 公司简介\n公司内容"},
        {"page_number": 3, "text": "第二章 核心经营数据\n经营数据内容"},
        {"page_number": 4, "text": "第三章 管理层讨论与分析\n管理层内容"},
    ]

    headings, diagnostics = resolve_headings(pages, mode="rules")
    sections = segment_sections(pages, headings=headings)
    chunks = chunk_sections(sections, chunk_size=200, chunk_overlap=20)

    assert diagnostics["unclassified_count"] == 1
    assert [section["section_type"] for section in sections] == [
        "front_matter",
        "company_profile",
        "unclassified",
        "management_discussion",
    ]
    unknown = sections[2]
    assert unknown["heading"] == "第二章 核心经营数据"
    assert unknown["start_page"] == 3
    assert unknown["end_page"] == 3
    assert any(chunk["section_id"] == unknown["section_id"] for chunk in chunks)


def test_repeated_previous_heading_does_not_hide_new_heading_on_same_page() -> None:
    pages = [
        {"page_number": 1, "text": "第一章 公司简介\n公司内容"},
        {
            "page_number": 2,
            "text": "第一章 公司简介\n第二章 核心经营数据\n经营数据内容",
        },
        {"page_number": 3, "text": "第三章 管理层讨论与分析\n管理层内容"},
    ]

    headings, _ = resolve_headings(pages, mode="rules")

    assert [item["raw_heading"] for item in headings] == [
        "第一章 公司简介",
        "第二章 核心经营数据",
        "第三章 管理层讨论与分析",
    ]


def test_unknown_top_level_section_is_kept_when_numbering_is_continuous() -> None:
    pages = [
        {"page_number": 1, "text": "第一节 公司简介和主要财务指标\n公司内容"},
        {"page_number": 2, "text": "第二节 新模板经营数据\n经营数据内容"},
        {"page_number": 3, "text": "第三节 管理层讨论与分析\n管理层内容"},
    ]

    headings, diagnostics = resolve_headings(pages, mode="rules")

    assert [item["raw_heading"] for item in headings] == [
        "第一节 公司简介和主要财务指标",
        "第二节 新模板经营数据",
        "第三节 管理层讨论与分析",
    ]
    assert headings[1]["section_type"] == "unclassified"
    assert diagnostics["unclassified_count"] == 1


def test_auto_heading_mode_uses_llm_only_for_unclassified_candidate() -> None:
    pages = [
        {"page_number": 1, "text": "第一章 公司简介\n公司内容"},
        {"page_number": 2, "text": "第二章 核心经营数据\n经营数据内容"},
        {"page_number": 3, "text": "第三章 管理层讨论与分析\n管理层内容"},
    ]
    received = None

    def reasoner(packet):
        nonlocal received
        received = packet
        return HeadingLLMAnalysis(
            classifications=(
                HeadingClassification(
                    candidate_id="candidate-0002",
                    section_type="financial_indicators",
                    normalized_heading="第二章 核心经营数据",
                    confidence=0.95,
                ),
            )
        )

    headings, diagnostics = resolve_headings(pages, mode="auto", reasoner=reasoner)
    sections = segment_sections(pages, headings=headings)

    assert received is not None
    assert [item["candidate_id"] for item in received["candidates"]] == ["candidate-0002"]
    assert diagnostics["llm_used"] is True
    assert diagnostics["unclassified_count"] == 0
    assert sections[1]["section_type"] == "financial_indicators"
    assert sections[1]["classification_method"] == "llm"


def test_heading_llm_cannot_replace_source_heading() -> None:
    pages = [{"page_number": 1, "text": "第二章 核心经营数据\n经营数据内容"}]

    def reasoner(_packet):
        return HeadingLLMAnalysis(
            classifications=(
                HeadingClassification(
                    candidate_id="candidate-0001",
                    section_type="financial_indicators",
                    normalized_heading="第二章 模型虚构标题",
                    confidence=0.99,
                ),
            )
        )

    headings, diagnostics = resolve_headings(pages, mode="auto", reasoner=reasoner)

    assert headings[0]["raw_heading"] == "第二章 核心经营数据"
    assert headings[0]["section_type"] == "unclassified"
    assert "changed source heading meaning" in diagnostics["warnings"][0]


def test_process_report_writes_outputs_and_reuses_cache(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    _announcement(data_dir)
    calls = 0

    def fake_extract(_path: Path):
        nonlocal calls
        calls += 1
        return _fake_extraction()

    monkeypatch.setattr("get_stock.documents.processor.extract_pages", fake_extract)
    first = process_report(data_dir, "000001", "report-1", chunk_size=250, chunk_overlap=20)
    second = process_report(data_dir, "000001", "report-1", chunk_size=250, chunk_overlap=20)

    output_dir = Path(first["output_dir"])
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert calls == 1
    assert (output_dir / "pages.jsonl").is_file()
    assert (output_dir / "headings.jsonl").is_file()
    assert (output_dir / "sections.jsonl").is_file()
    assert (output_dir / "chunks.jsonl").is_file()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha256"]
    assert manifest["heading_mode"] == "rules"
    assert manifest["outputs"]["headings"] == "headings.jsonl"
    assert manifest["quality"]["recognized_section_count"] == 3
    assert len(list(iter_json_lines(output_dir / "chunks.jsonl"))) > 0


def test_process_report_rejects_non_full_report(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _announcement(data_dir, role="report_summary")

    with pytest.raises(ReportProcessingError, match="document_role=full_report"):
        process_report(data_dir, "000001", "report-1")


def test_process_report_rejects_pdf_outside_stock_documents(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _announcement(data_dir)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\nfixture")
    registry = data_dir / "stocks" / "000001" / "cleaned" / "announcements.jsonl"
    record = next(iter(iter_json_lines(registry)))
    record["local_path"] = str(outside)
    atomic_write_json_lines(registry, [record])

    with pytest.raises(ReportProcessingError, match="outside the stock documents directory"):
        process_report(data_dir, "000001", "report-1")


def test_list_processable_reports_only_returns_full_reports(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _announcement(data_dir)

    reports = list_processable_reports(data_dir, "000001")

    assert [report["announcement_id"] for report in reports] == ["report-1"]
