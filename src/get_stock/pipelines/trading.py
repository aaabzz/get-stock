from datetime import datetime, timedelta, timezone
from pathlib import Path

from itemadapter import ItemAdapter

from get_stock.storage import (
    atomic_write_json,
    atomic_write_json_lines,
    cleaned_data_path,
    pretty_data_path,
    state_data_path,
    sync_pretty_json,
)

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class TradingDataPipeline:
    filenames = {
        "margin_trading": "margin_trading.jsonl",
        "block_trades": "block_trades.jsonl",
    }

    def open_spider(self, spider) -> None:
        self.stock_dir = Path(spider.data_dir) / "stocks" / spider.stock_code
        self.datasets: dict[str, int] = {}

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        dataset = str(adapter["dataset"])
        records = list(adapter.get("records", []))
        filename = self.filenames.get(dataset)
        if filename is None:
            raise ValueError(f"unsupported trading dataset: {dataset}")
        enriched = (
            {
                **record,
                "source_url": adapter["source_url"],
                "crawled_at": adapter["crawled_at"],
            }
            for record in records
        )
        atomic_write_json_lines(cleaned_data_path(self.stock_dir, filename), enriched)

        self.datasets[dataset] = len(records)
        spider.crawler.stats.inc_value(f"get_stock/trading_written/{dataset}", len(records))
        return item

    def close_spider(self, spider) -> None:
        if spider.pretty_json:
            for filename in self.filenames.values():
                source = cleaned_data_path(self.stock_dir, filename)
                if source.is_file():
                    sync_pretty_json(source, pretty_data_path(self.stock_dir, source))

        atomic_write_json(
            state_data_path(self.stock_dir, "trading_crawl_state.json"),
            {
                "stock_code": spider.stock_code,
                "completed_datasets": sorted(spider.completed_datasets),
                "failed_datasets": spider.failed_datasets,
                "record_counts": self.datasets,
                "updated_at": datetime.now(CHINA_TZ).isoformat(),
            },
        )
