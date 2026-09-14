import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from get_stock.agent_config import (
    FINANCIAL_DATASET_FILES,
    MARKET_TRADING_DATASET_FILES,
)
from get_stock.financial_agent.loaders import (
    StructuredDataAccessError,
    StructuredFinancialDataLoader,
)
from get_stock.market_trading_agent import (
    MarketTradingAnalysisAgent,
    MarketTradingAnalysisTask,
    MarketTradingTaskConstraints,
    build_market_trading_graph,
)
from get_stock.market_trading_agent.catalog import TOPIC_DATASETS as MARKET_TOPICS
from get_stock.market_trading_agent.intent import parse_market_trading_intent
from get_stock.market_trading_agent.loaders import (
    MarketTradingDataAccessError,
    StructuredMarketTradingDataLoader,
)
from get_stock.market_trading_agent.schemas import (
    MarketTradingClaim,
    MarketTradingLLMAnalysis,
)
from get_stock.storage import atomic_write_json, atomic_write_json_lines


def _write_market_fixture(data_dir: Path, *, block_records: bool = True) -> None:
    stock_dir = data_dir / "stocks" / "000001"
    cleaned = stock_dir / "cleaned"
    state = stock_dir / "state"
    atomic_write_json(
        cleaned / "company_profile.json",
        {
            "stock_code": "000001",
            "stock_name": "示例公司",
            "industry_name": "示例行业",
        },
    )
    history = []
    margin = []
    start = date(2026, 1, 1)
    for index in range(12):
        trade_date = (start + timedelta(days=index)).isoformat()
        close = 10.0 + index * 0.1
        history.append(
            {
                "stock_code": "000001",
                "trade_date": trade_date,
                "open": close - 0.05,
                "close": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "volume": 1000 + index * 100,
            }
        )
        margin.append(
            {
                "stock_code": "000001",
                "trade_date": trade_date,
                "financing_balance": 1_000_000 + index * 20_000,
                "financing_buy_amount": 100_000 + index * 1_000,
                "securities_lending_remaining_volume": 10_000,
                "margin_balance": 1_100_000 + index * 20_000,
            }
        )
    atomic_write_json_lines(cleaned / "market_history.jsonl", history)
    atomic_write_json_lines(cleaned / "margin_trading.jsonl", margin)
    atomic_write_json(
        cleaned / "market_snapshot.json",
        {
            "stock_code": "000001",
            "stock_name": "示例公司",
            "quote_time": "2026-01-12 15:00:00",
            "last_price": 11.1,
            "turnover_rate_percent": 1.2,
            "pe_ttm": 12.5,
            "pb_ratio": 1.4,
            "total_market_cap": 100_000_000,
            "float_market_cap": 80_000_000,
        },
    )
    blocks = (
        [
            {
                "stock_code": "000001",
                "stock_name": "示例公司",
                "trade_date": "2026-01-10",
                "trade_price": 10.8,
                "trade_volume_10k": 20.0,
                "trade_amount_10k": 216.0,
                "buyer": "机构专用",
                "seller": "示例营业部",
            }
        ]
        if block_records
        else []
    )
    atomic_write_json_lines(cleaned / "block_trades.jsonl", blocks)
    atomic_write_json(
        state / "market_crawl_state.json",
        {
            "stock_code": "000001",
            "completed_datasets": ["history", "snapshot"],
            "failed_datasets": {},
            "record_counts": {"history": 12, "snapshot": 1},
        },
    )
    atomic_write_json(
        state / "trading_crawl_state.json",
        {
            "stock_code": "000001",
            "completed_datasets": ["margin_trading", "block_trades"],
            "failed_datasets": {},
            "record_counts": {
                "margin_trading": 12,
                "block_trades": len(blocks),
            },
        },
    )


def _task(
    *,
    topics: tuple[str, ...] = (
        "price_trend",
        "volatility",
        "liquidity",
        "price_volume",
        "valuation",
        "margin_activity",
        "block_trades",
    ),
    datasets: tuple[str, ...] | None = None,
    require_llm: bool = False,
) -> MarketTradingAnalysisTask:
    return MarketTradingAnalysisTask(
        task_id="market-task-1",
        stock_code="000001",
        topics=topics,
        as_of_date=date(2026, 1, 12),
        lookback_sessions=10,
        dataset_names=datasets
        or (
            "company_profile",
            "market_snapshot",
            "market_history",
            "margin_trading",
            "block_trades",
        ),
        constraints=MarketTradingTaskConstraints(require_llm=require_llm),
    )


def test_agent_dataset_whitelists_are_central_and_separate() -> None:
    assert "income_statements" in FINANCIAL_DATASET_FILES
    assert "income_statements" not in MARKET_TRADING_DATASET_FILES
    assert "market_history" in MARKET_TRADING_DATASET_FILES
    assert "market_history" not in FINANCIAL_DATASET_FILES


def test_both_loaders_reject_cross_agent_or_unknown_datasets(tmp_path) -> None:
    with pytest.raises(MarketTradingDataAccessError, match="not allowed"):
        StructuredMarketTradingDataLoader(tmp_path, "000001").load("income_statements")
    with pytest.raises(StructuredDataAccessError, match="not allowed"):
        StructuredFinancialDataLoader(tmp_path, "000001").load("market_history")


def test_market_intent_parser_is_only_a_supervisor_adapter() -> None:
    intent = parse_market_trading_intent("分析000001最近20个交易日的股价、波动和两融")

    assert intent.stock_code == "000001"
    assert intent.lookback_sessions == 20
    assert intent.topics == ("price_trend", "volatility", "margin_activity")


def test_agent_returns_all_deterministic_dimensions(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir)

    result = MarketTradingAnalysisAgent(data_dir).analyze(_task())

    assert result.status == "completed"
    assert result.llm_used is False
    assert set(result.dimensions) == set(_task().topics)
    assert result.data_freshness["market_history"]["status"] == "fresh"
    assert result.evidence
    assert all(item["allowed_claim_types"] for item in result.evidence)
    assert result.confidence == 0.9


def test_successful_empty_block_trade_query_is_a_completed_no_event_fact(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir, block_records=False)

    result = MarketTradingAnalysisAgent(data_dir).analyze(
        _task(topics=("block_trades",), datasets=("company_profile", "block_trades"))
    )

    assert result.status == "completed"
    assert result.dimensions["block_trades"]["state"] == "no_events"
    assert result.evidence[0]["value"] == 0


def test_missing_data_returns_insufficient_without_calling_llm(tmp_path) -> None:
    called = False

    def reasoner(_packet):
        nonlocal called
        called = True
        raise AssertionError("LLM must not run without analyzable data")

    result = MarketTradingAnalysisAgent(tmp_path / "data", reasoner=reasoner).analyze(
        _task(
            topics=("price_trend",),
            datasets=("company_profile", "market_history"),
            require_llm=True,
        )
    )

    assert result.status == "insufficient_data"
    assert result.llm_used is False
    assert called is False
    assert result.missing_data[0].recommended_action == "crawl_market"


def test_partial_data_can_still_use_validated_llm_output(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir)

    def reasoner(packet):
        evidence = next(
            item for item in packet["evidence"] if "price_trend" in item["allowed_claim_types"]
        )
        return MarketTradingLLMAnalysis(
            market_state_summary="仅能完成价格趋势分析。",
            trend_assessments=[
                MarketTradingClaim(
                    claim="区间价格上涨。",
                    topic="price_trend",
                    assessment="positive",
                    evidence_ids=[evidence["evidence_id"]],
                    confidence=0.9,
                )
            ],
        )

    result = MarketTradingAnalysisAgent(data_dir, reasoner=reasoner).analyze(
        _task(
            topics=("price_trend", "valuation"),
            datasets=("company_profile", "market_history"),
            require_llm=True,
        )
    )

    assert result.status == "partial"
    assert result.llm_used is True
    assert set(result.dimensions) == {"price_trend"}


def test_cross_topic_evidence_use_falls_back_to_deterministic_analysis(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir)

    def reasoner(packet):
        price_evidence = next(
            item for item in packet["evidence"] if "price_trend" in item["allowed_claim_types"]
        )
        return MarketTradingLLMAnalysis(
            market_state_summary="无效输出",
            notable_activity=[
                MarketTradingClaim(
                    claim="融资余额增长。",
                    topic="margin_activity",
                    assessment="neutral",
                    evidence_ids=[price_evidence["evidence_id"]],
                    confidence=0.8,
                )
            ],
        )

    result = MarketTradingAnalysisAgent(data_dir, reasoner=reasoner).analyze(
        _task(topics=("price_trend", "margin_activity"))
    )

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.evidence
    assert any("已降级为确定性分析" in item for item in result.limitations)


def test_market_claim_schema_exposes_topic_enum_to_function_calling() -> None:
    schema = MarketTradingLLMAnalysis.model_json_schema()

    topic_schema = schema["$defs"]["MarketTradingClaim"]["properties"]["topic"]
    assert set(topic_schema["enum"]) == set(MARKET_TOPICS)


def test_nonstandard_market_topic_from_llm_uses_deterministic_fallback(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir)

    def reasoner(_packet):
        return {
            "market_state_summary": "invalid model output",
            "notable_activity": [
                {
                    "claim": "invalid alias",
                    "topic": "market_activity",
                    "assessment": "neutral",
                    "evidence_ids": [],
                    "confidence": 0.5,
                }
            ],
        }

    result = MarketTradingAnalysisAgent(data_dir, reasoner=reasoner).analyze(
        _task(topics=("price_trend",), require_llm=True)
    )

    assert result.status == "completed"
    assert result.llm_used is False
    assert result.trend_assessments
    assert any("market_activity" in item for item in result.limitations)


def test_market_graph_runs_when_dependency_is_installed(tmp_path) -> None:
    pytest.importorskip("langgraph")
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir)
    graph = build_market_trading_graph(MarketTradingAnalysisAgent(data_dir))

    state = graph.invoke({"task": _task(topics=("price_trend",)).model_dump(mode="json")})

    assert state["result"]["agent"] == "market_trading"
    assert state["result"]["status"] == "completed"


def test_market_result_is_json_serializable(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _write_market_fixture(data_dir)
    result = MarketTradingAnalysisAgent(data_dir).analyze(
        _task(topics=("margin_activity", "block_trades"))
    )

    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
