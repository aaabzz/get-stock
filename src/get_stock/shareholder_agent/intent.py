from __future__ import annotations

import re
from dataclasses import dataclass

from get_stock.shareholder_agent.catalog import COMPREHENSIVE_TOPICS

TOPIC_KEYWORDS = {
    "ownership_structure": ("股本结构", "总股本", "流通股", "限售股"),
    "shareholder_concentration": ("集中度", "十大股东", "十大流通股东"),
    "major_holder_changes": ("股东变化", "股东增持", "股东减持", "新进", "退出"),
    "shareholder_count": ("股东人数", "股东户数", "户数"),
    "fund_holdings": ("基金持股", "基金数量", "基金家数"),
    "restricted_unlocks": ("限售解禁", "解禁"),
    "equity_pledges": ("股权质押", "质押", "解除质押"),
}


@dataclass(frozen=True)
class ShareholderIntent:
    stock_code: str
    topics: tuple[str, ...]
    max_periods: int
    question: str


def parse_shareholder_intent(
    question: str,
    *,
    stock_code: str | None = None,
    max_periods: int | None = None,
) -> ShareholderIntent:
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
    periods = max_periods or _extract_periods(normalized) or 4
    if not 1 <= periods <= 20:
        raise ValueError("max periods must be between 1 and 20")
    return ShareholderIntent(
        stock_code=resolved_code,
        topics=tuple(dict.fromkeys(topics)),
        max_periods=periods,
        question=question,
    )


def _extract_stock_code(question: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", question)
    return match.group(1) if match else None


def _extract_periods(question: str) -> int | None:
    match = re.search(r"(?:最近|近)\s*(\d{1,2})\s*(?:个)?(?:期|季度)", question)
    return int(match.group(1)) if match else None
