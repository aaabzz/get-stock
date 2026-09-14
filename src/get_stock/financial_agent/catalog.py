from __future__ import annotations

from typing import Final

TOPIC_DATASETS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "growth": {
        "required": ("financial_indicators",),
        "optional": ("income_statements", "financial_summary"),
    },
    "profitability": {
        "required": ("financial_indicators",),
        "optional": ("income_statements", "balance_sheets"),
    },
    "earnings_quality": {
        "required": ("income_statements", "cash_flow_statements"),
        "optional": ("balance_sheets",),
    },
    "balance_sheet": {
        "required": ("balance_sheets",),
        "optional": ("financial_indicators", "financial_summary"),
    },
    "solvency": {
        "required": ("financial_indicators",),
        "optional": ("balance_sheets", "cash_flow_statements"),
    },
    "operating_efficiency": {
        "required": ("financial_indicators",),
        "optional": ("income_statements", "balance_sheets"),
    },
    "cash_flow": {
        "required": ("cash_flow_statements",),
        "optional": ("income_statements",),
    },
    "dividend": {
        "required": ("dividends",),
        "optional": ("income_statements", "cash_flow_statements"),
    },
    "capital_structure": {
        "required": ("stock_structure",),
        "optional": ("financial_summary",),
    },
}

COMPREHENSIVE_TOPICS: Final[tuple[str, ...]] = (
    "growth",
    "profitability",
    "earnings_quality",
    "balance_sheet",
    "solvency",
    "operating_efficiency",
    "cash_flow",
)

TOPIC_LABELS: Final[dict[str, str]] = {
    "growth": "成长能力",
    "profitability": "盈利能力",
    "earnings_quality": "盈利质量",
    "balance_sheet": "资产负债结构",
    "solvency": "偿债能力",
    "operating_efficiency": "运营效率",
    "cash_flow": "现金流",
    "dividend": "分红能力",
    "capital_structure": "股本结构",
}

REPORT_TYPES: Final[set[str]] = {
    "annual",
    "semiannual",
    "first_quarter",
    "third_quarter",
}
