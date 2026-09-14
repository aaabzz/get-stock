"""Shared specialist-to-synthesis topic vocabulary, independent of Agent runtimes."""

from typing import Final

FINANCIAL_TOPIC_MAP: Final[dict[str, str]] = {
    "growth": "financial_performance",
    "profitability": "profitability",
    "earnings_quality": "earnings_quality",
    "balance_sheet": "balance_sheet",
    "solvency": "solvency",
    "operating_efficiency": "operating_efficiency",
    "cash_flow": "cash_flow",
    "dividend": "dividends",
    "capital_structure": "capital_structure",
}

MARKET_TOPIC_MAP: Final[dict[str, str]] = {
    "price_trend": "market_price_trend",
    "volatility": "volatility",
    "liquidity": "liquidity",
    "price_volume": "price_volume",
    "valuation": "valuation",
    "margin_activity": "margin_activity",
    "block_trades": "block_trades",
}

SHAREHOLDER_TOPIC_MAP: Final[dict[str, str]] = {
    "ownership_structure": "ownership_structure",
    "shareholder_concentration": "shareholder_concentration",
    "major_holder_changes": "holder_changes",
    "shareholder_count": "shareholder_count",
    "fund_holdings": "fund_holdings",
    "restricted_unlocks": "restricted_unlocks",
    "equity_pledges": "equity_pledges",
}

REPORT_TOPIC_MAP: Final[dict[str, str]] = {
    "business_overview": "business_overview",
    "industry_position": "industry_position",
    "market_share_disclosure": "market_share",
    "competitive_advantage": "competitive_advantage",
    "technology_advantage": "technology_advantage",
    "research_and_development": "research_development",
    "growth_drivers": "growth_drivers",
    "management_explanation": "management_explanation",
    "business_risks": "business_risks",
    "customer_supplier_dependency": "customer_supplier_dependency",
    "development_strategy": "development_strategy",
}
