from datetime import datetime, timedelta, timezone
from pathlib import Path

from itemadapter import ItemAdapter

from get_stock.storage import (
    append_json_line,
    atomic_write_json,
    atomic_write_json_lines,
    cleaned_data_path,
    iter_json_lines,
    load_announcement_ids,
    pretty_data_path,
    state_data_path,
    sync_pretty_json,
)

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class JsonLinesPipeline:
    def open_spider(self, spider) -> None:
        self.stock_dir = Path(spider.data_dir) / "stocks" / spider.stock_code
        self.output_path = cleaned_data_path(self.stock_dir, "announcements.jsonl")
        self.written_ids = load_announcement_ids(self.output_path)

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        announcement_id = str(adapter["announcement_id"])
        if announcement_id in self.written_ids:
            if adapter.get("download_status") == "success" and adapter.get("local_path"):
                replacement = {
                    key: value
                    for key, value in adapter.asdict().items()
                    if key not in {"file_urls", "files"}
                }
                records = list(iter_json_lines(self.output_path))
                updated = False
                for index, existing in enumerate(records):
                    if str(existing.get("announcement_id") or "") == announcement_id:
                        records[index] = {**existing, **replacement}
                        updated = True
                if updated:
                    atomic_write_json_lines(self.output_path, records)
                    spider.crawler.stats.inc_value("get_stock/updated_downloads", 1)
                    return item
            spider.crawler.stats.inc_value("get_stock/pipeline_duplicates", 1)
            return item

        record = {
            key: value
            for key, value in adapter.asdict().items()
            if key not in {"file_urls", "files"}
        }
        append_json_line(self.output_path, record)
        self.written_ids.add(announcement_id)
        spider.crawler.stats.inc_value("get_stock/written", 1)
        return item

    def close_spider(self, spider) -> None:
        if spider.pretty_json and self.output_path.is_file():
            sync_pretty_json(self.output_path, pretty_data_path(self.stock_dir, self.output_path))

        stats = spider.crawler.stats.get_stats()
        state = {
            "stock_code": spider.stock_code,
            "start_date": spider.start_date.isoformat(),
            "end_date": spider.end_date.isoformat(),
            "last_successful_page": spider.last_successful_page,
            "finish_reason": stats.get("finish_reason", "unknown"),
            "pages": stats.get("get_stock/pages", 0),
            "total_reported": stats.get("get_stock/total_reported", 0),
            "reports_enabled": getattr(spider, "reports", True),
            "report_scope": getattr(spider, "report_scope", "all"),
            "regular_announcements_enabled": getattr(spider, "regular_announcements", True),
            "filtered_reports": stats.get("get_stock/filtered/reports", 0),
            "filtered_regular_announcements": stats.get(
                "get_stock/filtered/regular_announcements", 0
            ),
            "new_announcements": stats.get("get_stock/new_announcements", 0),
            "duplicates": stats.get("get_stock/duplicates", 0),
            "retry_downloads": stats.get("get_stock/retry_downloads", 0),
            "updated_downloads": stats.get("get_stock/updated_downloads", 0),
            "max_documents": getattr(spider, "max_documents", 0),
            "written": stats.get("get_stock/written", 0),
            "updated_at": datetime.now(CHINA_TZ).isoformat(),
        }
        atomic_write_json(state_data_path(self.stock_dir, "crawl_state.json"), state)
