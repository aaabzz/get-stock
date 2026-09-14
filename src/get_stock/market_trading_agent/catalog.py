"""Market-trading topics and their structured-data requirements."""

from typing import Final

TOPIC_DATASETS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "price_trend": {
        "required": ("market_history",),
        "optional": ("market_snapshot",),
    },
    "volatility": {
        "required": ("market_history",),
        "optional": (),
    },
    "liquidity": {
        "required": ("market_history",),
        "optional": ("market_snapshot", "stock_structure"),
    },
    "price_volume": {
        "required": ("market_history",),
        "optional": ("margin_trading",),
    },
    "valuation": {
        "required": ("market_snapshot",),
        "optional": ("company_profile",),
    },
    "margin_activity": {
        "required": ("margin_trading",),
        "optional": ("market_history",),
    },
    "block_trades": {
        "required": ("block_trades",),
        "optional": ("market_history",),
    },
}

TOPIC_LABELS: Final[dict[str, str]] = {
    "price_trend": "价格趋势",
    "volatility": "波动风险",
    "liquidity": "流动性",
    "price_volume": "价量关系",
    "valuation": "估值快照",
    "margin_activity": "融资融券",
    "block_trades": "大宗交易",
}

COMPREHENSIVE_TOPICS: Final[tuple[str, ...]] = tuple(TOPIC_DATASETS)

MIN_RECORDS: Final[dict[str, int]] = {
    "market_history": 2,
    "margin_trading": 2,
}

FRESHNESS_DAYS: Final[dict[str, int]] = {
    "market_snapshot": 7,
    "market_history": 7,
    "margin_trading": 7,
}
