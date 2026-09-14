import json
from datetime import date
from types import SimpleNamespace

import pytest

from get_stock.pipelines.company import CompanyDataPipeline
from get_stock.pipelines.financials import FinancialDataPipeline
from get_stock.pipelines.jsonl import JsonLinesPipeline
from get_stock.pipelines.market import MarketDataPipeline
from get_stock.pipelines.shareholders import ShareholderDataPipeline
from get_stock.pipelines.trading import TradingDataPipeline
from get_stock.storage import (
    append_json_line,
    atomic_write_json,
    cleaned_data_path,
    pretty_data_path,
    state_data_path,
)


class FakeStats:
    def get_stats(self) -> dict:
        return {}

    def inc_value(self, key, count=1) -> None:
        pass


@pytest.mark.parametrize("enabled", [True, False])
def test_announcement_pipeline_honors_pretty_json_switch(enabled, tmp_path) -> None:
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        pretty_json=enabled,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 29),
        last_successful_page=1,
        crawler=SimpleNamespace(stats=FakeStats()),
    )
    pipeline = JsonLinesPipeline()
    pipeline.open_spider(spider)
    append_json_line(pipeline.output_path, {"announcement_id": "1"})

    pipeline.close_spider(spider)

    pretty_path = pretty_data_path(pipeline.stock_dir, pipeline.output_path)
    assert pretty_path.exists() is enabled
    assert state_data_path(pipeline.stock_dir, "crawl_state.json").is_file()


@pytest.mark.parametrize("enabled", [True, False])
def test_company_pipeline_honors_pretty_json_switch(enabled, tmp_path) -> None:
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        pretty_json=enabled,
        completed_datasets={"executives"},
    )
    pipeline = CompanyDataPipeline()
    pipeline.open_spider(spider)
    profile_source = cleaned_data_path(pipeline.stock_dir, "company_profile.json")
    executives_source = cleaned_data_path(pipeline.stock_dir, "executives.jsonl")
    atomic_write_json(profile_source, {"company_name": "测试公司"})
    append_json_line(executives_source, {"name": "测试人员"})

    pipeline.close_spider(spider)

    assert pretty_data_path(pipeline.stock_dir, profile_source).exists() is enabled
    assert pretty_data_path(pipeline.stock_dir, executives_source).exists() is enabled


def test_company_pipeline_adds_industry_observation_date(tmp_path) -> None:
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        crawler=SimpleNamespace(stats=FakeStats()),
    )
    pipeline = CompanyDataPipeline()
    pipeline.open_spider(spider)

    pipeline.process_item(
        {
            "dataset": "profile",
            "records": [
                {
                    "stock_code": "000001",
                    "industry_name": "货币金融服务",
                    "industry_source": "cninfo_company_profile",
                    "industry_standard": None,
                }
            ],
            "source_url": "https://example.test/company",
            "crawled_at": "2026-08-31T10:26:08+08:00",
        },
        spider,
    )

    profile_path = cleaned_data_path(pipeline.stock_dir, "company_profile.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["industry_name"] == "货币金融服务"
    assert profile["industry_as_of"] == "2026-08-31"


@pytest.mark.parametrize("enabled", [True, False])
def test_market_pipeline_honors_pretty_json_switch(enabled, tmp_path) -> None:
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        pretty_json=enabled,
        completed_datasets={"history"},
        failed_datasets={},
    )
    pipeline = MarketDataPipeline()
    pipeline.open_spider(spider)
    snapshot_source = cleaned_data_path(pipeline.stock_dir, "market_snapshot.json")
    history_source = cleaned_data_path(pipeline.stock_dir, "market_history.jsonl")
    atomic_write_json(snapshot_source, {"last_price": 10.5})
    append_json_line(history_source, {"trade_date": "2026-08-28"})

    pipeline.close_spider(spider)

    assert pretty_data_path(pipeline.stock_dir, snapshot_source).exists() is enabled
    assert pretty_data_path(pipeline.stock_dir, history_source).exists() is enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_financial_pipeline_mirrors_summary_json(enabled, tmp_path) -> None:
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        pretty_json=enabled,
        completed_datasets={"summary"},
        failed_datasets={},
    )
    pipeline = FinancialDataPipeline()
    pipeline.open_spider(spider)
    source = cleaned_data_path(pipeline.stock_dir, "financial_summary.json")
    atomic_write_json(source, {"revenue": 100})

    pipeline.close_spider(spider)

    assert pretty_data_path(pipeline.stock_dir, source).exists() is enabled


@pytest.mark.parametrize(
    ("pipeline_class", "filename", "dataset"),
    [
        (FinancialDataPipeline, "financial_indicators.jsonl", "indicators"),
        (ShareholderDataPipeline, "stock_structure.jsonl", "stock_structure"),
        (ShareholderDataPipeline, "fund_holdings.jsonl", "fund_holdings"),
        (TradingDataPipeline, "margin_trading.jsonl", "margin_trading"),
        (TradingDataPipeline, "block_trades.jsonl", "block_trades"),
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_new_dataset_pipelines_honor_pretty_json_switch(
    pipeline_class,
    filename,
    dataset,
    enabled,
    tmp_path,
) -> None:
    spider = SimpleNamespace(
        data_dir=str(tmp_path),
        stock_code="000001",
        pretty_json=enabled,
        completed_datasets={dataset},
        failed_datasets={},
    )
    pipeline = pipeline_class()
    pipeline.open_spider(spider)
    source = cleaned_data_path(pipeline.stock_dir, filename)
    append_json_line(source, {"stock_code": "000001"})

    pipeline.close_spider(spider)

    assert pretty_data_path(pipeline.stock_dir, source).exists() is enabled
