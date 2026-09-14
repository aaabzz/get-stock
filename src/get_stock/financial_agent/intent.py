from __future__ import annotations

import re
from dataclasses import dataclass

from get_stock.financial_agent.catalog import COMPREHENSIVE_TOPICS, REPORT_TYPES

TOPIC_KEYWORDS = {
    "growth": ("成长", "增长", "营收", "收入", "利润趋势"),
    "profitability": ("盈利能力", "利润率", "毛利率", "净利率", "roe", "roa"),
    "earnings_quality": ("盈利质量", "利润质量", "现金含量", "利润含金量"),
    "balance_sheet": ("资产负债", "资产结构", "负债结构"),
    "solvency": ("偿债", "流动比率", "速动比率", "负债率"),
    "operating_efficiency": ("运营效率", "经营效率", "周转率"),
    "cash_flow": ("现金流", "现金流量"),
    "dividend": ("分红", "派息", "股息"),
    "capital_structure": ("股本", "流通股", "限售股"),
}
CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass(frozen=True)
class FinancialIntent:
    stock_code: str
    topics: tuple[str, ...]
    years: int
    report_type: str
    question: str


def parse_financial_intent(
    question: str,
    *,
    stock_code: str | None = None,
    years: int | None = None,
    report_type: str | None = None,
) -> FinancialIntent:
    normalized = question.strip().lower()
    resolved_code = stock_code or _extract_stock_code(normalized)
    if not resolved_code:
        raise ValueError("a six-digit stock code is required")

    topics = tuple(
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    )
    if "综合" in normalized or "全面" in normalized or not topics:
        topics = COMPREHENSIVE_TOPICS

    resolved_years = years or _extract_years(normalized) or 3
    if not 1 <= resolved_years <= 10:
        raise ValueError("years must be between 1 and 10")
    resolved_report_type = report_type or _extract_report_type(normalized)
    if resolved_report_type not in REPORT_TYPES:
        raise ValueError(f"unsupported report_type: {resolved_report_type}")
    return FinancialIntent(
        stock_code=resolved_code,
        topics=tuple(dict.fromkeys(topics)),
        years=resolved_years,
        report_type=resolved_report_type,
        question=question,
    )


def _extract_stock_code(question: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", question)
    return match.group(1) if match else None


def _extract_years(question: str) -> int | None:
    match = re.search(r"(?:最近|近)(\d{1,2}|[一二三四五六七八九十])年", question)
    if not match:
        return None
    value = match.group(1)
    return int(value) if value.isdigit() else CHINESE_NUMBERS.get(value)


def _extract_report_type(question: str) -> str:
    if "半年" in question or "中报" in question:
        return "semiannual"
    if "一季" in question:
        return "first_quarter"
    if "三季" in question:
        return "third_quarter"
    return "annual"
