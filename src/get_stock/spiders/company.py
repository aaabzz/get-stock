from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import Request, Response

from get_stock.items import CompanyDatasetItem
from get_stock.parsers import (
    PayloadError,
    parse_company_dividends_payload,
    parse_company_executives_payload,
    parse_company_profile_payload,
)
from get_stock.spiders.base import CHINA_TZ, CninfoBaseMixin


class CninfoCompanySpider(CninfoBaseMixin, scrapy.Spider):
    name = "cninfo_company"
    company_base_url = "https://www.cninfo.com.cn/data20/companyOverview"
    custom_settings = {
        "ITEM_PIPELINES": {
            "get_stock.pipelines.company.CompanyDataPipeline": 200,
        }
    }

    datasets: tuple[tuple[str, str, Callable], ...] = (
        ("profile", "getCompanyIntroduction", parse_company_profile_payload),
        ("executives", "getCompanyExecutives", parse_company_executives_payload),
        ("dividends", "getCompanyHisDividend", parse_company_dividends_payload),
    )

    def __init__(self, stock_code: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(stock_code, *args, **kwargs)
        self.completed_datasets: set[str] = set()

    def start_data_requests(self, security: dict[str, str]):
        for dataset, endpoint, parser in self.datasets:
            query = urlencode({"scode": self.stock_code})
            yield Request(
                url=f"{self.company_base_url}/{endpoint}?{query}",
                method="GET",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": self.detail_referer(security),
                },
                callback=self.parse_company_dataset,
                cb_kwargs={"dataset": dataset, "parser": parser},
                meta={"expect_json": True, "request_kind": f"company_{dataset}"},
            )

    def parse_company_dataset(
        self,
        response: Response,
        dataset: str,
        parser: Callable,
    ):
        if self.save_raw:
            self._save_raw(f"company-{dataset}-response.json", response.body)
        try:
            records = parser(response.body, self.stock_code)
        except PayloadError as exc:
            self._save_raw(f"company-{dataset}-error-response.txt", response.body)
            raise CloseSpider(reason=f"invalid_company_{dataset}_response: {exc}") from exc

        self.completed_datasets.add(dataset)
        self.crawler.stats.inc_value("get_stock/company_datasets", 1)
        self.crawler.stats.inc_value("get_stock/company_records", len(records))
        yield CompanyDatasetItem(
            dataset=dataset,
            stock_code=self.stock_code,
            records=records,
            source_url=response.url,
            crawled_at=datetime.now(CHINA_TZ).isoformat(),
        )
