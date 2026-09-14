from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from twisted.internet.defer import inlineCallbacks

from get_stock.acquisition.catalog import CRAWLER_REGISTRY
from get_stock.acquisition.schemas import AcquisitionJob


class ScrapyBatchRunner:
    """Run a validated batch with one Twisted reactor and sequential spiders."""

    def __call__(self, jobs: Sequence[AcquisitionJob], data_dir: Path) -> None:
        resolved = data_dir.resolve()
        settings = get_project_settings()
        settings.set("DATA_DIR", str(resolved), priority="cmdline")
        settings.set("FILES_STORE", str(resolved), priority="cmdline")
        process = CrawlerProcess(settings)

        @inlineCallbacks
        def crawl_sequentially():
            for job in jobs:
                registration = CRAWLER_REGISTRY[job.action]
                yield process.crawl(
                    registration.spider_class,
                    data_dir=str(resolved),
                    **job.kwargs,
                )

        crawl_sequentially()
        process.start()
