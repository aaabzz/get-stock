from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.http import Request, Response

from get_stock.items import FinancialDatasetItem
from get_stock.parsers import (
    PayloadError,
    parse_balance_sheets_payload,
    parse_cash_flow_statements_payload,
    parse_financial_indicators_payload,
    parse_financial_sign_payload,
    parse_financial_summary_payload,
    parse_income_statements_payload,
)
from get_stock.spiders.base import CHINA_TZ, CninfoBaseMixin


class CninfoFinancialsSpider(CninfoBaseMixin, scrapy.Spider):
    name = "cninfo_financials"
    data_base_url = "https://www.cninfo.com.cn/data20"
    custom_settings = {
        "ITEM_PIPELINES": {
            "get_stock.pipelines.financials.FinancialDataPipeline": 200,
        }
    }
    datasets: tuple[tuple[str, str, Callable], ...] = (
        ("indicators", "getMainIndicators", parse_financial_indicators_payload),
        ("balance_sheets", "getBalanceSheets", parse_balance_sheets_payload),
        ("income_statements", "getIncomeStatement", parse_income_statements_payload),
        ("cash_flow_statements", "getCashFlowStatement", parse_cash_flow_statements_payload),
    )

    def __init__(self, stock_code: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(stock_code, *args, **kwargs)
        self.completed_datasets: set[str] = set()
        self.failed_datasets: dict[str, str] = {}

    def start_data_requests(self, security: dict[str, str]):
        headers = self._financial_headers(security)
        yield Request(
            self._url("companyOverview/getHeadStripData", scode=self.stock_code),
            headers=headers,
            callback=self.parse_dataset,
            cb_kwargs={"dataset": "summary", "parser": parse_financial_summary_payload},
            meta={"expect_json": True, "request_kind": "financial_summary"},
        )
        yield Request(
            self._url("companyOverview/getCompanyInfo", scode=self.stock_code),
            headers=headers,
            callback=self.parse_financial_sign,
            meta={"expect_json": True, "request_kind": "financial_sign"},
        )

    def parse_financial_sign(self, response: Response):
        if self.save_raw:
            self._save_raw("financial-sign-response.json", response.body)
        try:
            sign = parse_financial_sign_payload(response.body)
        except PayloadError as exc:
            self._record_failure("sign", exc, response)
            for dataset, _, _ in self.datasets:
                self.failed_datasets[dataset] = "financial sign is unavailable"
            return

        for dataset, endpoint, parser in self.datasets:
            yield Request(
                self._url(f"financialData/{endpoint}", scode=self.stock_code, sign=sign),
                headers=self._financial_headers(),
                callback=self.parse_dataset,
                cb_kwargs={"dataset": dataset, "parser": parser},
                meta={"expect_json": True, "request_kind": f"financial_{dataset}"},
            )

    def parse_dataset(self, response: Response, dataset: str, parser: Callable):
        if self.save_raw:
            self._save_raw(f"financial-{dataset}-response.json", response.body)
        try:
            records = parser(response.body, self.stock_code)
        except PayloadError as exc:
            self._record_failure(dataset, exc, response)
            return

        self.completed_datasets.add(dataset)
        self.crawler.stats.inc_value("get_stock/financial_datasets", 1)
        self.crawler.stats.inc_value("get_stock/financial_records", len(records))
        yield FinancialDatasetItem(
            dataset=dataset,
            stock_code=self.stock_code,
            records=records,
            source_url=response.url,
            crawled_at=datetime.now(CHINA_TZ).isoformat(),
        )

    def _record_failure(self, dataset: str, exc: PayloadError, response: Response) -> None:
        message = str(exc)
        self.failed_datasets[dataset] = message
        self.crawler.stats.inc_value("get_stock/financial_failed_datasets", 1)
        self._save_raw(f"financial-{dataset}-error-response.txt", response.body)
        self.logger.warning("Skipping financial dataset %s: %s", dataset, message)

    def _url(self, path: str, **params: str) -> str:
        return f"{self.data_base_url}/{path}?{urlencode(params)}"

    def _financial_headers(self, security: dict[str, str] | None = None) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Referer": self.detail_referer(security),
        }
