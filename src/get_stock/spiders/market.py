from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import FormRequest, Request, Response

from get_stock.items import MarketDatasetItem
from get_stock.parsers import (
    PayloadError,
    parse_market_code_payload,
    parse_market_history_payload,
    parse_market_snapshot_payload,
)
from get_stock.spiders.base import CHINA_TZ, CninfoBaseMixin, as_bool


class CninfoMarketSpider(CninfoBaseMixin, scrapy.Spider):
    name = "cninfo_market"
    market_code_url = "https://www.cninfo.com.cn/data/common/getSzShStock"
    snapshot_url = "https://api.cninfo.com.cn/v5/hq/dataItem"
    history_url = "https://www.cninfo.com.cn/data/cube/dailyLine"
    custom_settings = {
        "ITEM_PIPELINES": {
            "get_stock.pipelines.market.MarketDataPipeline": 200,
        }
    }

    def __init__(
        self,
        stock_code: str,
        snapshot: bool | str = True,
        history: bool | str = True,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(stock_code, *args, **kwargs)
        self.fetch_snapshot = as_bool(snapshot)
        self.fetch_history = as_bool(history)
        self.completed_datasets: set[str] = set()
        self.failed_datasets: dict[str, str] = {}

    def start_data_requests(self, security: dict[str, str]):
        if self.fetch_history:
            yield Request(
                f"{self.history_url}?{urlencode({'stockCode': self.stock_code})}",
                headers=self._market_headers(security),
                callback=self.parse_dataset,
                cb_kwargs={"dataset": "history", "parser": parse_market_history_payload},
                meta={"expect_json": True, "request_kind": "market_history"},
            )

        if self.fetch_snapshot:
            yield FormRequest(
                self.market_code_url,
                method="POST",
                formdata={"stockCode": self.stock_code},
                headers=self._market_headers(security),
                callback=self.parse_market_code,
                meta={"expect_json": True, "request_kind": "market_code"},
            )

    def parse_market_code(self, response: Response):
        if self.save_raw:
            self._save_raw("market-code-response.json", response.body)
        try:
            quote_code = parse_market_code_payload(response.body, self.stock_code)
        except PayloadError as exc:
            self._record_failure("snapshot", exc, response)
            return

        query = urlencode({"codelist": quote_code, "jsonpCallback": "getStockCallback"})
        yield Request(
            f"{self.snapshot_url}?{query}",
            headers=self._market_headers(),
            callback=self.parse_dataset,
            cb_kwargs={"dataset": "snapshot", "parser": parse_market_snapshot_payload},
            meta={"expect_json": False, "request_kind": "market_snapshot"},
        )

    def parse_dataset(
        self,
        response: Response,
        dataset: str,
        parser: Callable,
    ):
        if self.save_raw:
            suffix = "jsonp" if dataset == "snapshot" else "json"
            self._save_raw(f"market-{dataset}-response.{suffix}", response.body)
        try:
            records = parser(response.body, self.stock_code)
        except PayloadError as exc:
            self._record_failure(dataset, exc, response)
            return

        self.completed_datasets.add(dataset)
        self.crawler.stats.inc_value("get_stock/market_datasets", 1)
        self.crawler.stats.inc_value("get_stock/market_records", len(records))
        yield MarketDatasetItem(
            dataset=dataset,
            stock_code=self.stock_code,
            records=records,
            source_url=response.url,
            crawled_at=datetime.now(CHINA_TZ).isoformat(),
        )

    def _record_failure(self, dataset: str, exc: PayloadError, response: Response) -> None:
        message = str(exc)
        self.failed_datasets[dataset] = message
        self.crawler.stats.inc_value("get_stock/market_failed_datasets", 1)
        self._save_raw(f"market-{dataset}-error-response.txt", response.body)
        self.logger.warning("Skipping market dataset %s: %s", dataset, message)

    def _market_headers(self, security: dict[str, str] | None = None) -> dict[str, str]:
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": self.detail_referer(security),
            "X-Requested-With": "XMLHttpRequest",
        }
