from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
TAG_PATTERN = re.compile(r"<[^>]+>")
REPORT_PERIOD_PATTERN = re.compile(
    r"(?P<year>(?:19|20)\d{2})年"
    r"(?P<period>年度|半年度|中期|第一季度|一季度|第三季度|三季度)"
)
REPORT_VERSION_SUFFIX = r"(?:[（(]?(?:修订版?|更新后|更正后)[）)]?)?"
FULL_REPORT_PATTERN = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})年(?P<period>年度|半年度)报告"
    rf"(?:全文|正文)?{REPORT_VERSION_SUFFIX}$"
)
QUARTERLY_REPORT_PATTERN = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})年"
    rf"(?P<period>第一季度|一季度|第三季度|三季度)报告"
    rf"(?:全文|正文)?{REPORT_VERSION_SUFFIX}$"
)
REPORT_SUMMARY_PATTERN = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})年(?P<period>年度|半年度)报告摘要"
    rf"{REPORT_VERSION_SUFFIX}$"
)
FINANCIAL_STATEMENTS_PATTERN = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})年(?P<period>年度|半年度|中期)"
    rf"(?:财务报告|财务报表)(?:[（(]?未经审计[）)]?)?"
    rf"{REPORT_VERSION_SUFFIX}$"
)
REVIEW_REPORT_PATTERN = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})年(?P<period>年度|半年度|中期)"
    rf"(?:财务报告|财务报表)?审阅报告{REPORT_VERSION_SUFFIX}$"
)
AUDIT_REPORT_PATTERN = re.compile(
    rf"(?P<year>(?:19|20)\d{{2}})年(?P<period>年度|半年度|中期)"
    rf"(?:财务报告|财务报表)?审计报告{REPORT_VERSION_SUFFIX}$"
)
REPORT_PREFIX_RISK_MARKERS = (
    "关于",
    "延期",
    "问询",
    "回复",
    "提示",
    "更正",
    "审议",
    "披露",
    "说明",
    "取消",
)
REPORT_TYPES = {
    "年度": ("annual", "12-31"),
    "半年度": ("semiannual", "06-30"),
    "中期": ("semiannual", "06-30"),
    "第一季度": ("first_quarter", "03-31"),
    "一季度": ("first_quarter", "03-31"),
    "第三季度": ("third_quarter", "09-30"),
    "三季度": ("third_quarter", "09-30"),
}


class PayloadError(ValueError):
    """Raised when a CNINFO response does not match the expected shape."""


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    return unescape(TAG_PATTERN.sub("", value)).strip()


def parse_json_body(body: bytes | str) -> Any:
    if isinstance(body, bytes):
        body = body.decode("utf-8-sig")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadError("response is not valid UTF-8 JSON") from exc


def infer_exchange(stock_code: str, org_id: str = "") -> tuple[str, str]:
    """Return a display exchange and the CNINFO announcement column."""
    if org_id.startswith(("gssz", "nssc")) or stock_code.startswith(("00", "30")):
        return "SZSE", "szse"
    if org_id.startswith(("gssh", "990")) or stock_code.startswith(("60", "68")):
        return "SSE", "sse"
    if stock_code.startswith(("4", "8", "92")):
        return "BSE", "third"
    raise PayloadError(f"cannot infer exchange for stock code {stock_code}")


def parse_security_payload(body: bytes | str, stock_code: str) -> dict[str, str]:
    payload = parse_json_body(body)
    if not isinstance(payload, list):
        raise PayloadError("security response must be a JSON list")

    match = next(
        (
            entry
            for entry in payload
            if isinstance(entry, dict) and str(entry.get("code", "")) == stock_code
        ),
        None,
    )
    if match is None:
        raise PayloadError(f"stock code {stock_code} was not found")

    org_id = str(match.get("orgId") or "").strip()
    stock_name = clean_html(str(match.get("zwjc") or ""))
    if not org_id or not stock_name:
        raise PayloadError("security response is missing orgId or stock name")

    exchange, column = infer_exchange(stock_code, org_id)
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "org_id": org_id,
        "exchange": exchange,
        "column": column,
    }


def epoch_millis_to_iso(value: Any) -> str:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError) as exc:
        raise PayloadError(f"invalid announcement timestamp: {value!r}") from exc
    return datetime.fromtimestamp(milliseconds / 1000, tz=CHINA_TZ).isoformat()


def build_pdf_url(adjunct_url: str | None) -> str:
    if not adjunct_url:
        return ""
    if adjunct_url.startswith(("https://", "http://")):
        return adjunct_url
    return f"https://static.cninfo.com.cn/{adjunct_url.lstrip('/')}"


def _safe_report_suffix_match(pattern: re.Pattern[str], title: str) -> re.Match[str] | None:
    """Return a report suffix match unless its leading text looks like a related notice."""
    match = pattern.search(title)
    if match is None:
        return None
    prefix = title[: match.start()].strip("：:-—_（）()[]【】")
    if any(marker in prefix for marker in REPORT_PREFIX_RISK_MARKERS):
        return None
    return match


def classify_announcement_document(title: str, category: str = "") -> dict[str, Any]:
    """Classify report documents by role without matching report-related notices."""
    normalized_title = re.sub(r"\s+", "", clean_html(title))
    normalized_category = re.sub(r"\s+", "", clean_html(category))
    role = "regular_announcement"
    match = None
    if match := _safe_report_suffix_match(REVIEW_REPORT_PATTERN, normalized_title):
        role = "review_report"
    elif match := _safe_report_suffix_match(AUDIT_REPORT_PATTERN, normalized_title):
        role = "audit_report"
    elif match := _safe_report_suffix_match(REPORT_SUMMARY_PATTERN, normalized_title):
        role = "report_summary"
    elif match := _safe_report_suffix_match(FINANCIAL_STATEMENTS_PATTERN, normalized_title):
        role = "financial_statements"
    elif match := _safe_report_suffix_match(FULL_REPORT_PATTERN, normalized_title):
        role = "full_report"
    elif match := _safe_report_suffix_match(QUARTERLY_REPORT_PATTERN, normalized_title):
        role = "quarterly_report"
    elif "报告" in normalized_title:
        role = "report_related_notice"

    report_roles = {
        "full_report",
        "quarterly_report",
        "report_summary",
        "financial_statements",
        "review_report",
        "audit_report",
    }
    if role not in report_roles or match is None:
        return {
            "document_type": "announcement",
            "document_role": role,
            "report_type": None,
            "report_period": None,
            "is_full_report": False,
            "is_summary": False,
            "is_revision": False,
            "content_validation_status": "not_applicable",
            "analysis_eligible": False,
        }

    report_type, date_suffix = REPORT_TYPES[match.group("period")]
    classification_text = f"{normalized_title}{normalized_category}"
    return {
        "document_type": "financial_report",
        "document_role": role,
        "report_type": report_type,
        "report_period": f"{match.group('year')}-{date_suffix}",
        "is_full_report": role == "full_report",
        "is_summary": role == "report_summary",
        "is_revision": any(
            marker in classification_text for marker in ("修订", "更新后", "更正后")
        ),
        "content_validation_status": "pending" if role == "full_report" else "not_applicable",
        "analysis_eligible": False,
    }


def parse_announcement_payload(
    body: bytes | str,
    security: dict[str, str],
    crawled_at: str,
) -> tuple[list[dict[str, Any]], int]:
    payload = parse_json_body(body)
    if not isinstance(payload, dict):
        raise PayloadError("announcement response must be a JSON object")

    raw_announcements = payload.get("announcements")
    if raw_announcements is None:
        raw_announcements = []
    if not isinstance(raw_announcements, list):
        raise PayloadError("announcements must be a JSON list")

    records: list[dict[str, Any]] = []
    for raw in raw_announcements:
        if not isinstance(raw, dict):
            continue
        announcement_id = str(raw.get("announcementId") or "").strip()
        if not announcement_id:
            continue

        title = clean_html(str(raw.get("announcementTitle") or ""))
        category = clean_html(str(raw.get("announcementTypeName") or raw.get("categoryName") or ""))
        records.append(
            {
                "stock_code": str(raw.get("secCode") or security["stock_code"]),
                "stock_name": clean_html(str(raw.get("secName") or security["stock_name"])),
                "org_id": str(raw.get("orgId") or security["org_id"]),
                "exchange": security["exchange"],
                "announcement_id": announcement_id,
                "title": title,
                "category": category,
                **classify_announcement_document(title, category),
                "published_at": epoch_millis_to_iso(raw.get("announcementTime")),
                "pdf_url": build_pdf_url(raw.get("adjunctUrl")),
                "local_path": "",
                "download_status": "pending",
                "page_count": None,
                "requires_ocr": None,
                "validation_page_limit": 20,
                "validated_pages": 0,
                "matched_sections": [],
                "validation_errors": [],
                "crawled_at": crawled_at,
            }
        )

    try:
        total_records = int(payload.get("totalRecordNum") or payload.get("totalAnnouncement") or 0)
    except (TypeError, ValueError) as exc:
        raise PayloadError("invalid total record count") from exc
    return records, total_records


def _company_records(body: bytes | str) -> list[dict[str, Any]]:
    payload = parse_json_body(body)
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise PayloadError("company response code is not 200")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultMsg") != "success":
        raise PayloadError("company response resultMsg is not success")
    records = data.get("records")
    if not isinstance(records, list):
        raise PayloadError("company records must be a JSON list")
    return [record for record in records if isinstance(record, dict)]


def parse_company_profile_payload(body: bytes | str, stock_code: str) -> list[dict[str, Any]]:
    records = _company_records(body)
    if not records:
        return []
    record = records[0]
    basic_records = record.get("basicInformation") or []
    listing_records = record.get("listingInformation") or []
    if not isinstance(basic_records, list) or not basic_records:
        raise PayloadError("company profile is missing basicInformation")
    basic = basic_records[0] if isinstance(basic_records[0], dict) else {}
    listing = (
        listing_records[0]
        if isinstance(listing_records, list)
        and listing_records
        and isinstance(listing_records[0], dict)
        else {}
    )
    return [
        {
            "stock_code": str(listing.get("SECCODE") or stock_code),
            "stock_name": clean_html(str(basic.get("ASECNAME") or "")),
            "company_name": clean_html(str(basic.get("ORGNAME") or "")),
            "english_name": clean_html(str(basic.get("F001V") or "")),
            "former_names": clean_html(str(basic.get("F002V") or "")),
            "related_securities": clean_html(str(basic.get("F052V") or "")),
            "market": clean_html(str(basic.get("MARKET") or "")),
            "industry_name": clean_html(str(basic.get("F032V") or "")),
            "industry_source": "cninfo_company_profile",
            "industry_standard": None,
            "established_date": basic.get("F010D"),
            "listing_date": basic.get("F006D"),
            "legal_representative": clean_html(str(basic.get("F003V") or "")),
            "general_manager": clean_html(str(basic.get("F042V") or "")),
            "board_secretary": clean_html(str(basic.get("F018V") or "")),
            "postal_code": clean_html(str(basic.get("F006V") or "")),
            "registered_address": clean_html(str(basic.get("F004V") or "")),
            "office_address": clean_html(str(basic.get("F005V") or "")),
            "telephone": clean_html(str(basic.get("F013V") or "")),
            "fax": clean_html(str(basic.get("F014V") or "")),
            "website": clean_html(str(basic.get("F011V") or "")),
            "email": clean_html(str(basic.get("F012V") or "")),
            "par_value": listing.get("F007N"),
            "issue_price": listing.get("F008N"),
            "net_fundraising_10k": listing.get("F028N"),
            "lead_underwriter": clean_html(str(listing.get("F047V") or "")),
            "selected_indexes": clean_html(str(basic.get("F044V") or "")),
            "main_business": clean_html(str(basic.get("F015V") or "")),
            "business_scope": clean_html(str(basic.get("F016V") or "")),
            "company_profile": clean_html(str(basic.get("F017V") or "")),
        }
    ]


def parse_company_executives_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "human_id": str(record.get("F001V") or ""),
            "name": clean_html(str(record.get("F002V") or "")),
            "gender": clean_html(str(record.get("F010V") or "")),
            "birth_year": clean_html(str(record.get("F012V") or "")),
            "education": clean_html(str(record.get("F017V") or "")),
            "title": clean_html(str(record.get("F009V") or "")),
            "compensation_raw": record.get("F005N"),
            "shares_held_raw": record.get("F012N"),
            "sequence_id": record.get("SEQID"),
        }
        for record in _company_records(body)
    ]


def parse_company_dividends_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "report_period": clean_html(str(record.get("F001V") or "")),
            "distribution_plan": clean_html(str(record.get("F007V") or "")),
            "record_date": record.get("F018D"),
            "ex_dividend_date": record.get("F020D"),
            "payment_date": record.get("F023D"),
        }
        for record in _company_records(body)
    ]


def parse_financial_summary_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    records = _company_records(body)
    if not records:
        return []
    record = records[0]
    return [
        {
            "stock_code": stock_code,
            "report_date": record.get("ENDDATE"),
            "total_shares": record.get("F020N"),
            "float_shares": record.get("F021N"),
            "debt_ratio_percent": record.get("F041N"),
            "net_profit": record.get("F102N"),
            "revenue": record.get("F089N"),
            "cash_and_equivalents": record.get("F109N"),
            "roe_percent": record.get("F081N"),
            "goodwill": record.get("F115N"),
            "receivables": record.get("F111N"),
            "pledge_ratio_percent": record.get("F005N"),
        }
    ]


def parse_financial_sign_payload(body: bytes | str) -> str:
    records = _company_records(body)
    if not records:
        raise PayloadError("company info response contains no records")
    sign = str(records[0].get("F002N") or "").strip()
    if not sign:
        raise PayloadError("company info response is missing financial sign")
    return sign


FINANCIAL_INDICATOR_FIELDS = {
    "F004N": "basic_eps",
    "F008N": "net_assets_per_share",
    "F010N": "capital_reserve_per_share",
    "F053N": "net_profit_growth_percent",
    "F052N": "revenue_growth_percent",
    "F067N": "weighted_roe_percent",
    "F042N": "current_ratio",
    "F043N": "quick_ratio",
    "F041N": "debt_ratio_percent",
    "F022N": "receivables_turnover",
    "F023N": "inventory_turnover",
    "F029N": "current_assets_turnover",
    "F026N": "fixed_assets_turnover",
    "F025N": "total_assets_turnover",
    "F011N": "operating_profit_margin_percent",
    "F017N": "net_profit_margin_percent",
    "F078N": "gross_margin_percent",
    "F016N": "return_on_total_assets_percent",
    "F056N": "total_assets_growth_percent",
    "F058N": "operating_profit_growth_percent",
    "F054N": "net_assets_growth_percent",
}

REPORT_BUCKETS = {
    "year": ("annual", "12-31"),
    "three": ("third_quarter", "09-30"),
    "middle": ("semiannual", "06-30"),
    "one": ("first_quarter", "03-31"),
}


def _financial_buckets(body: bytes | str) -> dict[str, list[dict[str, Any]]]:
    records = _company_records(body)
    if not records:
        return {}
    root = records[0]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for bucket in REPORT_BUCKETS:
        values = root.get(bucket) or []
        if not isinstance(values, list):
            raise PayloadError(f"financial bucket {bucket} must be a JSON list")
        buckets[bucket] = [value for value in values if isinstance(value, dict)]
    return buckets


def parse_financial_indicators_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for bucket, records in _financial_buckets(body).items():
        report_type, _ = REPORT_BUCKETS[bucket]
        for record in records:
            report_date = str(record.get("ENDDATE") or "").strip()
            if not report_date:
                continue
            output = {
                "stock_code": stock_code,
                "report_date": report_date,
                "report_type": report_type,
            }
            output.update(
                {
                    field_name: record.get(source_field)
                    for source_field, field_name in FINANCIAL_INDICATOR_FIELDS.items()
                }
            )
            normalized[report_date] = output
    return [normalized[key] for key in sorted(normalized, reverse=True)]


def _parse_financial_statement_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for bucket, rows in _financial_buckets(body).items():
        report_type, date_suffix = REPORT_BUCKETS[bucket]
        for row in rows:
            item_name = clean_html(str(row.get("index") or ""))
            if not item_name:
                continue
            for year, value in row.items():
                if year == "index" or not re.fullmatch(r"\d{4}", str(year)):
                    continue
                report_date = f"{year}-{date_suffix}"
                record = normalized.setdefault(
                    report_date,
                    {
                        "stock_code": stock_code,
                        "report_date": report_date,
                        "report_type": report_type,
                        "items": {},
                    },
                )
                record["items"][item_name] = value
    return [normalized[key] for key in sorted(normalized, reverse=True)]


def parse_balance_sheets_payload(body: bytes | str, stock_code: str) -> list[dict[str, Any]]:
    return _parse_financial_statement_payload(body, stock_code)


def parse_income_statements_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return _parse_financial_statement_payload(body, stock_code)


def parse_cash_flow_statements_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return _parse_financial_statement_payload(body, stock_code)


def parse_stock_structure_payload(body: bytes | str, stock_code: str) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "change_date": record.get("VARYDATE"),
            "change_reason": clean_html(str(record.get("F002V") or "")),
            "circulating_shares_10k": record.get("F021N"),
            "rmb_common_shares_10k": record.get("F022N"),
            "domestic_b_shares_10k": record.get("F023N"),
            "overseas_h_shares_10k": record.get("F024N"),
            "restricted_shares_10k": record.get("F028N"),
            "total_shares_10k": record.get("F003N"),
        }
        for record in _company_records(body)
    ]


def parse_shareholder_counts_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "report_date": record.get("ENDDATE"),
            "shareholder_count": record.get("F001N"),
            "change_percent": record.get("F009N"),
        }
        for record in _company_records(body)
    ]


def parse_fund_holdings_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    """Parse CNINFO's five-year, stock-level fund holding aggregates."""
    return [
        {
            "stock_code": stock_code,
            "report_date": record.get("ENDDATE"),
            "fund_count": record.get("F001N"),
            "total_shares_held": record.get("F002N"),
        }
        for record in _company_records(body)
    ]


def _parse_top_shareholders_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "report_date": record.get("F001D"),
            "rank": record.get("F005N"),
            "shareholder_name": clean_html(str(record.get("F002V") or "")),
            "shares_held_10k": record.get("F003N"),
            "holding_percent": record.get("F004N"),
            "share_type": clean_html(str(record.get("F006V") or "")),
        }
        for record in _company_records(body)
    ]


def parse_top_ten_shareholders_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return _parse_top_shareholders_payload(body, stock_code)


def parse_top_ten_float_shareholders_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return _parse_top_shareholders_payload(body, stock_code)


def parse_restricted_unlocks_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "unlock_date": record.get("F003D"),
            "unlocked_shares_10k": record.get("F004N"),
            "unlocked_percent": record.get("F005N"),
        }
        for record in _company_records(body)
    ]


def parse_equity_pledges_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "announcement_date": record.get("DECLAREDATE"),
            "pledgor": clean_html(str(record.get("F001V") or "")),
            "pledgee": clean_html(str(record.get("F003V") or "")),
            "pledged_shares_10k": record.get("F006N"),
            "total_share_percent": record.get("F007N"),
            "released_shares_10k": record.get("F012N"),
        }
        for record in _company_records(body)
    ]


def parse_margin_trading_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "stock_name": clean_html(str(record.get("SECNAME") or "")),
            "trade_date": record.get("TRADEDATE"),
            "financing_balance": record.get("F001N"),
            "financing_buy_amount": record.get("F002N"),
            "securities_lending_remaining_volume": record.get("F004N"),
            "securities_lending_sell_volume": record.get("F006N"),
            "securities_lending_balance": record.get("F008N"),
            "margin_balance": record.get("F009N"),
        }
        for record in _company_records(body)
    ]


def parse_block_trades_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": stock_code,
            "stock_name": clean_html(str(record.get("SECNAME") or "")),
            "trade_date": record.get("TRADEDATE"),
            "trade_price": record.get("F004N"),
            "trade_volume_10k": record.get("F005N"),
            "trade_amount_10k": record.get("F006N"),
            "buyer": clean_html(str(record.get("F002V") or "")),
            "seller": clean_html(str(record.get("F003V") or "")),
        }
        for record in _company_records(body)
    ]


def parse_market_code_payload(body: bytes | str, stock_code: str) -> str:
    payload = parse_json_body(body)
    if not isinstance(payload, dict):
        raise PayloadError("market code response must be a JSON object")
    if str(payload.get("stockCode") or "") != stock_code:
        raise PayloadError("market code response does not match the requested stock")
    quote_code = str(payload.get("stockCodeCh") or "").strip()
    if not quote_code:
        raise PayloadError("market code response is missing stockCodeCh")
    return quote_code


def _parse_json_or_jsonp(body: bytes | str) -> Any:
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PayloadError("response is not valid UTF-8 JSONP") from exc
    else:
        text = body
    stripped = text.strip()
    if stripped.startswith(("[", "{")):
        return parse_json_body(stripped)
    match = re.fullmatch(r"[A-Za-z_$][\w$\.]*\s*\((.*)\)\s*;?", stripped, re.DOTALL)
    if not match:
        raise PayloadError("response is not valid JSON or JSONP")
    return parse_json_body(match.group(1))


def _optional_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    normalized = str(value).strip().replace(",", "").removesuffix("%")
    if not normalized or normalized in {"-", "--", "null", "None"}:
        return None
    try:
        number = float(normalized)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def parse_market_snapshot_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    payload = _parse_json_or_jsonp(body)
    if not isinstance(payload, list):
        raise PayloadError("market snapshot response must be a JSON list")
    if not payload:
        raise PayloadError("market snapshot response is empty")
    raw = payload[0]
    if not isinstance(raw, dict):
        raise PayloadError("market snapshot record must be a JSON object")

    last_price = _optional_number(raw.get("10") or raw.get("Last"))
    total_shares = _optional_number(raw.get("TotalShare"))
    float_shares = _optional_number(raw.get("Float"))
    return [
        {
            "stock_code": stock_code,
            "stock_name": raw.get("133") or raw.get("name") or "",
            "quote_time": raw.get("Time") or raw.get("time"),
            "last_price": last_price,
            "price_change": _optional_number(raw.get("264648") or raw.get("Change")),
            "price_change_percent": _optional_number(raw.get("199112") or raw.get("PercentChange")),
            "volume": _optional_number(raw.get("13") or raw.get("Volume")),
            "turnover_amount": _optional_number(raw.get("19") or raw.get("Amount")),
            "turnover_rate_percent": _optional_number(
                raw.get("1968584") or raw.get("TurnoverRate")
            ),
            "pe_ttm": _optional_number(raw.get("2034120") or raw.get("PE_TTM")),
            "pb_ratio": _optional_number(raw.get("1149395") or raw.get("PB")),
            "total_shares": total_shares,
            "float_shares": float_shares,
            "total_market_cap": (
                last_price * total_shares
                if last_price is not None and total_shares is not None
                else None
            ),
            "float_market_cap": (
                last_price * float_shares
                if last_price is not None and float_shares is not None
                else None
            ),
        }
    ]


def parse_market_history_payload(
    body: bytes | str,
    stock_code: str,
) -> list[dict[str, Any]]:
    payload = parse_json_body(body)
    if not isinstance(payload, dict):
        raise PayloadError("market history response must be a JSON object")
    lines = payload.get("line")
    if not isinstance(lines, list):
        message = clean_html(str(payload.get("content") or payload.get("msg") or ""))
        raise PayloadError(f"market history response is missing line data: {message}")

    records: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, list) or len(line) < 6:
            continue
        try:
            timestamp = int(line[0])
        except (TypeError, ValueError):
            continue
        records.append(
            {
                "stock_code": stock_code,
                "trade_date": datetime.fromtimestamp(
                    timestamp / 1000,
                    tz=CHINA_TZ,
                )
                .date()
                .isoformat(),
                "timestamp": timestamp,
                "open": _optional_number(line[1]),
                "close": _optional_number(line[2]),
                "high": _optional_number(line[3]),
                "low": _optional_number(line[4]),
                "volume": _optional_number(line[5]),
            }
        )
    if not records:
        raise PayloadError("market history response contains no valid records")
    return records
