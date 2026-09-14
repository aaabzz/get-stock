"""Shareholder-analysis topics and structured-data requirements."""

from typing import Final

TOPIC_DATASETS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "ownership_structure": {
        "required": ("stock_structure",),
        "optional": ("company_profile",),
    },
    "shareholder_concentration": {
        "required": ("top_ten_shareholders", "top_ten_float_shareholders"),
        "optional": ("stock_structure",),
    },
    "major_holder_changes": {
        "required": ("top_ten_shareholders",),
        "optional": ("top_ten_float_shareholders",),
    },
    "shareholder_count": {
        "required": ("shareholder_counts",),
        "optional": ("stock_structure",),
    },
    "fund_holdings": {
        "required": ("fund_holdings",),
        "optional": ("stock_structure",),
    },
    "restricted_unlocks": {
        "required": ("restricted_unlocks",),
        "optional": ("stock_structure",),
    },
    "equity_pledges": {
        "required": ("equity_pledges",),
        "optional": ("stock_structure",),
    },
}

TOPIC_LABELS: Final[dict[str, str]] = {
    "ownership_structure": "股本结构",
    "shareholder_concentration": "股东集中度",
    "major_holder_changes": "主要股东变化",
    "shareholder_count": "股东人数",
    "fund_holdings": "基金持股",
    "restricted_unlocks": "限售解禁",
    "equity_pledges": "股权质押",
}

COMPREHENSIVE_TOPICS: Final[tuple[str, ...]] = tuple(TOPIC_DATASETS)
EVENT_DATASETS: Final[set[str]] = {"restricted_unlocks", "equity_pledges"}
