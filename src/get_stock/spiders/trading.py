from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import Request, Response

from get_stock.items import TradingDatasetItem
from get_stock.parsers import (
    PayloadError,
    parse_block_trades_payload,
    parse_margin_trading_payload,
)
from get_stock.spiders.base import CHINA_TZ, CninfoBaseMixin


class CninfoTradingSpider(CninfoBaseMixin, scrapy.Spider):
    name = "cninfo_trading"
    data_base_url = "https://www.cninfo.com.cn/data20/tradeInformation"
    custom_settings = {
        "ITEM_PIPELINES": {
            "get_stock.pipelines.trading.TradingDataPipeline": 200,
        }
    }
    datasets: tuple[tuple[str, str, Callable], ...] = (
        ("margin_trading", "getMarginTrading", parse_margin_trading_payload),
        ("block_trades", "getIntsDetail", parse_block_trades_payload),
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
                meta={"expect_json": True, "request_kind": f"trading_{dataset}"},
            )

    def parse_dataset(self, response: Response, dataset: str, parser: Callable):
        if self.save_raw:
            self._save_raw(f"trading-{dataset}-response.json", response.body)
        try:
            records = parser(response.body, self.stock_code)
        except PayloadError as exc:
            message = str(exc)
            self.failed_datasets[dataset] = message
            self.crawler.stats.inc_value("get_stock/trading_failed_datasets", 1)
            self._save_raw(f"trading-{dataset}-error-response.txt", response.body)
            self.logger.warning("Skipping trading dataset %s: %s", dataset, message)
            return

        self.completed_datasets.add(dataset)
        self.crawler.stats.inc_value("get_stock/trading_datasets", 1)
        self.crawler.stats.inc_value("get_stock/trading_records", len(records))
        yield TradingDatasetItem(
            dataset=dataset,
            stock_code=self.stock_code,
            records=records,
            source_url=response.url,
            crawled_at=datetime.now(CHINA_TZ).isoformat(),
        )
