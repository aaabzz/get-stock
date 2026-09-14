import json

import pytest

from get_stock.parsers import (
    PayloadError,
    classify_announcement_document,
    clean_html,
    parse_announcement_payload,
    parse_balance_sheets_payload,
    parse_block_trades_payload,
    parse_company_dividends_payload,
    parse_company_executives_payload,
    parse_company_profile_payload,
    parse_financial_indicators_payload,
    parse_financial_summary_payload,
    parse_fund_holdings_payload,
    parse_margin_trading_payload,
    parse_market_code_payload,
    parse_market_history_payload,
    parse_market_snapshot_payload,
    parse_security_payload,
    parse_shareholder_counts_payload,
    parse_stock_structure_payload,
    parse_top_ten_shareholders_payload,
)


def test_parse_security_payload_selects_exact_stock_code() -> None:
    body = json.dumps(
        [
            {"code": "000002", "zwjc": "万科A", "orgId": "gssz0000002"},
            {"code": "000001", "zwjc": "平安银行", "orgId": "gssz0000001"},
        ],
        ensure_ascii=False,
    )

    result = parse_security_payload(body, "000001")

    assert result == {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }


def test_parse_security_payload_rejects_unknown_stock() -> None:
    with pytest.raises(PayloadError, match="was not found"):
        parse_security_payload("[]", "000001")


def test_parse_announcement_payload_normalizes_record() -> None:
    security = {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "org_id": "gssz0000001",
        "exchange": "SZSE",
        "column": "szse",
    }
    body = json.dumps(
        {
            "totalAnnouncement": 1,
            "totalRecordNum": 1,
            "announcements": [
                {
                    "announcementId": "1225490393",
                    "secCode": "000001",
                    "secName": "平安银行",
                    "orgId": "gssz0000001",
                    "announcementTitle": "关于<em>董事</em>任职的公告",
                    "announcementTime": 1787328000000,
                    "adjunctUrl": "finalpage/2026-08-22/1225490393.PDF",
                    "announcementTypeName": "公司治理",
                }
            ],
        },
        ensure_ascii=False,
    )

    records, total = parse_announcement_payload(
        body,
        security,
        "2026-08-29T12:00:00+08:00",
    )

    assert total == 1
    assert len(records) == 1
    assert records[0]["announcement_id"] == "1225490393"
    assert records[0]["title"] == "关于董事任职的公告"
    assert records[0]["published_at"] == "2026-08-22T00:00:00+08:00"
    assert records[0]["pdf_url"] == (
        "https://static.cninfo.com.cn/finalpage/2026-08-22/1225490393.PDF"
    )
    assert records[0]["document_type"] == "announcement"
    assert records[0]["report_type"] is None


@pytest.mark.parametrize(
    (
        "title",
        "report_type",
        "report_period",
        "document_role",
        "is_summary",
        "is_revision",
        "is_full_report",
    ),
    [
        ("2025年年度报告", "annual", "2025-12-31", "full_report", False, False, True),
        (
            "2025年年度报告摘要",
            "annual",
            "2025-12-31",
            "report_summary",
            True,
            False,
            False,
        ),
        (
            "2026年半年度财务报告",
            "semiannual",
            "2026-06-30",
            "financial_statements",
            False,
            False,
            False,
        ),
        (
            "2026年第一季度报告",
            "first_quarter",
            "2026-03-31",
            "quarterly_report",
            False,
            False,
            False,
        ),
        (
            "2026年第三季度报告（修订版）",
            "third_quarter",
            "2026-09-30",
            "quarterly_report",
            False,
            True,
            False,
        ),
    ],
)
def test_classify_announcement_document_recognizes_periodic_reports(
    title,
    report_type,
    report_period,
    document_role,
    is_summary,
    is_revision,
    is_full_report,
) -> None:
    result = classify_announcement_document(title)

    assert result == {
        "document_type": "financial_report",
        "document_role": document_role,
        "report_type": report_type,
        "report_period": report_period,
        "is_summary": is_summary,
        "is_revision": is_revision,
        "is_full_report": is_full_report,
        "content_validation_status": "pending" if is_full_report else "not_applicable",
        "analysis_eligible": False,
    }


@pytest.mark.parametrize(
    ("title", "document_role"),
    [
        ("2026年半年度财务报告审阅报告", "review_report"),
        ("2025年年度财务报告审计报告", "audit_report"),
    ],
)
def test_classify_announcement_document_recognizes_assurance_reports(title, document_role) -> None:
    result = classify_announcement_document(title)

    assert result["document_type"] == "financial_report"
    assert result["document_role"] == document_role
    assert result["is_full_report"] is False
    assert result["analysis_eligible"] is False


@pytest.mark.parametrize(
    ("stock_code", "title", "document_role"),
    [
        ("000001", "2025年年度报告", "full_report"),
        ("688126", "沪硅产业2026年半年度报告", "full_report"),
        (
            "600519",
            "贵州茅台酒股份有限公司：2025年年度报告",
            "full_report",
        ),
        ("300750", "宁德时代-2025年年度报告摘要", "report_summary"),
        (
            "688981",
            "中芯国际2025年年度财务报表（未经审计）",
            "financial_statements",
        ),
        (
            "601398",
            "中国工商银行2025年年度财务报告审计报告",
            "audit_report",
        ),
    ],
)
def test_report_suffix_rules_support_multiple_stock_title_prefixes(
    stock_code, title, document_role
) -> None:
    result = classify_announcement_document(title)

    assert stock_code.isdigit()
    assert result["document_type"] == "financial_report"
    assert result["document_role"] == document_role


@pytest.mark.parametrize(
    "title",
    [
        "沪硅产业关于延期披露2026年半年度报告",
        "关于公司2025年年度报告",
        "董事会审议通过2025年年度报告",
        "关于2025年年度财务报告审计报告",
    ],
)
def test_report_suffix_rules_reject_risky_notice_prefixes(title) -> None:
    result = classify_announcement_document(title)

    assert result["document_type"] == "announcement"
    assert result["document_role"] == "report_related_notice"


@pytest.mark.parametrize(
    ("title", "document_role"),
    [
        ("关于延期披露2025年年度报告的公告", "report_related_notice"),
        ("关于召开2026年半年度业绩说明会的公告", "regular_announcement"),
        ("2025年年度报告问询函", "report_related_notice"),
        ("独立董事年度述职报告", "report_related_notice"),
    ],
)
def test_classify_announcement_document_does_not_match_report_related_notices(
    title, document_role
) -> None:
    result = classify_announcement_document(title)

    assert result["document_type"] == "announcement"
    assert result["document_role"] == document_role
    assert result["report_period"] is None


def test_clean_html_handles_entities_and_tags() -> None:
    assert clean_html("A&amp;B <em>报告</em>") == "A&B 报告"


def company_payload(records) -> str:
    return json.dumps(
        {"code": 200, "data": {"resultMsg": "success", "records": records}},
        ensure_ascii=False,
    )


def test_parse_company_profile_payload_maps_f_fields() -> None:
    body = company_payload(
        [
            {
                "basicInformation": [
                    {
                        "ORGNAME": "平安银行股份有限公司",
                        "ASECNAME": "平安银行",
                        "F032V": "货币金融服务",
                        "F011V": "bank.pingan.com",
                        "F015V": "银行业务",
                    }
                ],
                "listingInformation": [{"SECCODE": "000001", "F008N": 40}],
            }
        ]
    )

    records = parse_company_profile_payload(body, "000001")

    assert records[0]["company_name"] == "平安银行股份有限公司"
    assert records[0]["industry_name"] == "货币金融服务"
    assert records[0]["industry_source"] == "cninfo_company_profile"
    assert records[0]["industry_standard"] is None
    assert "industry" not in records[0]
    assert records[0]["website"] == "bank.pingan.com"
    assert records[0]["issue_price"] == 40


def test_parse_company_executives_payload_maps_records() -> None:
    body = company_payload(
        [
            {
                "F001V": "8801370890",
                "F002V": "谢永林",
                "F010V": "男",
                "F012V": "1969",
                "F017V": "博士研究生",
                "F009V": "董事长",
                "F005N": 26700,
            }
        ]
    )

    records = parse_company_executives_payload(body, "000001")

    assert records[0]["name"] == "谢永林"
    assert records[0]["title"] == "董事长"
    assert records[0]["compensation_raw"] == 26700


def test_parse_company_dividends_payload_maps_records() -> None:
    body = company_payload(
        [
            {
                "F001V": "2025年报",
                "F007V": "10派3.6元(含税)",
                "F018D": "2026-06-11",
                "F020D": "2026-06-12",
                "F023D": "2026-06-12",
            }
        ]
    )

    records = parse_company_dividends_payload(body, "000001")

    assert records[0]["report_period"] == "2025年报"
    assert records[0]["distribution_plan"] == "10派3.6元(含税)"
    assert records[0]["record_date"] == "2026-06-11"


def test_parse_financial_summary_payload_maps_head_strip_fields() -> None:
    body = company_payload(
        [
            {
                "ENDDATE": "2026-06-30T00:00:00.000+00:00",
                "F020N": 1000,
                "F021N": 800,
                "F041N": 90.5,
                "F102N": 200,
                "F089N": 500,
                "F081N": 4.6,
            }
        ]
    )

    records = parse_financial_summary_payload(body, "000001")

    assert records[0]["total_shares"] == 1000
    assert records[0]["float_shares"] == 800
    assert records[0]["debt_ratio_percent"] == 90.5
    assert records[0]["roe_percent"] == 4.6


def test_parse_financial_indicators_payload_normalizes_report_periods() -> None:
    body = company_payload(
        [
            {
                "year": [{"ENDDATE": "2025-12-31", "F004N": 1.2, "F067N": 8.5}],
                "three": [],
                "middle": [],
                "one": [],
            }
        ]
    )

    records = parse_financial_indicators_payload(body, "000001")

    assert records[0]["report_type"] == "annual"
    assert records[0]["basic_eps"] == 1.2
    assert records[0]["weighted_roe_percent"] == 8.5


def test_parse_balance_sheets_payload_transposes_items_by_period() -> None:
    body = company_payload(
        [
            {
                "year": [
                    {"index": "资产总计", "2025": 1000},
                    {"index": "负债合计", "2025": 800},
                ],
                "three": [],
                "middle": [],
                "one": [],
            }
        ]
    )

    records = parse_balance_sheets_payload(body, "000001")

    assert records[0]["report_date"] == "2025-12-31"
    assert records[0]["items"] == {"资产总计": 1000, "负债合计": 800}


def test_parse_shareholder_datasets_maps_named_fields() -> None:
    structure = parse_stock_structure_payload(
        company_payload([{"VARYDATE": "2026-01-01", "F021N": 800, "F003N": 1000}]),
        "000001",
    )
    counts = parse_shareholder_counts_payload(
        company_payload([{"ENDDATE": "2026-06-30", "F001N": 500000, "F009N": -1.2}]),
        "000001",
    )
    holders = parse_top_ten_shareholders_payload(
        company_payload([{"F001D": "2026-06-30", "F005N": 1, "F002V": "第一股东", "F003N": 100}]),
        "000001",
    )
    fund_holdings = parse_fund_holdings_payload(
        company_payload([{"ENDDATE": "2026-06-30", "F001N": 706, "F002N": 659032806}]),
        "000001",
    )

    assert structure[0]["total_shares_10k"] == 1000
    assert counts[0]["shareholder_count"] == 500000
    assert holders[0]["rank"] == 1
    assert holders[0]["shareholder_name"] == "第一股东"
    assert fund_holdings == [
        {
            "stock_code": "000001",
            "report_date": "2026-06-30",
            "fund_count": 706,
            "total_shares_held": 659032806,
        }
    ]


def test_parse_market_code_payload_returns_quote_code() -> None:
    body = json.dumps({"stockCode": "000001", "stockCodeCh": "sz000001"})

    assert parse_market_code_payload(body, "000001") == "sz000001"


def test_parse_trading_datasets_maps_cninfo_fields_and_units() -> None:
    margin_records = parse_margin_trading_payload(
        company_payload(
            [
                {
                    "SECNAME": "平安银行",
                    "TRADEDATE": "2026-08-31",
                    "F001N": 4624889163,
                    "F002N": 85234079,
                    "F004N": 6780565,
                    "F006N": 43700,
                    "F008N": 79468222,
                    "F009N": 4704357385,
                }
            ]
        ),
        "000001",
    )
    block_records = parse_block_trades_payload(
        company_payload(
            [
                {
                    "SECNAME": "平安银行",
                    "TRADEDATE": "2026-07-09",
                    "F004N": 10.49,
                    "F005N": 886.72,
                    "F006N": 9301.693,
                    "F002V": "机构专用",
                    "F003V": "机构专用",
                }
            ]
        ),
        "000001",
    )

    assert margin_records[0]["financing_balance"] == 4624889163
    assert margin_records[0]["securities_lending_sell_volume"] == 43700
    assert margin_records[0]["margin_balance"] == 4704357385
    assert block_records[0]["trade_price"] == 10.49
    assert block_records[0]["trade_volume_10k"] == 886.72
    assert block_records[0]["trade_amount_10k"] == 9301.693


def test_parse_market_snapshot_payload_supports_jsonp_and_calculates_market_cap() -> None:
    body = (
        'callback([{"10":12.5,"13":100,"19":1250,"TotalShare":1000,'
        '"Float":800,"2034120":8.2,"1149395":0.9,"1968584":1.5}])'
    )

    records = parse_market_snapshot_payload(body, "000001")

    assert records[0]["last_price"] == 12.5
    assert records[0]["volume"] == 100
    assert records[0]["pe_ttm"] == 8.2
    assert records[0]["total_market_cap"] == 12500
    assert records[0]["float_market_cap"] == 10000


def test_parse_market_snapshot_payload_rejects_empty_quote() -> None:
    with pytest.raises(PayloadError, match="empty"):
        parse_market_snapshot_payload("callback([])", "000001")


def test_parse_market_history_payload_maps_ohlcv_order() -> None:
    body = json.dumps({"line": [[0, 10, 11, 12, 9, 1000]]})

    records = parse_market_history_payload(body, "000001")

    assert records == [
        {
            "stock_code": "000001",
            "trade_date": "1970-01-01",
            "timestamp": 0,
            "open": 10,
            "close": 11,
            "high": 12,
            "low": 9,
            "volume": 1000,
        }
    ]
