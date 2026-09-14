from urllib.parse import parse_qs

import pytest

from get_stock.spiders.announcements import CninfoAnnouncementSpider
from get_stock.spiders.company import CninfoCompanySpider
from get_stock.spiders.financials import CninfoFinancialsSpider
from get_stock.spiders.market import CninfoMarketSpider
from get_stock.spiders.shareholders import CninfoShareholdersSpider
from get_stock.spiders.trading import CninfoTradingSpider


def test_announcement_request_contains_current_cninfo_form_fields(tmp_path) -> None:
    spider = CninfoAnnouncementSpider(
        stock_code="000001",
        start_date="2026-08-01",
        end_date="2026-08-29",
        max_pages=1,
        data_dir=str(tmp_path),
    )
    spider.security = {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }

    request = spider._announcement_request(page=1)
    form = parse_qs(request.body.decode(), keep_blank_values=True)

    assert request.method == "POST"
    assert form["stock"] == ["000001,gssz0000001"]
    assert form["column"] == ["szse"]
    assert form["seDate"] == ["2026-08-01~2026-08-29"]
    assert form["pageNum"] == ["1"]
    assert form["pageSize"] == ["30"]


@pytest.mark.parametrize("stock_code", ["1", "ABC001", "0000011"])
def test_spider_rejects_invalid_stock_codes(stock_code, tmp_path) -> None:
    with pytest.raises(ValueError, match="six digits"):
        CninfoAnnouncementSpider(
            stock_code=stock_code,
            start_date="2026-08-01",
            end_date="2026-08-29",
            data_dir=str(tmp_path),
        )


def test_spider_rejects_reversed_date_range(tmp_path) -> None:
    with pytest.raises(ValueError, match="cannot be later"):
        CninfoAnnouncementSpider(
            stock_code="000001",
            start_date="2026-08-29",
            end_date="2026-08-01",
            data_dir=str(tmp_path),
        )


def test_announcement_spider_can_filter_reports_and_regular_announcements(tmp_path) -> None:
    reports_only = CninfoAnnouncementSpider(
        stock_code="000001",
        reports=True,
        regular_announcements=False,
        data_dir=str(tmp_path),
    )
    regular_only = CninfoAnnouncementSpider(
        stock_code="000001",
        reports=False,
        regular_announcements=True,
        data_dir=str(tmp_path),
    )
    report = {"document_type": "financial_report", "document_role": "full_report"}
    announcement = {"document_type": "announcement"}

    assert reports_only._should_include(report) is True
    assert reports_only._should_include(announcement) is False
    assert regular_only._should_include(report) is False
    assert regular_only._should_include(announcement) is True


def test_announcement_spider_rejects_disabling_both_document_types(tmp_path) -> None:
    with pytest.raises(ValueError, match="cannot both be disabled"):
        CninfoAnnouncementSpider(
            stock_code="000001",
            reports=False,
            regular_announcements=False,
            data_dir=str(tmp_path),
        )


def test_announcement_spider_filters_report_roles_by_scope(tmp_path) -> None:
    spider = CninfoAnnouncementSpider(
        stock_code="000001",
        reports=True,
        regular_announcements=False,
        report_scope="full",
        data_dir=str(tmp_path),
    )

    assert spider._should_include(
        {"document_type": "financial_report", "document_role": "full_report"}
    )
    assert not spider._should_include(
        {"document_type": "financial_report", "document_role": "report_summary"}
    )
    assert not spider._should_include(
        {"document_type": "financial_report", "document_role": "financial_statements"}
    )


def test_announcement_spider_rejects_invalid_report_scope(tmp_path) -> None:
    with pytest.raises(ValueError, match="invalid report_scope"):
        CninfoAnnouncementSpider(
            stock_code="000001",
            report_scope="unknown",
            data_dir=str(tmp_path),
        )


def test_company_spider_builds_three_dataset_requests(tmp_path) -> None:
    spider = CninfoCompanySpider(stock_code="000001", data_dir=str(tmp_path))
    security = {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    spider.security = security

    requests = list(spider.start_data_requests(security))

    assert len(requests) == 3
    assert {request.meta["request_kind"] for request in requests} == {
        "company_profile",
        "company_executives",
        "company_dividends",
    }


def test_pretty_json_is_enabled_by_default(tmp_path) -> None:
    spider = CninfoCompanySpider(stock_code="000001", data_dir=str(tmp_path))

    assert spider.pretty_json is True


@pytest.mark.parametrize("value", [False, "false", "0", "off"])
def test_pretty_json_can_be_disabled(value, tmp_path) -> None:
    spider = CninfoCompanySpider(
        stock_code="000001",
        pretty_json=value,
        data_dir=str(tmp_path),
    )

    assert spider.pretty_json is False


def test_market_spider_builds_two_independent_dataset_requests(tmp_path) -> None:
    spider = CninfoMarketSpider(stock_code="000001", data_dir=str(tmp_path))
    security = {
        "stock_code": "000001",
        "stock_name": "Test Bank",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    spider.security = security

    requests = list(spider.start_data_requests(security))

    assert {request.meta["request_kind"] for request in requests} == {
        "market_history",
        "market_code",
    }


def test_market_spider_can_disable_snapshot_and_history(tmp_path) -> None:
    spider = CninfoMarketSpider(
        stock_code="000001",
        snapshot=False,
        history=False,
        data_dir=str(tmp_path),
    )
    security = {
        "stock_code": "000001",
        "stock_name": "Test Bank",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    spider.security = security

    requests = list(spider.start_data_requests(security))

    assert requests == []


def test_financial_spider_starts_summary_and_sign_requests(tmp_path) -> None:
    spider = CninfoFinancialsSpider(stock_code="000001", data_dir=str(tmp_path))
    security = {
        "stock_code": "000001",
        "stock_name": "Test Bank",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    spider.security = security

    requests = list(spider.start_data_requests(security))

    assert {request.meta["request_kind"] for request in requests} == {
        "financial_summary",
        "financial_sign",
    }


def test_shareholder_spider_builds_seven_dataset_requests(tmp_path) -> None:
    spider = CninfoShareholdersSpider(stock_code="000001", data_dir=str(tmp_path))
    security = {
        "stock_code": "000001",
        "stock_name": "Test Bank",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    spider.security = security

    requests = list(spider.start_data_requests(security))

    assert len(requests) == 7
    assert {request.meta["request_kind"] for request in requests} == {
        "shareholder_stock_structure",
        "shareholder_shareholder_counts",
        "shareholder_fund_holdings",
        "shareholder_top_ten",
        "shareholder_top_ten_float",
        "shareholder_restricted_unlocks",
        "shareholder_equity_pledges",
    }


def test_trading_spider_builds_two_dataset_requests(tmp_path) -> None:
    spider = CninfoTradingSpider(stock_code="000001", data_dir=str(tmp_path))
    security = {
        "stock_code": "000001",
        "stock_name": "Test Bank",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    spider.security = security

    requests = list(spider.start_data_requests(security))

    assert len(requests) == 2
    assert {request.meta["request_kind"] for request in requests} == {
        "trading_margin_trading",
        "trading_block_trades",
    }
