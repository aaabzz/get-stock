from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from get_stock.spiders.company import CninfoCompanySpider
from get_stock.spiders.financials import CninfoFinancialsSpider
from get_stock.spiders.market import CninfoMarketSpider
from get_stock.spiders.shareholders import CninfoShareholdersSpider
from get_stock.spiders.trading import CninfoTradingSpider


@dataclass(frozen=True)
class CrawlerRegistration:
    spider_class: Any
    datasets: frozenset[str]


CRAWLER_REGISTRY: Final[dict[str, CrawlerRegistration]] = {
    "crawl_company": CrawlerRegistration(
        CninfoCompanySpider,
        frozenset({"company_profile", "dividends"}),
    ),
    "crawl_financials": CrawlerRegistration(
        CninfoFinancialsSpider,
        frozenset(
            {
                "financial_summary",
                "financial_indicators",
                "balance_sheets",
                "income_statements",
                "cash_flow_statements",
            }
        ),
    ),
    "crawl_market": CrawlerRegistration(
        CninfoMarketSpider,
        frozenset({"market_snapshot", "market_history"}),
    ),
    "crawl_shareholders": CrawlerRegistration(
        CninfoShareholdersSpider,
        frozenset(
            {
                "stock_structure",
                "shareholder_counts",
                "fund_holdings",
                "top_ten_shareholders",
                "top_ten_float_shareholders",
                "restricted_unlocks",
                "equity_pledges",
            }
        ),
    ),
    "crawl_trading": CrawlerRegistration(
        CninfoTradingSpider,
        frozenset({"margin_trading", "block_trades"}),
    ),
}

DATASET_ACTIONS: Final[dict[str, str]] = {
    dataset: action
    for action, registration in CRAWLER_REGISTRY.items()
    for dataset in registration.datasets
}
