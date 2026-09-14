from __future__ import annotations

import re
from dataclasses import dataclass

from get_stock.market_trading_agent.catalog import COMPREHENSIVE_TOPICS

TOPIC_KEYWORDS = {
    "price_trend": ("价格", "股价", "涨跌", "走势", "趋势"),
    "volatility": ("波动", "回撤", "振幅", "风险"),
    "liquidity": ("流动性", "成交量", "成交额", "换手"),
    "price_volume": ("价量", "量价", "放量", "缩量"),
    "valuation": ("估值", "市盈率", "市净率", "pe", "pb", "市值"),
    "margin_activity": ("融资融券", "两融", "融资余额", "融券"),
    "block_trades": ("大宗交易", "大宗", "折价", "溢价"),
}


@dataclass(frozen=True)
class MarketTradingIntent:
    stock_code: str
    topics: tuple[str, ...]
    lookback_sessions: int
    question: str


def parse_market_trading_intent(
    question: str,
    *,
    stock_code: str | None = None,
    lookback_sessions: int | None = None,
) -> MarketTradingIntent:
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
    sessions = lookback_sessions or _extract_sessions(normalized) or 60
    if not 2 <= sessions <= 500:
        raise ValueError("lookback sessions must be between 2 and 500")
    return MarketTradingIntent(
        stock_code=resolved_code,
        topics=tuple(dict.fromkeys(topics)),
        lookback_sessions=sessions,
        question=question,
    )


def _extract_stock_code(question: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", question)
    return match.group(1) if match else None


def _extract_sessions(question: str) -> int | None:
    match = re.search(r"(?:最近|近)\s*(\d{1,3})\s*(?:个)?交易日", question)
    return int(match.group(1)) if match else None
