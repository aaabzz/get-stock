from pathlib import Path

from itemadapter import ItemAdapter
from scrapy import Request
from scrapy.pipelines.files import FilesPipeline

from get_stock.pdf_validation import validate_full_report_pdf


class CninfoFilesPipeline(FilesPipeline):
    def get_media_requests(self, item, info):
        adapter = ItemAdapter(item)
        return [
            Request(
                url,
                headers={
                    "Accept": "application/pdf,*/*",
                    "Referer": "https://www.cninfo.com.cn/",
                },
                meta={
                    "stock_code": adapter["stock_code"],
                    "announcement_id": adapter["announcement_id"],
                    "published_at": adapter["published_at"],
                    "document_type": adapter.get("document_type", "announcement"),
                    "document_role": adapter.get("document_role", "regular_announcement"),
                    "report_type": adapter.get("report_type"),
                    "report_period": adapter.get("report_period"),
                    "stock_name": adapter.get("stock_name", ""),
                    "download_timeout": 120,
                },
            )
            for url in adapter.get("file_urls", [])
        ]

    def file_path(self, request, response=None, info=None, *, item=None):
        year = request.meta["published_at"][:4]
        if request.meta["document_type"] == "financial_report":
            document_dir = f"reports/{request.meta['report_type'] or 'unknown'}/{year}"
        else:
            document_dir = f"announcements/{year}"
        return (
            f"stocks/{request.meta['stock_code']}/documents/{document_dir}/"
            f"{request.meta['announcement_id']}.pdf"
        )

    def item_completed(self, results, item, info):
        adapter = ItemAdapter(item)
        if not adapter.get("file_urls"):
            return item

        successful = [result for ok, result in results if ok]
        if not successful:
            adapter["download_status"] = "failed"
            self._mark_validation_failed(adapter, "download_failed")
            return item

        relative_path = successful[0]["path"]
        absolute_path = Path(info.spider.data_dir) / relative_path
        if not self._is_pdf(absolute_path):
            absolute_path.unlink(missing_ok=True)
            adapter["download_status"] = "invalid_pdf"
            self._mark_validation_failed(adapter, "invalid_pdf")
            return item

        adapter["local_path"] = str(absolute_path)
        adapter["download_status"] = "success"
        if adapter.get("document_role") == "full_report":
            validation = validate_full_report_pdf(
                absolute_path,
                stock_name=str(adapter.get("stock_name") or ""),
                report_type=str(adapter.get("report_type") or ""),
                report_period=str(adapter.get("report_period") or ""),
            )
            for key, value in validation.items():
                adapter[key] = value
        return item

    @staticmethod
    def _mark_validation_failed(adapter: ItemAdapter, reason: str) -> None:
        if adapter.get("document_role") != "full_report":
            return
        adapter["content_validation_status"] = "failed"
        adapter["analysis_eligible"] = False
        adapter["validation_errors"] = [reason]

    @staticmethod
    def _is_pdf(path: Path) -> bool:
        try:
            with path.open("rb") as stream:
                return stream.read(5) == b"%PDF-"
        except OSError:
            return False
