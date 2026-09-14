from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scrapy.exceptions import CloseSpider
from scrapy.http import FormRequest, Response

from get_stock.parsers import PayloadError, parse_security_payload
from get_stock.storage import (
    atomic_write_json,
    cleaned_data_path,
    pretty_data_path,
    sync_pretty_json,
)

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
STOCK_CODE_PATTERN = re.compile(r"^\d{6}$")


def as_bool(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CninfoBaseMixin:
    """Shared security resolution and request behavior for CNINFO spiders."""

    allowed_domains = ["www.cninfo.com.cn", "static.cninfo.com.cn", "api.cninfo.com.cn"]
    security_url = "https://www.cninfo.com.cn/new/information/topSearch/query"
    search_referer = (
        "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
    )

    def __init__(
        self,
        stock_code: str,
        save_raw: bool | str = False,
        pretty_json: bool | str = True,
        data_dir: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if not STOCK_CODE_PATTERN.fullmatch(stock_code):
            raise ValueError("stock_code must contain exactly six digits")

        self.stock_code = stock_code
        self.save_raw = as_bool(save_raw)
        self.pretty_json = as_bool(pretty_json)
        self.data_dir = str(Path(data_dir or "data").resolve())
        self.stock_dir = Path(self.data_dir) / "stocks" / self.stock_code
        self.raw_dir = self.stock_dir / "raw"
        self.security: dict[str, str] | None = None

    @property
    def request_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": self.search_referer,
            "Origin": "https://www.cninfo.com.cn",
            "X-Requested-With": "XMLHttpRequest",
        }

    async def start(self):
        yield FormRequest(
            url=self.security_url,
            method="POST",
            formdata={"keyWord": self.stock_code, "maxNum": "10", "plate": ""},
            headers=self.request_headers,
            callback=self.parse_security,
            meta={"expect_json": True, "request_kind": "security"},
        )

    def parse_security(self, response: Response):
        if self.save_raw:
            self._save_raw("security-response.json", response.body)
        try:
            security = parse_security_payload(response.body, self.stock_code)
        except PayloadError as exc:
            self._save_raw("security-error-response.txt", response.body)
            raise CloseSpider(reason=f"invalid_security_response: {exc}") from exc

        self.security = security
        security_path = cleaned_data_path(self.stock_dir, "security.json")
        atomic_write_json(
            security_path,
            {
                **security,
                "resolved_at": datetime.now(CHINA_TZ).isoformat(),
                "source_url": response.url,
            },
        )
        if self.pretty_json:
            sync_pretty_json(security_path, pretty_data_path(self.stock_dir, security_path))
        self.crawler.stats.set_value("get_stock/security_resolved", 1)
        yield from self.start_data_requests(security)

    def start_data_requests(self, security: dict[str, str]):
        raise NotImplementedError

    def _save_raw(self, filename: str, body: bytes) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.raw_dir / filename).write_bytes(body)

    def detail_referer(self, security: dict[str, str] | None = None) -> str:
        security = security or self.security
        if security is None:
            raise RuntimeError("security must be resolved first")
        return (
            "https://www.cninfo.com.cn/new/disclosure/stock"
            f"?orgId={security['org_id']}&stockCode={self.stock_code}"
        )
