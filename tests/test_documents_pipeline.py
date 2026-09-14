from types import SimpleNamespace

from scrapy import Request

import get_stock.pipelines.documents as documents_module
from get_stock.pipelines.documents import CninfoFilesPipeline
from get_stock.pipelines.jsonl import JsonLinesPipeline
from get_stock.storage import atomic_write_json_lines, iter_json_lines


def test_financial_report_pdf_path_is_separate_from_regular_announcements() -> None:
    report_request = Request(
        "https://static.cninfo.com.cn/report.pdf",
        meta={
            "stock_code": "000001",
            "announcement_id": "report-1",
            "published_at": "2026-08-15T00:00:00+08:00",
            "document_type": "financial_report",
            "report_type": "semiannual",
        },
    )
    announcement_request = Request(
        "https://static.cninfo.com.cn/announcement.pdf",
        meta={
            "stock_code": "000001",
            "announcement_id": "announcement-1",
            "published_at": "2026-08-22T00:00:00+08:00",
            "document_type": "announcement",
            "report_type": None,
        },
    )

    assert CninfoFilesPipeline.file_path(None, report_request) == (
        "stocks/000001/documents/reports/semiannual/2026/report-1.pdf"
    )
    assert CninfoFilesPipeline.file_path(None, announcement_request) == (
        "stocks/000001/documents/announcements/2026/announcement-1.pdf"
    )


def test_downloaded_full_report_is_validated_before_json_output(monkeypatch, tmp_path) -> None:
    relative_path = "stocks/000001/documents/reports/annual/2026/report-1.pdf"
    pdf_path = tmp_path / relative_path
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-test")
    monkeypatch.setattr(
        documents_module,
        "validate_full_report_pdf",
        lambda *args, **kwargs: {
            "content_validation_status": "passed",
            "analysis_eligible": True,
            "page_count": 120,
            "requires_ocr": False,
            "validation_page_limit": 20,
            "validated_pages": 20,
            "matched_sections": ["管理层讨论与分析"],
            "validation_errors": [],
        },
    )
    item = {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "announcement_id": "report-1",
        "published_at": "2026-04-01T00:00:00+08:00",
        "document_type": "financial_report",
        "document_role": "full_report",
        "report_type": "annual",
        "report_period": "2025-12-31",
        "file_urls": ["https://static.cninfo.com.cn/report.pdf"],
    }

    result = CninfoFilesPipeline.item_completed(
        CninfoFilesPipeline.__new__(CninfoFilesPipeline),
        [(True, {"path": relative_path})],
        item,
        SimpleNamespace(spider=SimpleNamespace(data_dir=str(tmp_path))),
    )

    assert result["download_status"] == "success"
    assert result["content_validation_status"] == "passed"
    assert result["analysis_eligible"] is True
    assert result["validated_pages"] == 20


def test_successful_retry_updates_existing_announcement_record(tmp_path) -> None:
    class Stats:
        def inc_value(self, *_args, **_kwargs):
            pass

    stock_dir = tmp_path / "stocks" / "000001"
    registry = stock_dir / "cleaned" / "announcements.jsonl"
    atomic_write_json_lines(
        registry,
        [{"announcement_id": "report-1", "download_status": "not_requested"}],
    )
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        crawler=SimpleNamespace(stats=Stats()),
    )
    pipeline = JsonLinesPipeline()
    pipeline.open_spider(spider)

    pipeline.process_item(
        {
            "announcement_id": "report-1",
            "download_status": "success",
            "local_path": str(stock_dir / "documents" / "report-1.pdf"),
        },
        spider,
    )

    record = next(iter(iter_json_lines(registry)))
    assert record["download_status"] == "success"
    assert record["local_path"].endswith("report-1.pdf")
