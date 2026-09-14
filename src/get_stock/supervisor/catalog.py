"""Deterministic routing policy for the stock-analysis Supervisor."""

from __future__ import annotations

from typing import Final

from get_stock.agent_plugins import build_builtin_agent_types

_BUILTIN_AGENT_TYPES = build_builtin_agent_types()
AGENT_TOPIC_MAPS: Final[dict[str, dict[str, str]]] = _BUILTIN_AGENT_TYPES.topic_maps()

# synthesis topic -> (specialist agent, specialist topic)
SYNTHESIS_ROUTES: Final[dict[str, tuple[str, str]]] = _BUILTIN_AGENT_TYPES.routes()

STRUCTURED_AGENTS: Final[tuple[str, ...]] = _BUILTIN_AGENT_TYPES.structured_names()
REPORT_AGENT: Final[str] = "financial_report_analysis"
COMPREHENSIVE_AGENT: Final[str] = "comprehensive_analysis"

# User-facing recovery hints. Execution uses get_stock.acquisition's stricter registry.
DATASET_CRAWL_ACTIONS: Final[dict[str, str]] = {
    "company_profile": "crawl_company",
    "financial_summary": "crawl_financials",
    "financial_indicators": "crawl_financials",
    "balance_sheets": "crawl_financials",
    "income_statements": "crawl_financials",
    "cash_flow_statements": "crawl_financials",
    "dividends": "crawl_company",
    "market_snapshot": "crawl_market",
    "market_history": "crawl_market",
    "margin_trading": "crawl_trading",
    "block_trades": "crawl_trading",
    "stock_structure": "crawl_shareholders",
    "shareholder_counts": "crawl_shareholders",
    "fund_holdings": "crawl_shareholders",
    "top_ten_shareholders": "crawl_shareholders",
    "top_ten_float_shareholders": "crawl_shareholders",
    "restricted_unlocks": "crawl_shareholders",
    "equity_pledges": "crawl_shareholders",
}
