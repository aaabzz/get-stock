"""Auditable file allowlists used by specialist agents.

Keep filesystem access policy separate from analysis catalogs so adding a topic
does not implicitly grant access to another local file.
"""

from typing import Final

FINANCIAL_DATASET_FILES: Final[dict[str, str]] = {
    "company_profile": "company_profile.json",
    "financial_summary": "financial_summary.json",
    "financial_indicators": "financial_indicators.jsonl",
    "balance_sheets": "balance_sheets.jsonl",
    "income_statements": "income_statements.jsonl",
    "cash_flow_statements": "cash_flow_statements.jsonl",
    "dividends": "dividends.jsonl",
    "stock_structure": "stock_structure.jsonl",
    "equity_pledges": "equity_pledges.jsonl",
    "restricted_unlocks": "restricted_unlocks.jsonl",
}

MARKET_TRADING_DATASET_FILES: Final[dict[str, str]] = {
    "company_profile": "company_profile.json",
    "market_snapshot": "market_snapshot.json",
    "market_history": "market_history.jsonl",
    "margin_trading": "margin_trading.jsonl",
    "block_trades": "block_trades.jsonl",
    "stock_structure": "stock_structure.jsonl",
}

MARKET_TRADING_STATE_FILES: Final[dict[str, str]] = {
    "market_crawl_state": "market_crawl_state.json",
    "trading_crawl_state": "trading_crawl_state.json",
}

# dataset -> (state name, dataset key recorded by the corresponding pipeline)
MARKET_TRADING_STATE_KEYS: Final[dict[str, tuple[str, str]]] = {
    "market_snapshot": ("market_crawl_state", "snapshot"),
    "market_history": ("market_crawl_state", "history"),
    "margin_trading": ("trading_crawl_state", "margin_trading"),
    "block_trades": ("trading_crawl_state", "block_trades"),
}

SHAREHOLDER_DATASET_FILES: Final[dict[str, str]] = {
    "company_profile": "company_profile.json",
    "stock_structure": "stock_structure.jsonl",
    "shareholder_counts": "shareholder_counts.jsonl",
    "fund_holdings": "fund_holdings.jsonl",
    "top_ten_shareholders": "top_ten_shareholders.jsonl",
    "top_ten_float_shareholders": "top_ten_float_shareholders.jsonl",
    "restricted_unlocks": "restricted_unlocks.jsonl",
    "equity_pledges": "equity_pledges.jsonl",
}

SHAREHOLDER_STATE_FILES: Final[dict[str, str]] = {
    "shareholder_crawl_state": "shareholder_crawl_state.json",
}

SHAREHOLDER_STATE_KEYS: Final[dict[str, tuple[str, str]]] = {
    "stock_structure": ("shareholder_crawl_state", "stock_structure"),
    "shareholder_counts": ("shareholder_crawl_state", "shareholder_counts"),
    "fund_holdings": ("shareholder_crawl_state", "fund_holdings"),
    "top_ten_shareholders": ("shareholder_crawl_state", "top_ten"),
    "top_ten_float_shareholders": ("shareholder_crawl_state", "top_ten_float"),
    "restricted_unlocks": ("shareholder_crawl_state", "restricted_unlocks"),
    "equity_pledges": ("shareholder_crawl_state", "equity_pledges"),
}

# The report agent receives an allowlisted announcement ID from its upstream
# supervisor and may only open this single derived artifact below that report.
REPORT_AGENT_ALLOWED_FILENAME: Final[str] = "chunks.jsonl"
