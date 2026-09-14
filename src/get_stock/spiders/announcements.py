from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import FormRequest, Response

from get_stock.items import AnnouncementItem
from get_stock.parsers import PayloadError, parse_announcement_payload
from get_stock.spiders.base import CHINA_TZ, CninfoBaseMixin, as_bool
from get_stock.storage import cleaned_data_path, iter_json_lines, load_announcement_ids

REPORT_SCOPES = {"all", "full", "summary", "financial-statements", "assurance"}


class CninfoAnnouncementSpider(CninfoBaseMixin, scrapy.Spider):
    name = "cninfo_announcements"
    announcements_url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    page_size = 30

    def __init__(
        self,
        stock_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        category: str = "",
        max_pages: int | str = 20,
        max_documents: int | str = 0,
        download_pdf: bool | str = False,
        reports: bool | str = True,
        regular_announcements: bool | str = True,
        report_scope: str = "all",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(stock_code, *args, **kwargs)
        today = date.today()
        self.start_date = self._parse_date(start_date or today.replace(day=1).isoformat())
        self.end_date = self._parse_date(end_date or today.isoformat())
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be later than end_date")

        self.category = category.strip()
        self.max_pages = max(1, int(max_pages))
        self.max_documents = max(0, int(max_documents))
        self.download_pdf = as_bool(download_pdf)
        self.reports = as_bool(reports)
        self.regular_announcements = as_bool(regular_announcements)
        self.report_scope = report_scope.strip().lower().replace("_", "-")
        if self.report_scope not in REPORT_SCOPES:
            choices = ", ".join(sorted(REPORT_SCOPES))
            raise ValueError(f"invalid report_scope {report_scope!r}; expected one of: {choices}")
        if not self.reports and not self.regular_announcements:
            raise ValueError("reports and regular_announcements cannot both be disabled")
        self.announcements_path = cleaned_data_path(self.stock_dir, "announcements.jsonl")
        self.existing_ids = load_announcement_ids(self.announcements_path)
        self.existing_records = {
            str(record.get("announcement_id")): record
            for record in iter_json_lines(self.announcements_path)
            if record.get("announcement_id")
        }
        self.seen_ids = set(self.existing_ids)
        self.scheduled_download_ids: set[str] = set()
        self.selected_document_count = 0
        self.last_successful_page = 0

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc

    def start_data_requests(self, security: dict[str, str]):
        yield self._announcement_request(page=1)

    def parse_announcements(self, response: Response):
        if self.security is None:
            raise CloseSpider(reason="security_not_resolved")

        page = int(response.meta["page"])
        if self.save_raw:
            self._save_raw(f"announcements-page-{page:04d}.json", response.body)

        crawled_at = datetime.now(CHINA_TZ).isoformat()
        try:
            records, total_records = parse_announcement_payload(
                response.body,
                self.security,
                crawled_at,
            )
        except PayloadError as exc:
            self._save_raw(f"announcements-error-page-{page:04d}.txt", response.body)
            raise CloseSpider(reason=f"invalid_announcement_response: {exc}") from exc

        self.last_successful_page = page
        self.crawler.stats.inc_value("get_stock/pages", 1)
        self.crawler.stats.set_value("get_stock/total_reported", total_records)

        for record in records:
            if not self._should_include(record):
                filtered_kind = (
                    "reports"
                    if record["document_type"] == "financial_report"
                    else "regular_announcements"
                )
                self.crawler.stats.inc_value(f"get_stock/filtered/{filtered_kind}", 1)
                continue

            announcement_id = record["announcement_id"]
            if announcement_id in self.seen_ids:
                existing = self.existing_records.get(announcement_id, {})
                retry_download = (
                    self.download_pdf
                    and announcement_id not in self.scheduled_download_ids
                    and not self._has_downloaded_file(existing)
                )
                if not retry_download:
                    self.crawler.stats.inc_value("get_stock/duplicates", 1)
                    continue
                self.scheduled_download_ids.add(announcement_id)
                self.crawler.stats.inc_value("get_stock/retry_downloads", 1)
            else:
                self.seen_ids.add(announcement_id)

            if self.max_documents and self.selected_document_count >= self.max_documents:
                self.crawler.stats.inc_value("get_stock/filtered/document_limit", 1)
                continue
            self.selected_document_count += 1

            if self.download_pdf and record["pdf_url"]:
                record["file_urls"] = [record["pdf_url"]]
                record["download_status"] = "pending"
            else:
                record["file_urls"] = []
                record["download_status"] = "not_requested"
                if record["document_role"] == "full_report":
                    record["content_validation_status"] = "not_run"

            if announcement_id not in self.existing_ids:
                self.crawler.stats.inc_value("get_stock/new_announcements", 1)
            yield AnnouncementItem(record)

        total_pages = math.ceil(total_records / self.page_size) if total_records else 0
        page_limit = min(total_pages, self.max_pages)
        limit_reached = self.max_documents and self.selected_document_count >= self.max_documents
        if page < page_limit and not limit_reached:
            yield self._announcement_request(page=page + 1)

    def _has_downloaded_file(self, record: dict[str, Any]) -> bool:
        value = record.get("local_path")
        if not value:
            return False
        supplied = Path(str(value))
        candidates = [supplied] if supplied.is_absolute() else [
            Path.cwd() / supplied,
            Path(self.data_dir) / supplied,
        ]
        return any(candidate.is_file() for candidate in candidates)

    def _should_include(self, record: dict[str, Any]) -> bool:
        if record.get("document_type") == "financial_report":
            return self.reports and self._matches_report_scope(record)
        return self.regular_announcements

    def _matches_report_scope(self, record: dict[str, Any]) -> bool:
        role = record.get("document_role")
        if self.report_scope == "all":
            return True
        if self.report_scope == "full":
            return role == "full_report"
        if self.report_scope == "summary":
            return role == "report_summary"
        if self.report_scope == "financial-statements":
            return role == "financial_statements"
        return role in {"review_report", "audit_report"}

    def _announcement_request(self, page: int) -> FormRequest:
        if self.security is None:
            raise RuntimeError("security must be resolved before requesting announcements")
        return FormRequest(
            url=self.announcements_url,
            method="POST",
            formdata={
                "pageNum": str(page),
                "pageSize": str(self.page_size),
                "column": self.security["column"],
                "tabName": "fulltext",
                "plate": "",
                "stock": f"{self.stock_code},{self.security['org_id']}",
                "searchkey": "",
                "secid": "",
                "category": self.category,
                "trade": "",
                "seDate": f"{self.start_date.isoformat()}~{self.end_date.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
            headers=self.request_headers,
            callback=self.parse_announcements,
            meta={
                "expect_json": True,
                "request_kind": "announcements",
                "page": page,
            },
        )
