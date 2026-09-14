from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import Request, Response

from get_stock.items import ShareholderDatasetItem
from get_stock.parsers import (
    PayloadError,
    parse_equity_pledges_payload,
    parse_fund_holdings_payload,
    parse_restricted_unlocks_payload,
    parse_shareholder_counts_payload,
    parse_stock_structure_payload,
    parse_top_ten_float_shareholders_payload,
    parse_top_ten_shareholders_payload,
)
from get_stock.spiders.base import CHINA_TZ, CninfoBaseMixin


class CninfoShareholdersSpider(CninfoBaseMixin, scrapy.Spider):
    name = "cninfo_shareholders"
    data_base_url = "https://www.cninfo.com.cn/data20/stockholderCapital"
    custom_settings = {
        "ITEM_PIPELINES": {
            "get_stock.pipelines.shareholders.ShareholderDataPipeline": 200,
        }
    }
    datasets: tuple[tuple[str, str, Callable], ...] = (
        ("stock_structure", "getStockStructure", parse_stock_structure_payload),
        ("shareholder_counts", "getStockholderNum", parse_shareholder_counts_payload),
        ("fund_holdings", "getFundHoldings", parse_fund_holdings_payload),
        ("top_ten", "getTopTenStockholders", parse_top_ten_shareholders_payload),
        (
            "top_ten_float",
            "getTopTenCirculatingStockholders",
            parse_top_ten_float_shareholders_payload,
        ),
        ("restricted_unlocks", "getLiftBan", parse_restricted_unlocks_payload),
        ("equity_pledges", "getEquityPledge", parse_equity_pledges_payload),
    )

    def __init__(self, stock_code: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(stock_code, *args, **kwargs)
        self.completed_datasets: set[str] = set()
        self.failed_datasets: dict[str, str] = {}

    def start_data_requests(self, security: dict[str, str]):
        for dataset, endpoint, parser in self.datasets:
            query = urlencode({"scode": self.stock_code})
            yield Request(
                f"{self.data_base_url}/{endpoint}?{query}",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": self.detail_referer(security),
                },
                callback=self.parse_dataset,
                cb_kwargs={"dataset": dataset, "parser": parser},
                meta={"expect_json": True, "request_kind": f"shareholder_{dataset}"},
            )

    def parse_dataset(self, response: Response, dataset: str, parser: Callable):
        if self.save_raw:
            self._save_raw(f"shareholder-{dataset}-response.json", response.body)
        try:
            records = parser(response.body, self.stock_code)
        except PayloadError as exc:
            message = str(exc)
            self.failed_datasets[dataset] = message
            self.crawler.stats.inc_value("get_stock/shareholder_failed_datasets", 1)
            self._save_raw(f"shareholder-{dataset}-error-response.txt", response.body)
            self.logger.warning("Skipping shareholder dataset %s: %s", dataset, message)
            return

        self.completed_datasets.add(dataset)
        self.crawler.stats.inc_value("get_stock/shareholder_datasets", 1)
        self.crawler.stats.inc_value("get_stock/shareholder_records", len(records))
        yield ShareholderDatasetItem(
            dataset=dataset,
            stock_code=self.stock_code,
            records=records,
            source_url=response.url,
            crawled_at=datetime.now(CHINA_TZ).isoformat(),
        )
